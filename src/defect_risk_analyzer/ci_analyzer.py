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
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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
# Inference runs in two layers, and both come from module-map.json. Neither has
# a built-in default: a scope rule the user cannot see is a scope rule they
# cannot fix, which is how PR #3 shipped a 79/100 HIGH RISK verdict for a
# one-line documentation change.
#
# Layer 1 (`exclude`) drops paths before anything looks at them.
# Layer 2 (`modules`) maps whatever survives to module names by path pattern.
#
# Bölüm A narrowed a keyword table until "auth" stopped matching inside
# "auth-probe.md". That fixed the documentation class and left the rest: of 34
# tracked .py files in this repository the rule produced a module for 8, and
# exactly 1 of those was right. api_auth.py fired Authentication and scored
# 79/100 off bug history for a module it has nothing to do with — it validates
# this tool's own X-API-Key header. No tuning separates it from api.py, because
# the difference is not in the filename. Going from a filename to a Jira
# component is a guess; it is now the user's declaration instead.


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


# =============================================================================
# The module map
# =============================================================================
# Loading is deliberately unforgiving. Bölüm A replaced a report that quietly
# invented a module with one that says what it does and does not know; a loader
# that swallows a typo and returns an empty map would put that silence straight
# back, one layer lower. So the map either loads or raises, and main() prints
# the reason into the report rather than analyzing with a half-read map.
#
# This lives here rather than in core/: it reads a file and reads config, and
# ci_analyzer is its only consumer.

# Glob syntax we do not implement. Rejected at load time rather than passed
# through as literal text, which would make such a pattern silently never
# match — and a user seeing no modules cannot tell that from a wrong path.
_UNSUPPORTED_PATTERN_CHARS = "[]{}!"


class ModuleMapError(Exception):
    """The module map could not be used. main() catches this type."""


class ModuleMapMissing(ModuleMapError):
    """No file at the expected path — a setup state, not a corruption."""


class ModuleMapInvalid(ModuleMapError):
    """The file exists but cannot be read as a map."""


@dataclass(frozen=True)
class ModuleMap:
    """Path patterns for module inference, plus the analysis scope.

    `modules` maps a path pattern to a module name; `exclude` lists patterns
    whose files never reach inference at all. Both come from module-map.json —
    there is no built-in default for either, which is the whole point of the
    phase: a scope rule the user cannot see is a scope rule they cannot fix.
    """

    modules: dict[str, str]
    exclude: tuple[str, ...]


def _validate_pattern(pattern: object, where: str) -> str:
    """Return `pattern` if it is a usable path glob, else raise.

    `where` names the section it came from, so the message points at a line of
    the user's file rather than at an internal variable.
    """
    if not isinstance(pattern, str) or not pattern:
        raise ModuleMapInvalid(
            f'module-map.json: every entry of "{where}" must be a non-empty '
            f"path pattern, got {pattern!r}."
        )

    if "\\" in pattern:
        raise ModuleMapInvalid(
            f'module-map.json: pattern {pattern!r} in "{where}" uses a '
            "backslash. Patterns are POSIX paths and use / on every platform, "
            "because that is what git diff emits on every platform."
        )

    if pattern.startswith("/"):
        raise ModuleMapInvalid(
            f'module-map.json: pattern {pattern!r} in "{where}" starts with /. '
            "Diff paths are relative to the repository root, so a leading "
            "slash can never match."
        )

    for char in _UNSUPPORTED_PATTERN_CHARS:
        if char in pattern:
            raise ModuleMapInvalid(
                f'module-map.json: pattern {pattern!r} in "{where}" uses {char!r}, '
                "which is not supported. The pattern syntax is * (within one "
                "path segment), ? (one character) and ** (any number of "
                "segments) — no character classes, braces or negation."
            )

    return pattern


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """json object hook that rejects a repeated key instead of keeping the last.

    Two entries for the same pattern is a mistake whose winner is decided by
    file order, silently — the same shape as the dictionary-ordering bug Bölüm A
    removed from the keyword table.
    """
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise ModuleMapInvalid(
                f"module-map.json: {key!r} is listed twice. Remove one — "
                "otherwise which module wins depends on the order of the lines."
            )
        seen[key] = value

    return seen


def load_module_map(path: Path | None = None) -> ModuleMap:
    """Read and validate module-map.json.

    Args:
        path: The file to read. Defaults to config.MODULE_MAP_FILE, which is
            derived from BASE_DIR, so tests can point it anywhere.

    Returns:
        The validated map.

    Raises:
        ModuleMapMissing: No file at `path`.
        ModuleMapInvalid: The file is not JSON, does not match the schema, or
            contains no patterns.
    """
    path = path or config.MODULE_MAP_FILE

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ModuleMapMissing(
            f"No module map: expected module-map.json at {path}. Create it — "
            "the analyzer cannot guess which directories belong to which "
            "module, and will not try. If this package was installed with "
            "`pip install .` outside a source checkout, set DRA_BASE_DIR to "
            "the project root."
        ) from None
    except OSError as exc:
        raise ModuleMapInvalid(f"module-map.json at {path} cannot be read: {exc}") from exc

    try:
        raw = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ModuleMapInvalid(
            f"module-map.json at {path} is not valid JSON: {exc.msg} "
            f"(line {exc.lineno}, column {exc.colno})."
        ) from exc

    if not isinstance(raw, dict):
        raise ModuleMapInvalid(
            "module-map.json: the top level must be an object with a "
            f'"modules" key, got {type(raw).__name__}.'
        )

    if "modules" not in raw:
        raise ModuleMapInvalid(
            'module-map.json: the required "modules" key is missing. It maps a '
            "path pattern to a module name."
        )

    modules = raw["modules"]
    if not isinstance(modules, dict):
        raise ModuleMapInvalid(
            'module-map.json: "modules" must be an object mapping a path '
            f"pattern to a module name, got {type(modules).__name__}."
        )

    if not modules:
        raise ModuleMapInvalid(
            'module-map.json contains no patterns: "modules" is empty. Add at '
            "least one path pattern, or delete the file if you meant to turn "
            "module inference off — an empty map cannot be told apart from a "
            "mistake."
        )

    for pattern, module in modules.items():
        _validate_pattern(pattern, "modules")
        if not isinstance(module, str) or not module:
            raise ModuleMapInvalid(
                f"module-map.json: the module name for pattern {pattern!r} must "
                f"be a non-empty string, got {module!r}. The name is compared "
                "against the component field in your bug data."
            )

    exclude = raw.get("exclude", [])
    if not isinstance(exclude, list):
        raise ModuleMapInvalid(
            f'module-map.json: "exclude" must be a list of path patterns, got '
            f"{type(exclude).__name__}."
        )

    # Omitting "exclude" excludes nothing. Falling back to a built-in denylist
    # here would be the exact thing this phase removes: a scope rule the user
    # cannot see, cannot change, and does not know is running.
    return ModuleMap(
        modules=dict(modules),
        exclude=tuple(_validate_pattern(item, "exclude") for item in exclude),
    )


def select_analyzable_files(changed_files: list[str], module_map: ModuleMap) -> list[str]:
    """
    Layer 1 — drop paths the map says never reach inference.

    Whatever `exclude` lists is out of scope, and that is the whole rule: there
    is no built-in denylist behind it. A module name appearing inside a file the
    user has excluded is a coincidence, not a signal, and only the user knows
    which files those are.

    Args:
        changed_files: All file paths from the diff.
        module_map: The loaded module-map.json. Required, and positional — a
            default would let a call site silently analyze with no scope at all.

    Returns:
        The subset worth analyzing, in the order given.
    """
    return [
        file_path
        for file_path in changed_files
        if not any(_matches(pattern, file_path) for pattern in module_map.exclude)
    ]


def infer_module_provenance(
    changed_files: list[str], module_map: ModuleMap
) -> dict[str, list[tuple[str, str]]]:
    """
    Infer affected modules, keeping the evidence for each one.

    Args:
        changed_files: All file paths from the diff.
        module_map: The loaded module-map.json.

    Returns:
        Module name -> sorted (file_path, pattern) pairs. Empty dict when
        nothing matched, which means "no mapping could be made" — NOT "this
        module has no recorded defects", and not a "General" module either.
        generate_risk_report says which of the two it means.

    The evidence is printed next to the risk table so a reader can see *why* a
    module was named. The pattern is recorded rather than the part of the path
    it matched: the pattern is a line in the reader's own module-map.json, so it
    names what to edit. Under the keyword rule the opposite was true — the rule
    was invisible, so the report quoted text from the path instead.
    """
    provenance: dict[str, set[tuple[str, str]]] = {}

    for file_path in select_analyzable_files(changed_files, module_map):
        for pattern, module in module_map.modules.items():
            if _matches(pattern, file_path):
                # No `break`: a path that names three modules affects three
                # modules. Stopping at the first hit made dictionary insertion
                # order decide the answer, silently — and the order of keys in
                # a JSON file is not something a reader should have to think
                # about. Unwanted matches are removed from the map, or excluded.
                provenance.setdefault(module, set()).add((file_path, pattern))

    return {module: sorted(pairs) for module, pairs in sorted(provenance.items())}


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
    module_map_error: str | None = None,
    now: datetime | None = None,
) -> str:
    """
    Generate a markdown risk report for a PR.

    Four outcomes are reported distinctly, because conflating them is what
    made the PR #3 probe print "LOW RISK" for a diff it had not assessed:

        module matched, history exists  -> a scored row in the risk table
        module matched, no history      -> named, but no row and no score
        nothing matched                 -> NOT ASSESSED, and no verdict at all
        no usable module map            -> NOT ASSESSED, plus the reason

    The last two both end with no modules and they are not the same thing. One
    says the diff touched nothing the map names; the other says there was no
    map to consult.

    Args:
        analyzer: Initialized AnalysisService with loaded bugs.
        changed_files: List of changed file paths.
        affected_modules: Inferred module names. Empty means nothing matched.
        analyzed_files: The subset of changed_files that reached inference, from
            select_analyzable_files. Used only for the "N excluded" count, which
            is what tells a reader why a docs-only PR matched nothing.
        provenance: Module -> (file, pattern) evidence from
            infer_module_provenance. Omitted means the section is not printed.
        module_map_error: Why the module map could not be used, as the loader
            phrased it. Set means no inference ran at all, and the message is
            printed verbatim — it already distinguishes a missing file from an
            unreadable one from an empty one, so the report does not re-classify
            what the loader has already diagnosed.
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
            # Not "documentation, config or asset" any more: the categories are
            # whatever the user's exclude list says, so the line names the file
            # rather than describing contents it can no longer know.
            line += f"  ({skipped} excluded by module-map.json)"
        report_lines.append(line)

    if module_map_error:
        modules_line = "— not inferred (no module map)"
    elif affected_modules:
        modules_line = ", ".join(affected_modules)
    else:
        modules_line = "— none matched"
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
            "*A pattern in module-map.json named these modules, but the bug "
            "history has no record of them, so no risk was calculated.*"
        )
        report_lines.append("")

    if provenance:
        report_lines.append("## Why these modules")
        report_lines.append("")
        for module in sorted(provenance):
            pairs = provenance[module]
            first_file, first_pattern = pairs[0]
            others = len({path for path, _ in pairs}) - 1
            more = f" (+{others} more file{'s' if others > 1 else ''})" if others else ""
            report_lines.append(
                f"- **{module}** ← pattern `{first_pattern}` matched "
                f"`{first_file}`{more}"
            )
        report_lines.append("")

    # Overall verdict. Computed from the scored modules only — an unscored module
    # must not drag the verdict down to LOW, which is a claim about risk rather
    # than an admission that none was measured.
    # Ordered before the "nothing matched" branch, not after: with no map there
    # are no modules either, so the generic text would fire first and report a
    # diff that missed the map as a diff that missed every module.
    if module_map_error:
        report_lines.append("### ⚪ NOT ASSESSED — no usable module map.")
        report_lines.append("")
        report_lines.append(module_map_error)
        report_lines.append("")
        report_lines.append(
            "**Recommendation:** Risk was not assessed; review the change on its "
            "own merits."
        )
    elif not scored:
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

    # A map that will not load stops inference, and only inference. The report
    # is still produced and still posted, carrying the reason — exiting nonzero
    # here would fail the workflow step and take the explanation down with it,
    # leaving the user with no comment and no idea why.
    analyzed_files: list[str] | None = None
    provenance: dict[str, list[tuple[str, str]]] = {}
    map_error: str | None = None
    try:
        module_map = load_module_map()
    except ModuleMapError as exc:
        map_error = str(exc)
        logger.error("Module inference disabled: %s", exc)
    else:
        analyzed_files = select_analyzable_files(changed_files, module_map)
        provenance = infer_module_provenance(changed_files, module_map)
        logger.info(
            "Changed files: %d (%d analyzed)", len(changed_files), len(analyzed_files)
        )

    affected_modules = sorted(provenance)
    logger.info("Affected modules: %s", affected_modules or "none matched")

    # Initialize analyzer
    analyzer = AnalysisService()
    bugs = load_bugs_from_file()
    if bugs:
        # index=False: nothing here queries the vector store. The only things
        # this module asks the service for are calculate_module_stats() and
        # calculate_risk_score(), both of which read the in-memory bug list.
        # Indexing anyway re-embedded the whole bug history on every run, and
        # a fresh CI machine has nothing for a diff sync to save — every run is
        # a first run. It also removes a way for the run to produce no report
        # at all: there is no try/except here, so a ChromaDB that failed to
        # initialise used to take the PR comment down with it.
        analyzer.load_bugs(bugs, index=False)
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
        module_map_error=map_error,
    )

    # Write output
    output_path = Path(args.output)
    output_path.write_text(report, encoding="utf-8")
    logger.info("Report written to %s", output_path)

    # Also print to stdout (for GitHub Actions)
    print(report)


if __name__ == "__main__":
    main()
