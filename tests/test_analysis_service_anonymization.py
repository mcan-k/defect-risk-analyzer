"""The masking round trip, end to end, with the REAL anonymizer.

WHY THIS FILE EXISTS. Faz 6B Adım 3 wrapped the analysis path in
`DataAnonymizer.session()`, and while doing so the suite stayed green with
`DataAnonymizer.anonymize_query` deleted outright. That is not a passing grade,
it is a blind spot: `test_analysis_service_breaker.py` injects a
`StubAnonymizer` whose transforms are the identity, so no test anywhere drove
the real class through the service. A path this PR changes must not be left
that way — the next change to it would repeat exactly the defect Adım 3 caught.

So this file injects everything EXCEPT the anonymizer. StubAnonymizer stays
where it is; the breaker file is about the circuit breaker and should keep
saying nothing about masking.

NO NETWORK, NO ChromaDB, NO LLM. The vector store, the repository and the
provider are stubs. The provider records the prompt it was handed and echoes a
token back, which is what a real model does when it refers to a masked value.

NO REAL SECRETS. `alice@example.invalid` is synthetic and the TLD is reserved.
"""

import re

import pytest

from defect_risk_analyzer import config
from defect_risk_analyzer.services.analysis_service import AnalysisService

REPORTER = "alice@example.invalid"

BUGS = [
    {"key": "AP-1", "summary": "checkout fails", "component": "Payment",
     "priority": "High", "status": "Open", "created": "2026-03-15T10:00:00.000+0300"},
    {"key": "AP-2", "summary": "login slow", "component": "Authentication",
     "priority": "Medium", "status": "Open", "created": "2026-03-16T10:00:00.000+0300"},
]

_EMAIL_TOKEN_RE = re.compile(r"\[EMAIL_\d{3}\]")


class StubVectorStore:
    """No ChromaDB. Returns no neighbours, so no similarity plumbing runs."""

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

    def upsert_result(self, result: dict) -> bool:
        self.results.append(result)
        return True

    def save_defect_density(self, density: dict) -> bool:
        return True

    def load_results(self) -> list[dict]:
        return list(self.results)


class EchoingLLM:
    """Records the prompt, then answers referring to the token it was given.

    Echoing rather than returning a fixed string is the whole point: the
    de-anonymization half has nothing to do unless the answer actually carries
    a token, and a fixed reply would let a broken `deanonymize_text` pass.
    """

    def __init__(self) -> None:
        self.user_prompt: str | None = None

    def analyze(self, system_prompt: str, user_prompt: str) -> dict:
        self.user_prompt = user_prompt
        match = _EMAIL_TOKEN_RE.search(user_prompt)
        seen = match.group() if match else "nobody"
        return {
            "reasoning": f"Ask {seen} to reproduce it.",
            "affected_modules": ["Payment"],
            "test_scenarios": ["retry checkout"],
            "recommended_actions": ["add a regression test"],
        }


@pytest.fixture
def make_service(monkeypatch):
    """An AnalysisService with a REAL DataAnonymizer and everything else stubbed."""
    monkeypatch.setattr(config, "GROQ_SLEEP", 0)
    monkeypatch.setattr(config, "ANONYMIZE_DATA", True)

    def _build(llm: EchoingLLM) -> AnalysisService:
        service = AnalysisService(
            vector_store=StubVectorStore(),
            repository=StubRepository(),
            llm=llm,
            # anonymizer deliberately NOT injected — the real one is the subject.
        )
        service._bugs = list(BUGS)
        return service

    return _build


def test_the_masking_round_trip_runs_end_to_end(make_service):
    """EXPECTED GREEN once Adım 3 is in; RED without the session() wiring.

    Both halves in one assertion set, because either alone can pass while the
    feature is broken: masking with no restore leaves the user reading
    `[EMAIL_001]`, and restoring with no masking means the address went to the
    provider.
    """
    llm = EchoingLLM()
    service = make_service(llm)

    result = service.analyze_bug(
        query=f"who owns {REPORTER}",
        bug_data={"key": "AP-1", "summary": f"escalated by {REPORTER}",
                  "component": "Payment"},
    )

    # Outbound: the provider saw a token, never the address.
    assert llm.user_prompt is not None, "the provider was never called"
    assert REPORTER not in llm.user_prompt
    assert _EMAIL_TOKEN_RE.search(llm.user_prompt), "nothing was masked"

    # Inbound: the answer came back with the real value restored.
    assert result["reasoning"] == f"Ask {REPORTER} to reproduce it."


def test_the_query_and_the_bug_share_one_token(make_service):
    """EXPECTED GREEN.

    The same address appears in the free-text query and in the bug record. One
    scope per call means one token for both; two tokens would show the model
    two unrelated people and is what a per-string reset would produce.
    """
    llm = EchoingLLM()
    service = make_service(llm)

    service.analyze_bug(
        query=f"who owns {REPORTER}",
        bug_data={"key": "AP-1", "summary": f"escalated by {REPORTER}",
                  "component": "Payment"},
    )

    tokens = set(_EMAIL_TOKEN_RE.findall(llm.user_prompt))
    assert len(tokens) == 1, f"expected one EMAIL token, got {sorted(tokens)}"


def test_the_stored_query_is_not_masked(make_service):
    """EXPECTED GREEN — and it pins a LIMITATION, not a feature.

    `analyze_bug` stores the caller's raw `query` in the result, and the result
    goes to `data/analysis_results.json`. Masking protects what leaves for the
    provider; it does not protect what is written to disk. SECURITY.md says so,
    and this test is what keeps that sentence true — if someone later masks the
    stored copy, this goes red and the document has to be corrected with it.
    """
    llm = EchoingLLM()
    service = make_service(llm)

    result = service.analyze_bug(query=f"who owns {REPORTER}")

    assert result["query"] == f"who owns {REPORTER}"


def test_masking_off_sends_the_address_to_the_provider(make_service, monkeypatch):
    """EXPECTED GREEN. The ANONYMIZE_DATA switch actually switches.

    Pinned because the setting is user-facing: the Settings page offers it, and
    a toggle that silently does nothing either way would be worse than not
    offering it.
    """
    monkeypatch.setattr(config, "ANONYMIZE_DATA", False)
    llm = EchoingLLM()
    service = make_service(llm)

    result = service.analyze_bug(query=f"who owns {REPORTER}")

    assert REPORTER in llm.user_prompt
    assert not _EMAIL_TOKEN_RE.search(llm.user_prompt)
    assert result["reasoning"] == "Ask nobody to reproduce it."
