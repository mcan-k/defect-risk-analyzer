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

import logging
import sys
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

    def __init__(self, backend, *, recommended=True, raises=None):
        self._backend = backend
        self._raises = raises
        self.stored: dict[tuple[str, str], str] = {}
        self.deleted: list[tuple[str, str]] = []
        self.core = SimpleNamespace(recommended=lambda kr: recommended)

    def get_keyring(self):
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
    store, description = secrets_adapter._decide(None)

    assert store is None
    assert description


def test_an_unusable_backend_falls_back():
    """The `fail.Keyring` path.

    Measured in the keyring source: `_detect_backend` never raises. When
    nothing viable is installed it returns `fail.Keyring`, whose priority is 0,
    and the error only arrives on the first get/set. So the decision is made
    from `core.recommended()` — priority >= 1 — and never by attempting an
    operation and catching what comes back.
    """
    fake = FakeKeyring(Keyring(), recommended=False)

    store, description = secrets_adapter._decide(fake)

    assert store is None
    assert "keyring.backends.fail.Keyring" in description, (
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

    store, description = secrets_adapter._decide(fake)

    assert store is not None
    assert "keyring.backends.Windows.WinVaultKeyring" in description


def test_the_three_descriptions_are_distinct():
    """The second element is a CONTRACT, not a debugging aid.

    D7 requires the resolved backend to be reported at run time rather than
    assumed at install time, and this string is what carries that report to the
    Settings page. So all three layers must be distinguishable from it — a
    description that said the same thing in every case would satisfy every other
    test in this file while telling the user nothing.

    Mutation: return one constant from `_decide` and this goes red while the
    three path tests above stay green, which is why it is a separate test.
    """
    absent = secrets_adapter._decide(None)[1]
    unusable = secrets_adapter._decide(FakeKeyring(Keyring(), recommended=False))[1]
    working = secrets_adapter._decide(FakeKeyring(WinVaultKeyring()))[1]

    assert len({absent, unusable, working}) == 3, "the layers are indistinguishable"

    # Each says which layer is in use, and the two keyring cases name the backend.
    assert ".env" in absent and "desktop" in absent
    assert ".env" in unusable and "keyring.backends.fail.Keyring" in unusable
    assert "keyring.backends.Windows.WinVaultKeyring" in working


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
    store, description = secrets_adapter._decide(fake)

    store.set("JIRA_API_TOKEN", SYNTHETIC)
    store.get("JIRA_API_TOKEN")

    assert SYNTHETIC not in description
    assert SYNTHETIC not in store.description
    assert store.description == "keyring.backends.Windows.WinVaultKeyring"


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def test_a_value_round_trips():
    fake = FakeKeyring(WinVaultKeyring())
    store, _ = secrets_adapter._decide(fake)

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
    store, _ = secrets_adapter._decide(fake)

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
    store, _ = secrets_adapter._decide(fake)

    assert store.delete("NEVER_STORED") is True


def test_a_backend_failure_is_reported_not_raised():
    """`keyring.errors.KeyringError` is not enough, measured: on Windows a
    CredRead/CredWrite failure arrives as a raw `pywin32ctypes` error that never
    passes through keyring's own hierarchy. Naming it would mean importing
    `win32ctypes`, which does not exist on Linux. So the adapter catches broadly
    and reports — its contract is "return the secret or say you could not"."""
    fake = FakeKeyring(WinVaultKeyring(), raises=RuntimeError("credential store is locked"))
    store, _ = secrets_adapter._decide(fake)

    assert store.get("JIRA_API_TOKEN") is None
    assert store.set("JIRA_API_TOKEN", SYNTHETIC) is False


# ---------------------------------------------------------------------------
# What reaches the log
# ---------------------------------------------------------------------------

def test_a_failure_logs_the_type_and_the_message(caplog):
    fake = FakeKeyring(WinVaultKeyring(), raises=RuntimeError("credential store is locked"))
    store, _ = secrets_adapter._decide(fake)

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
    store, _ = secrets_adapter._decide(fake)

    with caplog.at_level(logging.WARNING):
        store.set("JIRA_API_TOKEN", SYNTHETIC)

    text = caplog.text
    assert SYNTHETIC not in text, "the value reached the log through the exception"
    assert "RuntimeError" in text, "the exception type is still useful and must survive"


# ---------------------------------------------------------------------------
# The audit
# ---------------------------------------------------------------------------

def test_this_suite_never_imports_keyring():
    """The guarantee that no test in this file can reach a real credential store.

    Stated as an assertion rather than a convention. Mutation: call
    `resolve_store()` from any test above and this goes red on a machine where
    keyring is installed — which is every desktop this feature is FOR.
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
    store, _ = secrets_adapter._decide(fake)

    store.set(name, SYNTHETIC)

    services = {service for service, _ in fake.stored}
    assert len(services) == 1
    assert name in next(iter(services))
