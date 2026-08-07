import logging
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone

from memory.storage.vector_store import VectorStore, vector_call

logger = logging.getLogger(__name__)


class MemoryRetriever:
    """Retrieves relevant memories for a given query and formats them
    as a context block for the Claude system prompt.

    Supports:
    - person_id boosting: memories involving the current person rank higher
    - recency bias: recent memories are boosted over old ones
    """

    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store

    async def retrieve(self, query: str, person_id: str = "") -> str:
        """Retrieve and format relevant memories for a user message.

        1. Search ChromaDB for relevant souvenirs + connaissances
        2. Enrich with ORM data (themes, entities)
        3. Apply person_id boosting + recency reranking
        4. Format as readable text block for system prompt
        """
        from configs.service import config_service
        n_souvenirs = config_service.get("memory.retrieval_souvenirs")
        n_connaissances = config_service.get("memory.retrieval_connaissances")

        # Fetch more than needed so we can rerank.
        # ChromaDB search runs a CPU-heavy embedding encode — offload it to a
        # thread so it never blocks the ASGI event loop (this runs on the hot
        # path of every conversation turn). `vector_call` la sort en plus du
        # thread ORM partagé, où elle attendait derrière la passe de
        # décroissance du consolidateur.
        fetch_multiplier = 2
        souvenirs_raw = await vector_call(self.vector_store.search_souvenirs)(
            query,
            n=n_souvenirs * fetch_multiplier,
            min_importance=config_service.get("memory.min_importance"),
        )
        connaissances_raw = await vector_call(self.vector_store.search_connaissances)(
            query, n=n_connaissances
        )

        if not souvenirs_raw and not connaissances_raw:
            return ""

        # Enrich with ORM data
        souvenirs = await self._enrich_souvenirs(souvenirs_raw)
        connaissances = await self._enrich_connaissances(connaissances_raw)

        # Rerank souvenirs: person_id boost + recency bias
        souvenirs = self._rerank_souvenirs(souvenirs, person_id)

        # Take top N after reranking
        souvenirs = souvenirs[:n_souvenirs]

        return self._format_context(connaissances, souvenirs)

    def _rerank_souvenirs(
        self, souvenirs: list[dict], person_id: str
    ) -> list[dict]:
        """Rerank souvenirs with recency bias and person_id boosting.

        Score = base_relevance * recency_multiplier * person_multiplier
        Normalized to [0, 1] range.
        """
        now = timezone.now()

        for s in souvenirs:
            score = s.get("relevance", 0.5)

            # Recency bias: multiplicative (keeps score in reasonable range)
            occurred = s.get("occurred_at")
            if occurred:
                age_hours = (now - occurred).total_seconds() / 3600
                if age_hours < 1:
                    score *= 1.5        # Last hour: strong boost
                elif age_hours < 24:
                    score *= 1.3        # Last day
                elif age_hours < 168:   # 7 days
                    score *= 1.1
                # Older: no boost

            # Person-id boost: memories involving this person rank higher
            if person_id:
                entities = s.get("entities", [])
                pid_lower = person_id.lower()
                for entity in entities:
                    # Exact match (case-insensitive) to avoid "john" matching "johnathan"
                    if entity.lower() == pid_lower:
                        score *= 1.4
                        break

            # Normalize to [0, 1]
            s["_score"] = min(1.0, score)

        souvenirs.sort(key=lambda s: s.get("_score", 0), reverse=True)
        return souvenirs

    @staticmethod
    def _pk_of(raw: dict) -> int | None:
        """Identifiant ChromaDB -> pk ORM, ou None si la ligne n'en porte pas."""
        try:
            return int(raw["id"])
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    async def _load_by_pk(queryset, pks: list[int]) -> dict | None:
        """Charge en UNE requete les lignes demandees, avec leurs M2M.

        Retourne ``{pk: (ligne, themes, entities)}``, ou ``None`` si le
        chargement lui-meme a echoue (base verrouillee, table absente) — le
        cas ou l'appelant doit replier *toute* la page sur ChromaDB, a
        distinguer d'une ligne simplement absente du resultat.

        Les M2M se lisent via ``.all()``, la seule forme qui consomme le cache
        de ``prefetch_related`` : ``values_list()`` rechaine le queryset
        (``_result_cache`` remis a None) et refait la requete, ce qui rendait
        le prefetch purement decoratif.
        """
        if not pks:
            return {}

        def _charger() -> dict:
            rows = queryset.filter(pk__in=pks).prefetch_related("themes", "entities")
            return {
                row.pk: (
                    row,
                    [t.name for t in row.themes.all()],
                    [e.name for e in row.entities.all()],
                )
                for row in rows
            }

        try:
            return await sync_to_async(_charger)()
        except Exception:
            return None

    async def _enrich_souvenirs(self, raw_results: list[dict]) -> list[dict]:
        """Load full Souvenir data from ORM.

        Une seule requete pour toute la page ChromaDB, dans un seul saut
        ``sync_to_async``. Ligne par ligne, cela coutait cinq requetes et trois
        sauts de thread par souvenir — serialises sur l'unique executeur
        partage avec les six boucles de fond — soit une centaine de requetes
        par tour de conversation avant meme l'appel LLM.
        """
        from memory.models import Souvenir

        pks = [pk for pk in (self._pk_of(r) for r in raw_results) if pk is not None]
        loaded = await self._load_by_pk(Souvenir.objects.all(), pks)

        # L'ordre ChromaDB est l'ordre de pertinence : on le reconstitue en
        # Python plutot que de le demander a la base.
        enriched = []
        for r in raw_results:
            row = loaded.get(self._pk_of(r)) if loaded is not None else None
            if row is None:
                # Fallback: use ChromaDB data only
                meta = r.get("metadata", {})
                enriched.append({
                    "content": r["content"],
                    "emotion": meta.get("emotion", "neutral"),
                    "importance": meta.get("importance", 0.5),
                    "occurred_at": None,
                    "themes": [],
                    "entities": [],
                    "relevance": 0.5,
                })
                continue

            souvenir, themes, entities = row

            # Compute base relevance from vector distance (lower = more relevant)
            distance = r.get("distance")
            relevance = max(0, 1.0 - (distance or 0.5)) if distance is not None else 0.5

            enriched.append({
                "content": souvenir.content,
                "emotion": souvenir.emotion,
                "importance": souvenir.importance,
                "occurred_at": souvenir.occurred_at,
                "themes": themes,
                "entities": entities,
                "relevance": relevance,
            })
        return enriched

    async def _enrich_connaissances(self, raw_results: list[dict]) -> list[dict]:
        """Load full Connaissance data from ORM.

        Meme regroupement que pour les souvenirs (cf. `_enrich_souvenirs`).
        """
        from memory.models import Connaissance

        pks = [pk for pk in (self._pk_of(r) for r in raw_results) if pk is not None]
        # `is_valid=True` en ceinture-bretelles : ChromaDB filtre sur sa propre
        # metadonnee, donc une ligne invalidee entre l'indexation et cette
        # lecture doit disparaitre du bloc, pas etre servie.
        loaded = await self._load_by_pk(Connaissance.objects.filter(is_valid=True), pks)

        enriched = []
        for r in raw_results:
            pk = self._pk_of(r)
            if loaded is not None and pk is not None:
                row = loaded.get(pk)
                if row is None:
                    # Invalidee ou effacee : le repli ChromaDB la reservirait
                    # telle quelle, ce qui annulerait le filtre ci-dessus.
                    continue
                conn, themes, entities = row
                enriched.append({
                    "content": conn.content,
                    "confidence": conn.confidence,
                    "themes": themes,
                    "entities": entities,
                })
                continue

            # Chargement en echec, ou identifiant inexploitable : repli
            # ChromaDB, comme le faisait chaque ligne quand la requete etait
            # posee ligne par ligne.
            enriched.append({
                "content": r["content"],
                "confidence": r.get("metadata", {}).get("confidence", 0.5),
                "themes": [],
                "entities": [],
            })
        return enriched

    # Max characters for the entire memory context block injected into the prompt.
    # Prevents memory from dominating the system prompt context window.
    MAX_CONTEXT_CHARS = 4000

    def _format_context(
        self,
        connaissances: list[dict],
        souvenirs: list[dict],
    ) -> str:
        """Format memories as a readable text block for the system prompt.

        Truncates individual entries and caps total size to MAX_CONTEXT_CHARS.
        """
        lines = ["--- TES SOUVENIRS ---"]
        current_len = len(lines[0])

        if connaissances:
            lines.append("\n[Ce que tu sais]")
            current_len += len(lines[-1])
            for c in connaissances:
                conf_label = self._confidence_label(c["confidence"])
                entities_str = ""
                if c["entities"]:
                    entities_str = f" (concerne: {', '.join(c['entities'])})"
                # Truncate individual content to avoid one memory dominating
                content = c["content"][:300]
                line = f"  - {content}{entities_str} [{conf_label}]"
                if current_len + len(line) > self.MAX_CONTEXT_CHARS:
                    break
                lines.append(line)
                current_len += len(line)

        if souvenirs:
            lines.append("\n[Tes souvenirs vecus]")
            current_len += len(lines[-1])
            for s in souvenirs:
                time_str = self._time_ago(s["occurred_at"]) if s["occurred_at"] else "?"
                emotion = s.get("emotion", "neutral")
                emotion_str = f" [{emotion}]" if emotion != "neutral" else ""
                content = s["content"][:300]
                line = f"  - ({time_str}){emotion_str} {content}"
                if current_len + len(line) > self.MAX_CONTEXT_CHARS:
                    break
                lines.append(line)
                current_len += len(line)

        lines.append("\n--- FIN SOUVENIRS ---")
        return "\n".join(lines)

    # L'historique emotionnel avec une personne ne se lit plus ici. Il vivait
    # en double : `context._fetch_person_context` pose deja la meme question a
    # `read.recent_daily_summaries`, mais *derriere* la porte de divulgation
    # (`may_disclose_private_context`). Cette copie-ci s'ecrivait dans
    # `memory_context`, un bloc toujours injecte : dans un salon public, la
    # stance affective seule sortait par la porte gardee pendant que le climat
    # relationnel entrait par celle-ci. Le retriever revient a sa question
    # propre : souvenirs + connaissances.

    @staticmethod
    def _confidence_label(confidence: float) -> str:
        if confidence >= 0.8:
            return "certain"
        if confidence >= 0.5:
            return "probable"
        return "incertain"

    @staticmethod
    def _time_ago(dt) -> str:
        if dt is None:
            return "?"
        now = timezone.now()
        delta = now - dt
        if delta < timedelta(hours=1):
            return "il y a quelques minutes"
        if delta < timedelta(days=1):
            hours = int(delta.total_seconds() / 3600)
            return f"il y a {hours}h"
        days = delta.days
        if days == 1:
            return "hier"
        if days < 7:
            return f"il y a {days} jours"
        if days < 30:
            weeks = days // 7
            return f"il y a {weeks} semaine{'s' if weeks > 1 else ''}"
        months = days // 30
        return f"il y a {months} mois"
