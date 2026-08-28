"""
Circuit breaker behaviour in AnalysisService.analyze_bulk.

This is the one behaviour in analysis_service.py that Faz 3 covers, and it
exists because the except-block order there is load-bearing:

    except RateLimitError:   # circuit breaker: abandon the whole run
    except LLMError as e:    # skip this one bug
    except Exception as e:   # skip this one bug

The trailing `except Exception` is what makes the order matter. Move the
RateLimitError clause below it and every 429 quietly becomes "skip one bug":
the run keeps going, keeps hitting a spent quota, and circuit_breaker_triggered
stays False. Nothing raises, nothing logs an error — the failure mode the
breaker exists to prevent.

No network, no ChromaDB, no Jira, no config.init(). Every collaborator is
injected, so AnalysisService never constructs a real one.
"""

import contextlib
import time

import pytest

from defect_risk_analyzer import config
from defect_risk_analyzer.llm_provider import LLMError, RateLimitError
from defect_risk_analyzer.services.analysis_service import AnalysisService

BUGS = [
    {"key": "AP-1", "summary": "first", "component": "Authentication",
     "priority": "High", "status": "Open", "created": "2026-03-15T10:00:00.000+0300"},
    {"key": "AP-2", "summary": "second", "component": "Payment",
     "priority": "Highest", "status": "Open", "created": "2026-03-16T10:00:00.000+0300"},
    {"key": "AP-3", "summary": "third", "component": "Frontend",
     "priority": "Medium", "status": "Open", "created": "2026-03-17T10:00:00.000+0300"},
]

ALL_KEYS = ["AP-1", "AP-2", "AP-3"]


class StubVectorStore:
    """No ChromaDB. query_similar returns nothing, so no similarity plumbing runs."""

    def upsert_bugs(self, bugs: list[dict]) -> int:
        return len(bugs)

    def query_similar(self, query: str, n_results: int = 5) -> list[dict]:
        return []

    def count(self) -> int:
        return 0


class StubRepository:
    """No disk writes. Records what would have been persisted."""

    def __init__(self) -> None:
        self.results: list[dict] = []
        self.density: list[dict] = []

    def upsert_result(self, result: dict) -> bool:
        self.results.append(result)
        return True

    def save_defect_density(self, density: dict) -> bool:
        self.density.append(density)
        return True

    def load_results(self) -> list[dict]:
        return list(self.results)


class StubAnonymizer:
    """Identity transforms — anonymization is not what this test is about.

    Carries `session()` because Faz 6B moved the mapping into a per-call scope:
    the service now opens one and calls the transforms on what it yields. The
    stub yields itself, so the identity behaviour is unchanged and this file
    still says nothing about anonymization.
    """

    @contextlib.contextmanager
    def session(self):
        yield self

    def anonymize_query(self, query: str) -> str:
        return query

    def anonymize_bugs(self, bugs: list[dict]) -> list[dict]:
        return list(bugs)

    def deanonymize_text(self, text: str) -> str:
        return text


class StubLLM:
    """Raises `error` on exactly one call; every other call succeeds.

    Failing on a single call rather than "this call and all later ones" is what
    makes the contrast test meaningful: it lets AP-3 succeed after AP-2 failed,
    so "the run continued" is observable rather than inferred.
    """

    def __init__(self, error: Exception | None = None, fail_on_call: int | None = None) -> None:
        self._error = error
        self._fail_on_call = fail_on_call
        self.calls = 0

    def analyze(self, system_prompt: str, user_prompt: str) -> dict:
        self.calls += 1
        if self._error is not None and self.calls == self._fail_on_call:
            raise self._error
        return {
            "reasoning": "stub",
            "affected_modules": [],
            "test_scenarios": [],
            "recommended_actions": [],
        }


@pytest.fixture
def make_service(monkeypatch):
    """Build an AnalysisService with every collaborator stubbed.

    GROQ_SLEEP defaults to 2.0 and _call_llm sleeps that long before each
    request, which would make this test take 6 seconds. analysis_service.py
    does `from defect_risk_analyzer import config` and reads config.GROQ_SLEEP
    at call time, so patching the attribute on the module object takes effect.
    (Had it done `from ...config import GROQ_SLEEP`, the name would be bound at
    import time and this patch would be a silent no-op — hence the wall-clock
    assertion in test_bulk_run_is_not_sleeping below.)
    """
    monkeypatch.setattr(config, "GROQ_SLEEP", 0)

    def _build(llm: StubLLM) -> AnalysisService:
        service = AnalysisService(
            vector_store=StubVectorStore(),
            repository=StubRepository(),
            anonymizer=StubAnonymizer(),
            llm=llm,
        )
        # Assign directly rather than load_bugs(), which would also drive the
        # vector store and the component classifier.
        service._bugs = list(BUGS)
        return service

    return _build


# ===========================================================================
# The breaker
# ===========================================================================

def test_rate_limit_trips_the_circuit_breaker(make_service):
    """One 429 abandons the run: the quota is gone, continuing only burns time.

    This is the test that fails if the `except RateLimitError` clause is moved
    below `except Exception`.
    """
    llm = StubLLM(RateLimitError("simulated 429", retry_after_seconds=0), fail_on_call=2)
    service = make_service(llm)

    result = service.analyze_bulk(ALL_KEYS)

    assert result["circuit_breaker_triggered"] is True
    assert result["analyzed"] == 1
    assert result["skipped"] == 2
    # The bug that hit the limit, plus every key after it.
    assert result["skipped_keys"] == ["AP-2", "AP-3"]
    # AP-3 was never attempted — that is the point of the breaker.
    assert llm.calls == 2


def test_llm_error_does_not_trip_the_circuit_breaker(make_service):
    """The contrast case.

    Without this, test_rate_limit_trips_the_circuit_breaker would still pass
    against a breaker that tripped on *any* error — which would be a different
    bug, not a working breaker.
    """
    llm = StubLLM(LLMError("model exploded"), fail_on_call=2)
    service = make_service(llm)

    result = service.analyze_bulk(ALL_KEYS)

    assert result["circuit_breaker_triggered"] is False
    assert result["analyzed"] == 2      # AP-1 and AP-3 both succeeded
    assert result["skipped_keys"] == ["AP-2"]
    assert llm.calls == 3               # AP-3 was still attempted


def test_unexpected_error_does_not_trip_the_circuit_breaker(make_service):
    """A non-LLM exception skips one bug via the trailing `except Exception`."""
    llm = StubLLM(ValueError("something else"), fail_on_call=2)
    service = make_service(llm)

    result = service.analyze_bulk(ALL_KEYS)

    assert result["circuit_breaker_triggered"] is False
    assert result["skipped_keys"] == ["AP-2"]
    assert result["analyzed"] == 2


def test_unknown_key_is_skipped_without_tripping_the_breaker(make_service):
    llm = StubLLM()
    service = make_service(llm)

    result = service.analyze_bulk(["AP-1", "NOPE-999", "AP-3"])

    assert result["circuit_breaker_triggered"] is False
    assert result["skipped_keys"] == ["NOPE-999"]
    assert result["analyzed"] == 2
    assert llm.calls == 2   # the unknown key never reached the LLM


def test_all_keys_succeed_when_nothing_raises(make_service):
    llm = StubLLM()
    service = make_service(llm)

    result = service.analyze_bulk(ALL_KEYS)

    assert result["circuit_breaker_triggered"] is False
    assert result["analyzed"] == 3
    assert result["skipped_keys"] == []
    assert result["total"] == 3


# ===========================================================================
# The GROQ_SLEEP patch really lands
# ===========================================================================

def test_bulk_run_is_not_sleeping(make_service):
    """Fails loudly if the GROQ_SLEEP monkeypatch ever stops taking effect.

    Without the patch this run sleeps 2s per bug. A test that merely got slower
    would still pass, so the budget is asserted rather than assumed.
    """
    llm = StubLLM()
    service = make_service(llm)

    started = time.monotonic()
    service.analyze_bulk(ALL_KEYS)
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, (
        f"analyze_bulk took {elapsed:.1f}s for 3 bugs. config.GROQ_SLEEP is "
        "probably no longer being patched — check whether analysis_service "
        "still reads it as a module attribute at call time."
    )
