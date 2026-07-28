"""AI tool client — thin dispatcher for tool-enabled completions.

Every provider implements ``complete_with_tools(tools=[ModuleTool])`` on
itself:
  - Claude → MCP loop via claude_agent_sdk
  - OpenAI / GLM → OpenAI-compat ``tools=[...]`` ping/pong loop
  - Ollama → native ``tools=[...]`` loop (SDK ≥ 0.3, tool-capable model)
  - Gemini → ``types.Tool(function_declarations=[...])`` loop

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
    # provider_by_name rather than get_provider(role): the role is already
    # resolved above, and resolving it twice re-reads ai.models from the DB.
    provider = ai_router.provider_by_name(provider_name)
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
