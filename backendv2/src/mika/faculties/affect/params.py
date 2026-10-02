"""Paramètres d'``affect``, dérivés du tempérament.

Le point de départ est la physique de la v1 (oscillateur amorti, cliquet
d'impulsion, repos circadien) ; ce qui la valide ici, ce sont les cibles de
comportement des tests, pas la v1 elle-même.
"""

from __future__ import annotations

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
        # le fond d'une journée : plus long chez une âme lente à revenir au calme
        "fond_tau_us": round(geometric(8.0, 3.0, t.resilience) * HOUR),
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
        help="Part de l'ancre (ce que la personne a installé, mesuré depuis son repos moyen) qui s'ajoute au "
             "repos commun pour faire le repos de sa posture envers elle.")] = 0.6
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
        help="La demi-vie de base de l'ancre, qui guérit vers son repos moyen : celle d'un froid ordinaire. Une "
             "chaleur et une rancune répétée durent plus longtemps (ci-dessous). Dérivée de la résilience.")] = _DEFAULTS["anchor_half_life_us"]
    #: Ce qu'elle a déclaré envers quelqu'un décroît au rythme de sa posture ;
    #: en deçà de ce plancher, c'est la position qui parle (plus de fenêtre dure).
    declared_floor: Annotated[float, Knob(
        label="Déclaration : plancher", group="Lecture", lo=0, hi=1, step=0.01,
        help="Sa dernière émotion déclarée envers quelqu'un s'estompe au rythme de sa posture ; tant qu'elle reste "
             "au-dessus de ce plancher (et de ce que dit la position), c'est elle que le prompt et le visage "
             "montrent.")] = 0.1
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
        label="Posture installée : écart minimal", group="Lecture", lo=0, hi=1.2, step=0.05,
        help="Une posture n'est dite installée (« ça fait plusieurs échanges de suite… ») que si elle s'écarte "
             "de son repos d'au moins cette distance…")] = 0.25
    anchored_min_impulses: Annotated[int, Knob(
        label="Posture ancrée : tours concordants", group="Lecture", lo=1, hi=8,
        help="… et que tant de déclarations récentes vont dans son sens (les huit dernières sont gardées).")] = 2
    anchored_window_us: Annotated[int, Knob(
        label="Posture ancrée : fenêtre", group="Lecture", lo=MINUTE, hi=6 * HOUR,
        help="… dans cette fenêtre.")] = 900_000_000
    # ── le fond d'une journée ──
    fond_tau_us: Annotated[int, Knob(
        label="Fond : durée", group="Le fond d'une journée", lo=HOUR, hi=24 * HOUR,
        help="La constante de temps (en heures d'éveil) de la moyenne glissante de ses émotions du moment : une "
             "après-midi triste colore encore la soirée. Dérivée de la résilience.")] = _DEFAULTS["fond_tau_us"]
    fond_weight: Annotated[float, Knob(
        label="Fond : poids", group="Le fond d'une journée", lo=0, hi=2, step=0.05,
        help="Ce que l'émotion du moment, tenue longtemps, laisse au fond (0 : aucun fond, elle revient au repos "
             "en une vingtaine de minutes ; 1 : une émotion tenue des heures finit par devenir le fond).")] = 0.5
    fond_max: Annotated[float, Knob(
        label="Fond : plafond", group="Le fond d'une journée", lo=0, hi=0.6, step=0.01,
        help="Le fond ne l'éloigne jamais de son repos au-delà de cette distance.")] = 0.2
    fond_said: Annotated[float, Knob(
        label="Fond : ce qui se dit", group="Le fond d'une journée", lo=0, hi=0.5, step=0.01,
        help="Quand son humeur est à peu près au repos, un fond au-delà de cette distance se dit encore (« avec "
             "un petit reste de tristesse de tout à l'heure »).")] = 0.04
    sleep_relief: Annotated[float, Knob(
        label="Ce que le sommeil allège", group="Le fond d'une journée", lo=0, hi=1, step=0.05,
        help="Le fond ne bouge pas pendant qu'elle dort ; au réveil, il perd cette part. Le reste colore son "
             "matin.")] = 0.6
    # ── l'histoire d'une relation ──
    anchor_history_days: Annotated[float, Knob(
        label="Histoire qui ralentit l'ancre (jours)", group="L'histoire d'une relation", lo=1, hi=365, step=1,
        help="Ce qu'une déclaration fond dans l'ancre est divisé par (1 + jours de contact ÷ ceci) : une longue "
             "amitié ne se défait pas en sept phrases.")] = 14.0
    empathy_tenderness: Annotated[float, Knob(
        label="Empathie : tendresse", group="L'histoire d'une relation", lo=0, hi=1, step=0.05,
        help="Une tristesse, une peur, une solitude dites à quelqu'un qui va mal se fondent dans l'ancre vers un "
             "point tendre (cette part du chemin vers la tendresse, à pleine intensité), pas vers leur propre "
             "émotion : consoler rapproche.")] = 0.3
    warm_heal_factor: Annotated[float, Knob(
        label="Chaleur : guérison plus lente", group="L'histoire d'une relation", lo=1, hi=20, step=0.5,
        help="Une ancre chaleureuse guérit tant de fois plus lentement que la demi-vie de base : l'affection ne "
             "s'évapore pas en une semaine.")] = 5.0
    hostile_heal_steps: Annotated[int, Knob(
        label="Rancune : répétitions", group="L'histoire d'une relation", lo=1, hi=100,
        help="Une ancre hostile guérit (1 + déclarations hostiles ÷ ceci) fois plus lentement que la demi-vie de "
             "base : une hostilité répétée dure.")] = 6
    hostile_heal_max_us: Annotated[int, Knob(
        label="Rancune : demi-vie maximale", group="L'histoire d'une relation", lo=DAY, hi=90 * DAY,
        help="La demi-vie d'une ancre hostile ne dépasse jamais cette durée.")] = 21 * DAY
    bond_step: Annotated[float, Knob(
        label="Attachement : pas", group="L'histoire d'une relation", lo=0, hi=0.2, step=0.005,
        help="Chaque déclaration chaleureuse ou empathique envers quelqu'un l'attache un peu plus (ce pas × "
             "intensité × ce qui reste à gagner). L'attachement ne devient jamais négatif.")] = 0.01
    bond_half_life_us: Annotated[int, Knob(
        label="Attachement : demi-vie", group="L'histoire d'une relation", lo=7 * DAY, hi=365 * DAY,
        help="Sans nouvelle déclaration, l'attachement s'estompe avec cette demi-vie.")] = 60 * DAY
    bond_regard: Annotated[float, Knob(
        label="Attachement : part dans la chaleur", group="L'histoire d'une relation", lo=0, hi=1, step=0.05,
        help="Ce que l'attachement ajoute à la chaleur installée (le regard) envers quelqu'un.")] = 0.3
    bond_damping: Annotated[float, Knob(
        label="Attachement : ce qu'il ôte à la rancune", group="L'histoire d'une relation", lo=0, hi=1, step=0.05,
        help="L'hostilité envers quelqu'un est multipliée par (1 − ceci × attachement) : on en veut moins à une "
             "amie de longue date.")] = 0.6
    bond_said: Annotated[float, Knob(
        label="Attachement : « tu tiens à elle »", group="L'histoire d'une relation", lo=0, hi=1, step=0.05,
        help="Au-delà de cet attachement, le prompt lui dit qu'elle tient à cette personne.")] = 0.35
    wary_from: Annotated[float, Knob(
        label="Méfiance : hostilité qui la déclenche", group="L'histoire d'une relation", lo=0, hi=1, step=0.05,
        help="Envers quelqu'un qui n'est ni une amie ni une proche, une hostilité qui dépasse ce seuil laisse une "
             "méfiance plancher (ci-dessous) pendant un moment.")] = 0.3
    wary_floor: Annotated[float, Knob(
        label="Méfiance : plancher", group="L'histoire d'une relation", lo=0, hi=1, step=0.05,
        help="L'hostilité ne descend pas sous ce plancher tant que dure la méfiance.")] = 0.1
    wary_us: Annotated[int, Knob(
        label="Méfiance : durée", group="L'histoire d'une relation", lo=0, hi=90 * DAY,
        help="Combien de temps dure la méfiance plancher après la dernière hostilité forte.")] = 14 * DAY
    #: Débordement d'humeur → preuve d'initiative (log-odds).
    overflow_floor: Annotated[float, Knob(
        label="Seuil de débordement de l'humeur", group="Humeur qui déborde", lo=0, hi=0.95, step=0.05,
        help="Au-delà de cet écart ressenti à son repos, son humeur la pousse à parler, à quiconque est "
             "là.")] = 0.45
    overflow_max_evidence: Annotated[float, Knob(
        label="Preuve d'une humeur débordante", group="Humeur qui déborde", lo=0, hi=4, step=0.1,
        help="Preuve d'initiative (log-odds) d'une humeur pleinement débordante, croissant depuis le seuil. "
             "Plafonnée à 4 par l'arbitrage : seule, elle ne franchit pas le seuil d'initiative.")] = 4.0


def derive(t: Temperament, overrides: Mapping[str, Any] | None = None) -> AffectParams:
    values = physics_of(t)
    values.update(overrides or {})
    return AffectParams(**values)


DEFAULT = derive(Temperament())
