"""
Genel Bakış — the entry point, and the first of the four pages.

Streamlit's MPA-v1 discovery makes the entry script a page in its own right, so
the risk overview lives here rather than under pages/. Two tabs: the charts
that were the old Dashboard page, and the blind spot findings that were their
own page before Faz 5B. Both read what is already stored and report on it;
neither calls an LLM, which is why they ended up together.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from defect_risk_analyzer.ui.messages import format_finding
from defect_risk_analyzer.ui.service import call, get_service
from defect_risk_analyzer.ui.shell import bootstrap
from defect_risk_analyzer.ui.theme import CHART_COLORS, RISK_COLORS, apply_chart_theme

bootstrap()


def render_risk_overview():
    """Risk overview dashboard with charts and alerts."""
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


def render_blind_spots():
    """Display blind spots — untested risky areas and neglected bugs."""
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
            f"⚡ {len(unanalyzed)} riskli modülü **Analiz** sayfasından analiz edin"
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


st.title("📊 Genel Bakış")

tab_risk, tab_blind = st.tabs(["📊 Risk Dashboard", "🎯 Kör Nokta Tespiti"])

with tab_risk:
    render_risk_overview()

with tab_blind:
    render_blind_spots()
