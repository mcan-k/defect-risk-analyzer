"""
Regression test pinning core/scoring.py to the pre-refactor RiskAnalyzer.

The snapshots in tests/data/ were produced at commit aff55c6 by
src/defect_risk_analyzer/risk_analyzer.py, which was deleted in 2a52585. They
are the only remaining evidence that the Faz 2 split preserved behaviour.

If this test fails, investigate the change in core/scoring.py. Do NOT
regenerate or edit the snapshots — see tests/data/README.md.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from defect_risk_analyzer.core import scoring

TESTS_DATA = Path(__file__).resolve().parent / "data"

# Both clocks are required. At 2026-08-11 every sample bug is outside the
# 30-day window, so every module is "decreasing" with recent_bug_count 0; only
# 2026-04-01 exercises the "increasing" and "stable" branches and the 1.3 / 1.0
# trend multipliers.
SNAPSHOTS = [
    "scores-aff55c6-now2026-08-11.json",
    "scores-aff55c6-now2026-04-01.json",
]

def _score_all(bugs: list[dict], now: datetime) -> dict[str, dict]:
    """Reproduce the snapshot payload from the current scoring module."""
    stats = scoring.calculate_module_stats(bugs, now=now)

    out = {}
    for module, module_stats in stats.items():
        score = scoring.calculate_risk_score(module, module_stats)
        out[module] = {
            **module_stats,
            "risk_score": score,
            "risk_level": scoring.get_risk_level(score),
        }
    return out


@pytest.fixture(scope="module")
def bugs(sample_bugs_path: Path) -> list[dict]:
    # encoding="utf-8" is required, not stylistic: the file holds Turkish text
    # that raises UnicodeDecodeError under a cp1254 default locale, so a bare
    # open() fails on a Turkish Windows box and passes on Linux CI.
    return json.loads(sample_bugs_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("snapshot_name", SNAPSHOTS)
def test_scoring_matches_pre_refactor_snapshot(snapshot_name: str, bugs: list[dict]):
    snapshot = json.loads((TESTS_DATA / snapshot_name).read_text(encoding="utf-8"))

    # The frozen clock comes from the snapshot itself. datetime.now() would make
    # the 30-day trend window drift and turn this into a flaky test.
    now = datetime.fromisoformat(snapshot["_baseline_now"])

    # Guards against sample data drift: without it, an edit to sample_bugs.json
    # surfaces as a confusing per-field diff instead of a clear cause.
    assert len(bugs) == snapshot["_bug_count"], (
        f"data/sample_bugs.json has {len(bugs)} bugs but the snapshot was built "
        f"from {snapshot['_bug_count']}. The sample data changed; this test "
        "cannot be meaningful until that is reconciled."
    )

    actual = _score_all(bugs, now)
    expected = snapshot["modules"]

    assert set(actual) == set(expected)

    # Per-module comparison so a failure names the module. Whole-dict equality
    # (not a subset check) means a newly added field also fails, which is
    # intended: the snapshot pins the full shape of the result.
    for module in sorted(expected):
        assert actual[module] == expected[module], module


def test_snapshots_are_mode_a():
    """The fixtures must be the pre-refactor output, not a re-captured mode B.

    Silently swapping in a mode-B snapshot would make this suite compare
    core/scoring.py against itself — green, and worthless.
    """
    for name in SNAPSHOTS:
        snapshot = json.loads((TESTS_DATA / name).read_text(encoding="utf-8"))
        assert snapshot["_mode"] == "A", name
        assert snapshot["_scoring_module"] == "(none — RiskAnalyzer)", name
