import anthropic

from core.ai.emotion_engine import Emotion, extract_emotion
from core.config import personality, settings


class ClaudeClient:
    def __init__(self):
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.system_prompt = personality.to_system_prompt()

    async def chat(
        self, message: str, conversation_history: list[dict] | None = None
    ) -> tuple[str, Emotion]:
        """Send a message to Claude and return (clean_response, emotion)."""
        messages = []
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": message})

        response = await self.client.messages.create(
            model=settings.claude_model,
            max_tokens=1024,
            system=self.system_prompt,
            messages=messages,
        )

        raw_text = response.content[0].text
        clean_text, emotion = extract_emotion(raw_text)
        return clean_text, emotion
