"""Tests for pipeline context gathering.

`gather_context()` assembles memory + emotion + drives + modules + self
concept + per-person context into a single ConversationContext. The
function is pure orchestration: all DB/IO is delegated to singletons we
mock here.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
            self_concept="Je suis",
            person_context="C'est Alice",
        )
        assert ctx.memory_context == "mem"
        assert ctx.emotion_context == "happy"
        assert ctx.module_context == "3 emails"
        assert len(ctx.history) == 1
        assert ctx.mcp_server is None
        assert ctx.tool_names == ["send_email"]
        assert ctx.self_concept == "Je suis"
        assert ctx.person_context == "C'est Alice"

    def test_self_concept_and_person_context_default_empty(self):
        ctx = ConversationContext(
            memory_context="", emotion_context="", module_context="",
            history=[], mcp_server=None, tool_names=[],
        )
        assert ctx.self_concept == ""
        assert ctx.person_context == ""


class TestGatherContext:

    def _patch_deps(
        self,
        *,
        memory_ctx: str = "",
        global_mood: str = "",
        drive_ctx: str = "",
        module_ctx: str = "",
        history: list | None = None,
    ):
        mock_mem = MagicMock()
        mock_mem.get_memory_context = AsyncMock(return_value=memory_ctx)
        mock_mem.get_conversation_context = MagicMock(return_value=history or [])

        mock_emo = MagicMock()
        mock_emo.get_global_mood_context = MagicMock(return_value=global_mood)

        mock_drive = MagicMock()
        mock_drive.get_context = MagicMock(return_value=drive_ctx)

        mock_mod = MagicMock()
        mock_mod.collect_context = MagicMock(return_value=module_ctx)
        mock_mod.get_mcp_server = MagicMock(return_value=None)
        mock_mod.get_tool_names = MagicMock(return_value=[])

        return mock_mem, mock_emo, mock_drive, mock_mod

    def _apply_patches(self, mock_mem, mock_emo, mock_drive, mock_mod):
        """Use ExitStack-like context stacking via nested `with`."""
        return [
            patch("pipeline.context.memory_manager", mock_mem),
            patch("pipeline.context.emotion_engine", mock_emo),
            patch("pipeline.context.drive_engine", mock_drive),
            patch("pipeline.context.module_manager", mock_mod),
            # Self-concept + person-context fetches are DB calls; stub them.
            patch("pipeline.context._fetch_self_concept",
                  new_callable=AsyncMock, return_value=""),
            patch("pipeline.context._fetch_person_context",
                  new_callable=AsyncMock, return_value=""),
        ]

    @pytest.mark.asyncio
    async def test_assembles_all_parts(self):
        mocks = self._patch_deps(
            memory_ctx="souvenir",
            global_mood="Tu te sens excitee",
            drive_ctx="Tu as envie de parler",
            module_ctx="emails",
        )
        patches = self._apply_patches(*mocks)
        for p in patches:
            p.start()
        try:
            ctx = await gather_context("test", person_id="u1")
        finally:
            for p in reversed(patches):
                p.stop()

        assert ctx.memory_context == "souvenir"
        assert "excitee" in ctx.emotion_context
        assert "envie de parler" in ctx.emotion_context  # drives appended
        assert ctx.module_context == "emails"

    @pytest.mark.asyncio
    async def test_memory_failure_returns_empty_string(self):
        mock_mem, mock_emo, mock_drive, mock_mod = self._patch_deps()
        mock_mem.get_memory_context = AsyncMock(side_effect=Exception("DB down"))

        patches = self._apply_patches(mock_mem, mock_emo, mock_drive, mock_mod)
        for p in patches:
            p.start()
        try:
            ctx = await gather_context("test", person_id="u1")
        finally:
            for p in reversed(patches):
                p.stop()

        assert ctx.memory_context == ""

    @pytest.mark.asyncio
    async def test_include_tools_false_skips_mcp(self):
        mocks = self._patch_deps()
        mock_mod = mocks[3]
        mock_mod.get_mcp_server = MagicMock(return_value=MagicMock())
        mock_mod.get_tool_names = MagicMock(return_value=["tool"])

        patches = self._apply_patches(*mocks)
        for p in patches:
            p.start()
        try:
            ctx = await gather_context("test", person_id="u1", include_tools=False)
        finally:
            for p in reversed(patches):
                p.stop()

        assert ctx.mcp_server is None
        assert ctx.tool_names == []
        mock_mod.get_mcp_server.assert_not_called()

    @pytest.mark.asyncio
    async def test_include_tools_true_calls_mcp(self):
        mocks = self._patch_deps()
        mock_mod = mocks[3]
        fake_mcp = MagicMock()
        mock_mod.get_mcp_server = MagicMock(return_value=fake_mcp)
        mock_mod.get_tool_names = MagicMock(return_value=["send_email"])

        patches = self._apply_patches(*mocks)
        for p in patches:
            p.start()
        try:
            ctx = await gather_context("test", person_id="u1", include_tools=True)
        finally:
            for p in reversed(patches):
                p.stop()

        assert ctx.mcp_server is fake_mcp
        assert "send_email" in ctx.tool_names
