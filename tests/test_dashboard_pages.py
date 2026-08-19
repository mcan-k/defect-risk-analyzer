"""
Headless walk of all 7 dashboard pages, ported from baseline/walk_pages.py.

Uses Streamlit's own AppTest harness: it executes the real dashboard script and
collects any exception the app raised instead of rendering a traceback in a
browser. No server, no HTTP, no port, no API key.

Also fails a page if st.error() surfaced, or if any text claims the backend is
unreachable — that is how the pre-Faz-2 HTTP layer reported "API down", and
those strings must never reappear now that the dashboard calls the service
directly.

Beyond "it did not raise", CONTENT below pins the sections each page renders.
That is what makes this suite useful to Faz 5B, which folds seven pages into
four: a merge can drop a heading or a filter without raising anything at all,
and the walk alone would stay green. Verified by mutation — deleting one
st.subheader from dashboard.py fails only the content test, not the walk.

Two things the original script depended on that a CI checkout does not have,
both fixed by the fixture below:

  * It assumed a populated .env so the setup wizard would not appear. That made
    the assertion depend on the developer's personal configuration. Here the
    sandbox .env is generated, so the check means the same thing everywhere.

  * USE_MOCK_DATA does NOT disable ChromaDB — it is read only by jira_client
    and merely selects the data source. VectorStore still writes to disk. The
    fixture replaces it outright, so chromadb is never even imported.
"""

import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from defect_risk_analyzer import config
from defect_risk_analyzer.services import analysis_service as analysis_service_module

pytestmark = pytest.mark.slow

# Resolved from the installed package rather than a path relative to this file,
# so the walk follows whichever copy of the package the tests import.
APP = str(Path(config.__file__).resolve().parent / "dashboard.py")

PAGES = [
    "📊 Dashboard",
    "🐛 Bug Listesi",
    "⚡ Canlı Analiz",
    "🔗 Pattern Tespiti",
    "🎯 Kör Nokta Tespiti",
    "🔔 Webhook Sonuçları",
    "⚙️ Ayarlar",
]

# What each page actually renders today, measured against this app rather than
# read off the source: the assertions below are the contract Faz 5B's page merge
# has to keep. The walk above only proves a page did not raise — a section could
# vanish during the merge and nothing would notice.
#
# Deliberately excluded: anything carrying a day count. The blind spot findings
# render "155 gündür 'Open' durumunda", and that number grows with the wall
# clock, so pinning it would make this suite fail on a future Tuesday for no
# reason. Section headings and widget labels are the stable part.
#
# The blind spot headings below do depend on the sample bugs staying stale and
# unanalyzed. That only becomes more true as time passes — days_open grows, the
# 14-day threshold stays put, and the sandbox has no analysis results at all.
CONTENT: dict[str, dict[str, tuple[str, ...]]] = {
    "📊 Dashboard": {
        "title": ("📊 Risk Dashboard",),
        "subheader": (
            "Modül Risk Haritası",
            "Bug Dağılımı (Modül Bazında)",
            "Modül Risk Sıralaması",
            "📈 Bug Trend Analizi",
        ),
        "metric": ("Toplam Bug", "Analiz Edilen", "🔴 Kritik Modül", "🟠 Yüksek Risk Modül"),
    },
    "🐛 Bug Listesi": {
        "title": ("🐛 Bug Listesi",),
        "multiselect": ("Öncelik Filtresi", "Durum Filtresi", "Modül Filtresi"),
        "text_input": ("🔍 Ara (bug key veya özet)",),
    },
    "⚡ Canlı Analiz": {
        "title": ("⚡ Canlı Analiz",),
        "tabs": ("🔍 Tekli Analiz", "📦 Toplu Analiz"),
        "subheader": ("Tekli Bug / Alan Analizi", "Toplu Bug Analizi"),
        "radio": ("Analiz Türü",),
        "text_input": ("Bug Key",),
        "multiselect": ("Analiz edilecek bugları seçin",),
        "button": ("🚀 Analiz Et", "🚀 Toplu Analiz Başlat"),
    },
    "🔗 Pattern Tespiti": {
        "title": ("🔗 Pattern Tespiti",),
        "caption": ("Benzer bug'ları otomatik gruplar ve olası ortak nedenleri tespit eder.",),
        # StubVectorStore.collection is None, so this page renders its no-data
        # branch. That is the branch the merge must preserve.
        "info": (
            "Pattern tespit edilemedi. Yeterli bug verisi yüklendikten sonra bu sayfa "
            "otomatik dolar.",
        ),
    },
    "🎯 Kör Nokta Tespiti": {
        "title": ("🎯 Kör Nokta Tespiti",),
        "metric": ("Toplam Kör Nokta", "🔴 Kritik", "Sahipsiz Bug", "Bayat Bug"),
        "subheader": (
            "⚠️ Analiz Edilmemiş Riskli Modüller",
            "🚨 Sahipsiz Kritik Bug'lar",
            "🕐 Bayat Bug'lar (14+ gündür açık)",
            "📋 Önerilen Aksiyonlar",
        ),
    },
    "🔔 Webhook Sonuçları": {
        "title": ("🔔 Webhook Sonuçları",),
        "subheader": ("Webhook Nasıl Kurulur?",),
        "info": ("Henüz webhook analiz sonucu yok.",),
    },
    "⚙️ Ayarlar": {
        "title": ("⚙️ Ayarlar",),
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
        "number_input": (
            "Günlük Maksimum LLM İstek Sayısı",
            "İstekler Arası Bekleme (saniye)",
        ),
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
    #
    # The credentials are dummies but deliberately COMPLETE. The Settings page
    # renders st.error("Jira Eksik" / "LLM Eksik") for missing configuration,
    # and this suite treats any st.error as a failure. Half-configuring here
    # would mean relaxing that rule for one page; instead the fixture
    # represents what it claims to — a fully configured install running in mock
    # mode. Nothing reaches Jira: refresh_data() checks USE_MOCK_DATA before
    # is_jira_configured(), so mock mode wins. Nothing reaches an LLM either;
    # analysis is button-triggered and no test clicks it.
    config.ENV_FILE.write_text(
        "USE_MOCK_DATA=True\n"
        "ANONYMIZE_DATA=False\n"
        "GROQ_SLEEP=0\n"
        "JIRA_URL=https://example.atlassian.net\n"
        "JIRA_EMAIL=tests@example.com\n"
        "JIRA_API_TOKEN=dummy-token-not-a-real-credential\n"
        "JIRA_PROJECT_KEY=TEST\n"
        "LLM_PROVIDER=groq\n"
        "GROQ_API_KEY=dummy-key-not-a-real-credential\n",
        encoding="utf-8",
    )

    # Mock mode loads config.SAMPLE_BUGS_FILE, which the sandbox redirected.
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(sample_bugs_path, config.SAMPLE_BUGS_FILE)

    # Let dashboard's config.init() actually run and read the file above.
    mp.setattr(config, "_initialized", False)

    # AnalysisService() resolves VectorStore from its own module namespace, so
    # patching the name there covers the no-argument construction in
    # dashboard.get_service().
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


def _fresh_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    return at


def _open(page: str) -> AppTest:
    """A fresh app showing `page`."""
    at = _fresh_app()
    at.sidebar.radio[0].set_value(page).run()
    return at


def _rendered(at: AppTest, kind: str) -> list[str]:
    """Visible text of every `kind` element on the page, sidebar included."""
    attribute = "label" if kind in _LABELLED else "value"
    return [getattr(element, attribute) for element in getattr(at, kind)]


def test_setup_wizard_does_not_appear_when_configured():
    """A configured install must land on the app, not back in the wizard.

    If config.init() were missing, every setting would fall back to its default,
    is_first_run() would return True, and a configured user would be sent to the
    setup wizard. The sandbox .env is what makes this assertion independent of
    the developer's own configuration.
    """
    at = _fresh_app()

    titles = [t.value for t in at.title]
    assert not any("İlk Kurulum" in t for t in titles), (
        f"setup wizard appeared despite a configured .env: {titles}"
    )


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_errors(page: str):
    at = _fresh_app()

    assert not at.exception, [f"{e.value}" for e in at.exception]

    # The sidebar radio drives the router.
    at.sidebar.radio[0].set_value(page).run()

    assert not _problems(at), f"{page}: " + "; ".join(_problems(at))


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_all_of_its_sections(page: str):
    """Every heading and widget the page shows today must survive Faz 5B.

    Membership rather than equality on purpose: the sidebar contributes its own
    metrics and buttons to these lists, and a page is free to grow. What must
    not happen is a section quietly disappearing when seven pages become four.
    """
    at = _open(page)

    missing = [
        f"{kind}={text!r}"
        for kind, expected in CONTENT[page].items()
        for text in expected
        if text not in _rendered(at, kind)
    ]

    assert not missing, f"{page} no longer renders: " + ", ".join(missing)


def test_sync_button_is_present_and_works():
    """The sync button used to be hidden behind a reachable-backend check."""
    at = _fresh_app()

    sync = [b for b in at.sidebar.button if "Senkronize" in b.label]
    assert sync, "sidebar sync button is missing"

    sync[0].click().run()

    assert not at.exception, [f"{e.value}" for e in at.exception]
