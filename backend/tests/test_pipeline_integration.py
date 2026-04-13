"""
Integration test for the full conversation pipeline.

Mocks the AI call to return controlled responses, then verifies
the full flow: context assembly -> prompt -> AI -> emotion parsing
-> emotion engine -> SpeechOutput.

Tests the pipeline WITHOUT network, DB, or real AI calls.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from emotion.types import Emotion, EmotionData
from emotion.engine import EmotionEngine
from emotion.state import GlobalMood
from pipeline.processor import process_message, SpeechOutput
from pipeline.context import ConversationContext
from pipeline.prompt import build_system_prompt, format_conversation
from pipeline.response import call_ai_and_parse
from tests.conftest import TEMPERAMENT_DEFAULT


# ===================================================================
# HELPERS
# ===================================================================

def make_context(
    emotion_context: str = "",
    memory_context: str = "",
    module_context: str = "",
    history: list[dict] | None = None,
) -> ConversationContext:
    """Build a ConversationContext without async gather."""
    return ConversationContext(
        memory_context=memory_context,
        emotion_context=emotion_context,
        module_context=module_context,
        history=history or [],
        mcp_server=None,
        tool_names=[],
    )


# Simulated AI responses for different scenarios
AI_RESPONSES = {
    "greeting": "[EMOTION:happy:0.7] Hey ! Bienvenue ! Trop contente de te voir ici ~",
    "question_tech": "[EMOTION:curious:0.8] Oh Python ? J'adore ! Tu bosses sur quoi en ce moment ?",
    "sad_story": "[EMOTION:sad:0.75] Oh non... Je suis vraiment desolee pour toi...",
    "insult": "[EMOTION:angry:0.85] Ok la c'est pas cool du tout. Je merite mieux que ca.",
    "joke": "[EMOTION:amused:0.9] AHAHAHAH non mais c'est trop drole ca !!",
    "deep_question": "[EMOTION:thinking:0.6] Hmm... C'est une question profonde. Laisse-moi reflechir...",
    "compliment": "[EMOTION:love:0.65] Aww c'est trop gentil... Merci ca me touche !",
    "goodbye": "[EMOTION:grateful:0.5] A bientot ! C'etait super de parler avec toi !",
    "no_emotion": "Salut ! Ca va bien merci.",
    "error_format": "[EMOTION:spaghetti:0.5] Hmm ceci est un test.",
}


# ===================================================================
# CALL_AI_AND_PARSE (with mock AI)
# ===================================================================

class TestCallAiAndParse:
    """Test the AI call + response parsing step."""

    @pytest.mark.asyncio
    async def test_happy_response_parsed(self):
        """A happy AI response should be correctly parsed."""
        ctx = make_context()

        with patch("pipeline.response.ai_client") as mock_client:
            mock_client.complete = AsyncMock(return_value=AI_RESPONSES["greeting"])

            text, emotion, tools = await call_ai_and_parse(ctx, "Salut Mika !")

        assert "Bienvenue" in text
        assert "[EMOTION:" not in text  # tag should be stripped
        assert emotion.emotion == Emotion.HAPPY
        assert emotion.intensity == 0.7
        assert tools == []

    @pytest.mark.asyncio
    async def test_angry_response_parsed(self):
        ctx = make_context()

        with patch("pipeline.response.ai_client") as mock_client:
            mock_client.complete = AsyncMock(return_value=AI_RESPONSES["insult"])

            text, emotion, tools = await call_ai_and_parse(ctx, "t'es nulle")

        assert emotion.emotion == Emotion.ANGRY
        assert emotion.intensity == 0.85

    @pytest.mark.asyncio
    async def test_no_emotion_tag_defaults_to_neutral(self):
        ctx = make_context()

        with patch("pipeline.response.ai_client") as mock_client:
            mock_client.complete = AsyncMock(return_value=AI_RESPONSES["no_emotion"])

            text, emotion, tools = await call_ai_and_parse(ctx, "ca va ?")

        assert emotion.emotion == Emotion.NEUTRAL
        assert emotion.intensity == 0.5

    @pytest.mark.asyncio
    async def test_invalid_emotion_falls_back(self):
        ctx = make_context()

        with patch("pipeline.response.ai_client") as mock_client:
            mock_client.complete = AsyncMock(return_value=AI_RESPONSES["error_format"])

            text, emotion, tools = await call_ai_and_parse(ctx, "test")

        assert emotion.emotion == Emotion.NEUTRAL  # "spaghetti" -> neutral

    @pytest.mark.asyncio
    async def test_context_layers_in_prompt(self):
        """Verify that all context layers are assembled into the prompt."""
        ctx = make_context(
            emotion_context="Tu te sens excited.",
            memory_context="Souvenir: aime les chats.",
            module_context="3 emails non lus.",
            history=[
                {"role": "user", "content": "Salut"},
                {"role": "assistant", "content": "Hey !"},
            ],
        )

        captured_system = None
        captured_user = None

        async def fake_complete(system_prompt, user_prompt):
            nonlocal captured_system, captured_user
            captured_system = system_prompt
            captured_user = user_prompt
            return "[EMOTION:happy:0.5] Ok !"

        with patch("pipeline.response.ai_client") as mock_client:
            mock_client.complete = fake_complete

            await call_ai_and_parse(ctx, "Nouveau message")

        assert "excited" in captured_system
        assert "chats" in captured_system
        assert "emails" in captured_system
        assert "Salut" in captured_user
        assert "Hey" in captured_user
        assert "Nouveau message" in captured_user


# ===================================================================
# PROCESS_MESSAGE (full pipeline mock)
# ===================================================================

class TestProcessMessage:
    """Test the full process_message pipeline with mocks."""

    @pytest.mark.asyncio
    async def test_full_pipeline_greeting(self):
        """Full pipeline: greeting -> happy emotion -> valid SpeechOutput."""
        ctx = make_context()

        with patch("pipeline.response.ai_client") as mock_client, \
             patch("pipeline.processor.gather_context", new_callable=AsyncMock, return_value=ctx), \
             patch("pipeline.processor.broadcast_to_websocket", new_callable=AsyncMock), \
             patch("pipeline.processor.persist_to_memory", new_callable=AsyncMock), \
             patch("pipeline.processor.emit_communication_event", new_callable=AsyncMock), \
             patch("pipeline.processor.emotion_engine") as mock_engine:

            mock_client.complete = AsyncMock(return_value=AI_RESPONSES["greeting"])
            mock_engine.process_emotion = MagicMock(return_value=MagicMock())
            mock_engine._maybe_save_snapshot = AsyncMock()
            mock_engine.compute_message_emotion = MagicMock(return_value=MagicMock(
                emotion=Emotion.HAPPY, intensity=0.7, value="happy"
            ))
            mock_engine.compute_message_emotion.return_value.emotion = Emotion.HAPPY
            mock_engine.compute_message_emotion.return_value.intensity = 0.7
            mock_engine.get_state_dict = MagicMock(return_value={
                "person": {"emotion": "happy", "intensity": 0.7, "momentum": 0.0},
                "global": {"emotion": "happy", "intensity": 0.1},
                "message": {"emotion": "happy", "intensity": 0.7},
            })

            output = await process_message(
                "Salut Mika !",
                source="frontend",
                person_id="test_user",
                context=ctx,
            )

        assert isinstance(output, SpeechOutput)
        assert "Bienvenue" in output.text
        assert output.emotion_data.emotion == Emotion.HAPPY

    @pytest.mark.asyncio
    async def test_pipeline_error_recovery(self):
        """When AI call fails, pipeline should return error message gracefully."""
        ctx = make_context()

        with patch("pipeline.response.ai_client") as mock_client, \
             patch("pipeline.processor.gather_context", new_callable=AsyncMock, return_value=ctx), \
             patch("pipeline.processor.broadcast_to_websocket", new_callable=AsyncMock), \
             patch("pipeline.processor.persist_to_memory", new_callable=AsyncMock), \
             patch("pipeline.processor.emit_communication_event", new_callable=AsyncMock), \
             patch("pipeline.processor.emotion_engine") as mock_engine:

            mock_client.complete = AsyncMock(side_effect=Exception("API timeout"))
            mock_engine.process_emotion = MagicMock(return_value=MagicMock())
            mock_engine._maybe_save_snapshot = AsyncMock()
            mock_engine.compute_message_emotion = MagicMock(return_value=MagicMock(
                emotion=Emotion.SAD, intensity=0.6,
            ))
            mock_engine.get_state_dict = MagicMock(return_value={
                "person": {"emotion": "sad", "intensity": 0.6, "momentum": 0.0},
                "global": {"emotion": "happy", "intensity": 0.0},
                "message": {"emotion": "sad", "intensity": 0.6},
            })

            output = await process_message(
                "test",
                source="frontend",
                person_id="user",
                context=ctx,
            )

        # Should get fallback error message
        assert "bug" in output.text.lower() or "réessayer" in output.text.lower()

    @pytest.mark.asyncio
    async def test_pipeline_no_broadcast_option(self):
        """broadcast=False should skip WebSocket broadcast."""
        ctx = make_context()

        with patch("pipeline.response.ai_client") as mock_client, \
             patch("pipeline.processor.gather_context", new_callable=AsyncMock, return_value=ctx), \
             patch("pipeline.processor.broadcast_to_websocket", new_callable=AsyncMock) as mock_broadcast, \
             patch("pipeline.processor.persist_to_memory", new_callable=AsyncMock), \
             patch("pipeline.processor.emit_communication_event", new_callable=AsyncMock), \
             patch("pipeline.processor.emotion_engine") as mock_engine:

            mock_client.complete = AsyncMock(return_value=AI_RESPONSES["greeting"])
            mock_engine.process_emotion = MagicMock(return_value=MagicMock())
            mock_engine._maybe_save_snapshot = AsyncMock()
            mock_engine.compute_message_emotion = MagicMock(return_value=MagicMock(
                emotion=Emotion.HAPPY, intensity=0.5,
            ))
            mock_engine.get_state_dict = MagicMock(return_value={})

            await process_message(
                "test", context=ctx, broadcast=False, persist=False, emit_event=False,
            )

        mock_broadcast.assert_not_called()

    @pytest.mark.asyncio
    async def test_pipeline_persist_option(self):
        """persist=True should call persist_to_memory."""
        ctx = make_context()

        with patch("pipeline.response.ai_client") as mock_client, \
             patch("pipeline.processor.gather_context", new_callable=AsyncMock, return_value=ctx), \
             patch("pipeline.processor.broadcast_to_websocket", new_callable=AsyncMock), \
             patch("pipeline.processor.persist_to_memory", new_callable=AsyncMock) as mock_persist, \
             patch("pipeline.processor.emit_communication_event", new_callable=AsyncMock), \
             patch("pipeline.processor.emotion_engine") as mock_engine:

            mock_client.complete = AsyncMock(return_value=AI_RESPONSES["greeting"])
            mock_engine.process_emotion = MagicMock(return_value=MagicMock())
            mock_engine._maybe_save_snapshot = AsyncMock()
            mock_engine.compute_message_emotion = MagicMock(return_value=MagicMock(
                emotion=Emotion.HAPPY, intensity=0.5,
            ))
            mock_engine.get_state_dict = MagicMock(return_value={})

            await process_message(
                "Salut",
                source="frontend",
                person_id="user1",
                context=ctx,
                broadcast=False,
                persist=True,
                emit_event=False,
            )

        mock_persist.assert_called_once()
        args = mock_persist.call_args
        assert args[0][0] == "Salut"  # user message
        assert "Bienvenue" in args[0][1]  # response text


# ===================================================================
# SPEECH OUTPUT STRUCTURE
# ===================================================================

class TestSpeechOutput:

    def test_dataclass_fields(self):
        output = SpeechOutput(
            text="Hello",
            emotion_data=EmotionData(Emotion.HAPPY, 0.7),
            emotion_name="happy",
            emotion_intensity=0.7,
            emotion_state={"person": {}, "global": {}, "message": {}},
            tool_calls=[],
        )
        assert output.text == "Hello"
        assert output.emotion_name == "happy"
        assert output.emotion_intensity == 0.7
        assert output.tool_calls == []

    def test_with_tool_calls(self):
        output = SpeechOutput(
            text="Done",
            emotion_data=EmotionData(Emotion.PROUD, 0.6),
            emotion_name="proud",
            emotion_intensity=0.6,
            emotion_state={},
            tool_calls=["send_email", "list_recent_emails"],
        )
        assert len(output.tool_calls) == 2
        assert "send_email" in output.tool_calls


# ===================================================================
# CONVERSATION CONTEXT
# ===================================================================

class TestConversationContext:

    def test_context_structure(self):
        ctx = make_context(
            emotion_context="angry",
            memory_context="mem",
            module_context="mod",
            history=[{"role": "user", "content": "hi"}],
        )
        assert ctx.emotion_context == "angry"
        assert ctx.memory_context == "mem"
        assert ctx.module_context == "mod"
        assert len(ctx.history) == 1
        assert ctx.mcp_server is None
        assert ctx.tool_names == []
