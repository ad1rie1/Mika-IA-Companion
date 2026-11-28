"""Preuve M0 — déclenchement à taux : les instants de déclenchement ne
dépendent pas de la cadence d'évaluation, et suivent la loi exponentielle
attendue (test de Kolmogorov-Smirnov)."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass

from mika.kernel.arbitration import Anyone, Candidate
from mika.kernel.clock import US
from mika.kernel.episode import EpisodePolicy
from mika.kernel.faculty import Faculty
from mika.kernel.registry import ArbitrationPolicy
from mika.sim.clock import run_virtual
from tests.fixtures.harness import build, events_of

RATE = 1 / 600  # par seconde, au maximum
POLICY = ArbitrationPolicy(thresholds={"MURMUR": 0.0}, max_rates={"MURMUR": RATE})
POLICIES = {"MURMUR": EpisodePolicy(kind="MURMUR", role=None, voice=False, lane="background")}


@dataclass(frozen=True, slots=True)
class Quiet:
    pass


CHAT = Faculty("chat", state=Quiet, init=lambda p: Quiet())


@CHAT.propose(kinds=["MURMUR"], reasons={"pensée": (-2.0, 2.0)})
def _think(state, frame):
    return [Candidate("MURMUR", Anyone.NONE, "pensée", 0.0)]


def first_firing(tmp, seed: int, quantum_s: float) -> float:
    kernel, clock, _ = build(tmp, [CHAT], policies=POLICIES, arbitration=POLICY, seed=seed,
                             arbiter_quantum_s=quantum_s)

    async def main():
        await kernel.start()
        t0 = clock.now()
        for _ in range(400):
            await asyncio.sleep(600)
            if kernel.mind.root.slices["kernel"].selections:
                break
        sel = events_of(kernel, "kernel.selected")
        await kernel.stop()
        return (sel[0].at - t0) / US if sel else math.inf

    return run_virtual(kernel.deps.clock, main)


def ks_two_sample(a: list[float], b: list[float]) -> float:
    a, b = sorted(a), sorted(b)
    points = sorted(set(a) | set(b))
    d = 0.0
    for x in points:
        fa = sum(1 for v in a if v <= x) / len(a)
        fb = sum(1 for v in b if v <= x) / len(b)
        d = max(d, abs(fa - fb))
    return d


def ks_exponential(sample: list[float], mean: float) -> float:
    s = sorted(sample)
    n = len(s)
    return max(max((i + 1) / n - (1 - math.exp(-x / mean)), (1 - math.exp(-x / mean)) - i / n)
               for i, x in enumerate(s))


def test_firing_times_do_not_depend_on_cadence(tmp_path):
    n = 120
    fast = [first_firing(tmp_path / f"f{s}", s, 10.0) for s in range(n)]
    slow = [first_firing(tmp_path / f"s{s}", s, 60.0) for s in range(n)]
    assert all(math.isfinite(x) for x in fast + slow)
    # Plus fort qu'une égalité en loi : graine par graine, les mêmes instants.
    assert max(abs(a - b) for a, b in zip(fast, slow, strict=True)) < 1e-3
    assert ks_two_sample(fast, slow) < 0.2
    # σ(0) = 0,5 : intensité effective RATE/2, moyenne 1 200 s
    d = ks_exponential(fast, mean=1 / (RATE * 0.5))
    assert d < 1.63 / math.sqrt(n), d
