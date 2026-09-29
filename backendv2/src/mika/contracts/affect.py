"""Contrat d'``affect`` : l'humeur, la posture envers chacun, la chaleur."""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.facts import FactFamily, FactKey
from mika.vocab.affect import Declared, Emotion, Vec3

OWNER = "affect"

#: Raisons de preuve d'initiative.
MOOD_OVERFLOW = "mood_overflow"


@dataclass(frozen=True, slots=True)
class MoodReading:
    position: Vec3
    home: Vec3
    felt: Emotion  # ce que dit l'écart au repos
    felt_intensity: float
    overflow: float  # ce que lisent les portes (écart au repos)
    label: Emotion  # la position absolue (ce que montre le visage)
    intensity: float


@dataclass(frozen=True, slots=True)
class StanceReading:
    person: str
    position: Vec3
    home: Vec3  # repos propre de la personne
    felt: Emotion
    felt_intensity: float
    declared: Declared | None  # ce qu'elle vient de déclarer, si c'est encore frais
    anchor: Vec3 | None
    at_rest: bool
    anchored: bool  # une posture construite par plusieurs tours concordants


@dataclass(frozen=True, slots=True)
class Face:
    """Ce que montrent le visage et les trames : 60 % la posture envers la
    personne, 40 % son humeur à elle."""

    emotion: Emotion
    intensity: float
    blend: tuple[tuple[Emotion, float], ...]
    person: tuple[Emotion, float]
    mood: tuple[Emotion, float]


MOOD = FactKey("affect.mood", type=MoodReading, time_varying=True)
STANCE = FactFamily("affect.stance", arg=str, type=StanceReading, time_varying=True)
#: Composante plaisir de l'ancre (guérie à l'instant), dans [0, 1].
WARMTH = FactFamily("affect.warmth", arg=str, type=float, time_varying=True)
#: Ce que cette personne a installé, signé, dans [-1, 1] : la part du chemin
#: parcourue depuis le repos commun vers le plaisir maximal (> 0) ou minimal
#: (< 0).
REGARD = FactFamily("affect.regard", arg=str, type=float, time_varying=True)
#: L'hostilité que cette personne a installée, dans [0, 1] : un écart au repos
#: déplaisant **et** dominant (la colère, le dégoût, la frustration) — pas le
#: chagrin partagé, qui est déplaisant mais sans rancune. La rancune se lit ici.
HOSTILITY = FactFamily("affect.hostility", arg=str, type=float, time_varying=True)
FACE = FactFamily("affect.face", arg=str, type=Face, time_varying=True)
