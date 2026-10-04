"""AI client — pure call layer.

Simple completion and structured turns via the router (any provider).

This module carries **no** SDK-specific setup — every credential concern
(la clé d'API Anthropic, lue dans la configuration et passée au client
``AsyncAnthropic``) is handled inside ``ClaudeProvider``. The client is a
thin facade.
"""

import logging

from old.backend.ai.chat import ChatPrompt
from old.backend.ai.router import AIRole, ai_router

logger = logging.getLogger(__name__)


class AIClient:
    # -- Structured conversation turn (the pipeline's path) ---------------------

    async def chat(
        self,
        prompt: ChatPrompt,
        role: AIRole = AIRole.CONVERSATION,
    ) -> str:
        """Send a structured conversation turn to the configured provider.

        Chat-native providers cache the stable prefix and receive the
        history as real messages; the others get the legacy flattened pair.
        """
        return await ai_router.chat(role=role, prompt=prompt)

    async def chat_with_tools(
        self,
        prompt: ChatPrompt,
        tools: list,
    ) -> tuple[str, list[str]]:
        """Tool-enabled structured turn (CONVERSATION_TOOLS role).

        Returns ``(raw_text, tool_names_called)``.
        """
        return await ai_router.chat_with_tools(
            role=AIRole.CONVERSATION_TOOLS,
            prompt=prompt,
            tools=tools or [],
        )

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


ai_client = AIClient()
