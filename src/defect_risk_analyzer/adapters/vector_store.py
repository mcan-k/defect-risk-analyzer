"""
ChromaDB vector store — persistence and similarity search for bug history.

Wraps the ChromaDB client so the rest of the application never imports
chromadb directly. `chromadb` itself is imported lazily inside methods: it
pulls in a large dependency tree, and importing it at module scope adds
seconds to the startup of the dashboard and the CI analyzer, which often do
not touch the vector store at all.
"""

import logging
from typing import Any

from defect_risk_analyzer import config

logger = logging.getLogger(__name__)

COLLECTION_NAME = "defect_history"
COLLECTION_METADATA = {"hnsw:space": "cosine"}


class VectorStore:
    """Persistent ChromaDB collection holding one document per bug."""

    def __init__(self, db_path=None) -> None:
        self._db_path = db_path or config.CHROMA_DB_DIR
        self._client = None
        self._collection = None

    # ------------------------------------------------------------------
    # Client / collection lifecycle
    # ------------------------------------------------------------------

    def _get_client(self):
        """Lazy-initialize the persistent ChromaDB client."""
        if self._client is None:
            import chromadb
            self._client = chromadb.PersistentClient(path=str(self._db_path))
        return self._client

    def _get_collection(self):
        """Lazy-initialize ChromaDB collection."""
        if self._collection is not None:
            return self._collection

        try:
            client = self._get_client()
            self._collection = client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata=COLLECTION_METADATA,
            )
            logger.info(
                "ChromaDB collection ready. Documents: %d",
                self._collection.count(),
            )
        except Exception as e:
            logger.error("Failed to initialize ChromaDB: %s", e)
            raise

        return self._collection

    @property
    def collection(self):
        """The raw ChromaDB collection.

        pattern_detector and blind_spot_detector operate on the ChromaDB
        collection object directly, so it is exposed rather than hidden.
        """
        return self._get_collection()

    def reset(self) -> None:
        """Delete and recreate the collection to remove stale data.

        Deliberately destructive: mock and live data must never mix in the
        same collection, so every full load starts from a clean slate.
        """
        try:
            client = self._get_client()
            client.delete_collection(COLLECTION_NAME)
            self._collection = client.create_collection(
                name=COLLECTION_NAME,
                metadata=COLLECTION_METADATA,
            )
            logger.info("ChromaDB collection reset. Clean slate.")
        except Exception as e:
            logger.warning("Could not reset collection, falling back to get_or_create: %s", e)
            self._collection = self._get_client().get_or_create_collection(
                name=COLLECTION_NAME,
                metadata=COLLECTION_METADATA,
            )

    def count(self) -> int:
        """Number of documents currently indexed."""
        return self._get_collection().count()

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def upsert_bugs(self, bugs: list[dict[str, Any]]) -> int:
        """
        Replace the collection contents with the given bugs.

        Args:
            bugs: Bug dictionaries to index.

        Returns:
            Number of bugs actually indexed.
        """
        # Reset first to remove stale data (mock + real data mixing)
        self.reset()
        collection = self._collection

        ids = []
        documents = []
        metadatas = []

        for bug in bugs:
            bug_key = bug.get("key", "")
            if not bug_key:
                continue

            # Build searchable document text
            doc_text = (
                f"{bug.get('summary', '')} "
                f"{bug.get('description', '')} "
                f"{bug.get('component', '')} "
                f"{bug.get('priority', '')} "
                f"{bug.get('status', '')}"
            ).strip()

            if not doc_text:
                continue

            ids.append(bug_key)
            documents.append(doc_text)
            metadatas.append({
                "key": bug_key,
                "summary": bug.get("summary", ""),
                "priority": bug.get("priority", "Medium"),
                "status": bug.get("status", "Open"),
                "component": bug.get("component", "Unknown"),
                "created": bug.get("created", ""),
            })

        if not ids:
            logger.warning("No valid bugs to load into ChromaDB.")
            return 0

        # Upsert to ChromaDB (handles both insert and update)
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

        logger.info("Loaded %d bugs into ChromaDB.", len(ids))
        return len(ids)

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
        collection = self._get_collection()

        if collection.count() == 0:
            logger.info("ChromaDB is empty — no similar bugs to find.")
            return []

        # Limit n_results to collection size
        actual_n = min(n_results, collection.count())

        try:
            results = collection.query(
                query_texts=[query],
                n_results=actual_n,
            )
        except Exception as e:
            logger.error("ChromaDB query failed: %s", e)
            return []

        similar_bugs = []
        if results and results.get("metadatas"):
            for metadata in results["metadatas"][0]:
                similar_bugs.append(metadata)

        return similar_bugs
