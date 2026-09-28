"""Dynamiques exactes à tout instant.

Oscillateur amorti linéaire ``m·y'' + c·y' + k·y = 0`` (``y`` = écart au point
de repos), propagé en forme close par l'exponentielle de sa matrice 2×2 :
``exp(A·t) = e^{s·t}·[f0·I + f1·(A − s·I)]`` avec ``s = −c/2m`` et ``d² = s² − k/m``.
Selon le signe de ``d²`` : sur-amorti (cosh, sinh/d), sous-amorti (cos, sin/ω)
ou critique (1, t). Aucune dépendance au pas de lecture : propager ``a`` puis
``b`` égale propager ``a+b`` (semi-groupe), ce que les tests vérifient.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

Vec3 = tuple[float, float, float]
ZERO: Vec3 = (0.0, 0.0, 0.0)


@dataclass(frozen=True, slots=True)
class Oscillator:
    mass: float
    damping: float
    stiffness: float

    @property
    def tau(self) -> float:
        """Constante de temps de l'enveloppe (secondes)."""
        return 2.0 * self.mass / max(1e-12, self.damping)

    @property
    def zeta(self) -> float:
        return self.damping / (2.0 * math.sqrt(self.mass * self.stiffness))


def _coefficients(osc: Oscillator, t: float) -> tuple[float, float, float, float]:
    """Les quatre coefficients de exp(A·t) : y' = a·y + b·v ; v' = c·y + d·v.

    Sur-amorti, ``e^{st}·cosh(dt)`` s'écrit comme demi-somme d'exponentielles
    décroissantes : aucun débordement, même à très grand ``t``.
    """
    m, c, k = osc.mass, osc.damping, osc.stiffness
    s = -c / (2.0 * m)
    disc = s * s - k / m
    scale = abs(k / m) + s * s
    eps = 1e-12 * max(1.0, scale)
    if disc > eps:
        d = math.sqrt(disc)
        e_plus = math.exp((s + d) * t)
        e_minus = math.exp((s - d) * t)
        ef0 = 0.5 * (e_plus + e_minus)
        ef1 = (e_plus - e_minus) / (2.0 * d)
    else:
        e = math.exp(s * t)
        if disc < -eps:
            w = math.sqrt(-disc)
            ef0 = e * math.cos(w * t)
            ef1 = e * math.sin(w * t) / w
        else:
            ef0 = e
            ef1 = e * t
    a = ef0 - s * ef1
    b = ef1
    cc = -(k / m) * ef1
    dd = ef0 + s * ef1
    return a, b, cc, dd


def propagate(osc: Oscillator, position: Vec3, velocity: Vec3, home: Vec3, dt_s: float) -> tuple[Vec3, Vec3]:
    """État après ``dt_s`` secondes, le point de repos restant ``home``."""
    if dt_s <= 0:
        return position, velocity
    a, b, c, d = _coefficients(osc, dt_s)
    pos = []
    vel = []
    for x, v, h in zip(position, velocity, home, strict=True):
        y = x - h
        pos.append(h + a * y + b * v)
        vel.append(c * y + d * v)
    return (pos[0], pos[1], pos[2]), (vel[0], vel[1], vel[2])


def propagate_toward(
    osc: Oscillator, position: Vec3, velocity: Vec3, home_end: Vec3, home_offset: Vec3, rate: float, dt_s: float
) -> tuple[Vec3, Vec3]:
    """État après ``dt_s`` secondes quand le repos lui-même glisse
    exponentiellement : ``repos(t) = home_end + home_offset·e^{−rate·t}``.

    Solution exacte : une particulière ``home_end + B·e^{−rate·t}`` avec
    ``B = k·offset / (m·rate² − c·rate + k)``, plus la solution libre de
    l'écart restant. À ``rate = 0`` c'est ``propagate`` vers un repos fixe.
    """
    if dt_s <= 0:
        return position, velocity
    m, c, k = osc.mass, osc.damping, osc.stiffness
    denom = m * rate * rate - c * rate + k
    if abs(denom) < 1e-18:
        raise ValueError("résonance : le repos glisse au rythme propre de l'oscillateur")
    coeff = k / denom
    decay = math.exp(-rate * dt_s)
    pos = []
    vel = []
    for x, v, h, off in zip(position, velocity, home_end, home_offset, strict=True):
        big_b = coeff * off
        z0 = x - h - big_b
        w0 = v + rate * big_b
        (z,), (w,) = _free1(osc, z0, w0, dt_s)
        pos.append(h + big_b * decay + z)
        vel.append(-rate * big_b * decay + w)
    return (pos[0], pos[1], pos[2]), (vel[0], vel[1], vel[2])


def _free1(osc: Oscillator, y: float, v: float, dt_s: float) -> tuple[tuple[float], tuple[float]]:
    a, b, c, d = _coefficients(osc, dt_s)
    return (a * y + b * v,), (c * y + d * v,)


def euler_reference(osc: Oscillator, position: Vec3, velocity: Vec3, home: Vec3, dt_s: float, step_s: float = 0.5) -> tuple[Vec3, Vec3]:
    """Intégration semi-implicite d'Euler à petit pas : l'oracle du propagateur."""
    x = list(position)
    v = list(velocity)
    remaining = dt_s
    while remaining > 1e-12:
        h = min(step_s, remaining)
        for i in range(3):
            acc = (-osc.stiffness * (x[i] - home[i]) - osc.damping * v[i]) / osc.mass
            v[i] += acc * h
            x[i] += v[i] * h
        remaining -= h
    return (x[0], x[1], x[2]), (v[0], v[1], v[2])


def first_crossing(
    fn: Callable[[int], float], t0: int, t1: int, level: float, *, samples: int = 64, tol_us: int = 1_000_000
) -> int | None:
    """Le premier instant de ``[t0, t1]`` où ``fn`` franchit ``level``
    (changement de signe de ``fn − level``), trouvé par échantillonnage puis
    bissection ; ``None`` s'il n'y en a pas."""
    if t1 <= t0:
        return None
    f0 = fn(t0) - level
    if f0 == 0:
        return t0
    step = (t1 - t0) / samples
    prev_t, prev_f = t0, f0
    for i in range(1, samples + 1):
        t = t0 + round(i * step) if i < samples else t1
        f = fn(t) - level
        if f == 0:
            return t
        if (f > 0) != (prev_f > 0):
            lo, hi, flo = prev_t, t, prev_f
            while hi - lo > tol_us:
                mid = (lo + hi) // 2
                fm = fn(mid) - level
                if (fm > 0) == (flo > 0):
                    lo, flo = mid, fm
                else:
                    hi = mid
            return hi
        prev_t, prev_f = t, f
    return None
