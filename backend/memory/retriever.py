import logging
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone

from memory.vector_store import VectorStore

logger = logging.getLogger(__name__)


class MemoryRetriever:
    """Retrieves relevant memories for a given query and formats them
    as a context block for the Claude system prompt."""

    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store

    async def retrieve(self, query: str) -> str:
        """Retrieve and format relevant memories for a user message.

        1. Search ChromaDB for relevant souvenirs + connaissances
        2. Enrich with ORM data (themes, entities)
        3. Format as readable text block for system prompt
        """
        n_souvenirs = settings.MEMORY_RETRIEVAL_SOUVENIRS
        n_connaissances = settings.MEMORY_RETRIEVAL_CONNAISSANCES

        # Vector search
        souvenirs_raw = self.vector_store.search_souvenirs(
            query, n=n_souvenirs, min_importance=settings.MEMORY_MIN_IMPORTANCE
        )
        connaissances_raw = self.vector_store.search_connaissances(
            query, n=n_connaissances
        )

        if not souvenirs_raw and not connaissances_raw:
            return ""

        # Enrich with ORM data
        souvenirs = await self._enrich_souvenirs(souvenirs_raw)
        connaissances = await self._enrich_connaissances(connaissances_raw)

        return self._format_context(connaissances, souvenirs)

    async def _enrich_souvenirs(self, raw_results: list[dict]) -> list[dict]:
        """Load full Souvenir data from ORM."""
        from memory.models import Souvenir

        enriched = []
        for r in raw_results:
            try:
                pk = int(r["id"])
                souvenir = await sync_to_async(
                    lambda pk=pk: Souvenir.objects.prefetch_related("themes", "entities").get(pk=pk)
                )()
                themes = await sync_to_async(lambda s=souvenir: list(s.themes.values_list("name", flat=True)))()
                entities = await sync_to_async(lambda s=souvenir: list(s.entities.values_list("name", flat=True)))()

                enriched.append({
                    "content": souvenir.content,
                    "emotion": souvenir.emotion,
                    "importance": souvenir.importance,
                    "occurred_at": souvenir.occurred_at,
                    "themes": themes,
                    "entities": entities,
                })
            except Exception:
                # Fallback: use ChromaDB data only
                meta = r.get("metadata", {})
                enriched.append({
                    "content": r["content"],
                    "emotion": meta.get("emotion", "neutral"),
                    "importance": meta.get("importance", 0.5),
                    "occurred_at": None,
                    "themes": [],
                    "entities": [],
                })
        return enriched

    async def _enrich_connaissances(self, raw_results: list[dict]) -> list[dict]:
        """Load full Connaissance data from ORM."""
        from memory.models import Connaissance

        enriched = []
        for r in raw_results:
            try:
                pk = int(r["id"])
                conn = await sync_to_async(
                    lambda pk=pk: Connaissance.objects.prefetch_related("themes", "entities").get(pk=pk)
                )()
                themes = await sync_to_async(lambda c=conn: list(c.themes.values_list("name", flat=True)))()
                entities = await sync_to_async(lambda c=conn: list(c.entities.values_list("name", flat=True)))()

                enriched.append({
                    "content": conn.content,
                    "confidence": conn.confidence,
                    "themes": themes,
                    "entities": entities,
                })
            except Exception:
                enriched.append({
                    "content": r["content"],
                    "confidence": r.get("metadata", {}).get("confidence", 0.5),
                    "themes": [],
                    "entities": [],
                })
        return enriched

    def _format_context(
        self, connaissances: list[dict], souvenirs: list[dict]
    ) -> str:
        """Format memories as a readable text block for the system prompt."""
        lines = ["--- TES SOUVENIRS ---"]

        if connaissances:
            lines.append("\n[Ce que tu sais]")
            for c in connaissances:
                conf_label = self._confidence_label(c["confidence"])
                entities_str = ""
                if c["entities"]:
                    entities_str = f" (concerne: {', '.join(c['entities'])})"
                lines.append(f"  - {c['content']}{entities_str} [{conf_label}]")

        if souvenirs:
            lines.append("\n[Tes souvenirs vecus]")
            for s in souvenirs:
                time_str = self._time_ago(s["occurred_at"]) if s["occurred_at"] else "?"
                emotion = s.get("emotion", "neutral")
                emotion_str = f" [{emotion}]" if emotion != "neutral" else ""
                lines.append(f"  - ({time_str}){emotion_str} {s['content']}")

        lines.append("\n--- FIN SOUVENIRS ---")
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
