"""The shape GET /patterns promises, checked against what the detector emits.

Same reasoning as tests/test_blind_spot_contract.py, and the same failure it
was written after. Until this commit the endpoint returned the detector's dict
raw, with no response_model and no model in api_models.py — so the literal dict
WAS the contract, and Faz 5C changed it by replacing the ready-made "summary"
sentence with code/params. 5A found exactly this hole in /blind-spots; leaving
it open here would have meant breaking a public endpoint unobserved twice in
the same project.

response_model brings the opposite risk: a model that disagrees with the
payload makes FastAPI drop fields silently, turning a loud break into a quiet
one. So the model is not asserted field by field. It is round-tripped against a
real detector result:

    PatternResponse(**pattern).model_dump() == pattern

Pydantic ignores unknown keys, so anything the model forgot vanishes from
model_dump() and fails the comparison.

The payload is FULL — every field populated, both wording branches present. An
empty list round-trips trivially and proves nothing.
"""

import ast
from pathlib import Path

import pytest
from test_pattern_detector import StubCollection  # sibling module, not a package

from defect_risk_analyzer import api_models
from defect_risk_analyzer.api_models import PatternResponse
from defect_risk_analyzer.pattern_detector import detect_patterns

# Two clusters that cannot merge: the stub answers per collection, so each is
# detected on its own and the two are concatenated. That gives one pattern with
# keywords and one without, which is both wording branches in one payload.
THEMED = [
    {"key": "AP-1", "summary": "timeout", "description": "alfa",
     "component": "Payment", "priority": "High", "status": "Open"},
    {"key": "AP-2", "summary": "timeout", "description": "beta",
     "component": "Payment", "priority": "High", "status": "Open"},
    {"key": "AP-3", "summary": "timeout", "description": "gama",
     "component": "Payment", "priority": "Highest", "status": "Open"},
]

UNTHEMED = [
    {"key": "BP-1", "summary": "Kırmızı", "description": "",
     "component": "Frontend", "priority": "Low", "status": "Open"},
    {"key": "BP-2", "summary": "Yeşil", "description": "",
     "component": "Frontend", "priority": "Low", "status": "Open"},
]


@pytest.fixture(scope="module")
def payload() -> list[dict]:
    """What the endpoint returns: patterns with the `bugs` key removed.

    The pop mirrors services/analysis_service.py's include_bugs=False branch,
    which is what the route calls. test_the_endpoint_asks_for_the_shape_it
    _declares below pins that coupling rather than trusting this comment.
    """
    patterns = []
    for bugs in (THEMED, UNTHEMED):
        patterns += detect_patterns(bugs, StubCollection(bugs))

    for pattern in patterns:
        pattern.pop("bugs", None)

    return patterns


def test_the_payload_is_actually_full(payload):
    """Guards the guard: an empty round-trip would pass and mean nothing."""
    assert len(payload) == 2

    with_keywords = [p for p in payload if p["params"]["keywords"]]
    without_keywords = [p for p in payload if not p["params"]["keywords"]]
    assert with_keywords and without_keywords, "both wording branches must be present"

    for pattern in payload:
        assert set(pattern) == {
            "pattern_id", "bug_keys", "common_keywords", "common_component",
            "common_priority", "code", "params", "severity", "bug_count",
        }
        assert all(value is not None for value in pattern.values())


def test_the_model_round_trips_every_pattern(payload):
    """If PatternResponse is missing a field, Pydantic discards it on the way
    in and model_dump() comes back short. That is precisely the silent failure
    a response_model introduces."""
    for pattern in payload:
        assert PatternResponse(**pattern).model_dump() == pattern


def test_bugs_is_not_in_the_model(payload):
    """The one field the endpoint never sends.

    Adding it as optional would make model_dump() emit `"bugs": null` and break
    the round-trip above — a real coupling, worth naming rather than leaving as
    an accident of the field list.
    """
    assert "bugs" not in PatternResponse.model_fields
    assert all("bugs" not in pattern for pattern in payload)


def test_the_endpoint_asks_for_the_shape_it_declares():
    """response_model=list[PatternResponse] only holds if include_bugs=False.

    Read from the source: the package has no API test infrastructure (no
    TestClient, api.py builds a module-level analyzer singleton, the route
    carries an API-key dependency), so the contract is pinned here and the
    call's own argument is pinned by reading it.
    """
    source = Path(api_models.__file__).resolve().parent / "api.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    handlers = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_patterns"
    ]
    assert len(handlers) == 1, "get_patterns is not where this test thinks it is"

    calls = [
        keyword
        for node in ast.walk(handlers[0])
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "include_bugs"
    ]
    assert len(calls) == 1, "get_patterns no longer passes include_bugs explicitly"
    assert calls[0].value.value is False, "get_patterns now sends bug objects the model drops"
