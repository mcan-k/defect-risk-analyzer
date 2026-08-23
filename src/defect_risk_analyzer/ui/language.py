"""The Streamlit binding for i18n: where the active language comes from.

Separate from i18n.py, which deliberately knows nothing about Streamlit so the
locale contract stays testable without a script context. Everything that needs
st.session_state or writes to .env lives here instead.

Both shell.py and setup_wizard.py draw the selector, which is why this is its
own module rather than a function in shell.py: shell.py imports setup_wizard.py
to run the first-run gate, so the reverse import would be a real cycle.

Two layers hold the language, on purpose:

  * config.LANGUAGE — the persisted choice, read from .env at startup exactly
    like USE_MOCK_DATA. It is what sample_bugs_file() picks the demo set from.
  * st.session_state["dra_lang"] — the live value for this browser session,
    seeded from the persisted one on the first run of the script.

The selector writes both, through config.persist_language: session_state so
the page redraws immediately, .env so the choice survives a restart, and
config.LANGUAGE so the next explicit sync loads the matching demo set. That
last one used to be missing, which made the sync half of the Faz 5C promise a
no-op — the demo data stayed on whatever language the process booted with.

It uses config.persist_language rather than ui.service.save_multiple_env
because that helper also calls config.reload() and drops the cached LLM
provider, and changing the interface language has no business rebuilding an
LLM client or re-reading Jira credentials.
"""

import streamlit as st

from defect_risk_analyzer import config
from defect_risk_analyzer.ui import i18n

#: Session key holding the live language. Shared by the sidebar selector and
#: the wizard's, which is safe because only one of them renders per script run:
#: bootstrap() calls st.stop() inside the wizard branch, before the sidebar.
SESSION_KEY = "dra_lang"

# The .env key itself (DRA_LANGUAGE) is not named here any more: config both
# reads and writes it now, so a copy on this side could only ever drift.


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
    """Draw the language picker into `container` (st, or st.sidebar).

    The help text tells the user what to DO, not what happened: the interface
    switches at once but the demo bugs do not, and without a sentence saying so
    the only way to learn it is to sync and wonder why the text did not change.

    Two sentences rather than one, because the honest answer depends on the
    mode. Under mock data the demo set follows on the next sync; against a real
    Jira the bug text comes from Jira and the language never touches it, so a
    single "the data updates" line would promise something that cannot happen.
    config.USE_MOCK_DATA is safe to read live here — the Settings page saves it
    through save_multiple_env, which reloads.

    Two literal t() calls, not t() on a computed key: a computed key would need
    an entry in test_i18n_locales.DYNAMIC_PREFIXES, which exists to excuse keys
    that no literal call site names — and these two have one.
    """
    if config.USE_MOCK_DATA:
        help_text = i18n.t("sidebar.language.help.mock", action=i18n.t("sidebar.sync"))
    else:
        help_text = i18n.t("sidebar.language.help.jira")

    container.selectbox(
        i18n.t("sidebar.language"),
        options=list(i18n.LANGUAGES),
        format_func=lambda code: i18n.LANGUAGES[code],
        key=SESSION_KEY,
        on_change=_persist,
        help=help_text,
    )


def _persist() -> None:
    """Write the newly chosen language to .env and to config.LANGUAGE.

    Runs as a widget callback, so it fires only on an actual change — merely
    opening a page never writes, which is the same rule the Settings page
    follows for API key generation.

    Not config.set_env_value: that updates the file and os.environ but leaves
    the module global behind, and config.init() is guarded so it never catches
    up. See config.persist_language.
    """
    config.persist_language(st.session_state[SESSION_KEY])
