"""
Every entry point must reach `config.init()`.

WHY. Skipping `init()` does not raise and does not warn: every setting keeps
its module-level default, so a fully configured install is served as if nothing
were configured (tests/test_config_init.py documents that behaviour). Nothing
in the running process catches it. This guard catches it before shipping
instead, at the only moment the mistake is cheap — adding a new entry point.

WHAT COUNTS AS AN ENTRY POINT. Four explicit patterns. The guard matches
patterns; it does not guess. Faz 4's false positives came from `ci_analyzer`
inferring a module from a filename, and that is the class of cleverness being
avoided here.

  1. A module under `src/` with a top-level `if __name__ == "__main__":` block.
  2. A `[project.scripts]` target in pyproject.toml (`module:function`).
  3. A Streamlit page script: `ui/app.py`, plus the files in `ui/pages/` that
     Streamlit itself treats as pages.
  4. A tool under `tests/tools/` with a `__main__` block THAT IMPORTS `config`
     DIRECTLY.

Pattern 3 does not carry a hand-written exception list. It reuses Streamlit's
own rule, read from the installed source (streamlit 1.41.1,
`source_util.py:148-155`):

    for f in pages_dir.glob("*.py")
    if not f.name.startswith(".") and not f.name == "__init__.py"

So `pages/__init__.py` drops out because the framework does not run it, not
because this file names it. Note the rule is narrower than "skip anything
starting with an underscore": Streamlit *does* serve `pages/_helper.py` as a
page, so this guard inspects it too.

DIRECT IMPORT, for pattern 4, means any of these reaching the `config` module
itself, matched on the AST rather than by searching the source text:
`import ...config`, `from ... import config`, `from ...config import X`.

DECLARED BLIND SPOTS. These are limits of the guard, stated so that nobody
mistakes a green run for a proof:

  * Indirect config users are not seen. `tests/tools/chroma_cleanup.py` reaches
    config through `adapters.vector_store`, and `tests/tools/module_map_report.py`
    through `ci_analyzer`. Walking the import graph to find them would be the
    guessing this guard refuses to do. Both were measured and are harmless
    today; see docs/KNOWN-DEBT.md for the measurement and the trigger.
  * A conditional `init()` passes. The guard sees the call, not the path, so a
    module that calls `init()` only inside one branch is accepted.
  * Dynamic dispatch (`getattr`, a registry, a plugin hook) is invisible.
  * A module run with `python -m` but without a `__main__` block is not matched
    by pattern 1.
  * A consumer importing this package from outside the repo is out of reach
    entirely.
"""

import ast
import tomllib
from pathlib import Path

import pytest

# The repo, not the config sandbox: conftest points every config path at a
# temporary directory, so the shipped tree is only reachable from here.
REPO_ROOT = Path(__file__).resolve().parents[1]

# Measured, not assumed — see the module docstring for the discovery run.
EXPECTED_ENTRY_POINTS = {
    "src/defect_risk_analyzer/api.py",
    "src/defect_risk_analyzer/ci_analyzer.py",
    "src/defect_risk_analyzer/cli.py",
    "src/defect_risk_analyzer/ui/app.py",
    "src/defect_risk_analyzer/ui/pages/analiz.py",
    "src/defect_risk_analyzer/ui/pages/ayarlar.py",
    "src/defect_risk_analyzer/ui/pages/buglar.py",
    "tests/tools/make_baseline.py",
}


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------

def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def has_main_block(path: Path) -> bool:
    """A top-level `if __name__ == "__main__":`. Top-level only: a nested one
    does not make the module runnable."""
    for node in parse(path).body:
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        test = node.test
        if (
            isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and any(
                isinstance(c, ast.Constant) and c.value == "__main__"
                for c in test.comparators
            )
        ):
            return True
    return False


def imports_config_directly(path: Path) -> bool:
    """See DIRECT IMPORT in the module docstring."""
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[-1] == "config" for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[-1] == "config":
                return True
            if any(a.name == "config" for a in node.names):
                return True
    return False


def is_streamlit_page(path: Path) -> bool:
    """Streamlit's own rule, quoted in the module docstring."""
    return not path.name.startswith(".") and path.name != "__init__.py"


def console_script_modules(root: Path) -> list[Path]:
    """`[project.scripts]` targets, resolved to files under src/."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return []
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    found = []
    for target in data.get("project", {}).get("scripts", {}).values():
        module = target.split(":", 1)[0]
        candidate = root / "src" / Path(*module.split("."))
        candidate = candidate.with_suffix(".py")
        if candidate.is_file():
            found.append(candidate)
    return found


def discover_entry_points(root: Path) -> list[Path]:
    """The four patterns, applied to `root`. Parameterised by root on purpose:
    that is what lets the fixture tests below drive it over a synthetic tree."""
    found: list[Path] = []

    src = root / "src"
    if src.is_dir():
        found += [p for p in sorted(src.rglob("*.py")) if has_main_block(p)]

    found += console_script_modules(root)

    app = root / "src" / "defect_risk_analyzer" / "ui" / "app.py"
    if app.is_file():
        found.append(app)
    pages = root / "src" / "defect_risk_analyzer" / "ui" / "pages"
    if pages.is_dir():
        found += [p for p in sorted(pages.glob("*.py")) if is_streamlit_page(p)]

    tools = root / "tests" / "tools"
    if tools.is_dir():
        found += [
            p
            for p in sorted(tools.rglob("*.py"))
            if has_main_block(p) and imports_config_directly(p)
        ]

    return sorted(set(found))


def calls_config_init(node: ast.AST) -> bool:
    """A `config.init(...)` call anywhere inside `node`. Matched on the call
    node's attribute, never on a source substring."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "init"
            and isinstance(func.value, ast.Name)
            and func.value.id == "config"
        ):
            return True
    return False


def called_bare_names(tree: ast.Module) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def import_origin(tree: ast.Module, name: str, root: Path) -> Path | None:
    """Where `name` was imported from, as a file under src/.

    Resolved from the module's own imports rather than from a list of blessed
    helper names: if `bootstrap` is renamed or moved, this follows it, and a
    hard-coded list would not.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if any((alias.asname or alias.name) == name for alias in node.names):
            candidate = (root / "src" / Path(*node.module.split("."))).with_suffix(".py")
            if candidate.is_file():
                return candidate
    return None


def reaches_init(path: Path, root: Path) -> bool:
    """True if this entry point reaches `config.init()`, directly or one hop.

    ONE hop, and the hop is verified rather than trusted: the helper's own
    definition is parsed and must itself call `config.init()`. `bootstrap()` is
    the only such helper today, and if it ever stops calling `init()` this
    guard goes red instead of quietly approving every page script.
    """
    tree = parse(path)
    if calls_config_init(tree):
        return True

    for name in called_bare_names(tree):
        origin = import_origin(tree, name, root)
        if origin is None:
            continue
        for node in ast.walk(parse(origin)):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                if calls_config_init(node):
                    return True
    return False


def flagged_entry_points(root: Path) -> list[str]:
    return [
        p.relative_to(root).as_posix()
        for p in discover_entry_points(root)
        if not reaches_init(p, root)
    ]


# ---------------------------------------------------------------------------
# T16 — the guard works in both directions, on a synthetic tree
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_repo(tmp_path):
    """A miniature tree with one entry point of each kind."""
    pkg = tmp_path / "src" / "toy"
    pkg.mkdir(parents=True)

    (pkg / "no_init.py").write_text(
        "from toy import config\n\n\ndef main():\n    return 1\n\n\n"
        'if __name__ == "__main__":\n    main()\n',
        encoding="utf-8",
    )
    (pkg / "with_init.py").write_text(
        "from toy import config\n\n\ndef main():\n    config.init()\n    return 1\n\n\n"
        'if __name__ == "__main__":\n    main()\n',
        encoding="utf-8",
    )
    (pkg / "frame.py").write_text(
        "from toy import config\n\n\ndef boot():\n    config.init()\n",
        encoding="utf-8",
    )
    (pkg / "via_helper.py").write_text(
        "from toy.frame import boot\n\n\ndef main():\n    boot()\n\n\n"
        'if __name__ == "__main__":\n    main()\n',
        encoding="utf-8",
    )
    return tmp_path


def test_t16_the_guard_flags_a_module_that_skips_init(synthetic_repo):
    """T16 — both directions in one run.

    A guard that never flags anything is the failure mode this test exists for:
    it would sit green forever while the rule it names goes unenforced.
    """
    discovered = {
        p.relative_to(synthetic_repo).as_posix() for p in discover_entry_points(synthetic_repo)
    }
    assert discovered == {
        "src/toy/no_init.py",
        "src/toy/with_init.py",
        "src/toy/via_helper.py",
    }, "frame.py has no __main__ block and must not count as an entry point"

    assert flagged_entry_points(synthetic_repo) == ["src/toy/no_init.py"]


def test_t16b_adding_init_clears_the_flag(synthetic_repo):
    """The other direction, measured rather than assumed."""
    offender = synthetic_repo / "src" / "toy" / "no_init.py"
    assert flagged_entry_points(synthetic_repo) == ["src/toy/no_init.py"]

    offender.write_text(
        "from toy import config\n\n\ndef main():\n    config.init()\n    return 1\n\n\n"
        'if __name__ == "__main__":\n    main()\n',
        encoding="utf-8",
    )

    assert flagged_entry_points(synthetic_repo) == []


def test_t16c_the_single_hop_helper_must_itself_call_init(synthetic_repo):
    """The hop is verified, not trusted.

    `via_helper.py` only calls `boot()`. If `boot` stops calling `config.init()`,
    every module that relies on it has to go red — otherwise renaming or
    gutting the shared frame would silently disarm the guard for all of them.
    """
    assert flagged_entry_points(synthetic_repo) == ["src/toy/no_init.py"]

    (synthetic_repo / "src" / "toy" / "frame.py").write_text(
        "from toy import config\n\n\ndef boot():\n    return None\n",
        encoding="utf-8",
    )

    assert sorted(flagged_entry_points(synthetic_repo)) == [
        "src/toy/no_init.py",
        "src/toy/via_helper.py",
    ]


# ---------------------------------------------------------------------------
# T17 — the real tree
# ---------------------------------------------------------------------------

def test_t17_every_entry_point_in_this_repo_reaches_init():
    """T17 — EXPECTED GREEN, and it asserts the set, not just the absence.

    Asserting only "nothing was flagged" would pass on an empty discovery: a
    wrong scan root or a broken glob would produce a permanently green test
    that inspects zero files. So the eight measured entry points are named, and
    the guard must have looked at all of them.
    """
    discovered = {p.relative_to(REPO_ROOT).as_posix() for p in discover_entry_points(REPO_ROOT)}

    assert discovered == EXPECTED_ENTRY_POINTS
    assert flagged_entry_points(REPO_ROOT) == []


def test_t18_pattern_four_ignores_tools_that_do_not_import_config():
    """T18 — the narrowing itself, pinned.

    Pattern 4 covers `tests/tools/` scripts that import config directly. The
    three that do not are not inspected at all — they are neither green nor
    red here, and the module docstring records that as a declared blind spot.
    """
    discovered = {p.relative_to(REPO_ROOT).as_posix() for p in discover_entry_points(REPO_ROOT)}
    tools = {name for name in discovered if name.startswith("tests/tools/")}

    assert tools == {"tests/tools/make_baseline.py"}


def test_t19_pattern_three_follows_streamlits_own_page_rule():
    """T19 — `pages/__init__.py` is excluded by the framework's rule.

    Not by a name this file keeps: `is_streamlit_page` mirrors streamlit's
    `source_util.py`. The four real page scripts must all be present, so the
    filter cannot quietly swallow more than it should.
    """
    discovered = {p.relative_to(REPO_ROOT).as_posix() for p in discover_entry_points(REPO_ROOT)}
    pages = {name for name in discovered if "/ui/pages/" in name}

    assert pages == {
        "src/defect_risk_analyzer/ui/pages/analiz.py",
        "src/defect_risk_analyzer/ui/pages/ayarlar.py",
        "src/defect_risk_analyzer/ui/pages/buglar.py",
    }
    assert "src/defect_risk_analyzer/ui/pages/__init__.py" not in discovered
