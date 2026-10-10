"""
What the dashboard actually draws: the values inside every chart and table.

test_dashboard_pages.py proves that each page renders, has its sections and
configures its table headers. None of that reads a value. A pandas or Plotly
upgrade that reorders the risk bars, moves a bug into the wrong week or drops a
module from the pie would leave that whole file green. This file pins the
values themselves — phase 6D-6a, written BEFORE the pandas 3 and Plotly 7
bumps (6D-6b, 6D-6c) so that those bumps have something to be measured against.

WHAT IS READ. For Plotly, the JSON streamlit sends to the browser
(`plotly.io.to_json`, element `proto.spec`): trace order, trace names, and the
x/y/labels/values/text arrays. For tables, the rows of `st.dataframe`'s frame.

WHAT IS DELIBERATELY NOT READ: colours, the template, hover templates, margins,
fonts — version-dependent formatting — and table dtypes. pandas 3 stores text
as `str` where pandas 2 used `object`; that is not a change the user can see.

THE DATA IS A FAKE SERVICE, NOT THE SAMPLE BUGS. `ui.service.AnalysisService`
is replaced, so every page and the sidebar get the fixture below. Three reasons:
  * The expected values are derived BY HAND from the fixture and written here as
    literals; nothing is recomputed through the code under test. That needs a
    fixture small enough to derive by hand.
  * No wall clock. The blind spot tables show `days_open`, which the real
    service computes from today. Here the fake supplies it, so the values never
    drift. app.py and buglar.py read no clock themselves.
  * No VectorStore is ever constructed, so chromadb is not imported.
`get_service` itself cannot be patched: shell.py binds it by name at import.
The cost, declared: a change in the SHAPE of the real service's output is not
visible here. test_dashboard_pages.py (real service) and the scoring snapshots
cover that side.

VERSION-INDEPENDENT READING. Plotly >= 6 writes numeric arrays as
`{"dtype": "f8", "bdata": "<base64>"}` (measured 2026-10-10 on 7.1.0: integers
shrink to the smallest type, `[2, 7]` -> `{"dtype": "i1", "bdata": "Agc="}`).
`_values` decodes that with the standard library only — numpy is never imported
by this repo, and a test should not become its first importer. Dates are ISO
strings in both versions; `_day` reduces a midnight timestamp to its day, so a
second- versus nanosecond-resolution column (pandas 3 vs 2) reads the same,
while a real time of day is refused rather than truncated. The two helpers have
tests of their own: on Plotly 5 there is no `bdata` at all, so a broken decoder
would leave every value test green.

GUARDS ON THE GUARDS. Each chart is found by what it is (pie; horizontal bars;
stacked bars; lines with markers; area filled to zero), not by position, and
the set of charts and tables per page is pinned exactly. An array that cannot
be read raises. `test_bdata_decoding_matches_the_installed_plotly` ties the
presence of encoded arrays to the installed Plotly major, so the decoder cannot
silently stop being exercised after the bump.

WARNINGS (measured 2026-10-10). A warning raised in AppTest's script thread
does reach pytest's warnings summary. Under `simplefilter("error")` it does NOT
raise in the test: it stops the script and AppTest collects it as
`at.exception`. So the warning check renders the pages separately, with the
filter on — if the value tests shared that render, one FutureWarning would stop
the script and erase every value as evidence. Blind spots: streamlit reports
its own deprecations through logging, not `warnings` (the
`use_container_width` notice is one), and a warning raised at import time does
not repeat once its module is imported.

NO NATURAL RED, WITH ONE EXCEPTION. 6D-6a changes no behaviour, so its tests
are green on main by construction; their red was observed only under mutation
(docs/KNOWN-DEBT.md, "Faz 6D-6 eki"). Their job starts with the bumps.
`test_bars_in_a_stack_share_one_offset_group` (6D-6b) is the exception: it is
red on Plotly 5 by design, so reverting the Plotly 7 bump on its own turns it
red. That bump and this test are reverted as a pair.
"""

import base64
import json
import os
import re
import struct
import warnings
from importlib.metadata import version
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from defect_risk_analyzer import config
from defect_risk_analyzer.ui import service as ui_service

APP = str(Path(config.__file__).resolve().parent / "ui" / "app.py")
SCRIPTS = ("app.py", "pages/buglar.py")

# The same configured, mock-mode install test_dashboard_pages.py uses, with
# Turkish pinned: every expected label below is a Turkish string.
_ENV = (
    "DRA_LANGUAGE=tr\n"
    "USE_MOCK_DATA=True\n"
    "ANONYMIZE_DATA=False\n"
    "GROQ_SLEEP=0\n"
    "JIRA_URL=https://example.atlassian.net\n"
    "JIRA_EMAIL=tests@example.com\n"
    "JIRA_API_TOKEN=dummy-token-not-a-real-credential\n"
    "JIRA_PROJECT_KEY=TEST\n"
    "LLM_PROVIDER=groq\n"
    "GROQ_API_KEY=dummy-key-not-a-real-credential\n"
)
_ENV_KEYS = tuple(line.split("=", 1)[0] for line in _ENV.splitlines())

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

# Scores are exact in binary floating point, so equality is exact. Levels agree
# with core/scoring.py's thresholds (80 / 60 / 35). The dict order is
# deliberately NOT the score order, so a lost sort shows.
MODULE_RISKS = {
    "Auth": {"score": 20.5, "level": "LOW", "bug_count": 2, "open_count": 1},
    "Ödeme": {"score": 80.0, "level": "CRITICAL", "bug_count": 7, "open_count": 5},
    "Rapor": {"score": 45.25, "level": "MEDIUM", "bug_count": 3, "open_count": 2},
    "Arama": {"score": 62.75, "level": "HIGH", "bug_count": 4, "open_count": 0},
}

# 76 characters; the blind spot tables keep the first 70.
SUMMARY_76 = "Oturum açma ekranında hatalı parola girildiğinde hata mesajı hiç görünmüyor."
SUMMARY_76_FIRST_70 = "Oturum açma ekranında hatalı parola girildiğinde hata mesajı hiç görün"
# 90 characters; the pattern tab keeps the first 80 (ending in a space).
SUMMARY_90 = (
    "Ödeme adımında banka yanıtı gecikince işlem iki kez gönderiliyor "
    "ve müşteri iki kez ödüyor"
)
SUMMARY_90_FIRST_80 = (
    "Ödeme adımında banka yanıtı gecikince işlem iki kez gönderiliyor ve müşteri iki "
)


def _bug(key, summary, priority, status, component, created):
    return {
        "key": key,
        "summary": summary,
        "priority": priority,
        "status": status,
        "component": component,
        "created": created,
    }


# Every edge the trend charts have: a Sunday-night bug (T-2) that belongs to the
# week before; a Monday-00:30 bug (T-3) that is still Sunday in UTC, so a
# conversion to UTC would move it a week back; an unparseable date (T-6) and an
# empty one (T-7), both left out of every trend chart.
BUGS = [
    _bug("T-1", SUMMARY_76, "Highest", "Open", "Auth", "2026-03-02T09:00:00.000+0300"),
    _bug("T-2", "b", "Low", "Closed", "Auth", "2026-03-08T23:30:00.000+0300"),
    _bug("T-3", SUMMARY_90, "Medium", "In Progress", "Ödeme", "2026-03-09T00:30:00.000+0300"),
    _bug("T-4", "d", "High", "Done", "Ödeme", "2026-03-16T12:00:00.000+0300"),
    _bug("T-5", "e", "High", "Reopened", "Ödeme", "2026-03-17T08:00:00.000+0300"),
    _bug("T-6", "f", "High", "Open", "Ödeme", "bozuk-tarih"),
    _bug("T-7", "g", "Low", "Open", "Rapor", ""),
    _bug("T-8", "h", "Medium", "To Do", "Arama", "2026-03-04T10:00:00.000+0300"),
]


def _blind_row(code, days_open):
    row = {
        "key": "T-1",
        "summary": SUMMARY_76,
        "priority": "Highest",
        "status": "Open",
        "component": "Auth",
        "days_open": days_open,
        "code": code,
        "params": {"key": "T-1", "days_open": days_open},
    }
    if code == "neglected_critical_bug":
        row["params"].update(priority="Highest", status="Open")
    return row


BLIND_SPOTS = {
    "summary": {
        "total_blind_spots": 2,
        "critical_spots": 1,
        "categories": {"neglected_critical_bugs": 1, "stale_bugs": 1},
    },
    "unanalyzed_risky_modules": [],
    "neglected_critical_bugs": [_blind_row("neglected_critical_bug", 40)],
    "stale_bugs": [_blind_row("stale_bug", 23)],
    "rising_unattended": [],
}

PATTERNS = [
    {
        "pattern_id": 1,
        "bug_keys": ["T-3", "T-5"],
        "bug_count": 2,
        "common_keywords": ["zaman aşımı", "ödeme"],
        "common_component": "Ödeme",
        "common_priority": "High",
        "severity": "high",
    }
]


class FakeService:
    """Every service call the two pages and the sidebar make, and no more.

    A call the pages start making later fails as AttributeError, which AppTest
    collects as an exception — loudly, not as a silent default.
    """

    def get_risk_summary(self):
        return {"total_bugs": len(BUGS), "analyzed_count": 0, "module_risks": MODULE_RISKS}

    def get_bugs(self):
        return BUGS

    def get_daily_request_count(self):
        return 0

    def detect_blind_spots(self):
        return BLIND_SPOTS

    def detect_patterns(self, similarity_threshold=0.35, include_bugs=True):
        return PATTERNS


# ---------------------------------------------------------------------------
# Reading helpers
# ---------------------------------------------------------------------------

# Plotly's dtype codes -> struct format characters, little-endian.
_BDATA_FORMATS = {
    "i1": "b", "u1": "B", "i2": "h", "u2": "H", "i4": "i", "u4": "I",
    "i8": "q", "u8": "Q", "f4": "f", "f8": "d",
}

_MIDNIGHT = re.compile(r"(\d{4}-\d{2}-\d{2})(?:T00:00:00(?:\.0+)?)?")


def _values(array) -> list:
    """A Plotly data array as a plain list, whichever way it was written.

    A list passes through. A typed array (`dtype` + `bdata`, optional `shape`)
    is decoded. Anything else raises: an array this test cannot read must not
    turn into a quiet mismatch or, worse, a quiet match.
    """
    if isinstance(array, list):
        return array
    if not (isinstance(array, dict) and {"dtype", "bdata"} <= set(array)):
        raise ValueError(f"unreadable Plotly array: {array!r}")
    if set(array) - {"dtype", "bdata", "shape"}:
        raise ValueError(f"unknown keys in a typed array: {sorted(array)}")
    code = _BDATA_FORMATS.get(array["dtype"])
    if code is None:
        raise ValueError(f"unknown typed-array dtype: {array['dtype']!r}")
    raw = base64.b64decode(array["bdata"])
    size = struct.calcsize(code)
    if len(raw) % size:
        raise ValueError(f"{len(raw)} bytes is not a whole number of {array['dtype']}")
    decoded = list(struct.unpack(f"<{len(raw) // size}{code}", raw))
    if "shape" in array and str(array["shape"]) != str(len(decoded)):
        raise ValueError(f"not a flat array: shape {array['shape']!r}")
    return decoded


def _day(text: str) -> str:
    """`2026-03-02` from a date or a midnight timestamp; refuse a time of day."""
    match = _MIDNIGHT.fullmatch(text)
    if match is None:
        raise ValueError(f"not a date or a midnight timestamp: {text!r}")
    return match.group(1)


def _read(trace: dict, key: str) -> list:
    values = _values(trace[key])
    assert values, f"{trace.get('type')} trace {trace.get('name')!r}: {key} is empty"
    return values


def _specs(at: AppTest) -> list[dict]:
    return [json.loads(element.proto.spec) for element in at.get("plotly_chart")]


def _kind(spec: dict) -> str:
    """What a chart is, from what it draws rather than where it sits."""
    traces = spec["data"]
    types = {trace.get("type") for trace in traces}
    if types == {"pie"}:
        return "pie"
    if types == {"bar"} and all(trace.get("orientation") == "h" for trace in traces):
        return "risk_map"
    if types == {"bar"} and spec["layout"].get("barmode") == "stack":
        return "open_closed"
    if types == {"scatter"} and all(t.get("mode") == "lines+markers" for t in traces):
        return "weekly"
    if types == {"scatter"} and all(t.get("fill") == "tozeroy" for t in traces):
        return "cumulative"
    return f"unknown {sorted(map(str, types))}"


def _chart(at: AppTest, kind: str) -> dict:
    found = [spec for spec in _specs(at) if _kind(spec) == kind]
    assert len(found) == 1, f"expected one {kind} chart, found {len(found)}"
    return found[0]


def _tables(at: AppTest, columns: list[str]) -> list[list[dict]]:
    """The rows of every table with exactly these columns, in page order."""
    return [
        element.value.to_dict("records")
        for element in at.dataframe
        if list(element.value.columns) == columns
    ]


def _bdata_count(spec: dict) -> int:
    return sum(
        1
        for trace in spec["data"]
        for value in trace.values()
        if isinstance(value, dict) and "bdata" in value
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render(script: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    if script != "app.py":
        at.switch_page(script)
    at.run()
    return at


def _page(rendered: dict, script: str) -> AppTest:
    at = rendered[script]
    assert not at.exception, [f"{e.value}" for e in at.exception]
    return at


@pytest.fixture(scope="module")
def fake_dashboard():
    """The fake service behind a configured mock-mode install, then undone.

    Restores everything it changes (see conftest.py on partial monkeypatching):
    the sandbox .env, the variables load_dotenv writes from it, config's init
    flag and settings, the two patched names, and streamlit's process-wide
    caches — a cached FakeService would otherwise serve the next test file.
    """
    import streamlit as st

    saved_environ = {key: os.environ[key] for key in _ENV_KEYS if key in os.environ}
    saved_file = (
        config.ENV_FILE.read_text(encoding="utf-8") if config.ENV_FILE.exists() else None
    )
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.ENV_FILE.write_text(_ENV, encoding="utf-8")

    mp = pytest.MonkeyPatch()
    mp.setattr(config, "_initialized", False)
    mp.setattr(ui_service, "AnalysisService", FakeService)
    mp.setattr(ui_service, "load_bugs_from_file", lambda: [])
    st.cache_resource.clear()
    st.cache_data.clear()

    yield

    st.cache_resource.clear()
    st.cache_data.clear()
    mp.undo()
    if saved_file is None:
        config.ENV_FILE.unlink(missing_ok=True)
    else:
        config.ENV_FILE.write_text(saved_file, encoding="utf-8")
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
    os.environ.update(saved_environ)
    config._initialized = False
    config.reload()


@pytest.fixture(scope="module")
def rendered(fake_dashboard) -> dict:
    """Both pages, rendered once with the default warning filters."""
    return {script: _render(script) for script in SCRIPTS}


# ---------------------------------------------------------------------------
# The reading helpers themselves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("array", "expected"),
    [
        ({"dtype": "f8", "bdata": "AAAAAACANEA="}, [20.5]),
        ({"dtype": "i1", "bdata": "Agc="}, [2, 7]),
    ],
    ids=["f8", "i1"],
)
def test_bdata_is_decoded(array, expected):
    assert _values(array) == expected


def test_a_plain_list_passes_through():
    assert _values(["Auth", 20.5]) == ["Auth", 20.5]


@pytest.mark.parametrize(
    "array",
    [
        {"dtype": "i1", "bdata": "AQIDBA==", "shape": "2,2"},
        {"dtype": "c16", "bdata": "AAAAAAAAAAA="},
        {"dtype": "f8"},
    ],
    ids=["two-dimensional", "unknown-dtype", "no-bdata"],
)
def test_an_unreadable_array_is_refused(array):
    with pytest.raises(ValueError):
        _values(array)


@pytest.mark.parametrize(
    "text",
    ["2026-03-02", "2026-03-02T00:00:00", "2026-03-02T00:00:00.000000"],
)
def test_a_midnight_timestamp_reduces_to_its_day(text):
    assert _day(text) == "2026-03-02"


def test_a_time_of_day_is_refused():
    with pytest.raises(ValueError):
        _day("2026-03-02T09:00:00")


# ---------------------------------------------------------------------------
# Genel Bakış — Risk Dashboard tab
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_risk_map_bars(rendered):
    """Ascending by score; one trace per level, named by its Turkish label."""
    spec = _chart(_page(rendered, "app.py"), "risk_map")

    bars = [
        (t["name"], _read(t, "y"), _read(t, "x"), _read(t, "text")) for t in spec["data"]
    ]

    assert bars == [
        ("DÜŞÜK", ["Auth"], [20.5], [20.5]),
        ("ORTA", ["Rapor"], [45.25], [45.25]),
        ("YÜKSEK", ["Arama"], [62.75], [62.75]),
        ("KRİTİK", ["Ödeme"], [80.0], [80.0]),
    ]


@pytest.mark.slow
def test_bug_distribution_pie(rendered):
    """Module -> bug_count, in the order the service returned the modules."""
    (trace,) = _chart(_page(rendered, "app.py"), "pie")["data"]

    assert (_read(trace, "labels"), _read(trace, "values")) == (
        ["Auth", "Ödeme", "Rapor", "Arama"],
        [2, 7, 3, 4],
    )


@pytest.mark.slow
def test_weekly_trend_lines(rendered):
    """Monday of the local date, no UTC conversion; modules in sorted order.

    T-1 (Mon), T-8 (Wed) and T-2 (Sun 23:30) -> week of 03-02; T-3 (Mon 00:30,
    still Sunday in UTC) -> 03-09; T-4 (Mon) and T-5 (Tue) -> 03-16. T-6 and T-7
    have no usable date. "Ödeme" sorts after "Auth" (Ö is U+00D6).
    """
    spec = _chart(_page(rendered, "app.py"), "weekly")

    lines = [
        (t["name"], [_day(x) for x in _read(t, "x")], _read(t, "y")) for t in spec["data"]
    ]

    assert lines == [
        ("Arama", ["2026-03-02"], [1]),
        ("Auth", ["2026-03-02"], [2]),
        ("Ödeme", ["2026-03-09", "2026-03-16"], [1, 2]),
    ]


@pytest.mark.slow
def test_open_closed_stacked_bars(rendered):
    """Open = to do / open / in progress / in review / reopened; the rest closed.

    Open: T-1 (Auth), T-3 and T-5 (Ödeme), T-8 (Arama). Closed: T-2 (Auth),
    T-4 (Ödeme). Rows sort by module then label, so "Açık" comes first.
    """
    spec = _chart(_page(rendered, "app.py"), "open_closed")

    stacks = [(t["name"], _read(t, "x"), _read(t, "y")) for t in spec["data"]]

    assert stacks == [
        ("Açık", ["Arama", "Auth", "Ödeme"], [1, 1, 2]),
        ("Kapalı", ["Auth", "Ödeme"], [1, 1]),
    ]


@pytest.mark.slow
@pytest.mark.parametrize("kind", ["risk_map", "open_closed"])
def test_bars_in_a_stack_share_one_offset_group(rendered, kind):
    """Every bar trace lands in one stack, not in a slot of its own.

    plotly.js 3.0.0 (#7009) made `offsetgroup` work with barmode "stack" and
    "relative": bars in different offset groups are drawn side by side. Plotly
    5.24.1's px gives every bar trace `offsetgroup=<trace name>` whatever the
    barmode (`plotly/express/_core.py`); Plotly 7 only in group mode. streamlit
    1.65.0 bundles plotly.js 4.1.1, so on Plotly 5 the open/closed bars were
    drawn side by side and each risk-map bar took a quarter of its row — seen
    in the 6D-6b browser check. Red on Plotly 5 by design: the bump's natural
    red.
    """
    spec = _chart(_page(rendered, "app.py"), kind)

    assert spec["layout"].get("barmode") in ("stack", "relative")
    groups = {trace.get("offsetgroup") for trace in spec["data"]}
    assert len(groups) == 1, f"{kind}: {len(groups)} offset groups {sorted(map(str, groups))}"


@pytest.mark.slow
def test_cumulative_area(rendered):
    """The six dated bugs in date order, counted 1..6."""
    (trace,) = _chart(_page(rendered, "app.py"), "cumulative")["data"]

    assert ([_day(x) for x in _read(trace, "x")], _read(trace, "y")) == (
        [
            "2026-03-02",
            "2026-03-04",
            "2026-03-08",
            "2026-03-09",
            "2026-03-16",
            "2026-03-17",
        ],
        [1, 2, 3, 4, 5, 6],
    )


@pytest.mark.slow
def test_risk_ranking_table(rendered):
    """Descending by score, with the Turkish level label."""
    columns = ["module", "risk_score", "risk_level_label", "bug_count", "open_count"]

    (rows,) = _tables(_page(rendered, "app.py"), columns)

    assert rows == [
        {"module": "Ödeme", "risk_score": 80.0, "risk_level_label": "KRİTİK",
         "bug_count": 7, "open_count": 5},
        {"module": "Arama", "risk_score": 62.75, "risk_level_label": "YÜKSEK",
         "bug_count": 4, "open_count": 0},
        {"module": "Rapor", "risk_score": 45.25, "risk_level_label": "ORTA",
         "bug_count": 3, "open_count": 2},
        {"module": "Auth", "risk_score": 20.5, "risk_level_label": "DÜŞÜK",
         "bug_count": 2, "open_count": 1},
    ]


# ---------------------------------------------------------------------------
# Genel Bakış — Kör Nokta tab
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_blind_spot_tables(rendered):
    """Neglected, then stale; the summary cut to 70 characters."""
    assert len(SUMMARY_76) == 76  # a premise of the fixture, not a result
    columns = ["key", "summary", "priority", "status", "module", "days_open"]

    tables = _tables(_page(rendered, "app.py"), columns)

    row = {"key": "T-1", "summary": SUMMARY_76_FIRST_70, "priority": "Highest",
           "status": "Open", "module": "Auth"}
    assert tables == [[{**row, "days_open": 40}], [{**row, "days_open": 23}]]


# ---------------------------------------------------------------------------
# Buglar
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_bug_list_table(rendered):
    """Every bug, unfiltered, in service order; `created` cut to 10 characters."""
    columns = ["key", "summary", "priority", "status", "module", "created"]

    (rows,) = _tables(_page(rendered, "pages/buglar.py"), columns)

    assert [tuple(row.values()) for row in rows] == [
        ("T-1", SUMMARY_76, "Highest", "Open", "Auth", "2026-03-02"),
        ("T-2", "b", "Low", "Closed", "Auth", "2026-03-08"),
        ("T-3", SUMMARY_90, "Medium", "In Progress", "Ödeme", "2026-03-09"),
        ("T-4", "d", "High", "Done", "Ödeme", "2026-03-16"),
        ("T-5", "e", "High", "Reopened", "Ödeme", "2026-03-17"),
        ("T-6", "f", "High", "Open", "Ödeme", "bozuk-tari"),
        ("T-7", "g", "Low", "Open", "Rapor", ""),
        ("T-8", "h", "Medium", "To Do", "Arama", "2026-03-04"),
    ]


@pytest.mark.slow
def test_pattern_tab(rendered):
    """render_patterns: the pattern's expander and its bugs, summary cut to 80.

    The pattern tab never runs in test_dashboard_pages.py — its stub vector
    store has no collection, so detection returns nothing.
    """
    assert len(SUMMARY_90) == 90  # a premise of the fixture, not a result
    at = _page(rendered, "pages/buglar.py")
    columns = ["key", "summary", "priority", "status"]

    (rows,) = _tables(at, columns)

    assert [e.label for e in at.expander] == ["🟠 Pattern #1 — 2 bug — Ödeme"]
    assert rows == [
        {"key": "T-3", "summary": SUMMARY_90_FIRST_80, "priority": "Medium",
         "status": "In Progress"},
        {"key": "T-5", "summary": "e", "priority": "High", "status": "Reopened"},
    ]


# ---------------------------------------------------------------------------
# Guards on the guards
# ---------------------------------------------------------------------------

EXPECTED_CHARTS = {
    "app.py": ["cumulative", "open_closed", "pie", "risk_map", "weekly"],
    "pages/buglar.py": [],
}
EXPECTED_TABLES = {
    "app.py": [
        ["module", "risk_score", "risk_level_label", "bug_count", "open_count"],
        ["key", "summary", "priority", "status", "module", "days_open"],
        ["key", "summary", "priority", "status", "module", "days_open"],
    ],
    "pages/buglar.py": [
        ["key", "summary", "priority", "status", "module", "created"],
        ["key", "summary", "priority", "status"],
    ],
}


@pytest.mark.slow
@pytest.mark.parametrize("script", SCRIPTS)
def test_page_has_exactly_the_expected_charts_and_tables(rendered, script):
    """A chart or table that disappears, or a new one nobody pinned, is red."""
    at = _page(rendered, script)

    assert sorted(_kind(spec) for spec in _specs(at)) == EXPECTED_CHARTS[script]
    assert [list(e.value.columns) for e in at.dataframe] == EXPECTED_TABLES[script]


@pytest.mark.slow
def test_bdata_decoding_matches_the_installed_plotly(rendered):
    """Plotly >= 6 encodes numeric arrays; before 6 it never does.

    So the decoder is exercised by the pages exactly when it has to be, and a
    Plotly that stops encoding (or starts early) is noticed, not absorbed.
    """
    major = int(version("plotly").split(".")[0])
    encoded = sum(_bdata_count(spec) for spec in _specs(_page(rendered, "app.py")))

    if major >= 6:
        assert encoded > 0, f"plotly {version('plotly')} wrote no typed array"
    else:
        assert encoded == 0, f"plotly {version('plotly')} wrote {encoded} typed arrays"


@pytest.mark.slow
@pytest.mark.parametrize("script", SCRIPTS)
def test_rendering_raises_no_future_or_deprecation_warning(fake_dashboard, script):
    """Rendered on its own: under "error" a warning stops the script."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        warnings.simplefilter("error", DeprecationWarning)
        at = _render(script)

    assert not at.exception, [f"{e.value}" for e in at.exception]
