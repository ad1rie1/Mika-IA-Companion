"""Context assembly — gather all contextual information for a conversation turn.

Collects memory, emotion, module context, and conversation history
into a single structure ready for the AI call.
"""

import logging
from dataclasses import dataclass

from emotion.engine import emotion_engine
from memory.manager import memory_manager

logger = logging.getLogger(__name__)


@dataclass
class ConversationContext:
    """All context assembled for a single conversation turn."""
    memory_context: str
    emotion_context: str
    module_context: str
    history: list[dict]
    mcp_server: object | None  # SdkMcpServer or None
    tool_names: list[str]
    attachments: list = None  # list[MediaAttachment] | None


async def gather_context(
    message: str,
    person_id: str,
    include_tools: bool = True,
    attachments: list | None = None,
) -> ConversationContext:
    """Assemble all context needed for an AI conversation turn.

    Args:
        message: The user/trigger message (used for memory retrieval).
        person_id: Who is talking (for emotion + memory boosting).
        include_tools: Whether to include MCP tools from modules.
    """
    from modules.manager import module_manager

    # Memory context (graceful degradation)
    try:
        memory_context = await memory_manager.get_memory_context(
            message, person_id=person_id
        )
    except Exception:
        logger.warning("Memory retrieval failed, continuing without context")
        memory_context = ""

    # Emotion context for this person
    emotion_context = emotion_engine.get_emotion_context(person_id)

    # Module context for system prompt
    module_context = module_manager.collect_context()

    # Conversation history
    history = memory_manager.get_conversation_context()

    # Tools
    mcp_server = None
    tool_names = []
    if include_tools:
        mcp_server = module_manager.get_mcp_server()
        tool_names = module_manager.get_tool_names()

    return ConversationContext(
        memory_context=memory_context,
        emotion_context=emotion_context,
        module_context=module_context,
        history=history,
        mcp_server=mcp_server,
        tool_names=tool_names,
        attachments=attachments or [],
    )
