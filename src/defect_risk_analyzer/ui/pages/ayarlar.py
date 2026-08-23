"""Ayarlar — self-service configuration."""

import os
import time

import streamlit as st

from defect_risk_analyzer import config
from defect_risk_analyzer.ui.i18n import t
from defect_risk_analyzer.ui.service import get_service, save_multiple_env
from defect_risk_analyzer.ui.shell import bootstrap

bootstrap()


def render_settings():
    """Self-service configuration panel with live reload."""
    st.title(t("nav.settings"))
    st.caption(t("settings.caption"))

    # --- Jira Connection ---
    st.subheader(t("settings.jira.title"))

    jira_url = st.text_input(t("common.jira_url"), value=config.JIRA_URL,
                             placeholder="https://yourcompany.atlassian.net")
    jira_email = st.text_input(
        t("common.jira_email"), value=config.JIRA_EMAIL, placeholder="you@company.com"
    )
    jira_token = st.text_input(t("common.jira_token"), value=config.JIRA_API_TOKEN,
                               type="password", help=t("settings.jira_token.help"))
    jira_project = st.text_input(t("common.jira_project"), value=config.JIRA_PROJECT_KEY,
                                 placeholder="AP", help=t("common.jira_project.help"))

    col1, col2 = st.columns(2)
    if col1.button(t("settings.jira.save"), use_container_width=True):
        save_multiple_env({
            "JIRA_URL": jira_url.rstrip("/"),
            "JIRA_EMAIL": jira_email,
            "JIRA_API_TOKEN": jira_token,
            "JIRA_PROJECT_KEY": jira_project,
        })
        st.success(t("settings.jira.saved"))
        time.sleep(1)
        st.rerun()

    if col2.button(t("settings.jira.test"), use_container_width=True):
        if all([jira_url, jira_email, jira_token]):
            with st.spinner(t("settings.jira.testing")):
                try:
                    from defect_risk_analyzer.jira_client import JiraClient
                    client = JiraClient(jira_url.rstrip("/"), jira_email, jira_token, jira_project)
                    if client.test_connection():
                        st.success(t("common.jira.ok"))
                    else:
                        st.error(t("settings.jira.failed"))
                except Exception as e:
                    st.error(t("settings.error", detail=e))
        else:
            st.warning(t("settings.jira.incomplete"))

    st.markdown("---")

    # --- LLM Provider ---
    st.subheader(t("settings.llm.title"))

    provider = st.selectbox(
        t("common.provider"),
        ["groq", "openai"],
        index=0 if config.LLM_PROVIDER == "groq" else 1,
    )

    if provider == "groq":
        llm_key = st.text_input(
            t("common.groq_api_key"),
            value=config.GROQ_API_KEY,
            type="password",
            help=t("settings.groq.help"),
        )
    else:
        llm_key = st.text_input(
            t("common.openai_api_key"),
            value=config.OPENAI_API_KEY,
            type="password",
            help=t("settings.openai.help"),
        )

    col1, col2 = st.columns(2)
    if col1.button(t("settings.llm.save"), use_container_width=True):
        env_values = {"LLM_PROVIDER": provider}
        if provider == "groq":
            env_values["GROQ_API_KEY"] = llm_key
        else:
            env_values["OPENAI_API_KEY"] = llm_key
        save_multiple_env(env_values)
        st.success(t("settings.llm.saved"))
        time.sleep(1)
        st.rerun()

    if col2.button(t("settings.llm.test"), use_container_width=True):
        if llm_key:
            with st.spinner(t("settings.llm.testing")):
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
                        st.success(t("common.llm.ok", provider=provider.capitalize()))
                    else:
                        st.error(t("settings.llm.failed", provider=provider.capitalize()))
                except Exception as e:
                    st.error(t("settings.error", detail=e))
        else:
            st.warning(t("settings.llm.key_required", provider=provider.capitalize()))

    st.markdown("---")

    # --- App Settings ---
    st.subheader(t("settings.app.title"))

    max_daily = st.number_input(
        t("settings.max_daily"),
        min_value=1, max_value=500,
        value=config.MAX_DAILY_REQUESTS,
        help=t("settings.max_daily.help"),
    )
    groq_sleep = st.number_input(
        t("settings.sleep"),
        min_value=0.0, max_value=30.0,
        value=config.GROQ_SLEEP,
        step=0.5,
        help=t("settings.sleep.help"),
    )
    mock_mode = st.toggle(
        t("settings.mock_mode"),
        value=config.USE_MOCK_DATA,
        help=t("settings.mock_mode.help"),
    )

    st.markdown("---")

    # --- Data Anonymization ---
    st.subheader(t("settings.anon.title"))
    st.markdown(t("settings.anon.intro"))
    st.markdown(t("settings.anon.table"))
    st.caption(t("settings.anon.note"))

    anonymize = st.toggle(
        t("settings.anon.toggle"),
        value=config.ANONYMIZE_DATA,
        help=t("settings.anon.toggle.help"),
    )

    if st.button(t("settings.app.save"), use_container_width=True):
        save_multiple_env({
            "MAX_DAILY_REQUESTS": str(max_daily),
            "GROQ_SLEEP": str(groq_sleep),
            "USE_MOCK_DATA": str(mock_mode),
            "ANONYMIZE_DATA": str(anonymize),
        })
        st.success(t("settings.app.saved"))
        time.sleep(1)
        st.rerun()

    st.markdown("---")

    # --- System Status ---
    st.subheader(t("settings.status.title"))

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(t("sidebar.metric.bugs_loaded"), len(get_service().get_bugs()))
    with col2:
        if config.is_jira_configured():
            st.success(t("settings.status.jira_ok"))
        else:
            st.error(t("settings.status.jira_missing"))
    with col3:
        if config.is_llm_configured():
            st.success(t("settings.status.llm_ok", provider=config.LLM_PROVIDER))
        else:
            st.error(t("settings.status.llm_missing"))
    with col4:
        if config.USE_MOCK_DATA:
            st.info(t("settings.status.mock"))
        else:
            st.success(t("settings.status.live"))

    # API Key — only relevant to the optional webhook server
    st.markdown("---")
    st.subheader(t("settings.apikey.title"))

    if config.API_KEY:
        st.code(config.API_KEY, language=None)
        st.caption(t("settings.apikey.note"))
    else:
        st.info(t("settings.apikey.none"))

    # Generation is explicit: it writes to .env, and merely opening this page
    # must never do that.
    label = t("settings.apikey.rotate") if config.API_KEY else t("settings.apikey.create")
    if st.button(label, use_container_width=True):
        new_key = config.ensure_api_key(rotate=bool(config.API_KEY))
        st.success(t("settings.apikey.saved", key=new_key[:8]))
        st.warning(t("settings.apikey.restart"))
        time.sleep(1)
        st.rerun()
    st.warning(t("settings.webhook.separate_process"))


render_settings()
