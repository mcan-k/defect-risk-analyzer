"""
Scoring snapshot capture — the tool that produced tests/data/scores-aff55c6-*.json.

Runs the deterministic scoring path only — no LLM call, no ChromaDB access,
no HTTP — and writes a sorted JSON snapshot so a refactor can be proven
behaviour-preserving.

Kept alongside the fixtures it generated. It is NOT a way to rebuild those two
files: it snapshots whatever scoring module is importable right now, so today it
always emits mode B. Its purpose is to generate a *new* before/after pair around
a *future* refactor, the same way the committed pair was generated around Faz 2.
See tests/data/README.md.

Two modes, selected automatically:

  Mode A (before Faz 2 / Adim 1a): the `scoring` module does not exist yet.
          Drives `RiskAnalyzer` directly. `load_bugs()` is deliberately NOT
          called — it resets the ChromaDB collection and would destroy the
          existing vector database. `_bugs` is assigned directly instead.
          RETAINED FOR REFERENCE ONLY: risk_analyzer.py was deleted in 2a52585
          and config.get_risk_level no longer exists, so this branch cannot
          execute against the current tree. _find_scoring_module() always
          resolves core.scoring now, so it is never reached.

  Mode B (after Adim 1a): calls the pure `scoring` functions.

Usage:
    python tests/tools/make_baseline.py [iso-datetime] [out-dir]

Output defaults to the current working directory, not tests/data/ — generated
snapshots are scratch, and tests/data/ holds only the committed fixtures.
Root-level scores-*.json is gitignored.

Deliberately not named test_*.py so pytest does not collect it.
"""

import importlib.util
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Frozen clock
# ---------------------------------------------------------------------------
# calculate_module_stats derives a 30-day trend window from datetime.now().
# Two runs at different wall-clock times can legitimately move a bug in or out
# of that window, which would look exactly like a scoring regression. Freeze it.

# Two snapshots are captured, because the sample bugs span 2025-12-15..2026-03-20:
#
#   2026-08-11  every bug is older than 30 days -> trend "decreasing" everywhere
#   2026-04-01  window opens 2026-03-02, so March bugs count as recent, which
#               exercises the "increasing"/"stable" branches and the 1.3 / 1.0
#               trend multipliers that the late snapshot never reaches.
DEFAULT_NOW = datetime(2026, 8, 11, 12, 0, 0)

BASELINE_NOW = DEFAULT_NOW


class _FrozenDatetime(datetime):
    """datetime with only now() pinned — arithmetic and isoformat stay real.

    A bare `patch(...)` would install a MagicMock, turning
    `datetime.now() - timedelta(days=30)` into another MagicMock and making the
    string comparison in calculate_module_stats either raise TypeError or
    silently count every bug as recent.
    """

    @classmethod
    def now(cls, tz=None):
        return BASELINE_NOW


# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------

def _find_scoring_module() -> str | None:
    """Return the import path of the scoring module, or None if it is absent.

    Both candidate locations are probed: the flat layout and the core/
    package layout from docs/ROADMAP-v2.md.
    """
    for candidate in (
        "defect_risk_analyzer.scoring",
        "defect_risk_analyzer.core.scoring",
    ):
        try:
            if importlib.util.find_spec(candidate) is not None:
                return candidate
        except ModuleNotFoundError:
            continue
    return None


# ---------------------------------------------------------------------------
# Scoring runs
# ---------------------------------------------------------------------------

def _run_mode_a(bugs: list[dict]) -> dict[str, dict]:
    """Drive RiskAnalyzer without touching ChromaDB."""
    from defect_risk_analyzer import config
    from defect_risk_analyzer.risk_analyzer import RiskAnalyzer

    with patch("defect_risk_analyzer.risk_analyzer.datetime", _FrozenDatetime):
        analyzer = RiskAnalyzer()
        # Deliberately not analyzer.load_bugs(bugs): that resets the collection.
        analyzer._bugs = bugs

        stats = analyzer.calculate_module_stats()
        out = {}
        for module, module_stats in stats.items():
            score = analyzer.calculate_risk_score(module, module_stats)
            out[module] = {
                **module_stats,
                "risk_score": score,
                "risk_level": config.get_risk_level(score),
            }
    return out


def _run_mode_b(bugs: list[dict], scoring_path: str) -> dict[str, dict]:
    """Call the pure scoring functions directly."""
    import importlib

    scoring = importlib.import_module(scoring_path)

    stats = scoring.calculate_module_stats(bugs, now=BASELINE_NOW)
    out = {}
    for module, module_stats in stats.items():
        score = scoring.calculate_risk_score(module, module_stats)
        out[module] = {
            **module_stats,
            "risk_score": score,
            "risk_level": scoring.get_risk_level(score),
        }
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    global BASELINE_NOW

    if len(sys.argv) > 1:
        BASELINE_NOW = datetime.fromisoformat(sys.argv[1])

    from defect_risk_analyzer import config
    from defect_risk_analyzer.component_classifier import classify_bugs
    from defect_risk_analyzer.jira_client import load_bugs_from_file

    config.init()

    # Always the sample set: committed, deterministic, independent of .env.
    bugs_file = config.SAMPLE_BUGS_FILE
    bugs = load_bugs_from_file(bugs_file)
    if not bugs:
        print(f"ERROR: no bugs loaded from {bugs_file}", file=sys.stderr)
        return 1

    classify_bugs(bugs)

    scoring_path = _find_scoring_module()
    if scoring_path is None:
        mode = "A"
        modules = _run_mode_a(bugs)
    else:
        mode = "B"
        modules = _run_mode_b(bugs, scoring_path)

    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    payload = {
        "_baseline_now": BASELINE_NOW.isoformat(),
        "_mode": mode,
        "_scoring_module": scoring_path or "(none — RiskAnalyzer)",
        "_bugs_file": bugs_file.name,
        "_bug_count": len(bugs),
        "modules": {name: modules[name] for name in sorted(modules)},
    }

    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"scores-{commit}-now{BASELINE_NOW.date().isoformat()}.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"mode        : {mode} ({payload['_scoring_module']})")
    print(f"baseline_now: {payload['_baseline_now']}")
    print(f"bugs        : {len(bugs)} from {bugs_file.name}")
    print(f"modules     : {len(modules)}")
    print(f"written     : {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
