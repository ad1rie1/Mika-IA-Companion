"""AI provider abstraction layer.

Each provider lives in its own module and uses its native Python SDK. One
Protocol, ``AIProvider``, is the whole contract; ``AIRouter`` dispatches on
it without probing capabilities — every provider implements every method.

Adding a provider is two pieces:

- an *adapter* for its API family, a short class deriving from
  ``_tool_loop.AdaptateurOutils`` (thread in the native shape, tool
  serialization, one request, one response read, tool-result shape). The
  tool loop itself — iteration bound, argument decoding, handler outcomes,
  the ``max_tokens`` replay, the fallback texts, usage flushed on the way
  out — lives once in ``_tool_loop.executer_la_boucle`` and is never
  copied. An OpenAI-compatible endpoint reuses ``AdaptateurOpenAI`` as is.
- a provider class implementing this Protocol: ``complete`` (one prompt,
  no tools), ``complete_chat`` (a ``ChatPrompt`` — stable prefix as
  system, real history turns, volatile state in the final user turn),
  ``complete_chat_with_tools`` (the same prompt + ``ModuleTool`` list,
  handed to the loop through the adapter), ``list_models`` and ``test``
  (``default_test`` suffices when ``list_models`` proves the credential).

Then register the class in ``ai.router._PROVIDER_CLASSES`` and declare its
credential prefix so a rotated key evicts the cached instance.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AIProvider(Protocol):
    """What every provider implements — the router calls nothing else.

    ``complete`` is the single-turn path (extraction, captioning, inner
    voice…); ``complete_chat`` and ``complete_chat_with_tools`` are the
    conversation turn, structured so the provider can cache or prefix-match
    the stable part. ``tools`` is a list of provider-agnostic ``ModuleTool``
    objects (``name``, ``description``, ``to_json_schema()``, async
    ``handler``); the provider translates them to its native tool protocol
    and runs the loop — callers never see a provider-specific tool format.
    """

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        attachments: list | None = None,
    ) -> str: ...

    async def complete_chat(
        self,
        prompt,                   # ChatPrompt — quoted to avoid import cycle
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Run a structured turn: cacheable prefix + real message turns."""
        ...

    async def complete_chat_with_tools(
        self,
        prompt,                   # ChatPrompt
        model: str,
        tools: list,              # list[ModuleTool]
        max_tokens: int = 4096,
        temperature: float = 0.7,
        *,
        max_turns: int = 10,
    ) -> tuple[str, list[str]]:
        """Structured turn with tools; returns ``(texte, outils appelés)``."""
        ...

    async def list_models(self) -> list[dict]:
        """Return a list of ``{"id": str, "label": str}`` usable models."""
        ...

    async def test(self) -> dict:
        """Return ``{"ok": bool, "model_count": int, "error"?: str}``."""
        ...


async def default_test(provider: "AIProvider") -> dict:
    """Baseline implementation usable by any provider.

    Treats ``list_models()`` as the canonical liveness probe: if it
    returns anything the provider is reachable and the credentials work.
    """
    try:
        models = await provider.list_models()
    except Exception as exc:  # noqa: BLE001 — surface any error to the user
        return {"ok": False, "model_count": 0, "error": str(exc)}
    return {"ok": True, "model_count": len(models)}
