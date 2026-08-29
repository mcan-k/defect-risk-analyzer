"""
Genel Bakış — the entry point, and the first of the four pages.

Streamlit's MPA-v1 discovery makes the entry script a page in its own right, so
the risk overview lives here rather than under pages/. Two tabs: the charts
that were the old Dashboard page, and the blind spot findings that were their
own page before Faz 5B. Both read what is already stored and report on it;
neither calls an LLM, which is why they ended up together.

Every DataFrame here is keyed in English (`risk_score`, not "Risk Skoru"), and
the Turkish or English header is applied at render time — through
`column_config` for tables and `labels=` for Plotly. Before Faz 5C the column
name WAS the label, so `px.bar(x="Risk Skoru", ...)` meant switching language
would have required rebuilding the frame rather than relabelling it.
"""

import html

import pandas as pd
import plotly.express as px
import streamlit as st

from defect_risk_analyzer.ui.i18n import t
from defect_risk_analyzer.ui.messages import format_finding
from defect_risk_analyzer.ui.service import call, get_service
from defect_risk_analyzer.ui.shell import bootstrap
from defect_risk_analyzer.ui.theme import (
    CHART_COLORS,
    RISK_COLORS,
    apply_chart_theme,
    risk_color_map,
    risk_level_label,
)

bootstrap()


def render_risk_overview():
    """Risk overview dashboard with charts and alerts."""
    risks = call(get_service().get_risk_summary)
    if not risks:
        st.info(t("overview.no_data"))
        return

    module_risks = risks.get("module_risks", {})
    if not module_risks:
        st.info(t("overview.no_module_risk"))
        return

    # Top metrics
    total_bugs = risks.get("total_bugs", 0)
    analyzed = risks.get("analyzed_count", 0)
    critical_count = sum(1 for m in module_risks.values() if m.get("level") == "CRITICAL")
    high_count = sum(1 for m in module_risks.values() if m.get("level") == "HIGH")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(t("overview.metric.total_bugs"), total_bugs)
    col2.metric(t("overview.metric.analyzed"), analyzed)
    col3.metric(t("overview.metric.critical_modules"), critical_count)
    col4.metric(t("overview.metric.high_risk_modules"), high_count)

    # Critical alerts
    critical_modules = [
        name for name, data in module_risks.items() if data.get("level") == "CRITICAL"
    ]
    if critical_modules:
        st.error(t("overview.critical_alert", modules=", ".join(critical_modules)))

    st.markdown("---")

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader(t("overview.chart.risk_map"))
        df_risk = pd.DataFrame([
            {
                "module": name,
                "risk_score": data.get("score", 0),
                # The legend shows this column, so it holds the label. The
                # colour still comes from the English level — see
                # theme.risk_color_map().
                "risk_level_label": risk_level_label(data.get("level", "LOW")),
                "bug_count": data.get("bug_count", 0),
            }
            for name, data in module_risks.items()
        ]).sort_values("risk_score", ascending=True)

        fig = px.bar(
            df_risk,
            x="risk_score",
            y="module",
            orientation="h",
            color="risk_level_label",
            color_discrete_map=risk_color_map(),
            text="risk_score",
            labels={
                "risk_score": t("col.risk_score"),
                "module": t("col.module"),
                "risk_level_label": t("col.risk_level"),
            },
        )
        fig.update_traces(textposition="outside")
        apply_chart_theme(fig, height=400)
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.subheader(t("overview.chart.bug_distribution"))
        df_bugs = pd.DataFrame([
            {"module": name, "bug_count": data.get("bug_count", 0)}
            for name, data in module_risks.items()
        ])
        fig2 = px.pie(df_bugs, values="bug_count", names="module", hole=0.4,
                      color_discrete_sequence=CHART_COLORS,
                      labels={"bug_count": t("col.bug_count"), "module": t("col.module")})
        apply_chart_theme(fig2, height=400)
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")
    st.subheader(t("overview.table.risk_ranking"))

    table_data = []
    for name, data in sorted(
        module_risks.items(), key=lambda x: x[1].get("score", 0), reverse=True
    ):
        table_data.append({
            "module": name,
            "risk_score": data.get("score", 0),
            "risk_level_label": risk_level_label(data.get("level", "LOW")),
            "bug_count": data.get("bug_count", 0),
            "open_count": data.get("open_count", 0),
        })

    st.dataframe(
        pd.DataFrame(table_data),
        # Note col.level and col.total_bugs: the chart above shows the same two
        # values under different Turkish words ("Risk Seviyesi", "Bug Sayısı"),
        # so the display keys are separate even though the data keys are not.
        # Both wordings existed before 5C and both are preserved.
        column_config={
            "module": st.column_config.TextColumn(t("col.module")),
            "risk_score": st.column_config.NumberColumn(t("col.risk_score")),
            "risk_level_label": st.column_config.TextColumn(t("col.level")),
            "bug_count": st.column_config.NumberColumn(t("col.total_bugs")),
            "open_count": st.column_config.NumberColumn(t("col.open_bugs")),
        },
        use_container_width=True,
        hide_index=True,
    )

    # --- Trend Charts ---
    bugs = get_service().get_bugs()
    if bugs:
        st.markdown("---")
        st.subheader(t("overview.trend.title"))

        # Parse dates and build timeline data
        trend_data = []
        for bug in bugs:
            created = bug.get("created", "")
            component = bug.get("component", "Genel")
            if created:
                try:
                    date = pd.to_datetime(created).date()
                    trend_data.append({
                        "date": date,
                        "module": component,
                        "status": bug.get("status", "Open"),
                    })
                except Exception:
                    pass

        if trend_data:
            df_trend = pd.DataFrame(trend_data)

            col_left, col_right = st.columns(2)

            with col_left:
                st.markdown(t("overview.trend.weekly"))
                df_weekly = df_trend.copy()
                df_weekly["week"] = pd.to_datetime(df_weekly["date"]).apply(
                    lambda d: d - pd.Timedelta(days=d.weekday())
                )
                weekly_counts = (
                    df_weekly.groupby(["week", "module"]).size().reset_index(name="bug_count")
                )

                fig_trend = px.line(
                    weekly_counts,
                    x="week",
                    y="bug_count",
                    color="module",
                    markers=True,
                    color_discrete_sequence=CHART_COLORS,
                    labels={
                        "week": t("col.week"),
                        "bug_count": t("col.bug_count"),
                        "module": t("col.module"),
                    },
                )
                apply_chart_theme(fig_trend, height=350)
                st.plotly_chart(fig_trend, use_container_width=True)

            with col_right:
                st.markdown(t("overview.trend.open_closed"))
                open_statuses = {"to do", "open", "in progress", "in review", "reopened"}
                df_status = df_trend.copy()

                # The stable key decides the colour, the label is what the
                # legend shows. Splitting them is what keeps the palette from
                # depending on the interface language.
                df_status["category"] = df_status["status"].apply(
                    lambda s: "open" if s.lower() in open_statuses else "closed"
                )
                df_status["category_label"] = df_status["category"].map(
                    lambda code: t(f"chart.status.{code}")
                )
                status_by_module = (
                    df_status.groupby(["module", "category_label"])
                    .size()
                    .reset_index(name="count")
                )

                fig_status = px.bar(
                    status_by_module,
                    x="module",
                    y="count",
                    color="category_label",
                    barmode="stack",
                    color_discrete_map={
                        t("chart.status.open"): "#F97316",
                        t("chart.status.closed"): "#22C55E",
                    },
                    labels={
                        "module": t("col.module"),
                        "count": t("col.count"),
                        "category_label": t("col.category"),
                    },
                )
                fig_status.update_layout(xaxis_title="", yaxis_title=t("col.bug_count"))
                apply_chart_theme(fig_status, height=350)
                st.plotly_chart(fig_status, use_container_width=True)

            # Cumulative trend
            st.markdown(t("overview.trend.cumulative"))
            df_cumulative = df_trend.sort_values("date")
            df_cumulative["rank"] = range(1, len(df_cumulative) + 1)
            df_cumulative["date"] = pd.to_datetime(df_cumulative["date"])

            fig_cum = px.area(
                df_cumulative,
                x="date",
                y="rank",
                labels={"rank": t("col.cumulative_bugs"), "date": t("col.date")},
            )
            fig_cum.update_traces(fill="tozeroy", line_color="#8B5CF6")
            apply_chart_theme(fig_cum, height=300)
            st.plotly_chart(fig_cum, use_container_width=True)


def _bug_row(item: dict) -> dict:
    """One blind-spot bug as a row, keyed in English.

    The neglected and stale tables hold the same six fields, which is why the
    row and its headers are built once rather than spelled out twice.
    """
    return {
        "key": item.get("key", ""),
        "summary": item.get("summary", "")[:70],
        "priority": item.get("priority", ""),
        "status": item.get("status", ""),
        "module": item.get("component", ""),
        "days_open": item.get("days_open", 0),
    }


def _bug_columns() -> dict:
    """Headers for _bug_row, in the active language.

    Built per call rather than cached at import: the language can change
    between reruns, and a module-level dict would freeze whichever one happened
    to be active when this module first loaded.
    """
    return {
        "key": st.column_config.TextColumn(t("col.key")),
        "summary": st.column_config.TextColumn(t("col.summary")),
        "priority": st.column_config.TextColumn(t("col.priority")),
        "status": st.column_config.TextColumn(t("col.status")),
        "module": st.column_config.TextColumn(t("col.module")),
        "days_open": st.column_config.NumberColumn(t("col.days_open")),
    }


def render_blind_spots():
    """Display blind spots — untested risky areas and neglected bugs."""
    st.caption(t("blindspot.caption"))

    data = call(get_service().detect_blind_spots)

    if data is None:
        return

    summary = data.get("summary", {})
    total = summary.get("total_blind_spots", 0)
    critical = summary.get("critical_spots", 0)
    categories = summary.get("categories", {})

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(t("blindspot.metric.total"), total)
    col2.metric(t("blindspot.metric.critical"), critical)
    col3.metric(t("blindspot.metric.neglected"), categories.get("neglected_critical_bugs", 0))
    col4.metric(t("blindspot.metric.stale"), categories.get("stale_bugs", 0))

    if total == 0:
        st.success(t("blindspot.none"))
        return

    st.markdown("---")

    # --- 1. Unanalyzed Risky Modules ---
    unanalyzed = data.get("unanalyzed_risky_modules", [])
    if unanalyzed:
        st.subheader(t("blindspot.unanalyzed.title"))
        st.caption(t("blindspot.unanalyzed.caption"))

        for item in unanalyzed:
            risk_level = item.get("risk_level", "MEDIUM")
            color = RISK_COLORS.get(risk_level, "#666")
            detail = t(
                "blindspot.unanalyzed.detail",
                score=item.get("risk_score", 0),
                open_bugs=item.get("open_bugs", 0),
            )

            st.markdown(
                f"**{html.escape(str(item.get('module', '?')))}** — "
                f"<span style='background-color:{html.escape(color)}; color:white; "
                f"padding:2px 8px; border-radius:4px;'>"
                f"{html.escape(risk_level_label(risk_level))}</span> "
                f"{html.escape(detail)}",
                unsafe_allow_html=True,
            )
            st.caption(f"💡 {format_finding(item)}")

        st.markdown("---")

    # --- 2. Neglected Critical Bugs ---
    neglected = data.get("neglected_critical_bugs", [])
    if neglected:
        st.subheader(t("blindspot.neglected.title"))
        st.caption(t("blindspot.neglected.caption"))

        df_neglected = pd.DataFrame([_bug_row(item) for item in neglected])
        st.dataframe(
            df_neglected,
            column_config=_bug_columns(),
            use_container_width=True,
            hide_index=True,
        )

        for item in neglected[:3]:
            st.caption(f"💡 {format_finding(item)}")

        st.markdown("---")

    # --- 3. Stale Bugs ---
    stale = data.get("stale_bugs", [])
    if stale:
        st.subheader(t("blindspot.stale.title"))
        st.caption(t("blindspot.stale.caption"))

        df_stale = pd.DataFrame([_bug_row(item) for item in stale])
        st.dataframe(
            df_stale,
            column_config=_bug_columns(),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("---")

    # --- 4. Rising Unattended ---
    rising = data.get("rising_unattended", [])
    if rising:
        st.subheader(t("blindspot.rising.title"))
        st.caption(t("blindspot.rising.caption"))

        for item in rising:
            detail = t(
                "blindspot.rising.item",
                total_bugs=item.get("total_bugs", 0),
                recent_bugs=item.get("recent_bugs", 0),
                in_progress=item.get("in_progress", 0),
            )
            st.markdown(f"**{item.get('module', '?')}** — {detail}")
            st.caption(f"💡 {format_finding(item)}")

    # Action summary
    st.markdown("---")
    st.subheader(t("blindspot.actions.title"))

    actions = []
    if unanalyzed:
        actions.append(t("blindspot.action.unanalyzed", count=len(unanalyzed)))
    if neglected:
        actions.append(t("blindspot.action.neglected", count=len(neglected)))
    if stale:
        actions.append(t("blindspot.action.stale", count=len(stale)))
    if rising:
        actions.append(t("blindspot.action.rising", count=len(rising)))

    if actions:
        for action in actions:
            st.markdown(f"- {action}")
    else:
        st.success(t("blindspot.all_clear"))


st.title(t("nav.overview"))

tab_risk, tab_blind = st.tabs([t("overview.tab.risk"), t("overview.tab.blindspot")])

with tab_risk:
    render_risk_overview()

with tab_blind:
    render_blind_spots()
