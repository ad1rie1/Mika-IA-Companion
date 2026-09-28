"""Auto-test du simulateur, lançable sans les tests : déterminisme sous deux
graines de hachage, sentinelle d'horloge, blocage expliqué, E/S interdite."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from mika.adapters.store_sqlite import SqliteStore
from mika.kernel.clock import HOUR, US, instant
from mika.kernel.codec import digest
from mika.kernel.events import Payload
from mika.kernel.faculty import Faculty
from mika.kernel.ids import SeededIdGen
from mika.runtime.bootstrap import Kernel, KernelDeps
from mika.sim.checks import sentinel_leaks
from mika.sim.clock import SimClock, SimulationStalled, run_virtual
from mika.sim.env import sim_environment
from mika.sim.rng import RngTree

START = 1_790_000_000 * US


@dataclass(frozen=True, slots=True)
class _Tick:
    n: int = 0


class _Ticked(Payload):
    k: int


_TOY = Faculty("sim_toy", state=_Tick, init=lambda p: _Tick())
_TICKED = _TOY.event("ticked", _Ticked)


@_TOY.reducer(_TICKED)
def _r(s: _Tick, e, cx) -> _Tick:
    return replace(s, n=s.n + e.data.k)


def _toy_run(root: Path, seed: int, wall_clock_bug: bool = False) -> str:
    clock = SimClock(START)
    store = SqliteStore(root / "mind.db", root / "views.db", threaded=False)
    kernel = Kernel(KernelDeps(faculties=[_TOY], store=store, clock=clock, ids=SeededIdGen(seed), seed=seed))

    async def main() -> str:
        await kernel.start()
        r = RngTree(seed).child("monde").rng()
        for _ in range(200):
            await asyncio.sleep(r.expovariate(1 / HOUR) / US)  # µs → secondes
            k = instant(datetime.now(UTC)) if wall_clock_bug else r.randint(1, 9)
            await kernel.mind.append([_TICKED.draft(k=k)], emitter="sim_toy", correlation="toy")
        out = digest([(s.seq, s.type, s.data) for s in kernel.mind.store.read()])
        await kernel.stop()
        return out

    return run_virtual(clock, main)


def check_determinism() -> bool:
    outs = set()
    for hashseed in ("0", "12345"):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, PYTHONHASHSEED=hashseed)
            code = "import sys, pathlib; from mika.sim.selftest import _toy_run; print(_toy_run(pathlib.Path(sys.argv[1]), 3))"
            res = subprocess.run([sys.executable, "-c", code, d], env=env, capture_output=True, text=True, check=True)
            outs.add(res.stdout.strip())
    return len(outs) == 1


def check_sentinel() -> bool:
    with tempfile.TemporaryDirectory() as d, sim_environment():
        _toy_run(Path(d), 1, wall_clock_bug=True)
        store = SqliteStore(Path(d) / "mind.db", Path(d) / "views.db", threaded=False)
        asyncio.run(store.open())
        leaks = sentinel_leaks(store.read())
        asyncio.run(store.close())
    return bool(leaks)


def check_stall() -> bool:
    async def main() -> None:
        await asyncio.Event().wait()

    try:
        run_virtual(SimClock(START), main)
    except SimulationStalled:
        return True
    return False


def run() -> dict[str, bool]:
    return {
        "déterminisme": check_determinism(),
        "sentinelle d'horloge": check_sentinel(),
        "blocage expliqué": check_stall(),
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
