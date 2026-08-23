"""
What config does when init() is never called.

DOCUMENTING CURRENT BEHAVIOUR, NOT ENDORSING IT. Skipping init() does not raise
and does not warn: every setting silently keeps its module-level default, so a
fully configured .env is ignored and is_first_run() reports True. Consumers read
plausible-looking values that have nothing to do with the user's configuration.

The fix is Faz 6. These tests exist so that fix has a starting point, and so the
behaviour cannot change unnoticed in the meantime.

Order-independence: config._initialized is process-global and never reset, so
"defaults still hold" is only true if nothing earlier in the process called
init(). Rather than depend on that, each test reconstructs the pre-init() state
explicitly in its fixture — so the file passes alone and in a full run alike.
"""

import pytest

from defect_risk_analyzer import config

# The module-level defaults, written out literally rather than read back from
# config: reading them from the module under test would make the assertions
# circular — they would pass no matter what the defaults became.
CONFIG_DEFAULTS = {
    "JIRA_URL": "",
    "JIRA_EMAIL": "",
    "JIRA_API_TOKEN": "",
    "JIRA_PROJECT_KEY": "",
    "LLM_PROVIDER": "groq",
    "GROQ_API_KEY": "",
    "OPENAI_API_KEY": "",
    "LLM_MODEL": "",
    "API_KEY": "",
    "MAX_DAILY_REQUESTS": 50,
    "GROQ_SLEEP": 2.0,
    "MAX_RETRIES": 2,
    "USE_MOCK_DATA": False,
    "ANONYMIZE_DATA": True,
    "LANGUAGE": "tr",
    "API_HOST": "0.0.0.0",
    "API_PORT": 8000,
    "STREAMLIT_PORT": 8501,
    "LOG_LEVEL": "INFO",
}

# Deliberately different from every default above, so "the file was read" and
# "the default happened to match" can never be confused.
ENV_CONTENT = """\
JIRA_URL=https://example.atlassian.net
JIRA_EMAIL=someone@example.com
JIRA_API_TOKEN=token-sentinel
JIRA_PROJECT_KEY=SENTINEL
LLM_PROVIDER=openai
GROQ_API_KEY=groq-sentinel
OPENAI_API_KEY=openai-sentinel
MAX_DAILY_REQUESTS=7
GROQ_SLEEP=0
USE_MOCK_DATA=True
ANONYMIZE_DATA=False
DRA_LANGUAGE=en
LOG_LEVEL=debug
"""

ENV_KEYS = [line.split("=", 1)[0] for line in ENV_CONTENT.strip().splitlines()]


@pytest.fixture
def uninitialized_config(monkeypatch, tmp_path):
    """Reconstruct config's post-import, pre-init() state.

    monkeypatch restores every attribute and environment variable at teardown,
    so this cannot leak into other test modules either — the isolation runs both
    directions.
    """
    # load_dotenv(override=True) writes into os.environ. Registering each key
    # with monkeypatch first records its original value, so teardown restores it
    # regardless of what reload() does in between.
    for key in ENV_KEYS:
        monkeypatch.setenv(key, "__pre_test_sentinel__")

    env_file = tmp_path / ".env"
    env_file.write_text(ENV_CONTENT, encoding="utf-8")

    monkeypatch.setattr(config, "ENV_FILE", env_file)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "_initialized", False)
    for name, default in CONFIG_DEFAULTS.items():
        monkeypatch.setattr(config, name, default)

    return config


# ===========================================================================
# Without init()
# ===========================================================================

def test_is_initialized_is_false_before_init(uninitialized_config):
    assert uninitialized_config.is_initialized() is False


def test_settings_keep_defaults_before_init(uninitialized_config):
    """The silent failure being documented.

    A populated .env sits on disk the whole time. Nothing raises, nothing warns,
    and every read returns a default — so a configured user is served as if they
    had configured nothing.
    """
    assert uninitialized_config.ENV_FILE.exists()

    for name, default in CONFIG_DEFAULTS.items():
        assert getattr(uninitialized_config, name) == default, name


def test_is_first_run_is_true_before_init_despite_configured_env(uninitialized_config):
    """The user-visible consequence: the setup wizard reappears.

    is_first_run() is computed from the unpopulated globals, so a fully
    configured install looks brand new until init() has run.
    """
    assert uninitialized_config.is_first_run() is True


def test_llm_helpers_report_unconfigured_before_init(uninitialized_config):
    assert uninitialized_config.is_llm_configured() is False
    assert uninitialized_config.is_jira_configured() is False
    assert uninitialized_config.get_active_llm_key() == ""


# ===========================================================================
# After init()
# ===========================================================================

def test_init_populates_settings_from_env_file(uninitialized_config):
    uninitialized_config.init()

    assert uninitialized_config.is_initialized() is True
    assert uninitialized_config.JIRA_URL == "https://example.atlassian.net"
    assert uninitialized_config.JIRA_PROJECT_KEY == "SENTINEL"
    assert uninitialized_config.GROQ_API_KEY == "groq-sentinel"
    assert uninitialized_config.MAX_DAILY_REQUESTS == 7
    assert uninitialized_config.USE_MOCK_DATA is True
    assert uninitialized_config.ANONYMIZE_DATA is False
    assert uninitialized_config.LANGUAGE == "en"
    # Normalized on read: provider lowercased, log level uppercased.
    assert uninitialized_config.LLM_PROVIDER == "openai"
    assert uninitialized_config.LOG_LEVEL == "DEBUG"


def test_init_flips_is_first_run(uninitialized_config):
    assert uninitialized_config.is_first_run() is True
    uninitialized_config.init()
    assert uninitialized_config.is_first_run() is False


def test_init_creates_the_data_directory(uninitialized_config):
    assert not uninitialized_config.DATA_DIR.exists()
    uninitialized_config.init()
    assert uninitialized_config.DATA_DIR.is_dir()


def test_init_is_guarded_by_the_initialized_flag(uninitialized_config):
    """A second init() does not re-read .env.

    This is why the flag is a hazard rather than a mere optimization: once any
    caller has run init(), a later change to .env is invisible until the process
    restarts, and a test that forgets to reset the flag silently tests nothing.
    """
    uninitialized_config.init()
    assert uninitialized_config.MAX_DAILY_REQUESTS == 7

    uninitialized_config.ENV_FILE.write_text("MAX_DAILY_REQUESTS=99\n", encoding="utf-8")
    uninitialized_config.init()

    assert uninitialized_config.MAX_DAILY_REQUESTS == 7   # not 99

    # reload() bypasses the guard, which is how /reload-config picks up edits.
    uninitialized_config.reload()
    assert uninitialized_config.MAX_DAILY_REQUESTS == 99


# ===========================================================================
# Persisting one setting without re-reading the rest
# ===========================================================================

def test_persist_language_writes_the_file_and_the_global(uninitialized_config):
    """The edge the language picker was missing.

    set_env_value() alone updates .env and os.environ but leaves config.LANGUAGE
    on whatever the process booted with, and init() will not re-read it — the
    _initialized guard above is exactly why. Everything downstream of
    sample_bugs_file() then keeps serving the boot language.

    Narrower than reload() on purpose: one global, not seventeen. A language
    picker has no business re-reading Jira credentials or rate limits, so the
    last assertion pins that it does not — same shape as ensure_api_key().
    """
    cfg = uninitialized_config
    cfg.init()
    assert cfg.LANGUAGE == "en"

    untouched = cfg.LLM_PROVIDER, cfg.GROQ_API_KEY, cfg.MAX_DAILY_REQUESTS, cfg.USE_MOCK_DATA

    cfg.persist_language("tr")

    assert cfg.LANGUAGE == "tr"
    assert "DRA_LANGUAGE=tr" in cfg.ENV_FILE.read_text(encoding="utf-8")
    assert (
        cfg.LLM_PROVIDER,
        cfg.GROQ_API_KEY,
        cfg.MAX_DAILY_REQUESTS,
        cfg.USE_MOCK_DATA,
    ) == untouched


def test_persist_language_normalizes_the_code(uninitialized_config):
    """.env and the global must never disagree about the same choice.

    config.reload() lowercases what it reads (config.py: DRA_LANGUAGE), so a
    stored "EN" would mean sample_bugs_file() picked the English set now and
    the Turkish one after a restart — the same split-brain this whole fix is
    about, just one process later.
    """
    cfg = uninitialized_config
    cfg.init()

    cfg.persist_language("EN")

    assert cfg.LANGUAGE == "en"
    assert "DRA_LANGUAGE=en" in cfg.ENV_FILE.read_text(encoding="utf-8")
