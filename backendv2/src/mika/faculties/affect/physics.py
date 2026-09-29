"""La physique de l'affect, en forme close.

Deux sortes d'oscillateurs : l'humeur générale (repos commun) et une posture
par personne (repos propre : 60 % de ce qu'elle a déjà provoqué — l'ancre —,
40 % du repos commun). Le repos commun est constant par morceaux : il change
aux débuts de phase circadienne, des instants déterministes. L'ancre guérit
vers le repos commun avec une demi-vie de quelques jours ; entre deux
frontières, le repos d'une personne glisse donc exponentiellement, ce que
``propagate_toward`` résout exactement. Lire une position ne dépend jamais
du moment de la lecture.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from zoneinfo import ZoneInfo

from mika.faculties.affect.params import AffectParams
from mika.kernel.clock import DAY, local, next_local
from mika.kernel.dynamics import propagate, propagate_toward
from mika.vocab import affect as A
from mika.vocab import circadian
from mika.vocab.affect import Declared, Emotion, Vec3

ZERO: Vec3 = (0.0, 0.0, 0.0)
#: Au-delà de tant de constantes de temps, la position est le repos.
SETTLED_TAUS = 40.0
#: Au-delà de tant de demi-vies, l'ancre est guérie.
HEALED_HALF_LIVES = 20.0
RECENT_IMPULSES = 8


@dataclass(frozen=True, slots=True)
class Osc:
    position: Vec3
    velocity: Vec3
    at: int


@dataclass(frozen=True, slots=True)
class Stance:
    osc: Osc
    anchor: Vec3 | None = None  # valable à ``osc.at``
    folded_at: int = 0
    declared: str | None = None  # ``Declared.encode()``
    declared_at: int = 0
    recent: tuple[tuple[int, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Clockwork:
    """Ce que la physique doit savoir du temps : fuseau et rythme."""

    tz: ZoneInfo
    rhythm: circadian.Profile


def common_home(t: int, p: AffectParams, cw: Clockwork) -> Vec3:
    phase = circadian.phase_at(t, cw.tz, cw.rhythm)
    return A.add(A.to_pad(p.background, p.background_weight), circadian.tint(phase, cw.rhythm))


def person_home(anchor: Vec3 | None, base: Vec3, p: AffectParams) -> Vec3:
    if anchor is None:
        return base
    return A.add(A.scale(anchor, p.anchor_weight), A.scale(base, 1.0 - p.anchor_weight))


def _segments(t0: int, t1: int, cw: Clockwork) -> list[tuple[int, int]]:
    cuts = [t0, *circadian.boundaries(t0, t1, cw.tz, cw.rhythm), t1]
    return [(a, b) for a, b in zip(cuts, cuts[1:], strict=False) if b > a]


def advance_mood(osc: Osc | None, t: int, p: AffectParams, cw: Clockwork) -> Osc:
    if osc is None:
        return Osc(common_home(t, p, cw), ZERO, t)
    if t <= osc.at:
        return osc
    oscillator = p.mood.oscillator()
    if (t - osc.at) / 1e6 > SETTLED_TAUS * p.mood.tau_s:
        return Osc(common_home(t, p, cw), ZERO, t)
    pos, vel = osc.position, osc.velocity
    for a, b in _segments(osc.at, t, cw):
        pos, vel = propagate(oscillator, pos, vel, common_home(a, p, cw), (b - a) / 1e6)
    return Osc(pos, vel, t)


def new_stance(t: int, p: AffectParams, cw: Clockwork) -> Stance:
    """Une posture neuve commence au repos, pas à l'origine."""
    return Stance(Osc(common_home(t, p, cw), ZERO, t))


def _heal_segments(anchor: Vec3, t0: int, t1: int, p: AffectParams, cw: Clockwork) -> Vec3:
    for a, b in _segments(t0, t1, cw):
        anchor = A.lerp(anchor, common_home(a, p, cw), 1.0 - math.exp(-p.heal_rate * (b - a) / 1e6))
    return anchor


def _day_map(start: int, end: int, p: AffectParams, cw: Clockwork) -> tuple[float, Vec3]:
    """Une journée de guérison comme application affine : ``a ↦ k·a + c``
    (composée de ses segments de phase)."""
    k, c = 1.0, (0.0, 0.0, 0.0)
    for a, b in _segments(start, end, cw):
        w = 1.0 - math.exp(-p.heal_rate * (b - a) / 1e6)
        k, c = k * (1.0 - w), A.add(A.scale(c, 1.0 - w), A.scale(common_home(a, p, cw), w))
    return k, c


def _plain_days(start: int, end: int, tz: ZoneInfo) -> int:
    """Combien de jours de 24 h à partir de minuit ``start`` avant ``end`` ou
    le prochain changement d'heure. Deux changements d'heure sont séparés de
    cinq mois au moins : au-delà de quatre mois, on avance prudemment."""
    remaining = (end - start) // DAY
    offset = local(start, tz).utcoffset()
    if remaining > 120:
        n = 0
        while n < remaining and local(start + (n + 1) * DAY, tz).utcoffset() == offset:
            n += 1
        return n
    lo, hi = 0, remaining  # le plus grand n dont le minuit a encore le même décalage
    if local(start + hi * DAY, tz).utcoffset() == offset:
        return hi
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if local(start + mid * DAY, tz).utcoffset() == offset:
            lo = mid
        else:
            hi = mid
    return lo


def heal(anchor: Vec3 | None, t0: int, t1: int, p: AffectParams, cw: Clockwork) -> Vec3 | None:
    """L'ancre ramenée vers le repos commun, phase par phase. Sur plusieurs
    jours, les journées de 24 h se ressemblent toutes : leur composition est
    calculée une fois puis élevée à la puissance (forme close, O(1) en jours)."""
    if anchor is None or t1 <= t0:
        return anchor
    if (t1 - t0) > HEALED_HALF_LIVES * p.anchor_half_life_us:
        return None
    if t1 - t0 <= 2 * DAY:
        return _heal_segments(anchor, t0, t1, p, cw)
    midnight = next_local(t0, 0, 0, cw.tz)
    anchor = _heal_segments(anchor, t0, midnight, p, cw)
    cursor = midnight
    while cursor < t1:
        nxt = next_local(cursor, 0, 0, cw.tz)
        if nxt > t1:
            break
        if nxt - cursor != DAY:  # un jour de changement d'heure : exactement
            anchor = _heal_segments(anchor, cursor, nxt, p, cw)
            cursor = nxt
            continue
        # une suite de jours de 24 h : jusqu'au prochain changement d'heure (ou à t1)
        n = _plain_days(cursor, t1, cw.tz)
        probe = cursor + n * DAY
        k, c = _day_map(cursor, cursor + DAY, p, cw)
        kn = k ** n
        anchor = A.add(A.scale(anchor, kn), A.scale(c, (1.0 - kn) / (1.0 - k) if k < 1.0 else float(n)))
        cursor = probe
    return _heal_segments(anchor, cursor, t1, p, cw)


def advance_stance(st: Stance, t: int, p: AffectParams, cw: Clockwork) -> Stance:
    if t <= st.osc.at:
        return st
    settled = (t - st.osc.at) / 1e6 > SETTLED_TAUS * p.person.tau_s
    if settled:
        # au repos : seule l'ancre a bougé (forme close sur plusieurs jours)
        anchor = heal(st.anchor, st.osc.at, t, p, cw)
        return replace(st, osc=Osc(person_home(anchor, common_home(t, p, cw), p), ZERO, t), anchor=anchor)
    oscillator = p.person.oscillator()
    pos, vel, anchor = st.osc.position, st.osc.velocity, st.anchor
    for a, b in _segments(st.osc.at, t, cw):
        base = common_home(a, p, cw)
        dt = (b - a) / 1e6
        if anchor is None:
            if not settled:
                pos, vel = propagate(oscillator, pos, vel, base, dt)
            continue
        offset = A.scale(A.sub(anchor, base), p.anchor_weight)
        if not settled:
            pos, vel = propagate_toward(oscillator, pos, vel, base, offset, p.heal_rate, dt)
        anchor = A.lerp(anchor, base, 1.0 - math.exp(-p.heal_rate * dt))
    if anchor is not None and (t - st.osc.at) > HEALED_HALF_LIVES * p.anchor_half_life_us:
        anchor = None
    if settled:
        pos, vel = person_home(anchor, common_home(t, p, cw), p), ZERO
    return replace(st, osc=Osc(pos, vel, t), anchor=anchor)


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


def fold_anchor(anchor: Vec3 | None, declared: Declared, home: Vec3, p: AffectParams) -> Vec3:
    """Une ancre naît au repos commun ; chaque déclaration s'y fond à α."""
    current = anchor if anchor is not None else home
    return A.cap_norm(A.lerp(current, A.to_pad(declared.emotion, declared.intensity), p.anchor_alpha), p.anchor_max)


def fresh(st: Stance, now: int, p: AffectParams) -> Declared | None:
    if st.declared is None or now - st.declared_at > p.declared_window_us:
        return None
    return Declared.decode(st.declared)


def anchored(st: Stance, now: int, p: AffectParams) -> bool:
    pos = st.osc.position
    if A.norm(pos) < p.anchored_min_norm:
        return False
    agreeing = 0
    for at, name in st.recent:
        emotion = A.emotion_of(name)
        if emotion is None or now - at > p.anchored_window_us:
            continue
        if A.dot(A.ANCHORS[emotion], pos) > 0:
            agreeing += 1
    return agreeing >= p.anchored_min_impulses


def peak(osc: Osc, home: Vec3, p: AffectParams, horizon_s: int = 60) -> Vec3:
    """Là où va la posture dans la minute (la position, si elle revient déjà)."""
    oscillator = p.person.oscillator()
    best, best_d = osc.position, A.distance(osc.position, home)
    pos, vel = osc.position, osc.velocity
    for _ in range(horizon_s):
        pos, vel = propagate(oscillator, pos, vel, home, 1.0)
        d = A.distance(pos, home)
        if d <= best_d:
            break
        best, best_d = pos, d
    return best


def face(person_pos: Vec3, mood_pos: Vec3, background: Emotion) -> tuple[Emotion, float, list[tuple[Emotion, float]],
                                                                         tuple[Emotion, float], tuple[Emotion, float]]:
    blended = A.add(A.scale(person_pos, 0.6), A.scale(mood_pos, 0.4))
    label, intensity = A.label(blended)
    parts = A.blend(blended, top_k=2)
    if intensity < 0.05:
        label, intensity = background, 0.1
        parts = parts or [(background, 0.1)]
    pl, pi = A.label(person_pos)
    ml, mi = A.label(mood_pos)
    return (label, round(intensity, 2), parts, (pl if pi > 0.05 else background, round(pi, 2)),
            (ml if mi > 0.05 else background, round(mi, 2)))
