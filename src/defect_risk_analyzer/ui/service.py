"""
The analysis service handle every page shares, plus the error boundary.

get_service is @st.cache_resource, which is keyed by function identity and
lives for the whole process. That is why it is defined here exactly once: a
copy per page would mean a separate cache entry per page, each with its own
empty bug list.
"""

import logging

import streamlit as st

from defect_risk_analyzer import config
from defect_risk_analyzer.jira_client import load_bugs_from_file
from defect_risk_analyzer.llm_provider import LLMError, RateLimitError
from defect_risk_analyzer.services.analysis_service import (
    AnalysisService,
    BugNotFoundError,
)
from defect_risk_analyzer.ui.i18n import t

logger = logging.getLogger(__name__)


def save_multiple_env(values: dict[str, str]) -> None:
    """Save settings, and apply them to the running service.

    CREDENTIALS FOLLOW THE LAYER, everything else goes to `.env`. Without that
    split the first save after a migration would put the secret straight back
    into plain text: `config._get_secret` lets a non-empty `.env` win, so a
    credential written to the file would shadow the one in the store and the
    migration would be undone by the user's next visit to this page.

    `save_secret` falls back to `.env` when there is no store, which is the same
    thing `set_env_value` did before — so on Docker, on CI, and on a desktop
    without the extra this path is unchanged.
    """
    for key, value in values.items():
        if key in config.STORED_SECRET_KEYS:
            config.save_secret(key, value)
        else:
            config.set_env_value(key, value)
    # The one place a re-read is still needed: .env just changed underneath us.
    config.reload()
    # The service holds a provider built from the old credentials; drop it so
    # the next analysis picks up what was just saved.
    get_service().reset_llm()

@st.cache_resource(show_spinner="Analiz servisi hazırlanıyor...")
def get_service() -> AnalysisService:
    """
    Return the process-wide analysis service, loading bug data on first use.

    Cached with @st.cache_resource deliberately: Streamlit re-executes this
    module top-to-bottom on every interaction, and a fresh AnalysisService per
    rerun would start with an empty bug list. Nothing would raise — every page
    would just quietly report "no data".
    """
    service = AnalysisService()

    bugs = load_bugs_from_file()
    if bugs:
        service.load_bugs(bugs)
        logger.info("Dashboard loaded %d bugs into the analysis service.", len(bugs))
    else:
        logger.warning("No bug data found. Use the sidebar sync button or mock mode.")

    return service

def call(fn, *args, **kwargs):
    """
    Run a service call, reporting failures inline instead of raising.

    Preserves the contract the old api_request() had: callers check the result
    with `if not result:` and never see a traceback. Without this, an exception
    from the service would surface as a raw Streamlit traceback.
    """
    try:
        return fn(*args, **kwargs)
    except RateLimitError as e:
        st.error(t("error.quota", detail=e))
    except LLMError as e:
        st.error(t("error.llm", detail=e))
    except BugNotFoundError as e:
        st.error(t("error.plain", detail=e))
    except ValueError as e:
        st.error(t("error.plain", detail=e))
    except Exception as e:
        logger.exception("Service call %s failed", getattr(fn, "__name__", fn))
        st.error(t("error.unexpected", detail=e))
    return None

def get_status() -> dict:
    """Local status for the sidebar — no HTTP, no backend process."""
    service = get_service()
    return {
        "bugs_loaded": len(service.get_bugs()),
        "daily_requests_used": service.get_daily_request_count(),
        "daily_requests_limit": config.MAX_DAILY_REQUESTS,
        "mock_mode": config.USE_MOCK_DATA,
    }
