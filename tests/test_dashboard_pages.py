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
