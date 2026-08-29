"""Which credential layer is in use, and what happens when it is not there.

WRITTEN BEFORE THE FIX (Faz 6B, Adım 5). The first run of this file fails at
COLLECTION, because `adapters/secrets.py` does not exist yet. That red carries
no claim — it says "the module is missing", not "the rule is broken", and for a
brand-new module there is no way to route around it the way the anonymizer
tests routed around `session()`. The reds that carry the rules are the mutations
recorded in the commit message, run once the module is there.

NOTHING HERE IMPORTS `keyring`, AND THAT IS THE POINT.

CI installs `requirements-dev.txt` only, so keyring is absent on the runner —
it ships in the `desktop` extra, because on Linux it drags in SecretStorage and
jeepney, neither of which can work in `python:3.11-slim` or on a headless
runner. Two consequences shaped this file:

  * `resolve_store()` imports keyring INSIDE the function. A module-level
    import would make `adapters/secrets.py` unimportable on the runner.
  * The decision is split into `_decide(keyring_module)`, which is pure. Tests
    hand it a stand-in, so all three paths — installed and working, installed
    but resolving to `fail.Keyring`, not installed at all — are reachable
    without the library and without touching a real credential store.

That last point is not only about CI. The Faz 6B measurement run created an
orphan credential in the real Windows store (an empty username, which
`delete_password` then could not match), and this design makes that class
impossible: no test ever reaches the OS.

NO REAL SECRETS. Every value here is synthetic.
"""

import ast
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from defect_risk_analyzer.adapters import secrets as secrets_adapter

SYNTHETIC = "synthetic-not-a-secret-0000"


# ---------------------------------------------------------------------------
# Stand-ins for the keyring package. None of this touches the real library.
# ---------------------------------------------------------------------------

class WinVaultKeyring:
    """A backend that works. Named and located like the real one so the
    reported string is exactly what a user would see."""


WinVaultKeyring.__module__ = "keyring.backends.Windows"


class Keyring:
    """The no-op backend keyring resolves to when nothing else is viable."""


Keyring.__module__ = "keyring.backends.fail"


class FakeKeyring:
    """Stands in for the `keyring` module. Records what it was asked to do."""

    def __init__(self, backend, *, recommended=True, raises=None, resolve_raises=None):
        self._backend = backend
        self._raises = raises
        self._resolve_raises = resolve_raises
        self.stored: dict[tuple[str, str], str] = {}
        self.deleted: list[tuple[str, str]] = []
        self.core = SimpleNamespace(recommended=lambda kr: recommended)

    def get_keyring(self):
        # Can raise: _decide wraps this in `except Exception`, and until Faz 6B's
        # i18n fix that branch had no test at all.
        if self._resolve_raises is not None:
            raise self._resolve_raises
        return self._backend

    def set_password(self, service, username, password):
        if self._raises is not None:
            raise self._raises
        self.stored[(service, username)] = password

    def get_password(self, service, username):
        if self._raises is not None:
            raise self._raises
        return self.stored.get((service, username))

    def delete_password(self, service, username):
        if self._raises is not None:
            raise self._raises
        if (service, username) not in self.stored:
            # The real WinVaultKeyring raises here rather than passing; the
            # adapter has to absorb that, so the stand-in reproduces it.
            raise RuntimeError(f"no such password: {service}")
        del self.stored[(service, username)]
        self.deleted.append((service, username))


# ---------------------------------------------------------------------------
# _decide — the three layers
# ---------------------------------------------------------------------------

def test_no_keyring_installed_falls_back():
    """EXPECTED RED (module absent), then GREEN.

    `_decide(None)` is the ImportError path. It must not raise: an install
    without the desktop extra is a supported configuration, not an error.
    """
    store, code, params = secrets_adapter._decide(None)

    assert store is None
    assert code == secrets_adapter.LAYER_NO_KEYRING
    assert params == {}


def test_an_unusable_backend_falls_back():
    """The `fail.Keyring` path.

    Measured in the keyring source: `_detect_backend` never raises. When
    nothing viable is installed it returns `fail.Keyring`, whose priority is 0,
    and the error only arrives on the first get/set. So the decision is made
    from `core.recommended()` — priority >= 1 — and never by attempting an
    operation and catching what comes back.
    """
    fake = FakeKeyring(Keyring(), recommended=False)

    store, code, params = secrets_adapter._decide(fake)

    assert store is None
    assert code == secrets_adapter.LAYER_UNUSABLE_BACKEND
    assert params["backend"] == "keyring.backends.fail.Keyring", (
        "the resolved backend must be named, not just reported as unusable"
    )


def test_a_working_backend_is_used_and_named():
    """The resolved backend is REPORTED, never assumed.

    `PYTHON_KEYRING_BACKEND` and `keyringrc.cfg` both override the choice ahead
    of priority (measured in `keyring.core._detect_backend`), so "the desktop
    uses the OS credential store" is not something this project may state at
    install time. It states what actually resolved, at run time.
    """
    fake = FakeKeyring(WinVaultKeyring())

    store, code, params = secrets_adapter._decide(fake)

    assert store is not None
    assert code == secrets_adapter.LAYER_STORE_ACTIVE
    assert params["backend"] == "keyring.backends.Windows.WinVaultKeyring"


def test_the_layer_codes_are_distinct():
    """The code is a CONTRACT, and the four layers must be told apart by it.

    Was `test_the_three_descriptions_are_distinct`, and it pinned the SENTENCES
    — which is what let Faz 6B ship English prose into a Turkish page and still
    pass. Pinning codes is strictly stronger: the same mutation dies (return one
    constant and this goes red while the path tests stay green), and rewording a
    message no longer breaks a test that was never about wording.
    """
    codes = {
        secrets_adapter._decide(None)[1],
        secrets_adapter._decide(FakeKeyring(Keyring(), recommended=False))[1],
        secrets_adapter._decide(FakeKeyring(WinVaultKeyring()))[1],
        secrets_adapter._decide(
            FakeKeyring(WinVaultKeyring(), resolve_raises=RuntimeError("boom"))
        )[1],
    }

    assert len(codes) == 4, f"the layers are indistinguishable: {codes}"
    assert codes == {
        secrets_adapter.LAYER_NO_KEYRING,
        secrets_adapter.LAYER_UNUSABLE_BACKEND,
        secrets_adapter.LAYER_STORE_ACTIVE,
        secrets_adapter.LAYER_QUERY_FAILED,
    }


def test_the_query_failed_branch_reports_its_own_code():
    """`_decide`'s `except Exception` branch had NO test before this change.

    Kept separate from `unusable_backend` deliberately. They say different
    things and the reader does different things about them: an unusable backend
    is a defined state with a defined fix (install or configure one), while a
    failed query is unexpected and the fix starts with reading the error. Folding
    them would hand both readers the wrong instruction.
    """
    fake = FakeKeyring(WinVaultKeyring(), resolve_raises=RuntimeError("dbus is gone"))

    store, code, params = secrets_adapter._decide(fake)

    assert store is None
    assert code == secrets_adapter.LAYER_QUERY_FAILED
    assert params["error"] == "RuntimeError"


def test_a_failed_query_does_not_leak_the_message(caplog):
    """The params reach the SCREEN, so only the exception type may travel.

    A backend that quoted a credential back would otherwise put it in front of
    the user. The log keeps the message — `_describe` withholds it if it quotes
    a known value — but the rendered params never carry it.
    """
    secret = "synthetic-not-a-secret-9999"
    fake = FakeKeyring(
        WinVaultKeyring(),
        resolve_raises=RuntimeError(f"cannot open vault for {secret}"),
    )

    with caplog.at_level(logging.WARNING):
        _store, code, params = secrets_adapter._decide(fake)

    assert code == secrets_adapter.LAYER_QUERY_FAILED
    assert params == {"error": "RuntimeError"}
    assert secret not in str(params), "the exception message reached the rendered params"


def test_the_description_is_not_rebuilt_from_operation_errors():
    """The user-facing string must not become a channel for backend error text.

    It is decided once, before any operation, from the backend's type name — so
    there is no path by which a secret could enter it. Pinned because the
    tempting change is to append "last error" to it for the Settings page, and
    that error is exactly the text the log has to withhold.
    """
    fake = FakeKeyring(
        WinVaultKeyring(),
        raises=RuntimeError(f"rejected value {SYNTHETIC} for target"),
    )
    store, _code, params = secrets_adapter._decide(fake)

    store.set("JIRA_API_TOKEN", SYNTHETIC)
    store.get("JIRA_API_TOKEN")

    assert SYNTHETIC not in str(params)
    assert SYNTHETIC not in store.backend
    assert store.backend == "keyring.backends.Windows.WinVaultKeyring"


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def test_a_value_round_trips():
    fake = FakeKeyring(WinVaultKeyring())
    store, _, _ = secrets_adapter._decide(fake)

    assert store.set("JIRA_API_TOKEN", SYNTHETIC) is True
    assert store.get("JIRA_API_TOKEN") == SYNTHETIC


def test_the_username_is_never_empty():
    """Measured on Windows: `set_password` accepts an empty username, the OS
    stores `UserName` as None, and `delete_password` then cannot match it — the
    credential becomes unremovable through the public API. One orphan was
    created that way during the Faz 6B measurement run and had to be removed
    through a private method.
    """
    fake = FakeKeyring(WinVaultKeyring())
    store, _, _ = secrets_adapter._decide(fake)

    store.set("JIRA_API_TOKEN", SYNTHETIC)

    assert fake.stored, "nothing was stored"
    for service, username in fake.stored:
        assert username, f"empty username for {service}"
        assert service


def test_deleting_something_absent_is_not_an_error():
    """`delete_password` is not idempotent — the real backend raises when there
    is nothing to delete. The migration runs this on files it has never seen,
    so the adapter absorbs it."""
    fake = FakeKeyring(WinVaultKeyring())
    store, _, _ = secrets_adapter._decide(fake)

    assert store.delete("NEVER_STORED") is True


def test_a_backend_failure_is_reported_not_raised():
    """`keyring.errors.KeyringError` is not enough, measured: on Windows a
    CredRead/CredWrite failure arrives as a raw `pywin32ctypes` error that never
    passes through keyring's own hierarchy. Naming it would mean importing
    `win32ctypes`, which does not exist on Linux. So the adapter catches broadly
    and reports — its contract is "return the secret or say you could not"."""
    fake = FakeKeyring(WinVaultKeyring(), raises=RuntimeError("credential store is locked"))
    store, _, _ = secrets_adapter._decide(fake)

    assert store.get("JIRA_API_TOKEN") is None
    assert store.set("JIRA_API_TOKEN", SYNTHETIC) is False


# ---------------------------------------------------------------------------
# What reaches the log
# ---------------------------------------------------------------------------

def test_a_failure_logs_the_type_and_the_message(caplog):
    fake = FakeKeyring(WinVaultKeyring(), raises=RuntimeError("credential store is locked"))
    store, _, _ = secrets_adapter._decide(fake)

    with caplog.at_level(logging.WARNING):
        store.set("JIRA_API_TOKEN", SYNTHETIC)

    text = caplog.text
    assert "RuntimeError" in text
    assert "credential store is locked" in text
    assert SYNTHETIC not in text, "the value reached the log"


def test_a_message_containing_the_secret_is_withheld(caplog):
    """The one case where logging the exception text would leak.

    We control our own log call and never pass the value to it — but the
    provider's message is not ours, and a backend that echoed the credential
    back would put it in the log by way of `str(exc)`. Since the value is in
    scope at exactly that moment, it can be checked for, and this is the test
    that keeps the check honest rather than decorative.
    """
    fake = FakeKeyring(
        WinVaultKeyring(),
        raises=RuntimeError(f"rejected value {SYNTHETIC} for target"),
    )
    store, _, _ = secrets_adapter._decide(fake)

    with caplog.at_level(logging.WARNING):
        store.set("JIRA_API_TOKEN", SYNTHETIC)

    text = caplog.text
    assert SYNTHETIC not in text, "the value reached the log through the exception"
    assert "RuntimeError" in text, "the exception type is still useful and must survive"


# ---------------------------------------------------------------------------
# The audit
# ---------------------------------------------------------------------------

def test_the_sandbox_refuses_to_import_keyring():
    """The credential-store half of the sandbox promise, asserted directly.

    `conftest._KeyringBlocker` refuses the import for the whole session, so
    `resolve_store()` cannot reach a real backend no matter which test calls it
    or how it was imported. On this machine and in CI the import would fail
    anyway — keyring is absent — so what this pins is the guard, not the
    absence: it must raise the SANDBOX error, not a plain ModuleNotFoundError.
    """
    with pytest.raises(ImportError) as caught:
        import keyring  # noqa: F401

    assert "SANDBOX" in str(caught.value), (
        "keyring was refused, but by the environment rather than by the sandbox "
        "guard — on a machine that has it installed, nothing would have stopped it"
    )


def test_resolve_store_finds_nothing_under_the_sandbox():
    """The consequence: the one production entry point resolves to no store.

    This is the call `bootstrap()`'s migration will make. Under the blocker it
    falls to the ImportError path, so no test can migrate a credential into the
    developer's own credential manager.
    """
    store, code, _params = secrets_adapter.resolve_store()

    assert store is None
    assert code == secrets_adapter.LAYER_NO_KEYRING


def test_this_suite_never_imports_keyring():
    """The guarantee that no test in this file reached a real credential store.

    WHAT THIS MEASURES CHANGED when the sandbox gained `_KeyringBlocker`. It used
    to rest on a convention — no test calls `resolve_store()` — and the mutation
    that killed it was to add such a call. One now exists
    (`test_resolve_store_finds_nothing_under_the_sandbox`), deliberately, and
    this still passes: the blocker refuses the import, so the call falls to the
    ImportError path and nothing is recorded in `sys.modules`.

    So it no longer pins a convention, it pins the blocker's effect — and it is
    the assertion that would catch a blocker which stopped working while every
    other test went on passing. Remove the blocker from conftest and this goes
    red on any machine that has keyring installed, which is every desktop this
    feature is FOR.
    """
    assert "keyring" not in sys.modules


@pytest.mark.parametrize("name", ["JIRA_API_TOKEN", "GROQ_API_KEY", "API_KEY"])
def test_every_migrated_key_gets_its_own_target(name):
    """One credential per key, rather than one target with several usernames.

    WinVaultKeyring simulates multi-user support by moving a colliding entry to
    `{username}@{service}` (measured in its source). Giving each key its own
    service name means that path is never entered, so what is stored is what a
    reader of the OS credential manager would expect to find.
    """
    fake = FakeKeyring(WinVaultKeyring())
    store, _, _ = secrets_adapter._decide(fake)

    store.set(name, SYNTHETIC)

    services = {service for service, _ in fake.stored}
    assert len(services) == 1
    assert name in next(iter(services))


# ---------------------------------------------------------------------------
# The import direction, checked rather than asserted in a comment
# ---------------------------------------------------------------------------

def test_the_adapter_never_imports_config():
    """`config` imports this module; this module must never import `config`.

    THE DIRECTION IS LOAD-BEARING. `config.reload()` asks this adapter for a
    credential when `.env` has none, which makes `config -> adapters.secrets` a
    real edge. `adapters.results_repository` and `adapters.vector_store` both
    import `config`, so the reverse edge from HERE would close a cycle — and the
    migration logic lives in `config.py` for exactly this reason rather than
    being pushed down into the adapter where it would otherwise belong.

    A comment saying so is what this replaces. Read with `ast` rather than
    imported, so it reports the offending line instead of an ImportError.
    """
    source = Path(secrets_adapter.__file__).read_text(encoding="utf-8")

    offenders = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] == "config":
                    offenders.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[-1] == "config":
                offenders.append(f"line {node.lineno}: from {module} import ...")
            if any(alias.name == "config" for alias in node.names):
                offenders.append(f"line {node.lineno}: from {module} import config")

    assert not offenders, (
        f"adapters/secrets.py imports config, which closes a cycle: {offenders}"
    )
