"""Response parsing — extract emotion and clean text from AI output."""

import logging

from ai.client import ai_client
from emotion.types import EmotionData, extract_emotion
from pipeline.context import ConversationContext
from pipeline.media import MediaAttachment, transcribe_audio, read_text_attachment
from pipeline.prompt import build_system_prompt, format_conversation

logger = logging.getLogger(__name__)


async def _build_user_prompt_with_attachments(
    base_prompt: str,
    attachments: list[MediaAttachment],
) -> tuple[str, list[MediaAttachment]]:
    """Process attachments: transcribe audio/text, collect image attachments.

    Returns (enriched_prompt, image_attachments).
    """
    extra_parts: list[str] = []
    image_attachments: list[MediaAttachment] = []

    for att in attachments:
        if att.category == "image":
            image_attachments.append(att)

        elif att.category == "audio":
            transcript = await transcribe_audio(att)
            if transcript:
                extra_parts.append(f"[Transcription audio « {att.name} »] : {transcript}")
            else:
                extra_parts.append(
                    f"[Fichier audio joint : « {att.name} » — transcription indisponible"
                    " (configurez OPENAI_API_KEY pour activer Whisper)]"
                )

        elif att.category == "text":
            content = read_text_attachment(att)
            if content:
                extra_parts.append(f"[Fichier texte « {att.name} »] :\n{content}")
            else:
                extra_parts.append(f"[Fichier texte joint : « {att.name} » — lecture échouée]")

        else:
            extra_parts.append(f"[Fichier joint : « {att.name} » ({att.media_type})]")

    enriched = base_prompt
    if extra_parts:
        enriched += "\n\n" + "\n\n".join(extra_parts)

    return enriched, image_attachments


async def call_ai_and_parse(
    context: ConversationContext, message: str
) -> tuple[str, EmotionData, list[str]]:
    """Build prompt, call AI, extract emotion from response.

    Returns (clean_text, emotion_data, tool_calls).
    """
    system = build_system_prompt(
        context.emotion_context, context.memory_context, context.module_context
    )
    user_prompt = format_conversation(message, context.history)

    # Process attachments if any
    image_attachments: list[MediaAttachment] = []
    if context.attachments:
        user_prompt, image_attachments = await _build_user_prompt_with_attachments(
            user_prompt, context.attachments
        )

    if context.mcp_server and context.tool_names:
        raw_text, tool_calls = await ai_client.complete_with_tools(
            system_prompt=system,
            user_prompt=user_prompt,
            mcp_server=context.mcp_server,
            tool_names=context.tool_names,
        )
    else:
        raw_text = await ai_client.complete(
            system_prompt=system,
            user_prompt=user_prompt,
            attachments=image_attachments if image_attachments else None,
        )
        tool_calls = []

    clean_text, emotion_data = extract_emotion(raw_text)
    return clean_text, emotion_data, tool_calls
