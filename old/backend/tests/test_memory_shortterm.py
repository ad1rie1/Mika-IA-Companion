"""
Tests for the Memory system's short-term message buffer.

Since the full MemoryManager requires Django DB + ChromaDB,
these tests focus on the in-memory short-term list behavior
using a lightweight mock that mimics the real MemoryManager's
short-term operations.
"""

import pytest


class ShortTermBuffer:
    """
    Standalone replica of MemoryManager's short-term buffer logic,
    extracted for testing without Django/ChromaDB dependencies.
    """

    def __init__(self, max_size: int = 20):
        self.messages: list[dict] = []
        self.max_size = max_size

    def add_message(self, role: str, content: str, source: str = "frontend",
                    person_id: str = ""):
        msg = {
            "role": role,
            "content": content,
            "source": source,
            "person_id": person_id,
        }
        self.messages.append(msg)
        if len(self.messages) > self.max_size:
            self.messages = self.messages[-self.max_size:]

    def get_context(self) -> list[dict]:
        return list(self.messages)

    def clear(self):
        self.messages.clear()


# ===================================================================
# SHORT-TERM BUFFER
# ===================================================================

class TestShortTermBuffer:

    def test_add_single_message(self):
        buf = ShortTermBuffer()
        buf.add_message("user", "Salut Mika !")

        assert len(buf.messages) == 1
        assert buf.messages[0]["role"] == "user"
        assert buf.messages[0]["content"] == "Salut Mika !"

    def test_add_user_and_assistant(self):
        buf = ShortTermBuffer()
        buf.add_message("user", "Salut !")
        buf.add_message("assistant", "Hey ! Ca va ?")

        assert len(buf.messages) == 2
        assert buf.messages[0]["role"] == "user"
        assert buf.messages[1]["role"] == "assistant"

    def test_max_size_respected(self):
        """Buffer should never exceed max_size."""
        buf = ShortTermBuffer(max_size=5)

        for i in range(10):
            buf.add_message("user", f"Message {i}")

        assert len(buf.messages) == 5
        # Should keep the 5 most recent
        assert buf.messages[0]["content"] == "Message 5"
        assert buf.messages[4]["content"] == "Message 9"

    def test_default_max_is_20(self):
        buf = ShortTermBuffer()
        assert buf.max_size == 20

    def test_get_context_returns_copy(self):
        buf = ShortTermBuffer()
        buf.add_message("user", "test")

        ctx = buf.get_context()
        ctx.append({"role": "hacker", "content": "injected"})

        assert len(buf.messages) == 1, "Original buffer should not be modified"

    def test_clear(self):
        buf = ShortTermBuffer()
        buf.add_message("user", "test")
        buf.clear()

        assert len(buf.messages) == 0

    def test_person_id_tracked(self):
        buf = ShortTermBuffer()
        buf.add_message("user", "Salut", person_id="alice_123")

        assert buf.messages[0]["person_id"] == "alice_123"

    def test_source_tracked(self):
        buf = ShortTermBuffer()
        buf.add_message("user", "Salut", source="telegram")

        assert buf.messages[0]["source"] == "telegram"


# ===================================================================
# CONVERSATION REPLAY
# ===================================================================

class TestConversationReplay:
    """Simulate full conversations through the buffer and verify context."""

    def test_full_conversation_context(self):
        """A complete conversation should maintain proper order."""
        buf = ShortTermBuffer()

        exchanges = [
            ("user", "Salut Mika !"),
            ("assistant", "Hey ! Bienvenue !"),
            ("user", "Ca va ?"),
            ("assistant", "Super bien et toi ?"),
            ("user", "Nickel, on parle de quoi ?"),
            ("assistant", "De tout ! T'as des idees ?"),
        ]

        for role, content in exchanges:
            buf.add_message(role, content)

        ctx = buf.get_context()
        assert len(ctx) == 6
        for i, (role, content) in enumerate(exchanges):
            assert ctx[i]["role"] == role
            assert ctx[i]["content"] == content

    def test_long_conversation_drops_oldest(self):
        """In a long conversation, oldest messages should be dropped."""
        buf = ShortTermBuffer(max_size=10)

        # 25 exchanges = 50 messages, buffer keeps 10
        for i in range(25):
            buf.add_message("user", f"Question {i}")
            buf.add_message("assistant", f"Reponse {i}")

        ctx = buf.get_context()
        assert len(ctx) == 10

        # Should have the last 10 messages (exchanges 20-24)
        assert ctx[0]["content"] == "Question 20"
        assert ctx[1]["content"] == "Reponse 20"
        assert ctx[-1]["content"] == "Reponse 24"

    def test_multi_person_messages_interleave(self):
        """Multiple persons' messages should interleave correctly."""
        buf = ShortTermBuffer()

        buf.add_message("user", "Salut !", person_id="alice")
        buf.add_message("assistant", "Hey Alice !")
        buf.add_message("user", "Yo", person_id="bob")
        buf.add_message("assistant", "Salut Bob !")
        buf.add_message("user", "Comment ca ?", person_id="alice")
        buf.add_message("assistant", "Bien et toi ?")

        ctx = buf.get_context()
        assert len(ctx) == 6
        assert ctx[0]["person_id"] == "alice"
        assert ctx[2]["person_id"] == "bob"
        assert ctx[4]["person_id"] == "alice"


# ===================================================================
# SIMULATED STREAM SESSION
# ===================================================================

class TestStreamSession:
    """Simulate a full stream session through the buffer."""

    def test_two_hour_stream_simulation(self):
        """Simulate 2 hours of stream chat (120 exchanges)."""
        buf = ShortTermBuffer(max_size=20)

        topics = [
            "gaming", "anime", "tech", "musique", "cuisine",
            "voyage", "films", "science", "art", "sport",
        ]

        for i in range(120):
            topic = topics[i % len(topics)]
            buf.add_message("user", f"On parle de {topic} #{i} ?",
                           person_id=f"viewer_{i % 5}")
            buf.add_message("assistant", f"Oh oui {topic} c'est genial !")

        # Should have exactly 20 messages (last 10 exchanges)
        ctx = buf.get_context()
        assert len(ctx) == 20

        # Oldest should be exchange 110 (user message)
        assert "#110" in ctx[0]["content"]
        # Most recent should be exchange 119 (assistant reply)
        # The assistant reply doesn't contain the # — check user msg at -2
        assert "#119" in ctx[-2]["content"]

    def test_buffer_preserves_recent_context(self):
        """Important: recent messages should always be available for AI context."""
        buf = ShortTermBuffer(max_size=20)

        # Fill with noise
        for i in range(50):
            buf.add_message("user", f"noise {i}")
            buf.add_message("assistant", f"reply {i}")

        # Add an important message
        buf.add_message("user", "Mon chat s'appelle Pixel et il est mort hier",
                       person_id="sad_viewer")
        buf.add_message("assistant", "Oh non je suis desolee pour Pixel...")

        ctx = buf.get_context()
        # The important message should be in the context
        contents = [m["content"] for m in ctx]
        assert any("Pixel" in c for c in contents), \
            "Recent important messages must be in context"
