"""Contrat de ``body`` : le rythme, l'énergie, le sommeil.

Le sommeil suit un modèle à deux processus : une **pression** qui monte
pendant la veille et retombe pendant le sommeil, et le **rythme circadien**
qui module les seuils d'endormissement et de réveil. Elle s'endort quand la
pression franchit le seuil haut (et que plus personne ne lui parle depuis un
moment), se réveille quand elle retombe sous le seuil bas — ou quand un
message la réveille.
"""

from __future__ import annotations

import enum

from mika.kernel.events import Payload, event_type
from mika.kernel.facts import FactKey
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


FELL_ASLEEP = event_type("body.fell_asleep", OWNER, FellAsleep, public=True)
WOKE = event_type("body.woke", OWNER, Woke, public=True)
ALL = (FELL_ASLEEP, WOKE)



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
