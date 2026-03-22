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
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

import config
from jira_client import load_bugs_from_file
from risk_analyzer import RiskAnalyzer

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


def infer_modules_from_files(changed_files: list[str]) -> list[str]:
    """
    Infer affected modules/components from changed file paths.

    Uses common directory naming conventions to map files to modules.
    """
    modules = set()

    module_keywords = {
        "auth": "Authentication",
        "login": "Authentication",
        "session": "Authentication",
        "token": "Authentication",
        "password": "Authentication",
        "pay": "Payment",
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

    for file_path in changed_files:
        path_lower = file_path.lower()
        for keyword, module in module_keywords.items():
            if keyword in path_lower:
                modules.add(module)
                break

    # If no modules detected, use "General"
    if not modules:
        modules.add("General")

    return sorted(modules)


# =============================================================================
# Report Generator
# =============================================================================

def generate_risk_report(
    analyzer: RiskAnalyzer,
    changed_files: list[str],
    affected_modules: list[str],
) -> str:
    """
    Generate a markdown risk report for a PR.

    Args:
        analyzer: Initialized RiskAnalyzer with loaded bugs.
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
            level = config.get_risk_level(score)
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
    overall_level = config.get_risk_level(max_risk)
    if overall_level == "CRITICAL":
        report_lines.append(f"### ⚠️ CRITICAL RISK — `{max_risk_module}` module requires immediate attention!")
        report_lines.append("")
        report_lines.append("**Recommendation:** Request thorough code review and additional QA testing before merge.")
    elif overall_level == "HIGH":
        report_lines.append(f"### 🟠 HIGH RISK — `{max_risk_module}` module has elevated defect density.")
        report_lines.append("")
        report_lines.append("**Recommendation:** Ensure targeted testing for the affected module.")
    elif overall_level == "MEDIUM":
        report_lines.append(f"### 🟡 MEDIUM RISK — Standard review recommended.")
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
        "(https://github.com/Kartall01/defect-risk-analyzer) "
        "using ISTQB Risk-Based Testing principles and historical defect analysis.*"
    )

    return "\n".join(report_lines)


# =============================================================================
# Main CLI
# =============================================================================

def main():
    """CLI entry point."""
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
    analyzer = RiskAnalyzer()
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
