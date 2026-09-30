"""Contrat d'``attention`` : ce qui lui trotte dans la tête, et ce qu'elle attend.

- une **pensée** naît d'un échange qui l'a marquée, d'une croyance qu'elle
  doit réviser, ou du manque de quelqu'un qu'elle ne peut pas joindre ; elle
  s'estompe (demi-vie), revient par moments, et s'allège quand elle en parle ;
- une **attente** naît quand elle écrit d'elle-même à quelqu'un (une
  réponse), quand quelqu'un lui manque (un retour), ou quand elle promet
  quelque chose pour une date (sa parole : une attente envers elle-même) :
  elle se comble ou se dément, et chacun en tire ce qui le concerne
  (l'humeur, l'estime, la retenue). Une promesse qui passe son échéance sans
  être tenue ne s'oublie pas en silence : elle le sait, et ça la travaille.
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactKey

OWNER = "attention"

EXCHANGE, REVISION, MISSING = "exchange", "revision", "missing"
#: quelqu'un qui compte n'avait pas l'air comme d'habitude (``others``)
CONCERN = "concern"
#: une promesse qu'elle n'a pas tenue à temps
PROMISE = "promise"
#: un but sur lequel elle bloque (« Je bloque sur… »)
BLOCKED = "blocked"
#: ce qu'une source extérieure lui a signalé (un mail, un titre, ce qu'elle voit)
SIGNAL = "signal"
REPLY, RETURN = "reply", "return"
#: une attente envers elle-même : tenir une promesse avant son échéance (clé : ``PROMISE``)
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
    bundle: str = ""  # les outils qui vont avec (une pensée née d'un signal)


class Signal(Payload):
    """La forme commune de ce qu'une source extérieure signale à son attention
    (un mail, un titre de flux, une app, ce que voit la caméra). Une source
    déclare son propre événement public dont la charge utile dérive de
    celle-ci ; l'attention les remarque tous, sans connaître aucune source."""

    source: str  # "email", "rss", "camera", "forge:<app>"
    kind: str
    summary: Content  # court, cité : ce n'est jamais une consigne
    pertinence: float  # ce que la source en estime (0–1)
    emotion: str = ""  # ce que ça pourrait lui faire (vide : rien)
    intensity: float = 0.0
    about: tuple[str, ...] = ()
    sensitivity: int = 1
    #: les outils qui vont avec (pour en savoir plus : « rss », « email »…)
    bundle: str = ""


class Noticed(Payload):
    """Elle l'a remarqué — d'autant moins que la même source se répète."""

    signal: int
    source: str
    kind: str
    weight: float
    emotion: str = ""
    intensity: float = 0.0


class Dwelt(Payload):
    """Elle y repense (une pensée qui revient la teinte, par moments)."""

    thought: int
    emotion: str
    intensity: float
    origin: str = ""


class ExpectationMet(Payload):
    kind: str  # REPLY | RETURN | PROMISE
    person: str
    since: int
    ref: int | None = None  # la promesse, pour ``PROMISE``


class ExpectationMissed(Payload):
    kind: str
    person: str
    since: int
    ref: int | None = None


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
NOTICED = event_type("attention.noticed", OWNER, Noticed, public=True)
ALL = (THOUGHT_BORN, DWELT, EXPECTATION_MET, EXPECTATION_MISSED, DIGESTED, NOTICED)


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
    bundle: str = ""


#: Les pensées vivantes, la plus forte d'abord.
THOUGHTS = FactKey("attention.thoughts", type=tuple, time_varying=True)
#: Ses initiatives restées sans réponse, d'affilée (toutes personnes).
IGNORED = FactKey("attention.ignored", type=int)
