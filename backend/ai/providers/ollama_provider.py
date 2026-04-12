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
    ) -> str:
        response = await self._client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            options={
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        )

        return response.message.content or ""
