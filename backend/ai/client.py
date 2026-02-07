import anthropic
from django.conf import settings

from ai.emotions import Emotion, extract_emotion
from config.personality import personality


class ClaudeClient:
    def __init__(self):
        self.client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.system_prompt = personality.to_system_prompt()

    async def chat(
        self,
        message: str,
        conversation_history: list[dict] | None = None,
        memory_context: str = "",
    ) -> tuple[str, Emotion]:
        """Send a message to Claude and return (clean_response, emotion)."""
        messages = []
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": message})

        system = self.system_prompt
        if memory_context:
            system += "\n\n" + memory_context

        response = await self.client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=1024,
            system=system,
            messages=messages,
        )

        raw_text = response.content[0].text
        clean_text, emotion = extract_emotion(raw_text)
        return clean_text, emotion


claude_client = ClaudeClient()
