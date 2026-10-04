"""Le port LLM : des requêtes sans état, une passerelle qui route par rôle.

La boucle d'outils vit une seule fois, dans le runtime ; un fournisseur ne fait
que convertir une requête générique (messages, appels d'outils, résultats) vers
son API et revenir. Un rôle « voix » exige une persona : la passerelle refuse
une requête voix qui n'en porte pas.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from mika.kernel.slots import PREEMPTED as PREEMPTED


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    args: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Image:
    """Une image jointe à un message utilisateur (base64)."""

    mime: str
    data: str


@dataclass(frozen=True, slots=True)
class Message:
    role: str  # "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None
    is_error: bool = False
    #: des images (message utilisateur seulement : décrire une photo, ce que voit la caméra)
    images: tuple[Image, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolDecl:
    name: str
    description: str
    schema: Mapping[str, Any]
    #: à la demande : un fournisseur qui sait différer (recherche d'outils) ne le
    #: charge pas d'emblée ; celui qui ne sait pas l'envoie comme les autres
    deferred: bool = False


@dataclass(frozen=True, slots=True)
class PersonaRender:
    text: str
    hash: str
    depth: str


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0


@dataclass(frozen=True, slots=True)
class LLMRequest:
    role: str
    call_id: str
    system_stable: str
    system_volatile: str = ""
    messages: tuple[Message, ...] = ()
    tools: tuple[ToolDecl, ...] = ()
    max_tokens: int = 1024
    persona: PersonaRender | None = None
    lane: str = "background"
    priority: int = 1
    meta: Mapping[str, Any] = field(default_factory=dict)

    def extend(self, *messages: Message) -> LLMRequest:
        return replace(self, messages=self.messages + messages)


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    stop: str = "end"  # "end" | "tool_use" | "max_tokens" | "refusal"
    usage: Usage = Usage()
    model: str = ""
    truncated_tool_call: bool = False


#: ``meta`` d'une requête redemandée après une coupure par ``max_tokens`` : un
#: fournisseur qui bride sa sortie (un modèle local) lève alors son propre plafond
RETRY_AFTER_CUT = "retry_after_cut"


class MissingPersona(ValueError):
    pass


class LLMBackend(Protocol):
    """Un fournisseur. Facultatifs : ``resumes_tool_loops`` (faux : il ne sait pas
    reprendre une boucle d'outils commencée ailleurs — la passerelle ne bascule
    jamais vers lui en cours de boucle), ``defers_tools`` (faux : il ignore
    ``ToolDecl.deferred`` et envoie tous les outils — le prompt ne lui parle alors
    pas d'outils « à chercher ») et ``release(call_id)`` (la boucle est finie :
    relâcher ce qu'il tient encore pour elle)."""

    name: str

    async def complete(self, req: LLMRequest) -> LLMResponse: ...


class LLMGateway(Protocol):
    """``release(call_id)`` (facultatif, à appeler par ``getattr``) : la boucle
    d'outils ``call_id`` est finie — y compris quand on s'arrête sur un appel
    d'outil lu comme une sortie structurée, ou au plafond de tours. Sans lui, un
    fournisseur à session (la CLI de Claude Code) ne la relâche qu'à son délai
    d'inactivité."""

    def is_voice(self, role: str) -> bool: ...

    async def call(self, req: LLMRequest) -> LLMResponse: ...

    # facultatif (à appeler par ``getattr``) : ``defers_tools(role) -> bool`` — le fournisseur qui sert ce rôle
    # sait-il différer des outils (une recherche d'outils) ? Sans réponse : oui.
