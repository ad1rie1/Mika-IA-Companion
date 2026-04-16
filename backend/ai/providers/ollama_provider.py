"""Ollama provider — uses the official ``ollama`` Python SDK.

Runs models locally via the Ollama server (default: localhost:11434).
No API key required.
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class OllamaProvider:
    """Local model provider via the official ``ollama.AsyncClient``.

    Set ``OLLAMA_BASE_URL`` in .env to change the Ollama server address
    (default: http://localhost:11434).
    """

    def __init__(self):
        try:
            from ollama import AsyncClient
        except ImportError:
            raise ImportError(
                "Le provider Ollama nécessite le package 'ollama'. "
                "Installez-le avec : pip install ollama"
            )

        host = (
            getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")
            or "http://localhost:11434"
        )

        self._client = AsyncClient(host=host)

        logger.info("OllamaProvider initialisé (host=%s)", host)

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        attachments: list | None = None,
    ) -> str:
        user_message: dict = {"role": "user", "content": user_prompt}

        # Ollama supports vision when the selected model is multimodal
        # (llava, bakllava, llama3.2-vision, qwen2-vl, ...). The SDK
        # takes base64-encoded bytes via the `images` message field.
        # If the model is not vision-capable, Ollama will simply ignore
        # the images — we log it so it's visible but don't fail.
        if attachments:
            image_b64s = [
                a.data for a in attachments
                if getattr(a, "category", None) == "image" and a.data
            ]
            if image_b64s:
                user_message["images"] = image_b64s
                logger.debug(
                    "OllamaProvider: sending %d image(s) to model=%s",
                    len(image_b64s), model,
                )

        response = await self._client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                user_message,
            ],
            options={
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        )

        return response.message.content or ""
