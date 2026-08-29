"""
Headless walk of the four dashboard pages.

Uses Streamlit's own AppTest harness: it executes the real page scripts and
collects any exception the app raised instead of rendering a traceback in a
browser. No server, no HTTP, no port, no API key.

Also fails a page if st.error() surfaced, or if any text claims the backend is
unreachable — that is how the pre-Faz-2 HTTP layer reported "API down", and
those strings must never reappear now that the dashboard calls the service
directly.

Beyond "it did not raise", CONTENT pins the sections each page renders. Faz 5B
folded seven pages into four, and a merge can drop a heading or a filter
without raising anything at all — the walk alone would stay green. Verified by
mutation: deleting one st.subheader fails only the content test.

WHY pages/ AND NOT st.navigation: streamlit 1.41.1's AppTest says so itself
(streamlit/testing/v1/app_test.py:129) — it is not compatible with st.navigation
and st.Page. The reason is structural: st.Page hashes its URL path while
AppTest.switch_page hashes an absolute file path, so under st.navigation AppTest
can only ever render the default page. With the pages/ directory,
at.switch_page("pages/x.py") runs that script and three of the four pages stay
reachable from a test.

Two things the original script depended on that a CI checkout does not have,
both fixed by the fixture below:

  * It assumed a populated .env so the setup wizard would not appear. That made
    the assertion depend on the developer's personal configuration. Here the
    sandbox .env is generated, so the check means the same thing everywhere.

  * USE_MOCK_DATA does NOT disable ChromaDB — it is read only by jira_client
    and merely selects the data source. VectorStore still writes to disk. The
    fixture replaces it outright, so chromadb is never even imported.
"""

import ast
import json
import os
import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from defect_risk_analyzer import config
from defect_risk_analyzer.services import analysis_service as analysis_service_module
from defect_risk_analyzer.ui import shell

pytestmark = pytest.mark.slow

# Resolved from the installed package rather than a path relative to this file,
# so the walk follows whichever copy of the package the tests import.
APP = str(Path(config.__file__).resolve().parent / "ui" / "app.py")

# Paths as AppTest.switch_page wants them: relative to the entry script.
SCRIPTS = ["app.py", "pages/buglar.py", "pages/analiz.py", "pages/ayarlar.py"]

TITLES = {
    "app.py": "📊 Genel Bakış",
    "pages/buglar.py": "🐛 Buglar",
    "pages/analiz.py": "⚡ Analiz",
    "pages/ayarlar.py": "⚙️ Ayarlar",
}

# The merge contract. Each label here was a page title before Faz 5B, so this
# list is also the record of which old page ended up where. Ayarlar absorbed
# nothing and therefore has no tabs.
TABS = {
    "app.py": ["📊 Risk Dashboard", "🎯 Kör Nokta Tespiti"],
    "pages/buglar.py": ["🐛 Bug Listesi", "🔗 Pattern Tespiti"],
    "pages/analiz.py": ["🔍 Tekli Analiz", "📦 Toplu Analiz", "🔔 Webhook Sonuçları"],
    "pages/ayarlar.py": [],
}

# What each page renders, measured against the running app rather than read off
# the source. Membership, not equality: the sidebar contributes its own metrics
# and buttons to these lists, and a page is free to grow — what must not happen
# is a section quietly disappearing.
#
# Deliberately excluded: anything carrying a day count. The blind spot findings
# render "155 gündür 'Open' durumunda", and that number grows with the wall
# clock, so pinning it would fail on a future Tuesday for no reason.
#
# The blind spot headings do depend on the sample bugs staying stale and
# unanalyzed. That only becomes more true as time passes — days_open grows, the
# 14-day threshold stays put, and the sandbox has no analysis results at all.
CONTENT: dict[str, dict[str, tuple[str, ...]]] = {
    "app.py": {
        "subheader": (
            # Risk Dashboard
            "Modül Risk Haritası",
            "Bug Dağılımı (Modül Bazında)",
            "Modül Risk Sıralaması",
            "📈 Bug Trend Analizi",
            # Kör Nokta Tespiti
            "⚠️ Analiz Edilmemiş Riskli Modüller",
            "🚨 Sahipsiz Kritik Bug'lar",
            "🕐 Bayat Bug'lar (14+ gündür açık)",
            "📋 Önerilen Aksiyonlar",
        ),
        "metric": (
            "Toplam Bug",
            "Analiz Edilen",
            "🔴 Kritik Modül",
            "🟠 Yüksek Risk Modül",
            "Toplam Kör Nokta",
            "🔴 Kritik",
            "Sahipsiz Bug",
            "Bayat Bug",
        ),
    },
    "pages/buglar.py": {
        "multiselect": ("Öncelik Filtresi", "Durum Filtresi", "Modül Filtresi"),
        "text_input": ("🔍 Ara (bug key veya özet)",),
        "caption": ("Benzer bug'ları otomatik gruplar ve olası ortak nedenleri tespit eder.",),
        # StubVectorStore.collection is None, so pattern detection renders its
        # no-data branch. That is the branch the merge must preserve.
        "info": (
            "Pattern tespit edilemedi. Yeterli bug verisi yüklendikten sonra bu sayfa "
            "otomatik dolar.",
        ),
    },
    "pages/analiz.py": {
        "subheader": ("Tekli Bug / Alan Analizi", "Toplu Bug Analizi", "Webhook Nasıl Kurulur?"),
        "radio": ("Analiz Türü",),
        "text_input": ("Bug Key",),
        "multiselect": ("Analiz edilecek bugları seçin",),
        "button": ("🚀 Analiz Et", "🚀 Toplu Analiz Başlat"),
        "info": ("Henüz webhook analiz sonucu yok.",),
    },
    "pages/ayarlar.py": {
        "subheader": (
            "🔗 Jira Bağlantısı",
            "🤖 LLM Sağlayıcı",
            "🛠️ Uygulama Ayarları",
            "🔒 Veri Anonimleştirme",
            "📋 Sistem Durumu",
            "🔑 API Key (webhook servisi için)",
        ),
        "text_input": ("Jira URL", "Jira E-posta", "Jira API Token", "Proje Key", "Groq API Key"),
        "selectbox": ("Sağlayıcı",),
        "toggle": ("Mock Data Modu (Jira olmadan demo)", "Veri Anonimleştirme"),
        "number_input": ("Günlük Maksimum LLM İstek Sayısı", "İstekler Arası Bekleme (saniye)"),
        "button": (
            "💾 Jira Ayarlarını Kaydet",
            "🧪 Jira Bağlantısını Test Et",
            "💾 LLM Ayarlarını Kaydet",
            "🧪 LLM Bağlantısını Test Et",
            "💾 Uygulama Ayarlarını Kaydet",
            "🔑 API Key Üret",
        ),
    },
}

# Elements whose visible text lives on `.label`; everything else uses `.value`.
_LABELLED = frozenset(
    {"metric", "multiselect", "text_input", "radio", "selectbox", "toggle",
     "number_input", "button", "tabs"}
)

# Substrings that mean the page still believes it needs a backend.
FORBIDDEN = (
    "API Bağlantısı Yok",
    "API sunucusuna bağlanılamıyor",
    "Backend çalışmıyor",
    "API Kapalı",
    "zaman aşımına uğradı",
)

# The credentials are dummies but deliberately COMPLETE. The Settings page
# renders st.error("Jira Eksik" / "LLM Eksik") for missing configuration, and
# this suite treats any st.error as a failure. Half-configuring here would mean
# relaxing that rule for one page; instead the fixture represents what it claims
# to — a fully configured install running in mock mode. Nothing reaches Jira:
# refresh_data() checks USE_MOCK_DATA before is_jira_configured(), so mock mode
# wins. Nothing reaches an LLM either; analysis is button-triggered and no test
# clicks it.
#
# DRA_LANGUAGE is pinned for the same reason the credentials are: every content
# assertion in this file is a Turkish string, and without this line those pins
# would quietly mean "whatever language the developer last picked".
CONFIGURED_ENV = (
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

# Every key CONFIGURED_ENV sets that a first-run check looks at. load_dotenv
# only assigns what the file names, so a key left in os.environ survives an
# emptied .env and keeps is_first_run() False — which is how a wizard test can
# silently assert nothing at all.
_CONFIG_KEYS = (
    "JIRA_URL",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
    "JIRA_PROJECT_KEY",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "LLM_PROVIDER",
    "USE_MOCK_DATA",
)


class StubVectorStore:
    """In-memory stand-in for the ChromaDB adapter.

    `collection` returns None deliberately: pattern_detector and
    blind_spot_detector both guard with `collection is None or
    collection.count() == 0` and degrade to an empty result, which is exactly
    the no-data path we want those pages to render.
    """

    def __init__(self, *args, **kwargs) -> None:
        self._bugs: list[dict] = []

    def upsert_bugs(self, bugs: list[dict]) -> int:
        self._bugs = list(bugs)
        return len(self._bugs)

    def query_similar(self, query: str, n_results: int = 5) -> list[dict]:
        return []

    def count(self) -> int:
        return len(self._bugs)

    def reset(self) -> None:
        self._bugs = []

    @property
    def collection(self):
        return None


@pytest.fixture(scope="module", autouse=True)
def dashboard_env(sandbox_dir, sample_bugs_path):
    """Mock mode, sandboxed paths, and no ChromaDB.

    Module-scoped because it is shared by every page test; monkeypatch is
    function-scoped, so this uses a MonkeyPatch context manually.
    """
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()

    # Mock mode has to come from the .env file, not os.environ: config.reload()
    # calls load_dotenv(ENV_FILE, override=True), so the file wins over the
    # environment. ENV_FILE already points into the sandbox.
    config.ENV_FILE.write_text(CONFIGURED_ENV, encoding="utf-8")

    # Mock mode loads config.SAMPLE_BUGS_FILE, which the sandbox redirected.
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(sample_bugs_path, config.SAMPLE_BUGS_FILE)
    # Both demo sets, so config.sample_bugs_file() has a real choice to make —
    # without the English one the language walk below would "pass" on the
    # Turkish fallback and prove nothing. Copied per module rather than once
    # per session on purpose: test_sample_data_parity.py unlinks the English
    # file to exercise that fallback and does not put it back, and the two
    # share a single sandbox.
    shutil.copyfile(sample_bugs_path.parent / "sample_bugs_en.json", config.SAMPLE_BUGS_EN_FILE)

    # Let bootstrap's config.init() actually run and read the file above.
    mp.setattr(config, "_initialized", False)

    # AnalysisService() resolves VectorStore from its own module namespace, so
    # patching the name there covers the no-argument construction in
    # ui.service.get_service().
    mp.setattr(analysis_service_module, "VectorStore", StubVectorStore)

    yield

    mp.undo()


@pytest.fixture(autouse=True)
def _clear_streamlit_caches():
    """get_service() is @st.cache_resource — cached per process, not per run.

    Without this the service built by the first test would be reused by every
    later one, holding whatever configuration was live at that moment.
    """
    import streamlit as st

    st.cache_resource.clear()
    st.cache_data.clear()


def _rewrite_env(text: str):
    """Swap .env for `text` and restore it, config globals included.

    Restoring the file is not enough on its own: config caches every setting in
    module globals, and init() is guarded by a flag that a plain restore leaves
    set. Without the reload on the way out, a wizard test would leave every
    later test looking at an unconfigured install.
    """
    saved_environ = {key: os.environ[key] for key in _CONFIG_KEYS if key in os.environ}
    saved_file = config.ENV_FILE.read_text(encoding="utf-8")

    for key in _CONFIG_KEYS:
        os.environ.pop(key, None)
    config.ENV_FILE.write_text(text, encoding="utf-8")
    config._initialized = False

    yield

    config.ENV_FILE.write_text(saved_file, encoding="utf-8")
    for key in _CONFIG_KEYS:
        os.environ.pop(key, None)
    os.environ.update(saved_environ)
    config._initialized = False
    config.reload()


@pytest.fixture
def unconfigured():
    """A fresh install: no Jira, no LLM key, no mock mode — so is_first_run()."""
    yield from _rewrite_env("")


@pytest.fixture
def restorable_env():
    """The configured install, with the .env restored afterwards.

    For tests that make the app WRITE to .env. The module fixture writes
    CONFIGURED_ENV once; without this, a test that changes a setting would
    leave every later test looking at that change.
    """
    yield from _rewrite_env(CONFIGURED_ENV)


@pytest.fixture
def without_llm():
    """Configured enough not to be a first run, but with no LLM key."""
    lines = [
        line
        for line in CONFIGURED_ENV.splitlines(keepends=True)
        if not line.startswith("GROQ_API_KEY=")
    ]
    yield from _rewrite_env("".join(lines))


def _problems(at: AppTest) -> list[str]:
    """Everything wrong with a rendered page, as human-readable strings."""
    found = [f"EXCEPTION: {exc.value}" for exc in at.exception]

    errors = [e.value for e in at.error]
    found += [f"st.error: {err}" for err in errors]

    body = " ".join(
        [e.value for e in at.markdown]
        + [e.value for e in at.info]
        + [e.value for e in at.warning]
        + errors
    )
    found += [f"backend-dependent text: {phrase!r}" for phrase in FORBIDDEN if phrase in body]

    return found


def _open(script: str = "app.py") -> AppTest:
    """A fresh app showing `script`.

    app.py is the entry point, so it needs no switch; the other three are
    reached the only way AppTest supports, by running that file as the script.
    """
    at = AppTest.from_file(APP, default_timeout=120)
    if script != "app.py":
        at.switch_page(script)
    at.run()
    return at


def _rendered(at: AppTest, kind: str) -> list[str]:
    """Visible text of every `kind` element on the page, sidebar included."""
    attribute = "label" if kind in _LABELLED else "value"
    return [getattr(element, attribute) for element in getattr(at, kind)]


# ---------------------------------------------------------------------------
# The four pages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script", SCRIPTS)
def test_page_renders_without_errors(script: str):
    at = _open(script)

    assert not _problems(at), f"{script}: " + "; ".join(_problems(at))


@pytest.mark.parametrize("script", SCRIPTS)
def test_page_has_its_title(script: str):
    at = _open(script)

    assert TITLES[script] in _rendered(at, "title")


@pytest.mark.parametrize("script", SCRIPTS)
def test_page_has_exactly_the_tabs_the_merge_promised(script: str):
    """Equality here, unlike CONTENT: the tab list IS the merge contract.

    Every label was a page of its own before Faz 5B. An extra tab or a missing
    one means a page moved somewhere nobody decided on.
    """
    at = _open(script)

    assert _rendered(at, "tabs") == TABS[script]


@pytest.mark.parametrize("script", SCRIPTS)
def test_page_renders_all_of_its_sections(script: str):
    at = _open(script)

    missing = [
        f"{kind}={text!r}"
        for kind, expected in CONTENT[script].items()
        for text in expected
        if text not in _rendered(at, kind)
    ]

    assert not missing, f"{script} no longer renders: " + ", ".join(missing)


@pytest.mark.parametrize("script", SCRIPTS)
def test_dataframe_headers_are_configured_for_columns_that_exist(script: str):
    """A typo in column_config is silent, and worse than unlabelled.

    MEASURED, because the plan was unsure: streamlit 1.41.1 does not validate
    column_config against the DataFrame at all. A key naming no column raises
    nothing, warns nothing, and is serialised to the frontend as written — so
    the real column keeps its raw name as the header. Since Faz 5C renamed
    every DataFrame column to a stable English key, that failure now shows the
    user "risk_score" where "Risk Skoru" belongs, in neither language, and
    every other assertion in this file stays green.

    Probed with three dataframes (all keys right / one misspelled / all wrong):
    no exception in any case, and proto.columns carried the bad key verbatim.
    That probe is also what makes this check possible — the config arrives as
    JSON on the element, next to the frame it configures.
    """
    at = _open(script)

    stray = []
    for element in at.dataframe:
        configured = json.loads(element.proto.columns)
        columns = set(element.value.columns)
        stray += [
            f"{script}: column_config key {key!r} is not a column ({sorted(columns)})"
            for key in configured
            # "_index" is streamlit's own handle for the index, not a column.
            if not key.startswith("_") and key not in columns
        ]

    assert not stray, "; ".join(stray)


def test_sync_button_is_present_and_works():
    """The sync button used to be hidden behind a reachable-backend check."""
    at = _open()

    sync = [b for b in at.sidebar.button if "Senkronize" in b.label]
    assert sync, "sidebar sync button is missing"

    sync[0].click().run()

    assert not at.exception, [f"{e.value}" for e in at.exception]


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


def test_nav_declares_all_four_pages():
    """The one guard st.page_link can have.

    AppTest parses st.page_link into an UnknownElement — there is no accessor
    for it, so no rendered-page assertion can tell whether the sidebar offers
    four links, three, or none. Deleting one would make a page unreachable
    while every other test in this file stayed green. Reading the source is
    coarse, but it is the only thing that closes that hole.

    What it still does not catch: a link moved inside a conditional branch, or
    render_nav() never being called at all. Recorded in docs/KNOWN-DEBT.md
    under "Sidebar navigasyonunu yalnız kaynak okuyan bir test koruyor", along
    with the condition for deleting this test — an AppTest accessor for
    st.page_link in a later Streamlit release.
    """
    tree = ast.parse(Path(shell.__file__).read_text(encoding="utf-8"))

    targets = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "page_link"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]

    assert targets == SCRIPTS

    entry_directory = Path(APP).parent
    for target in targets:
        assert (entry_directory / target).is_file(), f"nav points at a missing page: {target}"


def test_the_analysis_page_links_to_settings_when_no_llm_is_configured(without_llm):
    """Replaces the session_state["force_page"] router bypass.

    The old page set a session key and main() popped it before rendering the
    sidebar, so the radio kept reporting the page the user had left. st.switch_page
    is the native equivalent and needs no key at all.
    """
    at = _open("pages/analiz.py")

    assert any("LLM API Key yapılandırılmamış" in w.value for w in at.warning)

    button = [b for b in at.button if "Ayarlar Sayfasına Git" in b.label]
    assert button, "no link to the settings page"

    button[0].click().run()

    # Positive assertion on purpose. st.switch_page reruns inside this same
    # run(), and AppTest does not clear its message queue between the two, so
    # widgets from the pre-switch page survive at any delta path the new page
    # does not overwrite. What is reliable is that the new page's own elements
    # are there.
    assert "⚙️ Ayarlar" in _rendered(at, "title")


def test_the_webhook_tab_reads_without_an_llm(without_llm):
    """The old page-level LLM guard would have taken this down with it.

    page_live_analysis returned early when no LLM was configured. Applying that
    to the merged page would hide the webhook history too — and that history is
    readable with no LLM at all, so the guard covers only the two analysis tabs.
    """
    at = _open("pages/analiz.py")

    assert _rendered(at, "tabs") == TABS["pages/analiz.py"]
    assert "Henüz webhook analiz sonucu yok." in _rendered(at, "info")


# ---------------------------------------------------------------------------
# Language picker
# ---------------------------------------------------------------------------


def test_the_sidebar_offers_the_language_picker():
    """Every page draws it, because render_nav() is part of bootstrap()."""
    at = _open()

    pickers = [s for s in at.sidebar.selectbox if s.label == "Dil"]
    assert pickers, f"no language picker in the sidebar: {[s.label for s in at.sidebar.selectbox]}"
    # AppTest reports options as the strings the user actually sees, i.e. after
    # format_func. Endonyms on purpose: a language picker written in the
    # language you cannot read is the one control a lost user cannot use.
    assert pickers[0].options == ["Türkçe", "English"]
    assert pickers[0].value == "tr"


def test_the_wizard_offers_the_language_picker_without_shifting_the_mode_radio(unconfigured):
    """The wizard is the only screen a fresh install has, and it has no sidebar.

    The second assertion is the reason the picker is a selectbox: the wizard's
    mode picker is reached below as at.radio[0], and a radio-shaped language
    control would take that index and make those tests drive the wrong widget
    while still passing.
    """
    at = _open()

    assert any(s.label == "Dil" for s in at.selectbox)
    assert at.radio[0].label == "Mod seçin:"


def test_choosing_a_language_persists_it_to_env(restorable_env):
    """Live for this session, and still chosen after a restart.

    session_state alone would forget on the next browser session; .env alone
    would need a restart to take effect. The picker writes both, and this pins
    the half that outlives the process.
    """
    at = _open()

    picker = [s for s in at.sidebar.selectbox if s.label == "Dil"][0]
    picker.set_value("en").run()

    assert "DRA_LANGUAGE=en" in config.ENV_FILE.read_text(encoding="utf-8")
    assert not at.exception, [f"{e.value}" for e in at.exception]


class _Recorder:
    """A stand-in for st / st.sidebar that just keeps the selectbox kwargs.

    render_selector() touches nothing else on the container, so this needs no
    script run context — which is the only way to read the help text at all:
    AppTest's Selectbox wrapper exposes value/options/format_func and no help.
    """

    def __init__(self) -> None:
        self.kwargs: dict = {}

    def selectbox(self, label, **kwargs):
        self.kwargs = dict(kwargs, label=label)


@pytest.mark.parametrize(
    ("mock_mode", "expected", "forbidden"),
    [
        (True, "Senkronize", "Jira'dan geldiği"),
        (False, "Jira'dan geldiği", "Senkronize"),
    ],
)
def test_the_language_picker_tells_the_user_what_to_do_about_the_data(
    monkeypatch, mock_mode, expected, forbidden
):
    """The other half of the gap this fix closes.

    Making the sync work is not enough if nothing tells the user a sync is
    needed: the interface flips at once and the bug text does not, and the
    picker said nothing at all about that before.

    Mode-dependent because the honest sentence differs. Under mock data the
    demo set follows the next sync; against a real Jira the text comes from
    Jira and the language never touches it, so the mock sentence would be a
    promise the code cannot keep. Inverting the branch fails here.
    """
    from defect_risk_analyzer.ui import i18n, language

    # Every other test here gets Turkish from _open() -> bootstrap() ->
    # language.apply(). This one drives render_selector directly, so it would
    # otherwise inherit whatever language ran last — test_dashboard_language.py
    # leaves English behind, and these assertions are Turkish sentences.
    monkeypatch.setattr(i18n, "_active", "tr")
    monkeypatch.setattr(config, "USE_MOCK_DATA", mock_mode)
    recorder = _Recorder()

    language.render_selector(recorder)

    help_text = recorder.kwargs["help"]
    assert expected in help_text
    assert forbidden not in help_text
    # The button name is interpolated from sidebar.sync rather than copied, so
    # renaming the button cannot leave this sentence pointing at a dead label.
    assert "{action}" not in help_text


def test_choosing_a_language_makes_the_next_sync_load_the_matching_demo_set(restorable_env):
    """The live path Faz 5C promised and did not deliver.

    Nothing else walked it. test_sample_data_parity.py pins sample_bugs_file()
    by monkeypatching config.LANGUAGE, which steps straight over the edge that
    was missing: the picker wrote .env and left the module global on whatever
    the process booted with, so a sync after a switch reloaded the boot
    language. Not an EN-to-TR bug — the picker contributed nothing to the data
    choice in either direction, and switching TO the boot language only looked
    like it worked.

    Why AppTest and not a service-level call: the defect lives in the wiring
    between the widget callback and config, so a test that calls the config
    helper itself would stay green even if _persist() never called it. Driving
    the real selectbox is the only level that can fail for the right reason.

    The LLM sentinel is the other half of the contract. Routing the picker
    through ui.service.save_multiple_env would also fix the language and would
    drop the provider on every toggle; this is what keeps that from happening.
    """
    from defect_risk_analyzer.ui.service import get_service

    at = _open()

    service = get_service()
    llm = object()
    service._llm = llm

    picker = [s for s in at.sidebar.selectbox if s.label == "Dil"][0]
    picker.set_value("en").run()

    # The fix itself, then the setting that reads it.
    assert config.LANGUAGE == "en"
    assert config.sample_bugs_file() == config.SAMPLE_BUGS_EN_FILE

    # The button's own label is translated too, so by now it reads in English.
    sync = [b for b in at.sidebar.button if "Sync from Jira" in b.label]
    assert sync, f"no sync button in the sidebar: {[b.label for b in at.sidebar.button]}"
    sync[0].click().run()

    # The payoff: the bugs actually in memory are the English set, verbatim.
    expected = json.loads(config.SAMPLE_BUGS_EN_FILE.read_text(encoding="utf-8"))
    assert [b["summary"] for b in service.get_bugs()] == [b["summary"] for b in expected]

    assert service._llm is llm, "the language picker dropped the LLM provider"
    assert not at.exception, [f"{e.value}" for e in at.exception]


# ---------------------------------------------------------------------------
# First-run setup wizard
# ---------------------------------------------------------------------------


def test_setup_wizard_does_not_appear_when_configured():
    """A configured install must land on the app, not back in the wizard.

    If config.init() were missing, every setting would fall back to its default,
    is_first_run() would return True, and a configured user would be sent to the
    setup wizard. The sandbox .env is what makes this assertion independent of
    the developer's own configuration.
    """
    at = _open()

    titles = _rendered(at, "title")
    assert not any("İlk Kurulum" in t for t in titles), (
        f"setup wizard appeared despite a configured .env: {titles}"
    )


def test_the_wizard_appears_when_nothing_is_configured(unconfigured):
    """The path the old suite never walked.

    Its only wizard test asserted the wizard was absent. Nothing checked that
    it works when it does appear, so Faz 5B could have moved it broken.
    """
    at = _open()

    assert "🚀 Defect Risk Analyzer — İlk Kurulum" in _rendered(at, "title")
    assert "Adım 1: Çalışma Modu" in _rendered(at, "subheader")
    assert not at.exception, [f"{e.value}" for e in at.exception]


def test_the_wizard_leaves_the_sidebar_empty(unconfigured):
    """bootstrap() calls st.stop() before it draws anything in the sidebar.

    That ordering is the whole reason the built-in pages/ navigation is turned
    off and render_nav draws its own: a navigation rendered by the frontend
    could not be suppressed for one run, and the wizard would appear with a
    working page switcher beside it. If this fails, the wizard is escapable.
    """
    at = _open()

    # Block.__iter__ yields the block itself first, so a length of one means the
    # sidebar holds no elements at all.
    assert len(list(at.sidebar)) == 1, f"sidebar is not empty: {list(at.sidebar)}"


def test_the_wizard_gate_is_on_every_page(unconfigured):
    """The gate lives in bootstrap(), not in the entry script.

    Reaching a page directly by URL has to hit the wizard too, otherwise a
    fresh install has three unguarded doors.
    """
    at = _open("pages/ayarlar.py")

    assert "🚀 Defect Risk Analyzer — İlk Kurulum" in _rendered(at, "title")


def test_the_wizard_live_mode_asks_for_jira_and_an_llm_key(unconfigured):
    """Demo is the default, so steps 2 and 3 only exist on the other branch."""
    at = _open()

    mode = at.radio[0]
    mode.set_value("🔗 Canlı Mod (Gerçek Jira hesabımla kullanacağım)").run()

    assert "Sağlayıcı" in _rendered(at, "selectbox")
    for label in ("Jira URL", "Jira E-posta", "Jira API Token", "Proje Key"):
        assert label in _rendered(at, "text_input")


def test_the_wizard_demo_button_writes_mock_mode(unconfigured):
    """Proves the wizard does something, not merely that it renders.

    Asserted against the .env on disk rather than the element tree: the wizard
    ends with st.rerun(), and the tree that comes back is a merge of both runs.
    The file is unambiguous.
    """
    at = _open()

    demo = [b for b in at.button if "Demo Modunu Aktifleştir" in b.label]
    assert demo, f"demo button missing: {[b.label for b in at.button]}"

    demo[0].click().run()

    assert "USE_MOCK_DATA=True" in config.ENV_FILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Faz 6B — the legacy anon_map.json removal notice
# ---------------------------------------------------------------------------
# config.init() deletes a pre-6B data/anon_map.json, which held the
# anonymisation mapping in plain text. That is a silent deletion of a file the
# user never asked us to touch, so it is reported where a person will see it.
# The headless half is a logger.warning from config; this is the screen half.

def _notice() -> str:
    from defect_risk_analyzer.ui.i18n import t

    return t("shell.legacy_anon_map_removed")


def _boot_with_legacy_map(monkeypatch, *, present: bool):
    """Run bootstrap() for real with, or without, a leftover mapping file.

    THE FLAG CANNOT BE FAKED, and finding that out is what this helper records.
    Setting `config.LEGACY_ANON_MAP_REMOVED` before opening the app measures
    nothing: `bootstrap()` calls `config.init()`, which WRITES that flag, so the
    pre-seeded value is gone before the notice ever reads it (measured — True
    going in, False coming out). The flag is only ever authoritative as `init()`
    left it, which means the honest test is the whole chain: a file on disk, a
    purge that removes it, a flag, a notice.

    `_initialized` has to be reset because it is process-global and an earlier
    test in this module has already tripped it, and `init()` does the purge only
    on the first call.
    """
    config.ANON_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    if present:
        config.ANON_MAP_FILE.write_text('{"forward": {}, "reverse": {}}', encoding="utf-8")
    elif config.ANON_MAP_FILE.exists():
        config.ANON_MAP_FILE.unlink()

    monkeypatch.setattr(config, "_initialized", False)
    return _open()


def test_the_removal_notice_is_shown_when_a_file_was_removed(monkeypatch):
    """The whole chain: leftover file -> purge -> flag -> notice on screen."""
    at = _boot_with_legacy_map(monkeypatch, present=True)

    assert not config.ANON_MAP_FILE.exists(), "the purge did not run"
    assert any(_notice() in w for w in _rendered(at, "warning")), (
        "the deletion happened and nothing on screen said so"
    )


def test_no_notice_when_nothing_was_removed(monkeypatch):
    """The other half, and the one a mutation kills.

    Dropping the flag check makes the notice unconditional: every user is told
    a file was deleted, including the overwhelming majority for whom none was.
    That reads as a bug in the product and teaches people to ignore the banner.
    """
    at = _boot_with_legacy_map(monkeypatch, present=False)

    assert not any(_notice() in w for w in _rendered(at, "warning"))


def test_the_notice_is_shown_once_per_session(monkeypatch):
    """Streamlit re-runs the script on every interaction.

    Without the session_state gate the banner returns on every click for the
    life of the process. config's flag cannot carry this: it is per process, and
    one process serves every browser session.
    """
    at = _boot_with_legacy_map(monkeypatch, present=True)
    assert any(_notice() in w for w in _rendered(at, "warning"))

    at.run()

    assert not any(_notice() in w for w in _rendered(at, "warning")), (
        "the notice came back on a rerun"
    )


# ---------------------------------------------------------------------------
# Faz 6B — no page may push a credential into the process environment
# ---------------------------------------------------------------------------

def _env_writes(tree: ast.AST) -> list[str]:
    """Every statement in `tree` that writes to the process environment."""
    found = []

    def is_environ(node: ast.AST) -> bool:
        # os.environ
        if isinstance(node, ast.Attribute) and node.attr == "environ":
            return isinstance(node.value, ast.Name) and node.value.id == "os"
        # `from os import environ`
        return isinstance(node, ast.Name) and node.id == "environ"

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Subscript) and is_environ(target.value):
                    found.append(f"line {node.lineno}: assignment into os.environ")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"update", "setdefault", "pop"} and is_environ(node.func.value):
                found.append(f"line {node.lineno}: os.environ.{node.func.attr}()")
            if node.func.attr in {"putenv", "unsetenv"} and isinstance(node.func.value, ast.Name):
                if node.func.value.id == "os":
                    found.append(f"line {node.lineno}: os.{node.func.attr}()")

    return found


def test_no_ui_module_writes_to_the_process_environment():
    """A source-level guard, because the failure it prevents is invisible on screen.

    The Settings page used to do this, and it was wrong twice over (Ö-B). It set
    `os.environ["GROQ_API_KEY"]` to the typed key before building a provider —
    which did nothing, because providers read `config.GROQ_API_KEY`, a module
    global only `reload()` writes and that branch never called it — and which
    left the credential in the process environment for as long as the process
    lived. A test that clicked the button would have shown neither half.

    `config.set_env_value` remains the single writer: it goes through the atomic
    `.env` path and updates `os.environ` as one deliberate step. The rule here is
    that the UI layer asks config, and never reaches around it.
    """
    ui_root = Path(config.__file__).resolve().parent / "ui"

    offenders = {}
    for path in sorted(ui_root.rglob("*.py")):
        writes = _env_writes(ast.parse(path.read_text(encoding="utf-8")))
        if writes:
            offenders[path.relative_to(ui_root).as_posix()] = writes

    assert not offenders, f"UI modules writing to os.environ: {offenders}"


# ---------------------------------------------------------------------------
# Faz 6B — the credential migration, and its notice sharing a boot with D4's
# ---------------------------------------------------------------------------

class _RecordingStore:
    """A credential store that accepts everything and remembers it."""

    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = value
        return True

    def delete(self, name):
        self.values.pop(name, None)
        return True


def _boot_with_store(monkeypatch, store, *, legacy_map: bool = False):
    """bootstrap() with a credential store injected and `.env` restored after.

    The `.env` this module's fixture wrote carries two synthetic credentials, so
    a migration has something to move. It is restored afterwards because the
    file is module-scoped and every other test in here reads it.
    """
    saved_env = config.ENV_FILE.read_text(encoding="utf-8")

    config.ANON_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    if legacy_map:
        config.ANON_MAP_FILE.write_text("{}", encoding="utf-8")
    elif config.ANON_MAP_FILE.exists():
        config.ANON_MAP_FILE.unlink()

    monkeypatch.setattr(config, "_secret_store", store)
    monkeypatch.setattr(config, "_secret_store_code", "store_active")
    monkeypatch.setattr(config, "_secret_store_params", {"backend": "fake.Backend"})
    monkeypatch.setattr(config, "_secret_store_resolved", True)
    monkeypatch.setattr(config, "_initialized", False)
    try:
        return _open()
    finally:
        config.ENV_FILE.write_text(saved_env, encoding="utf-8")
        config._initialized = False
        config.reload()


def test_the_migration_moves_credentials_and_says_so(monkeypatch):
    store = _RecordingStore()

    at = _boot_with_store(monkeypatch, store)

    assert store.get("JIRA_API_TOKEN") == "dummy-token-not-a-real-credential"
    assert store.get("GROQ_API_KEY") == "dummy-key-not-a-real-credential"
    assert any("JIRA_API_TOKEN" in m for m in _rendered(at, "success")), (
        "credentials moved and nothing on screen said so"
    )


def test_no_store_means_no_migration_and_no_notice(monkeypatch):
    """The Docker, CI and no-extra case. Silence is correct here.

    Scoped to the migration notice rather than "no success element at all": the
    sidebar status block renders its own `st.success` for a configured Jira and
    LLM, so a blanket assertion would fail for a reason that has nothing to do
    with migration.
    """
    at = _boot_with_store(monkeypatch, None)

    assert not any("JIRA_API_TOKEN" in m for m in _rendered(at, "success")), (
        "a migration notice appeared with no store to migrate into"
    )
    assert "dummy-token-not-a-real-credential" in config.ENV_FILE.read_text(
        encoding="utf-8"
    ), "the credential was removed with nowhere to put it"


def test_both_notices_survive_the_same_boot(monkeypatch):
    """The purge notice and the migration notice can fire on one startup.

    They are separate messages from separate steps, and the failure mode worth
    guarding is one silently replacing the other — `st.warning` and `st.success`
    do not queue behind each other, but the ordering in bootstrap() could easily
    put one after an `st.stop()` and nobody would notice.
    """
    store = _RecordingStore()

    at = _boot_with_store(monkeypatch, store, legacy_map=True)

    assert any(
        _notice() in w for w in _rendered(at, "warning")
    ), "the anon_map purge notice went missing when a migration ran too"
    assert any(
        "JIRA_API_TOKEN" in m for m in _rendered(at, "success")
    ), "the migration notice went missing when a purge ran too"


# ---------------------------------------------------------------------------
# The credential-layer caption is RENDERED, not passed through raw
# ---------------------------------------------------------------------------
# Faz 6B shipped an English sentence built inside adapters/secrets.py into a
# Turkish page, and every test passed: the adapter's tests pinned the sentence,
# and no test looked at what the page actually displayed. The mutation that
# feeds the raw code straight to the caption survived until this existed.

def test_the_credential_layer_caption_is_translated():
    """EXPECTED RED before the fix — the caption showed adapter English.

    Under the sandbox the keyring import is blocked, so the layer resolves to
    `no_keyring` and the page must render THAT code's Turkish sentence. Three
    assertions, because each catches a different way of getting it wrong:
    the code leaking through raw, the adapter's English leaking through, and
    the sentence simply not being there.
    """
    at = _open("pages/ayarlar.py")

    captions = _rendered(at, "caption")
    layer_line = [c for c in captions if "Kimlik bilgisi katmanı" in c]

    assert layer_line, f"no credential-layer caption rendered: {captions}"
    rendered = layer_line[0]

    assert "kurulu değil" in rendered, f"not the Turkish no_keyring sentence: {rendered!r}"
    assert "no_keyring" not in rendered, f"the raw code leaked to the page: {rendered!r}"
    assert "is not installed" not in rendered, (
        f"the adapter's English leaked to the page: {rendered!r}"
    )
