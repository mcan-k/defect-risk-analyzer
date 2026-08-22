"""
Analiz — everything that produces an analysis result.

The two tabs of the old Canlı Analiz page are top-level tabs here, and the
webhook history joins them: it renders the same payload through the same
display_analysis_result, it is just produced by Jira rather than by a click.

The LLM guard is deliberately NOT a page-level return. On the old page it cut
the whole page short, which here would take the webhook history down with it —
and that history is readable with no LLM configured at all. So the warning
renders once above the tabs, the two analysis tabs are gated on it, and the
webhook tab always renders.
"""

import streamlit as st

from defect_risk_analyzer import config
from defect_risk_analyzer.ui.i18n import t
from defect_risk_analyzer.ui.results import display_analysis_result
from defect_risk_analyzer.ui.service import call, get_service
from defect_risk_analyzer.ui.shell import bootstrap

bootstrap()

# Risk level → emoji. Keyed in English, like RISK_COLORS, so the badge survives
# translation; the level text next to it is the detector's own value.
RISK_EMOJI = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}


def render_single_analysis():
    """One bug or one free-text query, analysed on demand."""
    st.subheader(t("analysis.single.title"))

    by_bug_key = t("analysis.type.bug_key")
    analysis_type = st.radio(
        t("analysis.type"), [by_bug_key, t("analysis.type.free_text")], horizontal=True
    )

    # Compared against the rendered label rather than a Turkish literal: the
    # branch has to follow the widget in whatever language drew it.
    if analysis_type == by_bug_key:
        bug_key = st.text_input(t("common.bug_key"),
                                placeholder=t("analysis.bug_key.placeholder"))
        query = None
    else:
        query = st.text_input(t("analysis.query"),
                              placeholder=t("analysis.query.placeholder"))
        bug_key = None

    if st.button(t("analysis.run"), key="single_analyze"):
        if not bug_key and not query:
            st.warning(t("analysis.error.empty"))
        else:
            with st.spinner(t("analysis.running")):
                result = call(
                    get_service().analyze,
                    bug_key=bug_key or None,
                    query=query or None,
                )

            if result:
                display_analysis_result(result)


def render_bulk_analysis():
    """A batch of bugs, with per-bug progress and the circuit breaker."""
    st.subheader(t("analysis.bulk.title"))
    st.info(t("analysis.bulk.warning"))

    bugs = get_service().get_bugs()
    if bugs:
        bug_keys = [b.get("key", "") for b in bugs if b.get("key")]
        selected_keys = st.multiselect(t("analysis.bulk.select"), bug_keys, default=[])

        if st.button(t("analysis.bulk.run"), key="bulk_analyze"):
            if not selected_keys:
                st.warning(t("analysis.bulk.error.empty"))
            else:
                # The analysis now runs in this process, so the page blocks
                # for the whole batch. Report progress per bug instead of
                # leaving the user in front of a frozen spinner.
                progress = st.progress(0.0, text=t("analysis.bulk.starting"))

                def report(index: int, total: int, bug_key: str) -> None:
                    progress.progress(
                        index / total,
                        text=f"{index}/{total} — {bug_key}",
                    )

                result = call(
                    get_service().analyze_bulk,
                    selected_keys,
                    on_progress=report,
                )
                progress.empty()

                if result:
                    st.markdown("---")

                    col1, col2, col3 = st.columns(3)
                    col1.metric(t("analysis.bulk.metric.total"), result.get("total", 0))
                    col2.metric(t("analysis.bulk.metric.analyzed"), result.get("analyzed", 0))
                    col3.metric(t("analysis.bulk.metric.skipped"), result.get("skipped", 0))

                    if result.get("circuit_breaker_triggered"):
                        st.error(t("analysis.bulk.circuit_breaker"))

                    skipped = result.get("skipped_keys", [])
                    if skipped:
                        st.warning(t("analysis.bulk.skipped_keys",
                                     bug_keys=", ".join(skipped)))

                    for r in result.get("results", []):
                        with st.expander(
                            t(
                                "analysis.bulk.item",
                                bug_key=r.get("bug_key", "?"),
                                risk_score=r.get("risk_score", 0),
                                risk_level=r.get("risk_level", "?"),
                            )
                        ):
                            display_analysis_result(r)
    else:
        st.info(t("analysis.no_bugs"))


def render_webhook_results():
    """Display webhook analysis history."""
    results = get_service().get_webhook_results()
    if not results:
        st.info(t("webhook.no_results"))

        st.markdown("---")
        st.subheader(t("webhook.howto.title"))
        st.markdown(
            t(
                "webhook.howto.body",
                port=config.API_PORT,
                project=config.JIRA_PROJECT_KEY or "YOUR_PROJECT",
                api_key=config.API_KEY[:8],
            )
        )
        return

    st.markdown(t("webhook.count", count=len(results)))

    for r in reversed(results):
        level = r.get("risk_level", "LOW")
        with st.expander(
            t(
                "webhook.item",
                emoji=RISK_EMOJI.get(level, "⚪"),
                bug_key=r.get("bug_key", "?"),
                query=r.get("query", "?")[:60],
                risk_score=r.get("risk_score", 0),
            )
        ):
            display_analysis_result(r)


st.title(t("nav.analysis"))

llm_ready = config.is_llm_configured()
if not llm_ready:
    st.warning(t("analysis.no_llm"))
    if st.button(t("analysis.goto_settings")):
        st.switch_page("pages/ayarlar.py")

tab_single, tab_bulk, tab_webhook = st.tabs(
    [t("analysis.tab.single"), t("analysis.tab.bulk"), t("analysis.tab.webhook")]
)

with tab_single:
    if llm_ready:
        render_single_analysis()

with tab_bulk:
    if llm_ready:
        render_bulk_analysis()

with tab_webhook:
    render_webhook_results()
