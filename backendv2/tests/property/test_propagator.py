"""Preuve M0 — propagateur exact : conforme à Euler à petit pas sur la grille
de paramètres de la v1, semi-groupe à 1e-9, lecture en quelques microsecondes."""

from __future__ import annotations

import itertools
import math
import time

from hypothesis import given, settings
from hypothesis import strategies as st

from mika.kernel.dynamics import Oscillator, euler_reference, first_crossing, propagate


def v1_params(volatility: float, recovery: float) -> Oscillator:
    """La dérivation des paramètres de la v1 (emotion/physics.py::derive_params)."""
    mass = max(0.25, min(4.0, 1.0 / volatility))
    tau = 1800.0 * (240.0 / 1800.0) ** ((recovery - 0.05) / 0.95)
    zeta = 1.0 - 0.35 * volatility
    omega0 = 1.0 / (zeta * tau)
    return Oscillator(mass=mass, damping=2.0 * mass / tau, stiffness=mass * omega0 * omega0)


GRID = [v1_params(v, r) for v, r in itertools.product((0.1, 0.4, 0.7, 1.0), (0.05, 0.5, 1.0))]


def test_closed_form_matches_small_step_euler_on_v1_grid():
    home = (0.1, -0.05, 0.02)
    starts = [((0.8, -0.6, 0.3), (0.0, 0.0, 0.0)), ((-0.5, 0.4, -0.7), (0.002, -0.001, 0.0))]
    worst = 0.0
    for osc in GRID:
        for (x0, v0) in starts:
            for dt in (1.0, 60.0, 600.0, 1800.0):
                exact, _ = propagate(osc, x0, v0, home, dt)
                approx, _ = euler_reference(osc, x0, v0, home, dt, step_s=0.05)
                worst = max(worst, max(abs(a - b) for a, b in zip(exact, approx, strict=True)))
    assert worst < 1e-3, worst


@settings(max_examples=300, deadline=None)
@given(
    idx=st.integers(0, len(GRID) - 1),
    a=st.floats(0.0, 5000.0),
    b=st.floats(0.0, 5000.0),
    x=st.tuples(*[st.floats(-1.0, 1.0)] * 3),
    v=st.tuples(*[st.floats(-0.01, 0.01)] * 3),
)
def test_semigroup(idx, a, b, x, v):
    osc = GRID[idx]
    home = (0.05, 0.0, -0.02)
    p1, v1 = propagate(osc, x, v, home, a)
    p2, v2 = propagate(osc, p1, v1, home, b)
    p3, v3 = propagate(osc, x, v, home, a + b)
    assert all(math.isclose(i, j, abs_tol=1e-9) for i, j in zip(p2, p3, strict=True))
    assert all(math.isclose(i, j, abs_tol=1e-9) for i, j in zip(v2, v3, strict=True))


def test_relaxation_is_bounded_and_returns_home():
    osc = GRID[5]
    home = (0.2, 0.1, 0.0)
    pos, _ = propagate(osc, (1.0, -1.0, 1.0), (0.0, 0.0, 0.0), home, 20 * osc.tau)
    assert all(abs(p - h) < 1e-3 for p, h in zip(pos, home, strict=True))


def test_read_cost_is_microseconds():
    osc = GRID[4]
    n = 20_000
    t0 = time.perf_counter()
    for i in range(n):
        propagate(osc, (0.5, -0.2, 0.1), (0.0, 0.0, 0.0), (0.1, 0.0, 0.0), float(i % 3600))
    per_call_us = (time.perf_counter() - t0) / n * 1e6
    assert per_call_us <= 20.0, per_call_us


def test_first_crossing_finds_the_instant():
    osc = GRID[5]
    home = (0.0, 0.0, 0.0)

    def excursion(t_us: int) -> float:
        pos, _ = propagate(osc, (0.8, 0.0, 0.0), (0.0, 0.0, 0.0), home, t_us / 1e6)
        return abs(pos[0])

    t = first_crossing(excursion, 0, int(10 * osc.tau * 1e6), 0.4)
    assert t is not None
    assert abs(excursion(t) - 0.4) < 0.01
