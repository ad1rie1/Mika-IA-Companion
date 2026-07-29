"""Tests for pipeline error handling (P0 bugs).

When the AI call fails (exception) or times out, the pipeline must:
  1. Return a fallback response string
  2. NOT apply a sad-emotion impulse to the person_id (not the user's fault)
  3. NOT emit a chat.message event (no fake exchange to observe)
  4. Still PERSIST the exchange — what the person said happened whether or
     not the model answered in time — but flag the fallback reply
     ``is_internal`` so it reaches neither the extractor nor the rehydrated
     history. The turn is recorded, not pretended.
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
        from configs.service import config_service
        from emotion.engine import emotion_engine
        from pipeline import processor
        from pipeline.perception import Perception

        pid = "person_under_test_exc"
        emotion_engine.person_moods.pop(pid, None)

        # The timeout read hits the ORM whenever an earlier test invalidated
        # the config cache — which is why this one was red in a full run and
        # green on its own. Its sibling below already stubs the same read.
        with patch.object(config_service, "get", return_value=60), \
             patch.object(processor, "call_ai_and_parse", new=AsyncMock(
                 side_effect=RuntimeError("llm broke"),
             )), \
             patch.object(processor.emotion_engine, "ensure_person_loaded", new=AsyncMock()), \
             patch.object(processor, "gather_context", new=AsyncMock(return_value=_fake_context())):
            with patch.object(processor, "persist_user_message",
                          new=AsyncMock(return_value=1)) as persist_q, \
                 patch.object(processor, "persist_assistant_message",
                          new=AsyncMock(return_value=2)) as persist_a, \
                 patch.object(processor, "emit_communication_event", new=AsyncMock()) as emit, \
                 patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
                perception = Perception.from_text("hey", source="frontend", person_id=pid)
                output = await processor.process_message(perception)

        assert "bug" in output.text.lower() or "reessayer" in output.text.lower()
        mood = emotion_engine.person_moods.get(pid)
        assert mood is None or mood.intensity < 0.05
        emit.assert_not_called()
        # The exchange is kept; only the reply is demoted to machinery.
        persist_q.assert_called_once()
        persist_a.assert_called_once()
        assert persist_q.call_args.kwargs["message"] == "hey"
        assert persist_q.call_args.kwargs["is_internal"] is False
        assert persist_a.call_args.kwargs["is_internal"] is True

    async def test_timeout_does_not_touch_person_mood(self):
        from emotion.engine import emotion_engine
        from pipeline import processor
        from pipeline.perception import Perception
        from configs.service import config_service

        pid = "person_under_test_timeout"
        emotion_engine.person_moods.pop(pid, None)

        async def hang(*a, **kw):
            await asyncio.sleep(10)

        # Timeout now comes from config_service, not settings.AI_CALL_TIMEOUT.
        real_get = config_service.get

        def _fake_get(key, default=None):
            if key == "ai.call_timeout_seconds":
                return 0.05
            return real_get(key, default=default)

        with patch.object(processor, "call_ai_and_parse", new=hang), \
             patch.object(processor, "gather_context", new=AsyncMock(return_value=_fake_context())), \
             patch.object(config_service, "get", side_effect=_fake_get), \
             patch.object(processor, "persist_user_message",
                          new=AsyncMock(return_value=1)) as persist_q, \
             patch.object(processor, "persist_assistant_message",
                          new=AsyncMock(return_value=2)) as persist_a, \
             patch.object(processor, "emit_communication_event", new=AsyncMock()) as emit, \
             patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
            perception = Perception.from_text("hey", source="frontend", person_id=pid)
            output = await processor.process_message(perception)

        mood = emotion_engine.person_moods.get(pid)
        assert mood is None or mood.intensity < 0.05
        emit.assert_not_called()
        persist_q.assert_called_once()
        persist_a.assert_called_once()
        assert persist_a.call_args.kwargs["is_internal"] is True
        assert "reflechis" in output.text.lower() or "instant" in output.text.lower()


@pytest.mark.asyncio
class TestFailedTurnIsRecordedNotPretended:
    """A failed turn keeps the trace without claiming Mika answered.

    The flag is what carries the distinction, so it is the flag these tests
    assert: without it, "j'ai eu un petit bug" becomes a souvenir and comes
    back as something she said.
    """

    @pytest.fixture(autouse=True)
    def _no_db(self):
        """Cut the two ORM reads ``process_message`` does around the AI call.

        Neither is what these tests are about — persistence itself is mocked —
        but both are real queries, so without this the assertions depend on
        whether an earlier test left the config cache primed and the emotion
        engine hydrated. Stubbed, they hold in any order.
        """
        from configs.service import config_service
        from pipeline import processor

        with patch.object(config_service, "get", return_value=60), \
             patch.object(processor.emotion_engine, "ensure_person_loaded",
                          new=AsyncMock()), \
             patch.object(processor.emotion_engine, "_maybe_save_snapshot",
                          new=AsyncMock()):
            yield

    async def test_successful_turn_persists_a_real_reply(self):
        from emotion.types import Emotion, EmotionData
        from pipeline import processor
        from pipeline.perception import Perception

        ok = ("Salut !", EmotionData(emotion=Emotion.HAPPY, intensity=0.5), [])
        with patch.object(processor, "call_ai_and_parse", new=AsyncMock(return_value=ok)), \
             patch.object(processor, "gather_context", new=AsyncMock(return_value=_fake_context())), \
             patch.object(processor, "persist_user_message",
                          new=AsyncMock(return_value=1)) as persist_q, \
             patch.object(processor, "persist_assistant_message",
                          new=AsyncMock(return_value=2)) as persist_a, \
             patch.object(processor, "emit_communication_event", new=AsyncMock()), \
             patch.object(processor, "publish_turn_completed", new=AsyncMock()), \
             patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
            perception = Perception.from_text("hey", source="frontend", person_id="p_ok")
            await processor.process_message(perception)

        assert persist_a.call_args.kwargs["is_internal"] is False

    async def test_failed_turn_still_announces_nothing(self):
        """The trace is new; the silence around it is not. A fallback must
        still not wake the drives or the post-action audit."""
        from pipeline import processor
        from pipeline.perception import Perception

        with patch.object(processor, "call_ai_and_parse",
                          new=AsyncMock(side_effect=RuntimeError("llm broke"))), \
             patch.object(processor, "gather_context", new=AsyncMock(return_value=_fake_context())), \
             patch.object(processor, "persist_user_message",
                          new=AsyncMock(return_value=1)) as persist_q, \
             patch.object(processor, "persist_assistant_message",
                          new=AsyncMock(return_value=2)) as persist_a, \
             patch.object(processor, "emit_communication_event", new=AsyncMock()), \
             patch.object(processor, "publish_turn_completed", new=AsyncMock()) as announce, \
             patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
            perception = Perception.from_text("hey", source="frontend", person_id="p_ko")
            await processor.process_message(perception)

        persist_q.assert_called_once()
        persist_a.assert_called_once()
        announce.assert_not_called()

    async def test_persist_false_still_wins_over_a_failure(self):
        """``persist=False`` is a caller's explicit choice and outranks the
        new "record failures too" rule."""
        from pipeline import processor
        from pipeline.perception import Perception

        with patch.object(processor, "call_ai_and_parse",
                          new=AsyncMock(side_effect=RuntimeError("llm broke"))), \
             patch.object(processor, "gather_context", new=AsyncMock(return_value=_fake_context())), \
             patch.object(processor, "persist_user_message",
                          new=AsyncMock(return_value=None)) as persist_q, \
             patch.object(processor, "persist_assistant_message",
                          new=AsyncMock(return_value=None)) as persist_a, \
             patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
            perception = Perception.from_text("hey", source="frontend", person_id="p_np")
            await processor.process_message(perception, persist=False)

        # Both halves are skipped: the question is now written before the
        # AI call, so "don't persist" has to reach that side too.
        persist_q.assert_not_called()
        persist_a.assert_not_called()


@pytest.mark.asyncio
class TestInternalMessagesStayOutOfShortTerm:
    """The RAM buffer and the post-restart rehydration must agree.

    They didn't: ``_rehydrate_short_term`` excluded internal messages while
    ``add_message`` appended them, so the same conversation looked different
    before and after a restart. It matters more now that a failed turn stores
    its fallback — a run of timeouts would otherwise hand the model a history
    full of sentences Mika never said.
    """

    async def test_internal_message_is_not_appended(self):
        from memory.manager import memory_manager

        before = list(memory_manager.short_term)
        await memory_manager.add_message(
            "assistant", "Hmm, je reflechis plus lentement que prevu...",
            person_id="p_buf", is_internal=True,
        )
        assert list(memory_manager.short_term) == before

    async def test_normal_message_is_appended(self):
        from memory.manager import memory_manager

        before = len(memory_manager.short_term)
        await memory_manager.add_message("assistant", "Salut !", person_id="p_buf")
        assert len(memory_manager.short_term) == before + 1
        assert memory_manager.short_term[-1]["content"] == "Salut !"


class TestConversationToolAllowList:
    """``ai.conversation_tool_modules`` narrows what the model is handed.

    A tool declaration is prompt, re-sent on every turn of the tool loop; on
    a local model the nine modules outweigh the system prompt four to one.
    """

    def test_empty_means_every_module(self):
        from configs.service import config_service
        from pipeline import context as context_module

        with patch.object(config_service, "get", return_value=[]):
            assert context_module._conversation_tool_modules() == []

    def test_comma_separated_string_is_accepted(self):
        from configs.service import config_service
        from pipeline import context as context_module

        with patch.object(config_service, "get", return_value=" memory_tools , files "):
            assert context_module._conversation_tool_modules() == ["memory_tools", "files"]

    def test_unreadable_config_costs_tools_not_the_answer(self):
        from configs.service import config_service
        from pipeline import context as context_module

        with patch.object(config_service, "get", side_effect=RuntimeError("db gone")):
            assert context_module._conversation_tool_modules() == []


@pytest.mark.asyncio
class TestAllowListReachesGatherContext:
    """Asserted through ``gather_context`` itself, not by re-deriving the
    branch: the failure this guards against is the wiring, not the helper."""

    async def _gather(self):
        from pipeline import context as context_module

        with patch.object(context_module.memory_manager, "get_memory_context",
                          new=AsyncMock(return_value="")), \
             patch("pipeline.context._fetch_self_concept", new=AsyncMock(return_value="")), \
             patch("pipeline.context._fetch_person_context", new=AsyncMock(return_value="")):
            return await context_module.gather_context("hi", "some_user")

    async def test_allow_list_narrows(self):
        from pipeline import context as context_module

        with patch.object(context_module, "_conversation_tool_modules",
                          return_value=["memory_tools"]), \
             patch.object(context_module.module_manager, "get_tools_for_modules",
                          return_value=[_tool("narrowed")]) as narrowed, \
             patch.object(context_module.module_manager, "collect_tools",
                          return_value=[_tool("everything")]) as everything:
            ctx = await self._gather()

        assert [t.name for t in ctx.tools] == ["narrowed"]
        narrowed.assert_called_once_with(["memory_tools"])
        everything.assert_not_called()

    async def test_no_allow_list_keeps_every_tool(self):
        from pipeline import context as context_module

        with patch.object(context_module, "_conversation_tool_modules", return_value=[]), \
             patch.object(context_module.module_manager, "get_tools_for_modules",
                          return_value=[_tool("narrowed")]) as narrowed, \
             patch.object(context_module.module_manager, "collect_tools",
                          return_value=[_tool("everything")]):
            ctx = await self._gather()

        assert [t.name for t in ctx.tools] == ["everything"]
        narrowed.assert_not_called()


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


def _tool(name):
    """Minimal stand-in: gather_context only reads ``.name`` off a tool."""
    from types import SimpleNamespace
    return SimpleNamespace(name=name)


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
