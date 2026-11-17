"""
What api.py answers when an analysis endpoint fails (Faz 6E-2, PR 7).

User decision 3a, 2026-11-17: the 500 branches below get the fixed-sentence
treatment POST /refresh got in PR6. The status code stays what it was; the
detail becomes "<operation> failed; see server log."; the exception's own text
goes to the server log through logger.exception. Before, each detail carried
f"...: {e}" — and an exception's text can be a file path (on Windows, under the
account name) or a piece of an LLM provider's reply.

The branches, all 500:
  * POST /analyze, LLMError                 "LLM analysis failed; ..."
  * POST /analyze, any other exception       "Analysis failed; ..."
  * POST /webhook/jira, any exception        "Webhook analysis failed; ..."
  * GET /patterns, any exception             "Pattern detection failed; ..."
  * GET /patterns/{bug_key}/duplicates       "Duplicate search failed; ..."
  * GET /blind-spots, any exception          "Blind spot detection failed; ..."

Out of scope by decision 4a (v1.1): the 4xx branches of /analyze (ValueError,
BugNotFoundError, RateLimitError) and the webhook's 429. Nothing here touches
them.

The sentences are written out as literals, not imported from api.py: a test
that compared the response with the module's own constant would pass whatever
the constant said.

Same isolation as tests/test_api_refresh.py: `api.analyzer` swapped through
monkeypatch, the API-key dependency through dependency_overrides, no lifespan.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from defect_risk_analyzer import api
from defect_risk_analyzer.api_auth import require_api_key
from defect_risk_analyzer.llm_provider import LLMError
from defect_risk_analyzer.services.analysis_service import AnalysisService

# Spelled out so the assertions can look for it on both sides.
PRIVATE_PATH = r"C:\Users\someone-private\defect-risk-analyzer\data\bugs.json"
MARKER = "someone-private"

WEBHOOK_BUG = {
    "webhookEvent": "jira:issue_created",
    "issue": {
        "key": "AP-9",
        "fields": {"issuetype": {"name": "Bug"}, "summary": "Login fails"},
    },
}


class NoStore:
    """Vector store stand-in. The analyzer methods under test are replaced."""


def _os_error():
    return PermissionError(13, "Permission denied", PRIVATE_PATH)


# (id, method, path, json body, analyzer method that fails, exception, status, detail)
CASES = [
    (
        "analyze-llm-error", "post", "/analyze", {"query": "login"},
        "analyze", lambda: LLMError(f"provider said: {PRIVATE_PATH}"),
        500, "LLM analysis failed; see server log.",
    ),
    (
        "analyze-other-error", "post", "/analyze", {"query": "login"},
        "analyze", _os_error,
        500, "Analysis failed; see server log.",
    ),
    (
        "webhook", "post", "/webhook/jira", WEBHOOK_BUG,
        "analyze_bug_for_webhook", _os_error,
        500, "Webhook analysis failed; see server log.",
    ),
    (
        "patterns", "get", "/patterns", None,
        "detect_patterns", _os_error,
        500, "Pattern detection failed; see server log.",
    ),
    (
        "duplicates", "get", "/patterns/AP-1/duplicates", None,
        "find_duplicate_bugs", _os_error,
        500, "Duplicate search failed; see server log.",
    ),
    (
        "blind-spots", "get", "/blind-spots", None,
        "detect_blind_spots", _os_error,
        500, "Blind spot detection failed; see server log.",
    ),
]


@pytest.fixture
def analyzer(monkeypatch):
    service = AnalysisService(vector_store=NoStore())
    monkeypatch.setattr(api, "analyzer", service)
    monkeypatch.setitem(api.app.dependency_overrides, require_api_key, lambda: "test-key")
    return service


@pytest.mark.parametrize(
    "method,path,body,failing,make_error,status_code,detail",
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_a_failed_endpoint_answers_a_fixed_sentence_and_logs_the_error(
    analyzer, monkeypatch, caplog, method, path, body, failing, make_error, status_code, detail
):
    error = make_error()

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(analyzer, failing, fail)
    # /duplicates looks the bug up before the try block; a miss is its 404.
    monkeypatch.setattr(analyzer, "get_bug", lambda key: {"key": key, "summary": "x"})
    client = TestClient(api.app, raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR, logger="defect_risk_analyzer.api"):
        response = client.request(method, path, json=body)

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert MARKER not in response.text
    assert MARKER in caplog.text, "the details must still reach the log"
    logged = [
        r for r in caplog.records
        if r.name == "defect_risk_analyzer.api" and r.levelno == logging.ERROR
    ]
    assert [r.exc_info[1] for r in logged if r.exc_info] == [error], (
        "one ERROR record carrying the exception and its traceback"
    )
