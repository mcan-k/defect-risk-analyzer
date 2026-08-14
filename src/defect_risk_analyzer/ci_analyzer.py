"""
CI Analyzer — Headless CLI script for GitHub Actions PR risk analysis.

Takes git diff as input, identifies affected modules, runs risk analysis,
and outputs a markdown report suitable for posting as a GitHub PR comment.

Usage:
    python ci_analyzer.py --diff "git diff output" --output report.md
    python ci_analyzer.py --diff-file changes.diff --output report.md

No API server needed — calls analysis logic directly.
"""

import argparse
import functools
import logging
import re
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath

from defect_risk_analyzer import config
from defect_risk_analyzer.core import scoring
from defect_risk_analyzer.jira_client import load_bugs_from_file
from defect_risk_analyzer.services.analysis_service import AnalysisService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Diff Parser
# =============================================================================

def extract_changed_files(diff_text: str) -> list[str]:
    """
    Extract changed file paths from git diff output.

    Args:
        diff_text: Raw git diff output.

    Returns:
        List of changed file paths.
    """
    files = set()

    # Match "diff --git a/path b/path" lines
    pattern = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)
    for match in pattern.finditer(diff_text):
        files.add(match.group(2))

    # Also match "+++ b/path" lines
    pattern2 = re.compile(r"^\+\+\+ b/(.+?)$", re.MULTILINE)
    for match in pattern2.finditer(diff_text):
        if match.group(1) != "/dev/null":
            files.add(match.group(1))

    return sorted(files)


# =============================================================================
# Module Inference
# =============================================================================
# Inference runs in two layers, and both are load-bearing. See
# tests/test_ci_analyzer_inference.py for the production measurement (PR #3)
# that produced them.
#
# Layer 1 drops paths that carry no product behaviour. It is the only thing
# that stops docs/probe/auth-probe.md: "auth" is a genuine path token there,
# so no amount of token-boundary work removes it.
#
# Layer 2 matches keywords at token boundaries on whatever survives layer 1.
# It is what stops "ui" inside "requirements".

# A denylist, not an allowlist: an extension we failed to enumerate is likelier
# to be source we did not think of than documentation. A missed module produces
# an honest "no mapping" report; a spurious one fabricates a risk score against
# a module the diff never touched. The first failure mode is the cheap one.
EXCLUDED_DIRS = frozenset({"docs", "doc", ".github"})

EXCLUDED_SUFFIXES = frozenset({
    ".md", ".rst", ".adoc",                             # documentation
    ".txt",                                             # requirements*.txt et al
    ".cfg", ".toml", ".ini",                            # project configuration
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",    # assets
    ".webp", ".pdf",
})

# Path token -> module name. Faz 4(b) Bölüm B moves this to module-map.json;
# the matching rule below is what B has to preserve, not the literal.
MODULE_KEYWORDS: dict[str, str] = {
    "auth": "Authentication",
    "authentication": "Authentication",
    "login": "Authentication",
    "session": "Authentication",
    "token": "Authentication",
    "password": "Authentication",
    "payment": "Payment",
    "billing": "Payment",
    "invoice": "Payment",
    "checkout": "Payment",
    "cart": "Frontend",
    "ui": "Frontend",
    "frontend": "Frontend",
    "component": "Frontend",
    "view": "Frontend",
    "template": "Frontend",
    "report": "Reporting",
    "reporting": "Reporting",
    "export": "Reporting",
    "dashboard": "Reporting",
    "analytics": "Reporting",
    "inventory": "Inventory",
    "stock": "Inventory",
    "warehouse": "Inventory",
    "notification": "Notifications",
    "email": "Notifications",
    "sms": "Notifications",
    "push": "Notifications",
    "api": "API",
    "endpoint": "API",
    "route": "API",
    "database": "Database",
    "migration": "Database",
    "model": "Database",
    "schema": "Database",
}

# Separators between path tokens: "/", "_", "-", "." and anything else that is
# not alphanumeric.
_TOKEN_SEPARATORS = re.compile(r"[^a-z0-9]+")


# =============================================================================
# Path patterns
# =============================================================================
# The matching rule for module-map.json, hand-rolled because every standard
# library candidate is wrong here in a way that stays invisible until it
# produces a bad PR comment. See tests/test_ci_analyzer_inference.py
# ("Pattern semantics") for the rejected alternatives and the pinned rules.
#
# Paths are matched as raw strings. Git emits POSIX separators on every
# platform, and routing a path through Path() would reintroduce "\" and
# platform-dependent case folding into a tool whose output goes into a PR
# comment — a verdict that differs by runner is worse than one that is wrong
# consistently.

@functools.cache
def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile a path glob into an anchored regex.

    "*" and "?" are segment-local; "**" is a whole segment meaning "zero or
    more segments". Everything else is literal. Cached because the same handful
    of patterns is tested against every changed file.
    """
    segments = pattern.split("/")
    parts: list[str] = []

    for index, segment in enumerate(segments):
        is_last = index == len(segments) - 1

        if segment == "**":
            # Trailing "**" swallows the rest; in the middle it consumes whole
            # segments *including* their separator, which is what lets
            # "**/*.md" match README.md with no directory at all.
            parts.append(".*" if is_last else "(?:[^/]+/)*")
            continue

        parts.append(
            "".join(
                "[^/]*" if char == "*" else "[^/]" if char == "?" else re.escape(char)
                for char in segment
            )
        )
        if not is_last:
            parts.append("/")

    return re.compile("".join(parts))


def _matches(pattern: str, file_path: str) -> bool:
    """True if `pattern` matches the whole of `file_path`.

    fullmatch, not match: a pattern names a path from the repository root. The
    unanchored alternative is what makes pathlib.PurePath.match claim
    src/auth/login.py for the pattern "auth/**".
    """
    return _pattern_to_regex(pattern).fullmatch(file_path) is not None


def select_analyzable_files(changed_files: list[str]) -> list[str]:
    """
    Layer 1 — drop paths that cannot carry product behaviour.

    Documentation, dependency lists, project configuration and binary assets
    never reach module inference. A module name appearing inside one of them is
    a coincidence, not a signal.

    Args:
        changed_files: All file paths from the diff.

    Returns:
        The subset worth analyzing, in the order given.
    """
    analyzable = []

    for file_path in changed_files:
        path = PurePosixPath(file_path)

        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        # parts[:-1] is the directory chain — a file literally named "docs" is
        # not the same thing as a file inside docs/.
        if any(part in EXCLUDED_DIRS for part in path.parts[:-1]):
            continue

        analyzable.append(file_path)

    return analyzable


def _path_tokens(file_path: str) -> set[str]:
    """Split a path into lowercase tokens, dropping the file extension.

    The suffix names a file format, not a product module, so it is discarded
    before splitting — otherwise "form.ui" and "main.py" would contribute "ui"
    and "py" on equal footing.
    """
    path = PurePosixPath(file_path)
    parts = [*path.parts[:-1], path.stem]

    return {
        token
        for part in parts
        for token in _TOKEN_SEPARATORS.split(part.lower())
        if token
    }


def _matched_token(keyword: str, tokens: set[str]) -> str | None:
    """The token that matched `keyword`, as it appears in the path, or None.

    Exact token or its regular plural. Prefix matching would let "pay" match
    "payload" — a narrower copy of the bug being fixed — while exact-only would
    drop "payments", "migrations", "models", which is how those directories are
    ordinarily named.

    The token is returned rather than the keyword so the report can quote text
    that is actually in the path, which a reader can check by eye.
    """
    if keyword in tokens:
        return keyword

    plural = f"{keyword}s"
    if plural in tokens:
        return plural

    return None


def infer_module_provenance(changed_files: list[str]) -> dict[str, list[tuple[str, str]]]:
    """
    Infer affected modules, keeping the evidence for each one.

    Args:
        changed_files: All file paths from the diff.

    Returns:
        Module name -> sorted (file_path, matched_token) pairs. Empty dict when
        nothing matched.

    The evidence is printed next to the risk table so a reader can see *why* a
    module was named. Some of those reasons do not survive inspection:
    tests/test_ci_analyzer_report.py matches the token "report" and is credited
    to Reporting, which has real bug history and therefore gets a real score.
    Making that visible is the point of this function — narrowing the directory
    scope is Bölüm B's decision, not this one's.
    """
    provenance: dict[str, set[tuple[str, str]]] = {}

    for file_path in select_analyzable_files(changed_files):
        tokens = _path_tokens(file_path)

        for keyword, module in MODULE_KEYWORDS.items():
            matched = _matched_token(keyword, tokens)
            if matched is not None:
                # No `break`: a path that names three modules affects three
                # modules. Stopping at the first hit made dictionary insertion
                # order decide the answer, silently.
                provenance.setdefault(module, set()).add((file_path, matched))

    return {module: sorted(pairs) for module, pairs in sorted(provenance.items())}


def infer_modules_from_files(changed_files: list[str]) -> list[str]:
    """
    Infer affected modules from changed file paths.

    Returns:
        Sorted module names, or an empty list when nothing matched. Empty means
        "no mapping could be made" — it is NOT the same as "this module has no
        recorded defects", and generate_risk_report says which of the two it is
        rather than inventing a "General" module that no bug is filed against.
    """
    return sorted(infer_module_provenance(changed_files))


# =============================================================================
# Report Generator
# =============================================================================

def generate_risk_report(
    analyzer: AnalysisService,
    changed_files: list[str],
    affected_modules: list[str],
    *,
    analyzed_files: list[str] | None = None,
    provenance: dict[str, list[tuple[str, str]]] | None = None,
    now: datetime | None = None,
) -> str:
    """
    Generate a markdown risk report for a PR.

    Three outcomes are reported distinctly, because conflating them is what
    made the PR #3 probe print "LOW RISK" for a diff it had not assessed:

        module matched, history exists  -> a scored row in the risk table
        module matched, no history      -> named, but no row and no score
        nothing matched                 -> NOT ASSESSED, and no verdict at all

    Args:
        analyzer: Initialized AnalysisService with loaded bugs.
        changed_files: List of changed file paths.
        affected_modules: Inferred module names. Empty means nothing matched.
        analyzed_files: The subset of changed_files that reached inference, from
            select_analyzable_files. Used only for the "N skipped" count, which
            is what tells a reader why a docs-only PR matched nothing.
        provenance: Module -> (file, token) evidence from
            infer_module_provenance. Omitted means the section is not printed.
        now: Timestamp for the report header. Defaults to the current time.
            Passing it explicitly makes the output reproducible, which is what
            lets a test compare two reports for equality.

    Returns:
        Markdown-formatted report string.
    """
    # Resolved here rather than in the signature default, which would freeze the
    # value at import time. Same reasoning as core/scoring.py:92-94.
    now = now or datetime.now()

    module_stats = analyzer.calculate_module_stats()

    # A module is scored only if the bug history actually knows it. The rest are
    # named separately — being unable to score a module is not a low score.
    scored = [m for m in affected_modules if module_stats.get(m)]
    unscored = [m for m in affected_modules if not module_stats.get(m)]

    report_lines = []
    report_lines.append("# 🔍 Defect Risk Analysis Report")
    report_lines.append("")
    report_lines.append(f"**Generated:** {now.strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"**Changed Files:** {len(changed_files)}")

    if analyzed_files is not None:
        skipped = len(changed_files) - len(analyzed_files)
        line = f"**Analyzed Files:** {len(analyzed_files)}"
        if skipped:
            line += f"  ({skipped} skipped: documentation, config or asset)"
        report_lines.append(line)

    modules_line = ", ".join(affected_modules) if affected_modules else "— none matched"
    report_lines.append(f"**Affected Modules:** {modules_line}")
    report_lines.append("")

    max_risk = 0
    max_risk_module = ""

    # Only scored modules get a table. A row reading "N/A | No Data | 0 | 0" said
    # nothing except that the tool had been asked a question it could not answer.
    if scored:
        report_lines.append("## Risk Summary")
        report_lines.append("")
        report_lines.append(
            "| Module | Risk Score | Risk Level | Total Bugs | Open Bugs | Trend |"
        )
        report_lines.append(
            "|--------|-----------|------------|------------|-----------|-------|"
        )

        for module in scored:
            stats = module_stats[module]
            score = analyzer.calculate_risk_score(module, stats)
            level = scoring.get_risk_level(score)
            total = stats.get("total_bugs", 0)
            open_bugs = stats.get("open_bugs", 0)
            trend = stats.get("trend", "stable")

            emoji = {
                "CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢",
            }.get(level, "⚪")
            trend_emoji = {
                "increasing": "📈", "decreasing": "📉", "stable": "➡️",
            }.get(trend, "➡️")

            report_lines.append(
                f"| {module} | {score}/100 | {emoji} {level} | {total} "
                f"| {open_bugs} | {trend_emoji} {trend} |"
            )

            if score > max_risk:
                max_risk = score
                max_risk_module = module

        report_lines.append("")

    if unscored:
        report_lines.append(f"**Matched, no historical data:** {', '.join(unscored)}")
        report_lines.append("")
        report_lines.append(
            "*A path token named these modules, but the bug history has no record "
            "of them, so no risk was calculated.*"
        )
        report_lines.append("")

    if provenance:
        report_lines.append("## Why these modules")
        report_lines.append("")
        for module in sorted(provenance):
            pairs = provenance[module]
            first_file, first_token = pairs[0]
            others = len({path for path, _ in pairs}) - 1
            more = f" (+{others} more file{'s' if others > 1 else ''})" if others else ""
            report_lines.append(
                f"- **{module}** ← token `{first_token}` in `{first_file}`{more}"
            )
        report_lines.append("")

    # Overall verdict. Computed from the scored modules only — an unscored module
    # must not drag the verdict down to LOW, which is a claim about risk rather
    # than an admission that none was measured.
    if not scored:
        if unscored:
            named = ", ".join(unscored)
            report_lines.append(
                f"### ⚪ NOT ASSESSED — {named} matched, but the bug history has "
                "no record of them."
            )
        else:
            report_lines.append(
                "### ⚪ NOT ASSESSED — changed files did not map to any known module."
            )
        report_lines.append("")
        report_lines.append(
            "**Recommendation:** Risk was not assessed; review the change on its "
            "own merits."
        )
    elif scoring.get_risk_level(max_risk) == "CRITICAL":
        report_lines.append(
            f"### ⚠️ CRITICAL RISK — `{max_risk_module}` module requires "
            "immediate attention!"
        )
        report_lines.append("")
        report_lines.append(
            "**Recommendation:** Request thorough code review and additional QA "
            "testing before merge."
        )
    elif scoring.get_risk_level(max_risk) == "HIGH":
        report_lines.append(
            f"### 🟠 HIGH RISK — `{max_risk_module}` module has elevated defect density."
        )
        report_lines.append("")
        report_lines.append(
            "**Recommendation:** Ensure targeted testing for the affected module."
        )
    elif scoring.get_risk_level(max_risk) == "MEDIUM":
        report_lines.append("### 🟡 MEDIUM RISK — Standard review recommended.")
        report_lines.append("")
        report_lines.append(
            "**Recommendation:** Follow normal review process with attention to "
            "edge cases."
        )
    else:
        report_lines.append("### 🟢 LOW RISK — No significant defect patterns detected.")
        report_lines.append("")
        report_lines.append("**Recommendation:** Standard review is sufficient.")

    # Changed files section
    report_lines.append("")
    report_lines.append("## Changed Files")
    report_lines.append("")
    for f in changed_files[:20]:  # Limit to 20 files
        report_lines.append(f"- `{f}`")
    if len(changed_files) > 20:
        report_lines.append(f"- ... and {len(changed_files) - 20} more files")

    # ISTQB note
    report_lines.append("")
    report_lines.append("---")
    report_lines.append(
        "*This report is generated by [Defect Risk Analyzer]"
        "(https://github.com/mcan-k/defect-risk-analyzer) "
        "using ISTQB Risk-Based Testing principles and historical defect analysis.*"
    )

    return "\n".join(report_lines)


# =============================================================================
# Main CLI
# =============================================================================

def main():
    """CLI entry point."""
    # The report contains emoji; a Windows console using a legacy codepage
    # (e.g. cp1254) raises UnicodeEncodeError when printing it.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Reads .env — without it USE_MOCK_DATA stays False and the CI run silently
    # looks for bugs.json instead of the sample data.
    config.init()

    parser = argparse.ArgumentParser(
        description="CI Risk Analyzer — Analyze PR risk from git diff",
    )
    parser.add_argument(
        "--diff",
        type=str,
        default=None,
        help="Git diff content as string",
    )
    parser.add_argument(
        "--diff-file",
        type=str,
        default=None,
        help="Path to file containing git diff output",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="risk_report.md",
        help="Output file for the markdown report (default: risk_report.md)",
    )

    args = parser.parse_args()

    # Get diff content
    diff_text = ""
    if args.diff:
        diff_text = args.diff
    elif args.diff_file:
        try:
            diff_text = Path(args.diff_file).read_text(encoding="utf-8")
        except OSError as e:
            logger.error("Cannot read diff file: %s", e)
            sys.exit(1)
    else:
        # Try reading from stdin
        if not sys.stdin.isatty():
            diff_text = sys.stdin.read()
        else:
            logger.error("No diff provided. Use --diff, --diff-file, or pipe via stdin.")
            sys.exit(1)

    if not diff_text.strip():
        logger.warning("Empty diff — no changes to analyze.")
        report = "# 🔍 Defect Risk Analysis Report\n\nNo changes detected in this PR."
        Path(args.output).write_text(report, encoding="utf-8")
        print(report)
        sys.exit(0)

    # Parse diff
    changed_files = extract_changed_files(diff_text)
    analyzed_files = select_analyzable_files(changed_files)
    provenance = infer_module_provenance(changed_files)
    affected_modules = sorted(provenance)

    logger.info(
        "Changed files: %d (%d analyzed)", len(changed_files), len(analyzed_files)
    )
    logger.info("Affected modules: %s", affected_modules or "none matched")

    # Initialize analyzer
    analyzer = AnalysisService()
    bugs = load_bugs_from_file()
    if bugs:
        analyzer.load_bugs(bugs)
        logger.info("Loaded %d bugs for analysis.", len(bugs))
    else:
        logger.warning("No bug data available. Report will have limited risk data.")

    # Generate report
    report = generate_risk_report(
        analyzer,
        changed_files,
        affected_modules,
        analyzed_files=analyzed_files,
        provenance=provenance,
    )

    # Write output
    output_path = Path(args.output)
    output_path.write_text(report, encoding="utf-8")
    logger.info("Report written to %s", output_path)

    # Also print to stdout (for GitHub Actions)
    print(report)


if __name__ == "__main__":
    main()
