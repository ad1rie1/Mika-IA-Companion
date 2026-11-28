"""Une semaine simulée avec des facultés jouets, des interlocuteurs
synthétiques et un LLM aux latences log-normales. Sert à la preuve de
déterminisme (lancée en sous-processus sous plusieurs ``PYTHONHASHSEED``)."""

from __future__ import annotations

import asyncio
import json
import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from mika.contracts.runtime import PERCEPTION_RECEIVED, UTTERANCE
from mika.kernel.arbitration import Candidate
from mika.kernel.clock import DAY, HOUR, US
from mika.kernel.codec import digest
from mika.kernel.facts import FactFamily
from mika.kernel.faculty import Faculty
from mika.kernel.guards import Guard
from mika.kernel.registry import ArbitrationPolicy
from mika.kernel.state import FrozenDict
from mika.sim.clock import run_virtual
from mika.sim.llm.scripted import LognormalLatency
from mika.sim.rng import RngTree
from tests.fixtures.harness import build, said

PEOPLE = ("alice", "bob", "carol")


@dataclass(frozen=True, slots=True)
class FriendState:
    last_in: FrozenDict[str, int] = FrozenDict()
    last_out: FrozenDict[str, int] = FrozenDict()
    spoken: int = 0


FRIENDLY = Faculty("friendly", state=FriendState, init=lambda p: FriendState())
SILENCE = FactFamily("friendly.silence_h", arg=str, type=float, time_varying=True)


@FRIENDLY.reducer(PERCEPTION_RECEIVED)
def _in(s: FriendState, e, cx) -> FriendState:
    return replace(s, last_in=s.last_in.set(e.data.handle, e.at))


@FRIENDLY.reducer(UTTERANCE)
def _out(s: FriendState, e, cx) -> FriendState:
    if e.data.target is None:
        return s
    return replace(s, last_out=s.last_out.set(e.data.target, e.at), spoken=s.spoken + 1)


@FRIENDLY.fact(SILENCE)
def _silence(s: FriendState, cx, who: str) -> float:
    last = max(s.last_in.get(who, 0), s.last_out.get(who, 0))
    return (cx.now - last) / HOUR if last else 0.0


@FRIENDLY.propose(kinds=["INITIATIVE"], reasons={"manque": (0.0, 3.0)}, reads=[SILENCE])
def _miss(s: FriendState, frame):
    out = []
    for who in PEOPLE:
        h = frame.get(SILENCE(who))
        if h > 6:
            out.append(Candidate("INITIATIVE", who, "manque", min(3.0, math.log(h / 6) + 1.0),
                                 guards=(Guard("toujours_silencieux", reads=(SILENCE(who),)),)))
    return out


ARBITRATION = ArbitrationPolicy(thresholds={"INITIATIVE": 1.5}, max_rates={"INITIATIVE": 1 / 3600})


async def world(kernel, rng: RngTree, days: int) -> None:
    """Chaque personne écrit selon son rythme, pendant la journée."""

    async def person(who: str) -> None:
        r = rng.child("personne", who).rng()
        mean_gap_h = {"alice": 5, "bob": 14, "carol": 30}[who]
        clock = kernel.deps.clock
        end = clock.now() + days * DAY
        while True:
            gap = r.expovariate(1 / (mean_gap_h * HOUR))
            if clock.now() + gap >= end:
                return
            await asyncio.sleep(gap / US)
            await kernel.perceive(said(who, f"message de {who} n°{r.randint(1, 999)}"))

    await asyncio.gather(*(person(w) for w in PEOPLE))


def state_digest(root, registry) -> str:
    return digest({o: root.slices[o] for o in registry.persisted_owners()})


def run_week(root_dir: Path, seed: int = 7, days: int = 7) -> dict:
    kernel, clock, llm = build(
        root_dir, [FRIENDLY], latency=LognormalLatency(3.0, 0.6, seed), arbitration=ARBITRATION, seed=seed,
        snapshot_every=400,
    )

    async def main():
        await kernel.start()
        await world(kernel, RngTree(seed), days)
        await asyncio.sleep(3600)
        await kernel.lanes.join()
        log = digest([(s.seq, s.type, s.data) for s in kernel.mind.store.read()])
        initiatives = sum(1 for s in kernel.mind.store.read(types={"episode.started"}) if '"INITIATIVE"' in s.data)
        await kernel.stop()
        return {
            "state": state_digest(kernel.mind.root, kernel.registry),
            "log": log,
            "events": kernel.mind.head,
            "spoken": kernel.mind.root.slices["friendly"].spoken,
            "initiatives": initiatives,
        }

    return run_virtual(clock, main)


if __name__ == "__main__":
    print(json.dumps(run_week(Path(sys.argv[1]), int(sys.argv[2]))))
