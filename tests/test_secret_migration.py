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

import os

import pytest

from defect_risk_analyzer import config

TOKEN ="synthetic-jira-token-0000"
LLM_KEY = "synthetic-groq-key-1111"


class FakeStore:
    """Records every write, and can be told to fail in specific ways."""

    def __init__(self, *, refuse=(), lose=(), stuck=(), unreadable=()):
        self.values: dict[str, str] = {}
        self.writes: list[str] = []
        self.deletes: list[str] = []
        self._refuse = set(refuse)   # set() returns False
        self._lose = set(lose)       # set() succeeds but nothing is stored
        self._stuck = set(stuck)     # delete() returns False, the value stays
        self._unreadable = set(unreadable)  # get() returns None, the value stays

    def get(self, name):
        if name in self._unreadable:
            return None
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
        self.deletes.append(name)
        if name in self._stuck:
            return False
        self.values.pop(name, None)
        return True


@pytest.fixture
def migration(monkeypatch, tmp_path):
    """A throwaway `.env` and an injected store; all module state restored."""
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

    env_file = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", env_file)

    def _install(store, env_text):
        env_file.write_text(env_text, encoding="utf-8")
        monkeypatch.setattr(config, "_secret_store", store)
        monkeypatch.setattr(config, "_secret_store_code", "store_active")
        monkeypatch.setattr(config, "_secret_store_params", {"backend": "fake.Backend"})
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


def test_emptying_a_stored_secret_empties_it(migration):
    """6E-2 PR6 measured this red (K-E3, the xfail(strict) step); 6E-2 PR8
    fixed it (user decision 2a, 2026-11-17) and this is an ordinary test now.

    Clearing the token field on the Settings page saves "". An empty value
    never reached the store, so only `.env` was emptied — it was empty already
    — and `_get_secret` fell through to the store, which still held the old
    credential. PR8 also asks the store itself: the copy must be gone, not
    merely hidden.
    """
    store = FakeStore()
    store.values["JIRA_API_TOKEN"] = TOKEN
    migration(store, "JIRA_API_TOKEN=\n")

    config.save_secret("JIRA_API_TOKEN", "")
    config.reload()

    assert config.JIRA_API_TOKEN == "", "the cleared credential came back from the store"
    assert "JIRA_API_TOKEN" not in store.values, "the store still holds the credential"


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


# ---------------------------------------------------------------------------
# 6E-2 PR6, T1(a) — a settings save is all of it or none of it
# ---------------------------------------------------------------------------
# The Settings page saves several keys at once. Each used to get its own
# atomic file write, so a failure on the third key left the first two saved —
# in .env and in os.environ — with no reload() and no reset_llm() behind them.
# And a secret went to the store BEFORE its .env line was blanked: when the
# blanking failed, the store held the new value while .env kept the old plain
# text, which _get_secret prefers — the old value shadowing the new one.

PLAIN_KEYS = ("JIRA_URL", "JIRA_EMAIL", "JIRA_PROJECT_KEY")


@pytest.fixture
def settings_save(migration, monkeypatch):
    """The migration fixture plus the plain keys these tests write, and the
    Settings page's own entry point with the service stubbed out."""
    from defect_risk_analyzer.ui import service as ui_service

    for key in PLAIN_KEYS:
        monkeypatch.setenv(key, "")
        monkeypatch.setattr(config, key, getattr(config, key))

    class _StubService:
        def reset_llm(self):
            pass

    monkeypatch.setattr(ui_service, "get_service", _StubService)
    return migration, ui_service.save_multiple_env


def _write_fails_when(monkeypatch, predicate):
    """Make every .env replace whose content matches `predicate` fail."""
    real = config._atomic_write_lines

    def guarded(lines):
        if predicate("".join(lines)):
            raise PermissionError(13, "Permission denied", ".env")
        real(lines)

    monkeypatch.setattr(config, "_atomic_write_lines", guarded)


def test_a_save_that_fails_part_way_writes_none_of_it(settings_save, monkeypatch):
    migration, save = settings_save
    env_file = migration(None, "JIRA_URL=https://old\nJIRA_EMAIL=old@x\nJIRA_PROJECT_KEY=OLD\n")
    before = env_file.read_bytes()
    # Only the write that carries the last key fails: under a per-key writer
    # the first two are on disk by then.
    _write_fails_when(monkeypatch, lambda text: "JIRA_PROJECT_KEY=NEW" in text)

    with pytest.raises(PermissionError):
        save({"JIRA_URL": "https://new", "JIRA_EMAIL": "new@x", "JIRA_PROJECT_KEY": "NEW"})

    assert env_file.read_bytes() == before, "part of the save reached .env"
    assert [os.environ[k] for k in PLAIN_KEYS] == ["https://old", "old@x", "OLD"]


@pytest.mark.parametrize("previous", ["old-stored-token", None], ids=["replaced", "new"])
def test_a_secret_stored_before_the_file_failed_is_put_back(settings_save, monkeypatch, previous):
    """No shadowing: after a failed save the store holds what it held before,
    so the old plain-text .env line and the store agree on the old value."""
    migration, save = settings_save
    store = FakeStore()
    if previous is not None:
        store.values["JIRA_API_TOKEN"] = previous
    env_file = migration(store, "JIRA_API_TOKEN=old-plain-token\nJIRA_URL=https://old\n")
    before = env_file.read_bytes()
    _write_fails_when(monkeypatch, lambda text: True)

    with pytest.raises(PermissionError):
        save({"JIRA_API_TOKEN": "new-token-3333", "JIRA_URL": "https://new"})

    assert store.get("JIRA_API_TOKEN") == previous
    assert env_file.read_bytes() == before


def test_a_failed_put_back_is_logged_and_the_save_error_still_raised(
    settings_save, monkeypatch, caplog
):
    """If the store cannot take the old value back, that is the one state a
    user cannot see from the screen — so it has to be in the log by key name.
    The save's own error is what call() reports, not the put-back's."""
    migration, save = settings_save

    class _CannotPutBack(FakeStore):
        def set(self, name, value):
            if value == "old-stored-token":
                raise RuntimeError("store went away")
            return super().set(name, value)

    store = _CannotPutBack()
    store.values["JIRA_API_TOKEN"] = "old-stored-token"
    migration(store, "JIRA_API_TOKEN=old-plain-token\n")
    _write_fails_when(monkeypatch, lambda text: True)

    with caplog.at_level("ERROR", logger="defect_risk_analyzer.config"):
        with pytest.raises(PermissionError):
            save({"JIRA_API_TOKEN": "new-token-4444"})

    assert "JIRA_API_TOKEN" in caplog.text
    assert "could not be put back" in caplog.text


# ---------------------------------------------------------------------------
# 6E-2 PR8, Y2 — a cleared credential is removed from the store as well
# ---------------------------------------------------------------------------
# Emptying `.env` alone cannot remove a credential that lives in the store:
# `_get_secret` falls through to it. A delete the store refuses has no
# fallback, so it undoes the whole save, like any other failed save (T1(a)).


def test_emptying_removes_a_stored_copy_that_env_was_shadowing(migration):
    """`.env` held one value and the store another; the field showed the
    `.env` one. Clearing it must leave neither behind."""
    store = FakeStore()
    store.values["JIRA_API_TOKEN"] = "stored-token-5555"
    env_file = migration(store, f"JIRA_API_TOKEN={TOKEN}\n")
    config.reload()

    config.save_secret("JIRA_API_TOKEN", "")
    config.reload()

    assert config.JIRA_API_TOKEN == ""
    assert "JIRA_API_TOKEN" not in store.values
    assert _text(env_file) == "JIRA_API_TOKEN=\n"


def test_a_delete_the_store_refuses_undoes_the_whole_save(settings_save):
    """No half-saved batch: the other credential in the same save goes back to
    what the store held, `.env` is not touched, and the error is an OSError so
    call() reports it as a system error with nothing sensitive on screen."""
    migration, save = settings_save
    store = FakeStore(stuck={"JIRA_API_TOKEN"})
    store.values.update({"GROQ_API_KEY": "old-groq-6666", "JIRA_API_TOKEN": TOKEN})
    env_file = migration(store, "GROQ_API_KEY=\nJIRA_API_TOKEN=\nJIRA_URL=https://old\n")
    before = env_file.read_bytes()

    with pytest.raises(config.CredentialStoreError) as raised:
        save({"GROQ_API_KEY": LLM_KEY, "JIRA_API_TOKEN": "", "JIRA_URL": "https://new"})

    assert isinstance(raised.value, OSError)
    assert "JIRA_API_TOKEN" in str(raised.value)
    assert TOKEN not in str(raised.value), "the message carried the value"
    assert store.values == {"GROQ_API_KEY": "old-groq-6666", "JIRA_API_TOKEN": TOKEN}
    assert env_file.read_bytes() == before


def test_a_deleted_credential_is_put_back_when_env_cannot_be_written(
    settings_save, monkeypatch
):
    migration, save = settings_save
    store = FakeStore()
    store.values["JIRA_API_TOKEN"] = TOKEN
    env_file = migration(store, "JIRA_API_TOKEN=\nJIRA_URL=https://old\n")
    before = env_file.read_bytes()
    _write_fails_when(monkeypatch, lambda text: True)

    with pytest.raises(PermissionError):
        save({"JIRA_API_TOKEN": "", "JIRA_URL": "https://new"})

    assert store.values == {"JIRA_API_TOKEN": TOKEN}, "the cleared credential was lost"
    assert env_file.read_bytes() == before


def test_a_credential_the_store_cannot_read_is_not_deleted(migration):
    """What cannot be read cannot be put back if the save fails later, and the
    Settings page showed the field empty already — so nothing is deleted."""
    store = FakeStore(unreadable={"JIRA_API_TOKEN"})
    store.values["JIRA_API_TOKEN"] = TOKEN
    migration(store, "JIRA_API_TOKEN=\n")

    config.save_secret("JIRA_API_TOKEN", "")

    assert store.deletes == []
    assert store.values == {"JIRA_API_TOKEN": TOKEN}
