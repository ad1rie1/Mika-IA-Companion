"""AI tool client — MCP-based completion with tool support.

Handles multi-turn tool_use/tool_result loops via the Claude Agent SDK.
Separated from the simple completion client because the MCP flow is
substantially different (streaming, bidirectional, multi-turn).
"""

import logging
from collections.abc import AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
    query,
)
from claude_agent_sdk.types import ClaudeAgentOptions

from ai.router import AIRole, ai_router

logger = logging.getLogger(__name__)


async def _prompt_stream(text: str) -> AsyncIterator[dict]:
    """Wrap a prompt string as an async iterable of SDK messages.

    When MCP servers are present, the SDK must receive the prompt as
    an AsyncIterable so that ``stream_input()`` keeps stdin open for
    bidirectional control-protocol communication (MCP tool calls).
    """
    yield {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": text},
        "parent_tool_use_id": None,
    }


async def complete_with_tools(
    system_prompt: str,
    user_prompt: str,
    mcp_server=None,
    tool_names: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Completion with tool support via MCP server.

    The SDK handles the tool_use -> tool_result loop internally
    when max_turns > 1.

    Returns (raw_text, list_of_tool_names_called).
    """
    mcp_servers = {}
    allowed_tools = []
    if mcp_server:
        mcp_servers["vtuber_modules"] = mcp_server
        allowed_tools = [
            f"mcp__vtuber_modules__{name}" for name in (tool_names or [])
        ]

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=ai_router.get_model(AIRole.CONVERSATION_TOOLS),
        max_turns=10,
        mcp_servers=mcp_servers,
        allowed_tools=allowed_tools,
        permission_mode="bypassPermissions",
    )

    prompt_stream = _prompt_stream(user_prompt)
    response_stream = query(prompt=prompt_stream, options=options)

    raw_text = ""
    tool_calls_made: list[str] = []

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
                    tool_calls_made.append(block.name)

    if tool_calls_made:
        logger.info("Tools used in this turn: %s", tool_calls_made)

    return raw_text, tool_calls_made
