"""
VectorStore's wiring: which collection it opens, and what a sync actually calls.

test_vector_sync.py pins the decision; this file pins the plumbing around it —
that mock and live data land in separate collections, that reset() still behaves
even though nothing calls it any more, and that a second sync of unchanged data
writes nothing at all.

No ChromaDB. `_get_client()` returns `self._client` whenever it is not None
(vector_store.py:36-39), so assigning a fake there means the real client is never
constructed and chromadb is never even imported — the suite's rule
(conftest.py:9) and the repo-directory guard (conftest.py:87-110) both hold
without either of them having to catch anything.

The fake is stateful rather than a call recorder: upsert writes, get reads back.
Recording alone would let "the second sync writes nothing" pass vacuously, and
that claim is the entire reason diff-sync exists. FakeCollection also copies
chromadb 0.5.23's own validation of empty and duplicate id lists, so a plan that
would crash against the real client crashes here too.

What the fake still cannot prove: that real ChromaDB hands metadata back exactly
as it took it. test_lossy_round_trip_still_syncs_nothing attacks that from the
other side — it makes the fake deliberately lossy in the one way that is
plausible and shows the sync survives it.
"""

from typing import Any

import pytest

from defect_risk_analyzer import config
from defect_risk_analyzer.adapters.vector_store import (
    COLLECTION_LIVE,
    COLLECTION_MOCK,
    VectorStore,
)

# =============================================================================
# Fakes
# =============================================================================


class FakeCollection:
    """In-memory stand-in for a ChromaDB collection.

    `lossy` mimics a store that drops empty metadata values on the way out —
    the plausible round-trip failure that reading chromadb's source did not
    settle either way.
    """

    def __init__(self, name: str, *, lossy: bool = False) -> None:
        self.name = name
        self._lossy = lossy
        self._documents: dict[str, str] = {}
        self._metadatas: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, Any]] = []

    def count(self) -> int:
        return len(self._documents)

    def get(self, include: list[str] | None = None) -> dict[str, Any]:
        self.calls.append(("get", tuple(include or ())))
        ids = list(self._documents)
        return {
            "ids": ids,  # always returned, include cannot exclude them
            "documents": [self._documents[key] for key in ids],
            "metadatas": [self._read_metadata(key) for key in ids],
        }

    def _read_metadata(self, key: str) -> dict[str, Any]:
        metadata = self._metadatas[key]
        if self._lossy:
            return {k: v for k, v in metadata.items() if v != ""}
        return dict(metadata)

    def upsert(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        # chromadb 0.5.23 rejects both of these; see api/types.py:241-246 and
        # :505-527. Copied so a plan that would crash there crashes here.
        if not ids:
            raise ValueError("Non-empty lists are required for ['ids']")
        if len(set(ids)) != len(ids):
            raise ValueError("Expected IDs to be unique")

        self.calls.append(("upsert", list(ids)))
        for key, document, metadata in zip(ids, documents, metadatas, strict=True):
            self._documents[key] = document
            self._metadatas[key] = dict(metadata)

    def delete(self, ids: list[str] | None = None) -> None:
        # api/types.py:503-504 — an empty list raises rather than deleting all.
        if not ids:
            raise ValueError("Expected IDs to be a non-empty list, got 0 IDs")

        self.calls.append(("delete", list(ids)))
        for key in ids:
            self._documents.pop(key, None)
            self._metadatas.pop(key, None)

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]


class FakeClient:
    """In-memory stand-in for chromadb.PersistentClient."""

    def __init__(self, *, lossy: bool = False) -> None:
        self._lossy = lossy
        self.collections: dict[str, FakeCollection] = {}
        self.calls: list[tuple[str, str]] = []

    def get_or_create_collection(self, name: str, metadata: dict | None = None):
        self.calls.append(("get_or_create_collection", name))
        if name not in self.collections:
            self.collections[name] = FakeCollection(name, lossy=self._lossy)
        return self.collections[name]

    def create_collection(self, name: str, metadata: dict | None = None):
        self.calls.append(("create_collection", name))
        if name in self.collections:
            raise ValueError(f"Collection {name} already exists.")
        self.collections[name] = FakeCollection(name, lossy=self._lossy)
        return self.collections[name]

    def delete_collection(self, name: str) -> None:
        self.calls.append(("delete_collection", name))
        if name not in self.collections:
            # Wording matters: VectorStore._is_stale_handle() matches on
            # "does not exist" (vector_store.py:65).
            raise ValueError(f"Collection {name} does not exist.")
        del self.collections[name]

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]


def make_store(tmp_path, *, lossy: bool = False) -> tuple[VectorStore, FakeClient]:
    """A store wired to a fake client, with no ChromaDB anywhere in reach.

    db_path is passed but never used: no code path reaches PersistentClient once
    _client is set.
    """
    store = VectorStore(db_path=tmp_path / "never-created")
    client = FakeClient(lossy=lossy)
    store._client = client
    return store, client


def make_bug(key: str, **overrides: str) -> dict[str, Any]:
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


# =============================================================================
# The fake is actually reached
# =============================================================================


def test_the_fake_client_is_what_the_store_uses(tmp_path):
    """Guards every test below against a false pass.

    If the injection stopped working, the store would build a real
    PersistentClient against tmp_path and most of these assertions would fail in
    confusing ways instead of this one failing clearly.
    """
    store, client = make_store(tmp_path)

    assert store._get_client() is client
    assert not (tmp_path / "never-created").exists()


# =============================================================================
# C1, C2 — separate collections for mock and live data
# =============================================================================


@pytest.mark.parametrize(
    ("mock_mode", "expected"),
    [
        (True, COLLECTION_MOCK),
        (False, COLLECTION_LIVE),
    ],
)
def test_the_collection_follows_the_data_source(tmp_path, monkeypatch, mock_mode, expected):
    """C1 — mock and live bugs never share a collection.

    Before this, one collection named defect_history held whichever source ran
    last, and the only thing keeping them apart was that every load destroyed
    everything first.
    """
    monkeypatch.setattr(config, "USE_MOCK_DATA", mock_mode)
    store, client = make_store(tmp_path)

    store.upsert_bugs([make_bug("AP-1")])

    assert list(client.collections) == [expected]


def test_flipping_mock_mode_reopens_under_the_new_name(tmp_path, monkeypatch):
    """C2 — the name is resolved per call, never frozen at construction.

    This is not hypothetical tidiness. ui.service.save_multiple_env() writes
    USE_MOCK_DATA and calls config.reload(), but the AnalysisService holding this
    store is cached with @st.cache_resource and survives (ui/service.py,
    get_service).
    A name resolved in __init__ would send mock data into the live collection on
    the very first toggle — exactly the contamination this phase is removing.
    """
    monkeypatch.setattr(config, "USE_MOCK_DATA", False)
    store, client = make_store(tmp_path)
    store.upsert_bugs([make_bug("AP-37")])

    monkeypatch.setattr(config, "USE_MOCK_DATA", True)
    store.upsert_bugs([make_bug("AP-101")])

    assert sorted(client.collections) == sorted([COLLECTION_LIVE, COLLECTION_MOCK])

    live_ids = client.collections[COLLECTION_LIVE].get()["ids"]
    mock_ids = client.collections[COLLECTION_MOCK].get()["ids"]
    assert live_ids == ["AP-37"]
    assert mock_ids == ["AP-101"], "mock data must not land in the live collection"


# =============================================================================
# C3, C4, C5 — reset(), which nothing calls
# =============================================================================


def test_reset_empties_the_collection(tmp_path, monkeypatch):
    """C3 — reset() has no callers left, so its behaviour is pinned here.

    Diff-sync deliberately cannot express "empty the index": an empty bug list
    is read as "no data available". reset() is the only operation that says it,
    and the only recovery route when a collection is corrupt
    (docs/KNOWN-DEBT.md:184-215 records that as a real, observed failure). A
    method with no callers and no test rots silently.
    """
    monkeypatch.setattr(config, "USE_MOCK_DATA", False)
    store, client = make_store(tmp_path)
    store.upsert_bugs([make_bug("AP-1"), make_bug("AP-2")])
    assert client.collections[COLLECTION_LIVE].count() == 2

    store.reset()

    assert client.collections[COLLECTION_LIVE].count() == 0
    assert "delete_collection" in client.call_names()
    assert "create_collection" in client.call_names()


def test_reset_falls_back_when_the_collection_is_not_there(tmp_path, monkeypatch):
    """C4 — deleting a collection that was never created is an ordinary state.

    It is also the case the fallback exists for, and the reason narrowing the
    except block below must not narrow it out of existence.
    """
    monkeypatch.setattr(config, "USE_MOCK_DATA", False)
    store, client = make_store(tmp_path)

    store.reset()

    assert client.call_names() == [
        "delete_collection",
        "get_or_create_collection",
    ], "a missing collection should fall through to get_or_create, not raise"
    assert COLLECTION_LIVE in client.collections


def test_reset_does_not_retry_a_failing_client(tmp_path):
    """C5 — a client-level failure raises with its own traceback.

    The except block used to swallow everything and call _get_client() a second
    time inside the handler, so a broken client produced a chained, unlogged
    exception from inside an error path instead of the real one. Counting the
    calls is what tells the two versions apart: the failure surfaces either way,
    but only the old one asks twice.
    """
    store, _ = make_store(tmp_path)
    attempts = []

    def failing_client():
        attempts.append(1)
        raise RuntimeError("the client is broken")

    store._get_client = failing_client

    with pytest.raises(RuntimeError, match="the client is broken"):
        store.reset()

    assert len(attempts) == 1, (
        "a client failure must not be retried inside the except block — the "
        "fallback is for a missing collection, not a missing client"
    )


# =============================================================================
# C6, C7, C8 — what a sync does and does not call
# =============================================================================


def test_an_empty_list_never_touches_the_client(tmp_path):
    """C6 — the bug that made this phase urgent.

    reset() ran before the empty-list check, so refresh_data() returning [] --
    a missing bugs.json, an unconfigured Jira -- deleted the index. Now an empty
    list does not even open a collection.
    """
    store, client = make_store(tmp_path)

    assert store.upsert_bugs([]) == 0
    assert client.calls == [], "an empty load must not reach ChromaDB at all"
    assert store.last_sync is None


def test_a_list_of_unusable_bugs_never_deletes_anything(tmp_path, monkeypatch):
    """The same hazard one step further down, where the input check cannot see it."""
    monkeypatch.setattr(config, "USE_MOCK_DATA", False)
    store, client = make_store(tmp_path)
    store.upsert_bugs([make_bug("AP-1")])

    written = store.upsert_bugs([{"summary": "no key"}, {"key": "AP-9"}])

    assert written == 0
    assert client.collections[COLLECTION_LIVE].get()["ids"] == ["AP-1"]


def test_a_sync_never_deletes_the_collection(tmp_path, monkeypatch):
    """C7 — the wholesale delete is gone, not merely moved.

    A reset() reinstated anywhere inside upsert_bugs would still produce a
    correct-looking index, so nothing else here would notice.
    """
    monkeypatch.setattr(config, "USE_MOCK_DATA", False)
    store, client = make_store(tmp_path)

    store.upsert_bugs([make_bug("AP-1")])
    store.upsert_bugs([make_bug("AP-1"), make_bug("AP-2")])

    assert "delete_collection" not in client.call_names()
    assert "create_collection" not in client.call_names()


def test_delete_is_not_called_when_there_is_nothing_to_delete(tmp_path, monkeypatch):
    """C8 — delete(ids=[]) raises, and "nothing to delete" is the common case."""
    monkeypatch.setattr(config, "USE_MOCK_DATA", False)
    store, client = make_store(tmp_path)

    store.upsert_bugs([make_bug("AP-1")])
    store.upsert_bugs([make_bug("AP-1"), make_bug("AP-2")])

    assert "delete" not in client.collections[COLLECTION_LIVE].call_names()


def test_a_bug_that_left_the_incoming_list_is_deleted(tmp_path, monkeypatch):
    """The bd67c76 regression, through the adapter rather than the plan."""
    monkeypatch.setattr(config, "USE_MOCK_DATA", False)
    store, client = make_store(tmp_path)
    store.upsert_bugs([make_bug("AP-1"), make_bug("AP-2")])

    store.upsert_bugs([make_bug("AP-1")])

    assert client.collections[COLLECTION_LIVE].get()["ids"] == ["AP-1"]
    assert store.last_sync.delete_ids == ["AP-2"]


# =============================================================================
# C9, C10 — the second sync writes nothing
# =============================================================================


def test_syncing_the_same_bugs_twice_writes_nothing_the_second_time(tmp_path, monkeypatch):
    """C9 — the claim the whole phase rests on.

    chromadb re-embeds every document handed to upsert (contract 4 in
    vector_store.py), so "unchanged bugs are not passed to upsert" is the saving.
    Left to a log line it would degrade silently; here it fails.
    """
    monkeypatch.setattr(config, "USE_MOCK_DATA", False)
    store, client = make_store(tmp_path)
    bugs = [make_bug("AP-1"), make_bug("AP-2"), make_bug("AP-3")]

    store.upsert_bugs(bugs)
    collection = client.collections[COLLECTION_LIVE]
    assert collection.call_names().count("upsert") == 1

    store.upsert_bugs(bugs)

    assert collection.call_names().count("upsert") == 1, (
        "the second sync of unchanged data must not call upsert at all"
    )
    assert store.last_sync.unchanged == 3
    assert store.last_sync.upsert_ids == []


@pytest.mark.parametrize("lossy", [False, True], ids=["faithful-store", "lossy-store"])
def test_an_empty_metadata_field_still_syncs_nothing_the_second_time(
    tmp_path, monkeypatch, lossy
):
    """C10 — robustness against the one contract source-reading left open.

    chromadb takes '' as a metadata value but whether it returns '' rather than
    dropping the key is not visible in its source, so both readings are run. The
    lossy store is the pessimistic one; the faithful store is the likelier one,
    and it is the one that catches a comparison normalised on only one side.

    Either way, without the normalisation in plan_sync every bug with an empty
    field would be re-embedded on every sync forever — a total loss of the
    feature that no test and no error message would otherwise mention.
    """
    monkeypatch.setattr(config, "USE_MOCK_DATA", False)
    store, client = make_store(tmp_path, lossy=lossy)
    bugs = [make_bug("AP-1", created=""), make_bug("AP-2", created="")]

    store.upsert_bugs(bugs)
    collection = client.collections[COLLECTION_LIVE]

    store.upsert_bugs(bugs)

    assert collection.call_names().count("upsert") == 1, (
        "a store that drops empty metadata values must not restage every bug"
    )
    assert store.last_sync.unchanged == 2


def test_only_the_changed_bug_is_rewritten(tmp_path, monkeypatch):
    """Guards C9/C10 against passing because the sync stopped writing anything."""
    monkeypatch.setattr(config, "USE_MOCK_DATA", False)
    store, client = make_store(tmp_path)
    store.upsert_bugs([make_bug("AP-1"), make_bug("AP-2")])
    collection = client.collections[COLLECTION_LIVE]

    store.upsert_bugs([make_bug("AP-1"), make_bug("AP-2", summary="Now intermittent")])

    assert collection.calls[-1] == ("upsert", ["AP-2"])
    assert store.last_sync.unchanged == 1
