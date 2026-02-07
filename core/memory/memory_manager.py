import logging

from core.config import settings
from core.memory import database as db

logger = logging.getLogger(__name__)


class MemoryManager:
    """Manages short-term (in-memory) and long-term (SQLite) conversation memory."""

    def __init__(self):
        self.short_term: list[dict] = []
        self.max_short_term = settings.memory_short_term_limit
        self.conversation_id: int | None = None
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return
        await db.init_db()
        self.conversation_id = await db.create_conversation()
        self._initialized = True
        logger.info("Memory initialized, conversation_id=%d", self.conversation_id)

    async def add_message(self, role: str, content: str, source: str = "frontend"):
        """Add a message to short-term memory and persist to DB."""
        self.short_term.append({"role": role, "content": content})
        if len(self.short_term) > self.max_short_term:
            self.short_term = self.short_term[-self.max_short_term :]

        if self._initialized and self.conversation_id is not None:
            try:
                await db.save_message(self.conversation_id, role, content, source)
            except Exception:
                logger.exception("Failed to persist message to DB")

    def get_conversation_context(self) -> list[dict]:
        """Return the current conversation history for Claude."""
        return list(self.short_term)

    async def get_long_term_memories(self) -> list[str]:
        if not self._initialized:
            return []
        return await db.get_memories()

    async def save_summary(self, summary: str, keywords: str = ""):
        if not self._initialized:
            return
        await db.save_memory(summary, keywords)

    def clear_short_term(self):
        self.short_term.clear()
