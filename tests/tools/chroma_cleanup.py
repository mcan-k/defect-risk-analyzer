"""
Report what could be swept out of data/chroma_db, and (with --apply) sweep it.

Faz 4(a) PR-1 split the vector store into `defect_history_mock` and
`defect_history_live` and abandoned the old `defect_history` rather than
migrating it — its contents were the mock/live contamination being fixed. It is
still on disk, and so is one HNSW segment directory per load from the era when
every load deleted and recreated the collection. Nothing reads any of it.

This is a tool, not a startup hook. A cleanup that runs by itself is a cleanup
whose bugs delete live data before anyone sees them, so the deleting is manual:
the default mode measures and prints, and only an explicit --apply plus a typed
confirmation removes anything.

The deletion is chromadb's job in name only. `client.delete_collection()` removes
the segment directory and its rows just when the segment happens to already be
loaded in that process (segment/impl/manager/local.py, `delete_segments`: the
work is inside `if segment["id"] in self._instances`). A fresh client deletes the
bookkeeping and leaves the data — which is precisely how the orphans here were
made — and rows already orphaned belong to no collection, so `list_collections`
cannot see them at all. So this works on the SQLite file and the directories
directly, mirroring chroma's own delete order, and never imports chromadb.

Deliberately not named test_*.py so pytest does not collect it: what it reports
is a property of one developer's disk, and a stale segment directory should not
turn the suite red. The decision it makes is pure and is tested, in
tests/test_chroma_cleanup_plan.py and tests/test_chroma_cleanup_apply.py.

Usage: python tests/tools/chroma_cleanup.py [path/to/chroma_db]
"""

import shutil
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from defect_risk_analyzer.adapters.vector_store import (  # noqa: E402  (needs the path above)
    COLLECTION_LIVE,
    COLLECTION_MOCK,
)

# The names to keep, read from the adapter rather than spelled out again. If the
# collections are ever renamed, this tool follows instead of quietly deciding
# that the live data is junk. The import does not pull in chromadb: vector_store
# imports it lazily inside _get_client (vector_store.py:238).
KNOWN_COLLECTIONS = frozenset({COLLECTION_MOCK, COLLECTION_LIVE})

DEFAULT_STORE = REPO_ROOT / "data" / "chroma_db"

# Tables this tool needs to see before it will report anything. A missing one
# means the schema moved under us, which is a stop, not a warning.
REQUIRED_TABLES = (
    "collections",
    "segments",
    "embeddings",
    "embedding_metadata",
    "embedding_fulltext_search",
    "embeddings_queue",
    "max_seq_id",
    "segment_metadata",
    "collection_metadata",
)

# Printed, so it is ASCII on purpose: the default Windows console codepage here
# is cp1254 and an em-dash comes out as a replacement character. Same reason
# core_boundary_check.py's caller pins encoding="utf-8".
REFUSAL = """No known collection is present, so nothing was deleted.

Two different situations look exactly like this from here:

  * this tool is wrong - the collection names moved, the schema moved, the
    chromadb version changed, or this is not the directory you meant. In that
    case nothing on disk was recognised and everything looks like junk.
  * you have not synced yet - the store genuinely holds no live data because no
    refresh has run since the collections were split.

They produce the same inventory, and only one of them makes deleting everything
the right answer. Expected to find one of: {mock}, {live}.

Two ways forward:
  * run a refresh so the collections exist, then run this again; or
  * delete the store by hand. It is gitignored and one refresh rebuilds it."""


class CleanupError(Exception):
    """The store cannot be read, or is not a chroma store."""


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChromaInventory:
    """What is in the store, as plain data. No connection, no paths, no chromadb."""

    collections: tuple[tuple[str, str], ...]  # (id, name)
    segments: tuple[tuple[str, str, str], ...]  # (id, scope, collection_id)
    dirs: tuple[tuple[str, int], ...]  # (directory name, bytes on disk)
    embedding_segments: tuple[tuple[str, int], ...]  # (segment_id, row count)


@dataclass(frozen=True)
class CleanupPlan:
    """What would be removed. Ordered, so two runs print the same report."""

    keep_collection_ids: tuple[str, ...]
    drop_collection_ids: tuple[str, ...]
    keep_segment_ids: tuple[str, ...]
    drop_segment_ids: tuple[str, ...]
    keep_dirs: tuple[str, ...]
    drop_dirs: tuple[str, ...]
    unrecognised_dirs: tuple[str, ...]
    drop_embedding_segment_ids: tuple[str, ...]
    bytes_to_free: int
    refusal: str | None


def _is_segment_dir_name(name: str) -> bool:
    """True only for a canonical dashed UUID, which is how chroma names segments.

    Compared back against the canonical form on purpose: uuid.UUID also accepts
    braced and undashed spellings, and a directory chroma did not create is not
    ours to delete.
    """
    try:
        return str(uuid.UUID(name)) == name.lower()
    except ValueError:
        return False


def plan_cleanup(
    inventory: ChromaInventory,
    known_names: frozenset[str],
) -> CleanupPlan:
    """Decide what goes. Pure: plain data in, a plan out, touches nothing.

    The decision runs off the *keep* set in every case. A directory is deleted
    because `segments` places it under an abandoned collection or does not
    mention it at all — never because it failed some positive test for junk. So
    when the schema grows something this tool has not heard of, it under-deletes.
    """
    keep_collection_ids = tuple(
        sorted(cid for cid, name in inventory.collections if name in known_names)
    )
    drop_collection_ids = tuple(
        sorted(cid for cid, name in inventory.collections if name not in known_names)
    )

    kept_collections = set(keep_collection_ids)
    keep_segment_ids = tuple(
        sorted(sid for sid, _scope, coll in inventory.segments if coll in kept_collections)
    )
    drop_segment_ids = tuple(
        sorted(sid for sid, _scope, coll in inventory.segments if coll not in kept_collections)
    )

    kept_segments = set(keep_segment_ids)
    keep_dirs: list[str] = []
    drop_dirs: list[str] = []
    unrecognised_dirs: list[str] = []
    for name, _size in inventory.dirs:
        if not _is_segment_dir_name(name):
            unrecognised_dirs.append(name)
        elif name in kept_segments:
            keep_dirs.append(name)
        else:
            drop_dirs.append(name)

    drop_embedding_segment_ids = tuple(
        sorted(sid for sid, _rows in inventory.embedding_segments if sid not in kept_segments)
    )

    sizes = dict(inventory.dirs)
    bytes_to_free = sum(sizes[name] for name in drop_dirs)

    # The one case where doing the obvious thing is indistinguishable from a bug
    # in this file. See REFUSAL.
    refusal = (
        None
        if keep_collection_ids
        else REFUSAL.format(mock=COLLECTION_MOCK, live=COLLECTION_LIVE)
    )

    return CleanupPlan(
        keep_collection_ids=keep_collection_ids,
        drop_collection_ids=drop_collection_ids,
        keep_segment_ids=keep_segment_ids,
        drop_segment_ids=drop_segment_ids,
        keep_dirs=tuple(sorted(keep_dirs)),
        drop_dirs=tuple(sorted(drop_dirs)),
        unrecognised_dirs=tuple(sorted(unrecognised_dirs)),
        drop_embedding_segment_ids=drop_embedding_segment_ids,
        bytes_to_free=bytes_to_free,
        refusal=refusal,
    )


# ---------------------------------------------------------------------------
# The SQL, shared by counting and deleting
# ---------------------------------------------------------------------------


def deletion_statements(plan: CleanupPlan) -> list[tuple[str, str, tuple]]:
    """(table, WHERE clause, params) in the order the deletions must run.

    One list, used by both the report (as COUNT) and --apply (as DELETE), so the
    two cannot drift: whatever the report promises to remove is textually the
    same predicate that removes it.

    The order is chroma's own (segment/impl/metadata/sqlite.py:595-648): the
    full-text index first, then embedding_metadata, then embeddings. Both of the
    first two select their victims through a subquery over `embeddings`, so
    emptying `embeddings` first would leave them behind for good.

    The full-text rows are deleted through the fts5 virtual table, never through
    its _content/_data/_docsize/_idx shadow tables — writing to those directly
    corrupts the index.
    """
    keep_segments = plan.keep_segment_ids
    keep_collections = plan.keep_collection_ids

    # An id is never the empty string, so an empty keep list protects nothing —
    # which is the correct reading: no kept collection owns any segment. The
    # refusal is what stops that from meaning "delete the whole store".
    seg_marks = ", ".join("?" * len(keep_segments)) or "''"
    coll_marks = ", ".join("?" * len(keep_collections)) or "''"

    doomed_embeddings = f"SELECT id FROM embeddings WHERE segment_id NOT IN ({seg_marks})"

    statements: list[tuple[str, str, tuple]] = [
        ("embedding_fulltext_search", f"rowid IN ({doomed_embeddings})", keep_segments),
        ("embedding_metadata", f"id IN ({doomed_embeddings})", keep_segments),
        ("embeddings", f"segment_id NOT IN ({seg_marks})", keep_segments),
    ]

    # Matched by suffix rather than by rebuilding "persistent://default/default/<id>":
    # if the namespace format moves, a suffix match still finds the row, while a
    # reconstructed string would silently leave it behind.
    for collection_id in plan.drop_collection_ids:
        statements.append(("embeddings_queue", "topic LIKE '%' || ?", (collection_id,)))

    statements += [
        ("max_seq_id", f"segment_id NOT IN ({seg_marks})", keep_segments),
        ("segment_metadata", f"segment_id NOT IN ({seg_marks})", keep_segments),
        ("segments", f"id NOT IN ({seg_marks})", keep_segments),
        ("collection_metadata", f"collection_id NOT IN ({coll_marks})", keep_collections),
    ]

    if plan.drop_collection_ids:
        marks = ", ".join("?" * len(plan.drop_collection_ids))
        statements.append(("collections", f"id IN ({marks})", plan.drop_collection_ids))

    return statements


def count_doomed_rows(conn: sqlite3.Connection, plan: CleanupPlan) -> list[tuple[str, int]]:
    """How many rows each deletion would remove, in the same order."""
    counts: list[tuple[str, int]] = []
    for table, where, params in deletion_statements(plan):
        (n,) = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()
        counts.append((table, n))
    return counts


# ---------------------------------------------------------------------------
# Reading the store
# ---------------------------------------------------------------------------


def read_only_connection(db_path: Path) -> sqlite3.Connection:
    """Open the store so that reading it cannot possibly change it.

    `immutable=1` also promises SQLite that nothing else is writing, which is why
    hot_journal_files() is checked before this is trusted.
    """
    uri = "file:/" + db_path.resolve().as_posix().lstrip("/") + "?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def hot_journal_files(store: Path) -> list[str]:
    """Journal/WAL siblings, which mean an open connection or a crashed one.

    Not proof of either: one can outlive a crash with nobody attached. It is
    enough to stop and ask, which is all it is used for.
    """
    return sorted(
        p.name
        for p in store.iterdir()
        if p.is_file() and p.name.startswith("chroma.sqlite3-")
    )


def directory_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def read_inventory(store: Path) -> ChromaInventory:
    """Measure the store. Read-only, and the only place that touches disk to plan."""
    if not store.is_dir():
        raise CleanupError(f"{store} does not exist or is not a directory.")

    db_path = store / "chroma.sqlite3"
    if not db_path.is_file():
        raise CleanupError(f"{store} holds no chroma.sqlite3, so it is not a chroma store.")

    conn = read_only_connection(db_path)
    try:
        present = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        missing = [t for t in REQUIRED_TABLES if t not in present]
        if missing:
            raise CleanupError(
                f"{db_path} is missing {', '.join(missing)}. The schema is not the one "
                "this tool was written against (chromadb 0.5.23); refusing to guess."
            )

        collections = tuple(conn.execute("SELECT id, name FROM collections"))
        segments = tuple(conn.execute("SELECT id, scope, collection FROM segments"))
        embedding_segments = tuple(
            conn.execute("SELECT segment_id, COUNT(*) FROM embeddings GROUP BY segment_id")
        )
    finally:
        conn.close()

    dirs = tuple((p.name, directory_size(p)) for p in store.iterdir() if p.is_dir())

    return ChromaInventory(
        collections=collections,
        segments=segments,
        dirs=dirs,
        embedding_segments=embedding_segments,
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def human(n: int) -> str:
    return f"{n:,} bytes"


def sqlite_size(db_path: Path) -> tuple[int, int]:
    """(file bytes, page count). Both are printed before and after --apply."""
    conn = read_only_connection(db_path)
    try:
        (pages,) = conn.execute("PRAGMA page_count").fetchone()
    finally:
        conn.close()
    return db_path.stat().st_size, pages


def print_report(store: Path, inventory: ChromaInventory, plan: CleanupPlan) -> None:
    """The whole inventory, printed whether or not the plan refuses.

    Refusing without showing what is there would send the reader straight to a
    blind `rm -rf`, which is the uninformed deletion this tool exists to avoid.
    """
    db_path = store / "chroma.sqlite3"
    size, pages = sqlite_size(db_path)
    names = dict(inventory.collections)

    print(f"CHROMA CLEANUP REPORT  ({store})")
    print(f"  chroma.sqlite3   {human(size)}, {pages} pages")
    print(f"  known names      {', '.join(sorted(KNOWN_COLLECTIONS))}")

    print("\nCOLLECTIONS")
    if not inventory.collections:
        print("  (none)")
    for cid in plan.keep_collection_ids:
        print(f"  keep  {names[cid]:<28} {cid}")
    for cid in plan.drop_collection_ids:
        print(f"  DROP  {names[cid]:<28} {cid}")

    print("\nSEGMENT DIRECTORIES")
    print(f"  keep          {len(plan.keep_dirs):>4}")
    print(f"  DROP          {len(plan.drop_dirs):>4}   {human(plan.bytes_to_free)}")
    print(f"  unrecognised  {len(plan.unrecognised_dirs):>4}   left alone")
    for name in plan.unrecognised_dirs:
        print(f"                     {name}")

    print("\nROWS TO DELETE")
    conn = read_only_connection(db_path)
    try:
        for table, n in count_doomed_rows(conn, plan):
            print(f"  {table:<28} {n:>6}")
    finally:
        conn.close()

    hot = hot_journal_files(store)
    if hot:
        print("\nWARNING")
        print(f"  {', '.join(hot)} present — something may be using this store.")
        print("  The numbers above were read with immutable=1 and may be stale.")

    if plan.refusal:
        print("\nREFUSING")
        for line in plan.refusal.splitlines():
            print(f"  {line}" if line else "")


# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------


def stdin_is_interactive() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()


def read_confirmation() -> str:
    return input("  type the number to proceed: ")


def confirm(plan: CleanupPlan, read_line) -> bool:
    """Proceed only if the reader types back the number of directories to remove.

    Not a y/n: "y" is reachable by pressing Enter twice without reading anything,
    and this is the prompt standing in front of an irreversible delete. Typing
    the count means the report above was actually looked at.
    """
    expected = str(len(plan.drop_dirs))
    print(f"\nAbout to delete {expected} segment directories and the rows listed above.")
    print(f"This cannot be undone. To confirm, type: {expected}")
    return read_line().strip() == expected


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApplyOutcome:
    deleted_rows: tuple[tuple[str, int], ...]
    deleted_dirs: int
    bytes_freed: int
    size_before: int
    size_after: int
    pages_before: int
    pages_after: int
    problems: tuple[str, ...]


def verify_consistency(conn: sqlite3.Connection, store: Path) -> tuple[str, ...]:
    """Re-read the store and complain about anything still dangling.

    Run after the deletions rather than trusted from them: this tool writes SQL
    by hand against someone else's schema, and the cheapest way to find out that
    a predicate was wrong is to ask the database instead of assuming.
    """
    problems: list[str] = []

    dangling = {
        "embeddings under a segment that no longer exists": (
            "SELECT COUNT(*) FROM embeddings WHERE segment_id NOT IN (SELECT id FROM segments)"
        ),
        "embedding_metadata with no embedding": (
            "SELECT COUNT(*) FROM embedding_metadata WHERE id NOT IN (SELECT id FROM embeddings)"
        ),
        "full-text rows with no embedding": (
            "SELECT COUNT(*) FROM embedding_fulltext_search "
            "WHERE rowid NOT IN (SELECT id FROM embeddings)"
        ),
        "segment_metadata for a segment that no longer exists": (
            "SELECT COUNT(*) FROM segment_metadata "
            "WHERE segment_id NOT IN (SELECT id FROM segments)"
        ),
        "max_seq_id for a segment that no longer exists": (
            "SELECT COUNT(*) FROM max_seq_id WHERE segment_id NOT IN (SELECT id FROM segments)"
        ),
        "collection_metadata for a collection that no longer exists": (
            "SELECT COUNT(*) FROM collection_metadata "
            "WHERE collection_id NOT IN (SELECT id FROM collections)"
        ),
        "segments under a collection that no longer exists": (
            "SELECT COUNT(*) FROM segments WHERE collection NOT IN (SELECT id FROM collections)"
        ),
    }
    for description, sql in dangling.items():
        (n,) = conn.execute(sql).fetchone()
        if n:
            problems.append(f"{n} {description}")

    registered = {row[0] for row in conn.execute("SELECT id FROM segments")}
    for path in store.iterdir():
        if path.is_dir() and _is_segment_dir_name(path.name) and path.name not in registered:
            problems.append(f"segment directory {path.name} survives but is registered nowhere")

    return tuple(problems)


def apply_cleanup(store: Path, plan: CleanupPlan) -> ApplyOutcome:
    """Do it. Deletions first and committed, then directories, then VACUUM.

    VACUUM last and outside the transaction because SQLite will not run one with
    a transaction open on the connection, and after it because there is nothing
    to reclaim until the deletions are committed.
    """
    if plan.refusal:
        raise CleanupError(plan.refusal)

    db_path = store / "chroma.sqlite3"
    size_before, pages_before = sqlite_size(db_path)

    # VACUUM rebuilds the file beside the original before replacing it, so the
    # documented requirement is up to twice the file's size in free space.
    free = shutil.disk_usage(store).free
    if free < size_before * 2:
        raise CleanupError(
            f"VACUUM needs up to {human(size_before * 2)} free and only {human(free)} "
            "is available. Nothing was changed."
        )

    backup = store / "chroma.sqlite3.bak"
    stage = "taking the backup"
    conn = None
    try:
        shutil.copy2(db_path, backup)

        stage = "deleting rows"
        conn = sqlite3.connect(db_path)
        # We drive the transaction ourselves: sqlite3 would otherwise hold one
        # open and VACUUM below would fail.
        conn.isolation_level = None

        statements = deletion_statements(plan)
        conn.execute("BEGIN")
        # Counted before deleting, using the identical predicate the report used,
        # so the number shown and the number removed cannot be two different
        # things. That the rows are actually gone is verify_consistency's job.
        deleted_rows = []
        for table, where, params in statements:
            (n,) = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {where}", params
            ).fetchone()
            conn.execute(f"DELETE FROM {table} WHERE {where}", params)
            deleted_rows.append((table, n))
        conn.execute("COMMIT")

        stage = "removing segment directories"
        for name in plan.drop_dirs:
            shutil.rmtree(store / name)

        stage = "vacuuming"
        conn.execute("VACUUM")

        stage = "verifying"
        problems = verify_consistency(conn, store)
        (pages_after,) = conn.execute("PRAGMA page_count").fetchone()
        conn.close()
        conn = None

        backup.unlink()

        return ApplyOutcome(
            deleted_rows=tuple(deleted_rows),
            deleted_dirs=len(plan.drop_dirs),
            bytes_freed=plan.bytes_to_free,
            size_before=size_before,
            size_after=db_path.stat().st_size,
            pages_before=pages_before,
            pages_after=pages_after,
            problems=problems,
        )
    except Exception as exc:
        if conn is not None:
            conn.close()
        print(f"\nFAILED while {stage}: {exc}")
        print(f"A copy of the database from before the run is at {backup}")
        if stage in ("taking the backup", "deleting rows"):
            print(
                "No directory was removed, so copying that file back over "
                "chroma.sqlite3 returns the store to where it started."
            )
        else:
            print(
                "Copying that file back is NOT on its own a repair: segment "
                "directories may already be gone, so SQLite would then describe "
                "vectors that are not on disk. The way out is to delete the store "
                "entirely and run a refresh - it is gitignored and one refresh "
                "rebuilds it."
            )
        raise CleanupError(f"cleanup failed while {stage}: {exc}") from exc


def print_outcome(outcome: ApplyOutcome) -> None:
    print("\nDONE")
    print(f"  directories removed  {outcome.deleted_dirs:>6}   {human(outcome.bytes_freed)}")
    for table, n in outcome.deleted_rows:
        print(f"  {table:<28} {n:>6}")
    print(f"  chroma.sqlite3       {human(outcome.size_before)} -> {human(outcome.size_after)}")
    print(f"  pages                {outcome.pages_before} -> {outcome.pages_after}")
    if outcome.problems:
        print("\nPROBLEMS FOUND AFTER CLEANUP")
        for problem in outcome.problems:
            print(f"  {problem}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    applying = "--apply" in sys.argv[1:]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    store = Path(args[0]) if args else DEFAULT_STORE

    try:
        inventory = read_inventory(store)
    except CleanupError as exc:
        print(exc)
        return 1

    plan = plan_cleanup(inventory, KNOWN_COLLECTIONS)
    print_report(store, inventory, plan)

    if not applying:
        print("\nNothing was written. This mode only measures.")
        print("Re-run with --apply to delete what is listed above.")
        return 0

    if plan.refusal:
        return 1

    hot = hot_journal_files(store)
    if hot:
        print(f"\nNot applying: {', '.join(hot)} present.")
        print("Something may be using this store - check the dashboard and webhook are stopped.")
        return 1

    if not stdin_is_interactive():
        print("\nNot applying: --apply needs a terminal, so a person can confirm.")
        return 1

    if not confirm(plan, read_confirmation):
        print("Cancelled. Nothing was deleted.")
        return 1

    try:
        outcome = apply_cleanup(store, plan)
    except CleanupError as exc:
        print(exc)
        return 1

    print_outcome(outcome)
    return 1 if outcome.problems else 0


if __name__ == "__main__":
    sys.exit(main())
