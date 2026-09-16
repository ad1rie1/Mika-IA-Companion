import logging

import chromadb
from asgiref.sync import sync_to_async
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from django.conf import settings

logger = logging.getLogger(__name__)


# ── Schémas de métadonnées — un helper par collection ───────────────────────
# Chroma n'accepte que des scalaires, et chaque site d'écriture composait son
# dict à la main : le ré-index de la décroissance perdait `emotion`/`themes`
# parce qu'un upsert remplace les métadonnées EN ENTIER. Un helper par
# collection rend l'oubli impossible — tout écrivain passe par ici.

def souvenir_metadata(
    *, importance: float, emotion: str = "", occurred_at: str = "",
    themes: list[str] | None = None,
) -> dict:
    meta: dict = {"importance": float(importance)}
    if emotion:
        meta["emotion"] = emotion
    if occurred_at:
        meta["occurred_at"] = occurred_at
    if themes:
        meta["themes"] = ",".join(themes)
    return meta


def connaissance_metadata(
    *, confidence: float, is_valid: bool, themes: list[str] | None = None,
) -> dict:
    meta: dict = {"confidence": float(confidence), "is_valid": bool(is_valid)}
    if themes:
        meta["themes"] = ",".join(themes)
    return meta


def exchange_metadata(
    *, conversation_id: int, first_message_id: int, last_message_id: int,
    handle: str, ts: float,
) -> dict:
    """Métadonnées d'un chunk d'échange brut (étage épisodique).

    ``ts`` = epoch du premier message — epoch plutôt qu'ISO parce que la
    rétention et la fenêtre du jour filtrent en ``$gte``/``$lt`` numériques.
    ``handle`` = identifiant transport UNIQUE du chunk ("" pour une
    initiative interne de Mika) ; la résolution handle ↔ personne se fait à
    la requête via la couche identité, jamais ici.
    """
    return {
        "conversation_id": int(conversation_id),
        "first_message_id": int(first_message_id),
        "last_message_id": int(last_message_id),
        "handle": handle or "",
        "ts": float(ts),
    }


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

    Three collections:
    - souvenirs: curated episodic memories (what the night decided to keep)
    - connaissances: durable knowledge facts
    - echanges: raw exchange chunks — the same-day findability tier. Nothing
      is *decided* here: everything user-facing is indexed as it happens and
      pruned after ``memory.episodic_retention_days``; SQL keeps the truth
      forever and the nightly consolidation promotes what is durable.
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
        self._echanges = self._client.get_or_create_collection(
            name="echanges",
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "VectorStore initialized (%d souvenirs, %d connaissances, %d echanges)",
            self._souvenirs.count(),
            self._connaissances.count(),
            self._echanges.count(),
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

    def souvenir_ids_present(self, souvenir_ids) -> list[int]:
        """Parmi ces ids, ceux que la collection tient réellement.

        Sert au rattrapage du consolidateur : un ``upsert`` raté laisse une
        ligne ORM sans vecteur, donc irrécupérable pour le rappel.
        """
        ids = [str(i) for i in souvenir_ids if i is not None]
        if not ids:
            return []
        got = self._souvenirs.get(ids=ids, include=[])
        return [int(i) for i in (got.get("ids") or [])]

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
    # Echanges (episodic tier) — write / prune
    # ------------------------------------------------------------------

    def add_exchanges(self, entries: list[dict]):
        """Upsert un lot de chunks d'échanges.

        Chaque entrée : ``{"chunk_id": str, "content": str, "metadata": dict}``
        (métadonnées via :func:`exchange_metadata`). Un seul upsert = un seul
        encode SentenceTransformer par lot. Idempotent par id — le checkpoint
        de l'indexeur peut rejouer un lot sans dommage.
        """
        if not entries:
            return
        self._echanges.upsert(
            ids=[str(e["chunk_id"]) for e in entries],
            documents=[e["content"] for e in entries],
            metadatas=[e.get("metadata") or {} for e in entries],
        )

    def remove_exchanges(self, chunk_ids: list[str]):
        if not chunk_ids:
            return
        try:
            self._echanges.delete(ids=[str(c) for c in chunk_ids])
        except Exception:
            logger.debug("remove_exchanges: ids absents de ChromaDB")

    def prune_exchanges_before(self, cutoff_ts: float, page: int = 500) -> int:
        """Purge les chunks plus anciens que ``cutoff_ts`` (rétention étage 1).

        La rétention ORM (`memory/retention.py`) ne sait pas parler au vector
        store ; l'étage épisodique n'a pas de ligne ORM par chunk, donc il
        porte son propre chemin de purge. Paginé pour ne jamais matérialiser
        toute la collection.
        """
        removed = 0
        while True:
            got = self._echanges.get(
                where={"ts": {"$lt": float(cutoff_ts)}},
                limit=page,
                include=[],
            )
            ids = got.get("ids") or []
            if not ids:
                break
            self._echanges.delete(ids=ids)
            removed += len(ids)
            if len(ids) < page:
                break
        return removed

    def count_exchanges(self) -> int:
        return self._echanges.count()

    def get_exchanges_between(
        self, since_ts: float, until_ts: float, include_embeddings: bool = False,
    ) -> list[dict]:
        """Chunks d'une plage temporelle.

        Renvoie ``[{id, content, metadata, embedding?}]``. Les embeddings
        stockés sont réutilisés tels quels : personne ne ré-encode.
        """
        got = self._echanges.get(
            where={"$and": [
                {"ts": {"$gte": float(since_ts)}},
                {"ts": {"$lt": float(until_ts)}},
            ]},
            include=self._include_exchanges(include_embeddings),
        )
        return self._rows_from_get(got, include_embeddings)

    def get_exchanges_for_messages(
        self, min_message_id: int, max_message_id: int,
        include_embeddings: bool = False,
    ) -> list[dict]:
        """Chunks dont la plage de messages chevauche ``[min, max]`` —
        l'entrée du découpage par thème du consolidateur.

        Un chunk couvre ``[first_message_id, last_message_id]`` et un message
        appartient à au plus un chunk ; chevaucher la fenêtre suffit, le
        consolidateur ne garde de chaque chunk que les messages de SA
        fenêtre. Même forme de retour que ``get_exchanges_between``.
        """
        got = self._echanges.get(
            where={"$and": [
                {"last_message_id": {"$gte": int(min_message_id)}},
                {"first_message_id": {"$lte": int(max_message_id)}},
            ]},
            include=self._include_exchanges(include_embeddings),
        )
        return self._rows_from_get(got, include_embeddings)

    @staticmethod
    def _include_exchanges(include_embeddings: bool) -> list[str]:
        include = ["documents", "metadatas"]
        if include_embeddings:
            include.append("embeddings")
        return include

    @staticmethod
    def _rows_from_get(got: dict, include_embeddings: bool) -> list[dict]:
        """``collection.get`` → ``[{id, content, metadata, embedding?}]``."""
        out = []
        ids = got.get("ids") or []
        embeddings = got.get("embeddings")
        for i, chunk_id in enumerate(ids):
            row = {
                "id": chunk_id,
                "content": got["documents"][i],
                "metadata": got["metadatas"][i] if got.get("metadatas") is not None else {},
            }
            if include_embeddings and embeddings is not None:
                row["embedding"] = embeddings[i]
            out.append(row)
        return out

    # ------------------------------------------------------------------
    # Search operations
    # ------------------------------------------------------------------

    def search_exchanges(
        self,
        query: str,
        n: int = 8,
        *,
        handles: list[str] | None = None,
        since_ts: float | None = None,
        until_ts: float | None = None,
        contains: str | None = None,
    ) -> list[dict]:
        """Recherche sémantique dans les échanges bruts.

        ``handles`` restreint aux chunks de ces identifiants transport (la
        résolution personne → handles appartient à l'appelant, via la couche
        identité). ``contains`` ajoute un filtre plein-texte sur le document
        (l'hybride minimal pour les noms propres, que l'embedding multilingue
        sert mal). Chroma exige un ``$and`` explicite au-delà d'une clause.
        """
        count = self._echanges.count()
        if count == 0:
            return []
        clauses: list[dict] = []
        if handles:
            clauses.append({"handle": {"$in": [h or "" for h in handles]}})
        if since_ts is not None:
            clauses.append({"ts": {"$gte": float(since_ts)}})
        if until_ts is not None:
            clauses.append({"ts": {"$lte": float(until_ts)}})
        where = clauses[0] if len(clauses) == 1 else ({"$and": clauses} if clauses else None)
        results = self._echanges.query(
            query_texts=[query],
            n_results=min(n, count),
            where=where,
            where_document={"$contains": contains} if contains else None,
        )
        return self._parse_results(results)

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
