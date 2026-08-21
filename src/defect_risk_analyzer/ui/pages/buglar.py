"""
Buglar — the bug list and the patterns detected across it.

Both tabs answer "what is in the bug set": one lists it with filters, the other
groups it into clusters and checks a bug for duplicates.
"""

import pandas as pd
import streamlit as st

from defect_risk_analyzer.ui.service import call, get_service
from defect_risk_analyzer.ui.shell import bootstrap

bootstrap()


def render_bug_list():
    """Bug list with filters and search."""
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


def render_patterns():
    """Display detected bug patterns and clusters."""
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


st.title("🐛 Buglar")

tab_list, tab_patterns = st.tabs(["🐛 Bug Listesi", "🔗 Pattern Tespiti"])

with tab_list:
    render_bug_list()

with tab_patterns:
    render_patterns()
