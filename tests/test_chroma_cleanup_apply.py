"""
The apply path: what the cleanup tool actually removes from a store on disk.

test_chroma_cleanup_plan.py pins the decision. This pins the execution against a
real SQLite file and real directories, built under tmp_path from chroma 0.5.23's
own DDL. The repo's own data/chroma_db is never named here — the tool takes the
store path as an argument precisely so these tests can point somewhere else, and
conftest's _guard_repo_chroma_dir stays satisfied because nothing goes near it.

The schema is written out by hand rather than obtained by importing chromadb.
Two reasons: importing chromadb would drag fastapi and friends into a test run
that core_boundary_check.py exists to keep them out of, and a synthetic store
built from the DDL is the only way to have known-orphaned rows to delete — a real
client cannot create them on purpose, it can only leak them.

The load-bearing case is `test_a_refusing_plan_deletes_nothing`. Everything else
here checks that the right things go; that one checks that nothing goes when the
tool cannot tell "no live data" from "I failed to recognise the live data".
"""

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from defect_risk_analyzer.adapters.vector_store import COLLECTION_MOCK

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tests" / "tools" / "chroma_cleanup.py"


def _load_tool():
    assert TOOL_PATH.is_file(), f"{TOOL_PATH} is missing."
    spec = importlib.util.spec_from_file_location("chroma_cleanup", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["chroma_cleanup"] = module
    spec.loader.exec_module(module)
    return module


cleanup = _load_tool()

# =============================================================================
# Building a store
# =============================================================================

TENANT = "default_tenant"
DATABASE = "00000000-0000-0000-0000-000000000000"

KEEP_COLL = "11111111-1111-4111-8111-111111111111"
DEAD_COLL = "33333333-3333-4333-8333-333333333333"
GONE_COLL = "99999999-9999-4999-8999-999999999999"  # deleted long ago, rows left behind

KEEP_VEC = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
KEEP_META = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
DEAD_VEC = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
DEAD_META = "ffffffff-ffff-4fff-8fff-ffffffffffff"
ORPHAN_A = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
ORPHAN_B = "0b0b0b0b-0b0b-4b0b-8b0b-0b0b0b0b0b0b"

# chroma's schema, read off the developer store's sqlite_master (chromadb 0.5.23).
SCHEMA = """
CREATE TABLE tenants (id TEXT PRIMARY KEY, UNIQUE (id));
CREATE TABLE databases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    UNIQUE (tenant_id, name)
);
CREATE TABLE "collections" (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    dimension INTEGER,
    database_id TEXT NOT NULL REFERENCES databases(id) ON DELETE CASCADE,
    config_json_str TEXT,
    UNIQUE (name, database_id)
);
CREATE TABLE collection_metadata (
    collection_id TEXT REFERENCES collections(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    str_value TEXT, int_value INTEGER, float_value REAL, bool_value INTEGER,
    PRIMARY KEY (collection_id, key)
);
CREATE TABLE "segments" (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    scope TEXT NOT NULL,
    collection TEXT REFERENCES collection(id) NOT NULL
);
CREATE TABLE segment_metadata (
    segment_id TEXT REFERENCES segments(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    str_value TEXT, int_value INTEGER, float_value REAL, bool_value INTEGER,
    PRIMARY KEY (segment_id, key)
);
CREATE TABLE embeddings (
    id INTEGER PRIMARY KEY,
    segment_id TEXT NOT NULL,
    embedding_id TEXT NOT NULL,
    seq_id BLOB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (segment_id, embedding_id)
);
CREATE TABLE embedding_metadata (
    id INTEGER REFERENCES embeddings(id),
    key TEXT NOT NULL,
    string_value TEXT, int_value INTEGER, float_value REAL, bool_value INTEGER,
    PRIMARY KEY (id, key)
);
CREATE VIRTUAL TABLE embedding_fulltext_search USING fts5(string_value, tokenize='trigram');
CREATE TABLE embeddings_queue (
    seq_id INTEGER PRIMARY KEY,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    operation INTEGER NOT NULL,
    topic TEXT NOT NULL,
    id TEXT NOT NULL,
    vector BLOB, encoding TEXT, metadata TEXT
);
CREATE TABLE max_seq_id (segment_id TEXT PRIMARY KEY, seq_id BLOB NOT NULL);
CREATE TABLE maintenance_log (id INTEGER PRIMARY KEY, timestamp INTEGER, operation TEXT);
"""

METADATA_KEYS = ("key", "summary", "component", "priority", "status", "created", "chroma:document")


def _add_embeddings(conn, segment_id, count, start_id):
    """`count` embeddings under `segment_id`, each with metadata and one full-text row.

    One full-text row per embedding, keyed by embeddings.id — not one per metadata
    key. That is what chroma does (segment/impl/metadata/sqlite.py:389-416 inserts
    rowid=id with the `chroma:document` value only), and it is what the developer
    store shows: 976 embeddings, 976 full-text rows, 6832 metadata rows.
    """
    next_id = start_id
    for _n in range(count):
        conn.execute(
            "INSERT INTO embeddings (id, segment_id, embedding_id, seq_id) VALUES (?, ?, ?, ?)",
            (next_id, segment_id, f"AP-{next_id}", b"\x00" * 8),
        )
        for key in METADATA_KEYS:
            conn.execute(
                "INSERT INTO embedding_metadata (id, key, string_value) VALUES (?, ?, ?)",
                (next_id, key, f"{key} value for AP-{next_id} " + "padding " * 6),
            )
        conn.execute(
            "INSERT INTO embedding_fulltext_search (rowid, string_value) VALUES (?, ?)",
            (next_id, f"document for AP-{next_id} " + "padding " * 12),
        )
        next_id += 1
    return next_id


def build_store(tmp_path, *, include_keep=True):
    """A store holding one live collection, one abandoned one, and two orphan segments.

    The orphan rows are the point: `embeddings` under a segment_id that appears in
    no `segments` row, which is exactly what 46 wholesale deletes left on the
    developer's disk and what no live chroma client can be made to produce.

    `include_keep=False` reproduces today's measured state — the abandoned
    collection alone, nothing recognised.
    """
    store = tmp_path / "chroma_db"
    store.mkdir()
    db_path = store / "chroma.sqlite3"

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    conn.execute("INSERT INTO tenants (id) VALUES (?)", (TENANT,))
    conn.execute(
        "INSERT INTO databases (id, name, tenant_id) VALUES (?, ?, ?)",
        (DATABASE, "default_database", TENANT),
    )

    collections = [(DEAD_COLL, "defect_history")]
    if include_keep:
        collections.insert(0, (KEEP_COLL, COLLECTION_MOCK))
    for cid, name in collections:
        conn.execute(
            "INSERT INTO collections (id, name, dimension, database_id, config_json_str) "
            "VALUES (?, ?, 384, ?, '{}')",
            (cid, name, DATABASE),
        )
        conn.execute(
            "INSERT INTO collection_metadata (collection_id, key, str_value) VALUES (?, ?, ?)",
            (cid, "hnsw:space", "cosine"),
        )
    # A collection_metadata row whose collection vanished — 46 of these were measured.
    conn.execute(
        "INSERT INTO collection_metadata (collection_id, key, str_value) VALUES (?, ?, ?)",
        (GONE_COLL, "hnsw:space", "cosine"),
    )

    segments = [(DEAD_VEC, "VECTOR", DEAD_COLL), (DEAD_META, "METADATA", DEAD_COLL)]
    if include_keep:
        segments += [(KEEP_VEC, "VECTOR", KEEP_COLL), (KEEP_META, "METADATA", KEEP_COLL)]
    for sid, scope, coll in segments:
        kind = "vector/hnsw-local-persisted" if scope == "VECTOR" else "metadata/sqlite"
        conn.execute(
            "INSERT INTO segments (id, type, scope, collection) VALUES (?, ?, ?, ?)",
            (sid, f"urn:chroma:segment/{kind}", scope, coll),
        )

    # segment_metadata and max_seq_id for live and dead segments alike.
    for sid in (KEEP_VEC, KEEP_META, DEAD_VEC, DEAD_META, ORPHAN_A, ORPHAN_B):
        conn.execute(
            "INSERT INTO segment_metadata (segment_id, key, str_value) VALUES (?, ?, ?)",
            (sid, "hnsw:space", "cosine"),
        )
        conn.execute(
            "INSERT INTO max_seq_id (segment_id, seq_id) VALUES (?, ?)", (sid, b"\x00" * 8)
        )

    next_id = 1
    keep_ids = []
    if include_keep:
        start = next_id
        next_id = _add_embeddings(conn, KEEP_META, 10, next_id)
        keep_ids = list(range(start, next_id))
    next_id = _add_embeddings(conn, DEAD_META, 10, next_id)
    # Big enough that VACUUM has something to reclaim and the shrink is measurable.
    next_id = _add_embeddings(conn, ORPHAN_A, 400, next_id)
    next_id = _add_embeddings(conn, ORPHAN_B, 400, next_id)

    for seq, cid in enumerate((KEEP_COLL, DEAD_COLL), start=1):
        conn.execute(
            "INSERT INTO embeddings_queue (seq_id, operation, topic, id) VALUES (?, 0, ?, ?)",
            (seq, f"persistent://default/default/{cid}", "AP-1"),
        )

    conn.commit()
    conn.close()

    dirs = [DEAD_VEC, ORPHAN_A, ORPHAN_B]
    if include_keep:
        dirs.append(KEEP_VEC)
    for name in dirs:
        d = store / name
        d.mkdir()
        for f in ("data_level0.bin", "header.bin", "length.bin", "link_lists.bin"):
            (d / f).write_bytes(b"x" * 2048)

    return store, keep_ids


def rows(store, sql, params=()):
    conn = sqlite3.connect(store / "chroma.sqlite3")
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def count(store, table, where="1=1"):
    return rows(store, f"SELECT COUNT(*) FROM {table} WHERE {where}")[0][0]


def planned(store):
    return cleanup.plan_cleanup(cleanup.read_inventory(store), cleanup.KNOWN_COLLECTIONS)


@pytest.fixture
def store(tmp_path):
    built, _keep_ids = build_store(tmp_path)
    return built


# =============================================================================
# What survives
# =============================================================================


def test_the_live_collection_survives_intact(tmp_path):
    """Checked by id, not by count: the right ten rows, not merely ten rows."""
    store, keep_ids = build_store(tmp_path)
    cleanup.apply_cleanup(store, planned(store))

    assert [r[0] for r in rows(store, "SELECT id FROM collections")] == [KEEP_COLL]
    assert sorted(r[0] for r in rows(store, "SELECT id FROM segments")) == sorted(
        [KEEP_VEC, KEEP_META]
    )
    assert sorted(r[0] for r in rows(store, "SELECT id FROM embeddings")) == keep_ids
    assert (store / KEEP_VEC).is_dir()
    assert sorted(p.name for p in (store / KEEP_VEC).iterdir()) == [
        "data_level0.bin",
        "header.bin",
        "length.bin",
        "link_lists.bin",
    ]
    assert count(store, "embedding_metadata") == len(keep_ids) * len(METADATA_KEYS)


def test_a_directory_that_is_not_a_uuid_is_untouched(tmp_path):
    """Whatever the user parked in the store stays there."""
    store, _ = build_store(tmp_path)
    (store / "notes.txt").write_text("mine")
    scratch = store / "scratch"
    scratch.mkdir()
    (scratch / "keep.me").write_text("mine")

    cleanup.apply_cleanup(store, planned(store))

    assert (store / "notes.txt").read_text() == "mine"
    assert (scratch / "keep.me").read_text() == "mine"


# =============================================================================
# What goes
# =============================================================================


def test_the_abandoned_collection_and_its_segment_directory_go(store):
    cleanup.apply_cleanup(store, planned(store))

    assert count(store, "collections", "id = ?".replace("?", f"'{DEAD_COLL}'")) == 0
    assert count(store, "segments", f"collection = '{DEAD_COLL}'") == 0
    assert not (store / DEAD_VEC).exists()


def test_orphan_directories_go(store):
    cleanup.apply_cleanup(store, planned(store))

    assert not (store / ORPHAN_A).exists()
    assert not (store / ORPHAN_B).exists()


def test_every_side_table_is_swept(store):
    """The three tables the discovery pass missed, plus the queue.

    Each had 46 orphan rows on disk and none of them is reached by a cascade —
    see the note on foreign keys in the tool.
    """
    cleanup.apply_cleanup(store, planned(store))

    live_segments = {KEEP_VEC, KEEP_META}
    assert {r[0] for r in rows(store, "SELECT segment_id FROM segment_metadata")} == live_segments
    assert {r[0] for r in rows(store, "SELECT segment_id FROM max_seq_id")} == live_segments
    assert {r[0] for r in rows(store, "SELECT collection_id FROM collection_metadata")} == {
        KEEP_COLL
    }
    assert count(store, "embeddings_queue", f"topic LIKE '%{DEAD_COLL}'") == 0
    assert count(store, "embeddings_queue", f"topic LIKE '%{KEEP_COLL}'") == 1


def test_no_orphan_rows_remain(store):
    """The post-condition the whole tool exists for, asserted directly."""
    cleanup.apply_cleanup(store, planned(store))

    assert count(store, "embeddings", "segment_id NOT IN (SELECT id FROM segments)") == 0
    assert count(store, "embedding_metadata", "id NOT IN (SELECT id FROM embeddings)") == 0
    assert count(store, "segment_metadata", "segment_id NOT IN (SELECT id FROM segments)") == 0
    assert count(store, "max_seq_id", "segment_id NOT IN (SELECT id FROM segments)") == 0
    assert (
        count(store, "collection_metadata", "collection_id NOT IN (SELECT id FROM collections)")
        == 0
    )


def test_the_fulltext_index_stays_consistent(store):
    """fts5 rows are deleted through the virtual table, never its shadow tables.

    Writing to embedding_fulltext_search_content directly leaves the index
    describing rows that are gone, and the corruption only shows up later, on a
    query. This asserts both directions of the correspondence.
    """
    cleanup.apply_cleanup(store, planned(store))

    fts = {r[0] for r in rows(store, "SELECT rowid FROM embedding_fulltext_search")}
    surviving = {r[0] for r in rows(store, "SELECT id FROM embeddings")}
    assert fts == surviving

    # And the index still answers, which a corrupted one would not.
    hits = rows(
        store,
        "SELECT COUNT(*) FROM embedding_fulltext_search WHERE embedding_fulltext_search "
        "MATCH 'padding'",
    )
    assert hits[0][0] == len(surviving)


# =============================================================================
# The refusal
# =============================================================================


def test_a_refusing_plan_deletes_nothing(tmp_path):
    """Today's measured state: only `defect_history`, nothing recognised.

    Not "deletes little" — deletes nothing. Row counts, directory list and the
    sqlite file's own mtime all have to come through unchanged.
    """
    store, _ = build_store(tmp_path, include_keep=False)
    db = store / "chroma.sqlite3"

    before_dirs = sorted(p.name for p in store.iterdir())
    before_rows = {t: count(store, t) for t in ("collections", "segments", "embeddings")}
    before_mtime = db.stat().st_mtime_ns
    before_size = db.stat().st_size

    plan = planned(store)
    assert plan.refusal is not None

    with pytest.raises(cleanup.CleanupError):
        cleanup.apply_cleanup(store, plan)

    assert sorted(p.name for p in store.iterdir()) == before_dirs
    assert {t: count(store, t) for t in before_rows} == before_rows
    assert db.stat().st_mtime_ns == before_mtime
    assert db.stat().st_size == before_size


def test_main_refuses_without_deleting(tmp_path, monkeypatch, capsys):
    """The same guard reached the way a user reaches it."""
    store, _ = build_store(tmp_path, include_keep=False)
    before = sorted(p.name for p in store.iterdir())

    monkeypatch.setattr(sys, "argv", ["chroma_cleanup.py", str(store), "--apply"])
    code = cleanup.main()

    assert code == 1
    assert sorted(p.name for p in store.iterdir()) == before
    out = capsys.readouterr().out
    assert "REFUSING" in out
    assert "refresh" in out


# =============================================================================
# Confirmation
# =============================================================================


def test_confirmation_requires_the_directory_count(store):
    """Typing the number proves the report was read; "y" proves only that Enter works."""
    plan = planned(store)
    assert cleanup.confirm(plan, lambda: str(len(plan.drop_dirs))) is True


@pytest.mark.parametrize("answer", ["y", "yes", "", "0", "99"])
def test_a_wrong_confirmation_stops_the_run(store, answer):
    plan = planned(store)
    assert cleanup.confirm(plan, lambda: answer) is False


def test_main_deletes_nothing_when_confirmation_fails(tmp_path, monkeypatch):
    store, _ = build_store(tmp_path)
    before = sorted(p.name for p in store.iterdir())

    monkeypatch.setattr(sys, "argv", ["chroma_cleanup.py", str(store), "--apply"])
    monkeypatch.setattr(cleanup, "stdin_is_interactive", lambda: True)
    monkeypatch.setattr(cleanup, "read_confirmation", lambda: "nope")

    assert cleanup.main() == 1
    assert sorted(p.name for p in store.iterdir()) == before


# =============================================================================
# VACUUM and the backup
# =============================================================================


def test_vacuum_shrinks_the_file(store):
    """Measured, not assumed: freelist pages do not shrink a file on their own.

    The store is built with auto_vacuum off, as chroma's is (measured: 0), so
    without an explicit VACUUM the deletes free pages inside a file that stays
    exactly as large as it was.
    """
    outcome = cleanup.apply_cleanup(store, planned(store))

    assert outcome.size_after < outcome.size_before
    assert outcome.pages_after < outcome.pages_before
    assert (store / "chroma.sqlite3").stat().st_size == outcome.size_after


def test_the_backup_is_removed_on_success(store):
    cleanup.apply_cleanup(store, planned(store))

    assert not (store / "chroma.sqlite3.bak").exists()
    assert list(store.glob("*.bak")) == []


def test_a_failure_leaves_the_backup_and_says_so(store, monkeypatch, capsys):
    """If the run dies partway, the copy stays and the message names it.

    It also has to say that restoring the copy is not on its own a repair: once
    directories have gone, SQLite and the disk disagree, and the way out is to
    delete the store and refresh.
    """

    def boom(*_args, **_kwargs):
        raise OSError("disk went away")

    monkeypatch.setattr(cleanup.shutil, "rmtree", boom)

    with pytest.raises(cleanup.CleanupError):
        cleanup.apply_cleanup(store, planned(store))

    backup = store / "chroma.sqlite3.bak"
    assert backup.is_file()

    out = capsys.readouterr().out
    assert "chroma.sqlite3.bak" in out
    assert "refresh" in out.lower()


# =============================================================================
# Report and apply agree
# =============================================================================


def test_the_report_and_the_apply_agree_on_what_goes(store):
    """A report that promises different numbers than the apply delivers is worse

    than no report: it is the thing the user based their confirmation on.
    """
    plan = planned(store)
    conn = cleanup.read_only_connection(store / "chroma.sqlite3")
    try:
        promised = cleanup.count_doomed_rows(conn, plan)
    finally:
        conn.close()

    outcome = cleanup.apply_cleanup(store, plan)

    assert list(outcome.deleted_rows) == list(promised)
    assert outcome.deleted_dirs == len(plan.drop_dirs)


def test_a_second_run_finds_nothing_left(store):
    """Idempotent: the sweep is complete, not merely large."""
    cleanup.apply_cleanup(store, planned(store))

    second = planned(store)
    assert second.refusal is None
    assert second.drop_dirs == ()
    assert second.drop_segment_ids == ()
    assert second.drop_embedding_segment_ids == ()

    outcome = cleanup.apply_cleanup(store, second)
    assert all(n == 0 for _table, n in outcome.deleted_rows)


def test_the_consistency_check_passes_after_a_clean_run(store):
    """The tool's own post-condition check, exercised on the happy path."""
    outcome = cleanup.apply_cleanup(store, planned(store))
    assert outcome.problems == ()
