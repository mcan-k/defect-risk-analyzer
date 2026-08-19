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
from defect_risk_analyzer.ui.results import display_analysis_result
from defect_risk_analyzer.ui.service import call, get_service
from defect_risk_analyzer.ui.shell import bootstrap

bootstrap()


def render_single_analysis():
    """One bug or one free-text query, analysed on demand."""
    st.subheader("Tekli Bug / Alan Analizi")

    analysis_type = st.radio(
        "Analiz Türü", ["Bug Key ile", "Serbest Metin ile"], horizontal=True
    )

    if analysis_type == "Bug Key ile":
        bug_key = st.text_input("Bug Key", placeholder="Örn: AP-101")
        query = None
    else:
        query = st.text_input(
            "Analiz Sorgusu", placeholder="Örn: Authentication modülü güvenlik açıkları"
        )
        bug_key = None

    if st.button("🚀 Analiz Et", key="single_analyze"):
        if not bug_key and not query:
            st.warning("Lütfen bir Bug Key veya sorgu girin.")
        else:
            with st.spinner("Analiz yapılıyor... (LLM çağrısı 5-15 saniye sürebilir)"):
                result = call(
                    get_service().analyze,
                    bug_key=bug_key or None,
                    query=query or None,
                )

            if result:
                display_analysis_result(result)


def render_bulk_analysis():
    """A batch of bugs, with per-bug progress and the circuit breaker."""
    st.subheader("Toplu Bug Analizi")
    st.info(
        "⚠️ Toplu analiz LLM API kotanızı kullanır. "
        "Rate limit aşılırsa circuit breaker devreye girer."
    )

    bugs = get_service().get_bugs()
    if bugs:
        bug_keys = [b.get("key", "") for b in bugs if b.get("key")]
        selected_keys = st.multiselect("Analiz edilecek bugları seçin", bug_keys, default=[])

        if st.button("🚀 Toplu Analiz Başlat", key="bulk_analyze"):
            if not selected_keys:
                st.warning("En az bir bug seçin.")
            else:
                # The analysis now runs in this process, so the page blocks
                # for the whole batch. Report progress per bug instead of
                # leaving the user in front of a frozen spinner.
                progress = st.progress(0.0, text="Analiz başlıyor...")

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
                    col1.metric("Toplam", result.get("total", 0))
                    col2.metric("✅ Analiz Edilen", result.get("analyzed", 0))
                    col3.metric("⏭️ Atlanan", result.get("skipped", 0))

                    if result.get("circuit_breaker_triggered"):
                        st.error(
                            "🔴 Circuit Breaker Tetiklendi! "
                            "Rate limit aşıldığı için kalan buglar atlandı."
                        )

                    skipped = result.get("skipped_keys", [])
                    if skipped:
                        st.warning(f"Atlanan buglar: {', '.join(skipped)}")

                    for r in result.get("results", []):
                        with st.expander(
                            f"{r.get('bug_key', '?')} — "
                            f"Risk: {r.get('risk_score', 0)} ({r.get('risk_level', '?')})"
                        ):
                            display_analysis_result(r)
    else:
        st.info(
            "Analiz edilecek bug verisi yok. "
            "Sol menüden 'Jira'dan Senkronize Et' butonuna tıklayın."
        )


def render_webhook_results():
    """Display webhook analysis history."""
    results = get_service().get_webhook_results()
    if not results:
        st.info("Henüz webhook analiz sonucu yok.")

        st.markdown("---")
        st.subheader("Webhook Nasıl Kurulur?")
        jql_project = config.JIRA_PROJECT_KEY or "YOUR_PROJECT"
        st.markdown(f"""
        1. Jira'da **Settings → System → Webhooks** bölümüne gidin
        2. Yeni webhook oluşturun:
           - **URL:** `http://YOUR_SERVER:{config.API_PORT}/webhook/jira`
           - **Events:** Issue created, Issue updated
           - **JQL Filter:** `project = {jql_project} AND issuetype = Bug`
        3. Header ekleyin: `X-API-Key: {config.API_KEY[:8]}...`
        """)
        return

    st.markdown(f"**{len(results)}** webhook analiz sonucu")

    for r in reversed(results):
        level = r.get("risk_level", "LOW")
        emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(level, "⚪")
        with st.expander(
            f"{emoji} {r.get('bug_key', '?')} — {r.get('query', '?')[:60]} — "
            f"Risk: {r.get('risk_score', 0)}"
        ):
            display_analysis_result(r)


st.title("⚡ Analiz")

llm_ready = config.is_llm_configured()
if not llm_ready:
    st.warning("⚠️ LLM API Key yapılandırılmamış. Ayarlar sayfasından API key girin.")
    if st.button("⚙️ Ayarlar Sayfasına Git"):
        st.switch_page("pages/ayarlar.py")

tab_single, tab_bulk, tab_webhook = st.tabs(
    ["🔍 Tekli Analiz", "📦 Toplu Analiz", "🔔 Webhook Sonuçları"]
)

with tab_single:
    if llm_ready:
        render_single_analysis()

with tab_bulk:
    if llm_ready:
        render_bulk_analysis()

with tab_webhook:
    render_webhook_results()
