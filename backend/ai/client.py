import logging
import os
from collections.abc import AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
    query,
)
from claude_agent_sdk.types import ClaudeAgentOptions
from django.conf import settings

from ai.emotion_types import EmotionData, extract_emotion
from config.personality import personality

logger = logging.getLogger(__name__)


class ClaudeClient:
    def __init__(self):
        self.system_prompt = personality.to_system_prompt()
        # Set the token from Django settings for claude_agent_sdk
        # SDK looks for CLAUDE_CODE_OAUTH_TOKEN for OAuth, or ANTHROPIC_API_KEY for API key
        if settings.CLAUDE_OAUTH_TOKEN:
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = settings.CLAUDE_OAUTH_TOKEN
        elif settings.ANTHROPIC_API_KEY:
            os.environ["ANTHROPIC_API_KEY"] = settings.ANTHROPIC_API_KEY
        else:
            raise ValueError("Either CLAUDE_OAUTH_TOKEN or ANTHROPIC_API_KEY must be set")

    # ── Shared helpers ────────────────────────────────────────────

    def _build_system_prompt(
        self,
        emotion_context: str = "",
        memory_context: str = "",
        module_context: str = "",
    ) -> str:
        system = self.system_prompt
        if module_context:
            system += (
                "\n\n--- CONTEXTE MODULES ---\n"
                + module_context
                + "\n--- FIN CONTEXTE MODULES ---"
            )
        if emotion_context:
            system += (
                "\n\n--- TON ETAT EMOTIONNEL ACTUEL ---\n"
                + emotion_context
                + "\n--- FIN ETAT EMOTIONNEL ---"
            )
        if memory_context:
            system += "\n\n" + memory_context
        return system

    def _build_prompt(
        self,
        message: str,
        conversation_history: list[dict] | None = None,
    ) -> str:
        full_prompt = ""
        if conversation_history:
            for msg in conversation_history:
                role = msg["role"]
                content = msg["content"]
                if role == "user":
                    full_prompt += f"User: {content}\n\n"
                elif role == "assistant":
                    full_prompt += f"Assistant: {content}\n\n"
        full_prompt += f"User: {message}"
        return full_prompt

    # ── Simple chat (no tools) ────────────────────────────────────

    async def chat(
        self,
        message: str,
        conversation_history: list[dict] | None = None,
        memory_context: str = "",
        emotion_context: str = "",
    ) -> tuple[str, EmotionData]:
        """Send a message to Claude and return (clean_response, EmotionData).
        Single turn, no tools."""
        system = self._build_system_prompt(emotion_context, memory_context)
        full_prompt = self._build_prompt(message, conversation_history)

        options = ClaudeAgentOptions(
            system_prompt=system,
            model=settings.CLAUDE_MODEL,
            max_turns=1,
        )

        response_stream = query(prompt=full_prompt, options=options)

        raw_text = ""
        async for msg in response_stream:
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        raw_text += block.text

        clean_text, emotion_data = extract_emotion(raw_text)
        return clean_text, emotion_data

    # ── Chat with tools (MCP) ─────────────────────────────────────

    @staticmethod
    async def _prompt_stream(text: str) -> AsyncIterator[dict]:
        """Wrap a prompt string as an async iterable of SDK messages.

        When MCP servers are present, the SDK must receive the prompt as
        an AsyncIterable so that ``stream_input()`` keeps stdin open for
        bidirectional control-protocol communication (MCP tool calls).
        Passing a plain ``str`` causes the SDK to close stdin immediately
        after sending the user message, which breaks MCP.
        """
        yield {
            "type": "user",
            "session_id": "",
            "message": {"role": "user", "content": text},
            "parent_tool_use_id": None,
        }

    async def chat_with_tools(
        self,
        message: str,
        conversation_history: list[dict] | None = None,
        memory_context: str = "",
        emotion_context: str = "",
        module_context: str = "",
        mcp_server=None,
        tool_names: list[str] | None = None,
    ) -> tuple[str, EmotionData, list[str]]:
        """Chat with tool support via MCP server.

        The SDK handles the tool_use → tool_result loop internally
        when max_turns > 1.

        Returns (clean_text, emotion_data, list_of_tool_names_called).
        """
        system = self._build_system_prompt(
            emotion_context, memory_context, module_context
        )
        full_prompt = self._build_prompt(message, conversation_history)

        mcp_servers = {}
        allowed_tools = []
        if mcp_server:
            mcp_servers["vtuber_modules"] = mcp_server
            # MCP tool names are prefixed mcp__servername__toolname by the CLI
            allowed_tools = [
                f"mcp__vtuber_modules__{name}" for name in (tool_names or [])
            ]

        options = ClaudeAgentOptions(
            system_prompt=system,
            model=settings.CLAUDE_MODEL,
            max_turns=10,
            mcp_servers=mcp_servers,
            allowed_tools=allowed_tools,
            permission_mode="bypassPermissions",
        )

        # Pass prompt as AsyncIterable to keep stdin open for MCP
        prompt_stream = self._prompt_stream(full_prompt)
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

        clean_text, emotion_data = extract_emotion(raw_text)
        return clean_text, emotion_data, tool_calls_made


claude_client = ClaudeClient()
