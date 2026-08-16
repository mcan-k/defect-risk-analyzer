"""
The shape GET /blind-spots promises, checked against what the detector emits.

Until this commit the endpoint returned the detector's dict raw, with no
response_model and no model in api_models.py. The literal dict *was* the whole
contract, which is why converting "recommendation" into "code"/"params" broke
a public endpoint without a single test noticing. ROADMAP:268 knew the break
was coming; nothing could see it happen.

BlindSpotReport closes that. The risk it introduces is the opposite one — a
response_model that disagrees with the payload makes FastAPI drop fields
silently, turning a loud break into a quiet one. So the model is not asserted
field by field here. It is round-tripped against a real detector result:

    BlindSpotReport(**payload).model_dump() == payload

Pydantic ignores unknown keys by default, so anything the model forgot would
vanish from model_dump() and fail this comparison. That makes the test a
guard against the model being wrong, not a restatement of it.

The payload is built from the committed sample data at the snapshot clock —
same inputs as tests/test_blind_spots.py, so the two files cannot drift.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from defect_risk_analyzer.api_models import BlindSpotReport
from defect_risk_analyzer.blind_spot_detector import detect_blind_spots

TESTS_DATA = Path(__file__).resolve().parent / "data"
JIRA_TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 4, 1, 12, 0, tzinfo=JIRA_TZ)


@pytest.fixture(scope="module")
def payload(sample_bugs_path: Path) -> dict:
    """A detector result with every category populated.

    The sample data alone leaves rising_unattended empty — its only two
    increasing modules are the two with worked-on bugs — so a synthetic module
    is added to reach that branch. Without it the round-trip would never
    exercise the rising_unattended member of the model.
    """
    bugs = json.loads(sample_bugs_path.read_text(encoding="utf-8"))
    snapshot = json.loads(
        (TESTS_DATA / "scores-aff55c6-now2026-04-01.json").read_text(encoding="utf-8")
    )
    stats = dict(snapshot["modules"])
    stats["Search"] = {
        "total_bugs": 4, "open_bugs": 4, "trend": "increasing", "recent_bug_count": 3,
    }
    scores = {name: s.get("risk_score", 70) for name, s in stats.items()}

    return detect_blind_spots(
        bugs=bugs, module_stats=stats, analysis_results=[],
        risk_scores=scores, now=NOW,
    )


def test_the_payload_reaches_every_branch_of_the_model(payload):
    """Guard on the fixture itself. A round-trip over a payload with three
    empty lists would pass while proving almost nothing."""
    assert payload["unanalyzed_risky_modules"]
    assert payload["neglected_critical_bugs"]
    assert payload["stale_bugs"]
    assert payload["rising_unattended"]


def test_the_model_round_trips_without_losing_a_field(payload):
    """The real assertion: nothing the detector emits is dropped by the model.

    If BlindSpotReport is missing a field, Pydantic discards it on the way in
    and model_dump() comes back short. That is precisely the silent failure a
    response_model can introduce, so it is checked rather than assumed.
    """
    assert BlindSpotReport(**payload).model_dump() == payload


def test_a_finding_carries_a_code_and_params_not_a_sentence(payload):
    """The contract change itself, stated at the API boundary."""
    dumped = BlindSpotReport(**payload).model_dump()

    for category in (
        "unanalyzed_risky_modules",
        "neglected_critical_bugs",
        "stale_bugs",
        "rising_unattended",
    ):
        for finding in dumped[category]:
            assert "recommendation" not in finding
            assert isinstance(finding["code"], str) and finding["code"]
            assert isinstance(finding["params"], dict)


def test_an_empty_report_is_valid():
    """The all-clear case the dashboard short-circuits on — total 0. It has to
    validate too, or the endpoint 500s exactly when there is no bad news."""
    empty = detect_blind_spots(
        bugs=[], module_stats={}, analysis_results=[], risk_scores={}, now=NOW,
    )

    assert BlindSpotReport(**empty).model_dump() == empty
    assert empty["summary"]["total_blind_spots"] == 0
