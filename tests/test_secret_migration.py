"""Moving credentials out of `.env` and into the OS credential store.

WRITTEN BEFORE THE FIX (Faz 6B, 6b). The order is the subject, not a detail:

    write to the store -> read it back and verify -> empty `.env`
                       -> clear any retired copy left in a comment

Each arrow is a place the migration can stop, and stopping at a different one
leaves the user somewhere different. The three that matter each get their own
test, because "it works" only describes the path where nothing fails:

  * the store write fails      -> `.env` must be untouched. The user keeps a
                                  working configuration and loses nothing.
  * the read-back disagrees    -> the migration stops. This is the only thing
                                  that catches a store which reports success
                                  and silently keeps nothing.
  * emptying `.env` fails      -> the secret is now in BOTH places. Recoverable,
                                  and the user has to be told, because the
                                  plain-text copy is still there.

VERIFYING BY READING BACK is not paranoia about our own code. `store.set`
returns whether the backend accepted the write, which is not the same as the
value being retrievable — and the cost of being wrong is a credential deleted
from `.env` that cannot be read back from anywhere.

NO REAL SECRETS and no real credential store: `conftest._KeyringBlocker` refuses
the keyring import for the whole session, and these tests inject a fake.
"""

import pytest

from defect_risk_analyzer import config

TOKEN = "synthetic-jira-token-0000"
LLM_KEY = "synthetic-groq-key-1111"


class FakeStore:
    """Records every write, and can be told to fail in specific ways."""

    def __init__(self, *, refuse=(), lose=()):
        self.values: dict[str, str] = {}
        self.writes: list[str] = []
        self._refuse = set(refuse)   # set() returns False
        self._lose = set(lose)       # set() succeeds but nothing is stored

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.writes.append(name)
        if name in self._refuse:
            return False
        if name in self._lose:
            return True
        self.values[name] = value
        return True

    def delete(self, name):
        self.values.pop(name, None)
        return True


@pytest.fixture
def migration(monkeypatch, tmp_path):
    """A throwaway `.env` and an injected store; all module state restored."""
    for key in config.STORED_SECRET_KEYS:
        monkeypatch.setenv(key, "")
        monkeypatch.setattr(config, key, getattr(config, key))

    env_file = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", env_file)

    def _install(store, env_text):
        env_file.write_text(env_text, encoding="utf-8")
        monkeypatch.setattr(config, "_secret_store", store)
        monkeypatch.setattr(config, "_secret_store_description", "fake store")
        monkeypatch.setattr(config, "_secret_store_resolved", True)
        # RELOAD IS PART OF THE FIXTURE because it is part of the call sequence:
        # bootstrap() runs config.init(), which loads `.env` into os.environ, and
        # only then migrates. Without it `_get_env` sees the empty values this
        # fixture put in os.environ, the migration finds nothing to move, and
        # every test here passes or fails for a reason that has nothing to do
        # with what it claims — test_the_moved_value_is_still_readable passed
        # VACUOUSLY that way, reading the value straight back out of the .env
        # the migration had never touched.
        config.reload()
        return env_file

    return _install


def _text(path):
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------

def test_a_secret_moves_and_leaves_no_trace_in_the_file(migration):
    store = FakeStore()
    env_file = migration(store, f"JIRA_URL=https://x\nJIRA_API_TOKEN={TOKEN}\n")

    report = config.migrate_secrets_to_store()

    assert store.get("JIRA_API_TOKEN") == TOKEN
    assert TOKEN not in _text(env_file), "the secret is still in .env"
    assert "JIRA_URL=https://x" in _text(env_file), "unrelated settings were touched"
    assert report["moved"] == ["JIRA_API_TOKEN"]


def test_the_moved_value_is_still_readable(migration):
    """The point of the whole exercise. Emptying `.env` without this is data loss."""
    store = FakeStore()
    migration(store, f"GROQ_API_KEY={LLM_KEY}\n")

    config.migrate_secrets_to_store()
    config.reload()

    assert config.GROQ_API_KEY == LLM_KEY


def test_a_retired_copy_in_a_comment_is_cleared_too(migration):
    """The 6A writer retires a duplicate by commenting it out, value intact.

    A user who saved once between 6A and 6B shipping has exactly that line, and
    a migration that only emptied the live one would leave the secret on disk.
    The retired line is produced by the real writer rather than hand-written.
    """
    store = FakeStore()
    env_file = migration(store, f"JIRA_API_TOKEN=old-{TOKEN}\nJIRA_API_TOKEN={TOKEN}\n")

    config.set_env_value("JIRA_API_TOKEN", TOKEN)  # retires the first line
    assert f"old-{TOKEN}" in _text(env_file), "fixture did not retire a line"

    config.migrate_secrets_to_store()

    assert f"old-{TOKEN}" not in _text(env_file), "a commented-out secret survived"
    assert TOKEN not in _text(env_file)


# ---------------------------------------------------------------------------
# The three failure points
# ---------------------------------------------------------------------------

def test_a_refused_store_write_leaves_env_untouched(migration):
    """Failure point 1. Nothing is removed until something else holds it."""
    store = FakeStore(refuse={"JIRA_API_TOKEN"})
    env_file = migration(store, f"JIRA_API_TOKEN={TOKEN}\n")
    before = _text(env_file)

    report = config.migrate_secrets_to_store()

    assert _text(env_file) == before, ".env changed after a failed store write"
    assert report["moved"] == []
    assert report["not_moved"] == ["JIRA_API_TOKEN"]


def test_a_store_that_loses_the_value_stops_the_migration(migration):
    """Failure point 2, and the only thing that catches a silent backend.

    The store accepts the write and reports success, but nothing comes back.
    Without the read-back this is indistinguishable from a successful move, and
    the migration would delete the only remaining copy.
    """
    store = FakeStore(lose={"JIRA_API_TOKEN"})
    env_file = migration(store, f"JIRA_API_TOKEN={TOKEN}\n")

    report = config.migrate_secrets_to_store()

    assert TOKEN in _text(env_file), "the secret was deleted despite a failed read-back"
    assert report["not_moved"] == ["JIRA_API_TOKEN"]


def test_a_failed_env_write_is_reported_not_swallowed(migration, monkeypatch):
    """Failure point 3. The secret is in both places, and the user is told.

    Recoverable — nothing is lost — but the plain-text copy is still on disk, so
    silence here would be a lie by omission.
    """
    store = FakeStore()
    migration(store, f"JIRA_API_TOKEN={TOKEN}\n")

    def _refuse(*args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(config, "_atomic_write_lines", _refuse)

    report = config.migrate_secrets_to_store()

    assert store.get("JIRA_API_TOKEN") == TOKEN
    assert report["in_both"] == ["JIRA_API_TOKEN"]
    assert report["moved"] == []


# ---------------------------------------------------------------------------
# Idempotence — it runs on every start
# ---------------------------------------------------------------------------

def test_a_second_run_writes_nothing(migration):
    """It runs at every startup, so "nothing left to move" must cost nothing.

    Easy to be true today and easy to break tomorrow: a migration that rewrote
    the file or re-set the store on every boot would churn `.env` and re-issue
    credential writes forever.
    """
    store = FakeStore()
    env_file = migration(store, f"JIRA_API_TOKEN={TOKEN}\nGROQ_API_KEY={LLM_KEY}\n")

    config.migrate_secrets_to_store()
    after_first = env_file.read_bytes()
    writes_after_first = list(store.writes)

    report = config.migrate_secrets_to_store()

    assert env_file.read_bytes() == after_first, ".env was rewritten on the second run"
    assert store.writes == writes_after_first, "the store was written again"
    assert report["moved"] == []


def test_no_store_means_no_migration(migration):
    """Docker, CI, and any desktop without the extra.

    THIS IS THE CORRECT BEHAVIOUR, not a gap: with nowhere better to put it, the
    credential stays in `.env`. Pinned so the next person does not read it as a
    bug and "fix" it into deleting credentials with no replacement.
    """
    env_file = migration(None, f"JIRA_API_TOKEN={TOKEN}\n")
    before = _text(env_file)

    report = config.migrate_secrets_to_store()

    assert _text(env_file) == before
    assert report["moved"] == []
    assert TOKEN in _text(env_file)


# ---------------------------------------------------------------------------
# Saving from the Settings page — the layer has to hold after the migration
# ---------------------------------------------------------------------------
# WITHOUT THIS the migration undoes itself. `_get_secret` lets a non-empty
# `.env` win, so a credential saved back to the file would shadow the one in the
# store and the next visit to Settings would return the install to plain text.
# The mutation that sends every save to `.env` passed 59 tests before these
# existed.

def test_save_secret_writes_to_the_store_and_clears_the_file(migration):
    store = FakeStore()
    env_file = migration(store, f"JIRA_API_TOKEN={TOKEN}\n")

    layer = config.save_secret("JIRA_API_TOKEN", "replacement-token-2222")

    assert layer == "store"
    assert store.get("JIRA_API_TOKEN") == "replacement-token-2222"
    assert "replacement-token-2222" not in _text(env_file)
    assert TOKEN not in _text(env_file)


def test_save_secret_falls_back_to_the_file_with_no_store(migration):
    """No store is a supported configuration, and this path must be unchanged."""
    env_file = migration(None, "JIRA_API_TOKEN=\n")

    layer = config.save_secret("JIRA_API_TOKEN", TOKEN)

    assert layer == "env"
    assert TOKEN in _text(env_file)


def test_save_secret_falls_back_rather_than_losing_the_value(migration):
    """A store that loses the write must not cost the user their credential.

    Falling back to `.env` puts it somewhere less private but keeps it. Dropping
    it would be the worse trade in every direction.
    """
    store = FakeStore(lose={"GROQ_API_KEY"})
    env_file = migration(store, "GROQ_API_KEY=\n")

    layer = config.save_secret("GROQ_API_KEY", LLM_KEY)

    assert layer == "env"
    assert LLM_KEY in _text(env_file)


def test_the_settings_page_routes_secrets_and_settings_differently(migration, monkeypatch):
    """The routing itself, at the call site the Settings page actually uses."""
    from defect_risk_analyzer.ui import service as ui_service

    class _StubService:
        def reset_llm(self):
            pass

    store = FakeStore()
    env_file = migration(store, "JIRA_API_TOKEN=\nMAX_DAILY_REQUESTS=50\n")
    monkeypatch.setattr(ui_service, "get_service", _StubService)

    ui_service.save_multiple_env({
        "JIRA_API_TOKEN": TOKEN,
        "MAX_DAILY_REQUESTS": "99",
    })

    assert store.get("JIRA_API_TOKEN") == TOKEN, "the credential did not reach the store"
    assert TOKEN not in _text(env_file), "the credential was written to .env as well"
    assert "MAX_DAILY_REQUESTS=99" in _text(env_file), "a plain setting was diverted"
    assert store.get("MAX_DAILY_REQUESTS") is None, "a plain setting went to the store"
