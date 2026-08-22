"""The same four pages, walked in English.

tests/test_dashboard_pages.py pins the Turkish rendering — those literals were
measured against the running app and they are the only guard the "Turkish is
preserved verbatim" constraint has. This file is the other half: it proves the
pages still work when the language is not the one they were written in, and
that nothing was left behind untranslated.

Its own module, and its own .env, because the two cannot share one: the
language is read from DRA_LANGUAGE at config.init(), so a file asserting
English needs a different sandbox than one asserting Turkish. The fixture
restores whatever it found, since pytest runs both in a single process against
a single sandbox.

WHY THE LEAK TEST ONLY READS LABELS. Bug data is Turkish — data/sample_bugs.json
is 20 Turkish bug reports — and it legitimately appears in tables, markdown and
captions. Widget labels, titles, subheaders and tab names never carry it, so
those are exactly the surface where a Turkish character means an untranslated
string rather than a Turkish bug summary.
"""

import shutil

import pytest
from streamlit.testing.v1 import AppTest
from test_dashboard_pages import _LABELLED, APP, SCRIPTS, StubVectorStore, _problems

from defect_risk_analyzer import config
from defect_risk_analyzer.services import analysis_service as analysis_service_module
from defect_risk_analyzer.ui import i18n

pytestmark = pytest.mark.slow

ENGLISH_ENV = (
    "DRA_LANGUAGE=en\n"
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

#: Element kinds whose visible text is a label the interface owns, never data.
LABELLED_CHROME = (
    "title", "subheader", "tabs", "metric", "button", "multiselect",
    "text_input", "selectbox", "toggle", "number_input", "radio",
)

#: Letters that exist in Turkish and not in English. Their presence in a label
#: on an English page means a string never reached the locale files.
TURKISH_LETTERS = set("çğıöşüÇĞİÖŞÜ")


@pytest.fixture(scope="module", autouse=True)
def english_dashboard(sandbox_dir, sample_bugs_path):
    """Mock mode, sandboxed paths, no ChromaDB — and DRA_LANGUAGE=en."""
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    saved_env = config.ENV_FILE.read_text(encoding="utf-8") if config.ENV_FILE.exists() else ""
    saved_language = i18n.get_language()

    config.ENV_FILE.write_text(ENGLISH_ENV, encoding="utf-8")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(sample_bugs_path, config.SAMPLE_BUGS_FILE)
    # Both demo sets, so config.sample_bugs_file() has a real choice to make.
    shutil.copyfile(sample_bugs_path.parent / "sample_bugs_en.json", config.SAMPLE_BUGS_EN_FILE)

    mp.setattr(config, "_initialized", False)
    mp.setattr(analysis_service_module, "VectorStore", StubVectorStore)

    yield

    mp.undo()
    config.ENV_FILE.write_text(saved_env, encoding="utf-8")
    config._initialized = False
    config.reload()
    i18n.set_language(saved_language)


@pytest.fixture(autouse=True)
def _clear_streamlit_caches():
    """get_service() is @st.cache_resource — cached per process, not per run."""
    import streamlit as st

    st.cache_resource.clear()
    st.cache_data.clear()


def _open(script: str = "app.py") -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    if script != "app.py":
        at.switch_page(script)
    at.run()
    return at


def _chrome(at: AppTest) -> list[tuple[str, str]]:
    """(kind, text) for every label the interface owns on this page."""
    found = []
    for kind in LABELLED_CHROME:
        # Same split test_dashboard_pages.py uses: widgets carry .label,
        # headings carry .value.
        attribute = "label" if kind in _LABELLED else "value"
        for element in getattr(at, kind):
            found.append((kind, getattr(element, attribute)))
    return found


# ---------------------------------------------------------------------------
# The four pages, in English
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script", SCRIPTS)
def test_page_renders_without_errors_in_english(script: str):
    """A missing key raises UnknownMessageKey, and AppTest collects it.

    That is the whole reason i18n raises instead of returning "": a gap becomes
    this failure rather than a caption that silently is not there.
    """
    at = _open(script)

    assert not _problems(at), f"{script}: " + "; ".join(_problems(at))


@pytest.mark.parametrize("script", SCRIPTS)
def test_page_titles_come_from_the_english_catalog(script: str):
    """Not a tautology: it pins that the page rendered THIS key's text.

    Which key holds which words is pinned separately — by the Turkish literals
    in tests/test_dashboard_pages.py and by the catalog checks in
    tests/test_i18n_locales.py.
    """
    english = i18n.catalog("en")
    expected = {
        "app.py": english["nav.overview"],
        "pages/buglar.py": english["nav.bugs"],
        "pages/analiz.py": english["nav.analysis"],
        "pages/ayarlar.py": english["nav.settings"],
    }[script]

    at = _open(script)

    assert expected in [element.value for element in at.title]


@pytest.mark.parametrize("script", SCRIPTS)
def test_no_turkish_leaks_into_an_english_page(script: str):
    """The check that catches a literal somebody forgot to route through t().

    Scoped to labels the interface owns — see the module docstring. A failure
    names the element and the text, so the missing key is one grep away.
    """
    at = _open(script)

    leaks = [
        f"{kind}={text!r}"
        for kind, text in _chrome(at)
        if TURKISH_LETTERS & set(text)
    ]

    assert not leaks, f"{script} still renders Turkish: " + ", ".join(leaks)


def test_the_two_languages_actually_differ_on_screen():
    """Guards the guard above: an English page that never changed would pass it.

    Turkish has no exclusive letters in "Toplam Bug", so the leak test alone
    cannot tell a translated metric from an untranslated one. This names a
    label from each locale and asserts the English page shows one and not the
    other.
    """
    at = _open()

    labels = [text for _, text in _chrome(at)]

    assert i18n.catalog("en")["overview.metric.total_bugs"] in labels
    assert i18n.catalog("tr")["overview.metric.total_bugs"] not in labels


def test_the_language_picker_reports_english():
    at = _open()

    pickers = [s for s in at.sidebar.selectbox if s.label == i18n.catalog("en")["sidebar.language"]]
    assert pickers, "no language picker on an English page"
    assert pickers[0].value == "en"


def test_the_english_page_shows_the_english_demo_bugs():
    """End to end: the menus and the content are in the same language.

    Translating the interface around 20 Turkish bug reports would be half an
    i18n. This reads the bug table on the Buglar page and asserts it holds the
    English summaries — the keys stay AP-101 and friends in both files, so the
    summary text is what distinguishes them.
    """
    at = _open("pages/buglar.py")

    summaries = []
    for element in at.dataframe:
        if "summary" in element.value.columns:
            summaries += element.value["summary"].tolist()

    assert summaries, "the bug list rendered no rows"
    assert any("No error message shown" in text for text in summaries), summaries[:3]
    assert not any(TURKISH_LETTERS & set(text) for text in summaries), summaries[:3]


def test_the_risk_table_headers_are_translated():
    """column_config is where a translation gap is silent rather than loud.

    A key naming no column leaves the raw English DataFrame key as the header,
    with no exception and no warning — measured, see
    test_dataframe_headers_are_configured_for_columns_that_exist. Here the
    complementary half: the labels that reach the frontend are the catalog's.
    """
    import json

    at = _open()

    headers = set()
    for element in at.dataframe:
        for spec in json.loads(element.proto.columns).values():
            if "label" in spec:
                headers.add(spec["label"])

    english = i18n.catalog("en")
    assert english["col.risk_score"] in headers
    assert english["col.module"] in headers
    assert i18n.catalog("tr")["col.risk_score"] not in headers
