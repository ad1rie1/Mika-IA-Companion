"""La faculté ``expression`` : ses réglages (``ExpressionParams`` : le murmure, et après quel silence une conversation
commence pour ce qu'elle se répète), son état (``ExpressionState`` : à qui elle allait écrire quand elle s'est murmuré
quelque chose) et l'objet ``EXPRESSION`` sur lequel ses autres modules déclarent leurs contributions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

from pydantic import BaseModel, ConfigDict

from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.state import FrozenDict


class ExpressionParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    murmur_chance: Annotated[float, Knob(
        label="Murmure : une fois sur", group="Le murmure", lo=0, hi=1, step=0.05,
        help="La probabilité qu'une initiative vers quelqu'un qui la regarde soit précédée d'une pensée à mi-voix "
             "(tirée du hasard de l'épisode) : souvent, pas toujours.")] = 0.35
    murmur_charged_chance: Annotated[float, Knob(
        label="Murmure quand ça la travaille", group="Le murmure", lo=0, hi=1, step=0.05,
        help="La même probabilité quand c'est une humeur qui déborde, une inquiétude ou une peine qui la "
             "pousse : on se parle plus à soi-même quand quelque chose pèse.")] = 0.6
    murmur_adrift: Annotated[float, Knob(
        label="Murmure sans suite", group="Le murmure", lo=0, hi=1, step=0.05,
        help="Parmi les murmures, la part où elle se ravise : elle y pense, puis n'écrit pas (l'initiative ne "
             "suit pas).")] = 0.2
    murmur_spacing_us: Annotated[int, Knob(
        label="Murmures espacés d'au moins", group="Le murmure", lo=5 * MINUTE, hi=12 * HOUR,
        help="Pas deux murmures plus rapprochés : une voix intérieure qui commente tout lasse.")] = HOUR
    opening_gap_us: Annotated[int, Knob(
        label="Une conversation commence après un silence de", group="Ce qu'elle se répète", lo=30 * MINUTE,
        hi=48 * HOUR,
        help="Son premier message après un tel silence (qu'elle vienne d'elle-même ou qu'elle réponde) est une entrée "
             "en matière : comparée aux précédentes avec la même personne, pour qu'elle ne commence pas chaque "
             "retrouvaille par la même formule.")] = 3 * HOUR


@dataclass(frozen=True, slots=True)
class ExpressionState:
    #: les murmures récents : corrélation de l'épisode → l'adresse de la personne à qui elle allait écrire (le
    #: murmure se montre sur ses écrans à elle, jamais à tout le monde)
    murmurs: FrozenDict[str, str] = field(default_factory=FrozenDict)


EXPRESSION = Faculty("expression", state=ExpressionState, init=lambda p: ExpressionState(), params=ExpressionParams,
                     state_version=2)

#: au plus tant de murmures retenus (le temps que leur livraison parte)
MURMURS_KEPT = 8


def params(p: ExpressionParams | None) -> ExpressionParams:
    return p if p is not None else ExpressionParams()
