"""Contrat d'``attention`` : ce qui lui trotte dans la tête, et ce qu'elle attend.

- une **pensée** naît d'un échange qui l'a marquée, d'une croyance qu'elle
  doit réviser, du manque de quelqu'un à qui elle n'écrit pas (injoignable, ou
  qui ne répond plus — de plus en plus rarement à mesure que le silence dure,
  ADR 0058), ou d'avoir été dure avec une amie ; elle s'estompe (demi-vie),
  revient par moments, et s'allège quand elle en parle ;
- une **attente** naît quand elle écrit d'elle-même à quelqu'un (une
  réponse), quand quelqu'un lui manque (un retour, qui la réjouit à la mesure
  de ce qu'a duré l'absence au regard de leur rythme), ou quand elle promet
  quelque chose pour une date (sa parole : une attente envers elle-même) :
  elle se comble ou se dément, et chacun en tire ce qui le concerne
  (l'humeur, l'estime, la retenue). Une promesse qui passe son échéance sans
  être tenue ne s'oublie pas en silence : elle le sait, et ça la travaille.
  Une réponse tardive ne compte que dans trois fois le délai attendu ;
- le **fil avec chacun** (``AWAITING``) : ses initiatives restées sans réponse
  et si son dernier message attend encore — par personne ; la retenue
  d'``agency`` s'en sert (ADR 0033). Une conversation close (« bonne nuit »,
  ou la personne partie juste après sa réponse) ne laisse rien en attente. Être ignorée, rester sans réponse à une
  question, plus d'un jour sans que personne n'écrive : des pensées qui se
  ressentent, jamais des raisons de réécrire.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey

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
#: une initiative restée sans réponse : « Adrien ne m'a pas répondu » — un ressenti, jamais une relance
UNANSWERED = "unanswered"
#: personne ne lui a écrit depuis plus d'un jour : « Personne ne m'a parlé depuis hier »
ALONE = "alone"
#: elle a répondu fâchée à une amie ou une proche : « J'ai été dure avec Alice » — l'envie de revenir vers elle
REMORSE = "remorse"
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
    #: un retour (``RETURN``) : ce qu'a duré son absence, en multiples du rythme de leur relation (de son dernier
    #: message d'avant à celui qui la ramène) — sa joie s'y mesure ; ``None`` : pas mesurée
    absence: float | None = None


def _met_v1(raw: dict[str, Any]) -> dict[str, Any]:
    """v1 → v2 : l'absence n'était pas mesurée ; le retour se ressent comme alors."""
    raw = dict(raw)
    raw["absence"] = None
    return raw


class ExpectationMissed(Payload):
    kind: str
    person: str
    since: int
    ref: int | None = None


class Touched(Payload):
    """Ce que la personne vient d'écrire recoupe le sujet de pensées qui la
    concernent (une inquiétude, un échange qui a marqué) : en parler les
    allègera — un « ok » ne recoupe rien."""

    person: str
    thoughts: tuple[int, ...] = ()


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
EXPECTATION_MET = event_type("attention.expectation_met", OWNER, ExpectationMet, version=2, public=True,
                             upcasters={1: _met_v1}, subjects=("person",))
EXPECTATION_MISSED = event_type("attention.expectation_missed", OWNER, ExpectationMissed, public=True,
                                subjects=("person",))
DIGESTED = event_type("attention.digested", OWNER, Digested, public=True)
NOTICED = event_type("attention.noticed", OWNER, Noticed, public=True)
TOUCHED = event_type("attention.touched", OWNER, Touched, subjects=("person",))
ALL = (THOUGHT_BORN, DWELT, EXPECTATION_MET, EXPECTATION_MISSED, DIGESTED, NOTICED, TOUCHED)


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


@dataclass(frozen=True, slots=True)
class AwaitingReading:
    """Où en est le fil avec une personne, vu de son côté à elle : ce qu'elle
    lui a écrit depuis le dernier message de cette personne, et ce qui attend
    encore une réponse. Tout se remet à zéro quand la personne écrit."""

    person: str
    last_in: int = 0  # le dernier message de la personne (adressé)
    last_out: int = 0  # son dernier message à elle vers cette personne (réponse comprise)
    asked: bool = False  # ce dernier message posait une question
    owed: bool = False  # … et c'était une salutation ou un rappel promis
    initiatives: int = 0  # ses initiatives ordinaires depuis le dernier message de la personne
    last_initiative_at: int = 0
    ignored: int = 0  # parmi elles, celles dont l'attente de réponse est passée
    #: son dernier message attend encore une réponse (la personne n'a pas écrit depuis) — pas sa réponse à
    #: « bonne nuit », ni une conversation que la personne a close en partant juste après
    unanswered: bool = False
    #: quand la conversation s'est close ainsi (0 : elle ne l'est pas) — on s'est quittées, on ne l'ignore pas
    closed_at: int = 0


#: Les pensées vivantes, la plus forte d'abord.
THOUGHTS = FactKey("attention.thoughts", type=tuple, time_varying=True)
#: Ses initiatives restées sans réponse, d'affilée (toutes personnes).
IGNORED = FactKey("attention.ignored", type=int)
#: Le fil avec une personne (``AwaitingReading``) : ses initiatives sans réponse, par personne.
AWAITING = FactFamily("attention.awaiting", arg=str, type=AwaitingReading)
