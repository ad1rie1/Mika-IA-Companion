"""Contrat de ``body`` : le rythme, l'énergie, le sommeil.

Le sommeil suit un modèle à deux processus : une **pression** qui monte
pendant la veille et retombe pendant le sommeil, et le **rythme circadien**
qui module les seuils d'endormissement et de réveil. Elle s'endort quand la
pression franchit le seuil haut (et que plus personne ne lui parle depuis un
moment), se réveille quand elle retombe sous le seuil bas — ou quand un
message la réveille : la nuit, seulement celui d'une amie ou d'une proche, ou
quelque chose d'urgent (``body.roused``). Les autres messages attendent son
réveil (``body.waited``) : elle y répond le matin. Un réveil par API qui passe
outre son rythme la tire du sommeil aussi (ADR 0068).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from mika.kernel.events import Payload, event_type
from mika.kernel.facts import FactFamily, FactKey
from mika.vocab.circadian import Phase, Profile

OWNER = "body"

#: Veto : elle dort.
ASLEEP = "asleep"
#: Décalage : elle est fatiguée.
TIRED = "tired"
#: Veto : elle vient de se réveiller.
WAKING = "waking"
#: Veto : tirée du sommeil en pleine nuit, elle répond (ou dit l'urgent) et se
#: rendort — elle ne prend pas d'initiative ordinaire.
WOKEN_AT_NIGHT = "woken_at_night"
#: La barre de réveil (log-odds) : une raison qui la passe *à elle seule* la
#: réveille (un rappel urgent à l'heure dite) ; une somme d'envies, jamais.
#: Une politique, pas un trait : elle ne se calibre pas.
WAKE_BAR = 15.0


class SleepPhase(enum.StrEnum):
    AWAKE = "awake"
    LIGHT_SLEEP = "light_sleep"
    REM = "rem"
    DEEP_SLEEP = "deep_sleep"


class FellAsleep(Payload):
    at: int  # l'instant du croisement (un rattrapage après un arrêt le date au passé)
    pressure: float


class Woke(Payload):
    at: int
    pressure: float


class Roused(Payload):
    """Un message l'a tirée du sommeil : une amie, une proche, ou quelque chose
    d'urgent — ou un réveil par API qui passe outre son rythme (``message`` : le
    ``seq`` de l'appel, sans adresse). Un jugement enregistré (le rejeu retombe
    sur le même réveil)."""

    message: int
    handle: str
    person: str = ""
    reason: str = ""  # CLOSE_ONE | URGENT | CALL


class Waited(Payload):
    """Un message arrivé pendant sa nuit, qui ne la réveille pas : il attend son
    réveil, et elle y répondra le matin."""

    message: int
    handle: str
    person: str = ""


#: Raisons d'un réveil par message (et par un réveil par API, ADR 0068).
CLOSE_ONE, URGENT, CALL = "close", "urgent", "call"

FELL_ASLEEP = event_type("body.fell_asleep", OWNER, FellAsleep, public=True)
WOKE = event_type("body.woke", OWNER, Woke, public=True)
ROUSED = event_type("body.roused", OWNER, Roused, public=True, subjects=("person",))
WAITED = event_type("body.waited", OWNER, Waited, public=True, subjects=("person",))
#: Ce qui change son sommeil (s'endormir, se réveiller, être tirée du sommeil).
ALL = (FELL_ASLEEP, WOKE, ROUSED)


@dataclass(frozen=True, slots=True)
class Rousing:
    """Une fois où elle a été tirée du sommeil pendant une nuit (``body.roused``) : quand, par quelle adresse,
    quelle personne (vide : un réveil par API, ou une adresse sans personne) et pourquoi."""

    at: int
    handle: str
    person: str
    reason: str  # CLOSE_ONE | URGENT | CALL


@dataclass(frozen=True, slots=True)
class NightReading:
    """Sa dernière nuit, finie : de l'endormissement au réveil qui l'a close, ce qu'elle a vraiment dormi (sans
    les moments où un message l'a tenue éveillée), les fois où on l'a tirée du sommeil, une nuit courte (contre
    ses nuits d'habitude), coupée, ou commencée tard (une conversation l'a tenue éveillée au-delà de son seuil)."""

    start: int
    end: int
    duration_us: int
    rousings: tuple[Rousing, ...]
    short: bool
    broken: bool
    late: bool


RHYTHM = FactKey("body.rhythm", type=Profile, doc="le profil circadien en vigueur")
PHASE = FactKey("body.phase", type=Phase, time_varying=True)
ENERGY = FactKey("body.energy", type=float, time_varying=True)
SLEEP = FactKey("body.sleep", type=SleepPhase, time_varying=True)
#: Depuis quand elle est éveillée (0 si elle dort).
AWAKE_SINCE = FactKey("body.awake_since", type=int)
#: Depuis quand elle dort (0 si elle est éveillée).
ASLEEP_SINCE = FactKey("body.asleep_since", type=int)
#: Ce qui a changé son sommeil pour la dernière fois (pour les gardes).
EPOCH = FactKey("body.epoch", type=tuple)
#: Tirée du sommeil en pleine nuit par un message : elle répond, puis va se rendormir.
NIGHT_WAKING = FactKey("body.night_waking", type=bool, time_varying=True)
#: ``REPLY_WAIT(seq)`` : la réponse à ce message attend-elle son réveil ? ``None`` : rien de particulier ;
#: ``0`` : elle dort (ou a été tirée du sommeil par quelqu'un d'autre), la réponse attend ; sinon l'instant
#: d'où la réponse est due (son réveil).
REPLY_WAIT = FactFamily("body.reply_wait", arg=int, type=object, time_varying=True)
#: Sa dernière nuit (``NightReading``), du réveil qui l'a close jusqu'au milieu de sa journée ; ``None`` : elle dort
#: encore, n'est tirée du sommeil que le temps d'un message, ou sa nuit est loin (une nuit blanche n'en a pas).
LAST_NIGHT = FactKey("body.last_night", type=object, time_varying=True)
