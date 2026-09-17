"""GLM provider — Zhipu AI / ChatGLM models.

Zhipu ships an OpenAI-compatible endpoint at
``https://open.bigmodel.cn/api/paas/v4/``. We reuse the ``openai`` async
SDK so this provider inherits all the quality-of-life of OpenAIProvider
(streaming hooks, usage accounting, image support) for free — no
additional dependency.
"""

from __future__ import annotations

import logging

from utils.degradation import degradations

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

        from ai.providers._openai_tools import create_chat_completion, memo_for

        # Même reprise que le provider OpenAI : un modèle qui refuse
        # ``max_tokens`` ou ``temperature`` en 400 est repris une fois par
        # paramètre, et le refus mémorisé par modèle.
        response = await create_chat_completion(
            self._client, memo_for(self),
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

    async def complete_chat(
        self,
        prompt,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Tour structuré : de vrais rôles au lieu d'un bloc aplati.

        L'endpoint de Zhipu est compatible OpenAI jusque dans son cache de
        préfixe : le préfixe stable (système + historique) reste identique
        octet pour octet d'un tour à l'autre, et l'état du tour voyage dans
        le dernier tour user, après ce préfixe réutilisable.
        """
        from ai.providers._openai_tools import create_chat_completion, memo_for

        messages = [{"role": "system", "content": prompt.system_stable}]
        messages.extend(prompt.chat_messages())

        response = await create_chat_completion(
            self._client, memo_for(self),
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages,
        )

        try:
            from ai.quota import set_usage
            usage = getattr(response, "usage", None)
            if usage is not None:
                set_usage(
                    input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                )
        except Exception as exc:
            degradations.record("ai.providers.glm.complete_chat usage", exc)

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

    async def complete_chat_with_tools(
        self,
        prompt,
        model: str,
        tools: list,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        *,
        max_turns: int = 10,
    ) -> tuple[str, list[str]]:
        """Tour outillé structuré — la boucle générique, amorcée sur de vrais tours.

        Le cache de préfixe de Zhipu s'indexe comme celui d'OpenAI : ce qui
        compte est que le système et l'historique ne bougent pas d'un
        aller-retour d'outil à l'autre.
        """
        from ai.providers._openai_tools import (
            AdaptateurOpenAI,
            memo_for,
            messages_from_chat_prompt,
        )
        from ai.providers._tool_loop import executer_la_boucle

        return await executer_la_boucle(
            AdaptateurOpenAI(
                self._client, memo_for(self),
                label="GLM",
                messages=messages_from_chat_prompt(prompt),
                model=model,
                tools=tools,
                temperature=temperature,
            ),
            tools=tools,
            max_tokens=max_tokens,
            max_turns=max_turns,
        )
