"""Tests for pipeline error handling (P0 bugs).

When the AI call fails (exception) or times out, the pipeline must:
  1. Return a fallback response string
  2. NOT apply a sad-emotion impulse to the person_id (not the user's fault)
  3. NOT persist the fallback to memory (no pollution for the consolidator)
  4. NOT emit a chat.message event (no fake exchange to observe)
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
class TestErrorDoesNotColorPersonMood:

    async def test_exception_does_not_touch_person_mood(self):
        """Exception during AI call: person_id's mood must not receive
        a sad impulse. Only Mika's self-directed anxiety may bleed."""
        from emotion.engine import emotion_engine
        from pipeline import processor
        from pipeline.perception import Perception

        pid = "person_under_test_exc"
        emotion_engine.person_moods.pop(pid, None)

        with patch.object(processor, "call_ai_and_parse", new=AsyncMock(
            side_effect=RuntimeError("llm broke"),
        )), patch.object(processor, "gather_context", new=AsyncMock(return_value=_fake_context())):
            with patch.object(processor, "persist_to_memory", new=AsyncMock()) as persist, \
                 patch.object(processor, "emit_communication_event", new=AsyncMock()) as emit, \
                 patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
                perception = Perception.from_text("hey", source="frontend", person_id=pid)
                output = await processor.process_message(perception)

        assert "bug" in output.text.lower() or "reessayer" in output.text.lower()
        mood = emotion_engine.person_moods.get(pid)
        assert mood is None or mood.intensity < 0.05
        persist.assert_not_called()
        emit.assert_not_called()

    async def test_timeout_does_not_touch_person_mood(self):
        from emotion.engine import emotion_engine
        from pipeline import processor
        from pipeline.perception import Perception

        pid = "person_under_test_timeout"
        emotion_engine.person_moods.pop(pid, None)

        async def hang(*a, **kw):
            await asyncio.sleep(10)

        with patch.object(processor, "call_ai_and_parse", new=hang), \
             patch.object(processor, "gather_context", new=AsyncMock(return_value=_fake_context())), \
             patch.object(processor.settings, "AI_CALL_TIMEOUT", 0.05), \
             patch.object(processor, "persist_to_memory", new=AsyncMock()) as persist, \
             patch.object(processor, "emit_communication_event", new=AsyncMock()) as emit, \
             patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
            perception = Perception.from_text("hey", source="frontend", person_id=pid)
            output = await processor.process_message(perception)

        mood = emotion_engine.person_moods.get(pid)
        assert mood is None or mood.intensity < 0.05
        persist.assert_not_called()
        emit.assert_not_called()
        assert "reflechis" in output.text.lower() or "instant" in output.text.lower()


@pytest.mark.asyncio
class TestSingleDriveSatisfaction:
    """gather_context used to double-count social drive satisfaction: once
    before the AI call, once again when conscience.observe() fired on the
    chat.message event. Satisfaction must happen exactly once now."""

    async def test_gather_context_does_not_satisfy_drive(self):
        from drives.engine import drive_engine
        from drives.state import DriveKind
        from pipeline import context as context_module

        drive_engine.reset()
        drive_engine.states[DriveKind.SOCIAL].tension = 0.9
        before = drive_engine.states[DriveKind.SOCIAL].tension

        with patch.object(context_module.memory_manager, "get_memory_context",
                          new=AsyncMock(return_value="")), \
             patch("pipeline.context._fetch_self_concept",
                   new=AsyncMock(return_value="")), \
             patch("pipeline.context._fetch_person_context",
                   new=AsyncMock(return_value="")):
            await context_module.gather_context("hi", "some_user")

        after = drive_engine.states[DriveKind.SOCIAL].tension
        # gather_context must not satisfy the drive (which would subtract
        # decay_on_satisfy × tension). A few microseconds of natural growth
        # is fine, so we assert "didn't drop" rather than strict equality.
        assert after >= before


def _fake_context():
    from pipeline.context import ConversationContext
    return ConversationContext(
        memory_context="",
        emotion_context="",
        module_context="",
        history=[],
        tools=[],
        tool_names=[],
    )
