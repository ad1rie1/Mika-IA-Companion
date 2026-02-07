import anthropic
from django.conf import settings

from ai.emotion_types import EmotionData, extract_emotion
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
        emotion_context: str = "",
    ) -> tuple[str, EmotionData]:
        """Send a message to Claude and return (clean_response, EmotionData)."""
        messages = []
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": message})

        system = self.system_prompt
        if emotion_context:
            system += (
                "\n\n--- TON ETAT EMOTIONNEL ACTUEL ---\n"
                + emotion_context
                + "\n--- FIN ETAT EMOTIONNEL ---"
            )
        if memory_context:
            system += "\n\n" + memory_context

        response = await self.client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=1024,
            system=system,
            messages=messages,
        )

        raw_text = response.content[0].text
        clean_text, emotion_data = extract_emotion(raw_text)
        return clean_text, emotion_data


claude_client = ClaudeClient()
