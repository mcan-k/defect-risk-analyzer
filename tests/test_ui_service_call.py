"""`ui.service.call()` — the dashboard's error boundary, one test per branch.

Every page routes its service calls through `call()`, and its contract is the
one the old `api_request()` had: the caller checks `if not result:` and never
sees a traceback. Until 6E-2 PR3 none of its except branches ran under test
(KNOWN-DEBT, "6E keşfinde bulunan küçük test boşlukları"). This file pins each
branch: which message key the user sees, that the result is None, and — for
the two branches that call `logger.exception` — that the log keeps the detail.

`st` is replaced in the module under test, not in streamlit itself, so the
recorded calls are exactly the ones `call()` made. The language is pinned to
Turkish and the expected text comes from `t()`, so a wrong key fails here
while a reworded sentence does not.

The OSError branch (K-E4, 6E-2 PR3) is the one new behaviour: a `.env` that
cannot be written used to reach the user as a raw traceback, because the five
settings saves did not go through `call()` at all. Its message carries no
detail on purpose — an OSError's text usually names the path, and a path under
the user's home directory names the account.
"""

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from defect_risk_analyzer.jira_client import JiraFetchError
from defect_risk_analyzer.llm_provider import LLMError, RateLimitError
from defect_risk_analyzer.services.analysis_service import BugNotFoundError
from defect_risk_analyzer.ui import i18n
from defect_risk_analyzer.ui import service as ui_service
from defect_risk_analyzer.ui.i18n import t

LOCALES = Path(ui_service.__file__).resolve().parent / "locales"

# A path shaped like the real one, with a stand-in for the account name. Not a
# real directory: nothing here touches the disk.
FAKE_ENV_PATH = "C:/Users/hesap-adi-ornegi/defect-risk-analyzer/.env"


@pytest.fixture
def shown(monkeypatch):
    """Every st.error call() makes, in order."""
    errors: list[str] = []
    monkeypatch.setattr(ui_service, "st", SimpleNamespace(error=errors.append))
    monkeypatch.setattr(i18n, "_active", "tr")
    return errors


def _raising(exc: BaseException):
    def service_call(*args, **kwargs):
        raise exc

    return service_call


def test_a_successful_call_returns_the_value_and_shows_nothing(shown):
    seen = {}

    def service_call(*args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        return {"ok": 1}

    result = ui_service.call(service_call, "AP-1", query="login")

    assert result == {"ok": 1}
    assert seen == {"args": ("AP-1",), "kwargs": {"query": "login"}}
    assert shown == []


def test_a_rate_limit_is_reported_as_the_quota_message(shown):
    """RateLimitError does not derive from LLMError, so it has its own branch."""
    result = ui_service.call(_raising(RateLimitError("daily limit")))

    assert result is None
    assert shown == [t("error.quota", detail="daily limit")]


def test_an_llm_error_is_reported_as_the_llm_message(shown):
    result = ui_service.call(_raising(LLMError("model unavailable")))

    assert result is None
    assert shown == [t("error.llm", detail="model unavailable")]


def test_a_missing_bug_is_reported_plainly(shown):
    exc = BugNotFoundError("AP-404")

    result = ui_service.call(_raising(exc))

    assert result is None
    assert shown == [t("error.plain", detail=exc)]
    assert "AP-404" in shown[0]


def test_a_value_error_is_reported_plainly(shown):
    result = ui_service.call(_raising(ValueError("bug_key or query is required")))

    assert result is None
    assert shown == [t("error.plain", detail="bug_key or query is required")]


def test_anything_else_is_reported_as_unexpected_and_logged(shown, caplog):
    def service_call():
        raise RuntimeError("index is gone")

    with caplog.at_level(logging.ERROR, logger=ui_service.__name__):
        result = ui_service.call(service_call)

    assert result is None
    assert shown == [t("error.unexpected", detail="index is gone")]
    assert "service_call" in caplog.text
    assert caplog.records[-1].exc_info is not None


@pytest.mark.parametrize(
    "exc",
    [
        OSError(28, "No space left on device"),
        PermissionError(13, "Permission denied", FAKE_ENV_PATH),
    ],
    ids=["oserror", "permissionerror"],
)
def test_an_oserror_is_reported_without_its_text_and_logged(shown, caplog, exc):
    def save_settings():
        raise exc

    with caplog.at_level(logging.ERROR, logger=ui_service.__name__):
        result = ui_service.call(save_settings)

    assert result is None
    assert shown == [t("error.os")]
    # The exception's own text — and with it the path — stays off the screen…
    assert str(exc) not in shown[0]
    assert "hesap-adi-ornegi" not in shown[0]
    # …and goes to the log instead, traceback included.
    assert "save_settings" in caplog.text
    assert str(exc) in caplog.text
    assert caplog.records[-1].exc_info is not None


def test_a_failed_jira_fetch_says_the_data_was_kept_and_is_logged(shown, caplog):
    """6E-2 PR5 (K1/K2): its own message, not the disk-error one. JiraFetchError
    is not an OSError on purpose — the request error it chains is."""
    exc = JiraFetchError(2)

    def refresh():
        raise exc

    with caplog.at_level(logging.ERROR, logger=ui_service.__name__):
        result = ui_service.call(refresh)

    assert result is None
    assert shown == [t("error.jira_fetch")]
    assert str(exc) not in shown[0]
    assert "refresh" in caplog.text
    assert str(exc) in caplog.text
    assert caplog.records[-1].exc_info is not None


@pytest.mark.parametrize("language", ["tr", "en"])
def test_the_jira_fetch_message_has_no_placeholder(language):
    """No `{detail}`: the request error behind it can name the Jira host."""
    catalog = json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))

    message = catalog["error.jira_fetch"]

    assert message.strip()
    assert "{" not in message and "}" not in message


@pytest.mark.parametrize("language", ["tr", "en"])
def test_the_oserror_message_has_no_placeholder(language):
    """A `{detail}` slot here would be the path leak the branch exists to avoid."""
    catalog = json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))

    message = catalog["error.os"]

    assert message.strip()
    assert "{" not in message and "}" not in message
