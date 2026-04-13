"""Tests for pipeline context gathering."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pipeline.context import ConversationContext, gather_context


class TestConversationContext:

    def test_all_fields(self):
        ctx = ConversationContext(
            memory_context="mem",
            emotion_context="happy",
            module_context="3 emails",
            history=[{"role": "user", "content": "hi"}],
            mcp_server=None,
            tool_names=["send_email"],
        )
        assert ctx.memory_context == "mem"
        assert ctx.emotion_context == "happy"
        assert ctx.module_context == "3 emails"
        assert len(ctx.history) == 1
        assert ctx.mcp_server is None
        assert ctx.tool_names == ["send_email"]


class TestGatherContext:

    def _patch_deps(self, memory_ctx="mem", emotion_ctx="happy", module_ctx="mod", history=None):
        mock_mem = MagicMock()
        mock_mem.get_memory_context = AsyncMock(return_value=memory_ctx)
        mock_mem.get_conversation_context = MagicMock(return_value=history or [])
        mock_emo = MagicMock()
        mock_emo.get_emotion_context = MagicMock(return_value=emotion_ctx)
        mock_mod = MagicMock()
        mock_mod.collect_context = MagicMock(return_value=module_ctx)
        mock_mod.get_mcp_server = MagicMock(return_value=None)
        mock_mod.get_tool_names = MagicMock(return_value=[])
        return mock_mem, mock_emo, mock_mod

    @pytest.mark.asyncio
    async def test_assembles_all_parts(self):
        mock_mem, mock_emo, mock_mod = self._patch_deps(
            memory_ctx="souvenir", emotion_ctx="excited", module_ctx="emails"
        )
        with patch("pipeline.context.memory_manager", mock_mem), \
             patch("pipeline.context.emotion_engine", mock_emo), \
             patch("pipeline.context.module_manager", mock_mod):
            ctx = await gather_context("test", person_id="u1")

        assert ctx.memory_context == "souvenir"
        assert ctx.emotion_context == "excited"
        assert ctx.module_context == "emails"

    @pytest.mark.asyncio
    async def test_memory_failure_returns_empty_string(self):
        mock_mem, mock_emo, mock_mod = self._patch_deps()
        mock_mem.get_memory_context = AsyncMock(side_effect=Exception("DB down"))

        with patch("pipeline.context.memory_manager", mock_mem), \
             patch("pipeline.context.emotion_engine", mock_emo), \
             patch("pipeline.context.module_manager", mock_mod):
            ctx = await gather_context("test", person_id="u1")

        assert ctx.memory_context == ""

    @pytest.mark.asyncio
    async def test_include_tools_false_skips_mcp(self):
        mock_mem, mock_emo, mock_mod = self._patch_deps()
        mock_mod.get_mcp_server = MagicMock(return_value=MagicMock())
        mock_mod.get_tool_names = MagicMock(return_value=["tool"])

        with patch("pipeline.context.memory_manager", mock_mem), \
             patch("pipeline.context.emotion_engine", mock_emo), \
             patch("pipeline.context.module_manager", mock_mod):
            ctx = await gather_context("test", person_id="u1", include_tools=False)

        assert ctx.mcp_server is None
        assert ctx.tool_names == []
        mock_mod.get_mcp_server.assert_not_called()

    @pytest.mark.asyncio
    async def test_include_tools_true_calls_mcp(self):
        mock_mem, mock_emo, mock_mod = self._patch_deps()
        fake_mcp = MagicMock()
        mock_mod.get_mcp_server = MagicMock(return_value=fake_mcp)
        mock_mod.get_tool_names = MagicMock(return_value=["send_email"])

        with patch("pipeline.context.memory_manager", mock_mem), \
             patch("pipeline.context.emotion_engine", mock_emo), \
             patch("pipeline.context.module_manager", mock_mod):
            ctx = await gather_context("test", person_id="u1", include_tools=True)

        assert ctx.mcp_server is fake_mcp
        assert "send_email" in ctx.tool_names
