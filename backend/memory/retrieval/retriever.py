import logging
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone

from memory.storage.vector_store import VectorStore

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
        # path of every conversation turn).
        fetch_multiplier = 2
        souvenirs_raw = await sync_to_async(self.vector_store.search_souvenirs)(
            query,
            n=n_souvenirs * fetch_multiplier,
            min_importance=config_service.get("memory.min_importance"),
        )
        connaissances_raw = await sync_to_async(self.vector_store.search_connaissances)(
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

        # Build emotional history block for this person
        emotional_block = await self._get_emotional_history_block(person_id)

        return self._format_context(connaissances, souvenirs, emotional_block)

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
        emotional_block: str = "",
    ) -> str:
        """Format memories as a readable text block for the system prompt.

        Truncates individual entries and caps total size to MAX_CONTEXT_CHARS.
        """
        lines = ["--- TES SOUVENIRS ---"]
        current_len = len(lines[0])

        # Emotional history (inserted first, before connaissances)
        if emotional_block:
            if current_len + len(emotional_block) < self.MAX_CONTEXT_CHARS:
                lines.append(emotional_block)
                current_len += len(emotional_block)

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

    async def _get_emotional_history_block(self, person_id: str) -> str:
        """Build a short French text block describing the emotional history with a person.

        Returns empty string if no data or person is unknown.

        Lit **les résumés du jour uniquement**, via la couche de lecture. Le
        consolidateur écrit aussi une ligne ``weekly`` par personne, qui est
        déjà la moyenne pondérée de ses lignes ``daily`` : la ramasser ici
        comptait la semaine deux fois dans le climat général, évinçait les
        journées les plus anciennes de la fenêtre de sept lignes, et pouvait
        présenter l'agrégat hebdomadaire comme le « récemment » (le lundi, les
        deux types partagent le même ``period_start``).
        """
        from memory import read

        if not person_id or person_id in ("anonymous", "__global__"):
            return ""

        try:
            summaries = await read.recent_daily_summaries(person_id, days=7)
        except Exception:
            return ""

        if not summaries:
            return ""

        # Sans le handle : `person_id` est une poignee de transport
        # (`web_6f3e22ccb0ae`), pas un nom. L'imprimer donnait au modele une
        # chaine qu'il pouvait recracher a l'ecran, et le nom resolu se dit
        # deja plus haut dans le prompt (--- QUI TU AS EN FACE ---), la ou la
        # couche identite decide s'il peut etre divulgue.
        lines = ["\n[Ton historique emotionnel avec cette personne]"]

        # Most recent summary
        latest = summaries[0]
        trend_labels = {
            "warming": "en amelioration",
            "cooling": "en refroidissement",
            "volatile": "instable",
            "stable": "stable",
        }
        trend_str = trend_labels.get(latest.trend, latest.trend)
        lines.append(
            f"  - Recemment: emotion dominante = {latest.dominant_emotion} "
            f"(intensite {latest.dominant_intensity:.1f}), tendance {trend_str}"
        )

        # Overall pattern from available summaries
        if len(summaries) >= 3:
            all_emotions: dict[str, float] = {}
            for s in summaries:
                for emotion, weight in s.emotion_distribution.items():
                    all_emotions[emotion] = all_emotions.get(emotion, 0) + weight
            total = sum(all_emotions.values()) or 1.0
            top_3 = sorted(all_emotions.items(), key=lambda x: x[1], reverse=True)[:3]
            pattern_str = ", ".join(f"{e} ({w / total:.0%})" for e, w in top_3)
            lines.append(f"  - Climat general: {pattern_str}")

            # Trend direction across summaries
            trends = [s.trend for s in summaries]
            if trends.count("warming") > len(trends) // 2:
                lines.append("  - La relation se rechauffe avec le temps.")
            elif trends.count("cooling") > len(trends) // 2:
                lines.append("  - La relation se refroidit recemment.")

        return "\n".join(lines)

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
