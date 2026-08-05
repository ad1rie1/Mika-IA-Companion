import logging

import chromadb
from asgiref.sync import sync_to_async
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from django.conf import settings

logger = logging.getLogger(__name__)


def vector_call(fn):
    """Enveloppe asynchrone d'un appel ChromaDB, **hors du thread partagé**.

    `sync_to_async` en mode par défaut (`thread_sensitive=True`) exécute tout
    sur l'unique thread exécuteur du processus — celui que se partagent les six
    boucles de fond et chaque requête ORM d'un tour de conversation. Or aucune
    méthode de `VectorStore` n'ouvre de connexion Django : c'est du ChromaDB
    pur, dont chaque `upsert`/`query` déclenche un encode SentenceTransformer
    (~10-30 ms). La contrainte de thread ne s'y applique donc pas, et l'y
    laisser faisait attendre `gather_context()` derrière la passe de
    décroissance, qui ré-indexe jusqu'à `DECAY_BATCH` lignes d'affilée.

    Tout appel au `VectorStore` depuis un contexte async passe par ici.
    """
    return sync_to_async(fn, thread_sensitive=False)


class VectorStore:
    """ChromaDB wrapper for persistent semantic memory.

    Two collections:
    - souvenirs: episodic memories (events that happened)
    - connaissances: durable knowledge facts
    """

    def __init__(self, persist_dir: str | None = None, model_name: str | None = None):
        persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR
        model_name = model_name or settings.EMBEDDING_MODEL

        self._ef = SentenceTransformerEmbeddingFunction(model_name=model_name)
        self._client = chromadb.PersistentClient(path=persist_dir)

        self._souvenirs = self._client.get_or_create_collection(
            name="souvenirs",
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )
        self._connaissances = self._client.get_or_create_collection(
            name="connaissances",
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "VectorStore initialized (%d souvenirs, %d connaissances)",
            self._souvenirs.count(),
            self._connaissances.count(),
        )

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add_souvenir(
        self,
        souvenir_id: int,
        content: str,
        metadata: dict | None = None,
    ):
        """Upsert a souvenir into ChromaDB."""
        meta = metadata or {}
        self._souvenirs.upsert(
            ids=[str(souvenir_id)],
            documents=[content],
            metadatas=[meta],
        )

    def add_souvenirs(self, entries: list[dict]):
        """Upsert plusieurs souvenirs en un seul appel.

        Chaque entrée est ``{"souvenir_id", "content", "metadata"}``. Chroma
        accepte des listes, et SentenceTransformer encode un lot bien plus vite
        que les mêmes textes un par un — ce que la passe de décroissance fait
        par centaines.
        """
        if not entries:
            return
        self._souvenirs.upsert(
            ids=[str(e["souvenir_id"]) for e in entries],
            documents=[e["content"] for e in entries],
            metadatas=[e.get("metadata") or {} for e in entries],
        )

    def add_connaissance(
        self,
        connaissance_id: int,
        content: str,
        metadata: dict | None = None,
    ):
        """Upsert a connaissance into ChromaDB."""
        meta = metadata or {}
        self._connaissances.upsert(
            ids=[str(connaissance_id)],
            documents=[content],
            metadatas=[meta],
        )

    def remove_souvenir(self, souvenir_id: int):
        """Remove a souvenir (e.g. decayed below threshold)."""
        try:
            self._souvenirs.delete(ids=[str(souvenir_id)])
        except Exception:
            logger.debug("Souvenir %d not found in ChromaDB", souvenir_id)

    def remove_connaissance(self, connaissance_id: int):
        try:
            self._connaissances.delete(ids=[str(connaissance_id)])
        except Exception:
            logger.debug("Connaissance %d not found in ChromaDB", connaissance_id)

    # ------------------------------------------------------------------
    # Search operations
    # ------------------------------------------------------------------

    def search_souvenirs(
        self, query: str, n: int = 5, min_importance: float = 0.3
    ) -> list[dict]:
        """Semantic search in souvenirs.

        Returns list of {id, content, metadata, distance}.
        """
        if self._souvenirs.count() == 0:
            return []

        n = min(n, self._souvenirs.count())
        results = self._souvenirs.query(
            query_texts=[query],
            n_results=n,
            where={"importance": {"$gte": min_importance}} if self._souvenirs.count() > 0 else None,
        )
        return self._parse_results(results)

    def search_connaissances(self, query: str, n: int = 10) -> list[dict]:
        """Semantic search in connaissances (valid only)."""
        if self._connaissances.count() == 0:
            return []

        n = min(n, self._connaissances.count())
        results = self._connaissances.query(
            query_texts=[query],
            n_results=n,
            where={"is_valid": True} if self._connaissances.count() > 0 else None,
        )
        return self._parse_results(results)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_results(results: dict) -> list[dict]:
        """Convert ChromaDB query results to a flat list of dicts."""
        out = []
        if not results or not results.get("ids") or not results["ids"][0]:
            return out
        for i, doc_id in enumerate(results["ids"][0]):
            out.append({
                "id": doc_id,
                "content": results["documents"][0][i],
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results.get("distances") else None,
            })
        return out
