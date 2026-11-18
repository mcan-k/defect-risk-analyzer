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

import os

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

    # ALL FOUR store globals are recorded here, not inside _install. `secret_store()`
    # assigns every one of them, so a test that monkeypatches only some — and then
    # lets production code run — leaves the rest set at teardown. That leak is
    # invisible in this file and surfaced in test_dashboard_pages.py, where the
    # Settings page reported a "fake.Backend" credential layer that no test in
    # that file had injected.
    for name in ("_secret_store", "_secret_store_code",
                 "_secret_store_params", "_secret_store_resolved"):
        monkeypatch.setattr(config, name, getattr(config, name))
    # reload() writes this one too (6E-2 PR10); a store left unreadable here
    # would otherwise put a warning on the Settings page in another module.
    monkeypatch.setattr(config, "UNREADABLE_SECRETS", config.UNREADABLE_SECRETS)

    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", env_file)

    def _install(store, env_text=""):
        env_file.write_text(env_text, encoding="utf-8")
        monkeypatch.setattr(config, "_secret_store", store)
        monkeypatch.setattr(config, "_secret_store_code", "store_active")
        monkeypatch.setattr(config, "_secret_store_params", {"backend": "fake.Backend"})
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


# ---------------------------------------------------------------------------
# 6E-2 PR10 — a store that cannot be read is not a store that is empty
# ---------------------------------------------------------------------------

class _UnreadableFor(FakeStore):
    """Raises `SecretReadError` for the keys in `unreadable`, as KeyringStore
    does when the OS store fails; the values stay where they are."""

    def __init__(self, values=None, unreadable=()):
        super().__init__(values)
        self.unreadable = set(unreadable)

    def get(self, name):
        from defect_risk_analyzer.adapters.secrets import SecretReadError

        if name in self.unreadable:
            self.reads.append(name)
            raise SecretReadError(name)
        return super().get(name)


def test_reload_names_the_credentials_the_store_could_not_read(env_and_store):
    """Measured at cdb23f2: the read error ended as "" inside the adapter, so
    nothing above it could tell an unreadable token from a missing one."""
    store = _UnreadableFor(
        {"JIRA_API_TOKEN": SYNTHETIC_STORE, "GROQ_API_KEY": SYNTHETIC_STORE},
        unreadable={"JIRA_API_TOKEN"},
    )
    env_and_store(store, "JIRA_API_TOKEN=\nGROQ_API_KEY=\n")

    config.reload()

    assert config.JIRA_API_TOKEN == "", "every other reader still gets an empty value"
    assert config.GROQ_API_KEY == SYNTHETIC_STORE
    assert config.UNREADABLE_SECRETS == {"JIRA_API_TOKEN"}, (
        "absent (OPENAI_API_KEY, API_KEY) and readable keys must not be marked"
    )


def test_the_unreadable_mark_clears_once_the_store_reads_again(env_and_store):
    store = _UnreadableFor({"JIRA_API_TOKEN": SYNTHETIC_STORE}, unreadable={"JIRA_API_TOKEN"})
    env_and_store(store, "JIRA_API_TOKEN=\n")
    config.reload()

    store.unreadable.clear()
    config.reload()

    assert config.JIRA_API_TOKEN == SYNTHETIC_STORE
    assert config.UNREADABLE_SECRETS == frozenset()


def test_a_filled_env_value_is_never_marked_unreadable(env_and_store):
    """`.env` wins and the store is not asked, so nothing about it is known."""
    store = _UnreadableFor({"GROQ_API_KEY": SYNTHETIC_STORE}, unreadable={"GROQ_API_KEY"})
    env_and_store(store, f"GROQ_API_KEY={SYNTHETIC_ENV}\n")

    config.reload()

    assert config.GROQ_API_KEY == SYNTHETIC_ENV
    assert "GROQ_API_KEY" not in store.reads
    assert "GROQ_API_KEY" not in config.UNREADABLE_SECRETS


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
        return None, "should_not_have_been_called", {}

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
        return store, "store_active", {"backend": "fake.Backend"}

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

    assert SYNTHETIC_STORE not in repr(config._secret_store_code)
    assert SYNTHETIC_STORE not in repr(config._secret_store_params)
    cached = getattr(config, "_secret_store", None)
    assert cached is store, "the handle should be the cached thing"
    assert SYNTHETIC_STORE not in repr(config._secret_store_resolved)


def test_the_api_server_start_keeps_a_key_that_lives_in_the_store(env_and_store):
    """6E-2 PR6 measured this red (K-E3, the xfail(strict) step); 6E-2 PR8
    fixed it (user decision 1a, 2026-11-17) and this is an ordinary test now.

    After the migration the webhook key lives in the store and its `.env` line
    is empty. ensure_api_key() used to check `.env`/os.environ only: it found
    nothing, generated a NEW key and wrote it to `.env` in plain text, so the
    stored key — the one the Settings page showed and a Jira webhook held —
    stopped working. PR8 also asks for the return value: the caller must be
    handed the stored key, reported as saved.
    """
    store = FakeStore({"API_KEY": SYNTHETIC_STORE})
    env_file = env_and_store(store, "API_KEY=\n")
    config.reload()

    result = config.ensure_api_key()

    assert result == (SYNTHETIC_STORE, True), "the caller was not handed the stored key"
    assert config.API_KEY == SYNTHETIC_STORE, "the stored key was replaced"
    assert env_file.read_text(encoding="utf-8") == "API_KEY=\n", "a key went to .env"


# ---------------------------------------------------------------------------
# 6E-2 PR8, Y1 — the API key is read and saved like every other credential
# ---------------------------------------------------------------------------


class _RefusingStore(FakeStore):
    """A store that refuses every write."""

    def set(self, name, value):
        return False


def _unwritable_env(lines):
    raise PermissionError(13, "Permission denied", ".env")


def test_the_api_server_start_uses_the_stored_key(env_and_store, monkeypatch, tmp_path):
    """The call the API server makes at startup (api.py lifespan), end to end
    through init(): the stored key is the server's key, and nothing is written."""
    store = FakeStore({"API_KEY": SYNTHETIC_STORE})
    env_file = env_and_store(store, "API_KEY=\n")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "ANON_MAP_FILE", tmp_path / "data" / "anon_map.json")
    monkeypatch.setattr(config, "LEGACY_ANON_MAP_REMOVED", False)
    monkeypatch.setattr(config, "_initialized", False)

    config.init(generate_api_key=True)

    assert config.API_KEY == SYNTHETIC_STORE
    assert store.values == {"API_KEY": SYNTHETIC_STORE}, "the store was changed"
    assert env_file.read_text(encoding="utf-8") == "API_KEY=\n", "a key went to .env"


def test_a_generated_key_goes_to_the_store_not_to_env(env_and_store):
    store = FakeStore()
    env_file = env_and_store(store, "API_KEY=\n")

    result = config.ensure_api_key()

    assert result.saved is True
    assert result.key and store.values.get("API_KEY") == result.key
    assert result.key not in env_file.read_text(encoding="utf-8"), "plain text in .env"
    config.reload()
    assert config.API_KEY == result.key, "the next read found a different key"


def test_rotating_puts_the_new_key_in_the_store(env_and_store):
    store = FakeStore({"API_KEY": SYNTHETIC_STORE})
    env_file = env_and_store(store, "API_KEY=\n")

    result = config.ensure_api_key(rotate=True)

    assert result.saved is True
    assert result.key != SYNTHETIC_STORE
    assert store.values.get("API_KEY") == result.key
    assert result.key not in env_file.read_text(encoding="utf-8")


def test_a_generated_key_the_store_refuses_falls_back_to_env(env_and_store):
    """The same rule as every other credential (save_secret): a key the store
    will not take goes to `.env` rather than being lost."""
    env_file = env_and_store(_RefusingStore(), "API_KEY=\n")

    result = config.ensure_api_key()

    assert result.saved is True
    assert f"API_KEY={result.key}" in env_file.read_text(encoding="utf-8")


def test_a_generated_key_that_cannot_be_saved_is_kept_for_the_process(
    env_and_store, monkeypatch, caplog
):
    """T2(a) with a store in use: the store write succeeds, the `.env` write
    that empties the line fails, so the save is undone — the store is put back
    — and the key works for this process only, reported as not saved."""
    store = FakeStore()
    env_file = env_and_store(store, "API_KEY=\n")
    before = env_file.read_bytes()
    monkeypatch.setattr(config, "_atomic_write_lines", _unwritable_env)

    with caplog.at_level("WARNING", logger="defect_risk_analyzer.config"):
        result = config.ensure_api_key()

    assert result.saved is False
    assert result.key and config.API_KEY == result.key == os.environ["API_KEY"]
    assert "API_KEY" not in store.values, "the store kept a key reported as not saved"
    assert env_file.read_bytes() == before
    assert "could not be saved" in caplog.text


def test_a_key_in_env_still_wins_over_a_different_stored_key(env_and_store):
    """The rule that settled PR8's stop question: with a key in `.env` and a
    different one in the store, both the server and the dashboard read the
    `.env` one — measured at 9757edf before the fix, and unchanged by it."""
    store = FakeStore({"API_KEY": SYNTHETIC_STORE})
    env_file = env_and_store(store, f"API_KEY={SYNTHETIC_ENV}\n")
    config.reload()  # as init() does first: .env reaches os.environ

    result = config.ensure_api_key()

    assert result == (SYNTHETIC_ENV, True)
    assert store.values == {"API_KEY": SYNTHETIC_STORE}
    assert env_file.read_text(encoding="utf-8") == f"API_KEY={SYNTHETIC_ENV}\n"


# ---------------------------------------------------------------------------
# 6E-2 PR11 — a key the store cannot read is not replaced (user decision
# 1 (iii), 2026-11-18)
# ---------------------------------------------------------------------------
# Measured at 5b9ed4e with a fake store: the server start read the unreadable
# key as "", generated a new one, wrote it to `.env` in plain text (the
# read-back failed) and, when the store took the write, overwrote the stored
# key — a Jira webhook holding it answered 403 from then on.

_NO_NEW_KEY = "no new key was generated"


def _server_start(env_and_store, monkeypatch, tmp_path, store, env_text="API_KEY=\n"):
    """`init(generate_api_key=True)`, the call the API server's lifespan makes,
    on a fresh process state. Returns the `.env` path."""
    env_file = env_and_store(store, env_text)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "ANON_MAP_FILE", tmp_path / "data" / "anon_map.json")
    monkeypatch.setattr(config, "LEGACY_ANON_MAP_REMOVED", False)
    monkeypatch.setattr(config, "_initialized", False)
    config.init(generate_api_key=True)
    return env_file


def test_the_server_start_leaves_an_unreadable_key_alone(
    env_and_store, monkeypatch, tmp_path, caplog
):
    """Nothing generated, nothing written — `.env` byte for byte, the store
    value for value — and an ERROR that says so without a value in it."""
    store = _UnreadableFor({"API_KEY": SYNTHETIC_STORE}, unreadable={"API_KEY"})
    env_file = env_and_store(store, "API_KEY=\n")
    before = env_file.read_bytes()

    with caplog.at_level("ERROR", logger="defect_risk_analyzer.config"):
        _server_start(env_and_store, monkeypatch, tmp_path, store)

    assert config.API_KEY == "", "a key was put in use"
    assert env_file.read_bytes() == before, ".env was written"
    assert store.values == {"API_KEY": SYNTHETIC_STORE}, "the store was written"
    assert "API_KEY" in config.UNREADABLE_SECRETS
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 1 and _NO_NEW_KEY in errors[0].getMessage(), caplog.text
    assert SYNTHETIC_STORE not in caplog.text


def test_ensure_api_key_names_the_unreadable_key_on_its_own(env_and_store, monkeypatch):
    """Called with no reload() before it — the store went dark after the last
    one, or init() ran earlier in the process: the result is "", nothing is
    kept from before, and API_KEY joins UNREADABLE_SECRETS so api_auth's 503
    says what happened rather than "Set API_KEY in .env"."""
    store = _UnreadableFor({"API_KEY": SYNTHETIC_STORE}, unreadable={"API_KEY"})
    env_and_store(store, "API_KEY=\n")
    monkeypatch.setattr(config, "UNREADABLE_SECRETS", frozenset({"GROQ_API_KEY"}))
    monkeypatch.setattr(config, "API_KEY", "stale-key-from-before")

    result = config.ensure_api_key()

    assert result == ("", True)
    assert config.API_KEY == ""
    assert config.UNREADABLE_SECRETS == {"GROQ_API_KEY", "API_KEY"}
    assert store.values == {"API_KEY": SYNTHETIC_STORE}


def test_the_server_answers_503_with_the_unreadable_text_and_stays_healthy(
    env_and_store, monkeypatch, tmp_path
):
    """End to end through the real lifespan: the server comes up, /health is
    200, an authenticated endpoint answers 503 with the unreadable-store text —
    for the old key and for no key alike — and nothing was written."""
    from fastapi.testclient import TestClient

    from defect_risk_analyzer import api, api_auth

    store = _UnreadableFor({"API_KEY": SYNTHETIC_STORE}, unreadable={"API_KEY"})
    env_file = env_and_store(store, "API_KEY=\n")
    before = env_file.read_bytes()
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "ANON_MAP_FILE", tmp_path / "data" / "anon_map.json")
    monkeypatch.setattr(config, "LEGACY_ANON_MAP_REMOVED", False)
    monkeypatch.setattr(config, "_initialized", False)
    monkeypatch.setattr(api, "load_bugs_from_file", lambda: [])

    with TestClient(api.app, raise_server_exceptions=False) as client:
        health = client.get("/health")
        with_old = client.get("/results", headers={"X-API-Key": SYNTHETIC_STORE})
        without = client.get("/results")

    assert health.status_code == 200
    for response in (with_old, without):
        assert response.status_code == 503
        assert response.json() == {"detail": api_auth.API_KEY_UNREADABLE_DETAIL}
    assert env_file.read_bytes() == before
    assert store.values == {"API_KEY": SYNTHETIC_STORE}


def test_the_server_start_without_a_store_still_generates_into_env(
    env_and_store, monkeypatch, tmp_path, caplog
):
    """The Docker and CI path: no keyring, so no store and nothing unreadable.
    Unchanged by PR11 — the first start generates a key into `.env`."""
    with caplog.at_level("ERROR", logger="defect_risk_analyzer.config"):
        env_file = _server_start(env_and_store, monkeypatch, tmp_path, None)

    assert config.API_KEY
    assert env_file.read_text(encoding="utf-8") == f"API_KEY={config.API_KEY}\n"
    assert config.UNREADABLE_SECRETS == frozenset()
    assert _NO_NEW_KEY not in caplog.text


def test_the_server_start_keeps_a_readable_stored_key_after_pr11(
    env_and_store, monkeypatch, tmp_path, caplog
):
    """PR8's behaviour for a readable store, through the same start: the stored
    key is the server's key, nothing is written, and no ERROR."""
    store = FakeStore({"API_KEY": SYNTHETIC_STORE})

    with caplog.at_level("ERROR", logger="defect_risk_analyzer.config"):
        env_file = _server_start(env_and_store, monkeypatch, tmp_path, store)

    assert config.API_KEY == SYNTHETIC_STORE
    assert store.values == {"API_KEY": SYNTHETIC_STORE}
    assert env_file.read_text(encoding="utf-8") == "API_KEY=\n"
    assert "API_KEY" not in config.UNREADABLE_SECRETS
    assert _NO_NEW_KEY not in caplog.text
