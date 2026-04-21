"""AI provider abstraction layer.

Each provider lives in its own module and uses its native Python SDK.
The Protocol defines the common interface; the router uses it to
dispatch completion requests.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AIProvider(Protocol):
    """Minimal interface for AI text completion providers.

    Each provider owns three responsibilities:
      - ``complete()``    — single-turn generation (no streaming, no tools).
      - ``list_models()`` — discover the models available with the current
        credentials. Drives the "Charger les modèles" button in the UI.
      - ``test()``        — lightweight liveness check. Default impl just
        calls ``list_models()`` and counts the result, but providers may
        override if they have a cheaper ping.
    """

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str: ...

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
