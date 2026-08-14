"""
Shared test fixtures — filesystem sandbox and repo write guard.

Every path config exposes (DATA_DIR, CHROMA_DB_DIR, ENV_FILE, ...) is derived
from BASE_DIR, which config resolves ONCE at import time from the DRA_BASE_DIR
environment variable. So the redirection below has to happen at module scope,
before anything imports defect_risk_analyzer — a fixture would run far too late.

No test in this suite may touch the network, ChromaDB, Jira or an LLM API.
The sandbox enforces the filesystem half of that; the individual tests inject
stubs for the rest.
"""

import os
import shutil
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
    """
    from defect_risk_analyzer import config

    # MODULE_MAP_FILE is read, never written, but the guard is still the right
    # place for it: under the sandbox it points at an empty temp directory, so
    # a test that forgets to pass an explicit map raises ModuleMapMissing
    # instead of silently reading — and depending on — the developer's own
    # committed module-map.json.
    for name in ("BASE_DIR", "DATA_DIR", "CHROMA_DB_DIR", "ENV_FILE", "MODULE_MAP_FILE"):
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
