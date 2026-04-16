import logging

from asgiref.sync import sync_to_async
from django.conf import settings

logger = logging.getLogger(__name__)


class MemoryManager:
    """Orchestrates short-term (in-memory), vector (ChromaDB), and
    structured (Django ORM) memory systems."""

    def __init__(self):
        self.short_term: list[dict] = []
        self.max_short_term = settings.MEMORY_SHORT_TERM_LIMIT
        self.conversation = None
        self._initialized = False

        # Contextual memory components (initialized async)
        self.vector_store = None
        self.extractor = None
        self.consolidator = None
        self.retriever = None

    async def initialize(self):
        """Initialize all memory subsystems."""
        if self._initialized:
            return

        from memory.models import Conversation

        self.conversation = await Conversation.objects.acreate()
        logger.info("Memory initialized, conversation_id=%d", self.conversation.pk)

        # Initialize contextual memory (requires chromadb, not yet compatible with Python 3.14+)
        try:
            import chromadb  # noqa: F401 — test import before loading subsystems

            from memory.extraction import MemoryExtractor
            from memory.retrieval import MemoryRetriever
            from memory.storage import MemoryConsolidator, VectorStore

            self.vector_store = VectorStore()
            self.extractor = MemoryExtractor()
            self.retriever = MemoryRetriever(self.vector_store)
            self.consolidator = MemoryConsolidator(self.extractor, self.vector_store)
            await self.consolidator.start()
            logger.info("Contextual memory system initialized")
        except ImportError:
            import sys
            if sys.version_info >= (3, 14):
                logger.warning(
                    "chromadb is not compatible with Python %s — "
                    "contextual memory disabled, using basic memory only",
                    sys.version,
                )
            else:
                logger.warning("chromadb not installed — contextual memory disabled")
        except Exception:
            logger.exception("Failed to initialize contextual memory (falling back to basic)")

        self._initialized = True

    async def add_message(
        self, role: str, content: str, source: str = "frontend", person_id: str = ""
    ):
        """Add to short-term memory and persist via ORM."""
        self.short_term.append({"role": role, "content": content})
        if len(self.short_term) > self.max_short_term:
            self.short_term = self.short_term[-self.max_short_term :]

        logger.debug(
            "Memory add_message: role=%s source=%s person=%s short_term=%d content=%.60s",
            role, source, person_id, len(self.short_term), content,
        )

        if self._initialized and self.conversation:
            try:
                from memory.models import Message

                await Message.objects.acreate(
                    conversation=self.conversation,
                    role=role,
                    content=content,
                    source=source,
                    person_id=person_id,
                )
            except Exception:
                logger.exception("Failed to persist message to DB")

    def get_conversation_context(self) -> list[dict]:
        """Get short-term conversation history for Claude."""
        return list(self.short_term)

    async def get_memory_context(self, query: str, person_id: str = "") -> str:
        """Retrieve relevant long-term memories formatted for the system prompt.

        If person_id is provided, results are boosted for memories
        related to that person (but not exclusively filtered — Mika
        should still recall general knowledge).
        """
        if not self.retriever:
            return ""
        try:
            return await self.retriever.retrieve(query, person_id=person_id)
        except Exception:
            logger.exception("Memory retrieval error")
            return ""

    # ── Souvenir operations (used by Conscience) ───────────────────

    async def create_souvenir(
        self, content: str, emotion: str = "neutral", importance: float = 1.0
    ):
        """Create a Souvenir and index it in ChromaDB.

        Returns the created Souvenir or None on failure.
        """
        from memory.models import Souvenir
        from django.utils import timezone

        try:
            souvenir = await sync_to_async(Souvenir.objects.create)(
                content=content,
                emotion=emotion,
                importance=importance,
                occurred_at=timezone.now(),
            )

            if self.vector_store:
                await sync_to_async(self.vector_store.add_souvenir)(
                    souvenir_id=souvenir.pk,
                    content=souvenir.content,
                    metadata={
                        "importance": souvenir.importance,
                        "emotion": souvenir.emotion,
                    },
                )

            logger.info(
                "Created souvenir #%d (importance=%.1f)",
                souvenir.pk, souvenir.importance,
            )
            return souvenir
        except Exception:
            logger.exception("Failed to create souvenir")
            return None

    async def boost_souvenir(self, souvenir_id: int, boost: float) -> None:
        """Increase a souvenir's importance. Capped at 1.0."""
        from memory.models import Souvenir

        try:
            souvenir = await sync_to_async(Souvenir.objects.get)(pk=souvenir_id)
            souvenir.importance = min(1.0, souvenir.importance + boost)
            await sync_to_async(souvenir.save)(update_fields=["importance"])
        except Exception:
            logger.debug("boost_souvenir failed for #%d", souvenir_id, exc_info=True)

    async def reduce_souvenir(self, souvenir_id: int, reduction: float) -> None:
        """Decrease a souvenir's importance. Floored at 0.0."""
        from memory.models import Souvenir

        try:
            souvenir = await sync_to_async(Souvenir.objects.get)(pk=souvenir_id)
            souvenir.importance = max(0.0, souvenir.importance - reduction)
            await sync_to_async(souvenir.save)(update_fields=["importance"])
        except Exception:
            logger.debug("reduce_souvenir failed for #%d", souvenir_id, exc_info=True)

    async def boost_souvenirs_by_themes(
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
                s.importance = min(1.0, s.importance + boost)
                await sync_to_async(s.save)(update_fields=["importance"])
                count += 1

            if count:
                logger.info(
                    "Boosted %d souvenirs by %.2f (themes: %s)",
                    count, boost, themes,
                )
            return count
        except Exception:
            logger.debug("boost_souvenirs_by_themes failed", exc_info=True)
            return 0

    async def get_important_souvenirs(
        self, min_importance: float = 0.5, limit: int = 5
    ) -> list:
        """Get recent important souvenirs."""
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

    # ── Connaissance operations (used by Conscience) ─────────────

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
                "Invalidated connaissance #%d: %s (reason: %s)",
                connaissance_id, conn.content[:60], reason,
            )
        except Exception:
            logger.debug(
                "invalidate_connaissance failed for #%d",
                connaissance_id, exc_info=True,
            )

    async def reinforce_connaissance(
        self, connaissance_id: int, boost: float = 0.1
    ) -> None:
        """Increase confidence of a knowledge fact."""
        from memory.models import Connaissance

        try:
            conn = await sync_to_async(Connaissance.objects.get)(pk=connaissance_id)
            conn.confidence = min(1.0, conn.confidence + boost)
            await sync_to_async(conn.save)(update_fields=["confidence"])
        except Exception:
            logger.debug(
                "reinforce_connaissance failed for #%d",
                connaissance_id, exc_info=True,
            )

    async def update_connaissance_confidence(
        self, connaissance_id: int, confidence: float
    ) -> None:
        """Set the confidence of a connaissance to a specific value."""
        from memory.models import Connaissance

        try:
            conn = await sync_to_async(Connaissance.objects.get)(pk=connaissance_id)
            conn.confidence = max(0.0, min(1.0, confidence))
            await sync_to_async(conn.save)(update_fields=["confidence"])
        except Exception:
            logger.debug(
                "update_connaissance_confidence failed for #%d",
                connaissance_id, exc_info=True,
            )

    async def get_valid_connaissance(self, connaissance_id: int):
        """Get a valid Connaissance by ID, or None if not found/invalid."""
        from memory.models import Connaissance

        try:
            return await sync_to_async(Connaissance.objects.get)(
                pk=connaissance_id, is_valid=True
            )
        except Connaissance.DoesNotExist:
            return None
        except Exception:
            logger.debug(
                "get_valid_connaissance failed for #%d",
                connaissance_id, exc_info=True,
            )
            return None

    async def search_related_connaissances(
        self, text: str, n: int = 5
    ) -> list[dict]:
        """Semantic search for connaissances related to text via ChromaDB."""
        if not self.vector_store:
            return []
        try:
            return await sync_to_async(self.vector_store.search_connaissances)(text, n=n)
        except Exception:
            logger.debug("search_related_connaissances failed", exc_info=True)
            return []

    async def search_related_souvenirs(self, text: str, n: int = 5) -> list[dict]:
        """Semantic search for souvenirs related to text via ChromaDB."""
        if not self.vector_store:
            return []
        try:
            return await sync_to_async(self.vector_store.search_souvenirs)(text, n=n)
        except Exception:
            logger.debug("search_related_souvenirs failed", exc_info=True)
            return []

    def clear_short_term(self):
        self.short_term.clear()

    async def shutdown(self):
        """Graceful shutdown: force final consolidation and stop background tasks."""
        if self.consolidator:
            try:
                await self.consolidator.force_consolidate()
                await self.consolidator.stop()
                logger.info("Memory consolidator shut down cleanly")
            except Exception:
                logger.exception("Error during memory shutdown")


memory_manager = MemoryManager()
