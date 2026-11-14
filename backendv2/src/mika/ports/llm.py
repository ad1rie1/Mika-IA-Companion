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

from mika.kernel.prompt import Budget


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
    #: son nom (celui de sa persona) : un « Nom : » recopié en tête de réponse se retire (ADR 0070)
    name: str = ""
    #: un fil de messages qui donne le registre de sa voix (sa persona, ``reference_thread``) : seule l'autrice de la
    #: seconde passe le lit (ADR 0114)
    reference: str = ""


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
    #: le délai de chaque appel de cette requête (secondes, attente d'un créneau comprise) : celui de l'épisode qui la
    #: porte (le mode pro a quinze minutes, pas les deux de sa voie) ; ``None`` : le délai de sa voie (les processus)
    deadline_s: float | None = None
    #: ``auto`` : le modèle appelle ses outils s'il le veut ; ``none`` : aucun appel d'outil à ce tour (le tour de
    #: clôture d'une boucle). Les outils restent déclarés : un fournisseur refuse une conversation qui porte leurs
    #: appels sans eux (Claude) ; celui qui n'a pas de ``tool_choice`` (Ollama) ne les envoie pas
    tool_choice: str = "auto"
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
    #: la catégorie d'un refus (``stop_details.category`` de l'API : « cyber », « bio », « frontier_llm »…) ; vide hors
    #: refus, ou quand le fournisseur n'en donne pas
    stop_detail: str = ""
    #: la plus grande entrée d'un seul appel au modèle, cache compris, quand le fournisseur en a fait plusieurs pour
    #: cette réponse (la CLI de Claude Code cherche ses outils en cours de tour) ; 0 : l'entrée de ``usage`` suffit.
    #: C'est ce que la passerelle compare à l'estimation du budget — jamais la somme de plusieurs appels
    prompt_tokens: int = 0


#: ``meta`` d'une requête redemandée après une coupure par ``max_tokens`` : un
#: fournisseur qui bride sa sortie (un modèle local) lève alors son propre plafond
RETRY_AFTER_CUT = "retry_after_cut"
#: Clé que posent les fournisseurs quand les arguments d'un appel ne sont pas
#: du JSON : l'appel est refusé au modèle, jamais exécuté avec des défauts.
RAW_ARGS_KEY = "_raw"
#: ``meta`` : l'instant (``loop.time()``) où l'épisode qui porte la requête s'arrête — la passerelle ne donne à aucun
#: de ses appels plus que ce qui reste devant lui
DEADLINE_AT = "deadline_at"
#: les valeurs de ``LLMRequest.tool_choice``
TOOL_CHOICE_AUTO, TOOL_CHOICE_NONE = "auto", "none"


class MissingPersona(ValueError):
    pass


class Held(RuntimeError):
    """Un appel de fond refusé d'avance pour garder la réserve de la conversation (le quota d'un abonnement entamé
    au-delà de son plafond) : rien n'a été tenté, le fournisseur n'a pas manqué. Un épisode arrêté ainsi se règle en
    ``preempted`` — le premier plan passe devant —, jamais en panne (ADR 0127)."""


class LLMBackend(Protocol):
    """Un fournisseur. Facultatifs : ``resumes_tool_loops`` (faux : il ne sait pas
    reprendre une boucle d'outils commencée ailleurs — la passerelle ne bascule
    jamais vers lui en cours de boucle), ``defers_tools`` (faux : il ignore
    ``ToolDecl.deferred`` et envoie tous les outils — le prompt ne lui parle alors
    pas d'outils « à chercher »), ``release(call_id)`` (la boucle est finie :
    relâcher ce qu'il tient encore pour elle), ``output_tokens(req) -> int`` (le
    plafond de sortie qu'il enverra vraiment pour cette requête — un modèle qui
    réfléchit a un plancher ; sans lui : ``req.max_tokens``), ``status() -> dict``
    (ce qu'il dit de lui, le quota d'un abonnement : ``Gateway.status`` le joint à
    ses créneaux), ``holds(priority) -> str`` (la raison, en mots, d'un refus
    d'avance d'un appel de fond à cette priorité, le quota d'un abonnement entamé
    — ``Gateway.held`` et ``Gateway.holding``, ADR 0127 ; « » : il passerait),
    ``carries(req) -> bool`` (il tient déjà le fil de ``req``, une session de CLI
    vivante qui attend ces résultats : seuls les nouveaux résultats sont mesurés
    contre le budget — ``_carried``, adapters/llm/gateway.py) et ``async aclose()``
    (arrêter ce qu'il tient encore, les CLI de Claude Code : ``LiveGateway.aclose``,
    à l'arrêt du serveur)."""

    name: str

    async def complete(self, req: LLMRequest) -> LLMResponse: ...


class LLMGateway(Protocol):
    """La passerelle : ``is_voice`` et ``call`` sont toujours là. Les autres membres, les appelants les lisent par
    ``getattr`` (avec un repli), parce qu'une doublure de test peut ne pas les avoir et que ``_BoundedLLM`` (le
    runtime) délègue les siens. Les deux passerelles du dépôt les ont tous — ``Gateway``, la passerelle nue (celle
    du simulateur), et ``LiveGateway``, celle du serveur, qui l'enveloppe —, sauf ``configured`` et ``failing``, que
    seule la passerelle en service a : la passerelle nue ne garde pas de traces à relire."""

    def is_voice(self, role: str) -> bool: ...

    async def call(self, req: LLMRequest) -> LLMResponse: ...

    @property
    def configured(self) -> bool:
        """Peut-elle parler ? Le rôle « répondre » se résout vers un fournisseur déclaré (un fournisseur déclaré sans
        rôle ne suffit pas)."""
        ...

    def serving(self, role: str) -> str:
        """Le fournisseur qui sert vraiment ce rôle (replis compris) ; « » : aucun (une étape qui ne se fait que si
        l'opératrice lui a donné un modèle : la seconde passe, ``Role.POLISH``)."""
        ...

    def defers_tools(self, role: str) -> bool:
        """Le fournisseur de ce rôle sait-il différer des outils (une recherche d'outils) ? Sans configuration : oui
        (l'appel échouera de toute façon)."""
        ...

    def held(self, role: str, priority: int = 1) -> str:
        """Un appel de ce rôle à cette priorité serait-il refusé d'avance (``Held``) ? La raison en mots, « » : il
        passerait (ADR 0127)."""
        ...

    def holding(self) -> list[tuple[str, str]]:
        """Les fournisseurs qui refusent en ce moment leurs appels de fond : (fournisseur, raison)."""
        ...

    def output_tokens(self, req: LLMRequest) -> int:
        """Le plafond de sortie que le fournisseur de cette requête enverra vraiment (jamais sous ``req.max_tokens``) :
        un rejeu après coupure qui ne le relève pas ne vaut pas un appel (ADR 0135)."""
        ...

    def release(self, call_id: str) -> None:
        """La boucle d'outils ``call_id`` est finie — y compris quand on s'arrête sur un appel d'outil lu comme une
        sortie structurée, ou au plafond de tours. Sans lui, un fournisseur à session (la CLI de Claude Code) ne la
        relâche qu'à son délai d'inactivité."""
        ...

    def budget(self, role: str, max_tokens: int) -> Budget:
        """Le budget de prompt du fournisseur de ce rôle, la sortie réservée sur le plafond qu'il enverra vraiment."""
        ...

    def status(self) -> list[dict[str, Any]]:
        """L'état vivant de chaque fournisseur : créneaux, préemption, et ce qu'il dit de lui (vide sans
        configuration)."""
        ...

    def resolution(self) -> dict[str, str]:
        """Rôle → fournisseur qui le sert vraiment (« » : aucun), pour chaque rôle."""
        ...

    async def try_on(self, name: str, req: LLMRequest) -> Any:
        """Un essai de la console (« Rejouer avec… ») sur le fournisseur ``name`` : un seul appel, derrière tout le
        reste. Il rend un ``Trial`` (adapters/llm), qu'un port n'importe pas."""
        ...

    def failing(self, role: str, now: int, window_us: int) -> tuple[str, int, str] | None:
        """Le fournisseur de ce rôle ne répond plus : ses derniers appels (dans ``window_us``) ont tous échoué, sans un
        succès depuis. ``(fournisseur, depuis quand, cause)``, ou ``None``."""
        ...
