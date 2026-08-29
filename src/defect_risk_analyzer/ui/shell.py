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
from defect_risk_analyzer.ui.i18n import t
from defect_risk_analyzer.ui.messages import format_secret_layer
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

    # After language.apply() so the notice is translated, and BEFORE the
    # first-run gate so a fresh install still sees it — the gate ends the
    # script with st.stop(), and anything below it would never render for that
    # user. See _report_removed_legacy_files.
    _report_removed_legacy_files()
    _migrate_secrets()

    if config.is_first_run():
        render_setup_wizard()
        # Nothing below runs, so no navigation and no status is drawn behind
        # the wizard. Pinned by test_the_wizard_leaves_the_sidebar_empty.
        st.stop()

    render_nav()
    render_status()


# st.session_state key. Named once so the read and the write cannot drift.
_LEGACY_NOTICE_SHOWN = "_dra_legacy_anon_map_notice_shown"


def _report_removed_legacy_files() -> None:
    """Tell the user that `data/anon_map.json` was deleted at startup.

    A LOG LINE IS NOT ENOUGH, which is why this exists at all. The deletion is
    silent removal of a file the user never asked us to touch, and nobody reads
    `data/dashboard.log`. `config._purge_legacy_anon_map()` already writes a
    warning there for the headless paths — the API server and the CI analyzer,
    which have no screen — and this is the half that reaches a person.

    ONCE PER BROWSER SESSION, not once per rerun. Streamlit re-executes the
    whole script on every interaction, so an ungated `st.warning` would reappear
    on every click for as long as the process lived. `config` cannot carry that
    state: its flag is per PROCESS, and one process serves every browser
    session.

    Says nothing about what the file held. Not a count, not a category — the
    contents are the reason it was deleted.
    """
    if not config.LEGACY_ANON_MAP_REMOVED:
        return
    if st.session_state.get(_LEGACY_NOTICE_SHOWN):
        return

    st.session_state[_LEGACY_NOTICE_SHOWN] = True
    st.warning(t("shell.legacy_anon_map_removed"))


_MIGRATION_NOTICE_SHOWN = "_dra_secret_migration_notice_shown"


def _migrate_secrets() -> None:
    """Move credentials out of `.env` into the OS credential store, and report.

    HERE RATHER THAN IN config.init(). Every entry point reaches `init()`, which
    is why the anon_map purge lives there — but this is a different kind of act.
    The purge deletes a machine-generated leftover; this moves the user's
    working configuration, and it can only do so where keyring resolves, which
    is the desktop. Docker and CI take credentials as environment variables and
    have no credential store at all, so the migration would be a no-op there
    with nobody to read its report. `bootstrap()` is the desktop path and the
    one place with a screen.

    A SECOND DESTRUCTIVE JOB DOES NOT GO IN init(). It already deletes a file;
    adding "and moves your credentials" to a function whose name is `init` is
    how a startup path becomes something nobody dares change.

    Runs on every start and is idempotent — a `.env` with nothing left to move
    costs one empty-string check per key and never reaches the store.
    """
    report = config.migrate_secrets_to_store()

    if not (report["moved"] or report["in_both"] or report["not_moved"]):
        return
    if st.session_state.get(_MIGRATION_NOTICE_SHOWN):
        return

    st.session_state[_MIGRATION_NOTICE_SHOWN] = True

    if report["moved"]:
        st.success(
            t("shell.secrets_migrated",
              keys=", ".join(report["moved"]),
              layer=format_secret_layer(report["code"], report["params"]))
        )
    if report["in_both"]:
        # Recoverable, but the plain-text copy is still on disk. Saying nothing
        # would be a lie by omission.
        st.warning(t("shell.secrets_in_both", keys=", ".join(report["in_both"])))
    if report["not_moved"]:
        st.warning(t("shell.secrets_not_moved", keys=", ".join(report["not_moved"])))


def render_nav() -> None:
    """The four pages, in order.

    Written as four literal calls rather than a loop over a constant on
    purpose. AppTest has no accessor for st.page_link — it lands in the element
    tree as an UnknownElement — so nothing in a rendered-page assertion can
    prove these links exist. The only guard available is a source-level one,
    and that guard is both simpler and harder to fool against four literal
    calls with literal targets. See test_nav_declares_all_four_pages.
    """
    st.sidebar.title(t("sidebar.title"))

    st.sidebar.page_link("app.py", label=t("nav.overview"))
    st.sidebar.page_link("pages/buglar.py", label=t("nav.bugs"))
    st.sidebar.page_link("pages/analiz.py", label=t("nav.analysis"))
    st.sidebar.page_link("pages/ayarlar.py", label=t("nav.settings"))

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
    col1.metric(t("sidebar.metric.bugs_loaded"), status["bugs_loaded"])
    col2.metric(
        t("sidebar.metric.daily_requests"),
        f"{status['daily_requests_used']}/{status['daily_requests_limit']}",
    )

    if status["mock_mode"]:
        st.sidebar.info(t("sidebar.mock_mode"))

    if status["bugs_loaded"] == 0:
        st.sidebar.warning(t("sidebar.no_bugs"))

    st.sidebar.markdown("---")

    # Connection status indicators
    if config.is_jira_configured():
        st.sidebar.success(t("sidebar.jira.connected"))
    else:
        st.sidebar.warning(t("sidebar.jira.unconfigured"))

    if config.is_llm_configured():
        st.sidebar.success(t("sidebar.llm.connected", provider=config.LLM_PROVIDER.capitalize()))
    else:
        st.sidebar.warning(t("sidebar.llm.missing_key"))

    st.sidebar.markdown("---")

    # Refresh button — unconditional. It used to be gated behind a reachable
    # backend; with the service in-process there is nothing to be unreachable,
    # and a hidden button would leave the user unable to load any data.
    if st.sidebar.button(t("sidebar.sync"), use_container_width=True):
        with st.spinner(t("sidebar.sync.running")):
            result = call(get_service().refresh)
        if result:
            st.sidebar.success(t("sidebar.sync.done", count=result.get("bugs_fetched", 0)))
            st.rerun()
