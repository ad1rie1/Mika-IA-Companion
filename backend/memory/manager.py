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

        # Initialize contextual memory
        try:
            from memory.consolidator import MemoryConsolidator
            from memory.extractor import MemoryExtractor
            from memory.retriever import MemoryRetriever
            from memory.vector_store import VectorStore

            self.vector_store = VectorStore()
            self.extractor = MemoryExtractor()
            self.retriever = MemoryRetriever(self.vector_store)
            self.consolidator = MemoryConsolidator(self.extractor, self.vector_store)
            await self.consolidator.start()
            logger.info("Contextual memory system initialized")
        except Exception:
            logger.exception("Failed to initialize contextual memory (falling back to basic)")

        self._initialized = True

    async def add_message(self, role: str, content: str, source: str = "frontend"):
        """Add to short-term memory and persist via ORM."""
        self.short_term.append({"role": role, "content": content})
        if len(self.short_term) > self.max_short_term:
            self.short_term = self.short_term[-self.max_short_term :]

        if self._initialized and self.conversation:
            try:
                from memory.models import Message

                await Message.objects.acreate(
                    conversation=self.conversation,
                    role=role,
                    content=content,
                    source=source,
                )
            except Exception:
                logger.exception("Failed to persist message to DB")

    def get_conversation_context(self) -> list[dict]:
        """Get short-term conversation history for Claude."""
        return list(self.short_term)

    async def get_memory_context(self, query: str) -> str:
        """Retrieve relevant long-term memories formatted for the system prompt."""
        if not self.retriever:
            return ""
        try:
            return await self.retriever.retrieve(query)
        except Exception:
            logger.exception("Memory retrieval error")
            return ""

    async def get_long_term_memories(self) -> list[str]:
        """Legacy method for backward compatibility."""
        if not self._initialized:
            return []
        from memory.models import Memory

        return await sync_to_async(list)(
            Memory.objects.values_list("summary", flat=True)[:5]
        )

    async def save_summary(self, summary: str, keywords: str = ""):
        """Legacy method for backward compatibility."""
        if not self._initialized:
            return
        from memory.models import Memory

        await Memory.objects.acreate(summary=summary, keywords=keywords)

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
