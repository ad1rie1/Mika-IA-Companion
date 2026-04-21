"""Claude provider — uses the Anthropic Python SDK (anthropic.AsyncAnthropic).

For simple completions (no tools), we use the native Messages API directly.
The claude_agent_sdk is only used in client.py for MCP tool support.
"""

from __future__ import annotations

import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)


class ClaudeProvider:
    """Anthropic Claude via the official ``anthropic`` Python SDK.

    Supports both API key and OAuth token authentication.
    Uses ``anthropic.AsyncAnthropic.messages.create()`` for completions.
    """

    def __init__(self):
        from anthropic import AsyncAnthropic
        from configs.service import config_service

        api_key = config_service.get("ai.claude.api_key", default="") or None
        auth_token = config_service.get("ai.claude.oauth_token", default="") or None

        if not api_key and not auth_token:
            raise ValueError(
                "ClaudeProvider nécessite ai.claude.api_key ou ai.claude.oauth_token "
                "(éditeur Configuration > IA · Providers)."
            )

        # The anthropic SDK supports both api_key and auth_token kwargs.
        # auth_token is used for OAuth-based access (Claude.ai sessions).
        if auth_token:
            # claude_agent_sdk also needs this env var for chat_with_tools()
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = auth_token
            self._client = AsyncAnthropic(auth_token=auth_token)
        else:
            self._client = AsyncAnthropic(api_key=api_key)

        logger.info("ClaudeProvider initialisé (auth=%s)", "oauth" if auth_token else "api_key")

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        attachments: list | None = None,
    ) -> str:
        # Build content: image blocks first, then text
        if attachments:
            content: list | str = []
            for att in attachments:
                if att.category == "image":
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": att.media_type,
                            "data": att.data,
                        },
                    })
            content.append({"type": "text", "text": user_prompt})
        else:
            content = user_prompt

        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": content}],
        )

        # Surface native token usage to the quota tracker. No-op when this
        # call wasn't routed through AIRouter (e.g. ad-hoc provider use).
        try:
            from ai.quota import set_usage
            usage = getattr(response, "usage", None)
            if usage is not None:
                set_usage(
                    input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                )
        except Exception:
            pass

        parts = []
        for block in response.content:
            if block.type == "text":
                parts.append(block.text)

        return "".join(parts)

    async def list_models(self) -> list[dict]:
        """List Claude models reachable with the configured credentials."""
        page = await self._client.models.list(limit=100)
        out = []
        for m in page.data:
            out.append({
                "id": m.id,
                "label": getattr(m, "display_name", None) or m.id,
            })
        return out

    async def test(self) -> dict:
        from ai.providers import default_test
        return await default_test(self)

    # ── MCP tool loop (Claude-only capability) ────────────────────
    async def complete_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        *,
        mcp_server=None,
        tool_names: list[str] | None = None,
        max_turns: int = 10,
    ) -> tuple[str, list[str]]:
        """MCP-based completion with tool support.

        Uses ``claude_agent_sdk.query`` (not the plain anthropic SDK)
        because the tool loop needs the Agent SDK's streaming
        bidirectional control-protocol wire. Only Claude exposes this —
        other providers (OpenAI, Gemini, GLM, Ollama) don't have an
        equivalent MCP-native integration, which is why this method
        lives on ``ClaudeProvider`` rather than on the generic protocol.

        Returns ``(raw_text, list_of_tool_names_called)``.
        """
        from claude_agent_sdk import (
            AssistantMessage,
            TextBlock,
            ToolUseBlock,
            query,
        )
        from claude_agent_sdk.types import ClaudeAgentOptions

        mcp_servers: dict = {}
        allowed_tools: list[str] = []
        if mcp_server is not None:
            mcp_servers["vtuber_modules"] = mcp_server
            allowed_tools = [
                f"mcp__vtuber_modules__{name}" for name in (tool_names or [])
            ]

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            model=model,
            max_turns=max_turns,
            mcp_servers=mcp_servers,
            allowed_tools=allowed_tools,
            permission_mode="bypassPermissions",
        )

        async def _prompt_stream():
            yield {
                "type": "user",
                "session_id": "",
                "message": {"role": "user", "content": user_prompt},
                "parent_tool_use_id": None,
            }

        response_stream = query(prompt=_prompt_stream(), options=options)

        raw_text = ""
        tool_calls: list[str] = []
        async for msg in response_stream:
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        raw_text += block.text
                    elif isinstance(block, ToolUseBlock):
                        logger.info(
                            "Claude called tool: %s (input=%s)",
                            block.name, str(block.input)[:200],
                        )
                        tool_calls.append(block.name)
        if tool_calls:
            logger.info("Tools used in this turn: %s", tool_calls)
        return raw_text, tool_calls
