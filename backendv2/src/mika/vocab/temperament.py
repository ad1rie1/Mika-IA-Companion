"""Le tempérament : huit curseurs et une humeur de fond.

C'est le seul étage « caractère » : chaque faculté en dérive ses paramètres
par une fonction pure, monotone et bornée (``derive``), et le résultat est
journalisé (``kernel.params_changed``) pour que le rejeu relise les paramètres
en vigueur à l'époque. La politique (divulgation, budgets, plafonds) n'en fait
pas partie : ce ne sont pas des traits de caractère.

À 0,5 partout, chaque curseur vaut « comme la plupart des gens ».
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from mika.vocab.affect import Emotion

Slider = Field(default=0.5, ge=0.0, le=1.0)


class Temperament(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Masse, amortissement, gain des impulsions : à quel point un mot la touche.
    reactivity: float = Slider
    #: Constantes de temps de l'humeur et des postures, guérison des rancunes.
    resilience: float = Slider
    #: Ce que ses relations font à son humeur générale (0 = cloisonnée).
    contagion: float = Slider
    #: Valence du repos, seuils d'ennui et de détresse.
    optimism: float = Slider
    #: Horizon du besoin social, rythme des relances.
    sociability: float = Slider
    #: Horizon de la curiosité, seuil d'ouverture d'une exploration.
    curiosity: float = Slider
    #: Budget de pas, demi-vie de l'envie, échecs avant blocage.
    perseverance: float = Slider
    #: Décalage du rythme circadien (0 = lève-tôt, 1 = oiseau de nuit).
    chronotype: float = Slider
    #: L'humeur vers laquelle son repos penche et avec laquelle elle résonne.
    background: Emotion = Emotion.HAPPY


def lerp(lo: float, hi: float, x: float) -> float:
    return lo + (hi - lo) * max(0.0, min(1.0, x))


def geometric(lo: float, hi: float, x: float) -> float:
    """Interpolation géométrique (pour les constantes de temps)."""
    x = max(0.0, min(1.0, x))
    return lo * (hi / lo) ** x
