"""``body`` : le rythme circadien, l'énergie, le sommeil.

En M1 : le rythme (profil décalé par le chronotype), la phase et l'énergie à
l'instant, et une phase de sommeil toujours éveillée — la nuit (pression
homéostatique, endormissement, réveil) arrive en M5.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import body as c
from mika.kernel.faculty import Faculty, Zone
from mika.kernel.frame import Frame
from mika.vocab import circadian
from mika.vocab.episodes import CONVERSATIONAL
from mika.vocab.temperament import Temperament


class BodyParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Décalage du rythme, en minutes (chronotype : ±2 h autour du profil type).
    shift_minutes: int = 0


def derive(t: Temperament, overrides: Mapping[str, Any] | None = None) -> BodyParams:
    return BodyParams(shift_minutes=round((t.chronotype - 0.5) * 240), **dict(overrides or {}))


@dataclass(frozen=True, slots=True)
class BodyState:
    pass


BODY = Faculty("body", state=BodyState, init=lambda p: BodyState(), params=BodyParams, derive=derive)


def rhythm(params: BodyParams | None) -> circadian.Profile:
    shift = params.shift_minutes if params is not None else 0
    return circadian.DEFAULT.shifted(shift) if shift else circadian.DEFAULT


@BODY.fact(c.RHYTHM)
def _rhythm(s: BodyState, cx) -> circadian.Profile:
    return rhythm(cx.params)


@BODY.fact(c.PHASE)
def _phase(s: BodyState, cx) -> circadian.Phase:
    return circadian.phase_of(cx.local(), rhythm(cx.params))


@BODY.fact(c.ENERGY)
def _energy(s: BodyState, cx) -> float:
    return circadian.energy(cx.local(), rhythm(cx.params))


@BODY.fact(c.SLEEP)
def _sleep(s: BodyState, cx) -> c.SleepPhase:
    return c.SleepPhase.AWAKE


@BODY.section("rhythm", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=40, title="TON RYTHME")
def _rhythm_section(s: BodyState, frame: Frame, enrich: Any) -> str:
    profile = frame.get(c.RHYTHM)
    return circadian.describe(frame.local(), profile, frame.get(c.ENERGY))
