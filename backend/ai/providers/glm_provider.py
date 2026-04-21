"""GLM provider — Zhipu AI / ChatGLM models.

Zhipu ships an OpenAI-compatible endpoint at
``https://open.bigmodel.cn/api/paas/v4/``. We reuse the ``openai`` async
SDK so this provider inherits all the quality-of-life of OpenAIProvider
(streaming hooks, usage accounting, image support) for free — no
additional dependency.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"


class GLMProvider:
    """ChatGLM via Zhipu's OpenAI-compatible endpoint."""

    def __init__(self):
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError(
                "Le provider GLM utilise le SDK 'openai' (endpoint compatible). "
                "Installez-le avec : pip install openai"
            ) from exc

        from configs.service import config_service

        api_key = config_service.get("ai.glm.api_key", default="") or None
        if not api_key:
            raise ValueError(
                "GLMProvider nécessite ai.glm.api_key "
                "(éditeur Configuration > Fournisseur IA)."
            )

        self._client = AsyncOpenAI(api_key=api_key, base_url=DEFAULT_BASE_URL)
        logger.info("GLMProvider initialisé (base_url=%s)", DEFAULT_BASE_URL)

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        attachments: list | None = None,
    ) -> str:
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

        return (response.choices[0].message.content or "").strip()

    async def list_models(self) -> list[dict]:
        """List GLM models via the Zhipu OpenAI-compatible endpoint."""
        page = await self._client.models.list()
        out = []
        for m in page.data:
            mid = getattr(m, "id", None) or ""
            if mid:
                out.append({"id": mid, "label": mid})
        return sorted(out, key=lambda x: x["id"])

    async def test(self) -> dict:
        from ai.providers import default_test
        return await default_test(self)

    async def complete_with_tools(self, *args, **kwargs):
        from ai.providers import tools_unsupported
        return await tools_unsupported("GLMProvider")
