"""Contrat d'``attention`` : ce qui lui trotte dans la tête, et ce qu'elle attend.

- une **pensée** naît d'un échange qui l'a marquée, d'une croyance qu'elle
  doit réviser, ou du manque de quelqu'un qu'elle ne peut pas joindre ; elle
  s'estompe (demi-vie), revient par moments, et s'allège quand elle en parle ;
- une **attente** naît quand elle écrit d'elle-même à quelqu'un (une
  réponse), ou quand quelqu'un lui manque (un retour) : elle se comble ou se
  dément, et chacun en tire ce qui le concerne (l'humeur, l'estime, la
  retenue).
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactKey

OWNER = "attention"

EXCHANGE, REVISION, MISSING = "exchange", "revision", "missing"
#: un but sur lequel elle bloque (« Je bloque sur… »)
BLOCKED = "blocked"
REPLY, RETURN = "reply", "return"
#: Raison de preuve d'initiative : une pensée qui insiste, vers la personne concernée.
THOUGHT = "thought"


class ThoughtBorn(Payload):
    text: Content
    emotion: str
    intensity: float
    origin: str
    about: tuple[str, ...] = ()
    sensitivity: int = 2
    source: int | None = None  # le message ou l'élément de mémoire d'où elle vient


class Dwelt(Payload):
    """Elle y repense (une pensée qui revient la teinte, par moments)."""

    thought: int
    emotion: str
    intensity: float
    origin: str = ""


class ExpectationMet(Payload):
    kind: str  # REPLY | RETURN
    person: str
    since: int


class ExpectationMissed(Payload):
    kind: str
    person: str
    since: int


class DigestedThought(Payload):
    thought: int
    before: float
    after: float
    emotion: str  # la couleur après la nuit (la frustration devient du soulagement…)
    reflective: bool  # assez forte pour laisser un souvenir « après y avoir repensé »
    text_ref: str = ""
    about: tuple[str, ...] = ()
    sensitivity: int = 2


class Digested(Payload):
    """La nuit, les pensées de la veille s'allègent et se calment."""

    night: str
    items: tuple[DigestedThought, ...] = ()


THOUGHT_BORN = event_type("attention.thought_born", OWNER, ThoughtBorn, public=True, content=("text",),
                          subjects=("about",))
DWELT = event_type("attention.dwelt", OWNER, Dwelt, public=True)
EXPECTATION_MET = event_type("attention.expectation_met", OWNER, ExpectationMet, public=True, subjects=("person",))
EXPECTATION_MISSED = event_type("attention.expectation_missed", OWNER, ExpectationMissed, public=True,
                                subjects=("person",))
DIGESTED = event_type("attention.digested", OWNER, Digested, public=True)
ALL = (THOUGHT_BORN, DWELT, EXPECTATION_MET, EXPECTATION_MISSED, DIGESTED)


@dataclass(frozen=True, slots=True)
class ThoughtReading:
    id: int
    text_ref: str
    emotion: str
    intensity: float  # ce qu'il en reste à l'instant
    origin: str
    about: tuple[str, ...]
    sensitivity: int
    born_at: int


#: Les pensées vivantes, la plus forte d'abord.
THOUGHTS = FactKey("attention.thoughts", type=tuple, time_varying=True)
#: Ses initiatives restées sans réponse, d'affilée (toutes personnes).
IGNORED = FactKey("attention.ignored", type=int)
