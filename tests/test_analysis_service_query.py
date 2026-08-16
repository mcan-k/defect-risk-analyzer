"""
How a free-text query picks the module it scores.

calculate_risk_for_query is the second of the three checks lost when
baseline/compare_service.py was retired (KNOWN-DEBT:316-343), and it has had
no coverage since. The Canlı Analiz page's "Serbest Metin" tab runs entirely
through it, and so does analyze_query at analysis_service.py:352.

It has two ways of choosing a module and they behave nothing alike:

    keyword  — the module *name* appears inside the query string
    fallback — the most common component among vector-similar bugs

Only the first is deterministic. The second reaches the vector store, which is
why this was never covered: the existing stubs return [] from query_similar and
exercise only the empty leg. RecordingVectorStore below returns controlled
similar bugs, which is what opens the fallback branch.

Two behaviours here are wrong and are pinned as characterizations, named in
their own docstrings: a keyword match that scores 0 is discarded, and the
fallback can name a module it has no score for. Neither is fixed here.

No network, no ChromaDB, no LLM: every collaborator is injected, and bugs are
seeded straight into _bugs so load_bugs() never drives the vector store —
same approach as test_analysis_service_indexing.py:preload.
"""

from typing import Any

import pytest

from defect_risk_analyzer.services.analysis_service import AnalysisService

# Two modules, deliberately different sizes so their scores differ. Statuses
# and priorities are chosen to make Authentication clearly the riskier one.
BUGS = [
    {"key": "AP-1", "summary": "login fails", "component": "Authentication",
     "priority": "Highest", "status": "Open", "created": "2026-03-15T10:00:00.000+0300"},
    {"key": "AP-2", "summary": "token expiry", "component": "Authentication",
     "priority": "Highest", "status": "Open", "created": "2026-03-16T10:00:00.000+0300"},
    {"key": "AP-3", "summary": "session drop", "component": "Authentication",
     "priority": "High", "status": "Open", "created": "2026-03-17T10:00:00.000+0300"},
    {"key": "AP-4", "summary": "refund stuck", "component": "Payment",
     "priority": "Medium", "status": "Closed", "created": "2026-03-18T10:00:00.000+0300"},
]


class RecordingVectorStore:
    """Returns a fixed similar-bug list and records what it was asked.

    Unlike the stub in test_analysis_service_breaker.py this one can return
    results, because the fallback branch is unreachable without them.
    """

    def __init__(self, similar: list[dict[str, Any]] | None = None) -> None:
        self.similar = similar or []
        self.queries: list[tuple[str, int]] = []

    def upsert_bugs(self, bugs: list[dict]) -> int:
        return len(bugs)

    def query_similar(self, query: str, n_results: int = 5) -> list[dict]:
        self.queries.append((query, n_results))
        return list(self.similar)

    def count(self) -> int:
        return len(self.similar)


def make_service(bugs=BUGS, similar=None) -> tuple[AnalysisService, RecordingVectorStore]:
    store = RecordingVectorStore(similar)
    svc = AnalysisService(vector_store=store)
    # Seeded directly: load_bugs() would drive the vector store, and these
    # tests care about which calls happen.
    svc._bugs = [dict(bug) for bug in bugs]
    return svc, store


# =============================================================================
# The early return
# =============================================================================

def test_no_bugs_at_all_scores_zero_against_unknown():
    svc, store = make_service(bugs=[])

    assert svc.calculate_risk_for_query("anything") == (0, "LOW", "Unknown")
    # The early return happens before any similarity lookup.
    assert store.queries == []


# =============================================================================
# The keyword path
# =============================================================================

def test_a_module_named_in_the_query_is_matched_without_the_vector_store():
    svc, store = make_service()

    score, level, module = svc.calculate_risk_for_query(
        "authentication is dropping sessions"
    )

    assert module == "Authentication"
    assert score > 0
    assert level in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    assert store.queries == [], "keyword match must not consult the vector store"


def test_the_match_is_the_module_name_inside_the_query_not_the_reverse():
    """`module_name.lower() in query_lower` — direction matters.

    A query shorter than the module name cannot match, however obviously it
    refers to it. "auth" does not find "Authentication".
    """
    svc, store = make_service()

    _, _, module = svc.calculate_risk_for_query("auth")

    assert module != "Authentication"


def test_matching_is_case_insensitive():
    svc, _ = make_service()

    assert svc.calculate_risk_for_query("AUTHENTICATION broken")[2] == "Authentication"


def test_the_highest_scoring_module_wins_when_several_are_named():
    """Both names appear; the comparison is on score, not on position."""
    svc, _ = make_service()

    score, _, module = svc.calculate_risk_for_query(
        "payment and authentication both look bad"
    )

    auth_stats = svc.calculate_module_stats()["Authentication"]
    assert module == "Authentication"
    assert score == svc.calculate_risk_score("Authentication", auth_stats)


# =============================================================================
# The vector fallback
# =============================================================================

def test_the_fallback_takes_the_most_common_component_among_similar_bugs():
    similar = [
        {"key": "AP-1", "component": "Authentication"},
        {"key": "AP-2", "component": "Authentication"},
        {"key": "AP-4", "component": "Payment"},
    ]
    svc, store = make_service(similar=similar)

    score, _, module = svc.calculate_risk_for_query("users cannot get in")

    assert module == "Authentication"
    assert score > 0
    assert store.queries == [("users cannot get in", 3)], "fallback asks for 3"


def test_no_similar_bugs_leaves_the_query_unattributed():
    svc, store = make_service(similar=[])

    assert svc.calculate_risk_for_query("something unrecognisable") == (0, "LOW", "Unknown")
    assert len(store.queries) == 1


def test_a_similar_bug_with_no_component_falls_back_to_unknown():
    """Counter is fed b.get("component", "Unknown"), so missing components are
    a real bucket that can win the vote."""
    svc, _ = make_service(similar=[{"key": "X-1"}, {"key": "X-2"}])

    assert svc.calculate_risk_for_query("mystery") == (0, "LOW", "Unknown")


# =============================================================================
# Characterizations — current behaviour, and wrong
# =============================================================================

def test_no_module_built_from_real_bugs_can_score_zero():
    """Why the guard below is latent rather than live — worth stating, because
    the obvious reading of the code says otherwise.

    The keyword loop uses `score > best_score` from best_score = 0, so a
    0-scoring module would be silently discarded. It never happens through
    calculate_module_stats: an unrecognised priority still weighs
    DEFAULT_PRIORITY_WEIGHT (2.5) and the lowest real weight is Low at 2.0, so
    priority_factor bottoms out at 0.4. The quietest possible module — one
    closed Low bug, decreasing trend, negligible density — still scores 11:

        (0.4 * 60 + 0.0 * 40) * 1.0 * 0.8 * 0.55 = 10.56 -> 11

    A module with no bugs at all would score 0, but it cannot appear in
    module_stats, which is built by grouping bugs.
    """
    svc, _ = make_service()

    stats = svc.calculate_module_stats()
    assert stats, "sanity: the fixture produced stats"
    for name, module_stats in stats.items():
        assert svc.calculate_risk_score(name, module_stats) > 0, name


def test_a_zero_scoring_keyword_match_would_be_discarded(monkeypatch):
    """Characterization of a latent defect, not endorsement.

    Reached here by injecting stats that score 0, which real bug data cannot
    produce (see the test above). Pinned because the guard is wrong on its own
    terms: a named module that scores 0 should be reported as 0, not treated
    as if the name never appeared. Today it falls through to the vector store
    and can come back attributed to a different module entirely.

    If a future scoring change ever lets a real module reach 0 — a new
    priority weight, a different volume factor — this becomes live silently.
    """
    zero_scoring = {
        "total_bugs": 1, "open_bugs": 0, "closed_bugs": 1, "open_ratio": 0.0,
        "bug_density": 0.0, "priority_distribution": {}, "weighted_priority_score": 0.0,
        "trend": "decreasing", "recent_bug_count": 0,
    }
    similar = [{"key": "AP-1", "component": "Authentication"}]
    svc, store = make_service(similar=similar)
    monkeypatch.setattr(
        svc, "calculate_module_stats",
        lambda: {"Payment": zero_scoring, "Authentication": zero_scoring},
    )

    assert svc.calculate_risk_score("Payment", zero_scoring) == 0

    _, _, module = svc.calculate_risk_for_query("payment refunds are stuck")

    assert store.queries, "the vector store was consulted despite a keyword hit"
    assert module == "Authentication", "the named module was discarded"


def test_the_fallback_can_name_a_module_it_has_no_score_for():
    """Characterization, not endorsement.

    best_module is taken from the similar bugs' components, but the score is
    only recomputed if that component exists in module_stats. A component that
    appears in the vector store and not in the loaded bugs is returned with a
    score of 0 — indistinguishable from "no risk" rather than "no data".
    """
    similar = [{"key": "Z-1", "component": "Warehouse"}]
    svc, _ = make_service(similar=similar)

    assert svc.calculate_risk_for_query("pallets are missing") == (0, "LOW", "Warehouse")


@pytest.mark.parametrize("query", ["", "   "])
def test_an_empty_query_still_goes_through_the_fallback(query):
    """No guard on the query itself: "" contains no module name, so it reaches
    the vector store like any other unmatched string."""
    svc, store = make_service(similar=[])

    assert svc.calculate_risk_for_query(query) == (0, "LOW", "Unknown")
    assert len(store.queries) == 1
