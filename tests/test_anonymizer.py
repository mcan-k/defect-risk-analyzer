"""What `DataAnonymizer` masks, what it restores, and what it must not restore.

WRITTEN BEFORE THE FIX (Faz 6B, Adım 1). Several tests here are expected to be
RED on today's implementation; that is the point. The expected colour of every
test is recorded in its docstring, and a test that comes up the wrong colour is
a finding to report, not something to adjust the assertion for.

TWO ADAPTERS, AND WHY THEY EXIST. Adım 2 changes this class's API twice: the
`map_file` constructor parameter disappears with on-disk persistence, and a
`session()` scope appears. Both changes are absorbed by `anon` (the fixture) and
`scope()` (below), so that NOT ONE ASSERTION in this file changes in Adım 2.

That is not cosmetic. Written against the future API, the isolation test would
fail today with `AttributeError: session` — a red that says "the method is
missing", not "the rule is broken". Written against today's API, it would have
to be rewritten once the method lands, and the rewritten version would never
have been observed red. Both are worthless as evidence. Routed through the
adapters, the test runs to completion today and fails on its assertion, which
is the only red that carries the claim.

MEASURED, NOT ASSUMED. The phone expectations below come from running the
current regex over synthetic strings (Faz 6B keşfi, Sapma 11), not from the
handover note, which was wrong about this: version numbers, ISO timestamps and
letter-prefixed order codes are NOT masked today. The three real defect classes
are marked D8-1/2/3.

NO REAL SECRETS. Every value here is synthetic and uses the reserved
`.invalid` TLD or documentation ranges. Nothing in this file is a credential.
"""

import contextlib

import pytest

from defect_risk_analyzer.anonymizer import DataAnonymizer

# ---------------------------------------------------------------------------
# Adapters — the only two lines Adım 2 touches in this file
# ---------------------------------------------------------------------------

@pytest.fixture
def anon():
    """A fresh anonymizer.

    ADIM 2 APPLIED. Before the fix this took `map_file=tmp_path / ...`, which
    was load-bearing: `DataAnonymizer()` resolved `config.ANON_MAP_FILE`, one
    shared path for the whole session, so `_load_map()` handed each test
    whatever the previous one had persisted. Persistence is gone and that
    coupling went with it.
    """
    return DataAnonymizer()


@contextlib.contextmanager
def scope(anonymizer):
    """One analysis call's anonymisation scope.

    ADIM 2 APPLIED. Before the fix this yielded the instance unchanged, because
    there was no scope — the mapping lived on the instance and outlived every
    call. Every assertion in this file was written through this helper for that
    reason, and not one of them changed when the real scope landed.
    """
    with anonymizer.session() as scoped:
        yield scoped


# ---------------------------------------------------------------------------
# D8 — the phone pattern. Three defect classes, measured.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "Build 20241105123 failed",
        "Trace id 1234567890 in the log",
    ],
)
def test_d8_1_long_digit_runs_are_not_phone_numbers(anon, text):
    """D8-1 — EXPECTED RED.

    Seven or more unbroken digits is a build number or a trace id, not a phone
    number. Today the pattern's three mandatory groups can all be satisfied from
    one run, so the LLM receives `Build [PHONE_001] failed` and loses the
    identifier the whole report is about.
    """
    with scope(anon) as s:
        assert s._anonymize_string(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "Chunk 100 200 300 processed",
        "Memory grew 1024 2048 4096 MB across runs",
        "Invoice 2024 1155 88 not generated",
        "SKU 4512 8890 12 missing from cart",
    ],
)
def test_d8_2_number_triples_are_not_phone_numbers(anon, text):
    """D8-2 — EXPECTED RED.

    Three space-separated numbers match `(2-4)(3-4)(2-4)` whatever they mean.
    Measurements, sizes and quantities are the common case in a bug report, and
    all of them are being replaced with a PHONE token today.
    """
    with scope(anon) as s:
        assert s._anonymize_string(text) == text


def test_d8_3_a_partial_match_never_leaves_a_fragment(anon):
    """D8-3 — EXPECTED RED.

    A separate class from a plain miss. Sixteen digits in four groups match the
    first twelve and stop, so today's output is `[PHONE_001] 1111` — the mask
    reports success while four digits of the original survive next to it. A
    value is either masked or it is not; a fragment is the one outcome that must
    never happen, because it reads as masked.

    Asserted as a rule rather than against a fixed replacement: whatever the
    fixed pattern decides to do here, no digit group of the original may remain
    beside a token.
    """
    text = "Card ending 4111 1111 2222 3333 rejected"
    with scope(anon) as s:
        result = s._anonymize_string(text)

    if result == text:
        return  # not matched at all — an acceptable outcome
    assert "PHONE" in result, "unexpected category for a digit run"
    for group in ("4111", "1111", "2222", "3333"):
        assert group not in result, f"fragment {group!r} survived beside a token"


@pytest.mark.parametrize(
    "text",
    [
        "Login fails on v2.10.3 build 12345 after the 2024-11-05 release",
        "Release 2.10.3.4567 regressed",
        "Order ORD-2024-1155 stuck in queue",
        "Timestamp 2025-01-14T10:22:33Z on the request",
        "Elapsed 10:22:33 before timeout",
        "Error at line 1024, column 55, offset 7788",
    ],
)
def test_d8_these_already_pass_through_and_must_keep_doing_so(anon, text):
    """EXPECTED GREEN.

    The handover note claimed version numbers, order codes and dates were being
    masked. Measured: they are not. These are pinned so the D8 fix is not
    written to solve a problem that does not exist — and so that a fix which
    tightens the pattern too far shows up here instead of in production.
    """
    with scope(anon) as s:
        assert s._anonymize_string(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "Contact ops at +90 532 111 2233 for escalation",
        "Fallback number 555-123-4567 is unreachable",
    ],
)
def test_d8_real_phone_numbers_are_still_masked(anon, text):
    """EXPECTED GREEN.

    The other half of the D8 fix. Narrowing the pattern must not turn it off:
    a fix that simply stops matching would pass all three RED tests above and
    silently remove the only PII category this pattern exists for.
    """
    with scope(anon) as s:
        result = s._anonymize_string(text)
    assert result != text
    assert "PHONE_" in result


# ---------------------------------------------------------------------------
# Round trip — current behaviour, pinned
# ---------------------------------------------------------------------------

def test_the_round_trip_restores_what_it_masked(anon):
    """EXPECTED GREEN.

    Within one scope, a masked value comes back. This is the behaviour the
    isolation fix must not break, and it is the reason `deanonymize_text`
    exists at all.
    """
    original = "Report from alice@example.invalid about host 10.0.0.5"

    with scope(anon) as s:
        masked = s.anonymize_query(original)
        assert masked != original
        assert "alice@example.invalid" not in masked
        assert s.deanonymize_text(masked) == original


def test_one_value_gets_one_token_across_query_and_bug(anon):
    """EXPECTED GREEN.

    The same address in the query and in the bug record must become the same
    token, or the LLM sees two unrelated people. This is what makes the scope a
    scope rather than a per-string reset, and it is the property most at risk
    when the mapping's lifetime is shortened in Adım 2.
    """
    with scope(anon) as s:
        masked_query = s.anonymize_query("who owns alice@example.invalid")
        masked_bugs = s.anonymize_bugs([{"summary": "ping alice@example.invalid"}])

    token = masked_query.split()[-1]
    assert token.startswith("[EMAIL_")
    assert token in masked_bugs[0]["summary"]


def test_an_unmapped_token_is_left_alone(anon):
    """EXPECTED GREEN.

    The LLM can emit a token-shaped string this scope never issued. It must pass
    through untouched rather than raising or being blanked — the reasoning text
    is shown to the user, and corrupting it is worse than an unresolved token.
    """
    with scope(anon) as s:
        s.anonymize_query("mail alice@example.invalid")
        text = "Compare with [EMAIL_999] from the linked ticket."
        assert s.deanonymize_text(text) == text


# ---------------------------------------------------------------------------
# 7.6 Senaryo 1 — the isolation rule
# ---------------------------------------------------------------------------

def test_a_scope_does_not_restore_another_scopes_value(anon):
    """EXPECTED RED — and the red must come from the ASSERTION, not an
    AttributeError. See the module docstring on the two adapters.

    The measured leak: `deanonymize_text` replaces every token it has ever
    issued, without asking whether that token appeared in this call's prompt. A
    second analysis whose own text contains no PII at all can therefore have a
    first analysis's address written into its reasoning — and under
    `@st.cache_resource` the dashboard shares one instance across every browser
    session, so the two analyses can belong to two different people.
    """
    with scope(anon) as first:
        first.anonymize_query("escalate to alice@example.invalid")

    with scope(anon) as second:
        second.anonymize_query("the login button is broken")
        restored = second.deanonymize_text(
            "Root cause unclear. See prior note [EMAIL_001] for context."
        )

    assert "alice@example.invalid" not in restored


# ---------------------------------------------------------------------------
# session() — the contract, added in Adım 3
# ---------------------------------------------------------------------------

def test_a_scope_is_dropped_even_when_the_block_raises(anon):
    """EXPECTED GREEN.

    `_call_llm` raises LLMError and RateLimitError, both from inside the scope.
    If a failed analysis left its mapping behind, the next analysis would
    inherit it — the same leak as
    `test_a_scope_does_not_restore_another_scopes_value`, reached by the error
    path instead of the success path, which is the path least likely to be
    exercised by hand.

    Asserted through a LATER scope rather than by reading the mapping after the
    block. There is no mapping to read: the scope is a local, so the guarantee
    is that nothing survives to reach the next call, and that is what this
    measures. Reading a drained attribute would instead measure a cleanup step
    this design does not have.
    """
    with pytest.raises(RuntimeError):
        with anon.session() as failing:
            failing.anonymize_query("page alice@example.invalid")
            raise RuntimeError("LLM call failed")

    with anon.session() as later:
        restored = later.deanonymize_text("retry the page to [EMAIL_001]")

    assert "alice@example.invalid" not in restored


def test_a_scope_cannot_open_another_scope(anon):
    """EXPECTED GREEN.

    Nesting is prevented rather than defined. `session()` is public, so leaving
    nested use undefined would be a shape someone eventually relies on; but
    defining it means choosing whether the inner scope inherits the outer
    mapping, and no caller asks — the analysis path opens exactly one scope,
    under `_llm_lock`. So the scope simply does not carry the method, and a
    nested attempt fails at the point of misuse instead of quietly doing
    whichever thing was chosen.
    """
    with anon.session() as scoped:
        assert not hasattr(scoped, "session")
        with pytest.raises(AttributeError):
            scoped.session()


def test_the_anonymizer_itself_holds_no_mapping(anon):
    """EXPECTED GREEN.

    The structural half of the isolation rule. The dashboard shares one
    anonymizer across every browser session via `@st.cache_resource`; that is
    safe only because there is nothing on it to share. Pinned as an absence, so
    that moving any of these three back onto the instance — the obvious
    refactor for someone who wants stable token numbering — fails here.
    """
    with anon.session() as scoped:
        scoped.anonymize_query("mail alice@example.invalid")
        assert scoped._forward, "the scope should hold the mapping"

    for attribute in ("_forward", "_reverse", "_counters"):
        assert not hasattr(anon, attribute), f"{attribute} leaked onto the anonymizer"


# ---------------------------------------------------------------------------
# PERSON — the dead counter, recorded rather than fixed
# ---------------------------------------------------------------------------

def test_person_names_are_not_masked(anon):
    """EXPECTED GREEN.

    `_counters` carries a PERSON category with no pattern behind it. This test
    does not ask for one — name recognition is out of Faz 6B's scope. It records
    the behaviour so that README's claim to the contrary is provably wrong, and
    so that anyone who later adds a pattern has to come here and change a test
    that says what today actually does.
    """
    text = "Ahmet Yilmaz reported the crash and Mehmet Demir confirmed it"
    with scope(anon) as s:
        assert s._anonymize_string(text) == text


def test_the_person_counter_exists_but_never_moves(anon):
    """EXPECTED GREEN. The dead counter itself, pinned.

    Read through the scope, not off the instance: `_counters` is scope-owned
    state, and Adım 2 shortens its lifetime to one call. Reading `anon._counters`
    after the block would have measured the lifetime instead of the rule, and
    would have had to be rewritten in Adım 2.
    """
    with scope(anon) as s:
        s.anonymize_query("Ahmet Yilmaz saw it at alice@example.invalid")

        assert "PERSON" in s._counters
        assert s._counters["PERSON"] == 0
        assert s._counters["EMAIL"] == 1
