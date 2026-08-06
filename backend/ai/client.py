"""AI client — pure call layer.

Simple completion via the router (any provider).
Tool-enabled completion is delegated to ai.tool_client (Claude-only, MCP).

This module carries **no** SDK-specific setup — every credential /
environment concern (including the ``CLAUDE_CODE_OAUTH_TOKEN`` the Claude
Agent SDK picks up, passé par ``ClaudeAgentOptions.env`` et non par
``os.environ``) is handled inside ``ClaudeProvider``. The client is a
thin facade.
"""

import logging

from ai.router import AIRole, ai_router
from ai.tool_client import complete_with_tools as _complete_with_tools

logger = logging.getLogger(__name__)


class AIClient:
    # -- Simple completion (no tools) ------------------------------------------

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        role: AIRole = AIRole.CONVERSATION,
        attachments: list | None = None,
    ) -> str:
        """Send a ready-made prompt to the configured AI provider.

        attachments: list[MediaAttachment] optionnel — utilisé par files_analyze_image.
        Returns raw text response (caller handles emotion extraction etc.).
        """
        return await ai_router.complete(
            role=role,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            attachments=attachments,
        )

    # -- Completion with tools (MCP) -------------------------------------------

    async def complete_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list,
    ) -> tuple[str, list[str]]:
        """Tool-enabled completion.

        ``tools`` is a list of generic ``ModuleTool`` objects. The
        provider (resolved via the CONVERSATION_TOOLS role) converts
        them to its native tool format — MCP for Claude, function
        calling for others.

        Returns ``(raw_text, tool_names_called)``.
        """
        return await _complete_with_tools(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            tools=tools,
        )


ai_client = AIClient()
