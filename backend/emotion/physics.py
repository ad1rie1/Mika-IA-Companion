"""Physique des oscillateurs PAD : intégration, vieillissement, ancres.

Tout ce qui fait avancer un oscillateur ou déplace une ancre, sans ORM et
sans état : le moteur (``emotion/engine.py``) tient les impulsions et les
vues, la persistance (``emotion/persistence.py``) lit et écrit les relevés,
et les deux s'appuient sur les fonctions d'ici. Les lectures de
configuration passent par ``configs.runtime`` et ne lèvent jamais : la
constante du module reste le repli de la clé ``emotion.*`` correspondante
(``emotion/config_schema.py`` déclare exactement la même valeur).
"""
from __future__ import annotations

import random
import time

from configs.runtime import cfg_float
from emotion import pad
from emotion.dynamics import OscillatorParams, OscillatorState
from emotion.pad import Vec3
from emotion.state import PersonMood, Temperament
from emotion.types import Emotion
from utils.degradation import degradations

# Maximum sub-step size for stable integration. Semi-implicit Euler is only
# stable when dt · ω₀ < ~π; for our parameter range, 0.5s is always safe.
_MAX_SUBSTEP_DT = 0.5
# Past this much simulated time, the sub-step is coarsened: relaxation over
# an hour is 720 steps at 5s, and dt · ω₀ ≈ 0.006 stays far from the stability
# limit. The window before it stays fine-grained so a normal tick is exact.
_FINE_WINDOW_S = 60.0
_COARSE_SUBSTEP_DT = 5.0
# Ce qui n'est PAS configurable, et ne doit pas le devenir : les trois pas
# d'intégration ci-dessus. Ce ne sont pas des réglages mais la condition de
# stabilité du schéma d'Euler semi-implicite — un curseur y règle la justesse
# du calcul, pas le caractère.

# Upper bound on the total time advanced in a single decay pass.
# Invisible while the time constant was ~7s (the old 30s cap was already four
# time constants); with a τ counted in minutes it froze the state of a machine
# that had hibernated. Trois heures de rattrapage : à une heure, une
# hibernation de cinq heures laissait au fond 17 % de l'écart (τ_global
# 23 min, sous-amorti) — trois heures, c'est 7,8 τ. Et au-delà de
# ``AGED_HORIZON_TAUS`` constantes de temps, ``advance`` ne calcule plus :
# il pose le repos, comme ``aged_position`` le fait déjà pour un relevé.
_MAX_ADVANCE_SECONDS = 10800.0
#: Au-delà de tant de constantes de temps, un relevé ne dit plus rien de
#: la position : c'est le repos (exp(−10) < 5 · 10⁻⁵, oscillation comprise).
AGED_HORIZON_TAUS = 10.0

# Probability per tick that the global mood receives a tiny stochastic
# nudge. Without this, a well-rested idle Mika sits exactly on her home
# point — humans don't. Small nudges produce barely-perceptible drift
# ("why am I a bit off today") that the oscillator then metabolizes
# normally. Scoped to the global mood only; per-person moods are always
# reactive, never spontaneous.
# A nudge now lives for τ — minutes, not seconds — so at the old cadence they
# compounded into a visible random walk. Rarer and smaller, same drift.
_SPONTANEOUS_NUDGE_PROBABILITY: float = 0.004
# Max magnitude of a spontaneous nudge (in PAD units).
_SPONTANEOUS_NUDGE_MAX: float = 0.05

# Constante de temps du retour au repos, aux deux bouts du curseur « vitesse
# de récupération » (interpolation géométrique). Un tour dure 30-120 s : avec
# le réglage précédent l'état revenait au repos en ~27 s, donc l'émotion d'un
# tour avait disparu avant le tour suivant et tout ce qui lit la position —
# prompt, relevé, fiche affect, gestes — lisait le repos. Cible au défaut
# (recovery_speed 0.5) : ~11,6 min, dans une plage de 4 min à 30 min.
PERSON_TAU_FAST = 240.0
PERSON_TAU_SLOW = 1800.0
GLOBAL_TAU_FACTOR = 2.0
# Part de la distance restante qu'une impulsion parcourt d'un coup.
RATCHET_BASE = 1.0
RATCHET_MAX = 0.75
RATCHET_GLOBAL = 0.45
GLOBAL_RATCHET_MAX = 0.5

# Ancrage personnel : bornes de l'ancre et vitesse à laquelle un relevé s'y
# fond. Le poids de l'ancre dans le repos d'une personne, lui, reste au moteur
# (``_person_home``) : c'est une lecture, pas un mouvement.
ANCHOR_MAX_NORM = 0.7
ANCHOR_ALPHA = 0.15
# Demi-vie de la GUÉRISON d'une stance : le temps qu'il faut, sans plus aucun
# échange, pour que l'ancre ait parcouru la moitié du chemin vers le repos
# commun. Deux écrivains la déplaçaient — un relevé, une réhydratation — et
# aucun ne la ramenait jamais vers le neutre : une brouille de quarante tours
# installait un repos `frustrated` mesuré identique après 1 h, 6 h et 24 h de
# silence complet. Une rancune humaine s'émousse toute seule ; il faut juste
# que ce soit LENT devant une conversation (α = 0.15 par tour), sans quoi
# l'attachement ne se construirait jamais. Trois jours : une brouille du lundi
# est encore lisible le mercredi, oubliée la semaine suivante.
ANCHOR_HEAL_HALF_LIFE_S = 3 * 86400.0


# ----------------------------------------------------------------------
# Paramètres dérivés du tempérament
# ----------------------------------------------------------------------

def global_ratchet_max() -> float:
    """Le plafond du gain d'impulsion vers l'humeur de fond, une fois.

    Lu par ``derive_params`` ET par le gain d'une impulsion globale : il était
    écrit deux fois, dont une en littéral nu (``min(0.5, …)``). Deux plafonds
    pour une seule garde, c'est deux plafonds qui divergent au premier
    réglage — les deux sites lisent donc la même clé.
    """
    return cfg_float("emotion.global_ratchet_max", GLOBAL_RATCHET_MAX, mini=0.0)


def derive_params(t: Temperament) -> tuple[OscillatorParams, OscillatorParams]:
    """``(personne, fond)`` : les paramètres d'oscillateur d'un tempérament.

    Scaling choices:
    - `recovery_speed` fixes the time constant τ, geometrically between
      PERSON_TAU_SLOW and PERSON_TAU_FAST. It used to set the *stiffness*,
      which moves the oscillation frequency and nothing else: the decay
      envelope was c/2m, a function of `volatility` alone, so the cursor
      labelled "vitesse de récupération" changed no recovery at all
      (measured identical to five decimals across its whole range).
    - `damping = 2m/τ` is what makes that envelope exactly exp(-t/τ).
    - `volatility` keeps the mass, the damping ratio, and the size of the
      ratchet an impulse applies.
    """
    volatility = max(0.05, min(1.0, t.volatility))
    recovery = max(0.05, min(1.0, t.recovery_speed))
    mass = max(0.25, min(4.0, 1.0 / volatility))

    tau_fast = cfg_float("emotion.person_tau_fast", PERSON_TAU_FAST, mini=1e-3)
    tau_slow = cfg_float("emotion.person_tau_slow", PERSON_TAU_SLOW, mini=1e-3)
    tau = tau_slow * (tau_fast / tau_slow) ** ((recovery - 0.05) / 0.95)
    zeta = 1.0 - 0.35 * volatility
    omega0 = 1.0 / (zeta * tau)

    person = OscillatorParams(
        mass=mass,
        stiffness=mass * omega0 * omega0,
        damping=2.0 * mass / tau,
        impulse_gain=min(
            cfg_float("emotion.ratchet_max", RATCHET_MAX, mini=0.0),
            cfg_float("emotion.ratchet_base", RATCHET_BASE, mini=0.0)
            * max(0.1, t.intensity_base) * (0.5 + 0.5 * volatility),
        ),
    )

    # Global mood is lazier: heavier mass, twice the time constant. The
    # bleed is applied *once*, here — Factor 3 of conscience/scoring.py
    # reads this same intensity at a 0.7 threshold, so anyone lowering this
    # gain is turning that factor off. No floor either: the cursor promises
    # "à 0 elle compartimente entièrement".
    global_mass = mass * 1.5
    global_tau = tau * cfg_float(
        "emotion.global_tau_factor", GLOBAL_TAU_FACTOR, mini=1e-3,
    )
    global_omega0 = 1.0 / (0.9 * global_tau)
    bleed = max(0.0, t.global_bleed)
    fond = OscillatorParams(
        mass=global_mass,
        stiffness=global_mass * global_omega0 * global_omega0,
        damping=2.0 * global_mass / global_tau,
        impulse_gain=(
            0.0 if bleed <= 0.0
            else min(
                global_ratchet_max(),
                cfg_float("emotion.ratchet_global", RATCHET_GLOBAL, mini=0.0)
                * bleed,
            )
        ),
    )
    return person, fond


def tau_of(params: OscillatorParams) -> float:
    """Constante de temps du retour au repos, en secondes.

    ``derive_params`` pose ``damping = 2m/τ`` précisément pour que
    l'enveloppe de retour soit exp(−t/τ) ; on la relit ici plutôt que de
    la recalculer depuis le tempérament, pour que la restauration et la
    boucle physique parlent de la même constante.
    """
    return 2.0 * params.mass / max(1e-9, params.damping)


# ----------------------------------------------------------------------
# Intégration
# ----------------------------------------------------------------------

def max_advance_seconds() -> float:
    """Le plafond de rattrapage d'une passe, lu une fois par passe."""
    return cfg_float(
        "emotion.max_advance_seconds", _MAX_ADVANCE_SECONDS, mini=0.0,
    )


def advance(
    dynamic: OscillatorState,
    home: Vec3,
    params: OscillatorParams,
    total_dt: float,
    max_advance: float | None = None,
) -> None:
    """Advance an oscillator by total_dt seconds in stable sub-steps.

    ``max_advance`` est lu UNE fois par passe par ``_apply_decay`` et
    passé ici : la passe traverse toutes les personnes en RAM, et le
    plafond doit valoir la même chose pour toutes celles d'un même tick.
    ``None`` = lire le réglage (appel isolé, tests).
    """
    if max_advance is None:
        max_advance = max_advance_seconds()
    # Au-delà de dix constantes de temps, l'oscillateur EST au repos
    # (exp(−10) < 5 · 10⁻⁵, oscillation comprise) : on le pose, plutôt que
    # de plafonner le rattrapage et de laisser un reste — une machine
    # réveillée après cinq heures gardait 17 % de l'écart de la veille.
    if total_dt >= AGED_HORIZON_TAUS * tau_of(params):
        dynamic.position = home
        dynamic.velocity = pad.zero()
        return
    remaining = min(total_dt, max_advance)
    fine = _FINE_WINDOW_S
    while remaining > 1e-6:
        substep = _MAX_SUBSTEP_DT if fine > 0.0 else _COARSE_SUBSTEP_DT
        step_dt = min(substep, remaining)
        dynamic.step(home, params, step_dt)
        remaining -= step_dt
        fine -= step_dt


def aged_position(
    cible: Vec3, home: Vec3, elapsed: float, params: OscillatorParams,
) -> Vec3:
    """Où l'oscillateur en serait, parti de ``cible`` il y a ``elapsed`` s.

    On fait tourner l'oscillateur lui-même — le même ``advance`` que la
    boucle, depuis la position du relevé au repos (vitesse nulle) — et
    non une droite sur deux jours : à τ ≈ 11,6 min, un relevé ``angry
    0.8`` vieux d'une heure vaut le repos, alors que la droite en gardait
    98 %. Mesuré : l'oscillateur vivant lisait ``hopeful 0.11`` une heure
    après la colère, la réhydratation rendait ``angry 0.73`` — et encore
    ``angry 0.56`` douze heures plus tard. Une éviction (une heure
    d'inactivité, au repos) suivie d'une reconnexion ressuscitait donc
    une émotion déjà digérée ; même chose au redémarrage sans relevé
    d'arrêt.

    Intégrer plutôt qu'appliquer exp(−t/τ) : l'humeur de fond est
    sous-amortie (ζ = 0,9) et garde à 1 h 17 % de l'écart là où
    l'enveloppe seule en prédit 7 %. « Ce que l'oscillateur vivant
    lirait » est la seule définition qui ne dérive pas.

    Le relevé est pris pour la position qu'il porte, sans lui appliquer
    le cliquet : une ligne d'arrêt EST une position, et une ligne de tour
    porte la balise déclarée quelques minutes plus tôt — ce que
    ``DECLARED_WINDOW_S`` tient de toute façon pour actuel sur cette
    durée. Seule la partie non encore digérée du relevé est restaurée ; le
    reste est le repos.
    """
    horizon = AGED_HORIZON_TAUS * tau_of(params)
    elapsed = max(0.0, elapsed)
    if elapsed >= horizon:
        return home
    etat = OscillatorState(position=cible)
    advance(etat, home, params, elapsed, max_advance=horizon)
    return etat.position


def nudged_position(position: Vec3, home: Vec3, volatility: float) -> Vec3 | None:
    """Spontaneous mood drift: tiny random nudge so the global mood doesn't
    sit perfectly on its home point when nothing is happening.

    Scaled by:
      - stillness  (only nudge when close to rest — real impulses
                    still dominate when something is happening)
      - volatility (stoic personas barely drift, explosive ones do
                    — matches temperament personality)

    Renvoie la nouvelle position, ou ``None`` quand ce tick ne pousse pas.
    """
    volatility_scale = max(0.0, volatility)
    probabilite = cfg_float(
        "emotion.spontaneous_nudge_probability",
        _SPONTANEOUS_NUDGE_PROBABILITY, mini=0.0, maxi=1.0,
    )
    if volatility_scale <= 0.25 or random.random() >= probabilite:
        return None
    distance = pad.distance(position, home)
    stillness = max(0.0, 1.0 - distance * 3.0)  # 0 when far, 1 when at home
    if stillness <= 0.2:
        return None
    magnitude = (
        cfg_float("emotion.spontaneous_nudge_max", _SPONTANEOUS_NUDGE_MAX, mini=0.0)
        * stillness
        * volatility_scale
        * random.random()
    )
    nudge: Vec3 = (
        random.uniform(-1.0, 1.0) * magnitude,
        random.uniform(-1.0, 1.0) * magnitude,
        random.uniform(-1.0, 1.0) * magnitude,
    )
    return pad.clamp_component(pad.add(position, nudge), limit=1.0)


# ----------------------------------------------------------------------
# Ancres : la trace lissée de ce qu'une personne a déjà provoqué
# ----------------------------------------------------------------------

def heal_half_life_seconds() -> float:
    """Demi-vie de la guérison d'une stance, en secondes.

    Le réglage est exposé en JOURS — c'est l'unité dans laquelle on raisonne
    (« une brouille du lundi est-elle encore là mercredi ? »), pas en secondes
    où la valeur par défaut s'écrit 259 200. La conversion vit ici, une fois,
    plutôt qu'à chacun des deux sites de lecture.
    """
    return cfg_float(
        "emotion.anchor_heal_half_life_days",
        ANCHOR_HEAL_HALF_LIFE_S / 86400.0,
        mini=1e-6,
    ) * 86400.0


def anchor_alpha() -> float:
    return cfg_float("emotion.anchor_alpha", ANCHOR_ALPHA, mini=0.0, maxi=1.0)


def clamp_anchor(vector: Vec3) -> Vec3:
    limite = cfg_float("emotion.anchor_max_norm", ANCHOR_MAX_NORM, mini=0.0)
    magnitude = pad.norm(vector)
    if magnitude <= limite:
        return vector
    return pad.scale(vector, limite / magnitude)


def _vers_le_repos(ancre: Vec3, home: Vec3, part: float) -> Vec3:
    """L'ancre rapprochée du repos d'une part ``part`` du chemin, bornée."""
    return clamp_anchor(pad.add(
        pad.scale(ancre, 1.0 - part), pad.scale(home, part),
    ))


def heal_anchor(mood: PersonMood, home: Vec3, dt: float) -> None:
    """Rapproche lentement la stance envers quelqu'un du repos commun.

    Le seul mouvement de l'ancre venait des relevés — donc de nouvelles
    déclarations. Sans échange, elle ne bougeait pas d'un pouce : une
    stance négative installée un soir était encore là mot pour mot le
    lendemain, et seule une vingtaine de tours chaleureux pouvait la
    défaire. Le temps compte aussi, et beaucoup plus lentement que les
    mots — c'est ce rapport qui donne à la fois de la rancune et du pardon.
    """
    if mood.anchor is None or dt <= 0.0:
        return
    part = 1.0 - 0.5 ** (dt / heal_half_life_seconds())
    if part <= 0.0:
        return
    mood.anchor = _vers_le_repos(mood.anchor, home, part)


def fold_anchor(mood: PersonMood, position: Vec3, home: Vec3) -> None:
    """Fold a written snapshot into this person's own resting point.

    Fed from what was *persisted*, so the anchor and the record tell the
    same story — the tag when a turn declared one.

    Pas de premier relevé « à 100 % » : une ancre naît AU REPOS COMMUN
    (``home``) et le premier relevé s'y fond à α comme tous les suivants.
    Sinon un seul ``[EMOTION:angry:0.8]`` envers un inconnu posait l'ancre
    au plafond (0,7) — « légèrement en colère » une heure plus tard, encore
    teintée après trois jours de silence, trois tours chaleureux pour la
    retourner — ce que le contrat de ``PersonMood.anchor`` (« jamais une
    lecture instantanée ») interdit précisément.
    """
    alpha = anchor_alpha()
    courante = mood.anchor if mood.anchor is not None else home
    mood.anchor = clamp_anchor(pad.add(
        pad.scale(courante, 1.0 - alpha),
        pad.scale(position, alpha),
    ))


def anchor_from_rows(rows, home: Vec3) -> Vec3 | None:
    """Recency-weighted mean of what a person has already provoked.

    ``rows`` : des relevés (``primary_emotion``, ``primary_intensity``,
    ``created_at`` facultatif), le plus récent en tête. Le résultat est
    VIEILLI du temps écoulé depuis le relevé le plus récent, avec la même
    demi-vie que ``heal_anchor``. Sans cela, l'éviction rouvrait la porte
    que la guérison venait de fermer : une humeur inactive sort de la RAM
    au bout d'une heure, et la réhydratation reconstruisait l'ancre à
    partir de vingt vieilles déclarations — ramenant intacte, des semaines
    plus tard, une stance que le temps avait justement effacée.
    """
    try:
        total = 0.0
        lignes_valides = 0
        accumulated = pad.zero()
        for index, row in enumerate(rows):
            try:
                label = Emotion(row.primary_emotion)
            except ValueError:
                continue
            lignes_valides += 1
            weight = float(len(rows) - index)
            accumulated = pad.add(
                accumulated,
                pad.scale(pad.label_to_pad(label, row.primary_intensity), weight),
            )
            total += weight

        if total <= 0.0:
            return None
        moyenne = pad.scale(accumulated, 1.0 / total)

        # Même poids qu'une suite de relevés fondus un à un à α depuis le
        # repos (``fold_anchor``) : après n relevés il reste (1−α)ⁿ de
        # repos dans l'ancre. Une seule ligne pèse donc α, pas 1 — la
        # moyenne pondérée seule rendait à la réhydratation le défaut
        # que ``fold_anchor`` vient de perdre : une ligne, une ancre au
        # plafond.
        part_releves = 1.0 - (1.0 - anchor_alpha()) ** lignes_valides
        ancre = clamp_anchor(pad.add(
            pad.scale(home, 1.0 - part_releves),
            pad.scale(moyenne, part_releves),
        ))

        # `getattr` : une ligne peut ne pas porter de date (relevé
        # partiel, substitut de test). Sans horodatage on ne vieillit
        # simplement pas — jamais on ne perd l'ancre pour autant.
        dates = [
            d for d in (getattr(r, "created_at", None) for r in rows)
            if d is not None and hasattr(d, "timestamp")
        ]
        recent = max(dates, default=None)
        if recent is not None:
            age = max(0.0, time.time() - recent.timestamp())
            part = 1.0 - 0.5 ** (age / heal_half_life_seconds())
            if part > 0.0:
                ancre = _vers_le_repos(ancre, home, part)
        return ancre
    except Exception as exc:
        degradations.record("emotion.physics.anchor_from_rows", exc)
        return None
