"""
A result that could not be saved (Faz 6E-2, PR 12) — documented, not fixed.

KNOWN-DEBT, "Failed result writes are logged, not surfaced". `_write_json`
catches the OSError, logs it and returns False; AnalysisService logs a WARNING
and returns the result exactly as it returns a saved one. Measured at b7713e0
with a repository whose files cannot be written (their parent is a regular
file, so `mkdir` raises — the same on Windows, Linux and for root):

  * POST /analyze, /analyze/bulk and /webhook/jira answer 200 with the full
    result, and nothing in the response differs from a saved one; bulk counts
    the unsaved results as `analyzed`;
  * the result is not on disk afterwards; only the server log knows.

The dashboard's face of the same defect is in tests/test_dashboard_pages.py.

A second face was measured in the same PR (PLAN DIŞI): `_write_json` opens the
target itself with "w", so a write that fails part way — disk full — leaves a
truncated file. The next read quarantines it, and the quarantined copy is the
truncated one: the history that was on disk before the write is gone for good.

All four are xfail(strict) under K-E3: the fix is 6E-2's next PR. Any change to
what the endpoints answer is the user's decision first (the permanent api.py
rule), so the API assertions below are design-neutral: they only require that a
caller CAN tell an unsaved result from a saved one — by status, body or headers.

Same isolation as tests/test_api_error_responses.py: `api.analyzer` swapped
through monkeypatch, the API-key dependency through dependency_overrides, no
lifespan; every collaborator but the repository is a stub.
"""

import builtins
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_analysis_service_breaker import (  # sibling module, not a package
    BUGS,
    StubAnonymizer,
    StubLLM,
    StubVectorStore,
)

from defect_risk_analyzer import api, config
from defect_risk_analyzer.adapters import results_repository as results_repository_module
from defect_risk_analyzer.adapters.results_repository import ResultsRepository
from defect_risk_analyzer.api_auth import require_api_key
from defect_risk_analyzer.services.analysis_service import AnalysisService

_REASON = (
    "Bilinen kusur: kaydedilemeyen analiz sonucu yalnız günlüğe gidiyor "
    "(KNOWN-DEBT.md, 'Failed result writes are logged, not surfaced'; "
    "6E-2 PR12'de ölçüldü, düzeltme 6E-2'nin ikinci PR'ı)"
)

WEBHOOK_BUG = {
    "webhookEvent": "jira:issue_created",
    "issue": {
        "key": "AP-9",
        "fields": {
            "issuetype": {"name": "Bug"},
            "summary": "Login fails",
            "components": [{"name": "Authentication"}],
        },
    },
}

# Headers that differ between any two responses whatever was saved.
_VOLATILE_HEADERS = {"date", "content-length"}


def _repository(directory: Path) -> ResultsRepository:
    return ResultsRepository(
        results_file=directory / "analysis_results.json",
        webhook_results_file=directory / "webhook_results.json",
        defect_density_file=directory / "defect_density.json",
    )


def _blocked_repository(tmp_path: Path) -> ResultsRepository:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    return _repository(blocker)


def _service(repository: ResultsRepository) -> AnalysisService:
    service = AnalysisService(
        vector_store=StubVectorStore(),
        repository=repository,
        anonymizer=StubAnonymizer(),
        llm=StubLLM(),
    )
    service.load_bugs([dict(bug) for bug in BUGS], index=False)
    return service


def _without_timestamps(value):
    """`analyzed_at` differs between any two runs; nothing else should."""
    if isinstance(value, dict):
        return {k: _without_timestamps(v) for k, v in value.items() if k != "analyzed_at"}
    if isinstance(value, list):
        return [_without_timestamps(v) for v in value]
    return value


def _answer(monkeypatch, repository, path, body):
    """What a caller sees: status, body (timestamps out) and stable headers."""
    monkeypatch.setattr(api, "analyzer", _service(repository))
    response = TestClient(api.app).post(path, json=body)
    headers = {
        name.lower(): value
        for name, value in response.headers.items()
        if name.lower() not in _VOLATILE_HEADERS
    }
    return response.status_code, _without_timestamps(response.json()), headers


@pytest.fixture(autouse=True)
def _no_api_key_no_sleep(monkeypatch):
    monkeypatch.setitem(api.app.dependency_overrides, require_api_key, lambda: "test-key")
    # GROQ_SLEEP defaults to 2.0 and is read at call time (test_analysis_service_breaker).
    monkeypatch.setattr(config, "GROQ_SLEEP", 0)


@pytest.mark.xfail(strict=True, reason=_REASON)
@pytest.mark.parametrize(
    "path,body,saved_file",
    [
        ("/analyze", {"bug_key": "AP-1"}, "analysis_results.json"),
        ("/analyze/bulk", {"bug_keys": ["AP-1", "AP-2"]}, "analysis_results.json"),
        ("/webhook/jira", WEBHOOK_BUG, "webhook_results.json"),
    ],
    ids=["analyze", "analyze-bulk", "webhook"],
)
def test_a_caller_can_tell_an_unsaved_result_from_a_saved_one(
    monkeypatch, tmp_path, path, body, saved_file
):
    saved_directory = tmp_path / "saved"
    saved = _answer(monkeypatch, _repository(saved_directory), path, body)
    assert saved[0] == 200, f"precondition: the saved request succeeds, got {saved}"
    assert (saved_directory / saved_file).is_file(), "precondition: the result was saved"

    blocked = _blocked_repository(tmp_path)
    unsaved = _answer(monkeypatch, blocked, path, body)
    assert blocked.load_results() == [] and blocked.load_webhook_results() == [], (
        "precondition: nothing was saved"
    )

    assert unsaved != saved, (
        f"{path}: a result that was not saved is answered exactly like one that was"
    )


@pytest.mark.xfail(strict=True, reason=_REASON)
def test_a_write_that_fails_part_way_keeps_the_history_it_replaces(tmp_path, monkeypatch):
    """Disk full on the fourth chunk json.dump writes. Measured at b7713e0: the
    file is cut to its first chunks, the next read moves that cut file aside,
    and the two results that were on disk before the write are in neither."""
    repository = _repository(tmp_path)
    old = [{"bug_key": "OLD-1", "risk_score": 10}, {"bug_key": "OLD-2", "risk_score": 20}]
    for result in old:
        assert repository.upsert_result(result) is True
    real_open = builtins.open

    class _FillsUp:
        """A file object whose fourth write raises ENOSPC."""

        def __init__(self, handle):
            self._handle = handle
            self._writes = 0

        def write(self, text):
            self._writes += 1
            if self._writes > 3:
                raise OSError(28, "No space left on device")
            return self._handle.write(text)

        def __getattr__(self, name):
            return getattr(self._handle, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return self._handle.__exit__(*exc_info)

    def filling_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        return _FillsUp(handle) if "w" in mode else handle

    # Module-level `open` shadows the builtin for results_repository only.
    with monkeypatch.context() as patch:
        patch.setattr(results_repository_module, "open", filling_open, raising=False)
        assert repository.upsert_result({"bug_key": "NEW-1", "risk_score": 30}) is False

    assert repository.load_results() == old, (
        "a write that failed part way destroyed the history it was replacing"
    )
