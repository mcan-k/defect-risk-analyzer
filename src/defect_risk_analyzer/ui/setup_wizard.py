"""
First-run setup wizard.

Not a page: it is not reachable from the navigation and it disappears once
configuration exists. bootstrap() runs it when config.is_first_run() is true
and stops the script, so no page body and no navigation renders behind it.
"""

import time

import streamlit as st

from defect_risk_analyzer.ui import language
from defect_risk_analyzer.ui.i18n import t
from defect_risk_analyzer.ui.service import save_multiple_env


def render_setup_wizard():
    """First-run setup wizard for new users."""
    # A fresh install has no sidebar — bootstrap() stops the script before the
    # navigation — so this is the only place the language can be chosen, and a
    # non-Turkish user would otherwise be locked inside a Turkish setup.
    #
    # st.selectbox, NOT st.radio: tests/test_dashboard_pages.py reaches the
    # mode picker below as at.radio[0], and a second radio above it would
    # silently make that test drive the wrong widget.
    _, picker = st.columns([3, 1])
    language.render_selector(picker)

    st.title(t("wizard.title"))
    st.markdown(t("wizard.intro"))
    st.markdown("---")

    # Step 1: Choose mode
    st.subheader(t("wizard.step1.title"))
    st.markdown(t("wizard.step1.question"))

    demo_label = t("wizard.mode.demo")
    mode = st.radio(
        t("wizard.mode.label"),
        [demo_label, t("wizard.mode.live")],
        index=0,
        label_visibility="collapsed",
    )

    # Compared against the rendered label rather than searching it for "Demo".
    # The substring test happened to survive translation — "Demo" appears in
    # both wordings — but only by luck, and the next locale would decide the
    # whole branch by accident.
    if mode == demo_label:
        st.info(t("wizard.demo.info"))
        if st.button(t("wizard.demo.button"), type="primary", use_container_width=True):
            save_multiple_env({"USE_MOCK_DATA": "True"})
            st.success(t("wizard.demo.saved"))
            time.sleep(1)
            st.rerun()
        return

    # Step 2: LLM Provider
    st.markdown("---")
    st.subheader(t("wizard.step2.title"))
    st.markdown(t("wizard.step2.intro"))

    col1, col2 = st.columns([1, 3])
    with col1:
        llm_provider = st.selectbox(t("common.provider"), ["groq", "openai"], index=0)
    with col2:
        if llm_provider == "groq":
            llm_key = st.text_input(
                t("common.groq_api_key"),
                type="password",
                placeholder="gsk_...",
                help=t("wizard.groq.help"),
            )
        else:
            llm_key = st.text_input(
                t("common.openai_api_key"),
                type="password",
                placeholder="sk-...",
                help=t("wizard.openai.help"),
            )

    # Step 3: Jira Connection
    st.markdown("---")
    st.subheader(t("wizard.step3.title"))
    st.markdown(t("wizard.step3.intro"))

    col1, col2 = st.columns(2)
    with col1:
        jira_url = st.text_input(
            t("common.jira_url"),
            placeholder="https://yourcompany.atlassian.net",
            help=t("wizard.jira_url.help"),
        )
        jira_email = st.text_input(
            t("common.jira_email"),
            placeholder="you@company.com",
            help=t("wizard.jira_email.help"),
        )
    with col2:
        jira_token = st.text_input(
            t("common.jira_token"),
            type="password",
            placeholder="ATATT3x...",
            help=t("wizard.jira_token.help"),
        )
        jira_project = st.text_input(
            t("common.jira_project"),
            placeholder="AP",
            help=t("common.jira_project.help"),
        )

    # Save and start
    st.markdown("---")
    if st.button(t("wizard.save"), type="primary", use_container_width=True):
        # Validate minimum requirements
        if not llm_key:
            st.error(t("wizard.error.no_llm_key"))
            return

        if not all([jira_url, jira_email, jira_token, jira_project]):
            st.error(t("wizard.error.jira_incomplete"))
            return

        # Save all values
        env_values = {
            "LLM_PROVIDER": llm_provider,
            "USE_MOCK_DATA": "False",
            "JIRA_URL": jira_url.rstrip("/"),
            "JIRA_EMAIL": jira_email,
            "JIRA_API_TOKEN": jira_token,
            "JIRA_PROJECT_KEY": jira_project,
        }

        if llm_provider == "groq":
            env_values["GROQ_API_KEY"] = llm_key
        else:
            env_values["OPENAI_API_KEY"] = llm_key

        save_multiple_env(env_values)

        # Test connections
        st.info(t("wizard.testing"))

        # Test Jira
        try:
            from defect_risk_analyzer.jira_client import JiraClient
            client = JiraClient(jira_url, jira_email, jira_token, jira_project)
            if client.test_connection():
                st.success(t("common.jira.ok"))
            else:
                st.warning(t("wizard.jira.failed"))
        except Exception as e:
            st.warning(t("wizard.jira.error", detail=e))

        # Test LLM
        try:
            from defect_risk_analyzer.llm_provider import create_llm_provider
            llm = create_llm_provider(llm_provider)
            if llm.test_connection():
                st.success(t("common.llm.ok", provider=llm_provider.capitalize()))
            else:
                st.warning(t("wizard.llm.failed", provider=llm_provider.capitalize()))
        except Exception as e:
            st.warning(t("wizard.llm.error", detail=e))

        st.success(t("wizard.done"))
        time.sleep(2)
        st.rerun()
