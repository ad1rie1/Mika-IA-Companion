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

        from configs.service import config_service
        host = config_service.get("ai.ollama.base_url", default="http://localhost:11434")
        if not host:
            host = "http://localhost:11434"

        self._host = host
        self._client = AsyncClient(host=host)

        logger.info("OllamaProvider initialisé (host=%s)", host)

    # -- Generation policy ---------------------------------------------------
    #
    # Two knobs that decide whether a local model answers at all.
    #
    # `think`: the reasoning models now shipped by Ollama (gemma4, qwen3,
    # deepseek-r1) reason by DEFAULT, and that reasoning is generated before
    # the first word of the reply. Measured on gemma4:12b, RTX 3060, fully
    # in VRAM at ~30 tok/s: "coucou" answered in 1.5 s with thinking off and
    # 27 s with it on. With a real system prompt and 34 tool declarations the
    # same turn ran past 2000 generated tokens and was still going when the
    # 120 s timeout fired — every reply was the fallback.
    #
    # `num_predict`: the caller's default `max_tokens=4096` was handed
    # straight through, so a model that does not stop has a 4096-token rope.
    # At the ~19 tok/s a long context degrades to, that is 219 s — a turn
    # that CANNOT finish inside any sane timeout. The cap is the belt: even
    # with thinking re-enabled, a turn is bounded.

    def _generation_options(self, max_tokens: int, temperature: float) -> dict:
        from configs.service import config_service

        cap = max_tokens
        try:
            cap = min(max_tokens, int(config_service.get("ai.ollama.max_reply_tokens")))
        except Exception:
            # An unreadable config must not silently restore the unbounded
            # behaviour this cap exists to prevent.
            cap = min(max_tokens, 768)
        return {"num_predict": cap, "temperature": temperature}

    def _thinking(self) -> bool:
        from configs.service import config_service

        try:
            return bool(config_service.get("ai.ollama.thinking"))
        except Exception:
            return False

    async def _chat(self, **kwargs):
        """Call the SDK, degrading gracefully when `think` is unsupported.

        Not every model accepts the parameter, and older Ollama servers
        reject it outright. A provider that cannot talk to half the local
        models is worse than one that occasionally lets a model reason.
        """
        try:
            return await self._client.chat(**kwargs)
        except Exception as exc:
            if "think" not in kwargs:
                raise
            logger.debug(
                "Ollama rejected think=%s (%s) — retrying without it",
                kwargs.get("think"), exc,
            )
            kwargs.pop("think", None)
            return await self._client.chat(**kwargs)

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

        response = await self._chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                user_message,
            ],
            think=self._thinking(),
            options=self._generation_options(max_tokens, temperature),
        )

        _record_ollama_usage(response)
        return response.message.content or ""

    async def list_models(self) -> list[dict]:
        """List models available on the configured Ollama server.

        The ollama SDK exposes this, but some releases disagree on the
        return shape; we go through plain HTTP to stay version-agnostic
        and keep a single representation.
        """
        import httpx
        url = f"{self._host.rstrip('/')}/api/tags"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        out = []
        for m in data.get("models", []):
            mid = m.get("name") or m.get("model") or ""
            if mid:
                out.append({"id": mid, "label": mid})
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
        """Ollama function-calling loop (SDK ≥ 0.3, model must support tools).

        If the selected model isn't tool-capable, Ollama returns a plain
        response with no ``tool_calls`` — we detect this and return the
        text as-is, so the call degrades gracefully instead of looping.
        """
        import json

        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        serialized = _serialize_tools_for_ollama(tools) if tools else None
        tools_by_name = {t.name: t for t in tools}

        called: list[str] = []
        final_text = ""

        think = self._thinking()
        options = self._generation_options(max_tokens, temperature)

        for _ in range(max_turns):
            kwargs = {
                "model": model,
                "messages": messages,
                "think": think,
                "options": options,
            }
            if serialized:
                kwargs["tools"] = serialized

            response = await self._chat(**kwargs)
            _record_ollama_usage(response)

            msg = response.message
            tool_calls = getattr(msg, "tool_calls", None) or []

            if not tool_calls:
                final_text = msg.content or ""
                break

            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            })

            for tc in tool_calls:
                name = tc.function.name
                tool = tools_by_name.get(name)
                # Ollama already parses arguments to a dict — guard anyway.
                raw_args = tc.function.arguments
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args) if raw_args else {}
                    except json.JSONDecodeError as exc:
                        args = None
                        err = str(exc)
                    else:
                        err = None
                else:
                    args = raw_args or {}
                    err = None

                if tool is None:
                    content = json.dumps({"error": f"unknown tool '{name}'"})
                elif err is not None:
                    content = json.dumps({"error": f"invalid JSON arguments: {err}"})
                else:
                    logger.info(
                        "Ollama called tool: %s (input=%s)", name, str(args)[:200],
                    )
                    try:
                        result = await tool.handler(args)
                        content = json.dumps(result, ensure_ascii=False, default=str)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Tool '%s' handler raised: %s", name, exc)
                        content = json.dumps({"error": str(exc)})
                    called.append(name)

                messages.append({
                    "role": "tool",
                    "name": name,
                    "content": content,
                })
        else:
            final_text = final_text or "[max_turns atteint avant réponse finale]"

        if called:
            logger.info("Ollama tools used in this turn: %s", called)
        return final_text, called


def _record_ollama_usage(response) -> None:
    """Surface Ollama's prompt_eval_count / eval_count to the quota tracker.

    Ollama exposes these on the top-level response object (not on
    ``message``), and only after the full response is generated.
    """
    try:
        from ai.quota import set_usage
        tokens_in = int(getattr(response, "prompt_eval_count", 0) or 0)
        tokens_out = int(getattr(response, "eval_count", 0) or 0)
        if tokens_in or tokens_out:
            set_usage(input_tokens=tokens_in, output_tokens=tokens_out)
    except Exception:
        pass


def _serialize_tools_for_ollama(tools: list) -> list[dict]:
    """Convert ModuleTool list → Ollama ``tools`` parameter shape.

    Same shape as OpenAI's ``tools`` param — Ollama deliberately mirrored
    it — but kept local to this module so it doesn't drift if Ollama
    diverges later.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.to_json_schema(),
            },
        }
        for t in tools
    ]
