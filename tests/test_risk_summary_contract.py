"""
The defect density contract behind GET /risks.

Third of the three checks lost when baseline/compare_service.py was retired
(KNOWN-DEBT:316-343). There is no `defect_density` function to test — the
behaviour is split across three places, and each is pinned here:

    _update_defect_density  writes four fields per module
    get_defect_density      reads them back
    get_risk_summary        projects them down to one field and drops three

That projection is the part worth pinning. GET /risks advertises
`defect_density` as {module: float}, and everything else the density map
stores is discarded on the way out — so a change to the stored shape is
invisible at the endpoint until something downstream wants a field that is no
longer there.

Tested at the service level, not over HTTP. There is no API test harness in
this suite: no TestClient, no httpx, and api.py builds a module-level
`analyzer` singleton behind an API-key dependency. Standing that up is its own
piece of work. Validating the payload against the real response model pins the
same contract without it:

    RiskSummary(**svc.get_risk_summary())

The developer's own data/defect_density.json is deliberately not pinned. It
holds a single "Unknown" module from a code path that predates classification
being wired into load_bugs, it is gitignored, and conftest sandboxes DATA_DIR
away from the repo anyway. What is pinned is what the service computes from
given input.
"""

from typing import Any

from defect_risk_analyzer.api_models import RiskSummary
from defect_risk_analyzer.services.analysis_service import AnalysisService

BUGS = [
    {"key": "AP-1", "summary": "login fails", "component": "Authentication",
     "priority": "Highest", "status": "Open", "created": "2026-03-15T10:00:00.000+0300"},
    {"key": "AP-2", "summary": "token expiry", "component": "Authentication",
     "priority": "High", "status": "Open", "created": "2026-03-16T10:00:00.000+0300"},
    {"key": "AP-3", "summary": "refund stuck", "component": "Payment",
     "priority": "Medium", "status": "Closed", "created": "2026-03-18T10:00:00.000+0300"},
]


class StubVectorStore:
    def upsert_bugs(self, bugs: list[dict]) -> int:
        return len(bugs)

    def query_similar(self, query: str, n_results: int = 5) -> list[dict]:
        return []

    def count(self) -> int:
        return 0


class StubRepository:
    """Holds the density map and results in memory. No disk.

    Same shape as the stub in test_analysis_service_breaker.py, but this one
    serves reads back, because the read path is half of what is under test.
    """

    def __init__(self, results=None, density=None) -> None:
        self.results: list[dict] = list(results or [])
        self.density: dict[str, Any] = dict(density or {})
        self.saves: list[dict] = []

    def upsert_result(self, result: dict) -> bool:
        self.results.append(result)
        return True

    def load_results(self) -> list[dict]:
        return list(self.results)

    def save_defect_density(self, density: dict) -> bool:
        self.saves.append(density)
        self.density = density
        return True

    def load_defect_density(self) -> dict:
        return dict(self.density)


def make_service(bugs=BUGS, results=None, density=None):
    repo = StubRepository(results=results, density=density)
    svc = AnalysisService(vector_store=StubVectorStore(), repository=repo)
    svc._bugs = [dict(bug) for bug in bugs]
    return svc, repo


# =============================================================================
# What gets stored
# =============================================================================

def test_the_density_map_stores_four_fields_per_module():
    """_update_defect_density is private and normally reached only as a side
    effect of persisting an analysis result, which needs an LLM. Called
    directly here for the same reason _bugs is seeded directly elsewhere: the
    collaborator under test is the repository, not the LLM path."""
    svc, repo = make_service()

    svc._update_defect_density(svc.calculate_module_stats())

    assert len(repo.saves) == 1
    assert set(repo.saves[0]) == {"Authentication", "Payment"}
    assert set(repo.saves[0]["Authentication"]) == {
        "bug_density", "total_bugs", "risk_score", "risk_level",
    }
    assert repo.saves[0]["Authentication"]["total_bugs"] == 2
    # 2 of 3 bugs are Authentication's. Exact, not approx: scoring.py:115 is a
    # plain `total / total_all_bugs`, so this is the identical float division.
    assert repo.saves[0]["Authentication"]["bug_density"] == 2 / 3


def test_stored_risk_level_matches_the_stored_score():
    svc, repo = make_service()

    svc._update_defect_density(svc.calculate_module_stats())
    stored = repo.saves[0]["Authentication"]

    from defect_risk_analyzer.core import scoring
    assert stored["risk_level"] == scoring.get_risk_level(stored["risk_score"])


# =============================================================================
# What survives to the endpoint
# =============================================================================

def test_the_summary_keeps_only_bug_density_and_drops_the_rest():
    """The projection is lossy by design: three of the four stored fields are
    dropped. Pinned so that adding a field to the stored map does not create
    the impression it reaches the API."""
    density = {
        "Authentication": {
            "bug_density": 0.66, "total_bugs": 2, "risk_score": 91, "risk_level": "CRITICAL",
        },
    }
    svc, _ = make_service(density=density)

    assert svc.get_risk_summary()["defect_density"] == {"Authentication": 0.66}


def test_module_risks_carries_its_own_four_fields():
    """Unrelated to the stored density map — recomputed from the loaded bugs
    on every call. RiskSummary types this as dict[str, dict], so the inner
    names are unvalidated and a rename would break clients silently."""
    svc, _ = make_service()

    risks = svc.get_risk_summary()["module_risks"]

    assert set(risks) == {"Authentication", "Payment"}
    assert set(risks["Authentication"]) == {"score", "level", "bug_count", "open_count"}
    assert risks["Authentication"]["bug_count"] == 2
    assert risks["Authentication"]["open_count"] == 2
    assert risks["Payment"]["open_count"] == 0


def test_last_updated_is_the_newest_analyzed_at():
    """max() over strings, so it is an ISO lexicographic comparison rather than
    a date comparison. Correct only while every timestamp has the same shape."""
    results = [
        {"bug_key": "AP-1", "analyzed_at": "2026-03-23T13:57:49.788256"},
        {"bug_key": "AP-2", "analyzed_at": "2026-03-23T15:59:01.483119"},
        {"bug_key": "AP-3", "analyzed_at": "2026-01-02T09:00:00.000000"},
    ]
    svc, _ = make_service(results=results)

    summary = svc.get_risk_summary()

    assert summary["last_updated"] == "2026-03-23T15:59:01.483119"
    assert summary["analyzed_count"] == 3


def test_last_updated_is_none_when_nothing_has_been_analyzed():
    svc, _ = make_service()

    summary = svc.get_risk_summary()

    assert summary["last_updated"] is None
    assert summary["analyzed_count"] == 0
    assert summary["total_bugs"] == 3


# =============================================================================
# The response model
# =============================================================================

def test_the_summary_validates_against_the_response_model():
    """What GET /risks actually does: RiskSummary(**analyzer.get_risk_summary())."""
    density = {"Authentication": {"bug_density": 0.66, "total_bugs": 2,
                                  "risk_score": 91, "risk_level": "CRITICAL"}}
    svc, _ = make_service(results=[{"analyzed_at": "2026-03-23T15:59:01"}], density=density)

    model = RiskSummary(**svc.get_risk_summary())

    assert model.total_bugs == 3
    assert model.analyzed_count == 1
    assert model.defect_density == {"Authentication": 0.66}


def test_a_density_entry_with_no_bug_density_becomes_a_float_zero():
    """The service and the model disagree on type and Pydantic hides it.

    get_risk_summary uses d.get("bug_density", 0) — an int. RiskSummary
    declares dict[str, float]. Validation coerces rather than failing, so the
    endpoint emits 0.0 where the service produced 0. Pinned because the
    mismatch is real and invisible: it only surfaces if the field ever stops
    being coercible.
    """
    svc, _ = make_service(density={"Ghost": {"total_bugs": 0}})

    payload = svc.get_risk_summary()
    assert payload["defect_density"] == {"Ghost": 0}
    assert isinstance(payload["defect_density"]["Ghost"], int)

    coerced = RiskSummary(**payload).defect_density["Ghost"]
    assert coerced == 0.0
    assert isinstance(coerced, float)


def test_an_empty_service_still_produces_a_valid_summary():
    """The first-run case: no bugs, no results, no density file."""
    svc, _ = make_service(bugs=[])

    payload = svc.get_risk_summary()
    model = RiskSummary(**payload)

    assert (model.total_bugs, model.analyzed_count) == (0, 0)
    assert model.module_risks == {}
    assert model.defect_density == {}
    assert model.last_updated is None
