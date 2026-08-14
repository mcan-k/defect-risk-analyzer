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

from defect_risk_analyzer.ci_analyzer import (
    ModuleMap,
    ModuleMapError,
    _matches,
    extract_changed_files,
    generate_risk_report,
    infer_module_provenance,
    load_module_map,
    select_analyzable_files,
)
from defect_risk_analyzer.core import scoring

# Inference now reads module-map.json, so the report tests have to supply one.
# Built in memory rather than read from the repository: what these tests are
# about is what the report SAYS, and pinning that to whichever patterns happen
# to be committed would make an unrelated map edit fail them.
#
# "**/*auth*" is here for the same reason it is in the inference suite: it lets
# the PR #3 probes stay load-bearing. Without a pattern that really would claim
# docs/probe/auth-probe.md, the end-to-end probe tests below would pass whether
# or not the scope filter ran.
REPORT_MAP = ModuleMap(
    modules={
        "**/*auth*": "Authentication",
        "**/*_view.py": "Frontend",
        "**/*inventory*": "Inventory",
        "**/*report*": "Reporting",
    },
    exclude=("docs/**", "**/*.md"),
)

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


# ===========================================================================
# Matched, with history — the scored path
# ===========================================================================

def test_module_with_history_is_scored(authentication):
    """The score and level come from the snapshot, not from this file.

    79 / HIGH is also what the PR #3 probe printed. The probe was wrong about
    *which module* was affected, never about the arithmetic.
    """
    report = generate_risk_report(
        StubAnalyzer({"Authentication": authentication["stats"]}),
        ["src/auth/login.py"],
        ["Authentication"],
        now=FROZEN_NOW,
    )

    assert f"| Authentication | {authentication['score']}/100 |" in report
    assert authentication["level"] in report
    assert "HIGH RISK — `Authentication` module has elevated defect density." in report


# ===========================================================================
# Matched, without history — not the same thing as low risk
# ===========================================================================

def test_matched_module_without_history_gets_no_risk_row():
    """Inventory is a real module name; this analyzer just has no bugs for it.

    Before this commit the report printed "| Inventory | N/A | No Data | 0 | 0 |"
    and then, because max_risk had stayed 0, concluded "LOW RISK — No
    significant defect patterns detected". That is a claim about the change.
    The truth is that nothing was measured.
    """
    report = generate_risk_report(
        StubAnalyzer({}), ["src/inventory/stock.py"], ["Inventory"], now=FROZEN_NOW
    )

    assert "**Matched, no historical data:** Inventory" in report
    assert "NOT ASSESSED — Inventory matched" in report
    assert "Risk was not assessed" in report

    assert "## Risk Summary" not in report
    assert "No Data" not in report
    assert "LOW RISK" not in report
    assert "No significant defect patterns" not in report


def test_mixed_matched_modules(authentication):
    """One scored, one not. The unscored one must not touch the verdict."""
    report = generate_risk_report(
        StubAnalyzer({"Authentication": authentication["stats"]}),
        ["src/auth/payment_view.py", "src/inventory/stock.py"],
        ["Authentication", "Inventory"],
        now=FROZEN_NOW,
    )

    table_rows = [ln for ln in report.splitlines() if ln.startswith("| Authentication")]
    assert len(table_rows) == 1
    assert not any(ln.startswith("| Inventory") for ln in report.splitlines())

    assert "**Matched, no historical data:** Inventory" in report
    # The verdict comes from the module that was actually scored.
    assert "HIGH RISK — `Authentication`" in report
    assert "NOT ASSESSED" not in report


# ===========================================================================
# Nothing matched — the probe #2 outcome
# ===========================================================================

def test_no_module_match_is_not_assessed():
    report = generate_risk_report(
        StubAnalyzer({}),
        ["docs/probe/notes.md"],
        [],
        analyzed_files=[],
        now=FROZEN_NOW,
    )

    assert "**Affected Modules:** — none matched" in report
    assert "NOT ASSESSED — changed files did not map to any known module." in report
    # The wording used to name fixed categories ("documentation, config or
    # asset"). The categories are now whatever the user's exclude list says, so
    # the line points at the file instead of describing its contents.
    assert "**Analyzed Files:** 0  (1 excluded by module-map.json)" in report

    assert "## Risk Summary" not in report
    assert "LOW RISK" not in report
    assert "General" not in report


# ===========================================================================
# Provenance in the rendered report
# ===========================================================================

def test_report_shows_why_these_modules():
    """The evidence line names the pattern, which is a line the reader owns.

    Under the token rule this said "token `report` in `<file>`" — text quoted
    out of the path, because the rule itself was invisible and the path was the
    only thing a reader could check. Now the rule is a line in their own
    module-map.json, so the pattern is what they need: it says which line
    produced the claim and therefore which line to edit.
    """
    changed = ["src/reporting/export_report.py"]
    report = generate_risk_report(
        StubAnalyzer({}),
        changed,
        ["Reporting"],
        provenance=infer_module_provenance(changed, REPORT_MAP),
        now=FROZEN_NOW,
    )

    assert "## Why these modules" in report
    assert (
        "- **Reporting** ← pattern `**/*report*` matched "
        "`src/reporting/export_report.py`" in report
    )


# ===========================================================================
# No usable map — a fourth outcome, distinct from "nothing matched"
# ===========================================================================

@pytest.mark.parametrize(
    ("payload", "marker"),
    [
        pytest.param(None, "Create it", id="missing"),
        pytest.param("{", "not valid JSON", id="unreadable"),
        pytest.param('{"modules": {}}', "no patterns", id="empty"),
    ],
)
def test_module_map_error_reaches_the_report(tmp_path, payload, marker: str):
    """Three causes, three messages, none of them collapsed into the others.

    The messages are not written here — they are produced by load_module_map
    and carried through, so a test cannot drift from what a user actually sees.
    Each `marker` is the part that distinguishes one cause from the other two,
    which is what makes the three parameters different tests rather than three
    spellings of one.

    The distinction that matters most is against the existing "nothing matched"
    branch. Both end with no modules, but one means "your diff touched nothing
    the map names" and the other means "there was no map to consult". Printing
    the first when the second is true is the same class of error as PR #3's
    LOW RISK: a statement about the change, standing in for an admission that
    nothing was examined.
    """
    path = tmp_path / "module-map.json"
    if payload is not None:
        path.write_text(payload, encoding="utf-8")

    with pytest.raises(ModuleMapError) as excinfo:
        load_module_map(path)
    message = str(excinfo.value)
    assert marker in message

    report = generate_risk_report(
        StubAnalyzer({}),
        ["src/auth/login.py"],
        [],
        module_map_error=message,
        now=FROZEN_NOW,
    )

    assert "NOT ASSESSED — no usable module map." in report
    assert message in report
    assert "**Affected Modules:** — not inferred (no module map)" in report
    assert "Risk was not assessed" in report

    assert "did not map to any known module" not in report
    assert "## Risk Summary" not in report
    assert "LOW RISK" not in report


def test_a_usable_map_does_not_print_the_map_error_branch():
    """The default keeps every other report in this file unchanged."""
    report = generate_risk_report(
        StubAnalyzer({}), ["docs/probe/notes.md"], [], analyzed_files=[], now=FROZEN_NOW
    )

    assert "no usable module map" not in report
    assert "NOT ASSESSED — changed files did not map to any known module." in report


def test_provenance_section_is_omitted_when_not_supplied():
    report = generate_risk_report(
        StubAnalyzer({}), ["src/inventory/stock.py"], ["Inventory"], now=FROZEN_NOW
    )

    assert "## Why these modules" not in report


# ===========================================================================
# End to end — the two PR #3 probes, from raw diff to rendered report
# ===========================================================================

def _probe_diff(path: str) -> str:
    """A one-line documentation change, in the shape git actually emits."""
    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        "@@ -0,0 +1 @@\n"
        "+Bu dosya yalnizca CI kanit probe'u icin eklendi.\n"
    )


def _report_for(
    diff: str, analyzer: StubAnalyzer, module_map: ModuleMap = REPORT_MAP
) -> str:
    """The exact chain main() runs, minus the file I/O."""
    changed_files = extract_changed_files(diff)
    provenance = infer_module_provenance(changed_files, module_map)

    return generate_risk_report(
        analyzer,
        changed_files,
        sorted(provenance),
        analyzed_files=select_analyzable_files(changed_files, module_map),
        provenance=provenance,
        now=FROZEN_NOW,
    )


def test_doc_only_diff_produces_no_risk_end_to_end(authentication):
    """The full PR #3 regression, through every link in the chain.

    The analyzer is loaded with Authentication history on purpose: the bug was
    never that the data was missing, it was that a documentation file reached
    that data at all.

    REPORT_MAP's "**/*auth*" is what keeps this honest. Without a pattern that
    really would claim auth-probe.md the test would pass whether or not the
    scope filter ran, which is the failure mode 65fe72c found in the earlier
    version of these cases.
    """
    analyzer = StubAnalyzer({"Authentication": authentication["stats"]})

    assert _matches("**/*auth*", "docs/probe/auth-probe.md")

    report = _report_for(_probe_diff("docs/probe/auth-probe.md"), analyzer)

    assert "Authentication" not in report
    assert "HIGH RISK" not in report
    assert str(authentication["score"]) not in report
    assert "NOT ASSESSED" in report


def test_report_does_not_depend_on_a_doc_filename(authentication):
    """The two probes, side by side — the difference that exposed the bug.

    Both files hold the same one-line note. With the clock frozen the reports
    must be identical once the filename itself is substituted; any remaining
    difference means the filename leaked into the analysis again.
    """
    analyzer = StubAnalyzer({"Authentication": authentication["stats"]})

    keyword_named = _report_for(_probe_diff("docs/probe/auth-probe.md"), analyzer)
    neutral_named = _report_for(_probe_diff("docs/probe/notes.md"), analyzer)

    assert keyword_named.replace("auth-probe", "notes") == neutral_named
