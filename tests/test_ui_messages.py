"""
The sentences blind_spot_detector used to build itself.

These four expected strings arrived here from tests/test_blind_spots.py, in
the same commit that converted the detector to {"code", "params"}. They are
copied character for character on purpose: the diff of that commit shows this
file gaining exactly what the other file lost, which is what makes "the
wording moved" verifiable instead of asserted. If a sentence had been quietly
reworded during the move, the strings would not match and the claim would be
false.

The detector's own tests no longer look at wording at all. They assert the
code and params; the text is this layer's problem, and in Phase 5C it becomes
locales/{tr,en}.json.
"""

from datetime import datetime, timedelta, timezone

import pytest

from defect_risk_analyzer.blind_spot_detector import detect_blind_spots
from defect_risk_analyzer.ui.messages import (
    TEMPLATES,
    UnknownFindingCode,
    format_finding,
)

# =============================================================================
# The four sentences, as they read before the conversion
# =============================================================================

def test_unanalyzed_risky_module_sentence():
    assert format_finding({
        "code": "unanalyzed_risky_module",
        "params": {"module": "Authentication", "risk_level": "CRITICAL"},
    }) == (
        "Authentication modülü CRITICAL risk seviyesinde ancak henüz analiz "
        "edilmemiş. Canlı Analiz sayfasından analiz yapın."
    )


def test_neglected_critical_bug_sentence():
    assert format_finding({
        "code": "neglected_critical_bug",
        "params": {
            "key": "AP-201",
            "priority": "Highest",
            "days_open": 15,
            "status": "Open",
        },
    }) == (
        "AP-201 — Highest öncelikli bug 15 gündür 'Open' durumunda. "
        "Acil müdahale gerekiyor."
    )


def test_stale_bug_sentence():
    assert format_finding({
        "code": "stale_bug",
        "params": {"key": "AP-203", "days_open": 40},
    }) == (
        "AP-203 — 40 gündür açık. Çözüm süresi beklentinin üzerinde."
    )


def test_rising_unattended_module_sentence():
    assert format_finding({
        "code": "rising_unattended_module",
        "params": {"module": "Search", "recent_bugs": 5},
    }) == (
        "Search modülünde bug sayısı artıyor (5 yeni bug) ancak üzerinde "
        "çalışılan bug yok. Bu modüle kaynak ayrılması önerilir."
    )


# =============================================================================
# The contract between the two layers
# =============================================================================

def test_every_code_the_detector_emits_has_a_template():
    """The failure this prevents: the detector grows a fifth category, nobody
    adds a template, and the page raises for real users instead of in CI.

    Inputs are shaped to make all four categories non-empty at once.
    """
    now = datetime(2026, 4, 1, 12, 0, tzinfo=timezone(timedelta(hours=3)))
    bugs = [{
        "key": "S-1",
        "summary": "s",
        "component": "Search",
        "status": "Open",
        "priority": "Highest",
        "created": "2026-01-01T09:00:00.000+0300",
    }]
    stats = {"Search": {
        "total_bugs": 4, "open_bugs": 4, "trend": "increasing", "recent_bug_count": 3,
    }}

    spots = detect_blind_spots(
        bugs=bugs, module_stats=stats, analysis_results=[],
        risk_scores={"Search": 90}, now=now,
    )

    findings = [
        item
        for value in spots.values()
        if isinstance(value, list)
        for item in value
    ]
    emitted = {item["code"] for item in findings}

    assert emitted == set(TEMPLATES), (
        f"detector emits {emitted}, ui/messages.py knows {set(TEMPLATES)}"
    )
    # And each one renders without raising.
    for item in findings:
        assert format_finding(item)


def test_params_carry_everything_the_sentence_needs():
    """format_finding must not reach outside params.

    Keeping params self-contained is what lets Phase 5C swap the templates for
    locale files without the renderer knowing a finding's other fields.
    """
    assert format_finding({
        "code": "stale_bug",
        "params": {"key": "AP-203", "days_open": 40},
        # Deliberately contradictory neighbours — none may be read.
        "key": "WRONG",
        "days_open": -1,
        "summary": "should not appear",
    }) == "AP-203 — 40 gündür açık. Çözüm süresi beklentinin üzerinde."


# =============================================================================
# Failure modes — loud, not silent
# =============================================================================

@pytest.mark.parametrize("code", ["", "no_such_code", None, "Stale_Bug"])
def test_an_unknown_code_raises(code):
    """Silence here is what would hide a missing locale key in Phase 5C: the
    caption renders empty, the page looks fine, and nobody notices. Raising
    surfaces it in the dashboard walk, which collects exceptions.

    "Stale_Bug" is in the list because lookup is exact — no case folding.
    """
    with pytest.raises(UnknownFindingCode):
        format_finding({"code": code, "params": {}})


def test_a_finding_with_no_code_at_all_raises():
    with pytest.raises(UnknownFindingCode):
        format_finding({"params": {"key": "AP-1"}})


def test_a_missing_param_raises_rather_than_rendering_a_gap():
    """Same reasoning, one level down: a template needing days_open must not
    quietly produce a half-written sentence."""
    with pytest.raises(KeyError):
        format_finding({"code": "stale_bug", "params": {"key": "AP-203"}})
