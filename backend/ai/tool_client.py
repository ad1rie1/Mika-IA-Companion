"""AI tool client — thin dispatcher for tool-enabled completions.

Every provider implements ``complete_with_tools(tools=[ModuleTool])`` on
itself:
  - Claude → MCP loop via claude_agent_sdk
  - OpenAI / GLM → OpenAI-compat ``tools=[...]`` ping/pong loop
  - Ollama → native ``tools=[...]`` loop (SDK ≥ 0.3, tool-capable model)
  - Gemini → ``types.Tool(function_declarations=[...])`` loop

This module only forwards to the router — no SDK-specific code, et surtout
pas d'appel direct au provider : c'est ``AIRouter`` qui porte le quota, la
température du modèle déclaré et la trace unifiée.
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
    logger.debug("complete_with_tools: role=conversation_tools tools=%d", len(tools or []))
    return await ai_router.complete_with_tools(
        role=AIRole.CONVERSATION_TOOLS,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        tools=tools or [],
    )
