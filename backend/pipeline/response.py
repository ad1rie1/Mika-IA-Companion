"""Response parsing — extract emotion and clean text from AI output."""

from ai.client import ai_client
from emotion.types import EmotionData, extract_emotion
from pipeline.context import ConversationContext
from pipeline.prompt import build_system_prompt, format_conversation


async def call_ai_and_parse(
    context: ConversationContext, message: str
) -> tuple[str, EmotionData, list[str]]:
    """Build prompt, call AI, extract emotion from response.

    Returns (clean_text, emotion_data, tool_calls).
    Les fichiers uploadés sont accessibles via les outils files_* du FilesModule.
    """
    system = build_system_prompt(
        emotion_context=context.emotion_context,
        memory_context=context.memory_context,
        module_context=context.module_context,
        self_concept=context.self_concept,
        person_context=context.person_context,
        circadian_context=context.circadian_context,
        fatigue_fog=context.fatigue_fog,
        rumination_context=context.rumination_context,
        user_mood_hint=context.user_mood_hint,
        dream_context=context.dream_context,
        project_context=context.project_context,
        project_suppresses_emotion=context.project_suppresses_emotion,
    )
    user_prompt = format_conversation(message, context.history)

    if context.tools:
        raw_text, tool_calls = await ai_client.complete_with_tools(
            system_prompt=system,
            user_prompt=user_prompt,
            tools=context.tools,
        )
    else:
        raw_text = await ai_client.complete(
            system_prompt=system,
            user_prompt=user_prompt,
        )
        tool_calls = []

    clean_text, emotion_data = extract_emotion(raw_text)
    return clean_text, emotion_data, tool_calls
