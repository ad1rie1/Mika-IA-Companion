"""Le port de livraison : ce qu'elle dit part vers les transports.

La file de sortie appelle ``deliver`` après le commit, au moins une fois :
une livraison porte sa clé d'idempotence (l'identifiant de l'événement).
Un transport ne livre qu'aux personnes connectées ; une personne absente
rattrape par l'historique, jamais par une diffusion à tout le monde.

``deliver`` rend ``True`` quand c'est fait (ou qu'il n'y a rien à faire :
personne de connecté, salon plus autorisé), ``False`` quand le transport ne
peut pas livrer **pour l'instant** (canal pas encore démarré) : à réessayer.

Les sortes (``kind``) :

- ``speech`` : ce qu'elle dit ; ``persona`` dit si c'est une parole adressée
  (``speaking``) ou une pensée à voix haute (``inner``, le murmure). Une
  pensée ne part jamais en message écrit, seulement aux écrans de la
  personne à qui elle s'apprête à parler (``target``) — ou, sans cible, des
  opératrices ; elle n'a pas d'identifiant de message (elle n'est pas dans le
  fil) ;
- ``state`` : son état a changé (elle s'endort, s'éveille) — sans parole ;
- ``reply_failed`` : la réponse à ``reply_to`` n'a pas pu être composée (panne,
  délai, plus de modèle) ; ``text`` porte le détail technique (jamais montré
  tel quel). L'écran qui attendait le dit et cesse d'attendre ;
- ``reply_abstained`` : elle a choisi de ne pas répondre à ``reply_to`` ;
  l'écran cesse d'afficher « Mika écrit… ».

Le port d'activité (``activity``, ADR 0116) montre à la personne, en direct, ce qu'elle fait pendant qu'elle
travaille pour elle (le mode pro) : chaque outil qui part et ce qu'il rend, ce qu'elle écrit entre deux. Rien n'en
est gardé : ni journal, ni historique, ni nouvelle tentative — une connexion absente ne le voit pas.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

SPEECH = "speech"
STATE = "state"
REPLY_FAILED = "reply_failed"
REPLY_ABSTAINED = "reply_abstained"
#: les sortes qui disent ce qu'est devenue une question (sans parole)
REPLY_OUTCOMES = frozenset({REPLY_FAILED, REPLY_ABSTAINED})
#: le détail d'un ``reply_failed`` pour une question abandonnée parce que trop vieille (une reprise au
#: démarrage, des heures plus tard) : un transport peut le dire autrement qu'une panne
TOO_LATE = "trop tard pour répondre"


@dataclass(frozen=True, slots=True)
class EmotionView:
    emotion: str
    intensity: float
    blend: tuple[tuple[str, float], ...] = ()
    state: Mapping[str, Any] = field(default_factory=dict)
    declared: bool = False


@dataclass(frozen=True, slots=True)
class Delivery:
    key: str
    target: str | None  # adresse ; None = personne en particulier
    channel: str | None
    room: str | None
    text: str = ""  # jetons prosodiques compris : la voix en a besoin
    persona: str = "speaking"  # vocab.voice.SPEAKING | INNER
    emotion: EmotionView = field(default_factory=lambda: EmotionView("neutral", 0.0))
    message_id: int = 0
    reply_to: int | None = None
    client_msg_id: str | None = None
    source: str = "reply"
    sleep_phase: str = "awake"
    local_hour: int = 12
    kind: str = SPEECH
    #: les messages que cette réponse règle (tout le tour : une rafale reçoit une seule réponse, à son dernier
    #: message, ``reply_to``) — un écran rattache aussi les précédents à leur ligne du fil
    answers: tuple[int, ...] = ()
    #: ce qui part avec ce message (des identifiants de fichiers qu'elle a préparés pour la personne, opaques ici) :
    #: le transport demande au port d'entrée ce qu'il peut en montrer (``MindPort.shared``)
    attachments: tuple[str, ...] = ()
    #: le mode dans lequel elle a répondu (``pro``, ADR 0116) ; ``""`` : la conversation ordinaire
    mode: str = ""
    #: le fil de travail où elle répond (ADR 0164) ; ``None`` : son fil avec la personne
    strand: str | None = None


class DeliveryPort(Protocol):
    async def deliver(self, d: Delivery) -> bool: ...


#: les moments d'une activité : un outil part, il a fini, elle écrit entre deux appels, l'épisode est fini
TOOL_START = "start"
TOOL_END = "end"
NOTE = "note"
DONE = "done"


@dataclass(frozen=True, slots=True)
class Activity:
    """Un moment de son travail, montré en direct à ``target`` (ADR 0116). ``reply_to`` : le message auquel elle
    répond. ``args`` et ``result`` sont déjà bornés ; ``text`` : ce qu'elle a écrit entre deux appels (``note``) ;
    ``outcome`` : l'issue de l'épisode (``done``)."""

    target: str
    episode: str
    phase: str
    at: int
    reply_to: int | None = None
    call_id: str = ""
    name: str = ""
    args: str = ""
    ok: bool | None = None
    result: str = ""
    duration_us: int = 0
    text: str = ""
    outcome: str = ""
    #: le fil de travail où elle répond (ADR 0164) ; ``None`` : son fil avec la personne
    strand: str | None = None


class ActivityPort(Protocol):
    async def activity(self, a: Activity) -> None: ...
