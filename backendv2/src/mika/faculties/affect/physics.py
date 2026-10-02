"""La physique de l'affect, en forme close.

**L'humeur** se lit en trois couches, toutes linéaires :

- le *repos* (``rest``) : un oscillateur jumeau, sans impulsion, qui suit le
  repos commun (son humeur de fond teintée par le moment de la journée). Le
  repos commun saute aux débuts de phase : le jumeau saute avec, si bien que
  ce qu'elle ressent (l'écart au jumeau) ne voit jamais l'horloge — rien
  d'inventé à 18 h ;
- l'*émotion du moment* (``gap``) : ce que les impulsions ont déplacé, un
  oscillateur libre qui revient à zéro en une vingtaine de minutes ;
- le *fond* (``fond``) : la moyenne glissante, sur quelques heures d'éveil, de
  l'émotion du moment — une après-midi triste colore la soirée. Il ne bouge
  pas pendant qu'elle dort ; le réveil l'allège.

**Une posture** par personne a la même forme (jumeau + émotion du moment) ;
son repos propre est le repos commun plus une part de l'**ancre** : ce que la
relation a installé, mesuré depuis son repos *moyen sur 24 h* (jamais depuis
l'heure qu'il est), qui guérit exponentiellement — lentement si elle est
chaleureuse, d'autant plus lentement qu'une hostilité s'est répétée. Un
**attachement** (``bond``), plus lent encore, naît des déclarations
chaleureuses et empathiques ; il ne devient jamais négatif.

Une impulsion vise un point du **rayon** qui va du repos vers l'ancre de
l'émotion (``lerp(repos, ancre, intensité)``) : depuis un repos déjà positif,
« un peu contente » monte, « un peu triste » descend. Lire une position ne
dépend jamais du moment ni du pas de la lecture.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from zoneinfo import ZoneInfo

from mika.faculties.affect.params import AffectParams
from mika.kernel.dynamics import Oscillator, propagate, propagate_toward
from mika.vocab import affect as A
from mika.vocab import circadian
from mika.vocab.affect import Declared, Emotion, Vec3

ZERO: Vec3 = (0.0, 0.0, 0.0)
#: Au-delà de tant de constantes de temps, le jumeau est sur son repos.
SETTLED_TAUS = 40.0
#: En deçà de cette norme, une ancre est guérie (effacée).
HEALED_NORM = 1e-4
RECENT_IMPULSES = 8
#: Ce qu'elle garde des dernières impulsions de son humeur (pour en dire la cause).
MARKS = 8

#: Ce qu'elle déclare envers quelqu'un et qui l'attache à lui : de la chaleur…
WARM = frozenset({Emotion.HAPPY, Emotion.EXCITED, Emotion.LOVE, Emotion.PROUD, Emotion.GRATEFUL, Emotion.PLAYFUL,
                  Emotion.AMUSED, Emotion.HOPEFUL, Emotion.RELIEVED})
#: … ou de l'empathie : être triste *avec* quelqu'un rapproche, et se fond vers
#: un point tendre plutôt que vers sa propre ancre.
EMPATHIC = frozenset({Emotion.SAD, Emotion.LONELY, Emotion.ANXIOUS, Emotion.SCARED, Emotion.MELANCHOLIC,
                      Emotion.NOSTALGIC})
#: L'hostilité : un déplaisir dominant (la colère, le dégoût, la frustration).
HOSTILE = frozenset(e for e, (pl, _a, d) in A.ANCHORS.items() if pl < 0 < d)


@dataclass(frozen=True, slots=True)
class Osc:
    position: Vec3
    velocity: Vec3
    at: int


@dataclass(frozen=True, slots=True)
class Mark:
    """Une impulsion de son humeur, pour pouvoir en dire la cause."""

    at: int
    emotion: str
    cause: str  # un code (``talk``, ``retour``, ``rêve``…), jamais un texte libre
    person: str = ""  # la personne d'un échange (``talk``)


@dataclass(frozen=True, slots=True)
class Mood:
    rest: Osc
    gap: Vec3 = ZERO
    gap_velocity: Vec3 = ZERO
    fond: Vec3 = ZERO  # non borné ; lu borné (``fond_of``)
    asleep: bool = False
    marks: tuple[Mark, ...] = ()

    @property
    def at(self) -> int:
        return self.rest.at


@dataclass(frozen=True, slots=True)
class Stance:
    rest: Osc  # le jumeau sans impulsion, sur le repos propre de la personne
    gap: Vec3 = ZERO
    gap_velocity: Vec3 = ZERO
    #: ce que la relation a installé, mesuré depuis son repos moyen ; valable à ``rest.at``
    anchor: Vec3 | None = None
    bond: float = 0.0  # valable à ``rest.at``
    hostile: int = 0  # déclarations hostiles fondues (allongent la guérison)
    days: int = 0  # jours distincts où elle lui a déclaré quelque chose
    last_day: int = 0  # le dernier de ces jours (ordinal local)
    wary_until: int = 0  # méfiance plancher jusqu'à cet instant
    folded_at: int = 0
    declared: str | None = None  # ``Declared.encode()``
    declared_at: int = 0
    declared_reply: bool = True
    recent: tuple[tuple[int, str], ...] = field(default_factory=tuple)

    @property
    def at(self) -> int:
        return self.rest.at

    @property
    def position(self) -> Vec3:
        return A.add(self.rest.position, self.gap)


@dataclass(frozen=True, slots=True)
class Clockwork:
    """Ce que la physique doit savoir du temps : fuseau et rythme."""

    tz: ZoneInfo
    rhythm: circadian.Profile


# ── Repos ─────────────────────────────────────────────────────────────────


def common_home(t: int, p: AffectParams, cw: Clockwork) -> Vec3:
    """Le repos commun à l'instant : son humeur de fond, la teinte de la phase."""
    phase = circadian.phase_at(t, cw.tz, cw.rhythm)
    base = A.add(A.to_pad(p.background, p.background_weight), circadian.tint(phase, cw.rhythm))
    return A.add(base, (p.rest_valence, 0.0, 0.0)) if p.rest_valence else base


def reference(p: AffectParams, cw: Clockwork) -> Vec3:
    """Son repos **moyen sur 24 h** (chaque teinte pesée par la durée de sa
    phase) : ce dont on mesure une ancre, une chaleur, une rancune. Lues contre
    le repos de l'instant, elles variaient avec l'heure."""
    starts = cw.rhythm.starts
    total = 24 * 60
    tint = ZERO
    for i, (phase, start) in enumerate(starts):
        nxt = starts[(i + 1) % len(starts)][1]
        minutes = (nxt - start) % total or total
        tint = A.add(tint, A.scale(circadian.tint(phase, cw.rhythm), minutes / total))
    base = A.add(A.to_pad(p.background, p.background_weight), tint)
    return A.add(base, (p.rest_valence, 0.0, 0.0)) if p.rest_valence else base


def _segments(t0: int, t1: int, cw: Clockwork) -> list[tuple[int, int]]:
    cuts = [t0, *circadian.boundaries(t0, t1, cw.tz, cw.rhythm), t1]
    return [(a, b) for a, b in zip(cuts, cuts[1:], strict=False) if b > a]


def _follow(oscillator: Oscillator, osc: Osc, t: int, p: AffectParams, cw: Clockwork, settled_after_s: float,
            offset: Vec3 = ZERO, rate: float = 0.0) -> Osc:
    """Le jumeau propagé jusqu'à ``t`` : vers le repos commun de chaque segment
    de phase, plus un décalage ``offset`` (valable à ``osc.at``) qui décroît à
    ``rate`` — l'ancre qui guérit. Exact, quel que soit le pas."""
    if t <= osc.at:
        return osc

    def shift(at: int) -> Vec3:
        return A.scale(offset, math.exp(-rate * (at - osc.at) / 1e6)) if rate else offset

    if (t - osc.at) / 1e6 > settled_after_s:
        return Osc(A.add(common_home(t, p, cw), shift(t)), ZERO, t)
    pos, vel = osc.position, osc.velocity
    for a, b in _segments(osc.at, t, cw):
        pos, vel = propagate_toward(oscillator, pos, vel, common_home(a, p, cw), shift(a), rate, (b - a) / 1e6)
    return Osc(pos, vel, t)


# ── L'émotion du moment et le fond ────────────────────────────────────────


def _lowpass(osc: Oscillator, e0: Vec3, v0: Vec3, e1: Vec3, v1: Vec3, f0: Vec3, tau_s: float, weight: float,
             dt_s: float) -> Vec3:
    """Le fond après ``dt_s`` : ``f' = (weight·e − f)/tau`` où ``e`` est l'émotion
    du moment, un oscillateur libre. Forme close (exponentielle d'une matrice
    triangulaire par blocs) : ``f(t) = e^{λt}·f0 + b·(A−λI)⁻¹·[(e,v)(t) − e^{λt}(e,v)(0)]``."""
    lam = -1.0 / tau_s
    m, c, k = osc.mass, osc.damping, osc.stiffness
    det = lam * lam + lam * c / m + k / m
    if abs(det) < 1e-18:  # résonance improbable : un fond à peine plus lent l'évite
        return _lowpass(osc, e0, v0, e1, v1, f0, tau_s * 1.001, weight, dt_s)
    decay = math.exp(lam * dt_s)
    gain = weight / (tau_s * det)
    return tuple(  # type: ignore[return-value]
        decay * f + gain * ((-c / m - lam) * (x1 - decay * x0) - (w1 - decay * w0))
        for f, x0, w0, x1, w1 in zip(f0, e0, v0, e1, v1, strict=True))


def fond_of(m: Mood, p: AffectParams) -> Vec3:
    """Le fond tel qu'il colore son humeur : borné."""
    return A.cap_norm(m.fond, p.fond_max)


def advance_mood(m: Mood | None, t: int, p: AffectParams, cw: Clockwork) -> Mood:
    if m is None:
        return Mood(Osc(common_home(t, p, cw), ZERO, t))
    if t <= m.at:
        return m
    oscillator = p.mood.oscillator()
    rest = _follow(oscillator, m.rest, t, p, cw, SETTLED_TAUS * p.mood.tau_s)
    dt = (t - m.at) / 1e6
    gap, vel = propagate(oscillator, m.gap, m.gap_velocity, ZERO, dt)
    fond = m.fond if m.asleep else _lowpass(oscillator, m.gap, m.gap_velocity, gap, vel, m.fond,
                                            p.fond_tau_us / 1e6, p.fond_weight, dt)
    return replace(m, rest=rest, gap=gap, gap_velocity=vel, fond=fond)


def mood_position(m: Mood, p: AffectParams) -> Vec3:
    return A.add(A.add(m.rest.position, m.gap), fond_of(m, p))


def _marked(m: Mood, mark: Mark) -> tuple[Mark, ...]:
    return (*m.marks, mark)[-MARKS:]


def push_mood(m: Mood, target: Vec3, gain: float, p: AffectParams, mark: Mark) -> Mood:
    """Une impulsion sur son humeur : une part de la distance vers ``target``."""
    base = A.add(m.rest.position, fond_of(m, p))
    moved = ratchet(A.add(base, m.gap), target, gain)
    return replace(m, gap=A.sub(moved, base), marks=_marked(m, mark))


def mood_target(m: Mood, emotion: Emotion, intensity: float, p: AffectParams) -> Vec3:
    """Sur le rayon qui va de là où elle en est (repos et fond) vers l'émotion."""
    return A.lerp(A.add(m.rest.position, fond_of(m, p)), A.ANCHORS[emotion], max(0.0, min(1.0, intensity)))


def fall_asleep(m: Mood) -> Mood:
    return replace(m, asleep=True)


def wake(m: Mood, p: AffectParams) -> Mood:
    """Le sommeil allège le fond ; ce qui en reste colore le réveil."""
    return replace(m, asleep=False, fond=A.scale(m.fond, 1.0 - p.sleep_relief))


# ── Les postures ──────────────────────────────────────────────────────────


def heal_rate(anchor: Vec3 | None, hostile: int, p: AffectParams) -> float:
    """Le taux de guérison d'une ancre (par seconde) : la chaleur dure, une
    hostilité répétée aussi, plafonnée."""
    if anchor is None:
        return 0.0
    base = p.anchor_half_life_us
    if anchor[0] >= 0:
        half = base * p.warm_heal_factor
    elif anchor[2] > 0:
        half = min(float(p.hostile_heal_max_us), base * (1.0 + hostile / p.hostile_heal_steps))
    else:
        half = base
    return math.log(2.0) / (max(1.0, half) / 1e6)


def heal(anchor: Vec3 | None, hostile: int, dt_us: int, p: AffectParams) -> Vec3 | None:
    """L'ancre après ``dt_us`` : elle décroît vers le repos moyen, en ligne droite
    (sa direction ne change jamais), et s'efface une fois guérie."""
    if anchor is None or dt_us <= 0:
        return anchor
    healed = A.scale(anchor, math.exp(-heal_rate(anchor, hostile, p) * dt_us / 1e6))
    return None if A.norm(healed) < HEALED_NORM else healed


def bond_at(bond: float, dt_us: int, p: AffectParams) -> float:
    if bond <= 0 or dt_us <= 0:
        return max(0.0, bond)
    return bond * math.exp(-math.log(2.0) * dt_us / max(1, p.bond_half_life_us))


def person_home(anchor: Vec3 | None, common: Vec3, p: AffectParams) -> Vec3:
    """Le repos propre d'une personne : le repos commun, plus une part de ce
    que la relation a installé."""
    return common if anchor is None else A.add(common, A.scale(anchor, p.anchor_weight))


def new_stance(t: int, p: AffectParams, cw: Clockwork) -> Stance:
    """Une posture neuve commence au repos, pas à l'origine."""
    return Stance(Osc(common_home(t, p, cw), ZERO, t))


def advance_stance(st: Stance, t: int, p: AffectParams, cw: Clockwork) -> Stance:
    if t <= st.at:
        return st
    oscillator = p.person.oscillator()
    dt_us = t - st.at
    anchor = heal(st.anchor, st.hostile, dt_us, p)
    offset = ZERO if st.anchor is None else A.scale(st.anchor, p.anchor_weight)
    rest = _follow(oscillator, st.rest, t, p, cw, SETTLED_TAUS * p.person.tau_s, offset,
                   heal_rate(st.anchor, st.hostile, p))
    gap, vel = propagate(oscillator, st.gap, st.gap_velocity, ZERO, dt_us / 1e6)
    return replace(st, rest=rest, gap=gap, gap_velocity=vel, anchor=anchor, bond=bond_at(st.bond, dt_us, p),
                   hostile=st.hostile if anchor is not None else 0)


def push_stance(st: Stance, target: Vec3, gain: float) -> Stance:
    moved = ratchet(st.position, target, gain)
    return replace(st, gap=A.sub(moved, st.rest.position))


def stance_target(st: Stance, emotion: Emotion, intensity: float) -> Vec3:
    """Sur le rayon qui va de son repos envers la personne vers l'émotion."""
    return A.lerp(st.rest.position, A.ANCHORS[emotion], max(0.0, min(1.0, intensity)))


def fold_alpha(st: Stance, p: AffectParams) -> float:
    """Ce qu'une déclaration fond dans l'ancre : moins, à mesure que leur
    histoire s'allonge (un mois d'amitié ne se défait pas en sept phrases)."""
    return p.anchor_alpha / (1.0 + st.days / p.anchor_history_days)


def fold_point(declared: Declared, current: Vec3, ref: Vec3, p: AffectParams) -> Vec3:
    """Le point vers lequel une déclaration tire l'ancre (``current``, en
    absolu) : sur le rayon repos moyen → émotion. L'empathie (être triste
    *avec* quelqu'un) la tire vers la tendresse depuis là où en est la
    relation : consoler rapproche, jamais ne refroidit."""
    if declared.emotion in EMPATHIC:
        return A.lerp(current, A.ANCHORS[Emotion.LOVE], p.empathy_tenderness * declared.intensity)
    return A.lerp(ref, A.ANCHORS[declared.emotion], declared.intensity)


def fold(st: Stance, declared: Declared, at: int, day: int, ref: Vec3, p: AffectParams) -> Stance:
    """Une déclaration envers une personne identifiable : l'ancre s'en
    rapproche, l'attachement en naît s'il y a de la chaleur ou de l'empathie."""
    days, last_day = (st.days + 1, day) if day != st.last_day else (st.days, st.last_day)
    st = replace(st, days=days, last_day=last_day)
    current = ref if st.anchor is None else A.add(ref, st.anchor)
    point = fold_point(declared, current, ref, p)
    absolute = A.cap_norm(A.lerp(current, point, fold_alpha(st, p)), p.anchor_max)
    anchor = A.sub(absolute, ref)
    bond = st.bond
    if declared.emotion in WARM or declared.emotion in EMPATHIC:
        bond = min(1.0, bond + p.bond_step * declared.intensity * (1.0 - bond))
    hostile = st.hostile + (1 if declared.emotion in HOSTILE else 0)
    return replace(st, anchor=None if A.norm(anchor) < HEALED_NORM else anchor, bond=bond, hostile=hostile,
                   folded_at=at)


def regard_of(anchor: Vec3 | None, bond: float, ref: Vec3, p: AffectParams) -> float:
    """Ce que la relation a installé, signé, dans [−1, 1] : la part du chemin du
    plaisir moyen vers le plaisir maximal (ou minimal), plus l'attachement."""
    part = 0.0
    if anchor is not None:
        delta = anchor[0]
        span = (1.0 - ref[0]) if delta >= 0 else (1.0 + ref[0])
        part = delta / max(1e-6, span)
    return max(-1.0, min(1.0, part + p.bond_regard * bond))


def raw_hostility(anchor: Vec3 | None, ref: Vec3, p: AffectParams) -> float:
    """Un déplaisir installé **et** dominant, sans l'amortissement de l'attachement."""
    if anchor is None:
        return 0.0
    displeasure = max(0.0, -anchor[0]) / max(1e-6, 1.0 + ref[0])
    dominance = max(0.0, min(1.0, anchor[2] / p.hostility_dominance))
    return max(0.0, min(1.0, displeasure * dominance))


def hostility_of(anchor: Vec3 | None, bond: float, wary_until: int, now: int, ref: Vec3, p: AffectParams) -> float:
    """La rancune : amortie par l'attachement, jamais sous la méfiance plancher
    qu'une inconnue très hostile laisse quelques jours."""
    value = raw_hostility(anchor, ref, p) * (1.0 - p.bond_damping * max(0.0, min(1.0, bond)))
    if now < wary_until:
        value = max(value, p.wary_floor)
    return max(0.0, min(1.0, value))


def relation_at(st: Stance, now: int, p: AffectParams) -> tuple[Vec3 | None, float]:
    """L'ancre et l'attachement à l'instant (sans propager les oscillateurs)."""
    dt = max(0, now - st.at)
    return heal(st.anchor, st.hostile, dt, p), bond_at(st.bond, dt, p)


# ── Impulsions ────────────────────────────────────────────────────────────


def ratchet(position: Vec3, target: Vec3, gain: float) -> Vec3:
    """Une impulsion parcourt une part de la distance restante vers sa cible :
    jamais au-delà (bornée par construction), et deux impulsions de même
    signe s'additionnent en se rapprochant."""
    g = max(0.0, min(1.0, gain))
    return A.clamp(A.add(position, A.scale(A.sub(target, position), g)), 1.2)


def resonant_gain(target: Vec3, p: AffectParams) -> float:
    base = p.person_gain
    anchor = A.ANCHORS[p.background]
    na, nt = A.norm(anchor), A.norm(target)
    if p.resonance <= 0 or base <= 0 or na < 1e-9 or nt < 1e-9:
        return base
    cos = A.dot(anchor, target) / (na * nt)
    return base if cos <= 0 else min(1.0, base * (1.0 + p.resonance * cos))


def mood_gain(intensity: float, p: AffectParams) -> float:
    base = p.mood_gain
    if base <= 0:
        return 0.0
    force = max(0.0, min(1.0, intensity))
    return min(p.mood_gain_cap, base * p.mood_gain_max_factor, base * (p.mood_gain_floor + p.mood_gain_slope * force))


# ── Lectures ──────────────────────────────────────────────────────────────


def fresh(st: Stance, now: int, p: AffectParams) -> Declared | None:
    """Ce qu'elle a déclaré envers la personne, en décroissance au rythme de
    sa posture ; ``None`` une fois sous le plancher (plus de fenêtre dure)."""
    declared = Declared.decode(st.declared)
    if declared is None or now < st.declared_at:
        return declared
    decayed = declared.intensity * math.exp(-(now - st.declared_at) / 1e6 / p.person.tau_s)
    return None if decayed < p.declared_floor else Declared(declared.emotion, decayed)


def anchored(st: Stance, now: int, p: AffectParams) -> bool:
    """Plusieurs tours de suite dans le même sens, et un écart net au repos."""
    gap = st.gap
    if A.norm(gap) < p.anchored_min_norm:
        return False
    agreeing = 0
    for at, name in st.recent:
        emotion = A.emotion_of(name)
        if emotion is None or emotion is Emotion.NEUTRAL or now - at > p.anchored_window_us:
            continue
        if A.dot(A.sub(A.ANCHORS[emotion], st.rest.position), gap) > 0:
            agreeing += 1
    return agreeing >= p.anchored_min_impulses


def face(person_pos: Vec3, mood_pos: Vec3, background: Emotion, declared: Declared | None = None
         ) -> tuple[Emotion, float, list[tuple[Emotion, float]], tuple[Emotion, float], tuple[Emotion, float]]:
    """Ce que montre le visage : la balise de sa dernière réplique tant qu'elle
    dure (en décroissance), sinon 60 % la posture, 40 % son humeur."""
    blended = A.add(A.scale(person_pos, 0.6), A.scale(mood_pos, 0.4))
    label, intensity = A.label(blended)
    parts = A.blend(blended, top_k=2)
    if intensity < 0.05:
        label, intensity = background, 0.1
        parts = parts or [(background, 0.1)]
    pl, pi = A.label(person_pos)
    ml, mi = A.label(mood_pos)
    person_part = (pl if pi > 0.05 else background, round(pi, 2))
    mood_part = (ml if mi > 0.05 else background, round(mi, 2))
    if declared is not None:
        shown = round(declared.intensity, 2)
        under = [(e, w) for e, w in parts if e is not declared.emotion][:1]
        return declared.emotion, shown, [(declared.emotion, shown), *under], (declared.emotion, shown), mood_part
    return label, round(intensity, 2), parts, person_part, mood_part
