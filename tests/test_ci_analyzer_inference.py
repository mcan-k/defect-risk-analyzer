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
    extract_changed_files,
    infer_modules_from_files,
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
    "path",
    [
        "docs/probe/auth-probe.md",   # excluded directory AND extension
        "docs/architecture.md",
        "README.md",                  # extension alone, at the repo root
        ".github/workflows/tests.yml",
        "pyproject.toml",
        "setup.cfg",
        "LICENSE",
        "assets/auth-icon.png",       # an asset named after a module
    ],
)
def test_excluded_scope_is_not_analyzed(path: str):
    """Layer 1. Documentation, configuration and assets carry no behaviour.

    A denylist rather than an allowlist: an extension we failed to enumerate is
    likelier to be source we did not think of than documentation, and a missed
    module produces an honest "no mapping" report rather than a fabricated risk
    score. The asymmetry is the design — a false negative is cheap here, a
    false positive is what shipped to PR #3.
    """
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
