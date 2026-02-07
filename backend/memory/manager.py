import logging

from asgiref.sync import sync_to_async
from django.conf import settings

logger = logging.getLogger(__name__)


class MemoryManager:
    """Manages short-term (in-memory) and long-term (Django ORM) conversation memory."""

    def __init__(self):
        self.short_term: list[dict] = []
        self.max_short_term = settings.MEMORY_SHORT_TERM_LIMIT
        self.conversation = None
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return
        from memory.models import Conversation

        self.conversation = await Conversation.objects.acreate()
        self._initialized = True
        logger.info("Memory initialized, conversation_id=%d", self.conversation.pk)

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
        return list(self.short_term)

    async def get_long_term_memories(self) -> list[str]:
        if not self._initialized:
            return []
        from memory.models import Memory

        return await sync_to_async(list)(
            Memory.objects.values_list("summary", flat=True)[:5]
        )

    async def save_summary(self, summary: str, keywords: str = ""):
        if not self._initialized:
            return
        from memory.models import Memory

        await Memory.objects.acreate(summary=summary, keywords=keywords)

    def clear_short_term(self):
        self.short_term.clear()


memory_manager = MemoryManager()
