"""
Credential storage — the OS keyring when there is one, `.env` when there is not.

TWO LAYERS, AND THE USER IS TOLD WHICH. `resolve_store()` returns a store or
`None`, plus a description of what was decided. `None` is not a failure: an
install without the `desktop` extra is supported, and so is a desktop whose
keyring cannot resolve a backend. The caller falls back to `.env` and reports
the description; the migration that empties `.env` does not run in that case,
and the credential stays there in plain text. That is the intended behaviour —
see SECURITY.md, which scopes the guarantee to the layer that is actually in
use.

WHY THE IMPORT IS INSIDE THE FUNCTION. `keyring` ships in the `desktop` extra,
never in `requirements.txt`: on Linux it requires SecretStorage and jeepney,
and neither can work in `python:3.11-slim` or on a headless CI runner, where
credentials arrive as environment variables anyway (`docker-compose.yml` passes
`.env` with `env_file`). CI installs `requirements-dev.txt`, so the library is
absent there. A module-level import would make this file unimportable on the
runner.

WHY THE DECISION IS SPLIT OUT. `_decide()` takes the keyring module as an
argument and touches nothing else, so every branch is reachable in a test with
a stand-in — including on a machine that has keyring installed, where a test
that resolved for real would write to the developer's own credential store.

HOW THE LAYER IS CHOSEN — measured, not assumed. `keyring.core._detect_backend`
never raises: when nothing viable is installed it returns
`keyring.backends.fail.Keyring`, whose `priority` is 0, and the error only
arrives on the first get or set. So the question is asked with
`core.recommended()` (priority >= 1) before any operation, rather than by
trying one and catching what comes back.

The resolved backend is REPORTED, never assumed. `PYTHON_KEYRING_BACKEND` and
`keyringrc.cfg` both override the choice ahead of priority, so "the desktop uses
the OS credential store" is not a claim this project can make at install time.

SIZE LIMIT, measured on Windows: `CredWrite` accepts a credential blob of at
most 2560 bytes, which is 1280 characters (UTF-16, no BOM); 1281 fails with
`(1783, 'CredWrite', ...)`. The longest secret this project stores is a Jira
API token at 192 characters, so the limit is recorded rather than enforced.
"""

import logging
from typing import Protocol

logger = logging.getLogger(__name__)

# One credential per key, rather than one target carrying several usernames.
# WinVaultKeyring simulates multi-user support by moving a colliding entry to
# `{username}@{service}`; a distinct service name per key means that path is
# never entered, so what lands in the OS credential manager is what someone
# reading it would expect to find.
_SERVICE_PREFIX = "defect-risk-analyzer"

# Never empty. Measured on Windows: `set_password` accepts an empty username,
# the OS then stores `UserName` as None, and `delete_password` compares it
# against "" and never matches — the credential becomes unremovable through the
# public API. One orphan was created that way during the Faz 6B measurement run.
_USERNAME = "defect-risk-analyzer"

# Which layer is in use, as a CODE rather than a sentence. This module is an
# adapter: it must not know about locales, message keys or wording, and a
# sentence built here cannot be translated by anything downstream — the string
# is already interpolated by the time `ui/` sees it.
#
# The same lesson, for the fourth time. 5A moved blind-spot wording out of the
# detector for exactly this reason, 5C moved pattern wording after it, and 6B
# reintroduced it here. `ui/messages.py` renders these codes.
#
# `query_failed` is deliberately NOT folded into `unusable_backend`. They say
# different things and the reader does different things about them: an unusable
# backend is a defined state with a defined fix (install or configure one),
# while a failed query is unexpected and the fix starts with reading the error.
LAYER_NO_KEYRING = "no_keyring"
LAYER_UNUSABLE_BACKEND = "unusable_backend"
LAYER_STORE_ACTIVE = "store_active"
LAYER_QUERY_FAILED = "query_failed"


class SecretStore(Protocol):
    """What the rest of the application may ask of a credential store."""

    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> bool: ...

    def delete(self, name: str) -> bool: ...


def _service(name: str) -> str:
    return f"{_SERVICE_PREFIX}:{name}"


def _backend_name(backend: object) -> str:
    return f"{type(backend).__module__}.{type(backend).__name__}"


def _describe(exc: Exception, secret: str | None = None) -> str:
    """The exception's type and message, unless the message quotes the secret.

    The type and the message are what make a failure diagnosable, and this
    project's own code never passes a credential to a logging call. But the
    message belongs to the backend, not to us: one that echoed the value back
    would put it in the log through `str(exc)`. The value is in scope at exactly
    that moment, so it can be checked for — and it is checked rather than
    trusted, because "backends do not do that" is an assumption and this is not
    the file to make assumptions in.
    """
    text = f"{type(exc).__name__}: {exc}"
    if secret and secret in text:
        return f"{type(exc).__name__}: <message withheld: it quoted the value>"
    return text


class KeyringStore:
    """A `SecretStore` backed by the OS credential manager.

    EVERY OPERATION CATCHES `Exception`, deliberately.
    `keyring.errors.KeyringError` is not enough: measured on Windows, a
    `CredRead`/`CredWrite` failure arrives as a raw `pywin32ctypes` error that
    never passes through keyring's own hierarchy. Naming that type would mean
    importing `win32ctypes`, which does not exist on Linux and would make this
    adapter platform-specific. The contract here is "return the secret or say
    you could not", and at that boundary catching broadly is the right altitude.
    `KeyboardInterrupt` and `SystemExit` derive from `BaseException` and are
    still not caught.
    """

    def __init__(self, keyring_module: object, backend: str) -> None:
        self._keyring = keyring_module
        self.backend = backend

    def get(self, name: str) -> str | None:
        try:
            return self._keyring.get_password(_service(name), _USERNAME)
        except Exception as exc:
            logger.warning("Could not read %s from the credential store. %s",
                           name, _describe(exc))
            return None

    def set(self, name: str, value: str) -> bool:
        try:
            self._keyring.set_password(_service(name), _USERNAME, value)
        except Exception as exc:
            logger.warning("Could not store %s in the credential store. %s",
                           name, _describe(exc, value))
            return False
        return True

    def delete(self, name: str) -> bool:
        """Remove a stored credential. Absent is success, not an error.

        `delete_password` is not idempotent — the real backend raises when there
        is nothing to delete — and the exception type that means "absent" cannot
        be named here without importing `keyring.errors`. So a failure is
        resolved by asking: if the value can no longer be read, it is gone.
        """
        try:
            self._keyring.delete_password(_service(name), _USERNAME)
            return True
        except Exception as exc:
            if self.get(name) is None:
                return True
            logger.warning("Could not delete %s from the credential store. %s",
                           name, _describe(exc))
            return False


def _decide(keyring_module: object | None) -> tuple[SecretStore | None, str, dict]:
    """Choose the credential layer. Pure: the module comes in as an argument.

    Returns `(store, code, params)`. The code names the layer and the params
    carry what a sentence needs — today only `backend`, which is an identifier
    and is never translated. Rendering happens in `ui/messages.py`; nothing
    here knows a locale exists.
    """
    if keyring_module is None:
        return None, LAYER_NO_KEYRING, {}

    try:
        backend = keyring_module.get_keyring()
        name = _backend_name(backend)

        if not keyring_module.core.recommended(backend):
            return None, LAYER_UNUSABLE_BACKEND, {"backend": name}

        return KeyringStore(keyring_module, name), LAYER_STORE_ACTIVE, {"backend": name}
    except Exception as exc:
        # The TYPE only. The message belongs to the backend, and these params
        # are rendered on screen — a backend that quoted a credential back
        # would put it in front of the user. `_describe` withholds a message
        # that quotes a known value; here no value is even in scope to compare
        # against, so the message is dropped outright rather than filtered.
        logger.warning("keyring could not be queried. %s", _describe(exc))
        return None, LAYER_QUERY_FAILED, {"error": type(exc).__name__}


def resolve_store() -> tuple[SecretStore | None, str, dict]:
    """The layer this process will use, decided now and described.

    Not called from any test — a test that resolved for real would reach the
    developer's own credential store on any machine where keyring is installed,
    which is every machine this feature is for. `tests/test_secrets_adapter.py`
    asserts that `keyring` never enters `sys.modules` during the run.
    """
    try:
        import keyring
        import keyring.core  # noqa: F401  (attribute access below needs it bound)
    except ImportError:
        return _decide(None)

    return _decide(keyring)
