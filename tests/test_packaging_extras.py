"""
Every extra this project documents must actually be declared.

WHY. Faz 6B put `keyring` behind an optional `desktop` extra and wrote that name
into eight source files, four test files, SECURITY.md, README.md and both locale
catalogs — including the sentence the Settings page shows a user whose
credentials are still in plain text: "install the `desktop` extra". The extra was
never declared. `pyproject.toml` provided `webhook` and nothing else.

WHAT THAT LOOKS LIKE TO A USER, measured rather than assumed: pip does not fail
on an extra a project does not provide. `pip install -e ".[desktop]"` exits 0 and
prints `Successfully installed`, with one `WARNING: ... does not provide the
extra 'desktop'` line in the middle of the build output. Nothing is installed, so
the Settings page repeats the same instruction, and the user has no way to tell
the instruction is the problem. A silent success is exactly the class of failure
a guard is for: it cannot be caught by reading the file that is missing.

WHAT THIS HOLDS. The declared set, not one name. `desktop` is the extra that was
missing today, but the failure was structural — a plan named a file and no
closing measurement looked for it — so the guard matches the whole table against
a measured set and a new extra has to be added here deliberately, the same way
`test_entry_points.py` carries `EXPECTED_ENTRY_POINTS`.

BOTH DECLARATION FORMS ARE READ. This project declares extras dynamically
(`[tool.setuptools.dynamic.optional-dependencies]`, one requirements file each),
but a static `[project.optional-dependencies]` table is the other legal spelling.
Reading only the form in use today would make the guard silently blind the moment
someone switched, which is the same silence it exists to remove.

DECLARED BLIND SPOT. This does not read SECURITY.md, README.md or the locale
catalogs, so an extra documented under a name nobody declared is still only
caught if the name reaches `EXPECTED_EXTRAS`. Parsing prose for install commands
was considered and refused: the match would be fragile in both directions, and
the cheap half of the protection is here.
"""

import tomllib
from pathlib import Path

# The repo, not the config sandbox: conftest points every config path at a
# temporary directory, so the shipped tree is only reachable from here.
REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"

# Measured against pyproject.toml, and deliberately hand-held: adding an extra
# means adding it here too.
EXPECTED_EXTRAS = {"webhook", "desktop"}


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _dynamic_extras(data: dict) -> dict:
    """`[tool.setuptools.dynamic.optional-dependencies]` — name → table."""
    return (
        data.get("tool", {})
        .get("setuptools", {})
        .get("dynamic", {})
        .get("optional-dependencies", {})
    )


def _declared_extras(data: dict) -> set[str]:
    """Every extra name, in either spelling. See the module docstring."""
    return set(_dynamic_extras(data)) | set(data.get("project", {}).get(
        "optional-dependencies", {}
    ))


def test_declared_extras_match_the_expected_set():
    """The table is the assertion, not one name.

    A missing entry here is what shipped in 6B: the name is real everywhere
    except the one file that makes `pip install ".[name]"` do something.
    """
    assert _declared_extras(_pyproject()) == EXPECTED_EXTRAS


def test_every_dynamic_extra_points_at_a_file_that_exists():
    """A dynamic extra naming an absent file installs nothing, and says so once.

    setuptools reads the requirements file at build time. A typo, or a file that
    was planned and never written, produces an extra that exists in the metadata
    and delivers nothing — one step quieter than 6B's failure, not one step
    louder.
    """
    for name, table in sorted(_dynamic_extras(_pyproject()).items()):
        for target in table.get("file", []):
            path = REPO_ROOT / target
            assert path.is_file(), f'extra "{name}" names a missing file: {target}'
