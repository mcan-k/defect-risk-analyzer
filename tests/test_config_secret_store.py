"""Where `config` reads a credential from when `.env` does not have one.

WRITTEN BEFORE THE FIX (Faz 6B, D13). Every test here is EXPECTED RED today:
`reload()` builds the four credential globals purely from `.env`.

WHY THIS EXISTS AT ALL. D6 planned the write half of the keyring migration and
never costed the read. `reload()` (config.py) sets JIRA_API_TOKEN,
GROQ_API_KEY, OPENAI_API_KEY and API_KEY from `_get_env` alone, so emptying
`.env` — which is the entire point of the migration — would zero them on the
next reload and break every reader: llm_provider, jira_client, api_auth, the
API health endpoints and three UI modules. The in-process patch does not save
it either, because `load_dotenv(ENV_FILE, override=True)` lets the FILE win
over `os.environ`. There is no smaller correct version of the migration than
one that also teaches config to read.

THE ORDER IS `.env` FIRST. A non-empty `.env` value wins and the store is not
consulted. That keeps a half-finished migration working (both places hold the
same value), and it keeps a hand-edited `.env` meaningful — someone who pastes
a key into the file expects it to take effect. The cost is recorded in
docs/KNOWN-DEBT.md: a stale hand-written value silently shadows a newer one in
the store.

NO REAL SECRETS, and no real credential store: `conftest._KeyringBlocker`
refuses the keyring import for the whole session, and these tests inject a fake
store directly.
"""

import pytest

from defect_risk_analyzer import config

SYNTHETIC_ENV = "synthetic-from-env-0000"
SYNTHETIC_STORE = "synthetic-from-store-1111"


class FakeStore:
    """A credential store that records what it was asked for."""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.reads: list[str] = []

    def get(self, name):
        self.reads.append(name)
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = value
        return True

    def delete(self, name):
        self.values.pop(name, None)
        return True


@pytest.fixture
def env_and_store(monkeypatch, tmp_path):
    """A throwaway `.env` plus an injected store, with all state restored."""
    # setenv TO THE EMPTY STRING. Two things had to be true at once and each
    # obvious choice broke one of them.
    #
    # Not the "__pre_test_sentinel__" the other config tests use:
    # `load_dotenv(override=True)` only overrides keys the FILE contains, so a
    # key with no line at all would keep the sentinel, and "missing line" would
    # be indistinguishable from "line with a value" — which is the whole subject
    # of test_a_missing_env_line_also_falls_through.
    #
    # And not `delenv(raising=False)`: on a key that is already absent that
    # records NOTHING to undo, so when `reload()` calls load_dotenv and writes
    # this file's values into os.environ, teardown leaves them there. That leak
    # is invisible here and surfaces in another module — it put a value in
    # config.API_KEY and flipped the Settings page from "create" to "rotate",
    # failing test_page_renders_all_of_its_sections.
    #
    # setenv records "was absent" and deletes at teardown, and an empty value
    # reads as empty, so both properties hold.
    for key in config.STORED_SECRET_KEYS:
        monkeypatch.setenv(key, "")
        monkeypatch.setattr(config, key, getattr(config, key))

    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", env_file)

    def _install(store, env_text=""):
        env_file.write_text(env_text, encoding="utf-8")
        monkeypatch.setattr(config, "_secret_store", store)
        monkeypatch.setattr(config, "_secret_store_description", "fake store")
        monkeypatch.setattr(config, "_secret_store_resolved", True)
        return env_file

    return _install


def test_an_empty_env_value_falls_through_to_the_store(env_and_store):
    """EXPECTED RED. The whole point of the migration."""
    store = FakeStore({"GROQ_API_KEY": SYNTHETIC_STORE})
    env_and_store(store, "GROQ_API_KEY=\n")

    config.reload()

    assert config.GROQ_API_KEY == SYNTHETIC_STORE


def test_a_missing_env_line_also_falls_through(env_and_store):
    """EXPECTED RED. Absent and empty must behave the same.

    The migration empties the value and leaves the line; a user who deletes the
    line outright must not get different behaviour from one who blanks it.
    """
    store = FakeStore({"JIRA_API_TOKEN": SYNTHETIC_STORE})
    env_and_store(store, "USE_MOCK_DATA=True\n")

    config.reload()

    assert config.JIRA_API_TOKEN == SYNTHETIC_STORE


def test_a_filled_env_value_wins_over_the_store(env_and_store):
    """EXPECTED RED — red because the store must be consulted at all.

    Pins the precedence: `.env` is the explicit, visible, hand-editable layer
    and the store fills its gaps, not the other way round.
    """
    store = FakeStore({"GROQ_API_KEY": SYNTHETIC_STORE})
    env_and_store(store, f"GROQ_API_KEY={SYNTHETIC_ENV}\n")

    config.reload()

    assert config.GROQ_API_KEY == SYNTHETIC_ENV
    assert "GROQ_API_KEY" not in store.reads, (
        "the store was consulted even though .env had a value"
    )


def test_no_store_leaves_the_value_empty(env_and_store):
    """EXPECTED RED. Docker, CI, and any desktop without the extra.

    `resolve_store()` returns None there, and that is a supported configuration
    rather than a failure — the global simply stays empty, exactly as it does
    today.
    """
    env_and_store(None, "GROQ_API_KEY=\n")

    config.reload()

    assert config.GROQ_API_KEY == ""


def test_a_full_env_never_resolves_the_store(env_and_store, monkeypatch):
    """EXPECTED RED. Resolution costs an import of keyring; skip it when it
    cannot possibly be needed.

    Measured in Adım 5: `resolve_store()` imports the library inside the
    function. A `.env` with every credential present has no gap to fill, so the
    import must not happen at all.
    """
    monkeypatch.setattr(config, "_secret_store_resolved", False)

    resolutions = []

    def _counting_resolve():
        resolutions.append(1)
        return None, "should not have been called"

    from defect_risk_analyzer.adapters import secrets

    monkeypatch.setattr(secrets, "resolve_store", _counting_resolve)

    env_file = config.ENV_FILE
    env_file.write_text(
        "\n".join(f"{key}={SYNTHETIC_ENV}" for key in config.STORED_SECRET_KEYS) + "\n",
        encoding="utf-8",
    )

    config.reload()

    assert resolutions == [], "the store was resolved for a .env with no gaps"


def test_the_store_is_resolved_once_and_reused(env_and_store, monkeypatch):
    """EXPECTED RED. The HANDLE is cached; see the next test for the values."""
    monkeypatch.setattr(config, "_secret_store_resolved", False)
    monkeypatch.setattr(config, "_secret_store", None)

    resolutions = []
    store = FakeStore({"GROQ_API_KEY": SYNTHETIC_STORE})

    def _counting_resolve():
        resolutions.append(1)
        return store, "fake store"

    from defect_risk_analyzer.adapters import secrets

    monkeypatch.setattr(secrets, "resolve_store", _counting_resolve)
    config.ENV_FILE.write_text("GROQ_API_KEY=\n", encoding="utf-8")

    config.reload()
    config.reload()
    config.reload()

    assert len(resolutions) == 1, f"resolved {len(resolutions)} times"


def test_values_are_never_cached(env_and_store):
    """EXPECTED RED, and this is the one that matters most.

    6A closed a bug of exactly this shape: a save reported success and the next
    `reload()` handed back the old value. Caching the handle is safe — the
    backend does not change inside a process. Caching the VALUE would rebuild
    that bug on the other layer, where it would be harder to see because the
    file on disk would look right.
    """
    store = FakeStore({"GROQ_API_KEY": "first-value"})
    env_and_store(store, "GROQ_API_KEY=\n")

    config.reload()
    assert config.GROQ_API_KEY == "first-value"

    store.set("GROQ_API_KEY", "second-value")
    config.reload()

    assert config.GROQ_API_KEY == "second-value", "reload() served a cached value"


def test_the_cache_holds_no_secret_value(env_and_store):
    """EXPECTED RED. Nothing that is cached may be a credential.

    The handle is an object with methods; the description is a backend name.
    Neither is a secret, and this asserts it rather than assuming it — the
    tempting optimisation is to memoise what the store returned.
    """
    store = FakeStore({"GROQ_API_KEY": SYNTHETIC_STORE})
    env_and_store(store, "GROQ_API_KEY=\n")

    config.reload()
    assert config.GROQ_API_KEY == SYNTHETIC_STORE

    assert SYNTHETIC_STORE not in repr(config._secret_store_description)
    cached = getattr(config, "_secret_store", None)
    assert cached is store, "the handle should be the cached thing"
    assert SYNTHETIC_STORE not in repr(config._secret_store_resolved)
