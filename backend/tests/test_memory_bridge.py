"""
Tests for the Conscience MemoryBridge and Django ORM memory operations.

Uses Django's test database (pytest-django) for real DB operations.
Tests souvenir creation; boost/reduce et les operations sur les
connaissances sont couverts au niveau du memory_manager
(``test_memory_manager.py``), seul endroit ou elles existent.
"""

import pytest
from asgiref.sync import sync_to_async

from conscience.memory_bridge import MemoryBridge
from conscience.types import InterpretedSignal


# ===================================================================
# SOUVENIR OPERATIONS (via Django test DB)
# ===================================================================

@pytest.mark.django_db
class TestSouvenirCreation:

    @pytest.mark.asyncio
    async def test_create_souvenir_from_signal(self):
        """Creating a souvenir from an interpreted signal should persist to DB."""
        from memory.models import Souvenir

        bridge = MemoryBridge()
        signal = InterpretedSignal(
            summary="Alice a parle de son chat Pixel",
            category="communication",
            pertinence=0.7,
            emotional_reaction="sad",
            emotional_intensity=0.6,
            themes=["animaux"],
            entities=["Alice", "Pixel"],
            should_remember=True,
        )

        souvenir = await bridge.create_souvenir_from_signal(signal)

        assert souvenir is not None
        assert souvenir.content == "Alice a parle de son chat Pixel"
        assert souvenir.emotion == "sad"
        assert souvenir.importance == 0.7

    @pytest.mark.asyncio
    async def test_create_multiple_souvenirs(self):
        from memory.models import Souvenir

        bridge = MemoryBridge()

        for i in range(5):
            signal = InterpretedSignal(
                summary=f"Souvenir numero {i}",
                category="communication",
                pertinence=0.3 + i * 0.1,
                emotional_reaction="happy" if i % 2 == 0 else "sad",
                emotional_intensity=0.5,
                should_remember=True,
            )
            await bridge.create_souvenir_from_signal(signal)

        count = await sync_to_async(Souvenir.objects.count)()
        assert count >= 5


# ===================================================================
# MEMORY MANAGER SHORT-TERM (with Django)
# ===================================================================

@pytest.mark.django_db
class TestMemoryManagerShortTerm:

    @pytest.mark.asyncio
    async def test_add_and_retrieve_messages(self):
        """Messages added to memory_manager should be retrievable."""
        from memory.manager import MemoryManager

        mm = MemoryManager()
        # Don't call full initialize (needs ChromaDB), just set up short-term
        mm.short_term = []
        mm.max_short_term = 20

        await mm.add_message("user", "Salut Mika !", person_id="test_user")
        await mm.add_message("assistant", "Hey !")

        ctx = mm.get_conversation_context()
        assert len(ctx) == 2
        assert ctx[0]["role"] == "user"
        assert ctx[0]["content"] == "Salut Mika !"
        assert ctx[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_short_term_limit(self):
        from memory.manager import MemoryManager

        mm = MemoryManager()
        mm.short_term = []
        mm.max_short_term = 5

        for i in range(10):
            await mm.add_message("user", f"msg_{i}")

        ctx = mm.get_conversation_context()
        assert len(ctx) == 5
        assert ctx[0]["content"] == "msg_5"
        assert ctx[-1]["content"] == "msg_9"


# ===================================================================
# EMOTION SNAPSHOT PERSISTENCE
# ===================================================================

@pytest.mark.django_db
class TestEmotionSnapshotPersistence:

    @pytest.mark.asyncio
    async def test_snapshot_created(self):
        """Saving emotion state should create EmotionSnapshot records."""
        from memory.models import EmotionSnapshot, Conversation
        from emotion.engine import EmotionEngine
        from emotion.types import EmotionData, Emotion
        from emotion.state import GlobalMood, Temperament

        # Create a conversation for FK
        conversation = await sync_to_async(Conversation.objects.create)()

        # Create and persist snapshot directly
        await sync_to_async(EmotionSnapshot.objects.create)(
            conversation=conversation,
            person_id="test_person",
            primary_emotion="happy",
            primary_intensity=0.7,
            global_emotion="happy",
            global_intensity=0.3,
        )

        count = await sync_to_async(EmotionSnapshot.objects.count)()
        assert count >= 1

        snap = await sync_to_async(
            EmotionSnapshot.objects.filter(person_id="test_person").first
        )()
        assert snap.primary_emotion == "happy"
        assert snap.primary_intensity == 0.7


# ===================================================================
# DJANGO ORM MODELS BASIC VALIDATION
# ===================================================================

@pytest.mark.django_db
class TestDjangoModels:

    @pytest.mark.asyncio
    async def test_conversation_creation(self):
        from memory.models import Conversation
        conv = await sync_to_async(Conversation.objects.create)()
        assert conv.pk is not None

    @pytest.mark.asyncio
    async def test_message_creation(self):
        from memory.models import Conversation, Message
        conv = await sync_to_async(Conversation.objects.create)()
        msg = await sync_to_async(Message.objects.create)(
            conversation=conv,
            role="user",
            content="Test message",
            source="test",
            person_id="test_user",
        )
        assert msg.pk is not None
        assert msg.role == "user"

    @pytest.mark.asyncio
    async def test_souvenir_creation(self):
        from django.utils import timezone
        from memory.models import Souvenir
        s = await sync_to_async(Souvenir.objects.create)(
            content="Un beau souvenir de test",
            emotion="happy",
            importance=0.5,
            occurred_at=timezone.now(),
        )
        assert s.pk is not None
        assert s.content == "Un beau souvenir de test"

    @pytest.mark.asyncio
    async def test_connaissance_creation(self):
        from memory.models import Connaissance
        c = await sync_to_async(Connaissance.objects.create)(
            content="Le ciel est bleu",
            confidence=0.9,
            is_valid=True,
        )
        assert c.pk is not None
        assert c.is_valid is True

    @pytest.mark.asyncio
    async def test_conscience_observation_creation(self):
        from conscience.models import Observation
        obs = await sync_to_async(Observation.objects.create)(
            source="test",
            event_type="test.event",
            raw_data={"key": "value"},
            summary="Test observation",
            category="system",
            pertinence=0.5,
        )
        assert obs.pk is not None
        assert obs.status == "pending"

    @pytest.mark.asyncio
    async def test_conscience_log_creation(self):
        from conscience.models import ConscienceLog
        log = await sync_to_async(ConscienceLog.objects.create)(
            observations_count=3,
            max_pertinence=0.7,
            global_mood="happy",
            global_intensity=0.5,
            idle_seconds=120.0,
            decision="wait",
            reason="testing",
        )
        assert log.pk is not None
        assert log.decision == "wait"
