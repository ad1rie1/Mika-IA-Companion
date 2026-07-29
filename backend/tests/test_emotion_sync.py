"""Tests for the live emotion sync loop (``emotion/sync.py``).

The gap this closes: the PAD oscillators advance every second, but the only
frame that ever carried an emotion was ``speech``. Between two replies the
avatar's face, the gaze/hand mood and the emotion readout were frozen on the
last thing Mika said — and ``inner_state_update`` carries no emotion at all,
so it could not stand in.

What is pinned here is the *policy*: who gets a frame, when, and what stops a
frame going out. The transport (``broadcast_emotion_update``) is checked once
end-to-end against the real in-memory channel layer, on the payload contract
the frontend reads.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from communication.presence import person_group, presence_registry
from emotion.engine import emotion_engine
from emotion.sync import MIN_INTENSITY_DELTA, EmotionSync
from emotion.types import Emotion, EmotionData


PERSON = "web_sync_test"


@pytest.fixture(autouse=True)
def _clean_registry():
    """The presence registry and the mood table are process-wide singletons."""
    yield
    presence_registry.unregister(PERSON, "web")
    presence_registry.unregister("tg_42", "telegram")
    emotion_engine.person_moods.pop(PERSON, None)


def _connect(person_id: str = PERSON, channel: str = "web", kind: str = "consumer"):
    presence_registry.register(
        person_id=person_id,
        channel=channel,
        kind=kind,
        delivery_ref=person_group(person_id) if kind == "consumer" else "chat_id",
    )


def _push(person_id: str, emotion: Emotion, intensity: float) -> None:
    """Apply a real emotional impulse — no mock oscillator."""
    emotion_engine.process_emotion(EmotionData(emotion, intensity), person_id)


def _advance(seconds: float = 3.0) -> None:
    """Step the real physics forward, as the engine's own decay loop does.

    An impulse only sets *velocity*: the PAD position — which is what
    ``compute_message_emotion`` reads — moves over the following seconds.
    So the emotional consequence of a reply is not in the ``speech`` frame
    that reports it; it arrives afterwards, which is precisely what nothing
    was pushing to the frontend.
    """
    import time

    now = time.time()
    for mood in (*emotion_engine.person_moods.values(), emotion_engine.global_mood):
        mood.last_update = now - seconds
    emotion_engine._apply_decay()


class TestWhoGetsAFrame:

    async def test_connected_consumer_is_synced(self):
        _connect()
        sync = EmotionSync()
        with patch(
            "pipeline.broadcast.broadcast_emotion_update", new=AsyncMock(),
        ) as push:
            await sync.tick()
        push.assert_awaited_once()
        assert push.await_args.args[0] == PERSON
        assert push.await_args.kwargs["group"] == person_group(PERSON)

    async def test_module_target_is_not_synced(self):
        """Telegram has no avatar to keep in sync — and no live socket."""
        _connect("tg_42", channel="telegram", kind="module")
        sync = EmotionSync()
        with patch(
            "pipeline.broadcast.broadcast_emotion_update", new=AsyncMock(),
        ) as push:
            await sync.tick()
        assert not push.await_args_list

    async def test_nobody_connected_pushes_nothing(self):
        sync = EmotionSync()
        with patch(
            "pipeline.broadcast.broadcast_emotion_update", new=AsyncMock(),
        ) as push:
            await sync.tick()
        push.assert_not_awaited()


class TestOnlyWhenItMoved:
    """A frame per tick per client, to say nothing, is what this avoids."""

    async def test_second_tick_is_silent_when_state_is_stable(self):
        _connect()
        sync = EmotionSync()
        with patch(
            "pipeline.broadcast.broadcast_emotion_update", new=AsyncMock(),
        ) as push:
            await sync.tick()
            first = push.await_count
            # Freeze the state: report the same emotion on the second pass.
            with patch.object(
                emotion_engine,
                "compute_message_emotion",
                return_value=emotion_engine.compute_message_emotion(PERSON),
            ):
                await sync.tick()
                await sync.tick()
            assert push.await_count == first

    async def test_state_moving_on_its_own_pushes(self):
        """The reason the loop exists: an impulse is velocity, so the mood
        keeps travelling for seconds after the reply that caused it — with no
        turn happening, and nothing else to report it."""
        _connect()
        sync = EmotionSync()
        with patch(
            "pipeline.broadcast.broadcast_emotion_update", new=AsyncMock(),
        ) as push:
            await sync.tick()
            before = push.await_count
            _push(PERSON, Emotion.ANGRY, 0.9)
            _advance()
            await sync.tick()
        assert push.await_count == before + 1

    async def test_impulse_alone_is_not_yet_visible(self):
        """Pins the physics this loop is built on: right after the impulse the
        reported emotion is unchanged — the movement is still in the velocity.
        If this ever became instantaneous, the loop's cadence would matter far
        less than it does today."""
        _connect()
        before = emotion_engine.compute_message_emotion(PERSON)
        _push(PERSON, Emotion.ANGRY, 0.9)
        after = emotion_engine.compute_message_emotion(PERSON)
        assert (after.emotion, after.intensity) == (before.emotion, before.intensity)
        _advance()
        moved = emotion_engine.compute_message_emotion(PERSON)
        assert (moved.emotion, moved.intensity) != (before.emotion, before.intensity)

    async def test_intensity_drift_below_threshold_stays_silent(self):
        _connect()
        sync = EmotionSync()
        base = emotion_engine.compute_message_emotion(PERSON)
        nudged = base.__class__(
            emotion=base.emotion,
            intensity=base.intensity + MIN_INTENSITY_DELTA / 2,
            person_emotion=base.person_emotion,
            person_intensity=base.person_intensity,
            global_emotion=base.global_emotion,
            global_intensity=base.global_intensity,
            blend=base.blend,
        )
        with patch(
            "pipeline.broadcast.broadcast_emotion_update", new=AsyncMock(),
        ) as push:
            with patch.object(
                emotion_engine, "compute_message_emotion", return_value=base,
            ):
                await sync.tick()
            sent = push.await_count
            with patch.object(
                emotion_engine, "compute_message_emotion", return_value=nudged,
            ):
                await sync.tick()
            assert push.await_count == sent

    async def test_intensity_drift_past_threshold_pushes(self):
        _connect()
        sync = EmotionSync()
        base = emotion_engine.compute_message_emotion(PERSON)
        moved = base.__class__(
            emotion=base.emotion,
            intensity=base.intensity + MIN_INTENSITY_DELTA * 2,
            person_emotion=base.person_emotion,
            person_intensity=base.person_intensity,
            global_emotion=base.global_emotion,
            global_intensity=base.global_intensity,
            blend=base.blend,
        )
        with patch(
            "pipeline.broadcast.broadcast_emotion_update", new=AsyncMock(),
        ) as push:
            with patch.object(
                emotion_engine, "compute_message_emotion", return_value=base,
            ):
                await sync.tick()
            sent = push.await_count
            with patch.object(
                emotion_engine, "compute_message_emotion", return_value=moved,
            ):
                await sync.tick()
            assert push.await_count == sent + 1


class TestReconnect:

    async def test_disconnect_forgets_so_reconnect_resyncs(self):
        """Otherwise a fresh client shows a neutral face until the mood moves —
        which on a calm afternoon can be a very long time."""
        _connect()
        sync = EmotionSync()
        with patch(
            "pipeline.broadcast.broadcast_emotion_update", new=AsyncMock(),
        ) as push:
            await sync.tick()
            assert push.await_count == 1

            presence_registry.unregister(PERSON, "web")
            await sync.tick()          # nobody there
            assert push.await_count == 1
            assert PERSON not in sync._last_sent

            _connect()
            await sync.tick()          # same unchanged mood, new client
            assert push.await_count == 2


class TestHydration:
    """Reading a mood creates it at the origin, and ``ensure_person_loaded``
    is a no-op for anyone already in RAM — so reading before hydrating would
    permanently lose the stored mood of a client that reconnects silently."""

    async def test_hydrates_before_first_read(self):
        _connect()
        sync = EmotionSync()
        order: list[str] = []

        async def _hydrate(person_id):
            order.append(f"hydrate:{person_id}")

        real_compute = emotion_engine.compute_message_emotion

        def _compute(person_id):
            order.append(f"read:{person_id}")
            return real_compute(person_id)

        with patch.object(
            emotion_engine, "ensure_person_loaded", side_effect=_hydrate,
        ), patch.object(
            emotion_engine, "compute_message_emotion", side_effect=_compute,
        ), patch(
            "pipeline.broadcast.broadcast_emotion_update", new=AsyncMock(),
        ):
            await sync.tick()

        assert order[0] == f"hydrate:{PERSON}"
        assert order[1] == f"read:{PERSON}"

    async def test_hydration_happens_once_per_connection(self):
        _connect()
        sync = EmotionSync()
        with patch.object(
            emotion_engine, "ensure_person_loaded", new=AsyncMock(),
        ) as hydrate, patch(
            "pipeline.broadcast.broadcast_emotion_update", new=AsyncMock(),
        ):
            await sync.tick()
            await sync.tick()
            await sync.tick()
        assert hydrate.await_count == 1


class TestFramePayload:
    """The contract the frontend reads (frontend/src/types/messages.ts)."""

    async def test_frame_carries_the_speech_emotion_fields(self):
        from channels.layers import get_channel_layer
        from pipeline.broadcast import broadcast_emotion_update

        _push(PERSON, Emotion.EXCITED, 0.8)
        layer = get_channel_layer()
        channel = await layer.new_channel()
        group = person_group(PERSON)
        await layer.group_add(group, channel)

        await broadcast_emotion_update(PERSON, group=group)
        message = await layer.receive(channel)
        data = message["data"]

        assert data["type"] == "emotion_update"
        assert data["person_id"] == PERSON
        assert isinstance(data["emotion"], str)
        assert 0.0 <= data["emotion_intensity"] <= 1.0
        assert isinstance(data["emotion_blend"], list)
        for component in data["emotion_blend"]:
            assert set(component) == {"emotion", "weight"}
        # No text, no voice decision: this frame must never reach the TTS.
        assert "text" not in data
        assert "speak" not in data

    async def test_frame_goes_to_the_person_group_not_the_broadcast_group(self):
        """The emotion is Mika's stance *toward this person* — the same reason
        a reply is not dumped on every connected client."""
        from channels.layers import get_channel_layer
        from pipeline.broadcast import BROADCAST_GROUP, broadcast_emotion_update

        layer = get_channel_layer()
        listener = await layer.new_channel()
        await layer.group_add(BROADCAST_GROUP, listener)

        await broadcast_emotion_update(PERSON)

        with pytest.raises(TimeoutError):
            import asyncio
            await asyncio.wait_for(layer.receive(listener), timeout=0.1)
