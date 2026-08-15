"""
The cleanup plan: what gets deleted from data/chroma_db, decided without touching it.

Faz 4(a) PR-1 abandoned the old `defect_history` collection rather than migrating
it, and the loads before it left one HNSW segment directory behind per load. The
tool this file tests sweeps both up. Its dangerous half is obvious: a wrong
"orphan" definition deletes a live collection's segment, and the vectors are gone.

So the decision is a pure function over plain data — an inventory in, a list of
things to delete out — and it is tested here with no sqlite, no filesystem and no
ChromaDB, exactly as `plan_sync` is tested in test_vector_sync.py. The apply path
that acts on a plan is pinned separately in test_chroma_cleanup_apply.py.

Two rules carry the safety, and both are pinned from both directions below:

  * a directory is deleted only when the `segments` table says it belongs to an
    abandoned collection, or does not appear there at all. Anything registered
    and unrecognised is kept — when the schema grows, this tool under-deletes.
  * when no known collection is present at all, the plan refuses. "The tool is
    broken" (names moved, schema moved, wrong directory) and "the user has not
    synced yet" produce the identical inventory, and one of them makes deleting
    everything look correct. Same call as the empty-list guard in
    `upsert_bugs` (vector_store.py:397-402): when the two cannot be told apart,
    take the conservative reading.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from defect_risk_analyzer.adapters.vector_store import COLLECTION_LIVE, COLLECTION_MOCK

# =============================================================================
# Loading the tool
# =============================================================================

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tests" / "tools" / "chroma_cleanup.py"


def _load_tool():
    """Import the tool by path.

    `tests/tools/` is deliberately not a package (no __init__.py) because pytest
    must not collect what lives there, so there is no import path to it. Loading
    by location keeps that arrangement and avoids putting maintenance-only code
    into src/ just to make it importable.
    """
    assert TOOL_PATH.is_file(), (
        f"{TOOL_PATH} is missing. If the tool was renamed, rename it here too "
        "rather than letting this suite quietly test nothing."
    )
    spec = importlib.util.spec_from_file_location("chroma_cleanup", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["chroma_cleanup"] = module
    spec.loader.exec_module(module)
    return module


cleanup = _load_tool()

KNOWN = frozenset({COLLECTION_MOCK, COLLECTION_LIVE})

# =============================================================================
# Fixture data
# =============================================================================

# Collections
MOCK_COLL = "11111111-1111-4111-8111-111111111111"
LIVE_COLL = "22222222-2222-4222-8222-222222222222"
DEAD_COLL = "33333333-3333-4333-8333-333333333333"

# Segments. The *_VEC ids double as directory names on disk — that identity is
# the whole basis of the orphan rule, so the fixtures spell it out rather than
# hiding it behind a helper.
MOCK_VEC = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MOCK_META = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
LIVE_VEC = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
LIVE_META = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
DEAD_VEC = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
DEAD_META = "ffffffff-ffff-4fff-8fff-ffffffffffff"

# Directories left behind by loads whose collection is long gone.
ORPHAN_DIR_A = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
ORPHAN_DIR_B = "0b0b0b0b-0b0b-4b0b-8b0b-0b0b0b0b0b0b"

SEG_BYTES = 1_680_100  # measured: every segment directory on disk is this size


def make_inventory(
    *,
    collections=((MOCK_COLL, COLLECTION_MOCK),),
    segments=((MOCK_VEC, "VECTOR", MOCK_COLL), (MOCK_META, "METADATA", MOCK_COLL)),
    dirs=((MOCK_VEC, SEG_BYTES),),
    embedding_segments=((MOCK_META, 20),),
):
    """An inventory whose default is the healthy case: one known collection, nothing stray.

    Every test overrides exactly the part it is about, so a failure names the
    thing that changed.
    """
    return cleanup.ChromaInventory(
        collections=tuple(collections),
        segments=tuple(segments),
        dirs=tuple(dirs),
        embedding_segments=tuple(embedding_segments),
    )


def assert_cleanup_invariants(plan, inventory) -> None:
    """Structural rules every plan obeys, whatever the inventory.

    Called from every case rather than tested once on its own. The first two are
    the load-bearing ones: they are what stands between this tool and deleting a
    live collection's vectors. If a future change makes keep and drop overlap,
    every test in this file fails at once, which is the intent.
    """
    assert not set(plan.drop_dirs) & set(plan.keep_dirs), (
        f"directory in both keep and drop: "
        f"{sorted(set(plan.drop_dirs) & set(plan.keep_dirs))}"
    )
    assert not set(plan.drop_segment_ids) & set(plan.keep_segment_ids), (
        f"segment in both keep and drop: "
        f"{sorted(set(plan.drop_segment_ids) & set(plan.keep_segment_ids))}"
    )
    assert not set(plan.drop_collection_ids) & set(plan.keep_collection_ids), (
        "a collection is both kept and dropped"
    )

    # No segment of a kept collection may be dropped, by any route.
    kept_collection_segments = {
        seg_id
        for seg_id, _scope, coll in inventory.segments
        if coll in plan.keep_collection_ids
    }
    assert not kept_collection_segments & set(plan.drop_segment_ids), (
        "a segment belonging to a kept collection is scheduled for deletion"
    )
    assert not kept_collection_segments & set(plan.drop_dirs), (
        "a directory belonging to a kept collection's segment is scheduled for deletion"
    )

    # A directory the tool does not recognise is neither kept nor dropped — it is
    # left alone, which is a third state and must stay one.
    assert not set(plan.unrecognised_dirs) & set(plan.drop_dirs), (
        "an unrecognised directory is scheduled for deletion"
    )

    sizes = dict(inventory.dirs)
    assert plan.bytes_to_free == sum(sizes[d] for d in plan.drop_dirs), (
        "bytes_to_free must count the dropped directories and nothing else"
    )


# =============================================================================
# The happy path: known collections survive
# =============================================================================


def test_a_known_collection_is_kept_whole():
    """Nothing stray in the store, so the plan is empty and does not refuse."""
    inv = make_inventory()
    plan = cleanup.plan_cleanup(inv, KNOWN)
    assert_cleanup_invariants(plan, inv)

    assert plan.refusal is None
    assert plan.drop_collection_ids == ()
    assert plan.drop_segment_ids == ()
    assert plan.drop_dirs == ()
    assert plan.drop_embedding_segment_ids == ()
    assert plan.bytes_to_free == 0
    assert set(plan.keep_segment_ids) == {MOCK_VEC, MOCK_META}
    assert plan.keep_dirs == (MOCK_VEC,)


def test_both_known_collections_are_kept():
    """Mock and live coexist after PR-1; keeping only one of them would be a data loss."""
    inv = make_inventory(
        collections=((MOCK_COLL, COLLECTION_MOCK), (LIVE_COLL, COLLECTION_LIVE)),
        segments=(
            (MOCK_VEC, "VECTOR", MOCK_COLL),
            (MOCK_META, "METADATA", MOCK_COLL),
            (LIVE_VEC, "VECTOR", LIVE_COLL),
            (LIVE_META, "METADATA", LIVE_COLL),
        ),
        dirs=((MOCK_VEC, SEG_BYTES), (LIVE_VEC, SEG_BYTES)),
        embedding_segments=((MOCK_META, 20), (LIVE_META, 37)),
    )
    plan = cleanup.plan_cleanup(inv, KNOWN)
    assert_cleanup_invariants(plan, inv)

    assert set(plan.keep_collection_ids) == {MOCK_COLL, LIVE_COLL}
    assert plan.drop_dirs == ()
    assert plan.drop_embedding_segment_ids == ()


def test_a_segment_with_an_unrecognised_scope_is_kept():
    """An unknown scope on a kept collection means the schema grew, not that the row is junk.

    The rule keys on the collection, never on the scope, so a chromadb upgrade
    that adds a third segment scope makes this tool delete less rather than more.
    """
    inv = make_inventory(
        segments=(
            (MOCK_VEC, "VECTOR", MOCK_COLL),
            (MOCK_META, "METADATA", MOCK_COLL),
            (ORPHAN_DIR_A, "SOMETHING_NEW", MOCK_COLL),
        ),
        dirs=((MOCK_VEC, SEG_BYTES), (ORPHAN_DIR_A, SEG_BYTES)),
    )
    plan = cleanup.plan_cleanup(inv, KNOWN)
    assert_cleanup_invariants(plan, inv)

    assert ORPHAN_DIR_A in plan.keep_segment_ids
    assert ORPHAN_DIR_A not in plan.drop_dirs


# =============================================================================
# The abandoned collection
# =============================================================================


def test_an_unknown_collection_name_is_abandoned_and_dropped():
    """`defect_history` is not in the known set, so it and everything under it goes."""
    inv = make_inventory(
        collections=((MOCK_COLL, COLLECTION_MOCK), (DEAD_COLL, "defect_history")),
        segments=(
            (MOCK_VEC, "VECTOR", MOCK_COLL),
            (MOCK_META, "METADATA", MOCK_COLL),
            (DEAD_VEC, "VECTOR", DEAD_COLL),
            (DEAD_META, "METADATA", DEAD_COLL),
        ),
        dirs=((MOCK_VEC, SEG_BYTES), (DEAD_VEC, SEG_BYTES)),
        embedding_segments=((MOCK_META, 20), (DEAD_META, 20)),
    )
    plan = cleanup.plan_cleanup(inv, KNOWN)
    assert_cleanup_invariants(plan, inv)

    assert plan.drop_collection_ids == (DEAD_COLL,)
    assert set(plan.drop_segment_ids) == {DEAD_VEC, DEAD_META}
    assert plan.drop_dirs == (DEAD_VEC,)
    assert plan.drop_embedding_segment_ids == (DEAD_META,)
    assert plan.keep_dirs == (MOCK_VEC,)
    assert plan.bytes_to_free == SEG_BYTES


# =============================================================================
# Orphans — rows and directories whose collection is already gone
# =============================================================================


def test_a_directory_with_no_segment_row_is_an_orphan():
    """The 46 directories on disk today: registered nowhere, referenced by nothing."""
    inv = make_inventory(
        dirs=((MOCK_VEC, SEG_BYTES), (ORPHAN_DIR_A, SEG_BYTES), (ORPHAN_DIR_B, SEG_BYTES)),
    )
    plan = cleanup.plan_cleanup(inv, KNOWN)
    assert_cleanup_invariants(plan, inv)

    assert set(plan.drop_dirs) == {ORPHAN_DIR_A, ORPHAN_DIR_B}
    assert plan.keep_dirs == (MOCK_VEC,)
    assert plan.bytes_to_free == 2 * SEG_BYTES


def test_embedding_rows_under_a_vanished_segment_are_dropped():
    """The 956 rows measured today: their segment_id is in no `segments` row at all."""
    inv = make_inventory(
        embedding_segments=((MOCK_META, 20), (ORPHAN_DIR_A, 20), (ORPHAN_DIR_B, 24)),
    )
    plan = cleanup.plan_cleanup(inv, KNOWN)
    assert_cleanup_invariants(plan, inv)

    assert set(plan.drop_embedding_segment_ids) == {ORPHAN_DIR_A, ORPHAN_DIR_B}
    assert MOCK_META not in plan.drop_embedding_segment_ids


def test_a_segment_row_whose_collection_vanished_is_dropped():
    """A dangling `segments` row — collection deleted, segment row left behind."""
    inv = make_inventory(
        segments=(
            (MOCK_VEC, "VECTOR", MOCK_COLL),
            (MOCK_META, "METADATA", MOCK_COLL),
            (DEAD_VEC, "VECTOR", DEAD_COLL),  # DEAD_COLL is in no collections row
        ),
        dirs=((MOCK_VEC, SEG_BYTES), (DEAD_VEC, SEG_BYTES)),
    )
    plan = cleanup.plan_cleanup(inv, KNOWN)
    assert_cleanup_invariants(plan, inv)

    assert DEAD_VEC in plan.drop_segment_ids
    assert DEAD_VEC in plan.drop_dirs


@pytest.mark.parametrize(
    "name", ["chroma.sqlite3.bak", "notes.txt", "scratch", ".ipynb_checkpoints"]
)
def test_a_directory_that_is_not_a_uuid_is_left_alone(name):
    """Anything the user put there by hand is not ours to delete.

    Chroma names every segment directory after a UUID, so a name that will not
    parse as one cannot be a segment — and a cleanup tool that deletes files it
    cannot account for is worse than the mess it removes.
    """
    inv = make_inventory(dirs=((MOCK_VEC, SEG_BYTES), (name, 4096)))
    plan = cleanup.plan_cleanup(inv, KNOWN)
    assert_cleanup_invariants(plan, inv)

    assert name in plan.unrecognised_dirs
    assert name not in plan.drop_dirs
    assert name not in plan.keep_dirs
    assert plan.bytes_to_free == 0


def test_bytes_to_free_counts_only_what_is_dropped():
    """The headline number in the report. Counting kept directories would oversell it."""
    inv = make_inventory(
        dirs=((MOCK_VEC, 999), (ORPHAN_DIR_A, 100), (ORPHAN_DIR_B, 250), ("notes.txt", 7)),
    )
    plan = cleanup.plan_cleanup(inv, KNOWN)
    assert_cleanup_invariants(plan, inv)

    assert plan.bytes_to_free == 350


# =============================================================================
# The refusal
# =============================================================================


def test_an_empty_store_refuses():
    """No collections at all. Could be a fresh directory, could be the wrong path."""
    inv = make_inventory(collections=(), segments=(), dirs=(), embedding_segments=())
    plan = cleanup.plan_cleanup(inv, KNOWN)
    assert_cleanup_invariants(plan, inv)

    assert plan.refusal is not None


def test_only_an_abandoned_collection_refuses():
    """Today's measured state: `defect_history` alone, mock and live never created.

    Deleting everything here would be correct *and* indistinguishable from the
    case where this tool simply failed to recognise the collection names — so it
    refuses instead of guessing.
    """
    inv = make_inventory(
        collections=((DEAD_COLL, "defect_history"),),
        segments=((DEAD_VEC, "VECTOR", DEAD_COLL), (DEAD_META, "METADATA", DEAD_COLL)),
        dirs=((DEAD_VEC, SEG_BYTES), (ORPHAN_DIR_A, SEG_BYTES)),
        embedding_segments=((DEAD_META, 20), (ORPHAN_DIR_A, 20)),
    )
    plan = cleanup.plan_cleanup(inv, KNOWN)
    assert_cleanup_invariants(plan, inv)

    assert plan.refusal is not None


def test_the_refusal_still_reports_a_full_inventory():
    """Refusing is not the same as saying nothing — the user must see what is there.

    Report mode prints the plan whether or not it refuses, so the plan has to be
    populated in the refusing case too.
    """
    inv = make_inventory(
        collections=((DEAD_COLL, "defect_history"),),
        segments=((DEAD_VEC, "VECTOR", DEAD_COLL), (DEAD_META, "METADATA", DEAD_COLL)),
        dirs=((DEAD_VEC, SEG_BYTES), (ORPHAN_DIR_A, SEG_BYTES)),
        embedding_segments=((DEAD_META, 20), (ORPHAN_DIR_A, 20)),
    )
    plan = cleanup.plan_cleanup(inv, KNOWN)

    assert plan.drop_collection_ids == (DEAD_COLL,)
    assert set(plan.drop_dirs) == {DEAD_VEC, ORPHAN_DIR_A}
    assert plan.bytes_to_free == 2 * SEG_BYTES


def test_the_refusal_names_both_possibilities_and_a_way_out():
    """The message is the whole safety feature — a bare "refused" would send the user

    straight to `rm -rf`, which is exactly the uninformed deletion being avoided.
    """
    inv = make_inventory(collections=(), segments=(), dirs=(), embedding_segments=())
    message = cleanup.plan_cleanup(inv, KNOWN).refusal

    assert message is not None
    lowered = message.lower()
    # Both readings of the same inventory.
    assert "recognis" in lowered or "recogniz" in lowered, (
        "the message must raise the possibility that the tool itself is wrong"
    )
    assert "synced" in lowered or "sync" in lowered, (
        "the message must raise the possibility that the user simply has no data yet"
    )
    # Both ways out.
    assert "refresh" in lowered
    assert "delete" in lowered
    # The known names, so the user can compare them against what is on disk.
    assert COLLECTION_MOCK in message and COLLECTION_LIVE in message


def test_a_known_collection_present_does_not_refuse():
    """The refusal keys on the keep set being empty, not on there being nothing to do."""
    inv = make_inventory(dirs=((MOCK_VEC, SEG_BYTES), (ORPHAN_DIR_A, SEG_BYTES)))
    plan = cleanup.plan_cleanup(inv, KNOWN)
    assert_cleanup_invariants(plan, inv)

    assert plan.refusal is None
    assert plan.drop_dirs == (ORPHAN_DIR_A,)


# =============================================================================
# Determinism
# =============================================================================


def test_the_plan_is_ordered():
    """Two runs over the same store must print the same report, line for line."""
    inv = make_inventory(
        dirs=((ORPHAN_DIR_B, SEG_BYTES), (MOCK_VEC, SEG_BYTES), (ORPHAN_DIR_A, SEG_BYTES)),
        embedding_segments=((ORPHAN_DIR_B, 20), (MOCK_META, 20), (ORPHAN_DIR_A, 24)),
    )
    plan = cleanup.plan_cleanup(inv, KNOWN)
    assert_cleanup_invariants(plan, inv)

    assert list(plan.drop_dirs) == sorted(plan.drop_dirs)
    assert list(plan.drop_embedding_segment_ids) == sorted(plan.drop_embedding_segment_ids)
    assert list(plan.drop_segment_ids) == sorted(plan.drop_segment_ids)
