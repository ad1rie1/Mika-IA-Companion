"""Tests for the presence registry and recipient-aware output dispatch."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from communication.presence import (
    Interlocutor,
    PresenceRegistry,
    person_group,
    presence_registry,
)
from emotion.types import Emotion, EmotionData
from pipeline.broadcast import BROADCAST_GROUP, broadcast_to_websocket
from pipeline.processor import SpeechOutput


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def registry():
    return PresenceRegistry()


@pytest.fixture
def clean_global_registry():
    """Isolate tests that use the module-level singleton."""
    presence_registry._by_key.clear()
    yield presence_registry
    presence_registry._by_key.clear()


def make_output(text="coucou") -> SpeechOutput:
    return SpeechOutput(
        text=text,
        emotion_data=EmotionData(Emotion.HAPPY, 0.7),
        emotion_name="happy",
        emotion_intensity=0.7,
        emotion_state={"person": {}, "global": {}, "message": {}},
        tool_calls=[],
    )


# ── person_group ──────────────────────────────────────────────────

class TestPersonGroup:

    def test_prefixed(self):
        assert person_group("alice").startswith("vtuber_person_")

    def test_sanitizes_unsafe_chars(self):
        g = person_group("a b/c:d")
        assert " " not in g and "/" not in g and ":" not in g

    def test_distinct_persons_distinct_groups(self):
        assert person_group("alice") != person_group("bob")


# ── Registry ──────────────────────────────────────────────────────

class TestRegistry:

    def test_register_and_resolve(self, registry):
        registry.register("alice", "web", "consumer", delivery_ref="g")
        found = registry.resolve("alice")
        assert len(found) == 1
        assert found[0].channel == "web"
        assert found[0].is_consumer

    def test_resolve_unknown_is_empty(self, registry):
        assert registry.resolve("nobody") == []

    def test_same_person_multiple_channels(self, registry):
        registry.register("alice", "web", "consumer")
        registry.register("alice", "telegram", "module", delivery_ref="123")
        channels = {i.channel for i in registry.resolve("alice")}
        assert channels == {"web", "telegram"}

    def test_register_refreshes_handle(self, registry):
        registry.register("alice", "telegram", "module", delivery_ref="111")
        registry.register("alice", "telegram", "module", delivery_ref="222")
        found = registry.resolve("alice")
        assert len(found) == 1
        assert found[0].delivery_ref == "222"

    def test_unregister(self, registry):
        registry.register("alice", "web", "consumer")
        registry.unregister("alice", "web")
        assert registry.resolve("alice") == []

    def test_unreachable_excluded_from_resolve(self, registry):
        registry.register("alice", "telegram", "module", delivery_ref="1")
        registry.mark_unreachable("alice", "telegram")
        assert registry.resolve("alice") == []
        # ...but still tracked
        assert any(i.person_id == "alice" for i in registry.all())

    def test_reachable_lists_only_reachable(self, registry):
        registry.register("a", "web", "consumer")
        registry.register("b", "telegram", "module")
        registry.mark_unreachable("b", "telegram")
        reachable_ids = {i.person_id for i in registry.reachable()}
        assert reachable_ids == {"a"}


# ── Dispatch routing ──────────────────────────────────────────────

class TestDispatchRouting:

    @pytest.fixture(autouse=True)
    def _layer(self):
        self.layer = MagicMock()
        self.layer.group_send = AsyncMock()
        with patch("pipeline.broadcast.get_channel_layer", return_value=self.layer):
            yield

    async def test_consumer_target_uses_person_group(self, clean_global_registry):
        clean_global_registry.register(
            "alice", "web", "consumer", delivery_ref=person_group("alice")
        )
        await broadcast_to_websocket(make_output(), "frontend", "alice")

        sent_groups = [c.args[0] for c in self.layer.group_send.await_args_list]
        assert person_group("alice") in sent_groups
        assert BROADCAST_GROUP not in sent_groups  # no cross-client leak

    async def test_unresolved_falls_back_to_broadcast(self, clean_global_registry):
        await broadcast_to_websocket(make_output(), "conscience", "conscience_mika")
        sent_groups = [c.args[0] for c in self.layer.group_send.await_args_list]
        assert sent_groups == [BROADCAST_GROUP]

    async def test_module_proactive_calls_deliver(self, clean_global_registry):
        clean_global_registry.register(
            "tg_1", "telegram", "module", delivery_ref="555"
        )
        fake_module = MagicMock()
        fake_module.is_running = True
        fake_module.deliver = AsyncMock(return_value=True)

        with patch("modules.manager.module_manager.get_module", return_value=fake_module):
            # source != target channel → proactive → deliver via module API
            await broadcast_to_websocket(make_output(), "conscience", "tg_1")

        fake_module.deliver.assert_awaited_once()
        # Not broadcast to web
        sent_groups = [c.args[0] for c in self.layer.group_send.await_args_list]
        assert BROADCAST_GROUP not in sent_groups

    async def test_module_reactive_skips_deliver_and_broadcast(self, clean_global_registry):
        """A reactive Telegram turn echoes itself; dispatch must not double-send."""
        clean_global_registry.register(
            "tg_1", "telegram", "module", delivery_ref="555"
        )
        fake_module = MagicMock()
        fake_module.is_running = True
        fake_module.deliver = AsyncMock(return_value=True)

        with patch("modules.manager.module_manager.get_module", return_value=fake_module):
            # source == target channel → reactive → no module deliver, no broadcast
            await broadcast_to_websocket(make_output(), "telegram", "tg_1")

        fake_module.deliver.assert_not_awaited()
        assert self.layer.group_send.await_count == 0
