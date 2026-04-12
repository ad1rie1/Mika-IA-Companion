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

        api_key = settings.ANTHROPIC_API_KEY or None
        auth_token = settings.CLAUDE_OAUTH_TOKEN or None

        if not api_key and not auth_token:
            raise ValueError(
                "ClaudeProvider nécessite ANTHROPIC_API_KEY ou CLAUDE_OAUTH_TOKEN dans .env"
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
    ) -> str:
        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
        )

        # Extract text from content blocks
        parts = []
        for block in response.content:
            if block.type == "text":
                parts.append(block.text)

        return "".join(parts)
