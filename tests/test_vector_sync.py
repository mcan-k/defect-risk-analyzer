"""
The sync plan: what a load changes in the collection, decided without ChromaDB.

`VectorStore.upsert_bugs()` used to call `reset()` first (vector_store.py:137,
before this phase), deleting and recreating the collection on every load. That
made three things true at once, and all three were bugs:

  * an empty bug list wiped the index, because the reset ran before the
    empty-list check — a misconfigured Jira turned `POST /refresh` into a delete;
  * mock and live data could only be kept apart by destroying everything each
    time, which is what `bd67c76` actually bought;
  * every bug was re-embedded on every load, including the ones that had not
    changed.

Diff-sync replaces it. The decision — which ids to delete, which to upsert,
which to leave alone — is `plan_sync()`, a pure function over plain dicts, so it
is tested here with no stub, no client and no ChromaDB: the module imports
chromadb lazily inside `_get_client` only, so importing it costs nothing and
touches no disk. The adapter wiring is pinned separately in
test_vector_store_collections.py.

The deletion half is the load-bearing one. "In the collection, absent from the
incoming list, therefore delete" is what keeps a bug deleted in Jira from living
forever in the index — the failure `bd67c76` was really fixing. If that step is
ever dropped or half-done, that bug comes straight back, so it is pinned from
both directions here (S6) and by the structural invariants below.
"""

from typing import Any

import pytest

from defect_risk_analyzer.adapters.vector_store import (
    SyncPlan,
    build_document,
    build_metadata,
    plan_sync,
)

# =============================================================================
# Helpers
# =============================================================================


def make_bug(key: str, **overrides: str) -> dict[str, Any]:
    """A bug with every field the document and the metadata read.

    Defaults are spelled out rather than left empty so that a test which
    overrides one field is changing exactly one thing.
    """
    bug = {
        "key": key,
        "summary": "Login fails",
        "description": "Steps to reproduce",
        "component": "Authentication",
        "priority": "High",
        "status": "Open",
        "created": "2026-01-01",
    }
    bug.update(overrides)
    return bug


def indexed(bug: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The (document, metadata) pair a previous sync would have stored for `bug`.

    Built through the same two functions the writer uses, which is the point:
    `current` is not hypothetical data, it is what this code wrote last time.
    The literal format itself is pinned independently in test_document_format
    and test_metadata_fields, so this helper cannot quietly drift.
    """
    return build_document(bug), build_metadata(bug)


def assert_plan_invariants(plan: SyncPlan, current: dict[str, Any]) -> None:
    """Structural rules every plan obeys, whatever the inputs.

    Called from every case rather than tested once on its own. The first
    assertion is the important one and it is a design assumption made load
    bearing: the adapter only ever deletes ids that the `get()` it just
    performed handed back, which is what keeps us out of an unverified ChromaDB
    contract (deleting an id that does not exist — see the contract notes in
    vector_store.py). If someone later feeds plan_sync ids from anywhere else,
    this fails.
    """
    assert set(plan.delete_ids) <= set(current), (
        f"plan wants to delete {sorted(set(plan.delete_ids) - set(current))}, which "
        "is not in the current index. Deletions must be a subset of what get() "
        "returned — deleting an unknown id is a ChromaDB contract this suite "
        "cannot verify."
    )
    assert len(set(plan.upsert_ids)) == len(plan.upsert_ids), (
        f"duplicate ids in upsert_ids: {plan.upsert_ids}. chromadb 0.5.23 raises "
        "ValueError on duplicate ids (api/types.py:505-527)."
    )
    assert not set(plan.delete_ids) & set(plan.upsert_ids), (
        "an id is both deleted and upserted in the same plan"
    )
    assert len(plan.upsert_ids) == len(plan.upsert_documents) == len(plan.upsert_metadatas), (
        "upsert lists must stay parallel; ChromaDB reads them by position"
    )
    assert plan.desired_count == len(plan.upsert_ids) + plan.unchanged, (
        "every desired bug is either upserted or counted as unchanged"
    )


# =============================================================================
# The document and metadata formats
# =============================================================================


def test_document_format():
    """Pins the literal document text, so `indexed()` cannot drift silently.

    Five fields, single-spaced, in this order. `description` is in the document
    but deliberately not in the metadata — see test_metadata_fields.
    """
    doc = build_document(make_bug("AP-1"))

    assert doc == "Login fails Steps to reproduce Authentication High Open"


def test_metadata_fields():
    """Pins the metadata keys and the defaults that differ from the document's.

    The document uses '' for a missing component/priority/status; the metadata
    uses 'Unknown'/'Medium'/'Open'. That asymmetry predates this phase and is
    preserved here rather than tidied, because changing it would re-embed every
    bug in every existing index on the first sync after deploy.
    """
    assert build_metadata(make_bug("AP-1")) == {
        "key": "AP-1",
        "summary": "Login fails",
        "priority": "High",
        "status": "Open",
        "component": "Authentication",
        "created": "2026-01-01",
    }

    # description is searchable but not stored — a consumer of query results
    # cannot read it back.
    assert "description" not in build_metadata(make_bug("AP-1"))

    defaults = build_metadata({"key": "AP-9", "summary": "x"})
    assert defaults["priority"] == "Medium"
    assert defaults["status"] == "Open"
    assert defaults["component"] == "Unknown"
    assert defaults["created"] == ""


# =============================================================================
# First sync and steady state
# =============================================================================


def test_empty_index_upserts_everything():
    """S1 — the first run has nothing to compare against."""
    bugs = [make_bug("AP-1"), make_bug("AP-2")]

    plan = plan_sync({}, bugs)

    assert_plan_invariants(plan, {})
    assert plan.upsert_ids == ["AP-1", "AP-2"]
    assert plan.delete_ids == []
    assert plan.unchanged == 0
    assert plan.desired_count == 2


def test_unchanged_bugs_are_not_upserted():
    """S2 — the whole point of the phase.

    chromadb 0.5.23 re-embeds every document handed to upsert, unconditionally
    (api/models/CollectionCommon.py:402-406). Leaving unchanged bugs out of the
    call is the entire saving; if this test goes green vacuously the feature is
    doing nothing.
    """
    bugs = [make_bug("AP-1"), make_bug("AP-2")]
    current = {b["key"]: indexed(b) for b in bugs}

    plan = plan_sync(current, bugs)

    assert_plan_invariants(plan, current)
    assert plan.upsert_ids == []
    assert plan.delete_ids == []
    assert plan.unchanged == 2


# =============================================================================
# Change detection
# =============================================================================


@pytest.mark.parametrize(
    ("field", "value"),
    [
        # Ordinary edit: the summary is in the document, so the embedding is stale.
        ("summary", "Login fails intermittently"),
        # In the document too, and the one that motivated comparing documents
        # rather than Jira's `updated` timestamp: classify_bugs() rewrites
        # `component` in place before the upsert (analysis_service.py:94), so a
        # change to COMPONENT_KEYWORDS restages the embedding while `updated`
        # stays exactly the same.
        ("component", "Payments"),
        # In the document but not the metadata.
        ("description", "New steps"),
        # In the metadata but NOT the document — caught only because the plan
        # compares both. Comparing documents alone would leave this stale.
        ("created", "2026-02-02"),
    ],
)
def test_a_changed_field_restages_the_bug(field: str, value: str):
    """S3, S4, S5 — any field either side reads must restage the bug."""
    before = make_bug("AP-1")
    after = make_bug("AP-1", **{field: value})
    current = {"AP-1": indexed(before)}

    plan = plan_sync(current, [after])

    assert_plan_invariants(plan, current)
    assert plan.upsert_ids == ["AP-1"], f"a changed {field} must restage the bug"
    assert plan.unchanged == 0
    assert plan.delete_ids == []


def test_a_field_neither_side_reads_is_ignored():
    """Guards the case above against a false pass.

    If plan_sync compared whole bug dicts instead of the document and metadata
    it builds from them, every test above would still pass while every sync
    restaged everything. `updated` is exactly such a field: Jira sends it, and
    nothing in the index stores it.
    """
    before = make_bug("AP-1")
    after = make_bug("AP-1")
    after["updated"] = "2026-08-15T10:00:00"
    current = {"AP-1": indexed(before)}

    plan = plan_sync(current, [after])

    assert_plan_invariants(plan, current)
    assert plan.upsert_ids == []
    assert plan.unchanged == 1


# =============================================================================
# Deletion — the bd67c76 regression
# =============================================================================


def test_a_bug_absent_from_the_incoming_list_is_deleted():
    """S6 — a bug deleted in Jira must leave the collection.

    Before diff-sync this happened as a side effect of wiping everything. It is
    now an explicit step, and it is the step whose absence would silently
    reintroduce the failure `bd67c76` was fixing: the index would only ever
    grow, and searches would keep returning bugs that no longer exist.
    """
    kept = make_bug("AP-1")
    gone = make_bug("AP-2")
    current = {"AP-1": indexed(kept), "AP-2": indexed(gone)}

    plan = plan_sync(current, [kept])

    assert_plan_invariants(plan, current)
    assert plan.delete_ids == ["AP-2"]
    assert plan.upsert_ids == []
    assert plan.unchanged == 1


def test_deletions_are_ordered():
    """Deterministic output, same reason the report has an injectable clock.

    Set iteration order is not stable across runs, and an unordered delete list
    makes a failing assertion read like a flaky test.
    """
    current = {k: indexed(make_bug(k)) for k in ("AP-3", "AP-1", "AP-2")}

    plan = plan_sync(current, [])

    # Empty incoming list: nothing is desired, so everything currently indexed
    # is a deletion candidate. The adapter refuses to act on this plan — see
    # test_vector_store_collections.py — but the plan itself is still well formed.
    assert plan.delete_ids == ["AP-1", "AP-2", "AP-3"]


# =============================================================================
# Unusable input
# =============================================================================


def test_a_bug_without_a_key_is_skipped_without_causing_a_deletion():
    """S7 — an unusable bug is dropped from the plan, not treated as removal.

    The distinction matters: a keyless bug means "this record cannot be
    indexed", not "delete whatever was there".
    """
    current = {"AP-1": indexed(make_bug("AP-1"))}

    plan = plan_sync(current, [make_bug("AP-1"), {"summary": "no key at all"}])

    assert_plan_invariants(plan, current)
    assert plan.upsert_ids == []
    assert plan.delete_ids == []
    assert plan.desired_count == 1


def test_a_bug_with_no_text_at_all_is_skipped():
    """A bug whose five document fields are all empty has nothing to embed."""
    plan = plan_sync({}, [{"key": "AP-1"}])

    assert_plan_invariants(plan, {})
    assert plan.upsert_ids == []
    assert plan.desired_count == 0


@pytest.mark.parametrize(
    "bugs",
    [
        pytest.param([], id="empty-list"),
        pytest.param([{"summary": "no key"}], id="all-keyless"),
        pytest.param([{"key": "AP-1"}], id="all-textless"),
    ],
)
def test_nothing_usable_gives_a_desired_count_of_zero(bugs: list[dict[str, Any]]):
    """S10 — the signal the adapter's empty-list guard reads.

    Both spellings of "no data" have to produce it. An empty list is the obvious
    one; a non-empty list of unusable records reaches the same state further
    down and would otherwise slip past a guard that only checked the input.
    """
    plan = plan_sync({"AP-1": indexed(make_bug("AP-1"))}, bugs)

    assert plan.desired_count == 0


def test_duplicate_keys_are_deduplicated_last_one_winning():
    """S8 — removes a latent crash, not just untidiness.

    The pre-phase code appended every key without checking, and chromadb 0.5.23
    raises ValueError on duplicate ids inside one upsert call
    (api/types.py:505-527) — so two bugs sharing a key crashed the load rather
    than merging, which is the opposite of what the old comment assumed.
    """
    first = make_bug("AP-1", summary="First")
    second = make_bug("AP-1", summary="Second")

    plan = plan_sync({}, [first, second])

    assert_plan_invariants(plan, {})
    assert plan.upsert_ids == ["AP-1"]
    assert plan.upsert_documents[0].startswith("Second"), "the later bug wins"
    assert plan.desired_count == 1


# =============================================================================
# Metadata round-trip
# =============================================================================


def faithful(metadata: dict[str, Any]) -> dict[str, Any]:
    """What a store that returns exactly what it was given hands back."""
    return dict(metadata)


def lossy(metadata: dict[str, Any]) -> dict[str, Any]:
    """What a store that drops empty values hands back."""
    return {k: v for k, v in metadata.items() if v != ""}


def test_the_two_round_trip_shapes_actually_differ():
    """Guards the parametrisation below.

    If both helpers produced the same dict, the case below would run twice and
    cover one thing.
    """
    metadata = build_metadata(make_bug("AP-1", created=""))

    assert faithful(metadata) != lossy(metadata)
    assert "created" in faithful(metadata)
    assert "created" not in lossy(metadata)


@pytest.mark.parametrize("round_trip", [faithful, lossy], ids=["faithful", "lossy"])
def test_an_empty_metadata_value_survives_either_round_trip(round_trip):
    """S11 — an absent key and an empty string must compare equal, both ways.

    chromadb accepts '' as a metadata value on the way in (api/types.py:547-560
    only checks the type), but whether it hands '' back unchanged on the way out
    is not something reading the source settles, and this suite will not run a
    real client to find out. So the comparison normalises both sides instead of
    trusting either answer.

    Without it, every bug with an empty `created` — the default whenever Jira
    omits it — would be re-embedded on every single sync, forever. That is a
    silent loss of the entire feature, not a visible failure, which is why it is
    pinned here rather than left to a log line.

    Both shapes are covered because normalising only the desired side passes the
    lossy case by accident: the stored dict has already lost the key, so it
    happens to match. Only the faithful shape catches that — and the faithful
    shape is the likelier one in production, precisely because chromadb accepts
    '' on the way in.
    """
    bug = make_bug("AP-1", created="")
    document, metadata = indexed(bug)

    plan = plan_sync({"AP-1": (document, round_trip(metadata))}, [bug])

    assert plan.upsert_ids == [], "an absent key and '' must not count as a change"
    assert plan.unchanged == 1


def test_a_real_change_to_an_empty_field_is_still_detected():
    """Guards the normalisation against swallowing a genuine edit.

    Normalising both sides could easily be written so that '' equals anything
    absent-ish; it must not make '' equal to a real value.
    """
    before = make_bug("AP-1", created="")
    after = make_bug("AP-1", created="2026-03-03")
    current = {"AP-1": indexed(before)}

    plan = plan_sync(current, [after])

    assert plan.upsert_ids == ["AP-1"]
