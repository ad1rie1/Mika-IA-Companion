"""Contrat de ``body`` : le rythme, l'énergie, le sommeil."""

from __future__ import annotations

import enum

from mika.kernel.facts import FactKey
from mika.vocab.circadian import Phase, Profile

OWNER = "body"


class SleepPhase(enum.StrEnum):
    AWAKE = "awake"
    LIGHT_SLEEP = "light_sleep"
    REM = "rem"
    DEEP_SLEEP = "deep_sleep"


RHYTHM = FactKey("body.rhythm", type=Profile, doc="le profil circadien en vigueur")
PHASE = FactKey("body.phase", type=Phase, time_varying=True)
ENERGY = FactKey("body.energy", type=float, time_varying=True)
SLEEP = FactKey("body.sleep", type=SleepPhase, time_varying=True)
