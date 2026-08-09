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

    Each provider owns four responsibilities:
      - ``complete()``           — single-turn generation (no streaming, no tools).
      - ``complete_with_tools()``— tool-enabled generation: caller passes a list of
        generic ``ModuleTool`` objects, the provider translates to its native tool
        protocol (MCP for Claude, function-calling for OpenAI/Gemini/GLM, etc.)
        and runs the tool loop. Callers never see a provider-specific tool format.
      - ``list_models()``        — discover the models available with the current
        credentials. Drives the "Charger les modèles" button in the UI.
      - ``test()``               — lightweight liveness check. Default impl just
        calls ``list_models()`` and counts the result, but providers may
        override if they have a cheaper ping.

    Le tour structuré (``complete_chat`` / ``complete_chat_with_tools``) ne
    figure pas ici : c'est une *capacité*, déclarée par ``ChatNativeProvider``
    et ``ChatToolsProvider`` ci-dessous.
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

    async def complete_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        tools: list,              # list[ModuleTool] — quoted to avoid import cycle
        max_tokens: int = 4096,
        temperature: float = 0.7,
        *,
        max_turns: int = 10,
    ) -> tuple[str, list[str]]:
        """Run a completion with tool-calling support.

        Returns ``(assistant_text, names_of_tools_called_in_order)``.
        Providers that don't support tool calling raise
        ``NotImplementedError`` — see ``tools_unsupported``.
        """
        ...

    async def list_models(self) -> list[dict]:
        """Return a list of ``{"id": str, "label": str}`` usable models."""
        ...

    async def test(self) -> dict:
        """Return ``{"ok": bool, "model_count": int, "error"?: str}``."""
        ...


@runtime_checkable
class ChatNativeProvider(Protocol):
    """Provider sachant consommer un ``ChatPrompt`` sans outil.

    Volontairement **hors** de ``AIProvider`` : ``AIRouter.chat`` bascule sur
    ``hasattr(provider, "complete_chat")`` et retombe sur ``complete()`` avec
    l'aplatissement à deux chaînes sinon. Un membre de Protocol n'est jamais
    optionnel — l'exiger dans ``AIProvider`` déclarerait obligatoire ce que le
    routeur détecte comme une *capacité*, et présenterait le ``hasattr`` comme
    un test qui ne peut pas échouer, c'est-à-dire comme du code mort. Le socle
    reste ``AIProvider`` ; ceci nomme la forme que le routeur y cherche.
    """

    async def complete_chat(
        self,
        prompt,                   # ChatPrompt — quoted to avoid import cycle
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Run a structured turn: cacheable prefix + real message turns."""
        ...


@runtime_checkable
class ChatToolsProvider(Protocol):
    """Provider sachant consommer un ``ChatPrompt`` **avec** outils.

    Capacité distincte de la précédente, et détectée séparément : le routeur
    teste ``complete_chat`` dans ``chat()`` et ``complete_chat_with_tools``
    dans ``chat_with_tools()``. Deux protocoles pour deux ``hasattr``.
    """

    async def complete_chat_with_tools(
        self,
        prompt,                   # ChatPrompt — quoted to avoid import cycle
        model: str,
        tools: list,              # list[ModuleTool]
        max_tokens: int = 4096,
        temperature: float = 0.7,
        *,
        max_turns: int = 10,
    ) -> tuple[str, list[str]]:
        """Same contract as ``complete_with_tools``: ``(texte, outils appelés)``."""
        ...


async def tools_unsupported(provider_name: str) -> "tuple[str, list[str]]":
    """Baseline ``complete_with_tools`` for providers that don't implement it yet.

    Raises ``NotImplementedError`` with a message suggesting the user
    map ``AI_ROLE_CONVERSATION_TOOLS`` to a provider that does.
    """
    raise NotImplementedError(
        f"{provider_name} ne supporte pas encore le tool-calling via l'abstraction. "
        "Associe le rôle 'conversation_tools' à un modèle Claude dans "
        "Configuration > Fournisseur IA > IA · Rôles."
    )


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
