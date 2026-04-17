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
