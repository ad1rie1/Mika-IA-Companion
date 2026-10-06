"""Contrat du plugin ``teams`` (ADR 0069) : ce qu'elle remarque des conversations Teams de la personne qui
s'occupe d'elle, et ce qu'elle y écrit à sa place.

Un message remarqué est un **signal** (``attention.Signal``) : l'attention le dose et l'habitue comme tout ce qui
vient d'ailleurs. Son texte est cité, jamais obéi. Un message se désigne par sa **référence** (``t…``, attribuée
par l'adaptateur) ; une personne qu'on ne connaît que par Teams, par son sujet ``teams:<identifiant>``, que
l'oubli atteint.

Écrire est un effet externe (capacité ``teams.send``) : elle rédige un **brouillon** (gardé par l'adaptateur,
jamais au journal) et le propose ; selon le mode, il est posé dans Teams pour que la personne l'envoie, il part
après son accord, ou il part seul. Parti, elle le sait (``teams.sent``), retouché ou non.
"""

from __future__ import annotations

from mika.contracts.attention import Signal
from mika.kernel.events import Content, Payload, event_type
from mika.ports.teams import person_handle as person_handle

OWNER = "teams"
MESSAGE = "teams_message"
#: raison de preuve : préparer une réponse à un message Teams (une tâche silencieuse)
DRAFT = "teams_draft"
SEND = "teams.send"
#: la sorte du signal d'un brouillon parti
SENT_KIND = "teams_sent"


class TeamsNoticed(Signal):
    message: str  # la référence (attribuée par l'adaptateur)
    conversation: str
    #: le nom de la conversation (un groupe, un canal ; vide pour un tête-à-tête) — choisi par d'autres : inerte
    title: str
    author: str
    author_id: str
    #: quand il a été écrit (µs, l'horloge de Teams)
    sent_at: int = 0
    #: dm | group | channel | meeting | other
    where: str = "other"
    importance: float = 0.5
    #: une question à laquelle elle peut aider à répondre (elle peut préparer une réponse)
    needs_reply: bool = False
    mentions_me: bool = False


class TeamsSent(Signal):
    """Un brouillon d'elle est parti de Teams : envoyé par la personne (``edited`` : retouché avant), ou par
    l'extension (validation, autonome). Le texte reste dans le cache de l'adaptateur."""

    draft: str
    conversation: str
    #: le message auquel il répondait (vide : un message dans la conversation)
    reply_to: str = ""
    edited: bool = False


class DraftAsked(Payload):
    """Un opérateur lui demande de préparer une réponse à un message Teams (ce qu'il veut dire, s'il le précise) :
    une tâche qu'elle fera, silencieusement."""

    message: str
    conversation: str = ""
    by: str = ""
    instruction: Content | None = None
    about: tuple[str, ...] = ()


NOTICED = event_type("teams.noticed", OWNER, TeamsNoticed, public=True, content=("summary",), subjects=("about",))
SENT = event_type("teams.sent", OWNER, TeamsSent, public=True, content=("summary",), subjects=("about",))
DRAFT_ASKED = event_type("teams.draft_asked", OWNER, DraftAsked, public=True, content=("instruction",),
                         subjects=("about",))
ALL = (NOTICED, SENT, DRAFT_ASKED)
