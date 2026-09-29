"""Paramètres d'``affect``, dérivés du tempérament.

Le point de départ est la physique de la v1 (oscillateur amorti, cliquet
d'impulsion, repos circadien) ; ce qui la valide ici, ce sont les cibles de
comportement des tests, pas la v1 elle-même.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.dynamics import Oscillator
from mika.kernel.forms import Knob
from mika.vocab.affect import FR, Emotion
from mika.vocab.temperament import Temperament, geometric, lerp

_MOODS = tuple(sorted(((e.value, FR[e]) for e in Emotion), key=lambda m: m[1]))


class Osc(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mass: Annotated[float, Knob(
        label="Masse (inertie)", lo=0.2, hi=10, step=0.05,
        help="L'inertie du retour au repos : à amortissement égal, plus elle est grande, plus le retour est lent "
             "(constante de temps = 2 × masse ÷ amortissement). Une impulsion, elle, déplace l'état aussitôt.")]
    damping: Annotated[float, Knob(
        label="Amortissement", lo=0.0001, hi=0.05, step=0.0001,
        help="Dissipe l'écart au repos : plus il est fort, plus le retour est court. Bien au-delà de "
             "2 × √(masse × raideur), le retour devient une lente reptation.")]
    stiffness: Annotated[float, Knob(
        label="Raideur (rappel vers le repos)", lo=1e-8, hi=5e-4, step=1e-8,
        help="La force qui ramène l'état vers son repos : trop faible devant l'amortissement, le retour se "
             "traîne ; trop forte, l'état oscille autour du repos avant de s'y poser.")]

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
        "relational_scale": min(1.0, 2.0 * max(0.0, t.contagion)),
        "background": t.background,
        "anchor_half_life_us": round(geometric(6.0, 1.5, t.resilience) * DAY),
        # l'optimisme colore le repos : un peu plus (ou moins) de plaisir quand rien ne se passe
        "rest_valence": round(lerp(-0.12, 0.12, t.optimism), 4),
    }


_DEFAULTS = physics_of(Temperament())


class AffectParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    person: Annotated[Osc, Knob(
        label="Posture envers une personne", group="Oscillateurs",
        help="L'oscillateur de chaque posture (ce qu'elle ressent pour quelqu'un) : comment elle revient à son "
             "repos après une impulsion. Dérivé de la réactivité et de la résilience.")] = _DEFAULTS["person"]
    mood: Annotated[Osc, Knob(
        label="Humeur générale", group="Oscillateurs",
        help="L'oscillateur de son humeur générale, plus lent que les postures. Dérivé de la réactivité et de "
             "la résilience.")] = _DEFAULTS["mood"]
    #: Part de la distance restante qu'une impulsion parcourt (posture).
    person_gain: Annotated[float, Knob(
        label="Gain d'une impulsion (posture)", group="Impulsions", lo=0, hi=1, step=0.01,
        help="Part de la distance restante vers l'émotion déclarée qu'une impulsion fait parcourir à sa posture "
             "envers la personne (avant résonance). Dérivé de la réactivité.")] = _DEFAULTS["person_gain"]
    #: Même chose pour l'humeur générale, avant modulation par l'intensité
    #: (0 : elle cloisonne, ses relations ne touchent pas son humeur).
    mood_gain: Annotated[float, Knob(
        label="Gain d'une impulsion (humeur)", group="Impulsions", lo=0, hi=1, step=0.01,
        help="La même part pour son humeur générale, avant modulation par l'intensité et la proximité. 0 : elle "
             "cloisonne, ses échanges ne touchent pas son humeur. Dérivé de la contagion.")] = _DEFAULTS["mood_gain"]
    mood_gain_floor: Annotated[float, Knob(
        label="Humeur : part à intensité nulle", group="Impulsions", lo=0, hi=2, step=0.05,
        help="Le gain d'humeur vaut gain × (cette part + pente × intensité déclarée), borné par le facteur et le "
             "plafond ci-dessous.")] = 0.4
    mood_gain_slope: Annotated[float, Knob(
        label="Humeur : pente selon l'intensité", group="Impulsions", lo=0, hi=5, step=0.1,
        help="Combien l'intensité déclarée renforce le gain d'humeur : une émotion forte la marque davantage.")] = 1.6
    mood_gain_max_factor: Annotated[float, Knob(
        label="Humeur : facteur maximal", group="Impulsions", lo=0, hi=5, step=0.1,
        help="L'intensité ne multiplie jamais le gain d'humeur au-delà de ce facteur.")] = 2.0
    mood_gain_cap: Annotated[float, Knob(
        label="Humeur : plafond du gain", group="Impulsions", lo=0, hi=1, step=0.05,
        help="Aucune impulsion ne fait parcourir à son humeur plus que cette part du chemin, proximité "
             "comprise.")] = 0.5
    #: l'écart de dominance qui fait d'un déplaisir une hostilité pleine
    hostility_dominance: Annotated[float, Knob(
        label="Dominance d'une hostilité pleine", group="Impulsions", lo=0.05, hi=1, step=0.05,
        help="L'écart de dominance (ancre au-dessus du repos) qui fait d'un déplaisir installé une hostilité "
             "pleine. Plus petit : la moindre colère installée devient rancune (plus d'amitié ni "
             "d'initiative).")] = 0.25
    #: ce qu'une évaluation née d'une relation garde (0 : elle cloisonne)
    relational_scale: Annotated[float, Knob(
        label="Ce que garde une émotion relationnelle", group="Impulsions", lo=0, hi=1, step=0.05,
        help="La part d'intensité que garde une émotion née d'une relation (un manque, une attente comblée). "
             "0 : elle cloisonne. Dérivé de la contagion.")] = _DEFAULTS["relational_scale"]
    #: Ce que vit la relation déborde sur son humeur selon la proximité : un
    #: inconnu qui l'insulte la touche moins qu'une amie qui pleure.
    bleed_stranger: Annotated[float, Knob(
        label="Débordement : inconnue", group="Contagion selon la proximité", lo=0, hi=2, step=0.05,
        help="Multiplie le gain d'humeur d'un échange avec une inconnue : ce qu'elle vit avec quelqu'un touche "
             "son humeur selon leur proximité.")] = 0.5
    bleed_acquaintance: Annotated[float, Knob(
        label="Débordement : connaissance", group="Contagion selon la proximité", lo=0, hi=2, step=0.05,
        help="Le même multiplicateur pour une connaissance.")] = 0.8
    bleed_friend: Annotated[float, Knob(
        label="Débordement : amie", group="Contagion selon la proximité", lo=0, hi=2, step=0.05,
        help="Le même multiplicateur pour une amie.")] = 1.0
    bleed_close: Annotated[float, Knob(
        label="Débordement : proche", group="Contagion selon la proximité", lo=0, hi=2, step=0.05,
        help="Le même multiplicateur pour un proche (toujours sous le plafond du gain d'humeur).")] = 1.2

    def bleed(self, closeness: str) -> float:
        return {"stranger": self.bleed_stranger, "acquaintance": self.bleed_acquaintance, "friend": self.bleed_friend,
                "close": self.bleed_close}.get(closeness, 1.0)
    #: Une impulsion alignée sur son humeur de fond est amplifiée (jamais
    #: atténuée : résister est déjà le rôle du repos).
    resonance: Annotated[float, Knob(
        label="Résonance avec l'humeur de fond", group="Repos et ancre", lo=0, hi=2, step=0.05,
        help="Une impulsion alignée sur son humeur de fond voit son gain multiplié jusqu'à (1 + résonance) ; "
             "jamais atténuée. 0 : pas de résonance.")] = 0.45
    background: Annotated[Emotion, Knob(
        label="Humeur de fond", group="Repos et ancre", choices=_MOODS,
        help="L'humeur vers laquelle son repos penche et avec laquelle elle résonne ; vient du "
             "tempérament.")] = _DEFAULTS["background"]
    background_weight: Annotated[float, Knob(
        label="Poids de l'humeur de fond", group="Repos et ancre", lo=0, hi=1, step=0.05,
        help="Combien son repos commun penche vers l'humeur de fond ; le reste vient de la teinte du moment de "
             "la journée.")] = 0.15
    rest_valence: Annotated[float, Knob(
        label="Couleur du repos", group="Repos et ancre", lo=-0.3, hi=0.3, step=0.01,
        help="Ce que l'optimisme ajoute au plaisir de son repos (négatif : un repos plus terne). Son humeur y "
             "revient quand rien ne se passe ; ses relations aussi, par la contagion.")] = 0.0
    #: Part du repos d'une personne qui vient de ce qu'elle a déjà provoqué.
    anchor_weight: Annotated[float, Knob(
        label="Poids de l'ancre dans le repos", group="Repos et ancre", lo=0, hi=1, step=0.05,
        help="Part du repos d'une posture qui vient de ce que la personne a déjà provoqué (l'ancre) ; le reste "
             "est le repos commun.")] = 0.6
    anchor_alpha: Annotated[float, Knob(
        label="Ce qu'une déclaration fond dans l'ancre", group="Repos et ancre", lo=0, hi=1, step=0.01,
        help="À chaque déclaration envers une personne identifiable, l'ancre se rapproche de l'émotion déclarée "
             "de cette part. Plus grand : une seule phrase installe une rancune ou une tendresse.")] = 0.15
    anchor_max: Annotated[float, Knob(
        label="Norme maximale d'une ancre", group="Repos et ancre", lo=0, hi=1.2, step=0.05,
        help="Ce qu'une relation peut installer au plus : l'ancre ne s'éloigne jamais de l'origine "
             "au-delà.")] = 0.7
    anchor_fold_interval_us: Annotated[int, Knob(
        label="Intervalle entre deux fontes", group="Repos et ancre", lo=0, hi=HOUR,
        help="L'ancre n'absorbe pas plus d'une déclaration par intervalle : une rafale de messages compte pour "
             "une.")] = 30_000_000
    anchor_half_life_us: Annotated[int, Knob(
        label="Demi-vie de l'ancre", group="Repos et ancre", lo=6 * HOUR, hi=30 * DAY,
        help="L'ancre guérit vers le repos commun avec cette demi-vie (effacée au-delà de vingt) : le temps "
             "qu'une rancune ou une tendresse s'estompe. Dérivée de la résilience.")] = _DEFAULTS["anchor_half_life_us"]
    #: Tant qu'une déclaration est fraîche, c'est elle qui dit ce qu'elle
    #: ressent (la position n'a fait qu'une partie du chemin vers l'ancre).
    declared_window_us: Annotated[int, Knob(
        label="Fraîcheur d'une déclaration", group="Lecture", lo=MINUTE, hi=2 * HOUR,
        help="Tant que sa dernière émotion déclarée envers quelqu'un est plus récente, c'est elle que le prompt "
             "lui rappelle pour cette personne, plutôt que la position de sa posture.")] = 1_200_000_000
    rest_tolerance: Annotated[float, Knob(
        label="Tolérance du repos", group="Lecture", lo=0, hi=0.5, step=0.01,
        help="En deçà de cette distance à son repos, son humeur est « comme d'habitude » et sa posture envers "
             "quelqu'un sans rien de particulier.")] = 0.1
    fond_min: Annotated[float, Knob(
        label="Fond installé : intensité minimale", group="Lecture", lo=0, hi=1, step=0.05,
        help="Au repos, le fond qu'une relation a installé (l'ancre) n'est dit dans le prompt qu'au-delà de "
             "cette intensité.")] = 0.2
    marked_intensity: Annotated[float, Knob(
        label="Humeur « nettement plus que d'habitude »", group="Lecture", lo=0, hi=1, step=0.05,
        help="Quand son humeur va dans le sens de son humeur de fond, au-delà de cette intensité le prompt dit "
             "« nettement plus que d'habitude ».")] = 0.6
    anchored_min_norm: Annotated[float, Knob(
        label="Posture ancrée : intensité minimale", group="Lecture", lo=0, hi=1.2, step=0.05,
        help="Une posture n'est dite « bien ancrée » (elle ne va pas s'estomper facilement) que si sa position "
             "est au moins à cette distance de l'origine…")] = 0.4
    anchored_min_impulses: Annotated[int, Knob(
        label="Posture ancrée : tours concordants", group="Lecture", lo=1, hi=8,
        help="… et que tant de déclarations récentes vont dans son sens (les huit dernières sont gardées).")] = 2
    anchored_window_us: Annotated[int, Knob(
        label="Posture ancrée : fenêtre", group="Lecture", lo=MINUTE, hi=6 * HOUR,
        help="… dans cette fenêtre.")] = 900_000_000
    #: Débordement d'humeur → preuve d'initiative (log-odds).
    overflow_floor: Annotated[float, Knob(
        label="Seuil de débordement de l'humeur", group="Humeur qui déborde", lo=0, hi=0.95, step=0.05,
        help="Au-delà de cet écart ressenti à son repos, son humeur la pousse à parler, à quiconque est "
             "là.")] = 0.45
    overflow_max_evidence: Annotated[float, Knob(
        label="Preuve d'une humeur débordante", group="Humeur qui déborde", lo=0, hi=4, step=0.1,
        help="Preuve d'initiative (log-odds) d'une humeur pleinement débordante, croissant depuis le seuil. "
             "Plafonnée à 4 par l'arbitrage : seule, elle ne franchit pas le seuil d'initiative.")] = 4.0

    @property
    def heal_rate(self) -> float:
        """Taux de guérison d'une ancre, par seconde."""
        return math.log(2.0) / (self.anchor_half_life_us / 1_000_000)


def derive(t: Temperament, overrides: Mapping[str, Any] | None = None) -> AffectParams:
    values = physics_of(t)
    values.update(overrides or {})
    return AffectParams(**values)


DEFAULT = derive(Temperament())
