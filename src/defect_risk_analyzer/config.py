"""
Centralized configuration loaded from .env file.

All application settings are defined here with type validation and sensible defaults.
Import this module anywhere you need configuration values.

**Importing this module has no side effects.** It computes path constants and
nothing else — no directory is created, no file is read, no file is written.
Entry points (dashboard, API server, CI analyzer, `dra`) call `init()` once at
startup; that is what creates `data/` and reads `.env`.

Skipping `init()` does not raise: every setting simply keeps its module-level
default, and the application silently behaves as if nothing were configured —
mock mode off, no credentials, first-run wizard. If you add a new entry point,
call `init()` in it.

`reload()` re-reads `.env` on demand; the Settings page calls it after saving so
changes take effect without a restart. API key generation is explicit via
`ensure_api_key()` — it writes to `.env`, so it never happens implicitly.
"""

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths (these never change)
# ---------------------------------------------------------------------------

def _resolve_base_dir() -> Path:
    """
    Locate the project root, which holds `data/` and `.env`.

    This module lives inside the package (src/defect_risk_analyzer/), so
    `Path(__file__).parent` would point at the package directory, not the
    project root — silently relocating data/ and .env. Resolution order:

      1. DRA_BASE_DIR environment variable (explicit override).
      2. The nearest ancestor directory containing pyproject.toml
         (source checkout, editable install, and the Docker image).
      3. The current working directory (installed wheel, no project tree).

    See docs/KNOWN-DEBT.md for the limitations of the cwd fallback.
    """
    override = os.getenv("DRA_BASE_DIR", "").strip()
    if override:
        return Path(override).resolve()

    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent

    return Path.cwd().resolve()


# Path constants stay at import time on purpose. They are pure computation —
# no directory is created here — and moving them into init() would leave
# config.DATA_DIR as None for any code that touches it first: that reads as a
# valid value and fails much later, instead of raising at the point of misuse.
BASE_DIR = _resolve_base_dir()
DATA_DIR = BASE_DIR / "data"
ENV_FILE = BASE_DIR / ".env"

# Path patterns mapping directories to modules, read by ci_analyzer. Unlike
# .env this file is committed: it is a product default, not user credentials,
# and the PR workflow only checks the repository out — a gitignored map would
# simply be absent on the runner and the analyzer would go silent on every PR.
MODULE_MAP_FILE = BASE_DIR / "module-map.json"

# Data File Paths (static)
BUGS_FILE: Path = DATA_DIR / "bugs.json"
SAMPLE_BUGS_FILE: Path = DATA_DIR / "sample_bugs.json"
ANALYSIS_RESULTS_FILE: Path = DATA_DIR / "analysis_results.json"
DEFECT_DENSITY_FILE: Path = DATA_DIR / "defect_density.json"
ANON_MAP_FILE: Path = DATA_DIR / "anon_map.json"
WEBHOOK_RESULTS_FILE: Path = DATA_DIR / "webhook_results.json"
CHROMA_DB_DIR: Path = DATA_DIR / "chroma_db"

# Risk score thresholds are NOT here: they are fixed product rules rather than
# user settings, and live in core/scoring.py next to the formula that uses them.


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_env(key: str, default: str = "") -> str:
    """Read an environment variable, falling back to default."""
    return os.getenv(key, default).strip()


def _get_env_bool(key: str, default: bool = False) -> bool:
    """Read an environment variable as boolean."""
    value = _get_env(key, str(default)).lower()
    return value in ("true", "1", "yes")


def _get_env_int(key: str, default: int = 0) -> int:
    """Read an environment variable as integer."""
    try:
        return int(_get_env(key, str(default)))
    except ValueError:
        return default


def set_env_value(key: str, value: str) -> None:
    """
    Write a single key to `.env`, replacing an existing entry or appending.

    Also updates `os.environ` so the new value is visible immediately, before
    any `reload()`.
    """
    lines: list[str] = []
    if ENV_FILE.exists():
        with open(ENV_FILE, encoding="utf-8") as f:
            lines = f.readlines()

    replaced = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"# {key}="):
            lines[i] = f"{key}={value}\n"
            replaced = True
            break

    if not replaced:
        lines.append(f"{key}={value}\n")

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)

    os.environ[key] = str(value)


def ensure_api_key(*, rotate: bool = False) -> str:
    """
    Return the API key, generating and persisting one when needed.

    Writes to `.env`, so it is never called implicitly — only by the API server
    at startup and by the Settings page button.

    Args:
        rotate: Generate a fresh key even if one already exists.
    """
    global API_KEY

    if not rotate:
        existing = _get_env("API_KEY")
        if existing:
            API_KEY = existing
            return existing

    new_key = secrets.token_urlsafe(32)
    try:
        set_env_value("API_KEY", new_key)
    except OSError:
        # A read-only .env still gives a working key for this process.
        os.environ["API_KEY"] = new_key

    API_KEY = new_key
    return new_key


# ---------------------------------------------------------------------------
# Mutable config variables — updated by reload()
# ---------------------------------------------------------------------------

# Jira Connection
JIRA_URL: str = ""
JIRA_EMAIL: str = ""
JIRA_API_TOKEN: str = ""
JIRA_PROJECT_KEY: str = ""

# LLM Provider (BYOK)
LLM_PROVIDER: str = "groq"
GROQ_API_KEY: str = ""
OPENAI_API_KEY: str = ""
LLM_MODEL: str = ""

DEFAULT_GROQ_MODEL: str = "llama-3.3-70b-versatile"
DEFAULT_OPENAI_MODEL: str = "gpt-4o-mini"

# API Security
API_KEY: str = ""

# Rate Limiting & Cost Control
MAX_DAILY_REQUESTS: int = 50
GROQ_SLEEP: float = 2.0
MAX_RETRIES: int = 2

# Mock Data Mode
USE_MOCK_DATA: bool = False

# Data Anonymization
ANONYMIZE_DATA: bool = True

# Server
API_HOST: str = "0.0.0.0"
API_PORT: int = 8000
STREAMLIT_PORT: int = 8501
LOG_LEVEL: str = "INFO"


# ---------------------------------------------------------------------------
# Load / Reload
# ---------------------------------------------------------------------------

def reload() -> None:
    """
    Reload all configuration from .env file.

    Call this after saving settings to apply changes immediately
    without restarting the application.
    """
    global JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY
    global LLM_PROVIDER, GROQ_API_KEY, OPENAI_API_KEY, LLM_MODEL
    global API_KEY
    global MAX_DAILY_REQUESTS, GROQ_SLEEP, MAX_RETRIES
    global USE_MOCK_DATA
    global ANONYMIZE_DATA
    global API_HOST, API_PORT, STREAMLIT_PORT, LOG_LEVEL

    # Re-read .env (override=True forces refresh)
    load_dotenv(ENV_FILE, override=True)

    JIRA_URL = _get_env("JIRA_URL")
    JIRA_EMAIL = _get_env("JIRA_EMAIL")
    JIRA_API_TOKEN = _get_env("JIRA_API_TOKEN")
    JIRA_PROJECT_KEY = _get_env("JIRA_PROJECT_KEY")

    LLM_PROVIDER = _get_env("LLM_PROVIDER", "groq").lower()
    GROQ_API_KEY = _get_env("GROQ_API_KEY")
    OPENAI_API_KEY = _get_env("OPENAI_API_KEY")
    LLM_MODEL = _get_env("LLM_MODEL")

    # Read only — generating a key writes to .env, which reload() must not do.
    API_KEY = _get_env("API_KEY")

    MAX_DAILY_REQUESTS = _get_env_int("MAX_DAILY_REQUESTS", 50)
    GROQ_SLEEP = float(_get_env("GROQ_SLEEP", "2"))
    MAX_RETRIES = _get_env_int("MAX_RETRIES", 2)

    USE_MOCK_DATA = _get_env_bool("USE_MOCK_DATA", False)
    ANONYMIZE_DATA = _get_env_bool("ANONYMIZE_DATA", True)

    API_HOST = _get_env("API_HOST", "0.0.0.0")
    API_PORT = _get_env_int("API_PORT", 8000)
    STREAMLIT_PORT = _get_env_int("STREAMLIT_PORT", 8501)
    LOG_LEVEL = _get_env("LOG_LEVEL", "INFO").upper()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_llm_model() -> str:
    """Return the configured or default model name for the active provider."""
    if LLM_MODEL:
        return LLM_MODEL
    if LLM_PROVIDER == "openai":
        return DEFAULT_OPENAI_MODEL
    return DEFAULT_GROQ_MODEL


def is_jira_configured() -> bool:
    """Return True if all Jira credentials are present."""
    return all([JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY])


def is_llm_configured() -> bool:
    """Return True if the selected LLM provider has an API key."""
    if LLM_PROVIDER == "openai":
        return bool(OPENAI_API_KEY)
    return bool(GROQ_API_KEY)


def get_active_llm_key() -> str:
    """Return the API key for the currently selected LLM provider."""
    if LLM_PROVIDER == "openai":
        return OPENAI_API_KEY
    return GROQ_API_KEY


def is_first_run() -> bool:
    """Return True if no configuration exists (fresh install)."""
    return not is_jira_configured() and not is_llm_configured() and not USE_MOCK_DATA


# ---------------------------------------------------------------------------
# Bootstrap — called explicitly by entry points, never on import
# ---------------------------------------------------------------------------

_initialized: bool = False


def init(*, generate_api_key: bool = False) -> None:
    """
    Prepare configuration for an application run.

    Creates `data/` and loads `.env`. Safe to call more than once: the load
    happens on the first call only, so a Streamlit rerun does not re-read the
    file on every interaction. Use `reload()` to force a re-read.

    Args:
        generate_api_key: Create and persist an API key if none exists. Only
            the API server needs this; the dashboard offers it as an explicit
            button instead, so that merely opening the UI never writes to .env.
    """
    global _initialized

    if not _initialized:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        reload()
        _initialized = True

    if generate_api_key:
        ensure_api_key()


def is_initialized() -> bool:
    """True once init() has run in this process."""
    return _initialized
