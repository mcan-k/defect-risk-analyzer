"""
The Windows launcher must not edit `.env` after creating it.

WHY THIS EXISTS. BASLAT.bat used to append `USE_MOCK_DATA=True` to the end of
`.env` on every fresh install, guarded by `findstr /C:"USE_MOCK_DATA=True"`.
Both halves were wrong:

  * `.env.example` ships `USE_MOCK_DATA=False`, and `findstr /C:` is a literal,
    case-sensitive match (measured), so the guard never matched on a fresh
    install and the append always fired. Every fresh Windows install ended up
    with a duplicated key — the exact shape `config.set_env_value` used to
    silently mis-write.
  * `USE_MOCK_DATA=True` also makes `config.is_first_run()` return False
    (measured), and `ui/shell.py` gates the setup wizard on it. So the launcher
    silently answered the wizard's first question on the user's behalf and then
    skipped the wizard.

The rule is therefore broader than the one bug: the launcher creates `.env`
(by copying `.env.example`) and then leaves it alone. Anything else is the
installer making configuration decisions for the user, and an append is how
duplicates get generated in the first place.

Structural, not textual: the lines are parsed for a `>>` redirection and its
target, rather than searched for a phrase. Comparing against rendered text has
produced three wrong answers in this project already.
"""

from pathlib import Path

import pytest

# The launcher lives in the repo, not under the config sandbox: conftest points
# every config path at a temporary directory, so the shipped file is only
# reachable from the repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_FILES = sorted(REPO_ROOT.glob("*.bat"))


def append_target(line: str) -> str | None:
    """The file a line appends to with `>>`, or None if it does not append.

    Handles `>> .env` and `>>.env` alike. `>>` is checked before `>`: a single
    `>` truncates and is how the file is legitimately created, while `>>` is
    the operation that grows a file and so the one that can duplicate a key.
    """
    if ">>" not in line:
        return None
    tail = line.split(">>", 1)[1].strip()
    if not tail:
        return None
    return tail.split()[0].strip('"').lower()


def test_batch_files_exist():
    """A guard whose subject vanished would pass silently."""
    assert [p.name for p in BATCH_FILES] == ["BASLAT.bat", "DURDUR.bat"]


@pytest.mark.parametrize("batch_file", BATCH_FILES, ids=lambda p: p.name)
def test_t14_the_launcher_never_appends_to_env(batch_file):
    """T14 — EXPECTED RED before the fix, on BASLAT.bat.

    `.env` is created by copying `.env.example` and is not touched again. The
    historical violation is `echo USE_MOCK_DATA=True>> .env`.
    """
    offenders = []
    for number, line in enumerate(batch_file.read_text(encoding="utf-8").splitlines(), 1):
        if append_target(line) == ".env":
            offenders.append(f"{batch_file.name}:{number}: {line.strip()}")

    assert offenders == [], (
        "the launcher appends to .env, which is how a duplicated key is born: "
        f"{offenders}"
    )
