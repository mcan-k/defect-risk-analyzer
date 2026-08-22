"""The Streamlit binding for i18n: where the active language comes from.

Separate from i18n.py, which deliberately knows nothing about Streamlit so the
locale contract stays testable without a script context. Everything that needs
st.session_state or writes to .env lives here instead.

Both shell.py and setup_wizard.py draw the selector, which is why this is its
own module rather than a function in shell.py: shell.py imports setup_wizard.py
to run the first-run gate, so the reverse import would be a real cycle.

Two layers hold the language, on purpose:

  * config.LANGUAGE — the persisted default, read from .env by config.reload()
    exactly like USE_MOCK_DATA. It is what a fresh process starts with.
  * st.session_state["dra_lang"] — the live value for this browser session,
    seeded from the persisted one on the first run of the script.

The selector writes both: session_state so the page redraws immediately, and
.env so the choice survives a restart. It uses config.set_env_value rather than
ui.service.save_multiple_env because that helper also calls config.reload() and
drops the cached LLM provider, and changing the interface language has no
business rebuilding an LLM client.
"""

import streamlit as st

from defect_risk_analyzer import config
from defect_risk_analyzer.ui import i18n

#: Session key holding the live language. Shared by the sidebar selector and
#: the wizard's, which is safe because only one of them renders per script run:
#: bootstrap() calls st.stop() inside the wizard branch, before the sidebar.
SESSION_KEY = "dra_lang"

#: The .env key config reads. Prefixed like DRA_BASE_DIR — this is our setting,
#: not a standard one, and LANG/LANGUAGE are already claimed by the OS.
ENV_KEY = "DRA_LANGUAGE"


def apply() -> str:
    """Make this session's language active for i18n. Returns what was set.

    Called by bootstrap() on every script run, before anything renders. The
    round trip through i18n.set_language() is what normalises an unknown code:
    a hand-edited .env saying DRA_LANGUAGE=de leaves i18n on the source
    language, and writing the result back keeps session_state agreeing with it
    so the selector below can still find its own value in the options list.
    """
    requested = st.session_state.get(SESSION_KEY, config.LANGUAGE)
    active = i18n.set_language(requested)
    st.session_state[SESSION_KEY] = active
    return active


def render_selector(container=st) -> None:
    """Draw the language picker into `container` (st, or st.sidebar)."""
    container.selectbox(
        i18n.t("sidebar.language"),
        options=list(i18n.LANGUAGES),
        format_func=lambda code: i18n.LANGUAGES[code],
        key=SESSION_KEY,
        on_change=_persist,
    )


def _persist() -> None:
    """Write the newly chosen language to .env.

    Runs as a widget callback, so it fires only on an actual change — merely
    opening a page never writes, which is the same rule the Settings page
    follows for API key generation.
    """
    config.set_env_value(ENV_KEY, st.session_state[SESSION_KEY])
