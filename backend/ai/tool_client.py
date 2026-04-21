"""AI tool client — MCP-based completion with tool support.

Thin wrapper around the provider's native tool-loop capability. Only
``ClaudeProvider`` implements ``complete_with_tools`` today because MCP
is a Claude-ecosystem feature; if the ``conversation_tools`` role is
mapped to a non-Claude declared model we raise a clear error instead of
silently degrading.

All SDK / wire-protocol details live in the provider itself — see
``ai/providers/claude.py::complete_with_tools``. This module only
dispatches.
"""

from __future__ import annotations

import logging

from ai.router import AIRole, ai_router

logger = logging.getLogger(__name__)


async def complete_with_tools(
    system_prompt: str,
    user_prompt: str,
    mcp_server=None,
    tool_names: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Route a tool-enabled completion to the provider of the conversation_tools role."""
    provider_name, model, _temp, internal = ai_router.resolve(AIRole.CONVERSATION_TOOLS)
    provider = ai_router.get_provider(AIRole.CONVERSATION_TOOLS)

    if not hasattr(provider, "complete_with_tools"):
        raise RuntimeError(
            f"Le rôle 'conversation_tools' pointe sur '{internal}' "
            f"(provider={provider_name}), mais ce provider ne supporte pas "
            "les outils MCP. Seul Claude les supporte actuellement."
        )

    return await provider.complete_with_tools(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        mcp_server=mcp_server,
        tool_names=tool_names,
    )
