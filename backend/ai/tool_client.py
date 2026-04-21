"""AI tool client — thin dispatcher for tool-enabled completions.

Every provider implements ``complete_with_tools(tools=[ModuleTool])`` on
itself (Claude converts to MCP internally; the others currently raise
``NotImplementedError`` until their native function-calling is wired).

This module only resolves the role and forwards — no SDK-specific code.
"""

from __future__ import annotations

import logging

from ai.router import AIRole, ai_router

logger = logging.getLogger(__name__)


async def complete_with_tools(
    system_prompt: str,
    user_prompt: str,
    tools: list,
) -> tuple[str, list[str]]:
    """Route a tool-enabled completion to the CONVERSATION_TOOLS provider."""
    provider_name, model, _temp, internal = ai_router.resolve(AIRole.CONVERSATION_TOOLS)
    provider = ai_router.get_provider(AIRole.CONVERSATION_TOOLS)
    logger.debug(
        "complete_with_tools: role=conversation_tools internal=%s provider=%s model=%s tools=%d",
        internal, provider_name, model, len(tools or []),
    )
    return await provider.complete_with_tools(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        tools=tools or [],
    )
