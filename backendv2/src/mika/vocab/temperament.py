"""Le tempérament : huit curseurs et une humeur de fond.

C'est le seul étage « caractère » : chaque faculté en dérive ses paramètres
par une fonction pure, monotone et bornée (``derive``), et le résultat est
journalisé (``kernel.params_changed``) pour que le rejeu relise les paramètres
en vigueur à l'époque. La politique (divulgation, budgets, plafonds) n'en fait
pas partie : ce ne sont pas des traits de caractère.

À 0,5 partout, chaque curseur vaut « comme la plupart des gens ».
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from mika.kernel.forms import Knob
from mika.vocab.affect import FR, Emotion

Slider = Field(default=0.5, ge=0.0, le=1.0)
_MOODS = tuple(sorted(((e.value, FR[e]) for e in Emotion), key=lambda m: m[1]))


def _slider(label: str, help: str, order: int, lo: str = "", hi: str = "") -> Knob:
    ends = f" (0 : {lo} · 1 : {hi})" if lo else ""
    return Knob(label=label, help=help + ends, widget="slider", lo=0.0, hi=1.0, step=0.05, advanced=False,
                order=order)


class Temperament(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Masse, amortissement, gain des impulsions : à quel point un mot la touche.
    reactivity: Annotated[float, _slider("Réactivité", "À quel point un mot la touche.", 10,
                                         "imperturbable", "à fleur de peau")] = Slider
    #: Constantes de temps de l'humeur et des postures, guérison des rancunes.
    resilience: Annotated[float, _slider("Résilience", "Le temps qu'il lui faut pour revenir au calme, "
                                         "pardonner.", 20, "lente", "rapide")] = Slider
    #: Ce que ses relations font à son humeur générale (0 = cloisonnée).
    contagion: Annotated[float, _slider("Contagion", "Ce que ses relations font à son humeur générale.", 30,
                                        "cloisonnée", "poreuse")] = Slider
    #: Valence du repos, seuils d'ennui et de détresse.
    optimism: Annotated[float, _slider("Optimisme", "La couleur de son repos, ses seuils d'ennui et de "
                                       "détresse.", 40, "sombre", "lumineuse")] = Slider
    #: Horizon du besoin social, rythme des relances.
    sociability: Annotated[float, _slider("Sociabilité", "Son besoin de compagnie, le rythme de ses relances.",
                                          50, "solitaire", "sociable")] = Slider
    #: Horizon de la curiosité, seuil d'ouverture d'une exploration.
    curiosity: Annotated[float, _slider("Curiosité", "Son envie d'apprendre, d'explorer.", 60,
                                        "casanière", "exploratrice")] = Slider
    #: Budget de pas, demi-vie de l'envie, échecs avant blocage.
    perseverance: Annotated[float, _slider("Persévérance", "Combien elle s'accroche à ce qu'elle entreprend.",
                                           70, "vite lassée", "tenace")] = Slider
    #: Décalage du rythme circadien (0 = lève-tôt, 1 = oiseau de nuit).
    chronotype: Annotated[float, _slider("Chronotype", "Son rythme de la journée.", 80,
                                         "lève-tôt", "oiseau de nuit")] = Slider
    #: L'humeur vers laquelle son repos penche et avec laquelle elle résonne.
    background: Annotated[Emotion, Knob(label="Humeur de fond", help="L'humeur vers laquelle son repos penche, "
                                        "avec laquelle elle résonne.", advanced=False, order=90,
                                        choices=_MOODS)] = Emotion.HAPPY


def lerp(lo: float, hi: float, x: float) -> float:
    return lo + (hi - lo) * max(0.0, min(1.0, x))


def geometric(lo: float, hi: float, x: float) -> float:
    """Interpolation géométrique (pour les constantes de temps)."""
    x = max(0.0, min(1.0, x))
    return lo * (hi / lo) ** x
