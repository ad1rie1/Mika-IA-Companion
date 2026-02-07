import os
from django.conf import settings
from claude_agent_sdk import query, AssistantMessage, TextBlock
from claude_agent_sdk.types import ClaudeAgentOptions

from ai.emotion_types import EmotionData, extract_emotion
from config.personality import personality


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

    async def chat(
        self,
        message: str,
        conversation_history: list[dict] | None = None,
        memory_context: str = "",
        emotion_context: str = "",
    ) -> tuple[str, EmotionData]:
        """Send a message to Claude and return (clean_response, EmotionData)."""
        # Build the full system prompt
        system = self.system_prompt
        if emotion_context:
            system += (
                "\n\n--- TON ETAT EMOTIONNEL ACTUEL ---\n"
                + emotion_context
                + "\n--- FIN ETAT EMOTIONNEL ---"
            )
        if memory_context:
            system += "\n\n" + memory_context

        # Build full prompt with conversation history
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

        # Use claude_agent_sdk query with options
        options = ClaudeAgentOptions(
            system_prompt=system,
            model=settings.CLAUDE_MODEL,
            max_turns=1,  # Single turn conversation
        )

        response_stream = query(prompt=full_prompt, options=options)

        # Extract text from response
        raw_text = ""
        async for msg in response_stream:
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        raw_text += block.text

        clean_text, emotion_data = extract_emotion(raw_text)
        return clean_text, emotion_data


claude_client = ClaudeClient()
