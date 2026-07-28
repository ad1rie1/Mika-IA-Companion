"""`_turn.completed` — the signal that replaced the processor's inline hooks.

``process_message`` used to call ``drive_engine.on_reply`` and
``conscience_engine.post_action_audit`` directly, each behind its own
``try/except: logger.debug``. Neither wiring was ever tested: the drive test
exercised ``on_reply`` in isolation, and nothing at all covered the audit —
so the suite would have stayed green if the processor had simply stopped
calling them. These tests cover the wiring itself.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from emotion.types import Emotion
from modules.types import ModuleEvent
from pipeline.perception import Intent, Perception
from pipeline.processor import process_message
from pipeline.signals import TURN_COMPLETED, publish_turn_completed
from utils.eventbus import DeliveryMode, EventBus, event_bus


def _fake_context(**kwargs):
    from pipeline.context import ConversationContext
    return ConversationContext(
        memory_context="", emotion_context="", module_context="",
        history=[], tools=[], tool_names=[], **kwargs,
    )


def _turn_event(**data):
    payload = {
        "person_id": "user_1", "source": "frontend",
        "intent": "REQUEST_RESPONSE", "text": "voila", "word_count": 1,
        "emotion_name": "happy", "emotion_intensity": 0.7,
        "project_suppresses_emotion": False,
    }
    payload.update(data)
    return ModuleEvent(
        event_type=TURN_COMPLETED, source_module="pipeline", data=payload,
    )


# ---------------------------------------------------------------------------
# 1. The internal namespace — why the signal is named `_turn.completed`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestInternalNamespace:
    """A wildcard must not reach engine plumbing.

    This is not hygiene. The conscience subscribes to ``*`` to interpret
    everything it can see, and the Forge relays ``*`` to sandboxed modules
    Mika writes herself — some of which declare ``events: ["*"]``. Without
    the reserve, announcing "a turn finished" would cost a signal-
    interpretation LLM call and wake every forged module, once per turn.
    """

    async def test_wildcard_does_not_receive_an_internal_event(self):
        bus = EventBus()
        seen = []
        bus.subscribe(lambda e: _record(seen, e), name="greedy", pattern="*")

        await bus.emit(_turn_event())
        assert seen == []

    async def test_namespace_wildcard_does_not_reach_across(self):
        bus = EventBus()
        seen = []
        bus.subscribe(lambda e: _record(seen, e), name="a", pattern="turn.*")

        await bus.emit(_turn_event())
        assert seen == []

    async def test_explicit_internal_pattern_receives_it(self):
        bus = EventBus()
        seen = []
        bus.subscribe(lambda e: _record(seen, e), name="a", pattern="_turn.*")

        await bus.emit(_turn_event())
        assert len(seen) == 1

    async def test_exact_internal_name_receives_it(self):
        bus = EventBus()
        seen = []
        bus.subscribe(lambda e: _record(seen, e), name="a", pattern=TURN_COMPLETED)

        await bus.emit(_turn_event())
        assert len(seen) == 1

    async def test_public_events_are_unaffected(self):
        bus = EventBus()
        seen = []
        bus.subscribe(lambda e: _record(seen, e), name="a", pattern="*")

        await bus.emit(ModuleEvent(
            event_type="email.received", source_module="email", data={},
        ))
        assert len(seen) == 1

    async def test_the_conscience_interpreter_is_not_woken_by_a_turn(self):
        """The concrete regression: her own reply is not a signal about the
        world, and interpreting it as one would file an Observation and burn
        a Haiku call on every single turn."""
        from utils.eventbus import PRIORITY_OBSERVER

        bus = EventBus()
        interpreted = []
        # Exactly how ConscienceEngine.initialize() subscribes.
        bus.subscribe(
            lambda e: _record(interpreted, e), name="conscience",
            mode=DeliveryMode.AWAIT, priority=PRIORITY_OBSERVER,
        )

        await bus.emit(_turn_event())
        assert interpreted == []


# ---------------------------------------------------------------------------
# 2. The processor announces the turn
# ---------------------------------------------------------------------------


class TestProcessorPublishes:

    @staticmethod
    def _run(perception, ctx, response="[EMOTION:happy:0.8] Voila pour toi !"):
        published = []

        async def _capture(**kwargs):
            published.append(kwargs)

        async def _go():
            with patch("pipeline.processor.gather_context",
                       new_callable=AsyncMock, return_value=ctx), \
                 patch("pipeline.processor.broadcast_to_websocket",
                       new_callable=AsyncMock), \
                 patch("pipeline.processor.persist_to_memory",
                       new_callable=AsyncMock), \
                 patch("pipeline.processor.emit_communication_event",
                       new_callable=AsyncMock), \
                 patch("pipeline.processor.publish_turn_completed", _capture), \
                 patch("pipeline.response.ai_client") as client:
                client.complete = AsyncMock(return_value=response)
                await process_message(perception, context=ctx)
            return published

        return _go()

    @pytest.mark.asyncio
    async def test_a_successful_turn_is_announced(self):
        published = await self._run(
            Perception.from_text("Salut", source="frontend", person_id="user_a"),
            _fake_context(),
        )
        assert len(published) == 1
        assert published[0]["person_id"] == "user_a"
        assert published[0]["source"] == "frontend"
        assert published[0]["intent"] == "REQUEST_RESPONSE"
        assert "Voila" in published[0]["text"]
        assert published[0]["emotion_name"] == Emotion.HAPPY.value

    @pytest.mark.asyncio
    async def test_an_internal_trigger_is_announced_too(self):
        """Unlike ``chat.message``, which is deliberately suppressed for
        internal triggers to avoid a feedback loop. The audit *does* want
        to know; the drives filter it out themselves."""
        published = await self._run(
            Perception.from_internal_trigger(
                "vas-y", source="conscience", person_id="user_b",
            ),
            _fake_context(),
        )
        assert len(published) == 1
        assert published[0]["intent"] == Intent.INTERNAL_TRIGGER.name

    @pytest.mark.asyncio
    async def test_a_failed_turn_is_not_announced(self):
        """A fallback message is not something Mika said. The engine already
        refuses to persist it or let it colour her mood; a listener must not
        have to re-derive that."""
        published = []

        async def _capture(**kwargs):
            published.append(kwargs)

        ctx = _fake_context()
        with patch("pipeline.processor.gather_context",
                   new_callable=AsyncMock, return_value=ctx), \
             patch("pipeline.processor.broadcast_to_websocket",
                   new_callable=AsyncMock), \
             patch("pipeline.processor.publish_turn_completed", _capture), \
             patch("pipeline.response.ai_client") as client:
            client.complete = AsyncMock(side_effect=RuntimeError("api down"))
            output = await process_message(
                Perception.from_text("Salut", source="frontend", person_id="user_c"),
                context=ctx,
            )

        assert output.ai_failed is True
        assert published == []

    @pytest.mark.asyncio
    async def test_the_project_flag_travels_with_the_turn(self):
        published = await self._run(
            Perception.from_text("Salut", source="frontend", person_id="user_d"),
            _fake_context(project_suppresses_emotion=True),
        )
        assert published[0]["project_suppresses_emotion"] is True

    def test_the_processor_no_longer_names_its_listeners(self):
        """Regression guard: the point of the refactor is that a new
        subsystem interested in a turn does not edit this function."""
        import inspect

        from pipeline import processor

        src = inspect.getsource(processor.process_message)
        assert "drive_engine.on_reply" not in src
        assert "post_action_audit" not in src
        assert "publish_turn_completed" in src


# ---------------------------------------------------------------------------
# 3. The drives subscriber owns its own skip rule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDrivesSubscriber:

    def _subscription(self):
        subs = {s.name: s for s in event_bus.subscriptions()}
        assert "drives" in subs, "drives/apps.py should subscribe at ready()"
        return subs["drives"]

    async def test_a_reply_relieves_the_expression_drive(self):
        from drives.engine import drive_engine
        from drives.state import DriveKind

        drive_engine.states[DriveKind.EXPRESSION].tension = 0.9
        await self._subscription().handler(_turn_event(word_count=40))

        assert drive_engine.states[DriveKind.EXPRESSION].tension < 0.9

    async def test_an_internal_trigger_does_not_count_as_answering(self):
        """The conscience already calls on_act() for those; double-counting
        would empty EXPRESSION on every murmur."""
        from drives.engine import drive_engine
        from drives.state import DriveKind

        drive_engine.states[DriveKind.EXPRESSION].tension = 0.9
        await self._subscription().handler(
            _turn_event(intent="INTERNAL_TRIGGER", word_count=40),
        )

        assert drive_engine.states[DriveKind.EXPRESSION].tension == 0.9

    async def test_it_is_awaited_not_detached(self):
        """The thinking delay computed later in the same turn reads the
        energy level this feeds — detaching would make that a coin flip."""
        assert self._subscription().mode is DeliveryMode.AWAIT

    async def test_it_only_listens_to_the_turn_signal(self):
        assert self._subscription().pattern == TURN_COMPLETED


# ---------------------------------------------------------------------------
# 4. The conscience audit subscriber owns its own skip rule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestConscienceAuditSubscriber:

    async def test_it_delegates_to_post_action_audit(self):
        from conscience.engine import conscience_engine

        with patch.object(
            conscience_engine, "post_action_audit", new_callable=AsyncMock,
        ) as audit:
            await conscience_engine._audit_completed_turn(
                _turn_event(text="j'ai dit un truc vif", emotion_name="angry"),
            )

        audit.assert_awaited_once()
        assert audit.await_args.kwargs["emotion_name"] == "angry"
        assert audit.await_args.kwargs["person_id"] == "user_1"

    async def test_professional_mode_produces_no_self_doubt(self):
        """Policy about ruminations, so it lives with the conscience — the
        processor used to hold this rule on its behalf."""
        from conscience.engine import conscience_engine

        with patch.object(
            conscience_engine, "post_action_audit", new_callable=AsyncMock,
        ) as audit:
            await conscience_engine._audit_completed_turn(
                _turn_event(project_suppresses_emotion=True),
            )

        audit.assert_not_awaited()

    async def test_a_missing_field_does_not_raise(self):
        """The payload is data, not a contract enforced at the call site."""
        from conscience.engine import conscience_engine

        event = ModuleEvent(
            event_type=TURN_COMPLETED, source_module="pipeline", data={},
        )
        with patch.object(
            conscience_engine, "post_action_audit", new_callable=AsyncMock,
        ):
            await conscience_engine._audit_completed_turn(event)


# ---------------------------------------------------------------------------
# 5. publish_turn_completed itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPublish:

    async def test_it_never_raises(self):
        with patch("utils.eventbus.event_bus.emit",
                   new_callable=AsyncMock, side_effect=RuntimeError("bus down")):
            await publish_turn_completed(
                person_id="p", source="frontend", intent="REQUEST_RESPONSE",
                text="hello", emotion_name="happy", emotion_intensity=0.5,
                project_suppresses_emotion=False,
            )

    async def test_word_count_is_derived_from_the_text(self):
        captured = []

        async def _capture(event):
            captured.append(event)

        with patch("utils.eventbus.event_bus.emit", _capture):
            await publish_turn_completed(
                person_id="p", source="frontend", intent="REQUEST_RESPONSE",
                text="un deux trois quatre", emotion_name="happy",
                emotion_intensity=0.5, project_suppresses_emotion=False,
            )

        assert captured[0].data["word_count"] == 4


# ---------------------------------------------------------------------------
# 6. End to end — processor to subscriber, nothing mocked in between
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEndToEnd:
    """The chain the unit tests above only cover in halves.

    Worth its own test because the failure this refactor could plausibly
    introduce is silent: the processor stops calling anything, the bus
    delivers to nobody, and every assertion about ``on_reply`` in isolation
    still passes.
    """

    async def test_a_real_turn_relieves_the_expression_drive(self):
        from drives.engine import drive_engine
        from drives.state import DriveKind

        drive_engine.states[DriveKind.EXPRESSION].tension = 0.9
        ctx = _fake_context()

        with patch("pipeline.processor.gather_context",
                   new_callable=AsyncMock, return_value=ctx), \
             patch("pipeline.processor.broadcast_to_websocket",
                   new_callable=AsyncMock), \
             patch("pipeline.processor.persist_to_memory",
                   new_callable=AsyncMock), \
             patch("pipeline.processor.emit_communication_event",
                   new_callable=AsyncMock), \
             patch("pipeline.response.ai_client") as client:
            client.complete = AsyncMock(
                return_value="[EMOTION:happy:0.8] Mais oui carrement, tiens !",
            )
            await process_message(
                Perception.from_text("Salut", source="frontend", person_id="user_e2e"),
                context=ctx,
            )

        assert drive_engine.states[DriveKind.EXPRESSION].tension < 0.9


async def _record(sink, value):
    sink.append(value)
