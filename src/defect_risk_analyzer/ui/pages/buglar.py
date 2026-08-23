"""
Buglar — the bug list and the patterns detected across it.

Both tabs answer "what is in the bug set": one lists it with filters, the other
groups it into clusters and checks a bug for duplicates.
"""

import pandas as pd
import streamlit as st

from defect_risk_analyzer.ui.i18n import t
from defect_risk_analyzer.ui.service import call, get_service
from defect_risk_analyzer.ui.shell import bootstrap

bootstrap()

# Severity keys are the detector's own, in English, and so is the colour map.
# Only the badge text is translated — see SEVERITY_LABEL below.
SEVERITY_COLORS = {
    "critical": "#DC2626",
    "high": "#F97316",
    "medium": "#EAB308",
    "low": "#22C55E",
}

SEVERITY_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
}


def _bug_columns(*, created: bool) -> dict:
    """Headers for a bug table, in the active language.

    The pattern tab shows four of these columns and the list tab six, so the
    tail is optional rather than duplicated.
    """
    columns = {
        "key": st.column_config.TextColumn(t("col.key")),
        "summary": st.column_config.TextColumn(t("col.summary")),
        "priority": st.column_config.TextColumn(t("col.priority")),
        "status": st.column_config.TextColumn(t("col.status")),
    }
    if created:
        columns["module"] = st.column_config.TextColumn(t("col.module"))
        columns["created"] = st.column_config.TextColumn(t("col.created"))
    return columns


def render_bug_list():
    """Bug list with filters and search."""
    bugs = get_service().get_bugs()
    if not bugs:
        st.info(t("bugs.no_data"))
        return

    col1, col2, col3 = st.columns(3)

    priorities = sorted(set(b.get("priority", "Medium") for b in bugs))
    statuses = sorted(set(b.get("status", "Open") for b in bugs))
    components = sorted(set(b.get("component", "Unknown") for b in bugs))

    with col1:
        selected_priority = st.multiselect(t("bugs.filter.priority"), priorities,
                                           default=priorities)
    with col2:
        selected_status = st.multiselect(t("bugs.filter.status"), statuses, default=statuses)
    with col3:
        selected_component = st.multiselect(t("bugs.filter.module"), components,
                                            default=components)

    search = st.text_input(t("bugs.search"), "")

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

    st.markdown(t("bugs.count", shown=len(filtered), total=len(bugs)))

    if filtered:
        df = pd.DataFrame([
            {
                "key": b.get("key", ""),
                "summary": b.get("summary", ""),
                "priority": b.get("priority", ""),
                "status": b.get("status", ""),
                "module": b.get("component", ""),
                "created": b.get("created", "")[:10],
            }
            for b in filtered
        ])
        st.dataframe(
            df,
            column_config=_bug_columns(created=True),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.warning(t("bugs.no_match"))


def render_patterns():
    """Display detected bug patterns and clusters."""
    st.caption(t("patterns.caption"))

    patterns = call(get_service().detect_patterns, include_bugs=False)

    if patterns is None:
        return

    if not patterns:
        st.info(t("patterns.no_data"))
        return

    # Summary metrics
    total_patterns = len(patterns)
    total_bugs_in_patterns = sum(p.get("bug_count", 0) for p in patterns)
    critical_patterns = sum(1 for p in patterns if p.get("severity") == "critical")

    col1, col2, col3 = st.columns(3)
    col1.metric(t("patterns.metric.detected"), total_patterns)
    col2.metric(t("patterns.metric.affected_bugs"), total_bugs_in_patterns)
    col3.metric(t("patterns.metric.critical"), critical_patterns)

    st.markdown("---")

    # Fetched once: this used to be re-read inside the loop below, one call
    # per pattern.
    all_bugs = get_service().get_bugs()

    # Display each pattern
    for pattern in patterns:
        severity = pattern.get("severity", "low")
        color = SEVERITY_COLORS.get(severity, "#666")
        label = t(f"severity.{severity}") if severity in SEVERITY_COLORS else "?"
        bug_count = pattern.get("bug_count", 0)
        keywords = pattern.get("common_keywords", [])
        component = pattern.get("common_component", "Genel")
        bug_keys = pattern.get("bug_keys", [])

        header = t(
            "patterns.header",
            pattern_id=pattern.get("pattern_id", "?"),
            bug_count=bug_count,
            component=component,
        )

        with st.expander(f"{SEVERITY_EMOJI.get(severity, '🟢')} {header}"):

            # Severity badge
            st.markdown(
                f"{t('patterns.severity_label')} "
                f"<span style='background-color:{color}; color:white; "
                f"padding:2px 10px; border-radius:4px;'>{label}</span> &nbsp; "
                f"{t('patterns.module_label')} {component} &nbsp; "
                f"{t('patterns.common_priority_label')} "
                f"{pattern.get('common_priority', '?')}",
                unsafe_allow_html=True,
            )

            # Common keywords as tags
            if keywords:
                st.markdown(t("patterns.keywords"))
                keyword_tags = " ".join(
                    f"<span style='background-color:rgba(100,100,255,0.15); "
                    f"padding:2px 8px; border-radius:12px; margin:2px; "
                    f"display:inline-block; font-size:0.85em;'>{kw}</span>"
                    for kw in keywords
                )
                st.markdown(keyword_tags, unsafe_allow_html=True)

            # Bug list
            st.markdown(t("patterns.bugs_in", bug_keys=", ".join(bug_keys)))

            # Load full bug details
            if all_bugs:
                pattern_bugs = [b for b in all_bugs if b.get("key") in bug_keys]
                if pattern_bugs:
                    df = pd.DataFrame([
                        {
                            "key": b.get("key", ""),
                            "summary": b.get("summary", "")[:80],
                            "priority": b.get("priority", ""),
                            "status": b.get("status", ""),
                        }
                        for b in pattern_bugs
                    ])
                    st.dataframe(
                        df,
                        column_config=_bug_columns(created=False),
                        use_container_width=True,
                        hide_index=True,
                    )

            # Root cause suggestion
            if keywords:
                # The conjunction is a message of its own: "`a` ve `b`" is not
                # something an English locale can produce by substituting one
                # word into a Turkish sentence shape.
                quoted = f"`{keywords[0]}`"
                if len(keywords) > 1:
                    quoted += f" {t('patterns.root_cause.and')} `{keywords[1]}`"
                st.markdown(t("patterns.root_cause", keywords=quoted))

    # Duplicate check section
    st.markdown("---")
    st.subheader(t("patterns.duplicate.title"))
    st.caption(t("patterns.duplicate.caption"))

    bug_key_input = st.text_input(t("common.bug_key"),
                                  placeholder=t("patterns.duplicate.placeholder"))
    if st.button(t("patterns.duplicate.button")):
        if bug_key_input:
            bug = get_service().get_bug(bug_key_input)
            if bug is None:
                st.error(t("patterns.duplicate.not_found", bug_key=bug_key_input))
                dupes = None
            else:
                dupes = call(get_service().find_duplicate_bugs, bug)

            if dupes is not None:
                if dupes:
                    st.warning(t("patterns.duplicate.found", count=len(dupes)))
                    for d in dupes:
                        st.markdown(
                            t(
                                "patterns.duplicate.item",
                                key=d.get("key", "?"),
                                summary=d.get("summary", "?"),
                                similarity=d.get("similarity", 0),
                            )
                        )
                else:
                    st.success(t("patterns.duplicate.unique"))
        else:
            st.warning(t("patterns.duplicate.empty"))


st.title(t("nav.bugs"))

tab_list, tab_patterns = st.tabs([t("bugs.tab.list"), t("bugs.tab.patterns")])

with tab_list:
    render_bug_list()

with tab_patterns:
    render_patterns()
