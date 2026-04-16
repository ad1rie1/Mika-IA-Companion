"""Integration tests for the conversation pipeline.

Entry point is `pipeline.router.perceive(Perception)`. We mock the AI
client so tests don't burn LLM calls, but leave the real processor,
emotion engine, and router in place to catch integration bugs.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from emotion.engine import emotion_engine
from emotion.types import Emotion
from pipeline.perception import Intent, Perception
from pipeline.processor import SpeechOutput, process_message
from pipeline.router import perceive


AI_RESPONSES = {
    "greeting": "[EMOTION:happy:0.7] Hey ! Bienvenue ! Trop contente de te voir ici ~",
    "question": "[EMOTION:curious:0.8] Oh Python ? J'adore ! Tu bosses sur quoi ?",
    "no_emotion": "Salut ! Ca va bien merci.",
}


def _fake_context():
    from pipeline.context import ConversationContext
    return ConversationContext(
        memory_context="",
        emotion_context="",
        module_context="",
        history=[],
        mcp_server=None,
        tool_names=[],
    )


# ===================================================================
# call_ai_and_parse
# ===================================================================

class TestCallAiAndParse:

    @pytest.mark.asyncio
    async def test_happy_response_parsed(self):
        from pipeline.response import call_ai_and_parse

        ctx = _fake_context()
        with patch("pipeline.response.ai_client") as mock_client:
            mock_client.complete = AsyncMock(return_value=AI_RESPONSES["greeting"])
            text, emotion, tools = await call_ai_and_parse(ctx, "Salut Mika !")

        assert "Bienvenue" in text
        assert "[EMOTION:" not in text
        assert emotion.emotion is Emotion.HAPPY
        assert tools == []

    @pytest.mark.asyncio
    async def test_missing_tag_falls_back_to_neutral(self):
        from pipeline.response import call_ai_and_parse

        ctx = _fake_context()
        with patch("pipeline.response.ai_client") as mock_client:
            mock_client.complete = AsyncMock(return_value=AI_RESPONSES["no_emotion"])
            text, emotion, _ = await call_ai_and_parse(ctx, "hey")

        assert "Salut" in text
        # No tag → NEUTRAL fallback
        assert emotion.emotion is Emotion.NEUTRAL


# ===================================================================
# process_message — end-to-end with mocked AI
# ===================================================================

class TestProcessMessage:

    @staticmethod
    def _perception(text: str = "Salut", person_id: str = "user_greet"):
        return Perception.from_text(text, source="frontend", person_id=person_id)

    @pytest.mark.asyncio
    async def test_happy_path_returns_speech_output(self):
        ctx = _fake_context()
        with patch("pipeline.processor.gather_context",
                   new_callable=AsyncMock, return_value=ctx), \
             patch("pipeline.processor.broadcast_to_websocket",
                   new_callable=AsyncMock), \
             patch("pipeline.processor.persist_to_memory",
                   new_callable=AsyncMock), \
             patch("pipeline.processor.emit_communication_event",
                   new_callable=AsyncMock), \
             patch("pipeline.response.ai_client") as mock_client:
            mock_client.complete = AsyncMock(return_value=AI_RESPONSES["greeting"])

            output = await process_message(self._perception(), context=ctx)

        assert isinstance(output, SpeechOutput)
        assert "Bienvenue" in output.text
        assert output.emotion_data.emotion is Emotion.HAPPY

    @pytest.mark.asyncio
    async def test_broadcast_false_skips_broadcast(self):
        ctx = _fake_context()
        with patch("pipeline.processor.gather_context",
                   new_callable=AsyncMock, return_value=ctx), \
             patch("pipeline.processor.broadcast_to_websocket",
                   new_callable=AsyncMock) as mock_broadcast, \
             patch("pipeline.processor.persist_to_memory",
                   new_callable=AsyncMock), \
             patch("pipeline.processor.emit_communication_event",
                   new_callable=AsyncMock), \
             patch("pipeline.response.ai_client") as mock_client:
            mock_client.complete = AsyncMock(return_value=AI_RESPONSES["greeting"])

            await process_message(self._perception("hi", "u"), context=ctx, broadcast=False)

        mock_broadcast.assert_not_called()

    @pytest.mark.asyncio
    async def test_persist_false_skips_persistence(self):
        ctx = _fake_context()
        with patch("pipeline.processor.gather_context",
                   new_callable=AsyncMock, return_value=ctx), \
             patch("pipeline.processor.broadcast_to_websocket",
                   new_callable=AsyncMock), \
             patch("pipeline.processor.persist_to_memory",
                   new_callable=AsyncMock) as mock_persist, \
             patch("pipeline.processor.emit_communication_event",
                   new_callable=AsyncMock), \
             patch("pipeline.response.ai_client") as mock_client:
            mock_client.complete = AsyncMock(return_value=AI_RESPONSES["greeting"])

            await process_message(self._perception("hi", "u"), context=ctx, persist=False)

        mock_persist.assert_not_called()

    @pytest.mark.asyncio
    async def test_attachments_meta_passed_to_persist(self):
        """The descriptor list for non-text parts must reach persist_to_memory."""
        from pipeline.perception import Perception

        ctx = _fake_context()
        perception = Perception.from_mixed(
            text="look",
            attachments=[
                {"kind": "image", "mime_type": "image/png", "name": "cat.png",
                 "content": "b64bytes"},
            ],
            source="frontend", person_id="u1",
        )
        with patch("pipeline.processor.gather_context",
                   new_callable=AsyncMock, return_value=ctx), \
             patch("pipeline.processor.broadcast_to_websocket",
                   new_callable=AsyncMock), \
             patch("pipeline.processor.persist_to_memory",
                   new_callable=AsyncMock) as mock_persist, \
             patch("pipeline.processor.emit_communication_event",
                   new_callable=AsyncMock), \
             patch("pipeline.response.ai_client") as mock_client:
            mock_client.complete = AsyncMock(return_value=AI_RESPONSES["greeting"])
            await process_message(perception, context=ctx)

        kw = mock_persist.call_args.kwargs
        meta = kw["attachments_meta"]
        assert len(meta) == 1
        assert meta[0]["kind"] == "image"
        assert meta[0]["mime_type"] == "image/png"
        assert meta[0]["name"] == "cat.png"


# ===================================================================
# Entry point: perceive() routes through process_message
# ===================================================================

class TestRouterIntegration:

    @pytest.mark.asyncio
    async def test_perceive_request_response_invokes_process_message(self):
        with patch("pipeline.processor.process_message",
                   new_callable=AsyncMock) as mock_proc:
            mock_proc.return_value = SpeechOutput(
                text="ok",
                emotion_data=None,
                emotion_name="happy",
                emotion_intensity=0.5,
                emotion_state={},
                tool_calls=[],
            )
            p = Perception.from_text(
                "bonjour", source="frontend", person_id="alice",
                intent=Intent.REQUEST_RESPONSE,
            )
            output = await perceive(p)

        assert output.text == "ok"
        # Perception is passed positionally; source lives on the perception itself.
        assert mock_proc.call_args.args[0].source == "frontend"

    @pytest.mark.asyncio
    async def test_perceive_observation_skips_process_message(self):
        with patch("pipeline.processor.process_message",
                   new_callable=AsyncMock) as mock_proc, \
             patch("modules.manager.module_manager.emit_event",
                   new_callable=AsyncMock) as mock_emit:
            from pipeline.perception import Modality, Part

            p = Perception(
                modality=Modality.SENSOR,
                intent=Intent.OBSERVATION,
                parts=[Part("text", "noise detected")],
                source="camera",
                person_id="anonymous",
            )
            result = await perceive(p)

        mock_proc.assert_not_called()
        mock_emit.assert_called_once()
        assert result is None


# ===================================================================
# SpeechOutput dataclass
# ===================================================================

class TestSpeechOutput:

    def test_required_fields(self):
        from emotion.types import EmotionData
        out = SpeechOutput(
            text="ok",
            emotion_data=EmotionData(Emotion.HAPPY, 0.5),
            emotion_name="happy",
            emotion_intensity=0.5,
            emotion_state={},
            tool_calls=[],
        )
        assert out.text == "ok"
        assert out.emotion_name == "happy"
        assert out.tool_calls == []
        # Defaults
        assert out.request_id == "-"
        assert out.emotion_blend is None
