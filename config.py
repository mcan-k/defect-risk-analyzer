"""
Centralized configuration loaded from .env file.

All application settings are defined here with type validation and sensible defaults.
Import this module anywhere you need configuration values.
"""

import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
ENV_FILE = BASE_DIR / ".env"

# Ensure data directory exists
DATA_DIR.mkdir(exist_ok=True)

# Load .env file
load_dotenv(ENV_FILE)


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


# ---------------------------------------------------------------------------
# Jira Connection
# ---------------------------------------------------------------------------
JIRA_URL: str = _get_env("JIRA_URL")
JIRA_EMAIL: str = _get_env("JIRA_EMAIL")
JIRA_API_TOKEN: str = _get_env("JIRA_API_TOKEN")
JIRA_PROJECT_KEY: str = _get_env("JIRA_PROJECT_KEY")

# ---------------------------------------------------------------------------
# LLM Provider (BYOK)
# ---------------------------------------------------------------------------
LLM_PROVIDER: str = _get_env("LLM_PROVIDER", "groq").lower()
GROQ_API_KEY: str = _get_env("GROQ_API_KEY")
OPENAI_API_KEY: str = _get_env("OPENAI_API_KEY")
LLM_MODEL: str = _get_env("LLM_MODEL")

# Provider-specific defaults
DEFAULT_GROQ_MODEL: str = "llama-3.3-70b-versatile"
DEFAULT_OPENAI_MODEL: str = "gpt-4o-mini"


def get_llm_model() -> str:
    """Return the configured or default model name for the active provider."""
    if LLM_MODEL:
        return LLM_MODEL
    if LLM_PROVIDER == "openai":
        return DEFAULT_OPENAI_MODEL
    return DEFAULT_GROQ_MODEL


# ---------------------------------------------------------------------------
# API Security
# ---------------------------------------------------------------------------
def _ensure_api_key() -> str:
    """Return existing API key or auto-generate one and persist to .env."""
    key = _get_env("API_KEY")
    if key:
        return key

    # Generate a cryptographically secure key
    new_key = secrets.token_urlsafe(32)

    # Append to .env so it persists across restarts
    try:
        with open(ENV_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n# Auto-generated API key\nAPI_KEY={new_key}\n")
    except OSError:
        pass  # Container or read-only FS — key lives in memory only

    os.environ["API_KEY"] = new_key
    return new_key


API_KEY: str = _ensure_api_key()

# ---------------------------------------------------------------------------
# Rate Limiting & Cost Control
# ---------------------------------------------------------------------------
MAX_DAILY_REQUESTS: int = _get_env_int("MAX_DAILY_REQUESTS", 50)
GROQ_SLEEP: float = float(_get_env("GROQ_SLEEP", "2"))
MAX_RETRIES: int = _get_env_int("MAX_RETRIES", 2)

# ---------------------------------------------------------------------------
# Mock Data Mode
# ---------------------------------------------------------------------------
USE_MOCK_DATA: bool = _get_env_bool("USE_MOCK_DATA", False)

# ---------------------------------------------------------------------------
# Data File Paths
# ---------------------------------------------------------------------------
BUGS_FILE: Path = DATA_DIR / "bugs.json"
SAMPLE_BUGS_FILE: Path = DATA_DIR / "sample_bugs.json"
ANALYSIS_RESULTS_FILE: Path = DATA_DIR / "analysis_results.json"
DEFECT_DENSITY_FILE: Path = DATA_DIR / "defect_density.json"
ANON_MAP_FILE: Path = DATA_DIR / "anon_map.json"
WEBHOOK_RESULTS_FILE: Path = DATA_DIR / "webhook_results.json"
CHROMA_DB_DIR: Path = DATA_DIR / "chroma_db"

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
API_HOST: str = _get_env("API_HOST", "0.0.0.0")
API_PORT: int = _get_env_int("API_PORT", 8000)
STREAMLIT_PORT: int = _get_env_int("STREAMLIT_PORT", 8501)
LOG_LEVEL: str = _get_env("LOG_LEVEL", "INFO").upper()

# ---------------------------------------------------------------------------
# Risk Score Thresholds
# ---------------------------------------------------------------------------
RISK_CRITICAL: int = 80
RISK_HIGH: int = 60
RISK_MEDIUM: int = 35


def get_risk_level(score: int) -> str:
    """Map a numeric risk score to a human-readable level."""
    if score >= RISK_CRITICAL:
        return "CRITICAL"
    if score >= RISK_HIGH:
        return "HIGH"
    if score >= RISK_MEDIUM:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Validation helpers (used by Settings page and startup checks)
# ---------------------------------------------------------------------------
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
