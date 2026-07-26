"""Tests for voice as a routed output modality.

Speech leaves Mika through the same channels as text. Two things are tested:
the context policy (pure, per sink) and the delivery fallback chain
(voice → text, never silently dropped).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from emotion.types import Emotion, EmotionData
from pipeline import voice
from pipeline.processor import SpeechOutput
from pipeline.voice import VoiceClip, VoiceSink, decide_voice


def _output(text="Salut !"):
    return SpeechOutput(
        text=text,
        emotion_data=EmotionData(Emotion.HAPPY, 0.7),
        emotion_name="happy",
        emotion_intensity=0.7,
        emotion_state={"person": {}, "global": {}, "message": {}},
        tool_calls=[],
    )


class TestVoicePolicy:
    """A voice note and an open-air speaker are not the same decision."""

    def test_voice_note_ignores_time_of_day(self):
        # The recipient plays it when they want — 3am is fine.
        d = decide_voice(VoiceSink.MESSAGE, hour=3)
        assert d.speak

    def test_voice_note_respects_explicit_mute(self):
        d = decide_voice(VoiceSink.MESSAGE, hour=14, muted=True)
        assert not d.speak
        assert d.reason == "muted"

    def test_speaker_silent_during_quiet_hours(self):
        for hour in (22, 23, 0, 3, 7):
            d = decide_voice(VoiceSink.SPEAKER, hour=hour)
            assert not d.speak, f"speaker should stay quiet at {hour}h"
            assert d.reason == "quiet_hours"

    def test_speaker_speaks_during_the_day(self):
        d = decide_voice(VoiceSink.SPEAKER, hour=14)
        assert d.speak

    def test_speaker_silent_when_nobody_is_there(self):
        d = decide_voice(VoiceSink.SPEAKER, hour=14, person_present=False)
        assert not d.speak
        assert d.reason == "nobody_in_the_room"

    def test_speaker_silent_while_mika_sleeps(self):
        d = decide_voice(VoiceSink.SPEAKER, hour=14, sleep_phase="rem")
        assert not d.speak
        assert "asleep" in d.reason

    def test_screen_speaks_even_at_night(self):
        # The person is deliberately looking at the app; the avatar's own
        # animation carries the sleepiness.
        d = decide_voice(VoiceSink.SCREEN, hour=3, sleep_phase="light_sleep")
        assert d.speak

    def test_screen_silent_without_a_client(self):
        d = decide_voice(VoiceSink.SCREEN, hour=14, person_present=False)
        assert not d.speak

    def test_unknown_sink_stays_silent(self):
        d = decide_voice("megaphone", hour=14)
        assert not d.speak

    def test_quiet_hours_wraps_midnight(self):
        from pipeline.voice import in_quiet_hours
        assert in_quiet_hours(23) and in_quiet_hours(2) and in_quiet_hours(7)
        assert not in_quiet_hours(9) and not in_quiet_hours(21)


class TestInnerVoiceIdentity:
    """Mika thinking aloud is a different voice from Mika talking to you."""

    def test_conscience_initiative_is_inner(self):
        from pipeline.voice import VoicePersona, persona_for_source
        assert persona_for_source("conscience") == VoicePersona.INNER

    def test_chat_reply_is_addressed_speech(self):
        from pipeline.voice import VoicePersona, persona_for_source
        assert persona_for_source("frontend") == VoicePersona.SPEAKING

    def test_initiative_aimed_at_someone_is_speech(self):
        # She decided to *tell* them something — that's not musing.
        from pipeline.voice import VoicePersona, persona_for_source
        assert (
            persona_for_source("conscience", addressed=True)
            == VoicePersona.SPEAKING
        )

    def test_inner_profile_is_quieter_and_slower(self):
        from pipeline.voice import VoicePersona, profile_for
        inner = profile_for(VoicePersona.INNER)
        spoken = profile_for(VoicePersona.SPEAKING)
        assert inner.gain < spoken.gain
        assert inner.rate < spoken.rate
        assert inner.pitch < spoken.pitch

    def test_unknown_persona_falls_back_to_speaking(self):
        from pipeline.voice import VoicePersona, profile_for
        assert profile_for("whisper-shout") == profile_for(VoicePersona.SPEAKING)

    def test_inner_thought_is_never_sent_as_a_voice_note(self):
        d = decide_voice(
            VoiceSink.MESSAGE, hour=14, persona=voice.VoicePersona.INNER)
        assert not d.speak
        assert d.reason == "inner_thought_not_sent"

    def test_inner_thought_speaks_to_an_empty_room(self):
        # Nobody to disturb, and this is exactly how a mind at work sounds.
        d = decide_voice(
            VoiceSink.SPEAKER, hour=14, person_present=False,
            persona=voice.VoicePersona.INNER,
        )
        assert d.speak
        assert d.reason == "inner_speaker_ok"

    def test_inner_thought_still_respects_quiet_hours(self):
        d = decide_voice(
            VoiceSink.SPEAKER, hour=2, persona=voice.VoicePersona.INNER)
        assert not d.speak
        assert d.reason == "quiet_hours"

    def test_inner_thought_silent_while_she_sleeps(self):
        d = decide_voice(
            VoiceSink.SPEAKER, hour=14, sleep_phase="deep_sleep",
            persona=voice.VoicePersona.INNER,
        )
        assert not d.speak

    @pytest.mark.asyncio
    async def test_payload_carries_inner_persona_for_conscience_turns(self):
        layer = MagicMock()
        layer.group_send = AsyncMock()
        with patch("pipeline.broadcast.get_channel_layer", return_value=layer):
            from pipeline.broadcast import broadcast_to_websocket
            await broadcast_to_websocket(
                _output(text="oh tiens, si j'envoyais un message à Alice..."),
                source="conscience",
            )

        data = layer.group_send.call_args[0][1]["data"]
        assert data["voice_persona"] == "inner"
        assert data["voice_profile"]["gain"] < 1.0
        assert data["speak"] is True


class TestInnerThoughtGeneration:
    """The murmur is generated from action + result, never the raw summary."""

    @pytest.mark.asyncio
    async def test_generates_from_action_and_result(self):
        from pipeline.inner_voice import generate_inner_thought

        with patch("pipeline.inner_voice.ai_router") as router:
            router.complete = AsyncMock(
                return_value="oh tiens, si j'envoyais un message à Alice...")
            thought = await generate_inner_thought(
                "écrire à Alice", "elle n'a pas répondu depuis 3 jours")

        assert thought == "oh tiens, si j'envoyais un message à Alice..."
        # Both halves of the situation reach the prompt.
        user_prompt = router.complete.await_args[0][2]
        assert "écrire à Alice" in user_prompt
        assert "3 jours" in user_prompt

    @pytest.mark.asyncio
    async def test_uses_the_small_dedicated_role(self):
        from ai.router import AIRole
        from pipeline.inner_voice import generate_inner_thought

        with patch("pipeline.inner_voice.ai_router") as router:
            router.complete = AsyncMock(return_value="mmm")
            await generate_inner_thought("relire le brouillon")

        assert router.complete.await_args[0][0] is AIRole.INNER_VOICE

    @pytest.mark.asyncio
    async def test_empty_action_makes_no_call(self):
        from pipeline.inner_voice import generate_inner_thought

        with patch("pipeline.inner_voice.ai_router") as router:
            router.complete = AsyncMock(return_value="...")
            assert await generate_inner_thought("   ") is None
            router.complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_llm_failure_is_silence_not_an_error_message(self):
        from pipeline.inner_voice import generate_inner_thought

        with patch("pipeline.inner_voice.ai_router") as router:
            router.complete = AsyncMock(side_effect=RuntimeError("quota"))
            assert await generate_inner_thought("avancer") is None

    @pytest.mark.asyncio
    async def test_strips_quotes_and_prefixes(self):
        from pipeline.inner_voice import generate_inner_thought

        for raw, expected in (
            ('"ah mais oui"', "ah mais oui"),
            ("«bon, on continue»", "bon, on continue"),
            ("Pensée: mmm, intéressant", "mmm, intéressant"),
        ):
            with patch("pipeline.inner_voice.ai_router") as router:
                router.complete = AsyncMock(return_value=raw)
                assert await generate_inner_thought("x") == expected

    @pytest.mark.asyncio
    async def test_long_output_is_truncated_to_a_murmur(self):
        from pipeline.inner_voice import MAX_THOUGHT_CHARS, generate_inner_thought

        with patch("pipeline.inner_voice.ai_router") as router:
            router.complete = AsyncMock(return_value="bla " * 200)
            thought = await generate_inner_thought("x")

        assert thought and len(thought) <= MAX_THOUGHT_CHARS

    @pytest.mark.asyncio
    async def test_blank_llm_output_is_silence(self):
        from pipeline.inner_voice import generate_inner_thought

        with patch("pipeline.inner_voice.ai_router") as router:
            router.complete = AsyncMock(return_value="   \n ")
            assert await generate_inner_thought("x") is None


class TestSynthesizerRegistry:

    def teardown_method(self):
        voice.register_synthesizer(None)

    @pytest.mark.asyncio
    async def test_no_synthesizer_returns_none(self):
        voice.register_synthesizer(None)
        assert not voice.has_synthesizer()
        assert await voice.synthesize("coucou") is None

    @pytest.mark.asyncio
    async def test_registered_synthesizer_is_used(self):
        clip = VoiceClip(data=b"OggS", mime_type="audio/ogg", duration_s=1.2)
        synth = MagicMock()
        synth.synthesize = AsyncMock(return_value=clip)
        voice.register_synthesizer(synth)

        got = await voice.synthesize("coucou", emotion="happy", intensity=0.6)
        assert got is clip
        synth.synthesize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failing_synthesizer_degrades_to_none(self):
        # A broken TTS must not take the message down with it.
        synth = MagicMock()
        synth.synthesize = AsyncMock(side_effect=RuntimeError("no audio device"))
        voice.register_synthesizer(synth)
        assert await voice.synthesize("coucou") is None


class TestVoiceDelivery:
    """The fallback chain: voice when possible, text always."""

    def _target(self, channel="telegram"):
        t = MagicMock()
        t.channel = channel
        t.person_id = "tg_42"
        t.delivery_ref = "42"
        t.reachable = True
        t.meta = {}
        return t

    def _channel(self, sink=VoiceSink.MESSAGE, voice_ok=True):
        ch = MagicMock()
        ch.is_running = True
        ch.VOICE_SINK = sink
        ch.deliver = AsyncMock(return_value=True)
        ch.deliver_voice = AsyncMock(return_value=voice_ok)
        return ch

    def teardown_method(self):
        voice.register_synthesizer(None)

    @pytest.mark.asyncio
    async def test_voice_used_when_synthesizer_available(self):
        synth = MagicMock()
        synth.synthesize = AsyncMock(
            return_value=VoiceClip(b"OggS", "audio/ogg", 1.0))
        voice.register_synthesizer(synth)
        ch = self._channel()

        with patch("communication.delivery.get_channel", return_value=ch):
            from pipeline.broadcast import _deliver_via_module
            ok = await _deliver_via_module(self._target(), _output())

        assert ok
        ch.deliver_voice.assert_awaited_once()
        ch.deliver.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_back_to_text_without_synthesizer(self):
        voice.register_synthesizer(None)
        ch = self._channel()

        with patch("communication.delivery.get_channel", return_value=ch):
            from pipeline.broadcast import _deliver_via_module
            ok = await _deliver_via_module(self._target(), _output())

        assert ok
        ch.deliver_voice.assert_not_awaited()
        ch.deliver.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_text_when_channel_refuses_clip(self):
        synth = MagicMock()
        synth.synthesize = AsyncMock(
            return_value=VoiceClip(b"OggS", "audio/ogg", 1.0))
        voice.register_synthesizer(synth)
        ch = self._channel(voice_ok=False)

        with patch("communication.delivery.get_channel", return_value=ch):
            from pipeline.broadcast import _deliver_via_module
            ok = await _deliver_via_module(self._target(), _output())

        assert ok
        ch.deliver.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_text_only_channel_never_synthesizes(self):
        synth = MagicMock()
        synth.synthesize = AsyncMock(
            return_value=VoiceClip(b"OggS", "audio/ogg", 1.0))
        voice.register_synthesizer(synth)
        ch = self._channel(sink=None)
        del ch.VOICE_SINK  # a plain text channel has no attribute at all

        with patch("communication.delivery.get_channel", return_value=ch):
            from pipeline.broadcast import _deliver_via_module
            ok = await _deliver_via_module(self._target(), _output())

        assert ok
        synth.synthesize.assert_not_awaited()
        ch.deliver.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_muted_target_gets_text(self):
        synth = MagicMock()
        synth.synthesize = AsyncMock(
            return_value=VoiceClip(b"OggS", "audio/ogg", 1.0))
        voice.register_synthesizer(synth)
        ch = self._channel()
        target = self._target()
        target.meta = {"voice_muted": True}

        with patch("communication.delivery.get_channel", return_value=ch):
            from pipeline.broadcast import _deliver_via_module
            ok = await _deliver_via_module(target, _output())

        assert ok
        synth.synthesize.assert_not_awaited()
        ch.deliver.assert_awaited_once()


class TestScreenDecisionInPayload:

    @pytest.mark.asyncio
    async def test_speech_payload_carries_the_speak_decision(self):
        layer = MagicMock()
        layer.group_send = AsyncMock()
        with patch("pipeline.broadcast.get_channel_layer", return_value=layer):
            from pipeline.broadcast import broadcast_to_websocket
            await broadcast_to_websocket(_output(), source="frontend")

        data = layer.group_send.call_args[0][1]["data"]
        assert data["speak"] is True
        assert data["voice_reason"] == "screen_ok"
