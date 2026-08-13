"""
Unit tests for core/scoring.py.

Expected values are hand-derived from the formula, with each derivation written
out above the assertion. None are invented: the derivation method was first
checked against the committed snapshots on four independent modules —

    Authentication @2026-08-11  (0.9*60 + 0.3*40) * 1.5 * 0.8 * 1.0  = 79.2 -> 79
    Authentication @2026-04-01   66 * 1.5 * 1.3 * 1.0                = 128.7 -> 100
    Reporting      @2026-04-01  (0.6*60 + 0.1*40) * 1.5 * 1.0 * 0.70 = 42.0 -> 42
    Notifications  @2026-08-11  (0.4667*60 + 0.15*40) * 1.0*0.8*0.85 = 23.12 -> 23

— all four matching their snapshot exactly. See tests/test_scoring_regression.py.

The formula under test:
    priority_factor = weighted_priority_score / (total_bugs * 5.0)
    base_score      = priority_factor * 60 + bug_density * 40
    adjusted        = base_score * (1 + open_ratio*0.5) * trend_mult * volume_factor
    score           = clamp(int(round(adjusted)), 0, 100)
"""

from datetime import datetime

import pytest

from defect_risk_analyzer.core import scoring


def make_stats(
    total_bugs: int = 4,
    weighted: float | None = None,
    bug_density: float = 0.0,
    open_ratio: float = 0.0,
    trend: str = "stable",
) -> dict:
    """Stats dict with a neutral baseline of base_score = 60.

    weighted defaults to 5.0 * total_bugs, i.e. every bug "Highest", giving
    priority_factor = 1.0. With bug_density 0.0 that makes base_score exactly
    60, so each test below multiplies a single factor against a round number
    and no expected value lands on .5 (where int(round()) rounds to even).
    """
    return {
        "total_bugs": total_bugs,
        "weighted_priority_score": 5.0 * total_bugs if weighted is None else weighted,
        "bug_density": bug_density,
        "open_ratio": open_ratio,
        "trend": trend,
    }


# ===========================================================================
# Volume factor — 0.4 + min(n/4, 1.0) * 0.6
# ===========================================================================

@pytest.mark.parametrize(
    ("total_bugs", "expected"),
    [
        # base 60 * volume_factor:
        (1, 33),   # 0.4 + 0.25*0.6 = 0.55 -> 60 * 0.55 = 33.0
        (2, 42),   # 0.4 + 0.50*0.6 = 0.70 -> 60 * 0.70 = 42.0
        (3, 51),   # 0.4 + 0.75*0.6 = 0.85 -> 60 * 0.85 = 51.0
        (4, 60),   # 0.4 + 1.00*0.6 = 1.00 -> 60 * 1.00 = 60.0
        (8, 60),   # min() caps at 1.0, so 4+ bugs all score the same
    ],
)
def test_volume_factor_steps(total_bugs: int, expected: int):
    """Small modules are damped: you need 4+ bugs for full confidence."""
    assert scoring.calculate_risk_score("M", make_stats(total_bugs=total_bugs)) == expected


# ===========================================================================
# Trend multiplier
# ===========================================================================

@pytest.mark.parametrize(
    ("trend", "expected"),
    [
        ("increasing", 78),   # 60 * 1.3
        ("stable", 60),       # 60 * 1.0
        ("decreasing", 48),   # 60 * 0.8
        ("nonsense", 60),     # unknown trend falls back to 1.0
    ],
)
def test_trend_multiplier(trend: str, expected: int):
    assert scoring.calculate_risk_score("M", make_stats(trend=trend)) == expected


# ===========================================================================
# Open ratio factor — 1.0 + open_ratio * 0.5
# ===========================================================================

@pytest.mark.parametrize(
    ("open_ratio", "expected"),
    [
        (0.0, 60),   # 60 * 1.00
        (0.5, 75),   # 60 * 1.25
        (1.0, 90),   # 60 * 1.50
    ],
)
def test_open_ratio_factor(open_ratio: float, expected: int):
    assert scoring.calculate_risk_score("M", make_stats(open_ratio=open_ratio)) == expected


# ===========================================================================
# Risk level thresholds — CRITICAL 80, HIGH 60, MEDIUM 35, else LOW
# ===========================================================================

@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (100, "CRITICAL"),
        (80, "CRITICAL"),   # boundary, inclusive
        (79, "HIGH"),       # one below
        (60, "HIGH"),       # boundary, inclusive
        (59, "MEDIUM"),     # one below
        (35, "MEDIUM"),     # boundary, inclusive
        (34, "LOW"),        # one below
        (0, "LOW"),
    ],
)
def test_get_risk_level_thresholds(score: int, expected: str):
    assert scoring.get_risk_level(score) == expected


@pytest.mark.parametrize(("score", "expected"), [(-5, "LOW"), (150, "CRITICAL")])
def test_get_risk_level_does_not_validate_range(score: int, expected: str):
    """Documents current behaviour, not an endorsement.

    get_risk_level applies its comparisons to whatever it is handed. In practice
    calculate_risk_score clamps to 0-100 first, so out-of-range values cannot
    reach it through the normal path.
    """
    assert scoring.get_risk_level(score) == expected


# ===========================================================================
# Priority weights
# ===========================================================================

def test_unknown_priority_uses_default_weight():
    """An unrecognised priority contributes DEFAULT_PRIORITY_WEIGHT (2.5)."""
    stats = scoring.calculate_module_stats(
        [{"component": "M", "priority": "Bogus", "status": "Open", "created": ""}]
    )
    assert stats["M"]["priority_distribution"] == {"Bogus": 1}
    assert stats["M"]["weighted_priority_score"] == 2.5


def test_missing_priority_defaults_to_medium():
    """A bug with no priority key is treated as Medium (weight 3.0), not unknown."""
    stats = scoring.calculate_module_stats(
        [{"component": "M", "status": "Open", "created": ""}]
    )
    assert stats["M"]["priority_distribution"] == {"Medium": 1}
    assert stats["M"]["weighted_priority_score"] == 3.0


def test_known_priority_weights():
    """Highest 5.0 + High 4.0 + Medium 3.0 + Low 2.0 + Lowest 1.0 = 15.0"""
    bugs = [
        {"component": "M", "priority": p, "status": "Open", "created": ""}
        for p in ("Highest", "High", "Medium", "Low", "Lowest")
    ]
    assert scoring.calculate_module_stats(bugs)["M"]["weighted_priority_score"] == 15.0


# ===========================================================================
# Trend detection — recent vs older than the 30-day window
# ===========================================================================

NOW = datetime(2026, 6, 1, 12, 0, 0)   # window opens 2026-05-02T12:00:00
RECENT = "2026-05-15T10:00:00.000+0300"
OLD = "2026-01-10T10:00:00.000+0300"


@pytest.mark.parametrize(
    ("created_dates", "expected"),
    [
        ([RECENT, RECENT, OLD], "increasing"),   # 2 recent > 1 old
        ([RECENT, OLD], "stable"),               # 1 == 1, ties are stable
        ([RECENT, OLD, OLD], "decreasing"),      # 1 recent < 2 old
    ],
)
def test_trend_branches(created_dates: list[str], expected: str):
    bugs = [
        {"component": "M", "priority": "Medium", "status": "Open", "created": c}
        for c in created_dates
    ]
    stats = scoring.calculate_module_stats(bugs, now=NOW)
    assert stats["M"]["trend"] == expected
    assert stats["M"]["recent_bug_count"] == created_dates.count(RECENT)


def test_missing_created_counts_as_old():
    """A bug with no created timestamp falls into the older bucket."""
    bugs = [
        {"component": "M", "priority": "Medium", "status": "Open", "created": ""},
        {"component": "M", "priority": "Medium", "status": "Open"},
    ]
    stats = scoring.calculate_module_stats(bugs, now=NOW)
    assert stats["M"]["recent_bug_count"] == 0
    assert stats["M"]["trend"] == "decreasing"


# ===========================================================================
# Degenerate input
# ===========================================================================

def test_empty_bug_list_returns_empty_dict():
    assert scoring.calculate_module_stats([]) == {}


def test_zero_total_bugs_scores_zero():
    assert scoring.calculate_risk_score("M", {"total_bugs": 0}) == 0


def test_empty_stats_scores_zero():
    assert scoring.calculate_risk_score("M", {}) == 0


# ===========================================================================
# Clamping
# ===========================================================================

def test_score_clamps_at_100():
    """(1.0*60 + 1.0*40) * 1.5 * 1.3 * 1.0 = 195.0, clamped to 100.

    The same path the Authentication module takes at now=2026-04-01, where the
    snapshot records 128.7 -> 100.
    """
    stats = make_stats(
        total_bugs=4, weighted=20.0, bug_density=1.0, open_ratio=1.0, trend="increasing"
    )
    assert scoring.calculate_risk_score("M", stats) == 100


def test_score_clamps_at_0():
    """Defensive lower clamp: no real input produces a negative score.

    Forced here with a negative weighted_priority_score, which drives
    priority_factor negative. Covers the max(0, ...) guard.
    """
    stats = make_stats(total_bugs=4, weighted=-100.0)
    assert scoring.calculate_risk_score("M", stats) == 0
