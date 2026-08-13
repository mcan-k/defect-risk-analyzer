"""
Report generation in ci_analyzer — what the PR comment actually says.

No AnalysisService is constructed: StubAnalyzer supplies the statistics and
delegates scoring to the real core/scoring.py, so no ChromaDB, no Jira, no
config.init(), and data/chroma_db is never touched.

Expected scores are not invented and not copied. They are read at run time from
tests/data/scores-aff55c6-now2026-08-11.json — the pre-refactor snapshot that
tests/test_scoring_regression.py pins core/scoring.py against — and compared
against that same file's risk_score / risk_level fields. Authentication scores
79 there, which is also the number the PR #3 probe printed, and
tests/test_scoring_units.py:8 shows the derivation:

    (0.9*60 + 0.3*40) * 1.5 * 0.8 * 1.0 = 79.2 -> 79
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from defect_risk_analyzer.ci_analyzer import generate_risk_report
from defect_risk_analyzer.core import scoring

SNAPSHOT = (
    Path(__file__).resolve().parent / "data" / "scores-aff55c6-now2026-08-11.json"
)

# A clock with no meaning of its own — the report's timestamp is the only thing
# it reaches. It is frozen so two reports can be compared for equality.
FROZEN_NOW = datetime(2026, 6, 1, 12, 0, 0)


@pytest.fixture(scope="module")
def snapshot_modules() -> dict[str, dict[str, Any]]:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))["modules"]


@pytest.fixture(scope="module")
def authentication(snapshot_modules) -> dict[str, Any]:
    """The snapshot's Authentication entry, split into input and expectation.

    risk_score and risk_level are stripped from the stats before they are fed
    back in, so the test asserts against the reference rather than against
    something it computed itself.
    """
    entry = dict(snapshot_modules["Authentication"])
    expected_score = entry.pop("risk_score")
    expected_level = entry.pop("risk_level")

    # Guard: if the snapshot ever stopped producing this, the assertions below
    # would still pass while testing nothing recognisable.
    assert (expected_score, expected_level) == (79, "HIGH")

    return {"stats": entry, "score": expected_score, "level": expected_level}


class StubAnalyzer:
    """Supplies module statistics; scoring is the real thing.

    calculate_risk_score delegates to core/scoring.py rather than returning a
    canned number, so a change to the formula shows up here as a changed report
    instead of a test that keeps agreeing with itself.
    """

    def __init__(self, module_stats: dict[str, dict[str, Any]]) -> None:
        self._module_stats = module_stats

    def calculate_module_stats(self) -> dict[str, dict[str, Any]]:
        return self._module_stats

    def calculate_risk_score(self, module_name: str, module_stats: dict) -> int:
        return scoring.calculate_risk_score(module_name, module_stats)


# ===========================================================================
# The clock
# ===========================================================================

def test_generated_timestamp_is_injectable():
    """datetime.now() inside the report body made the output untestable.

    core/scoring.py:59 already solved this for calculate_module_stats; the
    reasoning at scoring.py:92-94 applies unchanged here.
    """
    report = generate_risk_report(
        StubAnalyzer({}), ["src/auth/login.py"], ["Authentication"], now=FROZEN_NOW
    )

    assert "**Generated:** 2026-06-01 12:00:00" in report


def test_generated_timestamp_defaults_to_now():
    """Omitting `now` must keep the production behaviour, not print an epoch."""
    before = datetime.now().replace(microsecond=0)
    report = generate_risk_report(StubAnalyzer({}), [], [])
    after = datetime.now().replace(microsecond=0)

    stamped = [line for line in report.splitlines() if line.startswith("**Generated:**")]
    assert len(stamped) == 1

    printed = datetime.strptime(
        stamped[0].removeprefix("**Generated:** "), "%Y-%m-%d %H:%M:%S"
    )
    assert before <= printed <= after
