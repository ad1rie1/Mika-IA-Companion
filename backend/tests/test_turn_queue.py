"""The turn queue, the split persistence, and who a reply is allowed to reach.

Three properties that only make sense together:

- A turn runs off the socket's read loop, so a connection stays answerable
  while Mika is thinking (``receive`` used to await the whole pipeline, and
  Channels dispatches a consumer's frames one at a time).
- A turn is written down *before* the AI call, so a process that dies
  mid-turn leaves an unanswered question rather than no question at all.
- A reply composed for one person never lands in someone else's browser
  just because its recipient happens to be offline.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
async def _fresh_queue():
    """Each test gets its own pool, and leaves none behind."""
    from pipeline.turns import turn_queue

    await turn_queue.stop()
    yield
    await turn_queue.stop()


async def _drain(timeout=5):
    """Drain with a deadline.

    A worker that dies on a bad turn stops calling ``task_done``, so a bare
    ``drain()`` would hang the suite instead of reporting the defect — the
    same silence the pool is built to avoid, reproduced in the tests.
    """
    from pipeline.turns import turn_queue

    await asyncio.wait_for(turn_queue.drain(), timeout=timeout)


def _perception(text="coucou", person_id="web_q"):
    from pipeline.perception import Intent, Perception

    return Perception.from_text(
        text, source="frontend", person_id=person_id,
        intent=Intent.REQUEST_RESPONSE,
    )


@pytest.mark.asyncio
class TestTurnQueue:

    async def test_submit_returns_immediately(self):
        """The caller must not pay for the turn.

        This is the property the whole change exists for: ``submit`` is
        called from the consumer's read loop, and anything it waits on is
        time the connection spends unable to answer a keepalive.
        """
        from pipeline.turns import turn_queue

        release = asyncio.Event()

        async def slow(_p):
            await release.wait()

        await turn_queue.start(workers=1)
        with patch("pipeline.router.perceive", new=slow):
            accepted = turn_queue.submit(_perception())
            assert accepted is True
            # Nothing awaited the turn, so we are here while it still runs.
            await asyncio.sleep(0)
            assert turn_queue.pending + 1 >= 1
            release.set()
            await _drain()

    async def test_turns_are_processed_in_order(self):
        """Order is why this is a queue and not a task per message.

        Two ``create_task`` calls would let the second reply overtake the
        first, and would put two LLM calls on a backend that has one slot.
        """
        from pipeline.turns import turn_queue

        seen: list[str] = []

        async def record(perception):
            await asyncio.sleep(0.01)
            seen.append(perception.text)

        await turn_queue.start(workers=1)
        with patch("pipeline.router.perceive", new=record):
            for i in range(4):
                turn_queue.submit(_perception(f"m{i}"))
            await _drain()

        assert seen == ["m0", "m1", "m2", "m3"]

    async def test_one_broken_turn_does_not_kill_the_worker(self):
        """Nothing supervises this pool.

        A worker dying on a malformed perception would stop every
        conversation on the install until the next restart, silently.
        """
        from pipeline.turns import turn_queue

        seen: list[str] = []

        async def explode_then_work(perception):
            if perception.text == "boom":
                raise RuntimeError("turn exploded")
            seen.append(perception.text)

        await turn_queue.start(workers=1)
        with patch("pipeline.router.perceive", new=explode_then_work):
            turn_queue.submit(_perception("boom"))
            turn_queue.submit(_perception("apres"))
            await _drain()

        assert seen == ["apres"]
        assert turn_queue.is_running

    async def test_a_full_backlog_is_refused_rather_than_accepted(self):
        """Refusing loudly beats queuing an hour of answers nobody waits for."""
        from pipeline import turns
        from pipeline.turns import turn_queue

        release = asyncio.Event()

        async def slow(_p):
            await release.wait()

        await turn_queue.start(workers=1)
        with patch("pipeline.router.perceive", new=slow), \
             patch.object(turns, "MAX_PENDING", 2):
            # Rebuild the queue so the patched ceiling applies.
            await turn_queue.stop()
            await turn_queue.start(workers=1)
            results = [turn_queue.submit(_perception(f"m{i}")) for i in range(6)]
            release.set()
            await _drain()

        assert results[0] is True
        assert False in results, "un backlog plein doit refuser, pas gonfler"

    async def test_submit_without_a_started_pool_still_runs(self):
        """A frame arriving before the lifespan ran must not be dropped."""
        from pipeline.turns import turn_queue

        seen: list[str] = []

        async def record(perception):
            seen.append(perception.text)

        with patch("pipeline.router.perceive", new=record):
            turn_queue.submit(_perception("avant-demarrage"))
            await asyncio.sleep(0)
            await _drain()

        assert seen == ["avant-demarrage"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestSplitPersistence:
    """The question is written before the answer is attempted."""

    async def _with_conversation(self):
        from memory.manager import memory_manager
        from memory.models import Conversation

        memory_manager.conversation = await Conversation.objects.acreate()
        memory_manager._initialized = True

    async def test_the_question_is_recorded_before_the_ai_call(self):
        """A restart during the call must leave the question behind.

        Persisting afterwards meant the 120s window in which the process is
        most likely to be restarted was exactly the window in which the
        message existed nowhere — while the client had been told "received".
        """
        from memory.models import Message
        from pipeline import processor
        from pipeline.perception import Intent, Perception

        await self._with_conversation()
        rows_during: list[str] = []

        async def call_ai(_ctx, _msg):
            from asgiref.sync import sync_to_async

            rows_during.extend(
                await sync_to_async(
                    lambda: list(
                        Message.objects.filter(person_id="web_split")
                        .values_list("content", flat=True)
                    )
                )()
            )
            from emotion.types import Emotion, EmotionData

            return "voila", EmotionData(emotion=Emotion.NEUTRAL, intensity=0.0), []

        perception = Perception.from_text(
            "ma question", source="frontend", person_id="web_split",
            intent=Intent.REQUEST_RESPONSE,
        )
        with patch.object(processor, "call_ai_and_parse", new=call_ai), \
             patch.object(processor, "gather_context", new=AsyncMock()), \
             patch.object(processor, "broadcast_to_websocket", new=AsyncMock()), \
             patch.object(processor, "emit_communication_event", new=AsyncMock()), \
             patch.object(processor, "publish_turn_completed", new=AsyncMock()):
            await processor.process_message(perception)

        assert rows_during == ["ma question"], (
            "la question doit être en base pendant l'appel, pas après"
        )

    async def test_awaiting_reply_is_set_then_cleared(self):
        from asgiref.sync import sync_to_async
        from memory.models import Message
        from pipeline.broadcast import (
            persist_assistant_message, persist_user_message,
        )

        await self._with_conversation()

        user_id = await persist_user_message(
            message="q", source="frontend", person_id="web_flag",
        )
        row = await sync_to_async(Message.objects.get)(pk=user_id)
        assert row.awaiting_reply is True

        await persist_assistant_message(
            response="r", person_id="web_flag", replying_to=user_id,
        )
        row = await sync_to_async(Message.objects.get)(pk=user_id)
        assert row.awaiting_reply is False

    async def test_a_failed_turn_also_clears_the_flag(self):
        """A fallback is an answer — a bad one, but the turn is over.

        Leaving the flag set would replay the same failing turn at every
        boot, forever.
        """
        from asgiref.sync import sync_to_async
        from memory.models import Message
        from pipeline.broadcast import (
            persist_assistant_message, persist_user_message,
        )

        await self._with_conversation()
        user_id = await persist_user_message(
            message="q", source="frontend", person_id="web_failed",
        )
        await persist_assistant_message(
            response="Oups, j'ai eu un petit bug...", person_id="web_failed",
            is_internal=True, replying_to=user_id,
        )

        row = await sync_to_async(Message.objects.get)(pk=user_id)
        assert row.awaiting_reply is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestResumeAfterRestart:

    async def test_an_unanswered_question_is_requeued(self):
        from memory.models import Conversation, Message
        from pipeline.turns import resume_interrupted_turns, turn_queue

        conv = await Conversation.objects.acreate()
        await Message.objects.acreate(
            conversation=conv, role="user", content="tu es la ?",
            person_id="web_resume", awaiting_reply=True,
        )

        seen: list[str] = []

        async def record(perception):
            seen.append(perception.text)

        await turn_queue.start(workers=1)
        with patch("pipeline.router.perceive", new=record):
            count = await resume_interrupted_turns()
            await _drain()

        assert count == 1
        assert seen == ["tu es la ?"]

    async def test_the_flag_is_cleared_so_a_crash_loop_cannot_form(self):
        """Cleared at re-queue, not at success.

        A turn that dies the same way twice would otherwise be replayed at
        every boot for the life of the install.
        """
        from asgiref.sync import sync_to_async
        from memory.models import Conversation, Message
        from pipeline.turns import resume_interrupted_turns, turn_queue

        conv = await Conversation.objects.acreate()
        row = await Message.objects.acreate(
            conversation=conv, role="user", content="boum",
            person_id="web_loop", awaiting_reply=True,
        )

        async def explode(_p):
            raise RuntimeError("same crash as last time")

        await turn_queue.start(workers=1)
        with patch("pipeline.router.perceive", new=explode):
            await resume_interrupted_turns()
            await _drain()

        refreshed = await sync_to_async(Message.objects.get)(pk=row.pk)
        assert refreshed.awaiting_reply is False

        # A second boot finds nothing to replay.
        assert await resume_interrupted_turns() == 0

    async def test_internal_scaffolding_is_not_replayed(self):
        """Re-greeting on every boot is noise, not continuity."""
        from memory.models import Conversation, Message
        from pipeline.turns import resume_interrupted_turns

        conv = await Conversation.objects.acreate()
        await Message.objects.acreate(
            conversation=conv, role="user", is_internal=True,
            content="Un visiteur vient de se connecter.",
            person_id="web_int", awaiting_reply=True,
        )

        assert await resume_interrupted_turns() == 0


@pytest.mark.asyncio
class TestNoCrossPersonLeak:
    """A message composed for someone is not a message for everyone."""

    @staticmethod
    def _output():
        from emotion.types import Emotion, EmotionData
        from pipeline.processor import SpeechOutput

        return SpeechOutput(
            text="ce que je sais de toi",
            emotion_data=EmotionData(emotion=Emotion.NEUTRAL, intensity=0.0),
            emotion_name="neutral", emotion_intensity=0.0, emotion_state={},
            tool_calls=[],
        )

    async def _send_to(self, person_id):
        from pipeline import broadcast

        sent: list = []

        class FakeLayer:
            async def group_send(self, group, payload):
                sent.append((group, payload))

        with patch.object(broadcast, "get_channel_layer",
                          return_value=FakeLayer()), \
             patch.object(broadcast, "_collect_inner_state",
                          new=AsyncMock(return_value={"person_profile": {
                              "name": "Adrien", "summary": "prive",
                          }})):
            await broadcast.broadcast_to_websocket(
                self._output(), "conscience", person_id=person_id,
            )
        return sent

    async def test_an_offline_person_is_not_broadcast_to_everyone(self):
        """The payload carries their profile and commitments.

        Nothing is lost by staying silent: the turn is persisted and their
        client pulls it by cursor on reconnect.
        """
        sent = await self._send_to("user_2")
        assert sent == [], (
            "un message pour une personne absente ne doit pas partir "
            "vers tous les navigateurs connectes"
        )

    async def test_an_anonymous_socket_still_uses_the_global_group(self):
        """A throwaway id has no durable thread to be caught up from, so
        "whoever is watching" IS the intended audience."""
        from pipeline.broadcast import BROADCAST_GROUP

        sent = await self._send_to("anon_deadbeef")
        assert [group for group, _ in sent] == [BROADCAST_GROUP]

    async def test_mikas_own_thinking_aloud_still_reaches_the_room(self):
        from pipeline.broadcast import BROADCAST_GROUP

        sent = await self._send_to("conscience_mika")
        assert [group for group, _ in sent] == [BROADCAST_GROUP]
