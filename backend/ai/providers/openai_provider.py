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

        api_key = getattr(settings, "OPENAI_API_KEY", "") or None
        base_url = getattr(settings, "OPENAI_BASE_URL", "") or None

        if not api_key:
            raise ValueError(
                "OpenAIProvider nécessite OPENAI_API_KEY dans .env"
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
    ) -> str:
        response = await self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        return response.choices[0].message.content or ""
