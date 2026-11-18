"""Ayarlar — self-service configuration."""

import streamlit as st

from defect_risk_analyzer import config
from defect_risk_analyzer.ui.i18n import t
from defect_risk_analyzer.ui.messages import format_secret_layer
from defect_risk_analyzer.ui.service import call, get_service, save_multiple_env
from defect_risk_analyzer.ui.shell import bootstrap

bootstrap()

# st.session_state key: a generated API key that .env did not take, carried
# over the button's st.rerun() to the run that shows the warning — anything
# drawn before the rerun is gone once the rerun renders (6E-2 PR5, MG).
_API_KEY_NOT_SAVED = "_dra_api_key_not_saved"

# st.session_state key: which save succeeded — "jira", "llm", "app" or
# "apikey" — carried over the same rerun to the run that shows its success
# line. The lines used to be drawn, then time.sleep(1), then st.rerun(): the
# rerun's tree is the one that stays, and it did not hold them (measured,
# 6E-2 PR8). The sync line was fixed the same way in 6E-2 PR7, without a
# sleep: waiting only made the user wait for a line that then vanished.
_SAVED = "_dra_settings_saved"


def _warn_if_unreadable(key: str) -> None:
    """Say so under a credential field the store could not fill (6E-2 PR10).

    The field starts with the value in use, and for an unreadable credential
    that is "" — which looks exactly like "not set". The layer line above
    still says the store is in use, so without this nothing on the page
    explains the empty field.
    """
    if key in config.UNREADABLE_SECRETS:
        st.warning(t("settings.secret_unreadable"))


def _add_credential(values: dict[str, str], key: str, typed: str) -> None:
    """Put a credential field into a save, unless it is a field the store
    could not fill and the user left it empty.

    An empty credential field normally means the user cleared it, and the
    save deletes the stored copy (6E-2 PR8). A field the store could not read
    is empty for another reason, and the warning under it says saving will
    not delete anything. Sent anyway, that "" deleted a credential the user
    had never seen as soon as the store could be read again (measured, 6E-2
    PR9) — so it is left out, and the stored value is not touched. A value
    the user typed is saved as usual.
    """
    if typed or key not in config.UNREADABLE_SECRETS:
        values[key] = typed


def render_settings():
    """Self-service configuration panel with live reload."""
    # Popped once, at the top, so each success line is shown once — on the
    # run right after its save — whichever section draws it.
    saved = st.session_state.pop(_SAVED, None)

    st.title(t("nav.settings"))
    st.caption(t("settings.caption"))

    # Which layer the credentials below actually live in. Shown rather than
    # assumed: PYTHON_KEYRING_BACKEND and keyringrc.cfg can both redirect the
    # choice, so the only honest answer is the one resolved at run time. This is
    # also what ROADMAP:494 asks for — the user is told which guarantee applies
    # to their install.
    _store, _layer_code, _layer_params = config.secret_store()
    st.caption(
        t("settings.secret_layer",
          layer=format_secret_layer(_layer_code, _layer_params))
    )

    # --- Jira Connection ---
    st.subheader(t("settings.jira.title"))

    jira_url = st.text_input(t("common.jira_url"), value=config.JIRA_URL,
                             placeholder="https://yourcompany.atlassian.net")
    jira_email = st.text_input(
        t("common.jira_email"), value=config.JIRA_EMAIL, placeholder="you@company.com"
    )
    jira_token = st.text_input(t("common.jira_token"), value=config.JIRA_API_TOKEN,
                               type="password", help=t("settings.jira_token.help"))
    _warn_if_unreadable("JIRA_API_TOKEN")
    jira_project = st.text_input(t("common.jira_project"), value=config.JIRA_PROJECT_KEY,
                                 placeholder="AP", help=t("common.jira_project.help"))

    col1, col2 = st.columns(2)
    # Every save goes through call(): a .env that cannot be written is reported
    # on the page, and the success line and rerun come only after a real save
    # (a rerun right after the error would wipe it off the screen).
    if col1.button(t("settings.jira.save"), use_container_width=True):
        jira_values = {"JIRA_URL": jira_url.rstrip("/"), "JIRA_EMAIL": jira_email}
        _add_credential(jira_values, "JIRA_API_TOKEN", jira_token)
        jira_values["JIRA_PROJECT_KEY"] = jira_project
        if call(save_multiple_env, jira_values):
            st.session_state[_SAVED] = "jira"
            st.rerun()
    if saved == "jira":
        st.success(t("settings.jira.saved"))

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

    llm_key_name = "GROQ_API_KEY" if provider == "groq" else "OPENAI_API_KEY"
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
    _warn_if_unreadable(llm_key_name)

    col1, col2 = st.columns(2)
    if col1.button(t("settings.llm.save"), use_container_width=True):
        env_values = {"LLM_PROVIDER": provider}
        _add_credential(env_values, llm_key_name, llm_key)
        if call(save_multiple_env, env_values):
            st.session_state[_SAVED] = "llm"
            st.rerun()
    if saved == "llm":
        st.success(t("settings.llm.saved"))

    if col2.button(t("settings.llm.test"), use_container_width=True):
        if llm_key:
            with st.spinner(t("settings.llm.testing")):
                try:
                    # The typed key is PASSED, not written to os.environ.
                    #
                    # The old code set os.environ and then built a provider —
                    # which did nothing for the test and everything for the
                    # leak. Measured: the providers read config.GROQ_API_KEY /
                    # config.OPENAI_API_KEY, module globals that only reload()
                    # writes, and this branch never calls reload(). So the
                    # button validated the last SAVED key while leaving the
                    # typed one in the process environment for good. On a fresh
                    # install it reported "GROQ_API_KEY is not set in .env" for
                    # a perfectly valid key.
                    from defect_risk_analyzer.llm_provider import create_llm_provider
                    llm = create_llm_provider(provider, api_key=llm_key)
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
        if call(save_multiple_env, {
            "MAX_DAILY_REQUESTS": str(max_daily),
            "GROQ_SLEEP": str(groq_sleep),
            "USE_MOCK_DATA": str(mock_mode),
            "ANONYMIZE_DATA": str(anonymize),
        }):
            st.session_state[_SAVED] = "app"
            st.rerun()
    if saved == "app":
        st.success(t("settings.app.saved"))

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
        # Prefix only. The full key used to be printed here, which is the one
        # place in the UI that did — analiz.py:141 and the rotate message below
        # both already showed [:8]. A webhook key is not something the page
        # needs to display in full to confirm that one exists.
        st.code(f"{config.API_KEY[:8]}…", language=None)
        st.caption(t("settings.apikey.note"))
    else:
        st.info(t("settings.apikey.none"))

    if st.session_state.pop(_API_KEY_NOT_SAVED, False):
        st.warning(t("settings.apikey.not_saved"))

    # The key's prefix is read here, from the key in use — the one st.code
    # shows above — not carried in session_state: there is no reason to keep
    # any part of a credential in the session for a message.
    if saved == "apikey":
        st.success(t("settings.apikey.saved", key=config.API_KEY[:8]))
        st.warning(t("settings.apikey.restart"))

    # Generation is explicit: it saves a credential (the store, or .env when
    # there is none), and merely opening this page must never do that.
    label = t("settings.apikey.rotate") if config.API_KEY else t("settings.apikey.create")
    if st.button(label, use_container_width=True):
        result = config.ensure_api_key(rotate=bool(config.API_KEY))
        if result.saved:
            st.session_state[_SAVED] = "apikey"
        else:
            # .env did not take the key: it works in this process only, and
            # "saved" would be the one thing not to say (T2(a), 2026-11-11).
            st.session_state[_API_KEY_NOT_SAVED] = True
        st.rerun()
    st.warning(t("settings.webhook.separate_process"))


render_settings()
