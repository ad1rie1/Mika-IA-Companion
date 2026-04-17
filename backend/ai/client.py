"""AI client — pure call layer.

Simple completion via the router (any provider).
Tool-enabled completion is delegated to ai.tool_client (Claude-only, MCP).
"""

import logging
import os

from django.conf import settings

from ai.router import AIRole, ai_router
from ai.tool_client import complete_with_tools as _complete_with_tools

logger = logging.getLogger(__name__)


class AIClient:
    def __init__(self):
        from configs.service import config_service
        # Ensure env vars are set for claude_agent_sdk (used by tool_client)
        oauth = config_service.get("ai.claude.oauth_token", default="")
        api_key = config_service.get("ai.claude.api_key", default="")
        if oauth:
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = oauth
        elif api_key:
            os.environ["ANTHROPIC_API_KEY"] = api_key

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
        mcp_server=None,
        tool_names: list[str] | None = None,
    ) -> tuple[str, list[str]]:
        """Completion with tool support via MCP server.

        Delegates to ai.tool_client which handles the full MCP flow.
        Returns (raw_text, list_of_tool_names_called).
        """
        return await _complete_with_tools(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            mcp_server=mcp_server,
            tool_names=tool_names,
        )


ai_client = AIClient()
