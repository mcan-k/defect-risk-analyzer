"""
Architectural boundary: no core module may import the webhook extra.

This is the only automated check of the rule Faz 2 established — that nothing
the dashboard or the CI analyzer loads reaches for fastapi/uvicorn or the api*
modules. Installing without requirements-webhook.txt does not produce a
fastapi-free environment (chromadb depends on it), so the separation is
verified at the loader level instead.

WHY A SUBPROCESS: the check works by installing a blocking finder on
sys.meta_path and then importing the core modules. `__import__` returns straight
from sys.modules for anything already imported — and under pytest, sibling test
modules have already imported defect_risk_analyzer.*, while chromadb may
already have pulled in fastapi. Run in-process, the blocker would never be
consulted and every assertion would pass vacuously. A clean interpreter is what
makes this test mean anything.

It fails rather than skips in every case, including when it cannot perform the
check at all. A silent skip would leave the rule unguarded while still showing
green.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = REPO_ROOT / "tests" / "tools" / "core_boundary_check.py"


def _run_check() -> subprocess.CompletedProcess:
    # PYTHONPATH must be passed explicitly: [tool.pytest.ini_options] pythonpath
    # applies to the pytest process only and does NOT reach a child interpreter.
    # Without it, a checkout with no `pip install -e .` fails with
    # ModuleNotFoundError — which reads like a boundary violation and sends the
    # next person hunting a bug that does not exist.
    #
    # Spread os.environ rather than passing a bare dict: the child still needs
    # PATH and SYSTEMROOT, and on Windows a stripped environment breaks the
    # interpreter outright.
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}

    return subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        capture_output=True,
        text=True,
        # The script prints Turkish status lines; under a cp1254 default locale
        # decoding them would raise.
        encoding="utf-8",
        env=env,
        cwd=str(REPO_ROOT),
    )


@pytest.fixture(scope="module")
def check_result() -> subprocess.CompletedProcess:
    """Run the check once — it imports the whole core tree, which is slow."""
    assert CHECK_SCRIPT.is_file(), f"boundary check script is missing: {CHECK_SCRIPT}"
    return _run_check()


def test_core_path_does_not_import_webhook_dependencies(check_result):
    """Every core module imports cleanly with fastapi/uvicorn/api* blocked."""
    result = check_result

    assert result.returncode == 0, (
        "core boundary check failed:\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    assert "CORE BOUNDARY CLEAN" in result.stdout


def test_the_blocker_is_actually_active(check_result):
    """Guards against the check silently degrading into a no-op.

    The script imports fastapi at the end and expects that to fail. If the
    blocker were inert, the core imports would all "pass" while verifying
    nothing — so a green run without this line proves nothing at all.
    """
    result = check_result

    assert "blocker aktif" in result.stdout, (
        "the import blocker did not report itself active, so the boundary "
        "check above verified nothing:\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    assert "blocker inert" not in result.stdout
