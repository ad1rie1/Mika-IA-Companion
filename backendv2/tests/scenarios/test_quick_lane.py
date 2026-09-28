"""La voie rapide : S01, S03, S13 réduit — en moins d'une minute, et la
preuve des pannes (≥ 200 arrêts brutaux simulés) en voie lente."""

from __future__ import annotations

import logging
import time

import pytest

from mika.app.composition import for_simulation
from mika.sim.scenarios import QUICK, run_lane, run_plan


@pytest.fixture(autouse=True)
def _quiet():
    logging.disable(logging.WARNING)  # les tentatives d'écriture après une panne sont attendues
    yield
    logging.disable(logging.NOTSET)


def test_quick_lane_is_green_and_fast(tmp_path):
    t0 = time.perf_counter()
    results = run_lane(for_simulation(), tmp_path)
    elapsed = time.perf_counter() - t0
    failures = [(r.name, r.seed, c.name, c.detail) for r in results for c in r.checks if not c.ok]
    assert not failures, failures
    assert elapsed < 60, elapsed


@pytest.mark.slow
def test_two_hundred_crashes_lose_nothing_and_repeat_nothing(tmp_path):
    plan = next(p for p in QUICK if p.name.startswith("S13"))
    crashes = 0
    seed = 0
    while crashes < 200:
        seed += 1
        d = tmp_path / f"s{seed}"
        d.mkdir()
        r = run_plan(plan, for_simulation(), d, seed)
        assert r.ok, [(c.name, c.detail) for c in r.checks if not c.ok]
        crashes += r.metrics["crashes"]
    assert crashes >= 200
