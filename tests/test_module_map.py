"""
Loading module-map.json — reading and validating, not matching.

The matching rule lives in tests/test_ci_analyzer_inference.py; this file is
only about turning a file on disk into a ModuleMap, and about what happens when
that file cannot be turned into one.

Every failure here has to be *loud*. Bölüm A's whole result was replacing a
report that quietly invented a module with one that says what it does and does
not know; a loader that swallows a typo and returns an empty map would put the
silence straight back, one layer lower. So there is no "best effort" path: the
map either loads or raises, and the caller prints the reason.

Three states are distinguished on purpose, because they need three different
responses from the reader:

    no file          -> a setup step was never done. Create it.
    unreadable file  -> the file is there and wrong. Fix this line.
    no patterns      -> the file is there, valid, and does nothing. Fill it in.

Fixtures write to tmp_path, never to the DRA_BASE_DIR sandbox: the sandbox is
session-scoped and shared, so a file left in it leaks between tests.
"""

import json
from pathlib import Path

import pytest

from defect_risk_analyzer import config
from defect_risk_analyzer.ci_analyzer import (
    ModuleMapInvalid,
    ModuleMapMissing,
    load_module_map,
)

VALID = {
    "_comment": "not part of the schema",
    "modules": {"src/auth/**": "Authentication"},
    "exclude": ["docs/**"],
}


def write_map(tmp_path: Path, payload, *, name: str = "module-map.json") -> Path:
    """Write `payload` as the map file and return its path.

    A str payload is written verbatim so a test can produce malformed JSON;
    anything else is serialized.
    """
    path = tmp_path / name
    text = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_text(text, encoding="utf-8")

    return path


# ===========================================================================
# The happy path
# ===========================================================================

def test_a_valid_map_loads(tmp_path: Path):
    module_map = load_module_map(write_map(tmp_path, VALID))

    assert module_map.modules == {"src/auth/**": "Authentication"}
    assert module_map.exclude == ("docs/**",)


def test_comment_and_unknown_keys_are_ignored(tmp_path: Path):
    """"_comment" is documentation, not schema, and must not leak into modules.

    Unknown top-level keys are accepted rather than rejected: a map written for
    a later version of the tool should still work with this one, and the cost
    of being wrong about that is nil — an ignored key changes no behaviour.
    """
    payload = dict(VALID, some_future_key={"anything": 1})
    module_map = load_module_map(write_map(tmp_path, payload))

    assert "_comment" not in module_map.modules
    assert module_map.modules == {"src/auth/**": "Authentication"}


def test_exclude_is_optional_and_defaults_to_nothing(tmp_path: Path):
    """Omitting "exclude" excludes nothing — there is no built-in denylist.

    Falling back to a hardcoded default here would be the exact thing Bölüm B
    removes: a scope rule the user cannot see, cannot change, and does not know
    is running. Excluding nothing is a legitimate configuration, and an empty
    scope shows up honestly in the report's "N excluded" count.
    """
    module_map = load_module_map(write_map(tmp_path, {"modules": VALID["modules"]}))

    assert module_map.exclude == ()


def test_load_defaults_to_config_module_map_file(tmp_path: Path, monkeypatch):
    """No argument means config.MODULE_MAP_FILE — the repository root's copy."""
    path = write_map(tmp_path, VALID)
    monkeypatch.setattr(config, "MODULE_MAP_FILE", path)

    assert load_module_map().modules == VALID["modules"]


# ===========================================================================
# State 1 — no file
# ===========================================================================

def test_missing_file_names_the_path_and_dra_base_dir(tmp_path: Path):
    """A setup state, and the message has to be actionable in both installs.

    In a checkout, BASE_DIR is the directory holding pyproject.toml and the map
    is found. Installed with a plain `pip install .` outside a project tree,
    BASE_DIR falls back to the current working directory and the map is not
    there — see docs/KNOWN-DEBT.md. The user cannot debug that from "file not
    found"; they can from a message that names DRA_BASE_DIR.
    """
    missing = tmp_path / "module-map.json"

    with pytest.raises(ModuleMapMissing) as excinfo:
        load_module_map(missing)

    message = str(excinfo.value)
    assert str(missing) in message
    assert "DRA_BASE_DIR" in message


def test_missing_is_a_module_map_error(tmp_path: Path):
    """main() catches one type. The subclasses only select the wording."""
    from defect_risk_analyzer.ci_analyzer import ModuleMapError

    with pytest.raises(ModuleMapError):
        load_module_map(tmp_path / "module-map.json")


# ===========================================================================
# State 2 — the file is there and wrong
# ===========================================================================

def test_invalid_json_names_the_line_and_column(tmp_path: Path):
    """"is not valid JSON" alone leaves the user searching by eye.

    json already computes the position; dropping it on the floor and re-raising
    a bare message is a choice, and the wrong one.
    """
    path = write_map(tmp_path, '{\n  "modules": {\n')

    with pytest.raises(ModuleMapInvalid) as excinfo:
        load_module_map(path)

    message = str(excinfo.value)
    assert "module-map.json" in message
    assert "line" in message and "column" in message


@pytest.mark.parametrize(
    ("payload", "id_"),
    [
        pytest.param([{"modules": {}}], "list", id="list"),
        pytest.param('"a string"', "str", id="string"),
        pytest.param("42", "int", id="number"),
    ],
)
def test_top_level_must_be_an_object(tmp_path: Path, payload, id_: str):
    with pytest.raises(ModuleMapInvalid):
        load_module_map(write_map(tmp_path, payload))


def test_modules_key_is_required(tmp_path: Path):
    with pytest.raises(ModuleMapInvalid) as excinfo:
        load_module_map(write_map(tmp_path, {"exclude": ["docs/**"]}))

    assert "modules" in str(excinfo.value)


@pytest.mark.parametrize("modules", [[], "src/**", 3], ids=["list", "str", "int"])
def test_modules_must_be_an_object(tmp_path: Path, modules):
    with pytest.raises(ModuleMapInvalid) as excinfo:
        load_module_map(write_map(tmp_path, {"modules": modules}))

    assert "modules" in str(excinfo.value)


@pytest.mark.parametrize("name", [None, 12, ["Authentication"], {}])
def test_module_name_must_be_a_string(tmp_path: Path, name):
    """The value is printed in the report and compared against bug components.

    A non-string reaches the report as a repr and matches no component, so it
    fails twice over — once visibly, once as a module that can never score.
    """
    with pytest.raises(ModuleMapInvalid) as excinfo:
        load_module_map(write_map(tmp_path, {"modules": {"src/**": name}}))

    assert "src/**" in str(excinfo.value)


def test_duplicate_pattern_is_rejected(tmp_path: Path):
    """json keeps the last of two identical keys and says nothing.

    A map that lists "src/auth/**" twice with different modules is a mistake
    with a silent winner decided by file order — the same shape as the
    dictionary-ordering bug Bölüm A removed from the keyword table.
    """
    path = write_map(
        tmp_path,
        '{"modules": {"src/auth/**": "Authentication", "src/auth/**": "Payment"}}',
    )

    with pytest.raises(ModuleMapInvalid) as excinfo:
        load_module_map(path)

    assert "src/auth/**" in str(excinfo.value)


@pytest.mark.parametrize("exclude", ["docs/**", {"docs/**": 1}, [1], [None]])
def test_exclude_must_be_a_list_of_strings(tmp_path: Path, exclude):
    payload = {"modules": VALID["modules"], "exclude": exclude}

    with pytest.raises(ModuleMapInvalid) as excinfo:
        load_module_map(write_map(tmp_path, payload))

    assert "exclude" in str(excinfo.value)


# ===========================================================================
# State 2b — the pattern itself
# ===========================================================================

@pytest.mark.parametrize(
    ("pattern", "reason"),
    [
        ("src/[ab]*.py", "character class"),
        ("src/{a,b}/**", "brace expansion"),
        ("!src/**", "negation"),
    ],
)
def test_unsupported_glob_syntax_is_rejected(tmp_path: Path, pattern: str, reason: str):
    """Treating these as literal text would make them silently never match.

    A user who writes "src/[ab]*.py" and sees no modules has no way to tell an
    unsupported construct from a wrong path. Rejecting at load time turns a
    silent miss into a sentence naming the construct.
    """
    payload = {"modules": {pattern: "Authentication"}}

    with pytest.raises(ModuleMapInvalid) as excinfo:
        load_module_map(write_map(tmp_path, payload))

    assert pattern in str(excinfo.value), reason


@pytest.mark.parametrize(
    ("pattern", "reason"),
    [
        ("", "an empty pattern matches nothing and names nothing"),
        ("/src/**", "diff paths are repo-relative, so a leading / never matches"),
        ("src\\auth\\**", "git emits POSIX separators on every platform"),
    ],
)
def test_invalid_pattern_is_rejected(tmp_path: Path, pattern: str, reason: str):
    payload = {"modules": {pattern: "Authentication"}}

    with pytest.raises(ModuleMapInvalid) as excinfo:
        load_module_map(write_map(tmp_path, payload))

    assert "module-map.json" in str(excinfo.value), reason


def test_backslash_pattern_message_names_the_separator(tmp_path: Path):
    """The Windows user writing a Windows path is the likely author here."""
    payload = {"modules": {"src\\auth\\**": "Authentication"}}

    with pytest.raises(ModuleMapInvalid) as excinfo:
        load_module_map(write_map(tmp_path, payload))

    assert "/" in str(excinfo.value)


def test_exclude_patterns_are_validated_too(tmp_path: Path):
    """Both lists are patterns; only one of them being checked is an accident."""
    payload = {"modules": VALID["modules"], "exclude": ["docs/[ab]**"]}

    with pytest.raises(ModuleMapInvalid) as excinfo:
        load_module_map(write_map(tmp_path, payload))

    assert "docs/[ab]**" in str(excinfo.value)


# ===========================================================================
# State 3 — valid, and empty
# ===========================================================================

def test_empty_modules_is_rejected(tmp_path: Path):
    """A map with no patterns cannot be told apart from a mistake.

    It is also indistinguishable, in the report, from a diff that matched
    nothing — and that conflation is precisely what Bölüm A spent a commit
    separating. A user who wants inference off should delete or rename the
    file, which states the intent unambiguously; the message says so.
    """
    with pytest.raises(ModuleMapInvalid) as excinfo:
        load_module_map(write_map(tmp_path, {"modules": {}}))

    message = str(excinfo.value)
    assert "no patterns" in message
    assert "delete" in message
