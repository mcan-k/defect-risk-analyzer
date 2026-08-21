"""One analysis result, rendered.

Shared by the live analysis and the webhook history — both show the same
payload shape, which is why the two ended up on one page in Faz 5B.
"""

import streamlit as st

from defect_risk_analyzer.ui.theme import RISK_COLORS


def display_analysis_result(result: dict):
    """Display a single analysis result with formatting."""
    risk_level = result.get("risk_level", "LOW")
    risk_score = result.get("risk_score", 0)
    color = RISK_COLORS.get(risk_level, "#666")

    st.markdown(
        f"### Risk Skoru: <span style='color:{color}; font-size:1.5em;'>{risk_score}</span> "
        f"<span style='background-color:{color}; color:white; padding:2px 10px; "
        f"border-radius:4px;'>{risk_level}</span>",
        unsafe_allow_html=True,
    )

    reasoning = result.get("reasoning", "")
    if reasoning:
        st.markdown("**Analiz:**")
        st.markdown(reasoning)

    col1, col2 = st.columns(2)

    with col1:
        modules = result.get("affected_modules", [])
        if modules:
            st.markdown("**Etkilenen Modüller:**")
            for m in modules:
                st.markdown(f"- {m}")

        scenarios = result.get("test_scenarios", [])
        if scenarios:
            st.markdown("**Test Senaryoları:**")
            for s in scenarios:
                st.markdown(f"- {s}")

    with col2:
        actions = result.get("recommended_actions", [])
        if actions:
            st.markdown("**Önerilen Aksiyonlar:**")
            for a in actions:
                st.markdown(f"- {a}")

    st.caption(
        f"Kaynak: {result.get('source', '?')} | "
        f"Tarih: {result.get('analyzed_at', '?')[:19]}"
    )
