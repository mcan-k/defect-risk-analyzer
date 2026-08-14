"""
Module inference in ci_analyzer — pinned against a bug measured in production.

These tests are committed RED, before the fix. They exist because the bug they
pin was observed on PR #3, not reasoned about: two documentation files with
identical one-line content produced different verdicts.

    docs/probe/auth-probe.md -> Affected Modules: Authentication, 79/100, HIGH RISK
    docs/probe/notes.md      -> Affected Modules: General, one "No Data" row, LOW RISK

Neither file contains code, and neither module was touched. The 79 is not
noise — it is exactly the Authentication score in
tests/data/scores-aff55c6-now2026-08-11.json. That is the whole point: the
scoring is correct, it is being handed a module the diff never touched.

Cause, in infer_modules_from_files (ci_analyzer.py:63-118):

  * each keyword is searched as a bare substring of the whole path, so "auth"
    matches inside "auth-probe.md" and "ui" matches inside "req-ui-rements.txt";
  * the `break` at :112 credits every file to exactly one module, letting
    dictionary insertion order silently pick the winner;
  * when nothing matches at all, the "General" fallback at :114-116 invents a
    module that calculate_module_stats has never heard of.

The fix is two layers and both are load-bearing:

  1. a scope filter — docs/, .github/, *.md, *.txt, *.toml and friends never
     reach inference. This is what catches auth-probe.md, because "auth" IS a
     genuine path token there; no amount of token-boundary work removes it.
  2. token-boundary matching on whatever survives layer 1 — this is what kills
     "ui" inside "requirements".

Every test below names the layer it isolates, so a future failure says which
half regressed.
"""

import pytest

from defect_risk_analyzer.ci_analyzer import (
    MODULE_KEYWORDS,
    _matched_token,
    _matches,
    _path_tokens,
    extract_changed_files,
    infer_module_provenance,
    infer_modules_from_files,
)


def modules_ignoring_scope(path: str) -> list[str]:
    """Layer 2 alone — what the path would map to if layer 1 did not exist.

    The private helpers are imported on purpose. Reimplementing the token rule
    here would let the two drift apart, and this function exists precisely to
    prove that a scope-filter test case is load-bearing: if it maps to nothing
    even without the filter, the case proves nothing about the filter.
    """
    tokens = _path_tokens(path)

    return sorted(
        {
            module
            for keyword, module in MODULE_KEYWORDS.items()
            if _matched_token(keyword, tokens)
        }
    )

# ===========================================================================
# The two probes — the observed bug, verbatim
# ===========================================================================

PROBE_KEYWORD_NAME = "docs/probe/auth-probe.md"
PROBE_NEUTRAL_NAME = "docs/probe/notes.md"


def test_two_probes_agree_and_map_to_nothing():
    """Layer 1. The measured defect, stated as an invariant.

    The two probe files differ only in filename. A documentation note cannot
    change which product module a PR touches, so both must infer nothing — and,
    more importantly, must infer the *same* nothing. Asserting the equality as
    well as the value is deliberate: it is the difference between the two
    reports that made the bug visible in CI.

    Token-boundary matching alone does NOT make this pass. "auth" is a real
    token of "auth-probe". Only the scope filter does.
    """
    keyword_named = infer_modules_from_files([PROBE_KEYWORD_NAME])
    neutral_named = infer_modules_from_files([PROBE_NEUTRAL_NAME])

    assert keyword_named == []
    assert neutral_named == []
    assert keyword_named == neutral_named


# ===========================================================================
# Layer 2 — substring matches that were never word matches
# ===========================================================================

@pytest.mark.parametrize(
    ("path", "reason"),
    [
        (
            "requirements.txt",
            'layer 1: a dependency list is not code. Also layer 2: "ui" is '
            'buried inside "req-ui-rements", it is not a token.',
        ),
        (
            "src/requirements_loader.py",
            "layer 2 in isolation: a .py file under src/ sails through the "
            'scope filter, so only token matching can stop "ui" here.',
        ),
        (
            "src/payload.py",
            'layer 2, the other direction: "pay" is a prefix of "payload". '
            "Prefix matching would reintroduce a narrower copy of this very "
            "bug, so exact-token (plus a trailing \"s\") is the rule.",
        ),
    ],
)
def test_substring_inside_a_token_does_not_match(path: str, reason: str):
    assert infer_modules_from_files([path]) == [], reason


# ===========================================================================
# Layer 1 — paths that never reach inference
# ===========================================================================

@pytest.mark.parametrize(
    ("rule", "path", "would_match"),
    [
        # Documentation
        (".md", "notes/payment-flow.md", ["Payment"]),
        (".rst", "manual/checkout.rst", ["Payment"]),
        (".adoc", "manual/dashboard.adoc", ["Reporting"]),
        # Dependency lists and project configuration
        (".txt", "requirements-api.txt", ["API"]),
        (".cfg", "deploy/inventory.cfg", ["Inventory"]),
        (".ini", "config/login.ini", ["Authentication"]),
        (".toml", "config/report.toml", ["Reporting"]),
        # Assets
        (".png", "assets/auth-icon.png", ["Authentication"]),
        (".jpg", "assets/cart.jpg", ["Frontend"]),
        (".jpeg", "assets/invoice.jpeg", ["Payment"]),
        (".gif", "assets/notification.gif", ["Notifications"]),
        (".svg", "assets/dashboard.svg", ["Reporting"]),
        (".ico", "assets/stock.ico", ["Inventory"]),
        (".webp", "assets/template.webp", ["Frontend"]),
        (".pdf", "spec/billing.pdf", ["Payment"]),
        # Directories — a suffix that is NOT excluded, so the directory rule is
        # the only thing that can stop these.
        ("docs/", "docs/examples/payment_api.py", ["API", "Payment"]),
        ("doc/", "doc/samples/login_flow.py", ["Authentication"]),
        (".github/", ".github/workflows/auth-deploy.yml", ["Authentication"]),
        # Both rules at once — the file from PR #3.
        ("docs/ + .md", "docs/probe/auth-probe.md", ["Authentication"]),
    ],
)
def test_excluded_scope_is_not_analyzed(rule: str, path: str, would_match: list[str]):
    """Layer 1. Documentation, configuration and assets carry no behaviour.

    A denylist rather than an allowlist: an extension we failed to enumerate is
    likelier to be source we did not think of than documentation, and a missed
    module produces an honest "no mapping" report rather than a fabricated risk
    score. The asymmetry is the design — a false negative is cheap here, a
    false positive is what shipped to PR #3.

    Every case carries its own weight. The first assertion is not decoration:
    an earlier version of this test listed paths like "README.md" and
    "pyproject.toml", which map to nothing under the token rule anyway. Deleting
    ".md" from EXCLUDED_SUFFIXES left the whole suite green — the cases were
    passing for a reason that had nothing to do with the rule they named.
    """
    assert modules_ignoring_scope(path) == would_match, (
        f"{path} maps to nothing even with layer 1 disabled, so it cannot "
        f"demonstrate anything about the {rule} rule. Pick a path that contains "
        "a module keyword."
    )

    assert infer_modules_from_files([path]) == []


# ===========================================================================
# Guard against over-tightening — real code paths must still map
# ===========================================================================

@pytest.mark.parametrize(
    ("path", "expected", "derivation"),
    [
        (
            "src/auth/login.py",
            ["Authentication"],
            'tokens {src, auth, login}; "auth" and "login" both -> Authentication',
        ),
        (
            "src/payments/checkout_service.py",
            ["Payment"],
            'tokens {src, payments, checkout, service}; "payments" matches the '
            '"payment" key via the trailing-s rule, "checkout" matches directly',
        ),
        (
            "web/ui/cart.tsx",
            ["Frontend"],
            'tokens {web, ui, cart}; "ui" -> Frontend and "cart" -> Frontend '
            "(ci_analyzer.py:81 — cart is a Frontend key, not a Payment one)",
        ),
        (
            "db/migrations/001_add_users.sql",
            ["Database"],
            'tokens {db, migrations, 001, add, users}; "migrations" matches the '
            '"migration" key via the trailing-s rule',
        ),
    ],
)
def test_real_code_paths_still_map(path: str, expected: list[str], derivation: str):
    """Tightening the match must not silence the tool on genuine paths.

    Plurals are the trap: exact-token equality alone would drop "payments" and
    "migrations", which are the ordinary way those directories are named.
    """
    assert infer_modules_from_files([path]) == expected, derivation


# ===========================================================================
# The `break` — one file, every module it actually names
# ===========================================================================

def test_file_matching_two_keywords_yields_every_module():
    """The `break` at :112 stops after the first hit, so today this returns
    ["Authentication"] alone — chosen not because it is the best answer but
    because "auth" happens to be the first key in the dict literal.

    Reordering the keyword table would silently change the report. That is not
    a defensible behaviour, so all three modules are reported: the path really
    does name all three.
    """
    modules = infer_modules_from_files(["src/auth/payment_view.py"])

    assert modules == ["Authentication", "Frontend", "Payment"]


# ===========================================================================
# The "General" fallback
# ===========================================================================

@pytest.mark.parametrize(
    "changed_files",
    [
        pytest.param([], id="empty-diff"),
        pytest.param(["README.md", "LICENSE"], id="docs-only"),
    ],
)
def test_no_match_returns_an_empty_list(changed_files: list[str]):
    """"General" is not a module — calculate_module_stats has never heard of it.

    Returning it makes the report print a "No Data" row and then conclude
    "LOW RISK — No significant defect patterns detected", which reads as a
    verdict when it is really an admission that nothing was assessed. An empty
    list lets the report say which of the two it means.
    """
    assert infer_modules_from_files(changed_files) == []


# ===========================================================================
# Provenance — which file, and which token, produced each module
# ===========================================================================

def test_provenance_names_the_file_and_the_token():
    """The evidence line for a match that does not survive inspection.

    This test file is itself the example: "report" is a genuine token of
    "test_ci_analyzer_report", so the tool credits Reporting — a module with
    real bug history, which therefore gets a real score. The scope filter does
    not catch it and the "no historical data" branch does not catch it either.
    What the report can do is show the reason, so a reader sees the match is
    about a test filename rather than the Reporting module.

    Narrowing the directory scope is Bölüm B's call. Making the reason visible
    is this commit's.
    """
    provenance = infer_module_provenance(["tests/test_ci_analyzer_report.py"])

    assert provenance == {
        "Reporting": [("tests/test_ci_analyzer_report.py", "report")],
    }


def test_provenance_reports_the_token_present_in_the_path():
    """"payments" is quoted, not the "payment" key that matched it.

    An evidence line naming a token the reader cannot find in the path is worse
    than no evidence line: it looks like a typo in the tool.
    """
    provenance = infer_module_provenance(["src/payments/checkout_service.py"])

    assert provenance == {
        "Payment": [
            ("src/payments/checkout_service.py", "checkout"),
            ("src/payments/checkout_service.py", "payments"),
        ],
    }


def test_provenance_is_deterministic():
    """Pairs are sorted by (file, token), never by dict iteration order.

    The report prints the first pair and counts the rest, so an unstable order
    would make the same diff produce different evidence between runs.
    """
    changed = [
        "src/views/dashboard.py",
        "src/auth/login.py",
    ]

    assert infer_module_provenance(changed) == {
        "Authentication": [
            ("src/auth/login.py", "auth"),
            ("src/auth/login.py", "login"),
        ],
        "Frontend": [("src/views/dashboard.py", "views")],
        "Reporting": [("src/views/dashboard.py", "dashboard")],
    }


@pytest.mark.parametrize(
    "changed_files",
    [
        pytest.param([], id="empty"),
        pytest.param(["README.md"], id="filtered-out"),
        pytest.param(["src/auth/payment_view.py"], id="three-modules"),
        pytest.param(["src/payments/checkout_service.py"], id="two-tokens-one-module"),
    ],
)
def test_modules_are_exactly_the_provenance_keys(changed_files: list[str]):
    """The two entry points cannot drift apart — one is defined by the other."""
    assert infer_modules_from_files(changed_files) == sorted(
        infer_module_provenance(changed_files)
    )


# ===========================================================================
# Diff parsing — the front of the chain, untested until now
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
# Bölüm B replaces MODULE_KEYWORDS with path globs the user writes in
# module-map.json. The matcher is hand-rolled on purpose; every candidate in
# the standard library is wrong for this job in a way that would be invisible
# until it produced a bad PR comment:
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
