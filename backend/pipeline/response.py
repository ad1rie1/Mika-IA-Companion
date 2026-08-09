"""Response parsing — extract emotion and clean text from AI output."""

from ai.client import ai_client
from emotion.types import EmotionData, extract_emotion
from pipeline.context import ConversationContext
from pipeline.prompt import build_chat_prompt


async def call_ai_and_parse(
    context: ConversationContext, message: str
) -> tuple[str, EmotionData | None, list[str]]:
    """Build prompt, call AI, extract emotion from response.

    Returns (clean_text, emotion_data, tool_calls), where ``emotion_data`` is
    ``None`` when the turn declared nothing usable — no tag at all, or a name
    outside the 29. The caller must not turn that into a neutral: NEUTRAL is
    the origin of PAD space, so applying it as an impulse pulls whatever the
    person just provoked back toward zero.
    Les fichiers uploadés sont accessibles via les outils files_* du FilesModule.

    Passes the ``ConversationContext`` object itself to the prompt builder —
    never a transcription of its fields. The structured ``ChatPrompt`` keeps
    the cacheable prefix, the per-turn state and the real message turns
    apart; each provider renders it in its native optimal form.
    """
    prompt = build_chat_prompt(context, message)

    if context.tools:
        raw_text, tool_calls = await ai_client.chat_with_tools(
            prompt=prompt,
            tools=context.tools,
        )
    else:
        raw_text = await ai_client.chat(prompt=prompt)
        tool_calls = []

    clean_text, emotion_data = extract_emotion(raw_text)
    return clean_text, emotion_data, tool_calls
