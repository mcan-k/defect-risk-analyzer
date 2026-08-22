"""
The frame every page draws inside: page config, styling, first-run gate,
navigation and the sidebar status block.

bootstrap() is the first call in each of the four page scripts. The order in it
is load-bearing. st.set_page_config has to come before any element, and the
first-run gate has to come before the navigation: the wizard ends the script
with st.stop(), and only then does the sidebar stay completely empty the way it
did when the wizard was a full-screen page inside a single-script app.
"""

import streamlit as st

from defect_risk_analyzer import config
from defect_risk_analyzer.ui import language
from defect_risk_analyzer.ui.service import call, get_service, get_status
from defect_risk_analyzer.ui.setup_wizard import render_setup_wizard
from defect_risk_analyzer.ui.theme import inject_css


def bootstrap() -> None:
    """Prepare the page. Call once, as the first statement of a page script."""
    st.set_page_config(
        page_title="Defect Risk Analyzer",
        page_icon="🔍",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()

    # The single bootstrap point for this process: creates data/ and reads
    # .env. Idempotent, so the Streamlit rerun loop does not re-read the file.
    config.init()

    # Before anything reads a message, and after config.init() has supplied the
    # persisted default. The wizard is on the far side of the gate below and
    # renders in this language too.
    language.apply()

    if config.is_first_run():
        render_setup_wizard()
        # Nothing below runs, so no navigation and no status is drawn behind
        # the wizard. Pinned by test_the_wizard_leaves_the_sidebar_empty.
        st.stop()

    render_nav()
    render_status()


def render_nav() -> None:
    """The four pages, in order.

    Written as four literal calls rather than a loop over a constant on
    purpose. AppTest has no accessor for st.page_link — it lands in the element
    tree as an UnknownElement — so nothing in a rendered-page assertion can
    prove these links exist. The only guard available is a source-level one,
    and that guard is both simpler and harder to fool against four literal
    calls with literal targets. See test_nav_declares_all_four_pages.
    """
    st.sidebar.title("🔍 Defect Risk Analyzer")

    st.sidebar.page_link("app.py", label="📊 Genel Bakış")
    st.sidebar.page_link("pages/buglar.py", label="🐛 Buglar")
    st.sidebar.page_link("pages/analiz.py", label="⚡ Analiz")
    st.sidebar.page_link("pages/ayarlar.py", label="⚙️ Ayarlar")

    # Under the links rather than above them: the four pages are what the
    # sidebar is for, and a settings-shaped control should not be the first
    # thing in it. Placed before the divider so the block count is unchanged.
    language.render_selector(st.sidebar)

    st.sidebar.markdown("---")


def render_status() -> None:
    """Loaded bugs, quota, connection state and the sync button."""
    # Local status — the analysis engine runs inside this process
    status = get_status()
    col1, col2 = st.sidebar.columns(2)
    col1.metric("Yüklü Bug", status["bugs_loaded"])
    col2.metric(
        "Günlük İstek",
        f"{status['daily_requests_used']}/{status['daily_requests_limit']}",
    )

    if status["mock_mode"]:
        st.sidebar.info("🎭 Mock Data Modu Aktif")

    if status["bugs_loaded"] == 0:
        st.sidebar.warning("⚠️ Bug verisi yok. Aşağıdan senkronize edin.")

    st.sidebar.markdown("---")

    # Connection status indicators
    if config.is_jira_configured():
        st.sidebar.success("✅ Jira: Bağlı")
    else:
        st.sidebar.warning("⚠️ Jira: Yapılandırılmamış")

    if config.is_llm_configured():
        st.sidebar.success(f"✅ LLM: {config.LLM_PROVIDER.capitalize()}")
    else:
        st.sidebar.warning("⚠️ LLM: API Key eksik")

    st.sidebar.markdown("---")

    # Refresh button — unconditional. It used to be gated behind a reachable
    # backend; with the service in-process there is nothing to be unreachable,
    # and a hidden button would leave the user unable to load any data.
    if st.sidebar.button("🔄 Jira'dan Senkronize Et", use_container_width=True):
        with st.spinner("Veriler senkronize ediliyor..."):
            result = call(get_service().refresh)
        if result:
            st.sidebar.success(f"✅ {result.get('bugs_fetched', 0)} bug yüklendi!")
            st.rerun()
