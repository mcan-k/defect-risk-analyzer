"""
Shared test fixtures — filesystem sandbox and repo write guard.

Every path config exposes (DATA_DIR, CHROMA_DB_DIR, ENV_FILE, ...) is derived
from BASE_DIR, which config resolves ONCE at import time from the DRA_BASE_DIR
environment variable. So the redirection below has to happen at module scope,
before anything imports defect_risk_analyzer — a fixture would run far too late.

No test in this suite may touch the network, ChromaDB, Jira, an LLM API or the
operating system's credential store. The sandbox enforces the filesystem half
of that and blocks the credential store outright; the individual tests inject
stubs for the rest.

MONKEYPATCHING A MODULE GLOBAL: check how many the production path writes.
`monkeypatch` restores what it recorded, and nothing else. Twice now a test has
patched part of a group of globals, let production code run, and left the rest
set — and both times the failure appeared in a DIFFERENT file, where nobody was
looking for it:

  * `monkeypatch.delenv(key, raising=False)` on an already-absent key records
    nothing to undo, so the values `load_dotenv` then wrote into `os.environ`
    survived teardown and flipped the Settings page from "create" to "rotate".
  * `config.secret_store()` assigns four globals; a test patched two of them,
    and the other two leaked a fake backend name into a page caption.

So: before patching one name, look at what the code under test assigns, and
record all of it. A leak here is not caught by the sandbox — the paths stay
inside it — and it does not fail where it was caused.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Sandbox — must precede any defect_risk_analyzer import
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]

_SANDBOX = Path(tempfile.mkdtemp(prefix="dra-tests-"))
os.environ["DRA_BASE_DIR"] = str(_SANDBOX)

# The real sample data, read from the repo rather than through config: the line
# above has just pointed config.SAMPLE_BUGS_FILE at the empty sandbox.
SAMPLE_BUGS = REPO_ROOT / "data" / "sample_bugs.json"

# Repo path that must never be created or modified by a test run.
REPO_CHROMA_DIR = REPO_ROOT / "data" / "chroma_db"

import pytest  # noqa: E402  (import order is load-bearing; see above)


class _KeyringBlocker:
    """Meta path finder that refuses `keyring` for the whole session.

    WHAT IT PREVENTS. `adapters.secrets.resolve_store()` imports keyring and,
    on a machine that has it, resolves the real OS credential store. Faz 6B puts
    a credential migration in `bootstrap()`, and `test_dashboard_language.py`
    writes a `.env` carrying synthetic tokens, resets `_initialized` and runs the
    real `bootstrap()` through AppTest. Without this, those tests would write
    their fixtures into the developer's own Windows Credential Manager and empty
    the sandbox `.env`. It is a no-op on this machine and in CI only because
    keyring is absent there — which is luck, not a guarantee, and the machines
    where it is installed are exactly the machines this feature is for.

    A BLOCKER RATHER THAN A MONKEYPATCH. Patching
    `adapters.secrets.resolve_store` would be escaped by any caller that did
    `from ...secrets import resolve_store`, binding the original before the
    patch. Refusing the import reaches every caller however it was written.
    Same shape as `tests/tools/core_boundary_check.py`, for the same reason.

    `sys.modules` IS LEFT ALONE on purpose. Inserting `sys.modules["keyring"] =
    None` would also block the import, but it would make
    `test_secrets_adapter.py`'s `"keyring" not in sys.modules` audit pass for
    the wrong reason — the key would be present. This raises without recording
    anything, so that audit keeps measuring what it says.
    """

    def find_module(self, fullname, path=None):
        return self.find_spec(fullname, path)

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "keyring" or fullname.startswith("keyring."):
            raise ImportError(
                f"SANDBOX: a test tried to import '{fullname}'. No test may reach "
                "the OS credential store; inject a fake at the adapters.secrets "
                "boundary instead (see tests/test_secrets_adapter.py)."
            )
        return None


sys.meta_path.insert(0, _KeyringBlocker())


@pytest.fixture(scope="session")
def sandbox_dir() -> Path:
    """The temporary BASE_DIR every config path resolves under."""
    return _SANDBOX


@pytest.fixture(scope="session")
def sample_bugs_path() -> Path:
    """Path to the committed sample bug set, in the repo (not the sandbox)."""
    return SAMPLE_BUGS


@pytest.fixture(scope="session")
def repo_module_map_path() -> Path:
    """Path to the committed module map, in the repo (not the sandbox).

    Same reason as sample_bugs_path: config.MODULE_MAP_FILE points at the empty
    sandbox, so the shipped file is only reachable from the repo root. Only the
    tests that assert what the shipped map says should use this — everything
    else builds a ModuleMap in memory, which keeps the rule under test separate
    from the data that happens to be committed.
    """
    return REPO_ROOT / "module-map.json"


@pytest.fixture(autouse=True, scope="session")
def _assert_sandboxed():
    """Fail the session if config resolved any path inside the repo.

    This is a guard, not a convenience: a test that writes into the working
    tree corrupts the developer's data/ and can leave data/chroma_db behind.
    It fails rather than skips — an unverifiable sandbox is a failure.

    TWO AXES, and only one of them is paths. This fixture covers the filesystem;
    the OS credential store is a separate axis with a separate mechanism
    (`_KeyringBlocker` above), because a path guard cannot see it — a credential
    does not live at a path this or any other assertion could resolve. Both are
    part of the same promise in the module docstring, and neither substitutes
    for the other.
    """
    from defect_risk_analyzer import config

    # MODULE_MAP_FILE is read, never written, but the guard is still the right
    # place for it: under the sandbox it points at an empty temp directory, so
    # a test that forgets to pass an explicit map raises ModuleMapMissing
    # instead of silently reading — and depending on — the developer's own
    # committed module-map.json.
    # ANON_MAP_FILE is listed because config.init() now DELETES it (Faz 6B:
    # a pre-6B leftover holds the anonymisation mapping in plain text). Every
    # entry point reaches init(), and 18 calls to it live in this suite, so an
    # escaped path would not merely write into the working tree — it would
    # remove the developer's own file. It resolves under DATA_DIR today and is
    # therefore covered transitively, but "covered transitively" is an argument,
    # not a check, and this guard exists to replace arguments with checks.
    for name in (
        "BASE_DIR",
        "DATA_DIR",
        "CHROMA_DB_DIR",
        "ENV_FILE",
        "MODULE_MAP_FILE",
        "ANON_MAP_FILE",
    ):
        resolved = Path(getattr(config, name)).resolve()
        assert resolved != REPO_ROOT and REPO_ROOT not in resolved.parents, (
            f"config.{name} resolved to {resolved}, which is inside the repo. "
            "The DRA_BASE_DIR sandbox did not take effect — refusing to run "
            "tests that would write into the working tree."
        )


@pytest.fixture(autouse=True, scope="session")
def _guard_repo_chroma_dir():
    """Assert the run neither creates nor modifies the repo's ChromaDB dir.

    USE_MOCK_DATA does NOT disable ChromaDB — it is read only by jira_client and
    selects the data source. VectorStore writes regardless. This check is what
    makes "no test touches the repo's vector store" verifiable instead of
    assumed.
    """
    existed = REPO_CHROMA_DIR.exists()
    before = REPO_CHROMA_DIR.stat().st_mtime if existed else None

    yield

    if not existed:
        assert not REPO_CHROMA_DIR.exists(), (
            f"{REPO_CHROMA_DIR} was created during the test run. Something "
            "constructed a real VectorStore against the repo path."
        )
    else:
        assert REPO_CHROMA_DIR.stat().st_mtime == before, (
            f"{REPO_CHROMA_DIR} was modified during the test run. Something "
            "wrote to the repo's vector store."
        )


def pytest_sessionfinish(session, exitstatus):
    """Remove the sandbox. Best-effort: a leaked temp dir must not fail a run."""
    shutil.rmtree(_SANDBOX, ignore_errors=True)
