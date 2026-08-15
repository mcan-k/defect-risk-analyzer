"""
What detect_blind_spots reports today, pinned before Phase 5 rewrites it.

blind_spot_detector.py has never had a test. KNOWN-DEBT calls it the sharpest
of the three checks lost when baseline/compare_service.py was retired, because
Phase 5 converts this function's return type to structural data and that break
is known to reach GET /blind-spots. KNOWN-DEBT:340-341 is explicit about the
order: pin it *before* the rewrite, not after. A test written afterwards can
only describe the new shape, which proves nothing about what was there.

So this file exists to make the next commit's diff readable. Everything here is
current behaviour, including the parts that are wrong — those are named as
characterizations in their own docstrings, not endorsed.

Where the expected values come from, since none are invented:

  * module_stats and risk_scores are read from tests/data/, the snapshot
    captured at aff55c6. It carries trend, total_bugs, open_bugs,
    recent_bug_count, risk_score and risk_level for all six modules, which is
    exactly what this detector consumes. test_scoring_regression.py proves on
    every CI run that current scoring still produces those numbers, so if the
    input ever drifts that test fails first and names the cause.
  * bugs are data/sample_bugs.json, unmodified.
  * days_open values are date subtraction against a fixed clock, written out
    above each assertion.
  * the synthetic cases at the bottom cover branches the sample data cannot
    reach at all — see test_rising_unattended_is_empty_for_the_sample.

The 2026-04-01 snapshot is used rather than 2026-08-11 because it is the only
one where any module has trend "increasing", which is the sole trigger for the
rising_unattended category.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from defect_risk_analyzer.blind_spot_detector import detect_blind_spots

TESTS_DATA = Path(__file__).resolve().parent / "data"
SNAPSHOT = "scores-aff55c6-now2026-04-01.json"

# The snapshot records its clock as "2026-04-01T12:00:00" — naive. It cannot be
# used as-is: every sample bug carries a +0300 Jira offset, and subtracting a
# naive reference from an aware timestamp raises TypeError, which _days_since
# swallows into a silent 0. That failure is green, not red: stale_bugs would
# simply come back empty and this file would pin nothing.
# Pinned as a behaviour in test_a_naive_now_is_swallowed_into_zero_days.
JIRA_TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 4, 1, 12, 0, tzinfo=JIRA_TZ)


@pytest.fixture(scope="module")
def bugs(sample_bugs_path: Path) -> list[dict]:
    # encoding="utf-8" for the same reason as test_scoring_regression.py: the
    # file holds Turkish text and a bare open() dies under a cp1254 locale.
    return json.loads(sample_bugs_path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return json.loads((TESTS_DATA / SNAPSHOT).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def module_stats(snapshot: dict) -> dict[str, dict]:
    """The snapshot's per-module payload, used as calculate_module_stats output.

    It carries two extra keys the real function does not return (risk_score,
    risk_level, added by the regression test's _score_all). The detector reads
    its four inputs with .get, so the extras are inert — and risk_level being
    present is what lets the next test cross-check _score_to_level against
    committed evidence instead of against my own arithmetic.
    """
    return snapshot["modules"]


@pytest.fixture(scope="module")
def risk_scores(module_stats: dict[str, dict]) -> dict[str, int]:
    return {name: stats["risk_score"] for name, stats in module_stats.items()}


def run(bugs, module_stats, risk_scores, *, analysis_results=None, now=NOW):
    return detect_blind_spots(
        bugs=bugs,
        module_stats=module_stats,
        analysis_results=analysis_results if analysis_results is not None else [],
        risk_scores=risk_scores,
        now=now,
    )


# =============================================================================
# Anchored on the committed sample data and snapshot
# =============================================================================

def test_sample_data_still_matches_the_snapshot_it_is_paired_with(bugs, snapshot):
    """Guard against sample drift, same as test_scoring_regression.py.

    Without it, an edit to sample_bugs.json surfaces as a spray of confusing
    per-bug diffs below instead of one clear cause.
    """
    assert len(bugs) == snapshot["_bug_count"]
    assert snapshot["_bugs_file"] == "sample_bugs.json"


def test_unanalyzed_lists_every_module_scoring_35_or_more(bugs, module_stats, risk_scores):
    """Threshold is `score >= 35`, sorted by score descending.

    Inventory (32) and Notifications (23) fall below it. Inventory sitting
    three points under the line is what makes this a boundary test and not
    just a happy path.
    """
    spots = run(bugs, module_stats, risk_scores)

    assert [(i["module"], i["risk_score"]) for i in spots["unanalyzed_risky_modules"]] == [
        ("Authentication", 100),
        ("Payment", 90),
        ("Reporting", 42),
        ("Frontend", 40),
    ]


def test_unanalyzed_risk_level_agrees_with_the_snapshot(bugs, module_stats, risk_scores):
    """_score_to_level duplicates scoring.get_risk_level with its own 80/60/35.

    The expected strings are read out of the snapshot rather than written here,
    so this fails if the private copy ever drifts from the shared thresholds.
    """
    spots = run(bugs, module_stats, risk_scores)

    for item in spots["unanalyzed_risky_modules"]:
        assert item["risk_level"] == module_stats[item["module"]]["risk_level"], item["module"]


def test_a_module_named_in_any_analysis_result_drops_out(bugs, module_stats, risk_scores):
    """Membership in analyzed_modules is an exact, case-sensitive string match
    against affected_modules — no normalisation, no fuzzy matching."""
    spots = run(
        bugs, module_stats, risk_scores,
        analysis_results=[{"affected_modules": ["Authentication", "Payment"]}],
    )

    assert [i["module"] for i in spots["unanalyzed_risky_modules"]] == ["Reporting", "Frontend"]


def test_neglected_critical_bugs_membership_and_order(bugs, module_stats, risk_scores):
    """priority in {Highest, High} AND status in {to do, open, backlog, new}.

    Sorted by (priority == "Highest", days_open) descending, so every Highest
    comes before every High regardless of age — AP-104 at 11 days outranks
    AP-501 at 31.

    days_open, from created to 2026-04-01T12:00+03:00:
        AP-201  2026-03-17T08:30  -> 15d 03h30m -> 15
        AP-102  2026-03-18T14:00  -> 13d 22h00m -> 13
        AP-104  2026-03-20T16:45  -> 11d 19h15m -> 11
        AP-501  2026-03-01T09:00  -> 31d 03h00m -> 31
        AP-103  2026-03-10T09:00  -> 22d 03h00m -> 22
        AP-106  2026-03-12T13:00  -> 19d 23h00m -> 19
        AP-101  2026-03-15T10:30  -> 17d 01h30m -> 17
        AP-202  2026-03-14T15:00  -> 17d 21h00m -> 17

    AP-105 is Highest but "In Progress", so the status filter excludes it —
    the one bug that separates the priority rule from the status rule.

    AP-101 and AP-202 both land on 17 and are ordered by sort stability, which
    preserves their order in sample_bugs.json. That is fragile, and pinned
    deliberately: if it changes, it should change visibly.
    """
    spots = run(bugs, module_stats, risk_scores)

    neglected = spots["neglected_critical_bugs"]

    assert [(i["key"], i["priority"], i["days_open"]) for i in neglected] == [
        ("AP-201", "Highest", 15),
        ("AP-102", "Highest", 13),
        ("AP-104", "Highest", 11),
        ("AP-501", "High", 31),
        ("AP-103", "High", 22),
        ("AP-106", "High", 19),
        ("AP-101", "High", 17),
        ("AP-202", "High", 17),
    ]


def test_stale_bugs_membership_and_order(bugs, module_stats, risk_scores):
    """Any open status held for >= 14 days, sorted by days_open descending.

    "Open status" is wider here than in the neglected category: it also admits
    in progress, in review and reopened. AP-203 is In Progress and still the
    oldest entry at 40 days, which is what distinguishes the two filters.

    The seven Closed bugs (AP-302/303/304, AP-502, AP-601/602/603) are excluded
    by status regardless of age — AP-602 is 100+ days old.
    """
    spots = run(bugs, module_stats, risk_scores)

    assert [(i["key"], i["days_open"]) for i in spots["stale_bugs"]] == [
        ("AP-203", 40),
        ("AP-402", 35),
        ("AP-501", 31),
        ("AP-401", 26),
        ("AP-301", 24),
        ("AP-103", 22),
        ("AP-106", 19),
        ("AP-101", 17),
        ("AP-202", 17),
        ("AP-201", 15),
    ]


def test_the_fourteen_day_staleness_line(bugs, module_stats, risk_scores):
    """>= 14, so 15 is in and 13 is out. The sample straddles the line already.

    Kept separate from the membership test above so a threshold change fails
    with a message about the threshold.
    """
    stale_keys = {i["key"] for i in run(bugs, module_stats, risk_scores)["stale_bugs"]}

    assert "AP-201" in stale_keys   # 15 days
    assert "AP-102" not in stale_keys  # 13 days
    assert "AP-104" not in stale_keys  # 11 days


def test_rising_unattended_is_empty_for_the_sample(bugs, module_stats, risk_scores):
    """Empty, and not by accident — the category is unreachable from this data.

    rising_unattended needs a module with trend "increasing" and no bug in
    "in progress" or "in review". At this clock exactly two modules trend
    increasing, Authentication and Payment, and those are exactly the two
    modules holding the sample's only worked-on bugs (AP-105, AP-203).

    So the sample can only ever prove the negative. The positive case needs
    synthetic input, below.
    """
    spots = run(bugs, module_stats, risk_scores)

    assert spots["rising_unattended"] == []
    increasing = {m for m, s in module_stats.items() if s["trend"] == "increasing"}
    assert increasing == {"Authentication", "Payment"}


def test_summary_counts(bugs, module_stats, risk_scores):
    """total_blind_spots sums the four lists; critical_spots is a narrower and
    slightly odd figure — every neglected bug (High as well as Highest) plus
    only the CRITICAL unanalyzed modules. Stale and rising never count.

        total    = 4 unanalyzed + 8 neglected + 10 stale + 0 rising = 22
        critical = 8 neglected + 2 CRITICAL modules (Auth, Payment) = 10
    """
    summary = run(bugs, module_stats, risk_scores)["summary"]

    assert summary == {
        "total_blind_spots": 22,
        "critical_spots": 10,
        "categories": {
            "unanalyzed_risky_modules": 4,
            "neglected_critical_bugs": 8,
            "stale_bugs": 10,
            "rising_unattended": 0,
        },
    }


# =============================================================================
# The Turkish sentences
#
# These four assertions move to tests/test_ui_messages.py in the commit that
# converts the detector to structural data. They are written out in full here
# so that the move is verifiable: the same strings must appear on the other
# side, proving the text was relocated rather than rewritten.
# =============================================================================

def test_unanalyzed_recommendation_sentence(bugs, module_stats, risk_scores):
    top = run(bugs, module_stats, risk_scores)["unanalyzed_risky_modules"][0]

    assert top["recommendation"] == (
        "Authentication modülü CRITICAL risk seviyesinde ancak henüz analiz "
        "edilmemiş. Canlı Analiz sayfasından analiz yapın."
    )


def test_neglected_recommendation_sentence(bugs, module_stats, risk_scores):
    top = run(bugs, module_stats, risk_scores)["neglected_critical_bugs"][0]

    assert top["recommendation"] == (
        "AP-201 — Highest öncelikli bug 15 gündür 'Open' durumunda. "
        "Acil müdahale gerekiyor."
    )


def test_stale_recommendation_sentence(bugs, module_stats, risk_scores):
    top = run(bugs, module_stats, risk_scores)["stale_bugs"][0]

    assert top["recommendation"] == (
        "AP-203 — 40 gündür açık. Çözüm süresi beklentinin üzerinde."
    )


def test_rising_recommendation_sentence():
    spots = detect_blind_spots(
        bugs=[],
        module_stats={"Search": _stats(trend="increasing", recent=5)},
        analysis_results=[],
        risk_scores={"Search": 0},
        now=NOW,
    )

    assert spots["rising_unattended"][0]["recommendation"] == (
        "Search modülünde bug sayısı artıyor (5 yeni bug) ancak üzerinde "
        "çalışılan bug yok. Bu modüle kaynak ayrılması önerilir."
    )


# =============================================================================
# Synthetic input — branches the sample data cannot reach
# =============================================================================

def _stats(*, trend="decreasing", total=4, open_bugs=4, recent=0) -> dict:
    """One module_stats entry, holding only the five keys the detector reads."""
    return {
        "total_bugs": total,
        "open_bugs": open_bugs,
        "trend": trend,
        "recent_bug_count": recent,
        "bug_density": 0.1,
    }


def _bug(key, *, component="Search", status="Open", priority="Medium", created=None) -> dict:
    return {
        "key": key,
        "summary": f"{key} summary",
        "component": component,
        "status": status,
        "priority": priority,
        "created": created or "2026-03-01T09:00:00.000+0300",
    }


def test_rising_unattended_reports_a_module_nobody_is_working_on():
    spots = detect_blind_spots(
        bugs=[_bug("S-1")],
        module_stats={"Search": _stats(trend="increasing", total=7, open_bugs=6, recent=5)},
        analysis_results=[],
        risk_scores={"Search": 0},
        now=NOW,
    )

    assert spots["rising_unattended"] == [{
        "module": "Search",
        "total_bugs": 7,
        "open_bugs": 6,
        "recent_bugs": 5,
        # Literal 0, never counted: the branch is only reached when the
        # in-progress list is empty, so the field can only ever be zero.
        "in_progress": 0,
        "recommendation": (
            "Search modülünde bug sayısı artıyor (5 yeni bug) ancak üzerinde "
            "çalışılan bug yok. Bu modüle kaynak ayrılması önerilir."
        ),
    }]


@pytest.mark.parametrize("status", ["In Progress", "In Review", "in progress", "IN REVIEW"])
def test_a_bug_being_worked_on_suppresses_the_rising_report(status):
    """Both worked-on statuses count, and the comparison is case-insensitive."""
    spots = detect_blind_spots(
        bugs=[_bug("S-1", status=status)],
        module_stats={"Search": _stats(trend="increasing", recent=5)},
        analysis_results=[],
        risk_scores={"Search": 0},
        now=NOW,
    )

    assert spots["rising_unattended"] == []


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (34, []),           # below the line
        (35, ["Search"]),   # the line itself is inclusive
        (36, ["Search"]),
    ],
)
def test_the_thirty_five_point_line_is_inclusive(score, expected):
    spots = detect_blind_spots(
        bugs=[],
        module_stats={"Search": _stats()},
        analysis_results=[],
        risk_scores={"Search": score},
        now=NOW,
    )

    assert [i["module"] for i in spots["unanalyzed_risky_modules"]] == expected


def test_a_future_created_date_clamps_to_zero_days():
    """max(0, delta.days) — a bug filed "tomorrow" is 0 days old, not negative."""
    spots = detect_blind_spots(
        bugs=[_bug("S-1", priority="Highest", created="2099-01-01T00:00:00.000+0300")],
        module_stats={},
        analysis_results=[],
        risk_scores={},
        now=NOW,
    )

    assert spots["neglected_critical_bugs"][0]["days_open"] == 0
    assert spots["stale_bugs"] == []


def test_an_unparseable_created_date_reports_zero_days():
    spots = detect_blind_spots(
        bugs=[_bug("S-1", priority="Highest", created="not a date")],
        module_stats={},
        analysis_results=[],
        risk_scores={},
        now=NOW,
    )

    assert spots["neglected_critical_bugs"][0]["days_open"] == 0


def test_a_naive_now_is_swallowed_into_zero_days(bugs, module_stats, risk_scores):
    """Characterization, not endorsement. This behaviour is wrong.

    Every sample bug carries a +0300 offset. Subtracting a naive reference from
    an aware timestamp raises TypeError, and _days_since catches TypeError and
    returns 0. So passing the snapshot's own naive "_baseline_now" makes every
    bug look brand new: stale_bugs empties out and the suite stays green.

    Pinned because it is a trap that fails silently and in the safe-looking
    direction. Recorded in KNOWN-DEBT; not fixed here, because this phase
    changes no behaviour.
    """
    naive = datetime(2026, 4, 1, 12, 0)

    spots = run(bugs, module_stats, risk_scores, now=naive)

    assert spots["stale_bugs"] == []
    assert {i["days_open"] for i in spots["neglected_critical_bugs"]} == {0}


def test_an_ancient_analysis_still_counts_a_module_as_analyzed():
    """Characterization, not endorsement. This behaviour is wrong.

    _find_unanalyzed_risky_modules has no recency window. It unions every
    affected_modules list it is handed, whatever the date on it, so a single
    analysis from years ago hides a module from this report forever. The
    developer's own data/analysis_results.json is 16 records all dated
    2026-03-23, and it is still suppressing modules today.

    Pinned so that fixing it later shows up as a visible diff on this
    assertion rather than as a quiet change in what the page lists. Recorded
    in KNOWN-DEBT.
    """
    ancient = [{
        "affected_modules": ["Search"],
        "analyzed_at": "2019-01-01T00:00:00",
    }]

    spots = detect_blind_spots(
        bugs=[],
        module_stats={"Search": _stats()},
        analysis_results=ancient,
        risk_scores={"Search": 99},
        now=NOW,
    )

    assert spots["unanalyzed_risky_modules"] == []


def test_summary_totals_only_the_four_categories():
    """total_blind_spots is built by summing every list-valued key, before the
    summary itself is inserted. Adding a fifth list to the result would change
    the total silently, so the count is pinned against a known shape."""
    spots = detect_blind_spots(
        bugs=[_bug("S-1", priority="Highest", created="2026-01-01T09:00:00.000+0300")],
        module_stats={"Search": _stats(trend="increasing", recent=2)},
        analysis_results=[],
        risk_scores={"Search": 90},
        now=NOW,
    )

    # 1 unanalyzed + 1 neglected + 1 stale + 1 rising
    assert spots["summary"]["total_blind_spots"] == 4
    # 1 neglected + 1 CRITICAL unanalyzed module
    assert spots["summary"]["critical_spots"] == 2
    assert isinstance(spots["summary"], dict)
