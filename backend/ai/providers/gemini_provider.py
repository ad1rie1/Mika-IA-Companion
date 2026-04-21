"""Gemini provider — uses the official ``google-genai`` Python SDK.

The previous ``google-generativeai`` package is deprecated in favour of
``google-genai`` (``from google import genai``). The new SDK ships a
unified ``Client`` with an async companion at ``client.aio``, which we
use directly instead of offloading the sync API to a thread.

The SDK handles Google's endpoint, so no base URL is required.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class GeminiProvider:
    """Google Gemini via the ``google-genai`` SDK."""

    def __init__(self):
        try:
            from google import genai
        except ImportError as exc:
            raise ImportError(
                "Le provider Gemini nécessite le package 'google-genai' "
                "(l'ancien 'google-generativeai' est deprecated). "
                "Installez-le avec : pip install google-genai"
            ) from exc

        from configs.service import config_service

        api_key = config_service.get("ai.gemini.api_key", default="") or None
        if not api_key:
            raise ValueError(
                "GeminiProvider nécessite ai.gemini.api_key "
                "(éditeur Configuration > Fournisseur IA)."
            )

        # The async surface lives on ``client.aio`` — same API shape as
        # the sync one, so we stash it directly for callers.
        self._genai = genai
        self._client = genai.Client(api_key=api_key)
        logger.info("GeminiProvider initialisé (SDK google-genai)")

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        attachments: list | None = None,
    ) -> str:
        from google.genai import types

        parts: list = []
        if attachments:
            import base64
            for att in attachments:
                if getattr(att, "category", None) == "image":
                    parts.append(types.Part.from_bytes(
                        data=base64.b64decode(att.data),
                        mime_type=att.media_type,
                    ))
        parts.append(types.Part.from_text(text=user_prompt))

        config = types.GenerateContentConfig(
            system_instruction=system_prompt or None,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        resp = await self._client.aio.models.generate_content(
            model=model,
            contents=parts,
            config=config,
        )
        _record_gemini_usage(resp)
        return (resp.text or "").strip()

    async def list_models(self) -> list[dict]:
        """List Gemini models that support content generation."""
        out: list[dict] = []
        pager = await self._client.aio.models.list()
        async for m in pager:
            # New SDK exposes ``supported_actions`` instead of the
            # deprecated ``supported_generation_methods``.
            actions = getattr(m, "supported_actions", None) or []
            if actions and "generateContent" not in actions:
                continue
            # ``name`` is already the bare model id (e.g. "gemini-2.0-flash")
            # or prefixed by "models/" depending on the SDK minor version.
            raw = m.name or ""
            mid = raw.split("/", 1)[-1] if "/" in raw else raw
            if not mid:
                continue
            label = getattr(m, "display_name", None) or mid
            out.append({"id": mid, "label": label})
        out.sort(key=lambda x: x["id"])
        return out

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
        """Gemini function-calling loop (google-genai SDK).

        Gemini uses a different shape than OpenAI: tools are wrapped in
        ``types.Tool(function_declarations=[...])`` and tool results are
        sent back as ``Part.from_function_response``. Otherwise the
        ping/pong structure is the same.
        """
        import json
        from google.genai import types

        function_declarations = [
            types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters=t.to_json_schema(),
            )
            for t in tools
        ]
        gemini_tools = (
            [types.Tool(function_declarations=function_declarations)]
            if function_declarations else None
        )
        tools_by_name = {t.name: t for t in tools}

        contents: list = [
            types.Content(role="user", parts=[types.Part.from_text(text=user_prompt)])
        ]
        config = types.GenerateContentConfig(
            system_instruction=system_prompt or None,
            temperature=temperature,
            max_output_tokens=max_tokens,
            tools=gemini_tools,
        )

        called: list[str] = []
        final_text = ""

        for _ in range(max_turns):
            resp = await self._client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            _record_gemini_usage(resp)

            function_calls = getattr(resp, "function_calls", None) or []

            if not function_calls:
                final_text = (resp.text or "").strip()
                break

            # Replay the model turn (the Content holding function_call parts).
            try:
                contents.append(resp.candidates[0].content)
            except (AttributeError, IndexError):
                pass

            response_parts = []
            for fc in function_calls:
                name = fc.name
                tool = tools_by_name.get(name)
                args = dict(fc.args) if fc.args else {}
                if tool is None:
                    payload = {"error": f"unknown tool '{name}'"}
                else:
                    logger.info(
                        "Gemini called tool: %s (input=%s)", name, str(args)[:200],
                    )
                    try:
                        result = await tool.handler(args)
                        payload = result if isinstance(result, dict) else {"result": result}
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Tool '%s' handler raised: %s", name, exc)
                        payload = {"error": str(exc)}
                    called.append(name)
                try:
                    json.dumps(payload, default=str)
                except TypeError:
                    payload = {"result": str(payload)}
                response_parts.append(types.Part.from_function_response(
                    name=name, response=payload,
                ))
            contents.append(types.Content(role="user", parts=response_parts))
        else:
            final_text = final_text or "[max_turns atteint avant réponse finale]"

        if called:
            logger.info("Gemini tools used in this turn: %s", called)
        return final_text, called


def _record_gemini_usage(resp) -> None:
    """Surface Gemini usage_metadata to the quota tracker."""
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
