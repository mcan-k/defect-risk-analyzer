"""
Centralized configuration loaded from .env file.

All application settings are defined here with type validation and sensible defaults.
Import this module anywhere you need configuration values.

Supports live reload via reload() — Settings page calls this after saving
so changes take effect immediately without restarting the application.
"""

import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths (these never change)
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
ENV_FILE = BASE_DIR / ".env"

# Ensure data directory exists
DATA_DIR.mkdir(exist_ok=True)

# Data File Paths (static)
BUGS_FILE: Path = DATA_DIR / "bugs.json"
SAMPLE_BUGS_FILE: Path = DATA_DIR / "sample_bugs.json"
ANALYSIS_RESULTS_FILE: Path = DATA_DIR / "analysis_results.json"
DEFECT_DENSITY_FILE: Path = DATA_DIR / "defect_density.json"
ANON_MAP_FILE: Path = DATA_DIR / "anon_map.json"
WEBHOOK_RESULTS_FILE: Path = DATA_DIR / "webhook_results.json"
CHROMA_DB_DIR: Path = DATA_DIR / "chroma_db"

# Risk Score Thresholds (static)
RISK_CRITICAL: int = 80
RISK_HIGH: int = 60
RISK_MEDIUM: int = 35


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


def _ensure_api_key() -> str:
    """Return existing API key or auto-generate one and persist to .env."""
    key = _get_env("API_KEY")
    if key:
        return key

    new_key = secrets.token_urlsafe(32)

    try:
        with open(ENV_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n# Auto-generated API key\nAPI_KEY={new_key}\n")
    except OSError:
        pass

    os.environ["API_KEY"] = new_key
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

    API_KEY = _ensure_api_key()

    MAX_DAILY_REQUESTS = _get_env_int("MAX_DAILY_REQUESTS", 50)
    GROQ_SLEEP = float(_get_env("GROQ_SLEEP", "2"))
    MAX_RETRIES = _get_env_int("MAX_RETRIES", 2)

    USE_MOCK_DATA = _get_env_bool("USE_MOCK_DATA", False)

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


def get_risk_level(score: int) -> str:
    """Map a numeric risk score to a human-readable level."""
    if score >= RISK_CRITICAL:
        return "CRITICAL"
    if score >= RISK_HIGH:
        return "HIGH"
    if score >= RISK_MEDIUM:
        return "MEDIUM"
    return "LOW"


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
# Initial load on import
# ---------------------------------------------------------------------------
reload()
