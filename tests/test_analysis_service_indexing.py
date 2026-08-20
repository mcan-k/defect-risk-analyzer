"""
When AnalysisService writes to the vector store, and when it deliberately does not.

Two separate holes, both about the same thing — the service driving an expensive,
destructive index for callers that did not ask for one.

The first is a bug. `refresh()` passed refresh_data()'s result straight into
load_bugs() with no check (analysis_service.py:117-118), while every other caller
of load_bugs guards with `if bugs:` (api.py:99, ui/service.py get_service()).
refresh_data()
returns [] for a missing bugs.json, an unreadable one, and an unconfigured Jira
alike (jira_client.py:329-334, :383-385), so a misconfigured install turned
`POST /refresh` and the dashboard's sync button into a delete: the empty list
reached upsert_bugs(), which reset the collection before checking it.

The second is waste. ci_analyzer only ever calls calculate_module_stats() and
calculate_risk_score(); it never runs a similarity query, and CI starts on a
clean machine every run, so every run is a first run and there is nothing for a
diff to save. It paid for a full re-embed of the bug history and read none of it.

No ChromaDB here either: the vector store is a recording stub, and the point of
most of these tests is what it does *not* receive.
"""

from typing import Any

import pytest

from defect_risk_analyzer import jira_client
from defect_risk_analyzer.services.analysis_service import AnalysisService

BUGS = [
    {
        "key": "AP-1",
        "summary": "Login fails",
        "component": "Authentication",
        "priority": "High",
        "status": "Open",
        "created": "2026-01-01",
    },
    {
        "key": "AP-2",
        "summary": "Checkout times out",
        "component": "Payments",
        "priority": "Medium",
        "status": "Closed",
        "created": "2026-01-02",
    },
]


class StubVectorStore:
    """Records what the service asks of the vector store. No ChromaDB.

    Unlike the stub in test_analysis_service_breaker.py this one keeps the
    calls, because here the absence of a call is the assertion.
    """

    def __init__(self) -> None:
        self.upsert_calls: list[list[dict[str, Any]]] = []

    def upsert_bugs(self, bugs: list[dict]) -> int:
        self.upsert_calls.append(list(bugs))
        return len(bugs)

    def query_similar(self, query: str, n_results: int = 5) -> list[dict]:
        return []

    def count(self) -> int:
        return 0


@pytest.fixture
def service() -> tuple[AnalysisService, StubVectorStore]:
    """A service whose only stubbed collaborator is the vector store.

    The repository and the anonymizer are left real: neither is reached by
    anything here, and ResultsRepository's constructor only resolves paths.
    """
    store = StubVectorStore()
    return AnalysisService(vector_store=store), store


def preload(svc: AnalysisService, bugs: list[dict]) -> None:
    """Seed the in-memory bug list without going through load_bugs().

    Same reason as test_analysis_service_breaker.py:105-107: load_bugs() would
    also drive the vector store, and these tests count those calls.
    """
    svc._bugs = [dict(bug) for bug in bugs]


# =============================================================================
# refresh() — an empty fetch must not reach the index
# =============================================================================


def test_an_empty_fetch_leaves_the_index_and_the_bug_list_alone(service, monkeypatch):
    """A4 — the bug: a broken Jira config used to delete the index.

    Both halves matter. The index must survive, and so must the bugs already in
    memory: blanking those turns every dashboard page into "no data" until the
    process restarts.
    """
    svc, store = service
    preload(svc, BUGS)
    monkeypatch.setattr(jira_client, "refresh_data", lambda: [])

    result = svc.refresh()

    assert store.upsert_calls == [], "an empty fetch must not reach the vector store"
    assert [bug["key"] for bug in svc.get_bugs()] == ["AP-1", "AP-2"]
    assert result["bugs_fetched"] == 0
    assert result["bugs_loaded"] == 0
    assert result["reindexed"] is False


def test_a_successful_fetch_still_reindexes(service, monkeypatch):
    """A5 — guards A4 against passing because refresh() stopped working.

    Without this, deleting the body of refresh() entirely would leave A4 green.
    """
    svc, store = service
    monkeypatch.setattr(jira_client, "refresh_data", lambda: [dict(b) for b in BUGS])

    result = svc.refresh()

    assert len(store.upsert_calls) == 1
    assert [bug["key"] for bug in store.upsert_calls[0]] == ["AP-1", "AP-2"]
    assert result["bugs_fetched"] == 2
    assert result["bugs_loaded"] == 2
    assert result["reindexed"] is True


def test_reindexed_distinguishes_a_skip_from_a_genuinely_empty_result(service, monkeypatch):
    """Both outcomes report bugs_loaded 0, so something else has to tell them apart.

    The layer cannot distinguish "the fetch failed" from "there really are no
    bugs" — load_bugs_from_file() returns [] for a missing file, an unreadable
    file and a file holding [] alike — so it always takes the conservative
    reading and says which one it took. Callers that need the destructive
    reading have to ask for it explicitly, via reset().
    """
    svc, _ = service
    monkeypatch.setattr(jira_client, "refresh_data", lambda: [])

    skipped = svc.refresh()

    assert skipped["bugs_loaded"] == 0
    assert skipped["reindexed"] is False


# =============================================================================
# load_bugs(index=...) — loading without paying for an index
# =============================================================================


def test_loading_bugs_indexes_them_by_default(service):
    """A1 — the default must not have changed.

    Also guards A2: without this, flipping the default to False would leave A2
    green while silently stopping the dashboard and the API from indexing
    anything at all.
    """
    svc, store = service

    loaded = svc.load_bugs([dict(b) for b in BUGS])

    assert len(store.upsert_calls) == 1
    assert loaded == 2
    assert [bug["key"] for bug in svc.get_bugs()] == ["AP-1", "AP-2"]


def test_index_false_skips_the_vector_store_entirely(service):
    """A2 — what ci_analyzer asks for.

    The bugs still land in memory, which is all the deterministic scoring path
    reads; the vector store is never called, so ChromaDB is never initialised
    and data/chroma_db is never created.
    """
    svc, store = service

    loaded = svc.load_bugs([dict(b) for b in BUGS], index=False)

    assert store.upsert_calls == []
    assert loaded == 0, "nothing was indexed, so nothing is reported as indexed"
    assert [bug["key"] for bug in svc.get_bugs()] == ["AP-1", "AP-2"]


def test_classification_still_runs_when_indexing_is_off(service):
    """A3 — skipping the index must not skip classify_bugs().

    core/scoring.py:99 groups bugs by `component`, and classify_bugs() is what
    fills that in when Jira left it empty. Skipping it would file every such bug
    under "Unknown", so ci_analyzer would match a module, find no history for it
    and report NOT ASSESSED on data it actually has. That failure looks like
    correct output, which is why it is pinned rather than assumed.
    """
    svc, store = service
    unclassified = {
        "key": "AP-9",
        "summary": "Login page rejects a valid password",
        "component": "",
        "priority": "High",
        "status": "Open",
        "created": "2026-01-01",
    }

    svc.load_bugs([unclassified], index=False)

    assert store.upsert_calls == []
    stats = svc.calculate_module_stats()
    assert "Authentication" in stats, "an empty component must still be classified"
    assert "Unknown" not in stats
