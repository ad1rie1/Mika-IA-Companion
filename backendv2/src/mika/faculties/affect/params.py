"""Paramètres d'``affect``, dérivés du tempérament.

Le point de départ est la physique de la v1 (oscillateur amorti, cliquet
d'impulsion, repos circadien) ; ce qui la valide ici, ce sont les cibles de
comportement des tests, pas la v1 elle-même.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from mika.kernel.clock import DAY
from mika.kernel.dynamics import Oscillator
from mika.vocab.affect import Emotion
from mika.vocab.temperament import Temperament, geometric


class Osc(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mass: float
    damping: float
    stiffness: float

    def oscillator(self) -> Oscillator:
        return Oscillator(self.mass, self.damping, self.stiffness)

    @property
    def tau_s(self) -> float:
        return 2.0 * self.mass / self.damping


def _volatility(reactivity: float) -> float:
    r = max(0.0, min(1.0, reactivity))
    return 0.2 + r if r <= 0.5 else 0.7 + 0.6 * (r - 0.5)


def physics_of(t: Temperament) -> dict[str, Any]:
    """Masse, amortissement, raideur, gains : ce que réactivité, résilience
    et contagion règlent."""
    volatility = _volatility(t.reactivity)
    intensity_base = 0.3 + 0.6 * t.reactivity
    recovery = max(0.05, min(1.0, t.resilience))
    bleed = 0.6 * t.contagion

    mass = max(0.25, min(4.0, 1.0 / volatility))
    tau = 1800.0 * (240.0 / 1800.0) ** ((recovery - 0.05) / 0.95)
    zeta = 1.0 - 0.35 * volatility
    omega0 = 1.0 / (zeta * tau)
    g_mass = mass * 1.5
    g_tau = 2.0 * tau
    g_omega0 = 1.0 / (0.9 * g_tau)
    return {
        "person": Osc(mass=mass, damping=2.0 * mass / tau, stiffness=mass * omega0 * omega0),
        "mood": Osc(mass=g_mass, damping=2.0 * g_mass / g_tau, stiffness=g_mass * g_omega0 * g_omega0),
        "person_gain": min(0.75, max(0.1, intensity_base) * (0.5 + 0.5 * volatility)),
        "mood_gain": 0.0 if bleed <= 0 else min(0.5, 0.45 * bleed),
        "background": t.background,
        "anchor_half_life_us": round(geometric(6.0, 1.5, t.resilience) * DAY),
    }


_DEFAULTS = physics_of(Temperament())


class AffectParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    person: Osc = _DEFAULTS["person"]
    mood: Osc = _DEFAULTS["mood"]
    #: Part de la distance restante qu'une impulsion parcourt (posture).
    person_gain: float = _DEFAULTS["person_gain"]
    #: Même chose pour l'humeur générale, avant modulation par l'intensité
    #: (0 : elle cloisonne, ses relations ne touchent pas son humeur).
    mood_gain: float = _DEFAULTS["mood_gain"]
    mood_gain_floor: float = 0.4
    mood_gain_slope: float = 1.6
    mood_gain_max_factor: float = 2.0
    mood_gain_cap: float = 0.5
    #: Une impulsion alignée sur son humeur de fond est amplifiée (jamais
    #: atténuée : résister est déjà le rôle du repos).
    resonance: float = 0.45
    background: Emotion = _DEFAULTS["background"]
    background_weight: float = 0.15
    #: Part du repos d'une personne qui vient de ce qu'elle a déjà provoqué.
    anchor_weight: float = 0.6
    anchor_alpha: float = 0.15
    anchor_max: float = 0.7
    anchor_fold_interval_us: int = 30_000_000
    anchor_half_life_us: int = _DEFAULTS["anchor_half_life_us"]
    #: Tant qu'une déclaration est fraîche, c'est elle qui dit ce qu'elle
    #: ressent (la position n'a fait qu'une partie du chemin vers l'ancre).
    declared_window_us: int = 1_200_000_000
    rest_tolerance: float = 0.1
    fond_min: float = 0.2
    marked_intensity: float = 0.6
    anchored_min_norm: float = 0.4
    anchored_min_impulses: int = 2
    anchored_window_us: int = 900_000_000
    #: Débordement d'humeur → preuve d'initiative (log-odds).
    overflow_floor: float = 0.45
    overflow_max_evidence: float = 4.0

    @property
    def heal_rate(self) -> float:
        """Taux de guérison d'une ancre, par seconde."""
        return math.log(2.0) / (self.anchor_half_life_us / 1_000_000)


def derive(t: Temperament, overrides: Mapping[str, Any] | None = None) -> AffectParams:
    values = physics_of(t)
    values.update(overrides or {})
    return AffectParams(**values)


DEFAULT = derive(Temperament())
