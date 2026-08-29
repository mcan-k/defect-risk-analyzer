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

import logging
import os
import secrets
import stat
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# The codec for .env, on both the read and the write side. Named once because
# the two sides disagreeing is silent: python-dotenv reads UTF-8 (load_dotenv's
# default, forwarded to DotEnv), while an open() without an explicit encoding
# falls back to the locale codec — cp1254 on a Turkish Windows install. A Jira
# e-mail or a project name with a non-ASCII character would round-trip through
# two different codecs and come back mangled, or raise on the next read.
_ENV_ENCODING = "utf-8"

# Left on a duplicate line that is being retired. The line is commented rather
# than deleted: dotenv ignores comments, so the duplicate stops competing, but
# nothing is destroyed — .env holds credentials and a bad line-removal rule is
# not something the user can undo.
_DUPLICATE_MARKER = "# [duplicate removed by set_env_value]"

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
SAMPLE_BUGS_EN_FILE: Path = DATA_DIR / "sample_bugs_en.json"
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


# The credentials that may live in the OS credential store instead of `.env`.
# Everything else in `.env` is a setting, not a secret, and stays in the file.
STORED_SECRET_KEYS = ("JIRA_API_TOKEN", "GROQ_API_KEY", "OPENAI_API_KEY", "API_KEY")

# Resolved once per process. THE HANDLE IS CACHED, THE VALUES ARE NOT — see
# _get_secret. Resolving means importing keyring, which is why it is deferred
# until something actually needs it.
_secret_store = None
_secret_store_code: str = ""
_secret_store_params: dict = {}
_secret_store_resolved: bool = False


def secret_store() -> tuple[object | None, str, dict]:
    """The credential store for this process, plus which layer it is.

    `None` is a supported outcome, not a failure: no `desktop` extra installed,
    or a keyring that resolved a backend which cannot store anything.

    The layer arrives as a `(code, params)` pair, not a sentence. Which layer is
    in use is shown to the user, and a sentence built in the adapter could not
    be translated — `ui/messages.py` renders these codes. This module passes
    them through and knows nothing about wording either.

    The import lives in `adapters.secrets` and this module is the only caller
    that matters, which fixes the direction of the dependency: `config` imports
    the adapter, never the reverse. `adapters.results_repository` and
    `adapters.vector_store` both import `config`, so an import back from the
    secrets adapter would close a cycle — that is why the migration logic below
    lives here rather than in the adapter, and why
    `test_the_adapter_never_imports_config` checks it instead of a comment
    claiming it.
    """
    global _secret_store, _secret_store_code, _secret_store_params
    global _secret_store_resolved

    if not _secret_store_resolved:
        from defect_risk_analyzer.adapters import secrets

        _secret_store, _secret_store_code, _secret_store_params = secrets.resolve_store()
        _secret_store_resolved = True

    return _secret_store, _secret_store_code, _secret_store_params


def _get_secret(key: str) -> str:
    """A credential from `.env`, falling back to the credential store.

    `.env` WINS when it holds a value, and the store is not consulted at all.
    It is the explicit, visible, hand-editable layer; the store fills its gaps.
    Two consequences, both intended: a half-finished migration keeps working,
    because both places hold the same value; and a key someone pastes into the
    file takes effect. The cost — a stale hand-written value silently shadowing
    a newer one in the store — is recorded in docs/KNOWN-DEBT.md.

    Nothing here is cached. 6A closed a bug where a save reported success and
    the next reload() handed back the old value; memoising what the store
    returned would rebuild it one layer over, where the file on disk would look
    correct the whole time.
    """
    value = _get_env(key)
    if value:
        return value

    store, _, _ = secret_store()
    if store is None:
        return ""

    return store.get(key) or ""


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


def _is_assignment_line(line: str, key: str) -> bool:
    """True if `line` is the assignment dotenv would read for `key`.

    Comments are never assignments, and the `{key}=` prefix is the whole reason
    why: a commented line starts with `#`, so it cannot match. The writer used
    to carry an explicit `# {key}=` branch as well, which made a comment a valid
    write target — that is what turned documentation into a live setting, and it
    also left a loop open, since the retired duplicates below are commented out
    and would be selected again on the next write. dotenv never reads a comment,
    so a comment can never be the effective value either.

    An explicit `startswith("#") -> False` guard stood here briefly. The
    mutation audit removed it and not one test went red: the `{key}=` prefix
    already covers every commented form, so the guard could not fail. It was
    dropped rather than kept as decoration — a line no test can kill is a line
    that documents an intention it does not enforce. What enforces it is
    test_t5 and test_t6 against the mutation that restores the old branch.

    The trailing `=` carries the other half: without it `USE_MOCK_DATA` would
    also match `USE_MOCK_DATA_EXTRA`.
    """
    # Comment lines are excluded on purpose, by the `=` suffix alone: `# KEY=`
    # does not start with `KEY=`. Loosen this match — case-insensitivity, a
    # regex, a wider strip — and comments become write targets again, which is
    # both the overwritten-documentation bug and the retire-your-own-marker
    # loop. test_t5 and test_t6 are what hold that shut.
    return line.strip().startswith(f"{key}=")


def _is_retired_assignment_line(line: str, key: str) -> bool:
    """True if `line` is an assignment for `key` that this writer retired.

    Both halves are required: the `# ` comment form AND the marker this module
    wrote. Neither alone is enough — a hand-written `# API_KEY=notes` is the
    user's own comment, and the marker on some other key's line is not ours to
    touch.

    SEPARATE FROM `_is_assignment_line` ON PURPOSE, and it must stay separate.
    That predicate refuses to match comments, which is what stops the writer
    from overwriting documentation and from re-retiring its own retired lines
    forever (test_t5, test_t6). Loosening it to reach these lines would reopen
    both. This one is consulted only by the emptying path below, which writes no
    markers and therefore cannot loop.
    """
    stripped = line.strip()
    if _DUPLICATE_MARKER not in stripped or not stripped.startswith("#"):
        return False
    return stripped.lstrip("#").strip().startswith(f"{key}=")


def _line_terminator(lines: list[str]) -> str:
    """The terminator the file already uses, for a line being appended.

    Read from the end because that is where the append lands. Falls back to LF
    for an empty or terminator-less file. Existing lines keep their own
    terminator; nothing here rewrites them.
    """
    for line in reversed(lines):
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n"):
            return "\n"
        if line.endswith("\r"):
            return "\r"
    return "\n"


def _split_terminator(line: str) -> tuple[str, str]:
    """Split a line into its content and its terminator."""
    for terminator in ("\r\n", "\n", "\r"):
        if line.endswith(terminator):
            return line[: -len(terminator)], terminator
    return line, ""


def _atomic_write_lines(lines: list[str]) -> None:
    """Replace `.env` with `lines`, or leave it exactly as it was.

    A half-written `.env` is a lost Jira token and a lost API key, so the new
    content goes to a sibling temp file first and `os.replace` swaps it in as
    one step. Sibling, not the system temp directory: `os.replace` is only
    atomic within a filesystem.

    The temp file is named predictably (`.env.tmp`) so a crash leaves something
    a human can recognise rather than a random `tmp*` blob — and `.gitignore`
    and `.dockerignore` can both cover it by name.

    Permission bits are carried over explicitly. Without that the file silently
    changes mode on POSIX: a fresh `open()` lands on the umask default (0644)
    and `NamedTemporaryFile` on 0600, so a `.env` the user locked down to 0640
    would drift either way. Windows does not model these bits — measured: every
    file there reports 0o666 — so the call is a no-op there, not a hazard.

    `newline=""` on both the read and this write is what keeps CRLF a CRLF file
    and LF an LF file. Python's default would translate every terminator in the
    file to os.linesep, rewriting lines nobody touched.
    """
    tmp_file = ENV_FILE.with_name(f"{ENV_FILE.name}.tmp")
    try:
        with open(tmp_file, "w", encoding=_ENV_ENCODING, newline="") as f:
            f.writelines(lines)

        if ENV_FILE.exists():
            os.chmod(tmp_file, stat.S_IMODE(os.stat(ENV_FILE).st_mode))

        os.replace(tmp_file, ENV_FILE)
    finally:
        # Only reachable when the write or the replace failed: a successful
        # replace consumes the temp file. A partial .env.tmp must not survive.
        if tmp_file.exists():
            tmp_file.unlink()


def set_env_value(key: str, value: str) -> None:
    """
    Write a single key to `.env`, collapsing duplicates onto the live line.

    THE BUG THIS CLOSES. The writer used to update the FIRST matching line and
    stop, while `python-dotenv` builds its dict in file order and lets the LAST
    occurrence win. On a file with the key twice the two halves aimed at
    different lines: the Settings page reported a successful save, `os.environ`
    agreed, and the next `reload()` quietly restored the old value. The live
    `.env` in this repo has exactly that shape — two filled, different
    `API_KEY=` lines — so "API Key Yenile" was a no-op across a restart.

    So the write targets the LAST assignment, the one dotenv already reads.
    That ordering is also the safe failure mode: if anything goes wrong after
    the value lands, the line the application reads is still the line just
    written.

    Earlier occurrences are commented out, not deleted. Deleting a credential
    line is not something a user can undo, and the point of this function is to
    stop losing values, not to start losing them differently.

    Also updates `os.environ` so the new value is visible immediately, before
    any `reload()`.
    """
    lines: list[str] = []
    if ENV_FILE.exists():
        with open(ENV_FILE, encoding=_ENV_ENCODING, newline="") as f:
            lines = f.readlines()

    matches = [i for i, line in enumerate(lines) if _is_assignment_line(line, key)]

    # EMPTYING IS NOT AN ORDINARY WRITE. Retiring a duplicate by commenting it
    # out moves the value out of dotenv's reach but leaves it on the disk, and
    # `_is_assignment_line` never matches a comment, so nothing here could ever
    # reach it again — the value would be stranded permanently, not briefly.
    # That is acceptable when a real value is being written (the retired line
    # documents what was replaced) and wrong when the whole point of the write
    # is that the value must stop existing, which is what the keyring migration
    # does. So an empty write blanks instead of preserving, on both the
    # duplicates it retires now and the ones an earlier write already retired.
    emptying = value == ""

    if emptying:
        for index, line in enumerate(lines):
            if _is_retired_assignment_line(line, key):
                _, terminator = _split_terminator(line)
                lines[index] = f"# {key}=  {_DUPLICATE_MARKER}{terminator}"

    if matches:
        target = matches[-1]
        _, terminator = _split_terminator(lines[target])
        lines[target] = f"{key}={value}{terminator}"

        for index in matches[:-1]:
            content, terminator = _split_terminator(lines[index])
            if emptying:
                lines[index] = f"# {key}=  {_DUPLICATE_MARKER}{terminator}"
            else:
                lines[index] = f"# {content}  {_DUPLICATE_MARKER}{terminator}"
    else:
        terminator = _line_terminator(lines)
        # A file whose last line has no terminator would otherwise get the new
        # assignment glued onto it, producing one corrupt line out of two.
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += terminator
        lines.append(f"{key}={value}{terminator}")

    _atomic_write_lines(lines)

    os.environ[key] = str(value)


def migrate_secrets_to_store() -> dict[str, object]:
    """Move any credential still sitting in `.env` into the credential store.

    THE ORDER IS THE CONTRACT: write to the store, read it back and verify, then
    empty `.env`, then clear a retired copy the 6A writer may have left in a
    comment. Nothing leaves `.env` until something else demonstrably holds it.

    THE READ-BACK IS NOT PARANOIA ABOUT OUR OWN CODE. `store.set()` reports
    whether the backend accepted the write, which is not the same as the value
    being retrievable afterwards, and the cost of confusing the two is a
    credential deleted from the only place that had it.

    IDEMPOTENT, because it runs at every startup. A key whose `.env` value is
    already empty has nothing to move and is skipped before any store call, so a
    second run neither rewrites the file nor re-issues a credential write.

    NO STORE MEANS NO MIGRATION. In Docker, in CI, and on a desktop without the
    `desktop` extra there is nowhere better to put the value, so it stays in
    `.env` in plain text. That is the intended behaviour and SECURITY.md scopes
    the guarantee to say so.

    Returns a report: `moved`, `not_moved` (the store refused it or lost it —
    `.env` untouched), `in_both` (stored, but `.env` could not be emptied, so
    the plain-text copy is still there), plus `code` and `params` naming the
    layer in use — rendered by `ui/messages.py`, never worded here.
    """
    store, code, params = secret_store()
    report: dict[str, object] = {
        "moved": [],
        "not_moved": [],
        "in_both": [],
        "code": code,
        "params": params,
    }
    if store is None:
        return report

    for key in STORED_SECRET_KEYS:
        value = _get_env(key)
        if not value:
            continue

        # The return value of set() is deliberately NOT branched on. A guard
        # stood here and the mutation audit removed it without turning a single
        # test red: a store that refuses the write has nothing to read back
        # either, so the check below already covers it — and it covers more,
        # because a store that reports failure while the value IS retrievable
        # (a previous partial run left it there) should count as a success, not
        # a failure. Dropped rather than kept as decoration, on the same
        # reasoning as the retired guard in _is_assignment_line.
        store.set(key, value)

        if store.get(key) != value:
            logger.warning(
                "%s was written to the credential store but did not read back; "
                "leaving it in .env.",
                key,
            )
            report["not_moved"].append(key)
            continue

        try:
            # Empties the live line AND blanks any retired duplicate carrying
            # the same secret — see the emptying branch in set_env_value.
            set_env_value(key, "")
        except OSError as exc:
            logger.warning(
                "%s is now in the credential store, but .env could not be "
                "updated (%s). The plain-text copy is still there.",
                key,
                type(exc).__name__,
            )
            report["in_both"].append(key)
            continue

        report["moved"].append(key)

    if report["moved"]:
        # The globals still hold what .env had before it was emptied; re-reading
        # is what routes them through the store from here on.
        reload()

    return report


def save_secret(key: str, value: str) -> str:
    """Store one credential in whichever layer is in use. Returns the layer.

    Writes to the store when there is one, and empties the `.env` line in the
    same step — otherwise the file would shadow what was just stored, because
    `_get_secret` lets a non-empty `.env` win. Without that, the first save
    after a migration would quietly put the credential back in plain text.

    FALLS BACK RATHER THAN FAILING. If the store refuses the write or loses it,
    the value goes to `.env`: a credential the user typed is not something to
    drop because the preferred layer misbehaved.
    """
    store, _, _ = secret_store()

    if store is not None and value:
        if store.set(key, value) and store.get(key) == value:
            set_env_value(key, "")
            return "store"
        logger.warning(
            "Could not store %s in the credential store; falling back to .env.", key
        )

    set_env_value(key, value)
    return "env"


def persist_language(code: str) -> None:
    """
    Persist the interface language and make it live for this process.

    `set_env_value` alone is not enough. It updates `.env` and `os.environ`,
    but `LANGUAGE` is a module global written only by `reload()`, and `init()`
    is guarded by `_initialized` — so a language chosen mid-session left
    `LANGUAGE` on whatever the process booted with, and `sample_bugs_file()`
    kept serving that boot language until a restart.

    Deliberately narrower than `reload()`. Both would fix `LANGUAGE`, but
    `reload()` re-reads every setting from disk, and a presentation control has
    no business re-reading Jira credentials or rate limits — nor picking up a
    half-finished `.env` edit as a side effect of a language toggle. This is
    the same shape `ensure_api_key()` uses: write the file, update the one
    global it owns.

    Nothing here touches the LLM provider. Only `AnalysisService.reset_llm()`
    does that, and it is not on this path — which is why the picker calls this
    rather than `ui.service.save_multiple_env()`.

    Lowercased once, so the file and the global cannot disagree: `reload()`
    lowercases what it reads, and a stored "EN" would mean one demo set now and
    the other after a restart.
    """
    global LANGUAGE

    code = code.strip().lower()
    set_env_value("DRA_LANGUAGE", code)
    LANGUAGE = code


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

# Interface language — the persisted choice, read by sample_bugs_file(). The
# live value for a browser session lives in st.session_state; see
# ui/language.py. Unlike every other global here it is also written outside
# reload(), by persist_language(): a language picked mid-session has to reach
# this variable, or the demo set stays on the boot language until a restart.
# Not validated here: ui/i18n.set_language() normalises an unknown code to the
# source language and logs it, and duplicating that check would mean two places
# to update when a locale is added.
LANGUAGE: str = "tr"

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
    global LANGUAGE
    global API_HOST, API_PORT, STREAMLIT_PORT, LOG_LEVEL

    # Re-read .env (override=True forces refresh)
    load_dotenv(ENV_FILE, override=True)

    JIRA_URL = _get_env("JIRA_URL")
    JIRA_EMAIL = _get_env("JIRA_EMAIL")
    JIRA_API_TOKEN = _get_secret("JIRA_API_TOKEN")
    JIRA_PROJECT_KEY = _get_env("JIRA_PROJECT_KEY")

    LLM_PROVIDER = _get_env("LLM_PROVIDER", "groq").lower()
    GROQ_API_KEY = _get_secret("GROQ_API_KEY")
    OPENAI_API_KEY = _get_secret("OPENAI_API_KEY")
    LLM_MODEL = _get_env("LLM_MODEL")

    # Read only — generating a key writes to .env, which reload() must not do.
    API_KEY = _get_secret("API_KEY")

    MAX_DAILY_REQUESTS = _get_env_int("MAX_DAILY_REQUESTS", 50)
    GROQ_SLEEP = float(_get_env("GROQ_SLEEP", "2"))
    MAX_RETRIES = _get_env_int("MAX_RETRIES", 2)

    USE_MOCK_DATA = _get_env_bool("USE_MOCK_DATA", False)
    ANONYMIZE_DATA = _get_env_bool("ANONYMIZE_DATA", True)

    LANGUAGE = _get_env("DRA_LANGUAGE", "tr").lower()

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


def sample_bugs_file() -> Path:
    """The demo bug set matching the PERSISTED interface language.

    Read from LANGUAGE, not from whatever a browser session currently shows,
    and that is a deliberate limit rather than an oversight.

    The dashboard's service handle is @st.cache_resource and loads bugs once
    per process. Making the demo set follow the live language would mean
    clearing that cache on every toggle, which means reloading and RE-INDEXING
    into ChromaDB. Faz 4(a) exists because indexing used to happen as a silent
    side effect of unrelated actions; a presentation control triggering it
    again would be the same mistake with a new trigger.

    So the language picker changes the interface immediately and the demo data
    follows on the next explicit sync or the next start. That promise needs
    persist_language() to hold: LANGUAGE used to move only at startup, so the
    sync half of it silently did nothing. Falls back to the Turkish set when
    the English one is absent: a missing translation should leave a working
    demo, not an empty bug list.
    """
    if LANGUAGE == "en" and SAMPLE_BUGS_EN_FILE.is_file():
        return SAMPLE_BUGS_EN_FILE
    return SAMPLE_BUGS_FILE


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

# True when THIS process deleted a leftover data/anon_map.json at startup. Read
# by the dashboard so the removal is reported somewhere a person actually looks
# — a log line alone would not be, and this is a silent deletion of user data.
LEGACY_ANON_MAP_REMOVED: bool = False


def _purge_legacy_anon_map() -> None:
    """Delete a `data/anon_map.json` left behind by a pre-Faz-6B version.

    That file was the anonymizer's token→original mapping, rewritten after every
    analysis and never pruned. It held whatever the patterns matched, in plain
    text — on the machine this was measured on, a Bearer token and an API key.
    Nothing writes it any more, so anything found here is a leftover.

    NEVER OPENED, only unlinked. Reporting how many entries it held, or which
    categories, would mean reading a file whose contents are the reason it is
    being deleted; a count is one refactor away from a value.

    RUNS ON EVERY START, with no marker file. The check is one `unlink` that
    normally raises FileNotFoundError and returns. A marker would be new surface
    that can go stale, and it would miss the case that matters: a user who
    downgrades, has the file recreated by the old code, and upgrades again.

    NEVER RAISES. A locked or read-only leftover must not take the application
    down — the anonymizer works without it, and refusing to start would trade a
    plain-text mapping for an unusable install.
    """
    global LEGACY_ANON_MAP_REMOVED

    LEGACY_ANON_MAP_REMOVED = False
    try:
        ANON_MAP_FILE.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning(
            "Could not remove the obsolete %s: %s. It holds anonymisation data "
            "in plain text; delete it by hand.",
            ANON_MAP_FILE.name,
            exc,
        )
        return

    LEGACY_ANON_MAP_REMOVED = True
    logger.warning(
        "Removed the obsolete %s. Versions before this one stored the "
        "anonymisation mapping there in plain text; it is no longer written.",
        ANON_MAP_FILE.name,
    )


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
        # Bound to `_initialized` deliberately: once per process is what is
        # wanted, and this is the one hook every shipped entry point reaches
        # (tests/test_entry_points.py holds that in CI). Note the coupling —
        # 5C showed this flag is easy to get wrong, and anything that changes
        # when the guard opens changes when the purge runs.
        _purge_legacy_anon_map()
        _initialized = True

    if generate_api_key:
        ensure_api_key()


def is_initialized() -> bool:
    """True once init() has run in this process."""
    return _initialized
