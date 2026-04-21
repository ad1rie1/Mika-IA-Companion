"""OpenAI provider — uses the official ``openai`` Python SDK.

Supports OpenAI, Azure OpenAI, and any OpenAI-compatible API
(Groq, Together, vLLM, LM Studio, etc.) via base_url override.
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """OpenAI-compatible provider via the official ``openai.AsyncOpenAI`` client.

    Set ``OPENAI_BASE_URL`` in .env to point to a custom endpoint
    (Azure, Groq, Together, local vLLM, etc.).
    """

    def __init__(self):
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "Le provider OpenAI nécessite le package 'openai'. "
                "Installez-le avec : pip install openai"
            )

        from configs.service import config_service
        api_key = config_service.get("ai.openai.api_key", default="") or None
        base_url = config_service.get("ai.openai.base_url", default="") or None

        if not api_key:
            raise ValueError(
                "OpenAIProvider nécessite ai.openai.api_key "
                "(éditeur Configuration > IA · Providers)."
            )

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        logger.info(
            "OpenAIProvider initialisé (base_url=%s)",
            base_url or "https://api.openai.com",
        )

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        attachments: list | None = None,
    ) -> str:
        # Build user content with optional image blocks
        if attachments:
            user_content: list | str = []
            for att in attachments:
                if att.category == "image":
                    user_content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{att.media_type};base64,{att.data}"},
                    })
            user_content.append({"type": "text", "text": user_prompt})
        else:
            user_content = user_prompt

        response = await self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )

        # Surface native token usage to the quota tracker.
        try:
            from ai.quota import set_usage
            usage = getattr(response, "usage", None)
            if usage is not None:
                set_usage(
                    input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                )
        except Exception:
            pass

        return response.choices[0].message.content or ""

    async def list_models(self) -> list[dict]:
        """List chat-capable models from the configured endpoint.

        The raw /models endpoint returns everything (embeddings, TTS, moderation…).
        We exclude known non-chat families and keep the rest — this is what
        makes the provider usable against OpenAI-compat backends (Groq,
        Together, LM Studio, vLLM) where model names don't follow OpenAI's
        ``gpt-*`` convention.
        """
        _EXCLUDE = (
            "embedding", "embed-",
            "whisper", "tts-", "audio",
            "dall-e", "image",
            "moderation",
            "babbage", "davinci-002", "davinci-003",
            "search-", "similarity-",
        )
        page = await self._client.models.list()
        out = []
        for m in page.data:
            mid = m.id or ""
            low = mid.lower()
            if not mid or any(tok in low for tok in _EXCLUDE):
                continue
            out.append({"id": mid, "label": mid})
        return sorted(out, key=lambda x: x["id"])

    async def test(self) -> dict:
        from ai.providers import default_test
        return await default_test(self)

    async def complete_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        tools: list,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        *,
        max_turns: int = 10,
    ) -> tuple[str, list[str]]:
        """OpenAI function-calling via ``tools=[...]`` + ping/pong loop."""
        from ai.providers._openai_tools import run_openai_tool_loop
        return await run_openai_tool_loop(
            client=self._client,
            provider_label="OpenAI",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            max_turns=max_turns,
        )

    # ── Audio transcription (OpenAI-specific capability) ─────────
    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        filename: str,
        *,
        model: str = "whisper-1",
    ) -> str:
        """Run a Whisper transcription on an audio buffer.

        Audio transcription is not part of the generic AIProvider
        protocol (only OpenAI exposes a mature Whisper endpoint), so
        callers import this method directly. Keeping it here — rather
        than re-instantiating ``AsyncOpenAI`` from ``files/service.py``
        — is what guarantees the SDK stays confined to the provider
        layer.
        """
        import io
        buf = io.BytesIO(audio_bytes)
        buf.name = filename
        transcript = await self._client.audio.transcriptions.create(
            model=model, file=buf,
        )
        return transcript.text
