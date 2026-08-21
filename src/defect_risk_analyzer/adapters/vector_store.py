"""
ChromaDB vector store — persistence and similarity search for bug history.

Wraps the ChromaDB client so the rest of the application never imports
chromadb directly. `chromadb` itself is imported lazily inside methods: it
pulls in a large dependency tree, and importing it at module scope adds
seconds to the startup of the dashboard and the CI analyzer, which often do
not touch the vector store at all.
"""

import logging
from dataclasses import dataclass
from typing import Any

from defect_risk_analyzer import config

logger = logging.getLogger(__name__)

# One collection per data source. A single `defect_history` used to hold
# whichever source ran last, and the only thing keeping mock keys (AP-101…) out
# of a live index (AP-37…) was that every load destroyed everything first. Once
# loads stopped being destructive the two had to be separated properly.
#
# The old `defect_history` is abandoned rather than migrated: its contents are a
# mixture of both sources, which is the contamination being fixed, so carrying
# it over would carry the problem into a clean collection. It is fully
# rebuildable from bugs.json or sample_bugs.json by one refresh. Deleting it
# off disk belongs to the cleanup that follows this change.
COLLECTION_MOCK = "defect_history_mock"
COLLECTION_LIVE = "defect_history_live"
COLLECTION_METADATA = {"hnsw:space": "cosine"}

# ---------------------------------------------------------------------------
# ChromaDB contracts this module relies on
# ---------------------------------------------------------------------------
# Read out of chromadb==0.5.23's own source, not probed at runtime: no test in
# this suite may run a real client. If the pin in requirements.txt moves, these
# four are the things to re-read before trusting them.
#
# 1. collection.get(include=[...]) always returns ids — they cannot be excluded
#    — and returns everything when limit is None.
#       api/models/Collection.py:108-119
# 2. collection.delete(ids=[]) raises ValueError. It does NOT empty the
#    collection, which is the reassuring half; the dangerous half is that the
#    ordinary "nothing to delete" case would crash, so the call is guarded.
#       api/types.py:503-504, api/segment.py:662-677
# 3. collection.upsert() raises ValueError on duplicate ids, and on empty lists.
#    The comment this file used to carry assumed upsert silently merged
#    duplicates; it does not, so plan_sync deduplicates before the call.
#       api/types.py:505-527, api/types.py:241-246
# 4. upsert() re-embeds every document it is handed, unconditionally, whenever
#    embeddings is None. That is the entire reason diff-sync is worth doing.
#       api/models/CollectionCommon.py:402-406
#
# One contract is NOT settled by reading the source: whether deleting an id that
# does not exist is a silent no-op at the segment layer. SegmentAPI._delete
# hands ids straight to the producer with no existence check (api/segment.py:
# 695-696), so nothing raises client-side, but the segments' own behaviour is
# not visible from there. It is made unreachable rather than assumed: the ids
# passed to delete always come from the get() performed moments earlier, and
# tests/test_vector_sync.py fails if a plan ever violates that.


@dataclass(frozen=True)
class SyncPlan:
    """What one load changes in the collection.

    The three upsert lists are parallel and ready to hand to ChromaDB as they
    are. `unchanged` and `desired_count` are carried so the adapter can guard
    and report without recomputing anything.
    """

    delete_ids: list[str]
    upsert_ids: list[str]
    upsert_documents: list[str]
    upsert_metadatas: list[dict[str, Any]]
    unchanged: int
    desired_count: int


def build_document(bug: dict[str, Any]) -> str:
    """The searchable text indexed for one bug.

    `description` is in here but not in build_metadata, so it is searchable and
    unreadable: a consumer of query results never gets it back.
    """
    return (
        f"{bug.get('summary', '')} "
        f"{bug.get('description', '')} "
        f"{bug.get('component', '')} "
        f"{bug.get('priority', '')} "
        f"{bug.get('status', '')}"
    ).strip()


def build_metadata(bug: dict[str, Any]) -> dict[str, Any]:
    """The metadata stored alongside one bug's embedding.

    The defaults deliberately differ from build_document's empty strings.
    Aligning them would be tidier, and would also restage every bug in every
    existing index on the first sync after deploy, for no gain.
    """
    return {
        "key": bug.get("key", ""),
        "summary": bug.get("summary", ""),
        "priority": bug.get("priority", "Medium"),
        "status": bug.get("status", "Open"),
        "component": bug.get("component", "Unknown"),
        "created": bug.get("created", ""),
    }


def _comparable(metadata: dict[str, Any]) -> dict[str, Any]:
    """Metadata reduced to what a lossy round-trip cannot change.

    chromadb accepts '' as a metadata value on the way in (api/types.py:547-560
    checks only the type), but whether it hands '' back rather than dropping the
    key is not settled by reading the source, and this suite will not run a real
    client to find out. Applied to both sides of the comparison, so an absent
    key and an empty string compare equal whichever way it turns out.

    Without it, every bug with an empty field — `created` is empty whenever Jira
    omits it — would be re-embedded on every sync, forever. That loses the whole
    feature silently rather than failing, which is why it is pinned by a test.
    """
    return {k: v for k, v in metadata.items() if v != "" and v is not None}


def plan_sync(
    current: dict[str, tuple[str, dict[str, Any]]],
    bugs: list[dict[str, Any]],
) -> SyncPlan:
    """Decide what to delete, what to upsert and what to leave alone.

    Pure: takes plain dicts, returns a plain dict-like plan, touches nothing.
    The comparison is over the document text and the metadata rather than Jira's
    `updated` timestamp, because classify_bugs() rewrites `component` in place
    before the upsert (analysis_service.py:94) — a change to COMPONENT_KEYWORDS
    restages the embedding while `updated` stays exactly the same.

    Args:
        current: id -> (document, metadata), as read back from the collection.
        bugs: the bugs the index should hold once this load is done.

    Returns:
        The plan. Bugs without a key, or with no indexable text at all, are
        dropped from it rather than counted as deletions: they mean "cannot be
        indexed", not "remove whatever was there".
    """
    desired: dict[str, tuple[str, dict[str, Any]]] = {}
    for bug in bugs:
        key = bug.get("key", "")
        if not key:
            continue
        document = build_document(bug)
        if not document:
            continue
        # Later bugs win. Deduplicating is not tidiness: contract 3 above means
        # two bugs sharing a key would otherwise crash the load.
        desired[key] = (document, build_metadata(bug))

    # Sorted so a failing assertion names a stable id rather than reading like a
    # flaky test — set iteration order is not stable across runs.
    delete_ids = sorted(set(current) - set(desired))

    upsert_ids: list[str] = []
    upsert_documents: list[str] = []
    upsert_metadatas: list[dict[str, Any]] = []
    unchanged = 0

    for key, (document, metadata) in desired.items():
        stored = current.get(key)
        if (
            stored is not None
            and stored[0] == document
            and _comparable(stored[1]) == _comparable(metadata)
        ):
            unchanged += 1
            continue
        upsert_ids.append(key)
        upsert_documents.append(document)
        upsert_metadatas.append(metadata)

    return SyncPlan(
        delete_ids=delete_ids,
        upsert_ids=upsert_ids,
        upsert_documents=upsert_documents,
        upsert_metadatas=upsert_metadatas,
        unchanged=unchanged,
        desired_count=len(desired),
    )


def _read_current(stored: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    """Turn a collection.get() result into the map plan_sync compares against.

    Defensive about lengths and None entries: ids are guaranteed present
    (contract 1), the parallel lists are not guaranteed to be equally long by
    anything this code controls, and a shorter list here must not raise.
    """
    ids = stored.get("ids") or []
    documents = stored.get("documents") or []
    metadatas = stored.get("metadatas") or []

    current: dict[str, tuple[str, dict[str, Any]]] = {}
    for position, key in enumerate(ids):
        document = documents[position] if position < len(documents) else ""
        metadata = metadatas[position] if position < len(metadatas) else None
        current[key] = (document or "", metadata or {})
    return current


class VectorStore:
    """Persistent ChromaDB collection holding one document per bug."""

    def __init__(self, db_path=None) -> None:
        self._db_path = db_path or config.CHROMA_DB_DIR
        self._client = None
        self._collection = None

        # Which collection the cached handle belongs to, so that a change of
        # data source invalidates it instead of writing to the wrong one.
        self._open_collection_name: str | None = None

        # The plan the last upsert_bugs() acted on, or None if it has not run.
        # Exposed so that "the second sync of the same data writes nothing" is
        # observable from outside — that claim is the feature's reason to exist,
        # and a log line is not something a test can hold on to.
        self.last_sync: SyncPlan | None = None

    # ------------------------------------------------------------------
    # Client / collection lifecycle
    # ------------------------------------------------------------------

    def _get_client(self):
        """Lazy-initialize the persistent ChromaDB client."""
        if self._client is None:
            import chromadb
            self._client = chromadb.PersistentClient(path=str(self._db_path))
        return self._client

    @staticmethod
    def _collection_name() -> str:
        """The collection for the data source currently configured.

        Read at call time, never cached in __init__. The dashboard writes
        USE_MOCK_DATA and calls config.reload() while the AnalysisService
        holding this store stays alive behind @st.cache_resource
        (ui/service.py, get_service), so a name frozen at construction would
        send mock data into the live collection on the first toggle.
        """
        return COLLECTION_MOCK if config.USE_MOCK_DATA else COLLECTION_LIVE

    def _get_collection(self):
        """Lazy-initialize ChromaDB collection."""
        name = self._collection_name()
        if self._collection is not None and self._open_collection_name == name:
            return self._collection

        try:
            client = self._get_client()
            self._collection = client.get_or_create_collection(
                name=name,
                metadata=COLLECTION_METADATA,
            )
            self._open_collection_name = name
            logger.info(
                "ChromaDB collection %s ready. Documents: %d",
                name,
                self._collection.count(),
            )
        except Exception as e:
            logger.error("Failed to initialize ChromaDB: %s", e)
            raise

        return self._collection

    @staticmethod
    def _is_stale_handle(error: Exception) -> bool:
        """True when the cached collection was deleted out from under us."""
        return "does not exist" in str(error).lower()

    def _run(self, operation):
        """Run an operation on the collection, reopening a stale handle once.

        The dashboard and the optional webhook server are separate processes
        pointing at the same directory, and a full load deletes and recreates
        the collection. Whoever was not doing the loading is left holding a
        handle to a collection that no longer exists; every later call then
        fails forever. Reopening once turns that into a transparent recovery.

        Diff-sync made that far rarer — an ordinary load no longer deletes
        anything wholesale — but reset() still does, so the recovery branch is
        still load bearing. It is load bearing for exactly as long as reset()
        exists: if reset() is ever removed, remove the recovery branch in the
        same commit rather than leaving a handler for a case nothing can cause.
        The rest of _run is not optional either way, since count(), collection
        and query_similar all reach the collection through it.
        """
        try:
            return operation(self._get_collection())
        except Exception as e:
            if not self._is_stale_handle(e):
                raise
            logger.warning("ChromaDB collection handle is stale (%s). Reopening.", e)
            self._client = None
            self._collection = None
            self._open_collection_name = None
            return operation(self._get_collection())

    @property
    def collection(self):
        """The raw ChromaDB collection.

        pattern_detector and blind_spot_detector operate on the ChromaDB
        collection object directly, so it is exposed rather than hidden. The
        cheap count() forces a stale handle to surface here, where it can be
        recovered, rather than inside the caller.
        """
        return self._run(lambda c: (c.count(), c)[1])

    def reset(self) -> None:
        """Delete and recreate the current collection. Destructive, and unused.

        Nothing calls this. It used to open every upsert_bugs(); diff-sync
        replaced that, and it is kept deliberately rather than left behind:

        * Diff-sync cannot empty the index. An empty bug list is read as "no
          data available" (see upsert_bugs), so "delete everything" is no longer
          expressible through that path, and this is the only operation that
          says it.
        * It is the only recovery route when a collection is corrupt.
          docs/KNOWN-DEBT.md:184-215 records that as an observed failure, not a
          hypothetical one: a second process loading data left the live
          dashboard's Pattern page broken for the rest of its session.

        Its behaviour is pinned in tests/test_vector_store_adapter.py, because a
        callerless method with no test rots without anyone noticing.
        """
        # Outside the try: a client that cannot be built is not something the
        # fallback below can help with. Retrying it inside the handler — which
        # this method used to do — turned a broken client into a chained,
        # half-logged exception raised from inside an error path.
        client = self._get_client()
        name = self._collection_name()

        try:
            client.delete_collection(name)
            self._collection = client.create_collection(
                name=name,
                metadata=COLLECTION_METADATA,
            )
            logger.info("ChromaDB collection %s reset. Clean slate.", name)
        except Exception as e:
            # The ordinary case here is a collection that was never created.
            logger.warning("Could not reset %s, falling back to get_or_create: %s", name, e)
            self._collection = client.get_or_create_collection(
                name=name,
                metadata=COLLECTION_METADATA,
            )

        self._open_collection_name = name

    def count(self) -> int:
        """Number of documents currently indexed."""
        return self._run(lambda c: c.count())

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def upsert_bugs(self, bugs: list[dict[str, Any]]) -> int:
        """
        Sync the collection to the given bugs: write what changed, drop what went.

        Replaces the delete-and-recreate this method used to open with. Bugs
        that are already indexed unchanged are left alone rather than re-embedded
        (contract 4), and bugs the incoming list no longer mentions are deleted —
        the step that keeps a bug closed in Jira from living in the index forever.

        An empty bug list leaves the index untouched and returns 0. That is a
        deliberate asymmetry, and it means this method cannot express "the bug
        set is genuinely empty now": nothing upstream can tell that apart from a
        failed fetch, since load_bugs_from_file() returns [] for a missing file,
        an unreadable file and a file containing [] alike (jira_client.py:
        329-334). The conservative reading is the only safe one, so emptying the
        index on purpose is reset()'s job instead.

        Args:
            bugs: Bug dictionaries the index should hold after this call.

        Returns:
            Number of bugs the index holds from this load — unchanged ones
            included, so a steady-state sync still reports the full count.
            See `last_sync` for what actually moved.
        """
        if not bugs:
            logger.warning(
                "No bugs supplied; leaving the index untouched. An empty list "
                "reads as 'no data available', never as 'delete everything'."
            )
            return 0

        try:
            stored = self._run(lambda c: c.get(include=["documents", "metadatas"]))
        except Exception as e:
            # Degrade to "current state unknown": upsert everything, delete
            # nothing. Slower than a real diff and strictly non-destructive,
            # which is the right way round to fail.
            logger.warning("Could not read the current index (%s). Upserting all bugs.", e)
            stored = {}

        plan = plan_sync(_read_current(stored), bugs)
        self.last_sync = plan

        if plan.desired_count == 0:
            # The list was not empty but nothing in it could be indexed. Same
            # hazard as an empty list, one step further down, and the guard
            # above cannot see it.
            logger.warning("No valid bugs to load into ChromaDB; index left untouched.")
            return 0

        # Upserted before deleted so that a crash between the two leaves stale
        # extras rather than a hole. The id sets are disjoint by construction, so
        # the order is otherwise free.
        if plan.upsert_ids:
            self._run(
                lambda c: c.upsert(
                    ids=plan.upsert_ids,
                    documents=plan.upsert_documents,
                    metadatas=plan.upsert_metadatas,
                )
            )

        # Guarded, not optional: delete(ids=[]) raises rather than no-ops
        # (contract 2), and "nothing to delete" is the common case.
        if plan.delete_ids:
            self._run(lambda c: c.delete(ids=plan.delete_ids))

        logger.info(
            "ChromaDB synced: %d written, %d deleted, %d unchanged.",
            len(plan.upsert_ids),
            len(plan.delete_ids),
            plan.unchanged,
        )
        return plan.desired_count

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def query_similar(self, query: str, n_results: int = 5) -> list[dict[str, Any]]:
        """
        Find similar bugs using cosine similarity search.

        Returns an empty list — never raises — when the collection is empty or
        the query fails; callers treat "no similar bugs" as a normal outcome.

        Args:
            query: Search query text.
            n_results: Maximum number of similar bugs to return.

        Returns:
            List of similar bug metadata dictionaries.
        """
        try:
            count = self.count()
        except Exception as e:
            logger.error("ChromaDB is unavailable: %s", e)
            return []

        if count == 0:
            logger.info("ChromaDB is empty — no similar bugs to find.")
            return []

        # Limit n_results to collection size
        actual_n = min(n_results, count)

        try:
            results = self._run(
                lambda c: c.query(query_texts=[query], n_results=actual_n)
            )
        except Exception as e:
            logger.error("ChromaDB query failed: %s", e)
            return []

        similar_bugs = []
        if results and results.get("metadatas"):
            for metadata in results["metadatas"][0]:
                similar_bugs.append(metadata)

        return similar_bugs
