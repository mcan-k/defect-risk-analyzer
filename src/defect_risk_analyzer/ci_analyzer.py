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

EXCLUDED_NAMES = frozenset({"LICENSE", "LICENSE.md", "NOTICE", "CODEOWNERS"})

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

        if path.name in EXCLUDED_NAMES:
            continue
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


def infer_modules_from_files(changed_files: list[str]) -> list[str]:
    """
    Infer affected modules from changed file paths.

    Returns:
        Sorted module names, or an empty list when nothing matched. Empty means
        "no mapping could be made" — it is NOT the same as "this module has no
        recorded defects", and generate_risk_report says which of the two it is
        rather than inventing a "General" module that no bug is filed against.
    """
    modules = set()

    for file_path in select_analyzable_files(changed_files):
        tokens = _path_tokens(file_path)

        for keyword, module in MODULE_KEYWORDS.items():
            # Exact token, or its regular plural. Prefix matching would let
            # "pay" match "payload" — a narrower copy of the bug being fixed —
            # while exact-only would drop "payments", "migrations", "models",
            # which is how those directories are ordinarily named.
            if keyword in tokens or f"{keyword}s" in tokens:
                # No `break`: a path that names three modules affects three
                # modules. Stopping at the first hit made dictionary insertion
                # order decide the answer, silently.
                modules.add(module)

    return sorted(modules)


# =============================================================================
# Report Generator
# =============================================================================

def generate_risk_report(
    analyzer: AnalysisService,
    changed_files: list[str],
    affected_modules: list[str],
) -> str:
    """
    Generate a markdown risk report for a PR.

    Args:
        analyzer: Initialized AnalysisService with loaded bugs.
        changed_files: List of changed file paths.
        affected_modules: Inferred module names.

    Returns:
        Markdown-formatted report string.
    """
    report_lines = []
    report_lines.append("# 🔍 Defect Risk Analysis Report")
    report_lines.append("")
    report_lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"**Changed Files:** {len(changed_files)}")
    report_lines.append(f"**Affected Modules:** {', '.join(affected_modules)}")
    report_lines.append("")

    # Module statistics
    module_stats = analyzer.calculate_module_stats()

    # Overall risk assessment
    report_lines.append("## Risk Summary")
    report_lines.append("")
    report_lines.append("| Module | Risk Score | Risk Level | Total Bugs | Open Bugs | Trend |")
    report_lines.append("|--------|-----------|------------|------------|-----------|-------|")

    max_risk = 0
    max_risk_module = ""

    for module in affected_modules:
        stats = module_stats.get(module, {})
        if stats:
            score = analyzer.calculate_risk_score(module, stats)
            level = scoring.get_risk_level(score)
            total = stats.get("total_bugs", 0)
            open_bugs = stats.get("open_bugs", 0)
            trend = stats.get("trend", "stable")

            emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(level, "⚪")
            trend_emoji = {"increasing": "📈", "decreasing": "📉", "stable": "➡️"}.get(trend, "➡️")

            report_lines.append(
                f"| {module} | {score}/100 | {emoji} {level} | {total} | {open_bugs} | {trend_emoji} {trend} |"
            )

            if score > max_risk:
                max_risk = score
                max_risk_module = module
        else:
            report_lines.append(f"| {module} | N/A | ⚪ No Data | 0 | 0 | ➡️ N/A |")

    report_lines.append("")

    # Overall verdict
    overall_level = scoring.get_risk_level(max_risk)
    if overall_level == "CRITICAL":
        report_lines.append(f"### ⚠️ CRITICAL RISK — `{max_risk_module}` module requires immediate attention!")
        report_lines.append("")
        report_lines.append("**Recommendation:** Request thorough code review and additional QA testing before merge.")
    elif overall_level == "HIGH":
        report_lines.append(f"### 🟠 HIGH RISK — `{max_risk_module}` module has elevated defect density.")
        report_lines.append("")
        report_lines.append("**Recommendation:** Ensure targeted testing for the affected module.")
    elif overall_level == "MEDIUM":
        report_lines.append("### 🟡 MEDIUM RISK — Standard review recommended.")
        report_lines.append("")
        report_lines.append("**Recommendation:** Follow normal review process with attention to edge cases.")
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
    affected_modules = infer_modules_from_files(changed_files)

    logger.info("Changed files: %d", len(changed_files))
    logger.info("Affected modules: %s", affected_modules)

    # Initialize analyzer
    analyzer = AnalysisService()
    bugs = load_bugs_from_file()
    if bugs:
        analyzer.load_bugs(bugs)
        logger.info("Loaded %d bugs for analysis.", len(bugs))
    else:
        logger.warning("No bug data available. Report will have limited risk data.")

    # Generate report
    report = generate_risk_report(analyzer, changed_files, affected_modules)

    # Write output
    output_path = Path(args.output)
    output_path.write_text(report, encoding="utf-8")
    logger.info("Report written to %s", output_path)

    # Also print to stdout (for GitHub Actions)
    print(report)


if __name__ == "__main__":
    main()
