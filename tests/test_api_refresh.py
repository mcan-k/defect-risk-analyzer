"""
POST /refresh when the Jira fetch fails or is cut short (Faz 6E-2, PR 5).

api.py's code did not change in that PR, but what the endpoint answers did,
because AnalysisService.refresh() changed under it (user decisions of
2026-11-13, "kullanıcı başarısız bir işlemi başarılı sanmamalı"):

  * a failed Jira page used to come back as 200 "ok" — with a partial list
    saved, or with nothing; JiraFetchError now reaches the endpoint's existing
    except branch, so the caller gets its existing 500 shape;
  * a fetch cut short by the page cap now says so in an added `truncated` field.
    The fields that were there are unchanged.

The webhook (POST /webhook/jira) never fetches from Jira and is not involved.

The suite had no HTTP test of api.py (KNOWN-DEBT, "6E keşfinde bulunan küçük
test boşlukları"): the module builds an `analyzer` singleton at import and every
route carries an API-key dependency. Both are swapped here, through
monkeypatch and FastAPI's dependency_overrides. No lifespan runs — TestClient is
not used as a context manager — so nothing reads .env or loads bug data, and the
vector store is a counting stub: no ChromaDB.
"""

import pytest
from fastapi.testclient import TestClient

from defect_risk_analyzer import api, jira_client
from defect_risk_analyzer.api_auth import require_api_key
from defect_risk_analyzer.jira_client import FetchResult, JiraFetchError
from defect_risk_analyzer.services.analysis_service import AnalysisService

BUGS = [
    {"key": "AP-1", "summary": "Login fails", "component": "Authentication",
     "priority": "High", "status": "Open", "created": "2026-01-01"},
    {"key": "AP-2", "summary": "Checkout times out", "component": "Payment",
     "priority": "Medium", "status": "Closed", "created": "2026-01-02"},
]


class CountingStore:
    """Vector store stand-in: reports how many bugs it was given, embeds nothing."""

    def upsert_bugs(self, bugs):
        return len(bugs)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "analyzer", AnalysisService(vector_store=CountingStore()))
    monkeypatch.setitem(api.app.dependency_overrides, require_api_key, lambda: "test-key")
    return TestClient(api.app, raise_server_exceptions=False)


def test_a_failed_jira_page_is_a_500_not_an_ok(client, monkeypatch):
    def failed_fetch():
        raise JiraFetchError(1)

    monkeypatch.setattr(jira_client, "refresh_data", failed_fetch)

    response = client.post("/refresh")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Refresh failed: Jira search failed on page 1; nothing was saved."
    }


def test_a_fetch_cut_by_the_page_cap_says_so(client, monkeypatch):
    monkeypatch.setattr(
        jira_client, "refresh_data", lambda: FetchResult([dict(b) for b in BUGS], True)
    )

    response = client.post("/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is True
    assert {k: body[k] for k in ("status", "bugs_fetched", "bugs_loaded", "reindexed")} == {
        "status": "ok", "bugs_fetched": 2, "bugs_loaded": 2, "reindexed": True,
    }
