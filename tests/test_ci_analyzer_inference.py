"""
Module inference in ci_analyzer — pinned against a bug measured in production.

PR #3 produced the original defect: two documentation files with identical
one-line content produced different verdicts.

    docs/probe/auth-probe.md -> Affected Modules: Authentication, 79/100, HIGH RISK
    docs/probe/notes.md      -> Affected Modules: General, one "No Data" row, LOW RISK

Neither file contains code, and neither module was touched. The 79 is not
noise — it is exactly the Authentication score in
tests/data/scores-aff55c6-now2026-08-11.json. The scoring was correct; it was
being handed a module the diff never touched.

Bölüm A fixed that with a scope filter plus token-boundary matching, and killed
the documentation class of false positive. Bölüm B removes what was left, which
was not a bug in the token rule but the token rule itself. Measured on this
repository, of 34 tracked .py files 8 produced a module and 1 of those was
right:

    api.py             -> API            correct
    api_auth.py        -> Authentication 79/100 HIGH RISK, from one line changed
    api_models.py      -> Database
    component_classifier.py -> Frontend
    prompt_templates.py     -> Frontend
    dashboard.py            -> Reporting
    tests/test_ci_analyzer_report.py -> Reporting
    tests/test_dashboard_pages.py    -> Reporting

api_auth.py is the expensive one: it validates the tool's own X-API-Key header
and has nothing to do with the product's Authentication module. No setting of
the token rule can separate it from api.py, because the difference is not in
the filename — it is in what the file does. Going from a filename to a Jira
component is a guess, and it was right 1 time in 8.

So the guess is gone. Patterns now come from module-map.json, which the user
writes, and both layers read from it:

  1. `exclude` — paths that never reach inference at all.
  2. `modules` — path pattern to module name, matched against what survives.

Most tests below build a ModuleMap in memory rather than on disk: the rule is
what is under test, not the file that happens to be committed. The three
tests that DO read the shipped file say so in their names.
"""

import subprocess
from pathlib import Path

import pytest

from defect_risk_analyzer.ci_analyzer import (
    ModuleMap,
    _matches,
    extract_changed_files,
    infer_module_provenance,
    load_module_map,
    select_analyzable_files,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ===========================================================================
# The fixture map
# ===========================================================================
# Deliberately broader than the map this repository ships. The old scope tests
# earned their keep by choosing paths that WOULD have produced a module if the
# filter had not stopped them (65fe72c); keeping that property means the map
# under test has to be able to claim a path under docs/ or tests/ in the first
# place. The shipped map cannot — every one of its patterns lives under
# src/defect_risk_analyzer/ — so the rule is exercised here and the shipped
# file's contents are checked separately.

FIXTURE_MAP = ModuleMap(
    modules={
        "**/*auth*": "Authentication",
        "**/*payment*": "Payment",
        "**/*dashboard*": "Reporting",
        "**/*_view.py": "Frontend",
        "src/auth/**": "Authentication",
    },
    exclude=(
        "docs/**",
        "tests/**",
        ".github/**",
        "**/*.md",
        "**/*.png",
        "**/*.txt",
    ),
)


def modules_for(path: str, module_map: ModuleMap = FIXTURE_MAP) -> list[str]:
    """Both layers, the way main() runs them."""
    return sorted(infer_module_provenance([path], module_map))


def modules_ignoring_scope(path: str, module_map: ModuleMap = FIXTURE_MAP) -> list[str]:
    """Layer 2 alone — what the path would map to if `exclude` did not exist.

    The private matcher is imported on purpose. Reimplementing the rule here
    would let the two drift apart, and this function exists precisely to prove
    that a scope-filter test case is load-bearing: if it maps to nothing even
    without the filter, the case proves nothing about the filter.
    """
    return sorted(
        {
            module
            for pattern, module in module_map.modules.items()
            if _matches(pattern, path)
        }
    )


# ===========================================================================
# The two probes — the observed bug, verbatim
# ===========================================================================

PROBE_KEYWORD_NAME = "docs/probe/auth-probe.md"
PROBE_NEUTRAL_NAME = "docs/probe/notes.md"


def test_two_probes_agree_and_map_to_nothing():
    """The measured defect, stated as an invariant.

    The two probe files differ only in filename. A documentation note cannot
    change which product module a PR touches, so both must infer nothing — and,
    more importantly, must infer the *same* nothing. Asserting the equality as
    well as the value is deliberate: it is the difference between the two
    reports that made the bug visible in CI.

    The fixture map contains "**/*auth*", so this is not passing by accident:
    layer 2 really would claim auth-probe.md, and only `exclude` stops it. A
    user can write exactly that pattern.
    """
    assert modules_ignoring_scope(PROBE_KEYWORD_NAME) == ["Authentication"]

    keyword_named = modules_for(PROBE_KEYWORD_NAME)
    neutral_named = modules_for(PROBE_NEUTRAL_NAME)

    assert keyword_named == []
    assert neutral_named == []
    assert keyword_named == neutral_named


# ===========================================================================
# Layer 1 — paths that never reach inference
# ===========================================================================

@pytest.mark.parametrize(
    ("rule", "path", "would_match"),
    [
        ("docs/**", "docs/examples/payment_api.py", ["Payment"]),
        ("tests/**", "tests/test_dashboard_pages.py", ["Reporting"]),
        (".github/**", ".github/workflows/auth-deploy.yml", ["Authentication"]),
        ("**/*.md", "notes/payment-flow.md", ["Payment"]),
        ("**/*.png", "assets/auth-icon.png", ["Authentication"]),
        ("**/*.txt", "requirements-auth.txt", ["Authentication"]),
        ("docs/** and **/*.md", PROBE_KEYWORD_NAME, ["Authentication"]),
    ],
)
def test_excluded_scope_is_not_analyzed(rule: str, path: str, would_match: list[str]):
    """`exclude` runs first and its result is final.

    Every case carries its own weight. The first assertion is not decoration:
    an earlier version of this test listed paths like "README.md" and
    "pyproject.toml", which mapped to nothing under the matching rule anyway.
    Deleting ".md" from the scope left the whole suite green — the cases were
    passing for a reason that had nothing to do with the rule they named.

    Note the "tests/**" case. It is the one Bölüm B decided to exclude by
    default, and it is exactly the shape of the false positive Bölüm A could
    only report rather than prevent: a test filename naming a product module.
    """
    assert modules_ignoring_scope(path) == would_match, (
        f"{path} maps to nothing even with `exclude` disabled, so it cannot "
        f"demonstrate anything about the {rule} rule. Pick a path that a "
        "module pattern actually claims."
    )

    assert modules_for(path) == []
    assert select_analyzable_files([path], FIXTURE_MAP) == []


# ===========================================================================
# Guard against over-tightening — real code paths must still map
# ===========================================================================

@pytest.mark.parametrize(
    ("path", "expected", "derivation"),
    [
        (
            "src/auth/login.py",
            ["Authentication"],
            'the directory pattern "src/auth/**" claims everything below it; '
            '"**/*auth*" does not, because the final segment is "login.py"',
        ),
        (
            "src/auth/oauth/tokens/refresh.py",
            ["Authentication"],
            '"src/auth/**" spans any depth, so a nested rewrite of the same '
            "module keeps mapping",
        ),
        (
            "web/components/cart_view.py",
            ["Frontend"],
            '"**/*_view.py" matches at any depth with a partial final segment',
        ),
        (
            "src/services/payment_gateway.py",
            ["Payment"],
            '"**/*payment*" matches inside the final segment — the substring '
            "rule is legitimate here because the user asked for it by writing "
            "the star, rather than the tool inferring it from a word list",
        ),
    ],
)
def test_real_code_paths_still_map(path: str, expected: list[str], derivation: str):
    """Moving to patterns must not silence the tool on genuine paths.

    Depth is the trap the token rule did not have: a pattern anchored at the
    root will miss a file one directory deeper unless "**" is doing its job.
    """
    assert modules_for(path) == expected, derivation


# ===========================================================================
# One file, every module it actually names
# ===========================================================================

def test_file_matching_two_patterns_yields_every_module():
    """No `break` in the pattern loop — a path that names three modules
    affects three modules.

    Bölüm A removed the `break` because stopping at the first hit let the order
    of the keyword table silently decide the answer. The same reasoning applies
    to a user-written map, and more sharply: the order of keys in a JSON file
    is not something anyone should have to think about. A user who does not
    want one of these matches removes it, or excludes the path.
    """
    modules = modules_for("src/auth/payment_view.py")

    assert modules == ["Authentication", "Frontend", "Payment"]


# ===========================================================================
# Nothing matched
# ===========================================================================

@pytest.mark.parametrize(
    "changed_files",
    [
        pytest.param([], id="empty-diff"),
        pytest.param(["README.md", "LICENSE"], id="docs-only"),
        pytest.param(["src/unmapped/thing.py"], id="in-scope-but-unmapped"),
    ],
)
def test_no_match_returns_an_empty_provenance(changed_files: list[str]):
    """Empty means "no mapping could be made".

    It is NOT the same as "this module has no recorded defects", and it is not
    a "General" module either — calculate_module_stats has never heard of that
    name, so reporting it produced a "No Data" row and a "LOW RISK" verdict for
    a diff that had not been assessed. generate_risk_report says which of the
    two it means; this function's job is only to not invent a third.
    """
    assert infer_module_provenance(changed_files, FIXTURE_MAP) == {}


# ===========================================================================
# Provenance — which file, and which pattern, produced each module
# ===========================================================================

def test_provenance_names_the_file_and_the_pattern():
    """The evidence line quotes the pattern, not the path fragment it matched.

    This is the reversal Bölüm B makes. Under the token rule the report quoted
    text found in the path, because the rule was invisible and the path was the
    only thing the reader could check. Now the rule is a line in the reader's
    own file, so the pattern is the more useful half: it says which line to
    edit. The pattern need not appear in the path at all.
    """
    provenance = infer_module_provenance(["src/auth/login.py"], FIXTURE_MAP)

    assert provenance == {
        "Authentication": [("src/auth/login.py", "src/auth/**")],
    }


def test_provenance_reports_every_pattern_that_matched():
    """Two patterns naming the same module both appear.

    Collapsing them would hide the fact that one of the two is redundant, which
    is something the reader can only act on if they can see it.
    """
    provenance = infer_module_provenance(["src/auth/oauth_handler.py"], FIXTURE_MAP)

    assert provenance == {
        "Authentication": [
            ("src/auth/oauth_handler.py", "**/*auth*"),
            ("src/auth/oauth_handler.py", "src/auth/**"),
        ],
    }


def test_provenance_is_deterministic():
    """Pairs are sorted by (file, pattern), never by dict iteration order.

    The report prints the first pair and counts the rest, so an unstable order
    would make the same diff produce different evidence between runs.
    """
    changed = [
        "src/views/dashboard.py",
        "src/auth/login.py",
    ]

    assert infer_module_provenance(changed, FIXTURE_MAP) == {
        "Authentication": [("src/auth/login.py", "src/auth/**")],
        "Reporting": [("src/views/dashboard.py", "**/*dashboard*")],
    }


# ===========================================================================
# The shipped map — what this repository's own module-map.json says
# ===========================================================================
# Separate from everything above on purpose. The tests above pin the RULE
# against a map written for them; these pin the DATA in the committed file.
# Both are needed: a correct rule reading a mistyped map still produces a wrong
# PR comment, and the eighteen exclude patterns are now file content rather
# than a frozenset the type checker would have caught.

SHIPPED_SUFFIX_PATTERNS = [
    "**/*.md", "**/*.rst", "**/*.adoc", "**/*.txt",
    "**/*.toml", "**/*.cfg", "**/*.ini",
    "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.gif",
    "**/*.svg", "**/*.ico", "**/*.webp", "**/*.pdf",
]

SHIPPED_DIRECTORY_PATTERNS = ["docs/**", "tests/**", ".github/**"]


@pytest.fixture(scope="module")
def shipped(repo_module_map_path: Path) -> ModuleMap:
    return load_module_map(repo_module_map_path)


def test_the_two_pattern_lists_below_are_the_whole_exclude_list(shipped: ModuleMap):
    """A pattern added to the map without a case here would go untested.

    This is the enumeration guard the frozenset used to get for free.
    """
    assert set(shipped.exclude) == set(SHIPPED_SUFFIX_PATTERNS) | set(
        SHIPPED_DIRECTORY_PATTERNS
    )


@pytest.mark.parametrize("pattern", SHIPPED_SUFFIX_PATTERNS)
def test_shipped_map_excludes_every_suffix_pattern(shipped: ModuleMap, pattern: str):
    """Each suffix rule, against a path a module pattern really does claim.

    The probe lives under adapters/, which the shipped map claims with
    "src/defect_risk_analyzer/adapters/**" — a pattern ending in "**" takes any
    filename, whatever its extension. So the suffix rule is the only thing
    stopping each of these, exactly as in the pre-Bölüm-B version of this test.
    """
    suffix = pattern.removeprefix("**/*")
    probe = f"src/defect_risk_analyzer/adapters/probe{suffix}"

    assert modules_ignoring_scope(probe, shipped) == ["Adapters"], (
        f"{probe} maps to nothing even with `exclude` disabled, so it cannot "
        f"demonstrate anything about the {pattern} rule."
    )

    assert infer_module_provenance([probe], shipped) == {}


@pytest.mark.parametrize("pattern", SHIPPED_DIRECTORY_PATTERNS)
def test_shipped_map_excludes_every_directory_pattern(shipped: ModuleMap, pattern: str):
    """The directory rules, with no load-bearing guard — and that is the point.

    There is no path under docs/, tests/ or .github/ that the shipped map's
    module patterns would claim, because all thirteen of them live under
    src/defect_risk_analyzer/. So unlike the suffix cases above, these three
    cannot be shown to be stopping anything today. The assertion here is only
    that the rule is present and applies; whether it currently does any work is
    measured by the next test, which exists to keep that honest.
    """
    probe = f"{pattern.removesuffix('/**')}/probe/module.py"

    assert select_analyzable_files([probe], shipped) == []


def test_shipped_directory_excludes_are_defence_in_depth(shipped: ModuleMap):
    """Records what docs/**, tests/** and .github/** do today: nothing.

    Removing any of the three changes no result for any file this repository
    tracks, because no module pattern reaches outside src/defect_risk_analyzer/.
    They are kept for the reader who copies this file and writes something
    broad like "**/*_report*", at which point tests/ starts producing modules
    immediately.

    **If this test fails, read it before fixing it.** A failure means some
    module pattern now claims a path under one of those directories, so the
    rule has become an active filter rather than a spare one. That is a change
    in what the map does, not a regression in the code — update the assertion
    and say so in the commit.
    """
    tracked = _tracked_files()

    baseline = infer_module_provenance(tracked, shipped)

    for pattern in SHIPPED_DIRECTORY_PATTERNS:
        without = ModuleMap(
            modules=shipped.modules,
            exclude=tuple(p for p in shipped.exclude if p != pattern),
        )
        assert infer_module_provenance(tracked, without) == baseline, (
            f"Dropping {pattern} now changes the result, so it has become an "
            "active filter. See this test's docstring."
        )


def test_shipped_map_matches_this_repository(shipped: ModuleMap):
    """The false positives Bölüm A measured, and what they map to now.

    The first two are the ones Bölüm A could only report, not prevent: the
    provenance line showed a test filename crediting Reporting, and left it
    there. The third is the expensive one — api_auth.py fired Authentication
    through the token "auth" and scored 79/100 HIGH RISK off bug history for a
    module it has nothing to do with. It is the tool's own X-API-Key check.
    """
    cases = {
        "docs/probe/auth-probe.md": {},
        "tests/test_ci_analyzer_report.py": {},
        "tests/test_dashboard_pages.py": {},
        "src/defect_risk_analyzer/api_auth.py": {
            "API Server": [
                (
                    "src/defect_risk_analyzer/api_auth.py",
                    "src/defect_risk_analyzer/api*.py",
                )
            ]
        },
        "src/defect_risk_analyzer/ci_analyzer.py": {
            "CI Analyzer": [
                (
                    "src/defect_risk_analyzer/ci_analyzer.py",
                    "src/defect_risk_analyzer/ci_analyzer.py",
                )
            ]
        },
    }

    for path, expected in cases.items():
        assert infer_module_provenance([path], shipped) == expected, path


def _tracked_files() -> list[str]:
    """Every file git tracks, in the POSIX form the diff parser also sees."""
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover
        pytest.skip(f"git ls-files unavailable: {exc}")

    return out.stdout.split()


# ===========================================================================
# Diff parsing — the front of the chain
# ===========================================================================

DIFF = """\
diff --git a/src/auth/login.py b/src/auth/login.py
index 1111111..2222222 100644
--- a/src/auth/login.py
+++ b/src/auth/login.py
@@ -1 +1 @@
-old
+new
diff --git a/docs/gone.md b/docs/gone.md
deleted file mode 100644
index 3333333..0000000
--- a/docs/gone.md
+++ /dev/null
@@ -1 +0,0 @@
-bye
"""


def test_extract_changed_files_reads_both_marker_styles():
    """Documents current behaviour, which the end-to-end report tests rely on.

    Deleted files still appear: they are picked up from the `diff --git` header
    even though their `+++` line is /dev/null. Sorted, de-duplicated — the two
    markers name the same file for a normal modification.
    """
    assert extract_changed_files(DIFF) == ["docs/gone.md", "src/auth/login.py"]


def test_extract_changed_files_on_empty_input():
    assert extract_changed_files("") == []


# ===========================================================================
# Pattern semantics — the rule that replaces token matching
# ===========================================================================
# The matcher is hand-rolled on purpose; every candidate in the standard
# library is wrong for this job in a way that would be invisible until it
# produced a bad PR comment:
#
#   fnmatch          "*" crosses "/", so src/*.py would match src/a/b/c.py.
#                    It also normcases on Windows -> silently case-insensitive.
#   PurePath.match   matches from the RIGHT, unanchored, and "**" is not
#                    recursive before 3.13 (it behaves like "*").
#   PurePath.full_match / glob.translate
#                    exactly the semantics wanted, but Python 3.13+. This
#                    project is ">=3.11" and both workflows pin 3.11.
#
# So the semantics are defined here rather than inherited, and these tests are
# the definition. Paths are matched as raw strings: git emits POSIX separators
# on every platform, and routing them through Path() would reintroduce "\" and
# platform-dependent case folding into a tool whose output goes into a PR.


@pytest.mark.parametrize(
    ("pattern", "path", "expected", "rule"),
    [
        ("src/**", "src/a/b.py", True, "** spans any depth"),
        ("src/**", "src/a.py", True, "** spans one segment too"),
        ("src/**", "srcx/a.py", False, "literal segments are not prefixes"),
        ("src/*.py", "src/a.py", True, "* within a segment"),
        ("**/*.md", "docs/a/b.md", True, "leading ** plus a suffix match"),
        ("**/*.md", "docs/b.mdx", False, "the suffix is anchored at the end"),
        ("**/api*.py", "src/pkg/api_auth.py", True, "* is a partial segment"),
        ("src/**/test_*.py", "src/x/y/test_a.py", True, "** in the middle"),
    ],
)
def test_pattern_matching_table(pattern: str, path: str, expected: bool, rule: str):
    """The ordinary cases, stated once so the named tests below stay narrow."""
    assert _matches(pattern, path) is expected, rule


def test_star_does_not_cross_a_separator():
    """"*" is a segment-local wildcard, which is what makes a pattern readable.

    Under fnmatch semantics "src/*.py" also matches "src/a/b/c.py", so a user
    who writes a deliberately shallow pattern silently gets a recursive one.
    That is the same failure shape as Bölüm A's substring bug: the rule the
    user believes they wrote is narrower than the rule that runs.
    """
    assert _matches("src/*.py", "src/a.py") is True
    assert _matches("src/*.py", "src/a/b.py") is False


def test_pattern_is_anchored_at_the_repo_root():
    """Patterns match the whole path, never a suffix of it.

    This is where the matcher parts company with pathlib.PurePath.match, which
    matches from the right: there, "auth/**" would claim src/auth/login.py and
    a user could never write a pattern that means "only at the top level".
    """
    assert _matches("auth/**", "src/auth/login.py") is False
    assert _matches("src/auth/**", "src/auth/login.py") is True


def test_double_star_matches_zero_segments():
    """"**/" means "at any depth, including none".

    Without this, "**/*.md" would miss README.md at the repo root — the single
    most likely thing a user wants that pattern to catch.
    """
    assert _matches("**/*.md", "README.md") is True
    assert _matches("**/*.md", "docs/a/b.md") is True


def test_matching_is_case_sensitive_on_every_platform():
    """The verdict must not depend on which OS the runner happens to use.

    fnmatch applies os.path.normcase, so the same map would exclude different
    files on Windows and Linux. A PR comment that differs by runner is worse
    than one that is wrong consistently.
    """
    assert _matches("SRC/**", "src/a.py") is False
    assert _matches("src/**", "SRC/a.py") is False


def test_directory_pattern_does_not_match_a_file_of_the_same_name():
    """"docs/**" is about the directory, not about a file called "docs".

    Bölüm A made this distinction with `path.parts[:-1]` (ci_analyzer.py:159)
    and left it untested — the comment claimed it, nothing checked it. Here the
    rule comes from the pattern itself: "docs/**" requires the separator.
    """
    assert _matches("docs/**", "docs/probe/notes.md") is True
    assert _matches("docs/**", "docs") is False
    assert _matches("docs/**", "docsx/a.py") is False
