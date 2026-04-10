"""MemoryBridge — the Conscience's R/W interface to long-term memory.

This is the key component that makes the Conscience more than a passive
observer. It can read, create, boost, reduce, and invalidate memories.
"""

from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.utils import timezone

from conscience.types import InterpretedSignal

logger = logging.getLogger(__name__)


class MemoryBridge:
    """Read/write interface from the Conscience to long-term memory.

    Reads use the existing MemoryRetriever (vector search + ORM enrichment).
    Writes go directly through Django ORM + VectorStore.
    """

    # ── Read ─────────────────────────────────────────────────────

    async def recall_for_context(self, queries: list[str]) -> str:
        """Retrieve relevant memories for a list of query strings.

        Reuses the existing MemoryRetriever from memory/retriever.py.
        Returns formatted context string or empty.
        """
        from memory.manager import memory_manager

        if not queries:
            return ""

        # Use the most pertinent query for retrieval
        combined = " ".join(queries[:3])
        try:
            return await memory_manager.get_memory_context(combined)
        except Exception:
            logger.exception("MemoryBridge: recall_for_context failed")
            return ""

    async def get_important_souvenirs(
        self, min_importance: float = 0.5, limit: int = 5
    ) -> list:
        """Get recent important souvenirs (for memory recall trigger)."""
        from memory.models import Souvenir

        try:
            return await sync_to_async(
                lambda: list(
                    Souvenir.objects.filter(importance__gte=min_importance)
                    .order_by("-created_at")[:limit]
                )
            )()
        except Exception:
            logger.debug("get_important_souvenirs failed", exc_info=True)
            return []

    async def search_related(self, text: str, n: int = 5) -> list[dict]:
        """Semantic search in ChromaDB for souvenirs related to text."""
        from memory.manager import memory_manager

        if not memory_manager.vector_store:
            return []
        try:
            return await sync_to_async(memory_manager.vector_store.search_souvenirs)(text, n=n)
        except Exception:
            logger.debug("search_related failed", exc_info=True)
            return []

    # ── Write: Create ────────────────────────────────────────────

    async def create_souvenir_from_signal(
        self, signal: InterpretedSignal
    ):
        """Create a Souvenir from an interpreted signal.

        Also indexes it in ChromaDB for vector search.
        """
        from memory.manager import memory_manager
        from memory.models import Souvenir

        try:
            souvenir = await sync_to_async(Souvenir.objects.create)(
                content=signal.summary,
                emotion=signal.emotional_reaction or "neutral",
                importance=signal.pertinence,
                occurred_at=timezone.now(),
            )

            # Index in ChromaDB (sync call — run in thread to avoid blocking event loop)
            if memory_manager.vector_store:
                await sync_to_async(memory_manager.vector_store.add_souvenir)(
                    souvenir_id=souvenir.pk,
                    content=souvenir.content,
                    metadata={
                        "importance": souvenir.importance,
                        "emotion": souvenir.emotion,
                    },
                )

            logger.info(
                "MemoryBridge: created souvenir #%d (importance=%.1f) from signal",
                souvenir.pk,
                souvenir.importance,
            )
            return souvenir
        except Exception:
            logger.exception("MemoryBridge: create_souvenir_from_signal failed")
            return None

    # ── Write: Modify Importance ─────────────────────────────────

    async def boost_importance(self, souvenir_id: int, boost: float) -> None:
        """Increase a souvenir's importance. Capped at 1.0."""
        from memory.models import Souvenir

        try:
            souvenir = await sync_to_async(Souvenir.objects.get)(pk=souvenir_id)
            old = souvenir.importance
            souvenir.importance = min(1.0, souvenir.importance + boost)
            await sync_to_async(souvenir.save)(update_fields=["importance"])
            logger.debug(
                "MemoryBridge: boost souvenir #%d importance %.2f → %.2f",
                souvenir_id, old, souvenir.importance,
            )
        except Exception:
            logger.debug("boost_importance failed for #%d", souvenir_id, exc_info=True)

    async def reduce_importance(self, souvenir_id: int, reduction: float) -> None:
        """Decrease a souvenir's importance. Floored at 0.0."""
        from memory.models import Souvenir

        try:
            souvenir = await sync_to_async(Souvenir.objects.get)(pk=souvenir_id)
            old = souvenir.importance
            souvenir.importance = max(0.0, souvenir.importance - reduction)
            await sync_to_async(souvenir.save)(update_fields=["importance"])
            logger.debug(
                "MemoryBridge: reduce souvenir #%d importance %.2f → %.2f",
                souvenir_id, old, souvenir.importance,
            )
        except Exception:
            logger.debug("reduce_importance failed for #%d", souvenir_id, exc_info=True)

    async def boost_related_souvenirs(
        self, themes: list[str], boost: float = 0.1
    ) -> int:
        """Boost importance of souvenirs linked to given themes.

        Returns the number of souvenirs affected.
        """
        from memory.models import Souvenir

        if not themes:
            return 0

        try:
            souvenirs = await sync_to_async(
                lambda: list(
                    Souvenir.objects.filter(
                        themes__name__in=themes,
                        importance__lt=1.0,
                    ).distinct()[:20]
                )
            )()

            count = 0
            for s in souvenirs:
                old = s.importance
                s.importance = min(1.0, s.importance + boost)
                await sync_to_async(s.save)(update_fields=["importance"])
                count += 1

            if count:
                logger.info(
                    "MemoryBridge: boosted %d souvenirs by %.2f (themes: %s)",
                    count, boost, themes,
                )
            return count
        except Exception:
            logger.debug("boost_related_souvenirs failed", exc_info=True)
            return 0

    # ── Write: Connaissances ─────────────────────────────────────

    async def invalidate_connaissance(
        self, connaissance_id: int, reason: str = ""
    ) -> None:
        """Mark a knowledge fact as invalid."""
        from memory.models import Connaissance

        try:
            conn = await sync_to_async(Connaissance.objects.get)(pk=connaissance_id)
            conn.is_valid = False
            await sync_to_async(conn.save)(update_fields=["is_valid"])
            logger.info(
                "MemoryBridge: invalidated connaissance #%d: %s (reason: %s)",
                connaissance_id, conn.content[:60], reason,
            )
        except Exception:
            logger.debug("invalidate_connaissance failed for #%d", connaissance_id, exc_info=True)

    async def reinforce_connaissance(
        self, connaissance_id: int, boost: float = 0.1
    ) -> None:
        """Increase confidence of a knowledge fact."""
        from memory.models import Connaissance

        try:
            conn = await sync_to_async(Connaissance.objects.get)(pk=connaissance_id)
            conn.confidence = min(1.0, conn.confidence + boost)
            await sync_to_async(conn.save)(update_fields=["confidence"])
            logger.debug(
                "MemoryBridge: reinforced connaissance #%d (confidence=%.2f)",
                connaissance_id, conn.confidence,
            )
        except Exception:
            logger.debug("reinforce_connaissance failed for #%d", connaissance_id, exc_info=True)

    async def check_contradictions(self, new_info: str) -> list[dict]:
        """Check if new information contradicts existing connaissances.

        Uses vector search to find only RELEVANT connaissances (max 5),
        then validates each with an LLM call. Much cheaper than checking all 20.

        Returns list of {connaissance_id, content, still_valid, new_confidence}.
        """
        from memory.extractor import MemoryExtractor
        from memory.manager import memory_manager
        from memory.models import Connaissance

        results = []
        extractor = MemoryExtractor()

        try:
            # Use vector search to find only connaissances semantically related
            # to the new info — avoids blind LLM calls on unrelated facts
            candidates = []
            if memory_manager.vector_store:
                raw = await sync_to_async(
                    memory_manager.vector_store.search_connaissances
                )(new_info, n=5)
                for r in raw:
                    try:
                        pk = int(r["id"])
                        conn = await sync_to_async(Connaissance.objects.get)(
                            pk=pk, is_valid=True
                        )
                        candidates.append(conn)
                    except (Connaissance.DoesNotExist, ValueError):
                        continue

            if not candidates:
                return results

            for conn in candidates:
                try:
                    still_valid, new_confidence = await extractor.check_connaissance_validity(
                        conn.content, new_info
                    )
                except Exception:
                    logger.warning(
                        "Validity check failed for connaissance #%d", conn.pk
                    )
                    continue

                if not still_valid:
                    await self.invalidate_connaissance(
                        conn.pk, reason=f"Contradicted by: {new_info[:100]}"
                    )
                    results.append({
                        "connaissance_id": conn.pk,
                        "content": conn.content,
                        "still_valid": False,
                        "new_confidence": new_confidence,
                    })
                elif new_confidence != conn.confidence:
                    conn.confidence = new_confidence
                    await sync_to_async(conn.save)(update_fields=["confidence"])
                    results.append({
                        "connaissance_id": conn.pk,
                        "content": conn.content,
                        "still_valid": True,
                        "new_confidence": new_confidence,
                    })

        except Exception:
            logger.exception("check_contradictions failed")

        return results
