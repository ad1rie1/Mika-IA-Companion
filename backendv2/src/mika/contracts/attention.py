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
  Une réponse tardive ne compte que dans trois fois le délai attendu. Par
  messagerie, quand l'application de la personne dit ce qu'elle a lu
  (``presence.read``), un message pas encore vu n'attend rien encore (trois
  jours au plus) et le délai court à partir de la lecture ;
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

from pydantic import model_validator

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey
from mika.vocab.lineage import Lineage, subjects

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
#: elle a menti à quelqu'un (pour botter en touche, garder ce qu'on lui a confié) : « J'ai menti à Bob » — une gêne
#: qu'elle porte, jamais une relance
LIE = "lie"
#: un souvenir qui lui revient de lui-même, seule et désœuvrée (une date anniversaire, ce qu'elle a entre les mains,
#: ou sans raison) : « Il y a un an jour pour jour… » — il se ressent, il peut se raconter à qui il concerne ; jamais
#: une raison d'écrire à elle seule (ADR 0098)
REMINISCENCE = "reminiscence"
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
    sources: tuple[int, ...] = ()  # toutes les preuves citées par une pensée composée
    bundle: str = ""  # les outils qui vont avec (une pensée née d'un signal)
    #: ce qu'elle sait d'où la pensée vient (une croyance révisée : l'ancienne et la nouvelle) et devant qui ses
    #: sources permettent de la redire ; ``None`` : une pensée d'avant, ou qui ne vient pas de ce qu'elle sait
    lineage: Lineage | None = None

    @model_validator(mode="after")
    def _inherited_subjects(self):
        # qui ses sources concernent, et qui les a confiées : l'oubli de l'un d'eux l'atteint
        about = tuple(sorted({*self.about, *subjects(self.lineage)}))
        if self.lineage is not None and about != self.about:
            object.__setattr__(self, "about", about)
        return self


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


class Anticipated(Payload):
    """Ce qu'elle attend le plus en ce moment (ADR 0086) : un moment de quelqu'un qui compte pour elle, ou du monde
    qui lui tient à cœur, qui approche — avec espoir (``hopeful``) ou inquiétude (``anxious``), d'autant plus fort
    qu'il est proche, important, probable, et que la personne lui est chère. Une fois par jour et par moment, le seul
    qui domine."""

    event: int
    thread: int = 0
    emotion: str
    weight: float
    about: tuple[str, ...] = ()
    when: int = 0


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
ANTICIPATED = event_type("attention.anticipated", OWNER, Anticipated, public=True, subjects=("about",))
ALL = (THOUGHT_BORN, DWELT, EXPECTATION_MET, EXPECTATION_MISSED, DIGESTED, NOTICED, TOUCHED, ANTICIPATED)


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
    #: devant qui ses sources permettent de la redire (``None`` : la règle de ses personnes et de sa sensibilité)
    lineage: Lineage | None = None


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
    #: quand la personne a lu sa dernière initiative (son application le dit, si elle l'a permis) ; 0 : pas encore,
    #: ou on ne le sait pas (un journal ancien, un client qui n'en dit rien, un écran qui se tait sur ce qu'on y lit).
    #: Ça reste vrai quand elle écrit : jusqu'à la prochaine initiative
    seen_at: int = 0
    #: … elle ne l'a pas encore lue : son application dit ce qu'elle a lu depuis, et ce n'est pas encore ça
    unseen: bool = False


#: Les pensées vivantes, la plus forte d'abord.
THOUGHTS = FactKey("attention.thoughts", type=tuple, time_varying=True)
#: Ce qu'elle attend le plus en ce moment (ADR 0086), s'il y en a un qui domine (``Anticipated``, sinon ``None``) :
#: le moment qui approche, l'émotion et son poids.
ANTICIPATION = FactKey("attention.anticipation", type=object, time_varying=True)
#: Ses initiatives restées sans réponse, d'affilée (toutes personnes).
IGNORED = FactKey("attention.ignored", type=int)
#: Le fil avec une personne (``AwaitingReading``) : ses initiatives sans réponse, par personne.
AWAITING = FactFamily("attention.awaiting", arg=str, type=AwaitingReading)
