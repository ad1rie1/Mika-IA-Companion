"""Gemini provider — uses the official ``google-generativeai`` Python SDK.

The SDK handles the Google endpoint, so no base URL is required
(unlike Ollama). Only an API key, obtainable from Google AI Studio.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class GeminiProvider:
    """Google Gemini via ``google.generativeai``.

    The SDK exposes a sync API (``GenerativeModel.generate_content``);
    we offload it to a thread to keep the async pipeline non-blocking.
    """

    def __init__(self):
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise ImportError(
                "Le provider Gemini nécessite le package 'google-generativeai'. "
                "Installez-le avec : pip install google-generativeai"
            ) from exc

        from configs.service import config_service

        api_key = config_service.get("ai.gemini.api_key", default="") or None
        if not api_key:
            raise ValueError(
                "GeminiProvider nécessite ai.gemini.api_key "
                "(éditeur Configuration > Fournisseur IA)."
            )

        genai.configure(api_key=api_key)
        self._genai = genai
        logger.info("GeminiProvider initialisé")

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        attachments: list | None = None,
    ) -> str:
        def _call() -> str:
            gm = self._genai.GenerativeModel(
                model_name=model,
                system_instruction=system_prompt or None,
            )
            parts: list = [user_prompt]
            if attachments:
                import base64
                for att in attachments:
                    if att.category == "image":
                        parts.append({
                            "mime_type": att.media_type,
                            "data": base64.b64decode(att.data),
                        })
            resp = gm.generate_content(
                parts,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                },
            )
            try:
                from ai.quota import set_usage
                usage = getattr(resp, "usage_metadata", None)
                if usage is not None:
                    set_usage(
                        input_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
                        output_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
                    )
            except Exception:
                pass
            return (resp.text or "").strip()

        return await asyncio.to_thread(_call)

    async def list_models(self) -> list[dict]:
        """List Gemini models that support ``generateContent``."""
        def _sync() -> list[dict]:
            out: list[dict] = []
            for m in self._genai.list_models():
                if "generateContent" in getattr(m, "supported_generation_methods", []):
                    mid = m.name.split("/", 1)[-1] if "/" in m.name else m.name
                    label = getattr(m, "display_name", None) or mid
                    out.append({"id": mid, "label": label})
            return sorted(out, key=lambda x: x["id"])
        return await asyncio.to_thread(_sync)

    async def test(self) -> dict:
        from ai.providers import default_test
        return await default_test(self)
