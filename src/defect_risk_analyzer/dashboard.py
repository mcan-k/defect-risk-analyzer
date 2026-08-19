"""
Streamlit Dashboard — 7-page UI for the Predictive Defect Analysis Engine.

Pages:
  1. Dashboard       — Risk heatmap, priority distribution, module ranking, trends
  2. Bug Listesi     — All bugs with filters and search
  3. Canlı Analiz    — Single + bulk analysis with progress bar + circuit breaker
  4. Pattern Tespiti  — Similar bug clustering and root cause hints
  5. Kör Nokta Tespiti — Untested risky areas, neglected bugs
  6. Webhook          — Webhook analysis history
  7. Ayarlar          — Self-service configuration panel

First-run experience: If no configuration exists, the app opens directly
to a setup wizard that guides the user through entering credentials.

All UI text is in Turkish.
"""

import os
import time

import pandas as pd
import plotly.express as px
import streamlit as st

from defect_risk_analyzer import config
from defect_risk_analyzer.ui.messages import format_finding
from defect_risk_analyzer.ui.results import display_analysis_result
from defect_risk_analyzer.ui.service import (
    call,
    get_service,
    get_status,
    save_multiple_env,
)
from defect_risk_analyzer.ui.setup_wizard import render_setup_wizard
from defect_risk_analyzer.ui.theme import (
    CHART_COLORS,
    RISK_COLORS,
    apply_chart_theme,
    inject_css,
)

# ---------------------------------------------------------------------------
# Page Config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Defect Risk Analyzer",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> str:
    """Render sidebar with navigation and status."""
    st.sidebar.title("🔍 Defect Risk Analyzer")

    page = st.sidebar.radio(
        "Sayfa Seçin",
        [
            "📊 Dashboard",
            "🐛 Bug Listesi",
            "⚡ Canlı Analiz",
            "🔗 Pattern Tespiti",
            "🎯 Kör Nokta Tespiti",
            "🔔 Webhook Sonuçları",
            "⚙️ Ayarlar",
        ],
        index=0,
    )

    st.sidebar.markdown("---")

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

    return page


# =============================================================================
# Page 1: Dashboard
# =============================================================================

def page_dashboard():
    """Risk overview dashboard with charts and alerts."""
    st.title("📊 Risk Dashboard")

    risks = call(get_service().get_risk_summary)
    if not risks:
        st.info("Henüz analiz verisi yok. Sol menüden 'Jira'dan Senkronize Et' butonuna tıklayın.")
        return

    module_risks = risks.get("module_risks", {})
    if not module_risks:
        st.info(
            "Modül risk verisi bulunamadı. "
            "Sol menüden 'Jira'dan Senkronize Et' butonuna tıklayın."
        )
        return

    # Top metrics
    total_bugs = risks.get("total_bugs", 0)
    analyzed = risks.get("analyzed_count", 0)
    critical_count = sum(1 for m in module_risks.values() if m.get("level") == "CRITICAL")
    high_count = sum(1 for m in module_risks.values() if m.get("level") == "HIGH")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Toplam Bug", total_bugs)
    col2.metric("Analiz Edilen", analyzed)
    col3.metric("🔴 Kritik Modül", critical_count)
    col4.metric("🟠 Yüksek Risk Modül", high_count)

    # Critical alerts
    critical_modules = [
        name for name, data in module_risks.items() if data.get("level") == "CRITICAL"
    ]
    if critical_modules:
        st.error(
            f"⚠️ KRİTİK RİSK: {', '.join(critical_modules)} "
            "modüllerinde acil müdahale gerekiyor!"
        )

    st.markdown("---")

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Modül Risk Haritası")
        df_risk = pd.DataFrame([
            {
                "Modül": name,
                "Risk Skoru": data.get("score", 0),
                "Risk Seviyesi": data.get("level", "LOW"),
                "Bug Sayısı": data.get("bug_count", 0),
            }
            for name, data in module_risks.items()
        ]).sort_values("Risk Skoru", ascending=True)

        fig = px.bar(
            df_risk,
            x="Risk Skoru",
            y="Modül",
            orientation="h",
            color="Risk Seviyesi",
            color_discrete_map=RISK_COLORS,
            text="Risk Skoru",
        )
        fig.update_traces(textposition="outside")
        apply_chart_theme(fig, height=400)
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.subheader("Bug Dağılımı (Modül Bazında)")
        df_bugs = pd.DataFrame([
            {"Modül": name, "Bug Sayısı": data.get("bug_count", 0)}
            for name, data in module_risks.items()
        ])
        fig2 = px.pie(df_bugs, values="Bug Sayısı", names="Modül", hole=0.4,
                      color_discrete_sequence=CHART_COLORS)
        apply_chart_theme(fig2, height=400)
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")
    st.subheader("Modül Risk Sıralaması")

    table_data = []
    for name, data in sorted(
        module_risks.items(), key=lambda x: x[1].get("score", 0), reverse=True
    ):
        table_data.append({
            "Modül": name,
            "Risk Skoru": data.get("score", 0),
            "Seviye": data.get("level", "LOW"),
            "Toplam Bug": data.get("bug_count", 0),
            "Açık Bug": data.get("open_count", 0),
        })

    st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)

    # --- Trend Charts ---
    bugs = get_service().get_bugs()
    if bugs:
        st.markdown("---")
        st.subheader("📈 Bug Trend Analizi")

        # Parse dates and build timeline data
        trend_data = []
        for bug in bugs:
            created = bug.get("created", "")
            component = bug.get("component", "Genel")
            if created:
                try:
                    date = pd.to_datetime(created).date()
                    trend_data.append({
                        "Tarih": date,
                        "Modül": component,
                        "Durum": bug.get("status", "Open"),
                    })
                except Exception:
                    pass

        if trend_data:
            df_trend = pd.DataFrame(trend_data)

            col_left, col_right = st.columns(2)

            with col_left:
                st.markdown("**Haftalık Bug Oluşturma Trendi**")
                df_weekly = df_trend.copy()
                df_weekly["Hafta"] = pd.to_datetime(df_weekly["Tarih"]).apply(
                    lambda d: d - pd.Timedelta(days=d.weekday())
                )
                weekly_counts = (
                    df_weekly.groupby(["Hafta", "Modül"]).size().reset_index(name="Bug Sayısı")
                )

                fig_trend = px.line(
                    weekly_counts,
                    x="Hafta",
                    y="Bug Sayısı",
                    color="Modül",
                    markers=True,
                    color_discrete_sequence=CHART_COLORS,
                )
                apply_chart_theme(fig_trend, height=350)
                st.plotly_chart(fig_trend, use_container_width=True)

            with col_right:
                st.markdown("**Açık vs Kapalı Bug Dağılımı**")
                open_statuses = {"to do", "open", "in progress", "in review", "reopened"}
                df_status = df_trend.copy()
                df_status["Kategori"] = df_status["Durum"].apply(
                    lambda s: "Açık" if s.lower() in open_statuses else "Kapalı"
                )
                status_by_module = (
                    df_status.groupby(["Modül", "Kategori"]).size().reset_index(name="Sayı")
                )

                fig_status = px.bar(
                    status_by_module,
                    x="Modül",
                    y="Sayı",
                    color="Kategori",
                    barmode="stack",
                    color_discrete_map={"Açık": "#F97316", "Kapalı": "#22C55E"},
                )
                fig_status.update_layout(xaxis_title="", yaxis_title="Bug Sayısı")
                apply_chart_theme(fig_status, height=350)
                st.plotly_chart(fig_status, use_container_width=True)

            # Cumulative trend
            st.markdown("**Kümülatif Bug Trendi (Toplam)**")
            df_cumulative = df_trend.sort_values("Tarih")
            df_cumulative["Sıra"] = range(1, len(df_cumulative) + 1)
            df_cumulative["Tarih"] = pd.to_datetime(df_cumulative["Tarih"])

            fig_cum = px.area(
                df_cumulative,
                x="Tarih",
                y="Sıra",
                labels={"Sıra": "Toplam Bug Sayısı"},
            )
            fig_cum.update_traces(fill="tozeroy", line_color="#8B5CF6")
            apply_chart_theme(fig_cum, height=300)
            st.plotly_chart(fig_cum, use_container_width=True)


# =============================================================================
# Page 2: Bug List
# =============================================================================

def page_bug_list():
    """Bug list with filters and search."""
    st.title("🐛 Bug Listesi")

    bugs = get_service().get_bugs()
    if not bugs:
        st.info(
            "Henüz bug verisi yüklenmemiş. "
            "Sol menüden 'Jira'dan Senkronize Et' butonuna tıklayın."
        )
        return

    col1, col2, col3 = st.columns(3)

    priorities = sorted(set(b.get("priority", "Medium") for b in bugs))
    statuses = sorted(set(b.get("status", "Open") for b in bugs))
    components = sorted(set(b.get("component", "Unknown") for b in bugs))

    with col1:
        selected_priority = st.multiselect("Öncelik Filtresi", priorities, default=priorities)
    with col2:
        selected_status = st.multiselect("Durum Filtresi", statuses, default=statuses)
    with col3:
        selected_component = st.multiselect("Modül Filtresi", components, default=components)

    search = st.text_input("🔍 Ara (bug key veya özet)", "")

    filtered = [
        b for b in bugs
        if b.get("priority") in selected_priority
        and b.get("status") in selected_status
        and b.get("component") in selected_component
        and (
            not search
            or search.lower() in b.get("key", "").lower()
            or search.lower() in b.get("summary", "").lower()
        )
    ]

    st.markdown(f"**{len(filtered)}** / {len(bugs)} bug gösteriliyor")

    if filtered:
        df = pd.DataFrame([
            {
                "Key": b.get("key", ""),
                "Özet": b.get("summary", ""),
                "Öncelik": b.get("priority", ""),
                "Durum": b.get("status", ""),
                "Modül": b.get("component", ""),
                "Oluşturulma": b.get("created", "")[:10],
            }
            for b in filtered
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.warning("Filtrelere uyan bug bulunamadı.")


# =============================================================================
# Page 3: Live Analysis
# =============================================================================

def page_live_analysis():
    """Single and bulk analysis with progress and circuit breaker display."""
    st.title("⚡ Canlı Analiz")

    # Check LLM is configured
    if not config.is_llm_configured():
        st.warning("⚠️ LLM API Key yapılandırılmamış. Ayarlar sayfasından API key girin.")
        if st.button("⚙️ Ayarlar Sayfasına Git"):
            st.session_state["force_page"] = "settings"
            st.rerun()
        return

    tab1, tab2 = st.tabs(["🔍 Tekli Analiz", "📦 Toplu Analiz"])

    with tab1:
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

    with tab2:
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


# =============================================================================
# Page 4: Pattern Detection
# =============================================================================

def page_patterns():
    """Display detected bug patterns and clusters."""
    st.title("🔗 Pattern Tespiti")
    st.caption("Benzer bug'ları otomatik gruplar ve olası ortak nedenleri tespit eder.")

    patterns = call(get_service().detect_patterns, include_bugs=False)

    if patterns is None:
        return

    if not patterns:
        st.info(
            "Pattern tespit edilemedi. "
            "Yeterli bug verisi yüklendikten sonra bu sayfa otomatik dolar."
        )
        return

    # Summary metrics
    total_patterns = len(patterns)
    total_bugs_in_patterns = sum(p.get("bug_count", 0) for p in patterns)
    critical_patterns = sum(1 for p in patterns if p.get("severity") == "critical")

    col1, col2, col3 = st.columns(3)
    col1.metric("Tespit Edilen Pattern", total_patterns)
    col2.metric("Etkilenen Bug", total_bugs_in_patterns)
    col3.metric("Kritik Pattern", critical_patterns)

    st.markdown("---")

    # Pattern severity colors
    severity_colors = {
        "critical": "#DC2626",
        "high": "#F97316",
        "medium": "#EAB308",
        "low": "#22C55E",
    }
    severity_labels = {
        "critical": "KRİTİK",
        "high": "YÜKSEK",
        "medium": "ORTA",
        "low": "DÜŞÜK",
    }

    # Fetched once: this used to be re-read inside the loop below, one call
    # per pattern.
    all_bugs = get_service().get_bugs()

    # Display each pattern
    for pattern in patterns:
        severity = pattern.get("severity", "low")
        color = severity_colors.get(severity, "#666")
        label = severity_labels.get(severity, "?")
        bug_count = pattern.get("bug_count", 0)
        keywords = pattern.get("common_keywords", [])
        component = pattern.get("common_component", "Genel")
        bug_keys = pattern.get("bug_keys", [])

        # Pattern header
        header = (
            f"Pattern #{pattern.get('pattern_id', '?')} — "
            f"{bug_count} bug — {component}"
        )

        severity_emoji = (
            "🔴" if severity == "critical"
            else "🟠" if severity == "high"
            else "🟡" if severity == "medium"
            else "🟢"
        )
        with st.expander(f"{severity_emoji} {header}"):

            # Severity badge
            st.markdown(
                f"**Önem:** <span style='background-color:{color}; color:white; "
                f"padding:2px 10px; border-radius:4px;'>{label}</span> &nbsp; "
                f"**Modül:** {component} &nbsp; "
                f"**Yaygın Öncelik:** {pattern.get('common_priority', '?')}",
                unsafe_allow_html=True,
            )

            # Common keywords as tags
            if keywords:
                st.markdown("**Ortak Anahtar Kelimeler:**")
                keyword_tags = " ".join(
                    f"<span style='background-color:rgba(100,100,255,0.15); "
                    f"padding:2px 8px; border-radius:12px; margin:2px; "
                    f"display:inline-block; font-size:0.85em;'>{kw}</span>"
                    for kw in keywords
                )
                st.markdown(keyword_tags, unsafe_allow_html=True)

            # Bug list
            st.markdown(f"**Bu pattern'daki bug'lar:** {', '.join(bug_keys)}")

            # Load full bug details
            if all_bugs:
                pattern_bugs = [b for b in all_bugs if b.get("key") in bug_keys]
                if pattern_bugs:
                    df = pd.DataFrame([
                        {
                            "Key": b.get("key", ""),
                            "Özet": b.get("summary", "")[:80],
                            "Öncelik": b.get("priority", ""),
                            "Durum": b.get("status", ""),
                        }
                        for b in pattern_bugs
                    ])
                    st.dataframe(df, use_container_width=True, hide_index=True)

            # Root cause suggestion
            if keywords:
                st.markdown(
                    f"💡 **Olası Ortak Neden:** Bu bug'lar `{keywords[0]}` "
                    f"{'ve `' + keywords[1] + '`' if len(keywords) > 1 else ''} "
                    f"konusunda ortak bir sorun paylaşıyor olabilir. "
                    f"Tek bir root cause düzeltmesi birden fazla bug'ı çözebilir."
                )

    # Duplicate check section
    st.markdown("---")
    st.subheader("🔍 Duplicate Bug Kontrolü")
    st.caption("Bir bug key girin, benzer bug'lar varsa gösterelim.")

    bug_key_input = st.text_input("Bug Key", placeholder="Örn: AP-12")
    if st.button("Benzer Bug'ları Bul"):
        if bug_key_input:
            bug = get_service().get_bug(bug_key_input)
            if bug is None:
                st.error(f"⚠️ '{bug_key_input}' yüklü veride bulunamadı.")
                dupes = None
            else:
                dupes = call(get_service().find_duplicate_bugs, bug)

            if dupes is not None:
                if dupes:
                    st.warning(f"⚠️ {len(dupes)} benzer bug bulundu!")
                    for d in dupes:
                        st.markdown(
                            f"- **{d.get('key', '?')}** — {d.get('summary', '?')} "
                            f"(Benzerlik: %{d.get('similarity', 0)})"
                        )
                else:
                    st.success("✅ Benzer bug bulunamadı — bu bug benzersiz görünüyor.")
        else:
            st.warning("Lütfen bir Bug Key girin.")


# =============================================================================
# Page 5: Blind Spot Detection
# =============================================================================

def page_blind_spots():
    """Display blind spots — untested risky areas and neglected bugs."""
    st.title("🎯 Kör Nokta Tespiti")
    st.caption(
        "Test edilmemiş riskli alanları, sahipsiz kritik bug'ları ve "
        "uzun süredir açık sorunları tespit eder."
    )

    data = call(get_service().detect_blind_spots)

    if data is None:
        return

    summary = data.get("summary", {})
    total = summary.get("total_blind_spots", 0)
    critical = summary.get("critical_spots", 0)
    categories = summary.get("categories", {})

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Toplam Kör Nokta", total)
    col2.metric("🔴 Kritik", critical)
    col3.metric("Sahipsiz Bug", categories.get("neglected_critical_bugs", 0))
    col4.metric("Bayat Bug", categories.get("stale_bugs", 0))

    if total == 0:
        st.success("✅ Kör nokta tespit edilmedi! QA kapsamınız iyi durumda.")
        return

    st.markdown("---")

    # --- 1. Unanalyzed Risky Modules ---
    unanalyzed = data.get("unanalyzed_risky_modules", [])
    if unanalyzed:
        st.subheader("⚠️ Analiz Edilmemiş Riskli Modüller")
        st.caption("Bu modüller yüksek risk taşıyor ancak henüz detaylı analiz yapılmamış.")

        for item in unanalyzed:
            risk_level = item.get("risk_level", "MEDIUM")
            color = RISK_COLORS.get(risk_level, "#666")

            st.markdown(
                f"**{item.get('module', '?')}** — "
                f"<span style='background-color:{color}; color:white; padding:2px 8px; "
                f"border-radius:4px;'>{risk_level}</span> "
                f"(Skor: {item.get('risk_score', 0)}, "
                f"{item.get('open_bugs', 0)} açık bug)",
                unsafe_allow_html=True,
            )
            st.caption(f"💡 {format_finding(item)}")

        st.markdown("---")

    # --- 2. Neglected Critical Bugs ---
    neglected = data.get("neglected_critical_bugs", [])
    if neglected:
        st.subheader("🚨 Sahipsiz Kritik Bug'lar")
        st.caption("Yüksek öncelikli bug'lar henüz üzerinde çalışılmıyor.")

        df_neglected = pd.DataFrame([
            {
                "Key": item.get("key", ""),
                "Özet": item.get("summary", "")[:70],
                "Öncelik": item.get("priority", ""),
                "Durum": item.get("status", ""),
                "Modül": item.get("component", ""),
                "Açık (gün)": item.get("days_open", 0),
            }
            for item in neglected
        ])
        st.dataframe(df_neglected, use_container_width=True, hide_index=True)

        for item in neglected[:3]:
            st.caption(f"💡 {format_finding(item)}")

        st.markdown("---")

    # --- 3. Stale Bugs ---
    stale = data.get("stale_bugs", [])
    if stale:
        st.subheader("🕐 Bayat Bug'lar (14+ gündür açık)")
        st.caption("Uzun süredir açık olan bug'lar — çözüm süresi beklentinin üzerinde.")

        df_stale = pd.DataFrame([
            {
                "Key": item.get("key", ""),
                "Özet": item.get("summary", "")[:70],
                "Öncelik": item.get("priority", ""),
                "Durum": item.get("status", ""),
                "Modül": item.get("component", ""),
                "Açık (gün)": item.get("days_open", 0),
            }
            for item in stale
        ])
        st.dataframe(df_stale, use_container_width=True, hide_index=True)

        st.markdown("---")

    # --- 4. Rising Unattended ---
    rising = data.get("rising_unattended", [])
    if rising:
        st.subheader("📈 Yükselen Risk — Müdahale Yok")
        st.caption("Bug sayısı artıyor ancak üzerinde çalışılan bug yok.")

        for item in rising:
            st.markdown(
                f"**{item.get('module', '?')}** — "
                f"{item.get('total_bugs', 0)} toplam bug, "
                f"{item.get('recent_bugs', 0)} yeni, "
                f"{item.get('in_progress', 0)} üzerinde çalışılıyor"
            )
            st.caption(f"💡 {format_finding(item)}")

    # Action summary
    st.markdown("---")
    st.subheader("📋 Önerilen Aksiyonlar")

    actions = []
    if unanalyzed:
        actions.append(
            f"⚡ {len(unanalyzed)} riskli modülü **Canlı Analiz** sayfasından analiz edin"
        )
    if neglected:
        actions.append(f"🚨 {len(neglected)} kritik bug'a kaynak atayın veya öncelik güncelleyin")
    if stale:
        actions.append(
            f"🕐 {len(stale)} bayat bug'ı gözden geçirin — "
            "kapatılabilir veya önceliklendirilebilir"
        )
    if rising:
        actions.append(f"📈 {len(rising)} modüle ek test kaynağı ayrılması önerilir")

    if actions:
        for action in actions:
            st.markdown(f"- {action}")
    else:
        st.success("Tüm alanlar kontrol altında!")


# =============================================================================
# Page 6: Webhook Results
# =============================================================================

def page_webhook_results():
    """Display webhook analysis history."""
    st.title("🔔 Webhook Sonuçları")

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


# =============================================================================
# Page 5: Settings
# =============================================================================

def page_settings():
    """Self-service configuration panel with live reload."""
    st.title("⚙️ Ayarlar")
    st.caption("Değişiklikler kaydedildiğinde anında uygulanır — yeniden başlatma gerekmez.")

    # --- Jira Connection ---
    st.subheader("🔗 Jira Bağlantısı")

    jira_url = st.text_input("Jira URL", value=config.JIRA_URL, placeholder="https://yourcompany.atlassian.net")
    jira_email = st.text_input(
        "Jira E-posta", value=config.JIRA_EMAIL, placeholder="you@company.com"
    )
    jira_token = st.text_input("Jira API Token", value=config.JIRA_API_TOKEN, type="password",
                               help="[Token oluştur →](https://id.atlassian.com/manage-profile/security/api-tokens)")
    jira_project = st.text_input("Proje Key", value=config.JIRA_PROJECT_KEY, placeholder="AP",
                                 help="Bug key'lerinin başındaki harfler (örn: AP-101 → AP)")

    col1, col2 = st.columns(2)
    if col1.button("💾 Jira Ayarlarını Kaydet", use_container_width=True):
        save_multiple_env({
            "JIRA_URL": jira_url.rstrip("/"),
            "JIRA_EMAIL": jira_email,
            "JIRA_API_TOKEN": jira_token,
            "JIRA_PROJECT_KEY": jira_project,
        })
        st.success("✅ Jira ayarları kaydedildi ve uygulandı!")
        time.sleep(1)
        st.rerun()

    if col2.button("🧪 Jira Bağlantısını Test Et", use_container_width=True):
        if all([jira_url, jira_email, jira_token]):
            with st.spinner("Jira bağlantısı test ediliyor..."):
                try:
                    from defect_risk_analyzer.jira_client import JiraClient
                    client = JiraClient(jira_url.rstrip("/"), jira_email, jira_token, jira_project)
                    if client.test_connection():
                        st.success("✅ Jira bağlantısı başarılı!")
                    else:
                        st.error("❌ Jira bağlantısı başarısız. Bilgileri kontrol edin.")
                except Exception as e:
                    st.error(f"❌ Hata: {e}")
        else:
            st.warning("Lütfen tüm Jira bilgilerini doldurun.")

    st.markdown("---")

    # --- LLM Provider ---
    st.subheader("🤖 LLM Sağlayıcı")

    provider = st.selectbox(
        "Sağlayıcı",
        ["groq", "openai"],
        index=0 if config.LLM_PROVIDER == "groq" else 1,
    )

    if provider == "groq":
        llm_key = st.text_input(
            "Groq API Key",
            value=config.GROQ_API_KEY,
            type="password",
            help="[Groq Console →](https://console.groq.com/keys) adresinden ücretsiz key alın",
        )
    else:
        llm_key = st.text_input(
            "OpenAI API Key",
            value=config.OPENAI_API_KEY,
            type="password",
            help="[OpenAI Platform →](https://platform.openai.com/api-keys) adresinden key alın",
        )

    col1, col2 = st.columns(2)
    if col1.button("💾 LLM Ayarlarını Kaydet", use_container_width=True):
        env_values = {"LLM_PROVIDER": provider}
        if provider == "groq":
            env_values["GROQ_API_KEY"] = llm_key
        else:
            env_values["OPENAI_API_KEY"] = llm_key
        save_multiple_env(env_values)
        st.success("✅ LLM ayarları kaydedildi ve uygulandı!")
        time.sleep(1)
        st.rerun()

    if col2.button("🧪 LLM Bağlantısını Test Et", use_container_width=True):
        if llm_key:
            with st.spinner("API key test ediliyor..."):
                try:
                    # Temporarily set for test
                    if provider == "groq":
                        os.environ["GROQ_API_KEY"] = llm_key
                    else:
                        os.environ["OPENAI_API_KEY"] = llm_key
                    os.environ["LLM_PROVIDER"] = provider

                    from defect_risk_analyzer.llm_provider import create_llm_provider
                    llm = create_llm_provider(provider)
                    if llm.test_connection():
                        st.success(f"✅ {provider.capitalize()} API bağlantısı başarılı!")
                    else:
                        st.error(f"❌ {provider.capitalize()} API bağlantısı başarısız.")
                except Exception as e:
                    st.error(f"❌ Hata: {e}")
        else:
            st.warning(f"Lütfen {provider.capitalize()} API key girin.")

    st.markdown("---")

    # --- App Settings ---
    st.subheader("🛠️ Uygulama Ayarları")

    max_daily = st.number_input(
        "Günlük Maksimum LLM İstek Sayısı",
        min_value=1, max_value=500,
        value=config.MAX_DAILY_REQUESTS,
        help="Günlük maliyet kontrolü için LLM çağrı limiti",
    )
    groq_sleep = st.number_input(
        "İstekler Arası Bekleme (saniye)",
        min_value=0.0, max_value=30.0,
        value=config.GROQ_SLEEP,
        step=0.5,
        help="Groq free-tier rate limit'e takılmamak için bekleme süresi",
    )
    mock_mode = st.toggle(
        "Mock Data Modu (Jira olmadan demo)",
        value=config.USE_MOCK_DATA,
        help="Aktifken Jira yerine örnek veriler kullanılır",
    )

    st.markdown("---")

    # --- Data Anonymization ---
    st.subheader("🔒 Veri Anonimleştirme")
    st.markdown("Aktifken, bug verileri LLM'e gönderilmeden önce hassas bilgiler maskelenir.")
    st.markdown(
        """**Maskelenen veriler:**

| Veri Türü | Örnek | Maskelenmiş Hali |
|-----------|-------|-----------------|
| E-posta adresleri | `ahmet@firma.com` | `[EMAIL_001]` |
| IP adresleri | `192.168.1.50` | `[IP_001]` |
| URL'ler | `https://site.com/api` | `[URL_001]` |
| Telefon numaraları | `+90 532 123 4567` | `[PHONE_001]` |
| Bearer Token'lar | `Bearer eyJhbG...` | `[TOKEN_001]` |
| API Key'ler | `gsk_abc123...`, `sk-abc123...` | `[APIKEY_001]` |
"""
    )
    st.caption(
        "Not: Düz metin olarak yazılmış kişi isimleri (ör. 'Ahmet Yılmaz') "
        "yapısal bir formata uymadığı için maskelenmez."
    )

    anonymize = st.toggle(
        "Veri Anonimleştirme",
        value=config.ANONYMIZE_DATA,
        help="LLM'e gönderilen verilerde PII maskeleme",
    )

    if st.button("💾 Uygulama Ayarlarını Kaydet", use_container_width=True):
        save_multiple_env({
            "MAX_DAILY_REQUESTS": str(max_daily),
            "GROQ_SLEEP": str(groq_sleep),
            "USE_MOCK_DATA": str(mock_mode),
            "ANONYMIZE_DATA": str(anonymize),
        })
        st.success("✅ Uygulama ayarları kaydedildi ve uygulandı!")
        time.sleep(1)
        st.rerun()

    st.markdown("---")

    # --- System Status ---
    st.subheader("📋 Sistem Durumu")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Yüklü Bug", len(get_service().get_bugs()))
    with col2:
        if config.is_jira_configured():
            st.success("✅ Jira Bağlı")
        else:
            st.error("❌ Jira Eksik")
    with col3:
        if config.is_llm_configured():
            st.success(f"✅ LLM ({config.LLM_PROVIDER})")
        else:
            st.error("❌ LLM Eksik")
    with col4:
        if config.USE_MOCK_DATA:
            st.info("🎭 Mock Aktif")
        else:
            st.success("🔴 Canlı Mod")

    # API Key — only relevant to the optional webhook server
    st.markdown("---")
    st.subheader("🔑 API Key (webhook servisi için)")

    if config.API_KEY:
        st.code(config.API_KEY, language=None)
        st.caption(
            "Bu key yalnızca opsiyonel webhook/API servisi için gerekir; dashboard "
            "analiz motorunu doğrudan çalıştırır ve bu key'i kullanmaz."
        )
    else:
        st.info(
            "Henüz bir API key üretilmemiş. Webhook kurmayacaksanız gerek yok — "
            "dashboard bu key olmadan da tam olarak çalışır."
        )

    # Generation is explicit: it writes to .env, and merely opening this page
    # must never do that.
    label = "🔄 API Key'i Yenile" if config.API_KEY else "🔑 API Key Üret"
    if st.button(label, use_container_width=True):
        new_key = config.ensure_api_key(rotate=bool(config.API_KEY))
        st.success(f"✅ API key kaydedildi: `{new_key[:8]}…`")
        st.warning(
            "Webhook servisi çalışıyorsa yeni key'i alması için yeniden "
            "başlatılmalı; Jira webhook tanımındaki header da güncellenmeli."
        )
        time.sleep(1)
        st.rerun()
    st.warning(
        "⚠️ Webhook servisi ayrı bir process olarak çalışıyorsa, buradaki "
        "ayarları görmez. Kaydettiğiniz değişikliklerin webhook tarafında da "
        "geçerli olması için o servisi yeniden başlatın."
    )


# =============================================================================
# Main Router
# =============================================================================

def main():
    """Main app entry point."""
    # The single bootstrap point for this process: creates data/ and reads
    # .env. Idempotent, so the Streamlit rerun loop does not re-read the file.
    config.init()

    # First-run: show setup wizard if nothing is configured
    if config.is_first_run():
        render_setup_wizard()
        return

    # Force page redirect (from session state)
    force_page = st.session_state.pop("force_page", None)

    page = render_sidebar()

    if force_page == "settings":
        page_settings()
    elif "Dashboard" in page:
        page_dashboard()
    elif "Bug Listesi" in page:
        page_bug_list()
    elif "Canlı Analiz" in page:
        page_live_analysis()
    elif "Pattern" in page:
        page_patterns()
    elif "Kör Nokta" in page:
        page_blind_spots()
    elif "Webhook" in page:
        page_webhook_results()
    elif "Ayarlar" in page:
        page_settings()


if __name__ == "__main__":
    main()
