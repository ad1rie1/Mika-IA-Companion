"""Preuve M0 — le simulateur se protège du monde réel : la sentinelle attrape
un appel à l'heure système, le fuseau piège décale les calculs locaux fautifs,
un blocage produit ``SimulationStalled`` avec les piles, une E/S réelle lève."""

from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest

from mika.kernel.clock import instant
from mika.kernel.events import Payload
from mika.kernel.faculty import Faculty
from mika.sim.checks import sentinel_leaks
from mika.sim.clock import RealIOInSimulation, SimClock, SimulationStalled, run_virtual
from mika.sim.env import sim_environment
from tests.conftest import START
from tests.fixtures.harness import build


@dataclass(frozen=True, slots=True)
class Bad:
    n: int = 0


class Stamped(Payload):
    when: int


BUGGY = Faculty("buggy", state=Bad, init=lambda p: Bad())
STAMPED = BUGGY.event("stamped", Stamped)


@BUGGY.reducer(STAMPED)
def _st(s: Bad, e, cx) -> Bad:
    return replace(s, n=s.n + 1)


@BUGGY.process("horodateur-fautif", max_quantum_s=600)
class WallClockUser:
    def next_due(self, state, frame, last_run):
        return frame.now if last_run is None else None

    async def run(self, ctx):
        # Le défaut qu'on cherche : lire l'heure système au lieu de l'horloge injectée.
        await ctx.emit(STAMPED.draft(when=instant(datetime.now(UTC))))


def test_sentinel_catches_a_wall_clock_read(tmp_path):
    kernel, clock, _ = build(tmp_path, [BUGGY])

    async def main():
        await kernel.start()
        await asyncio.sleep(5)
        leaks = sentinel_leaks(kernel.mind.store.read())
        await kernel.stop()
        return leaks

    with sim_environment():
        leaks = run_virtual(clock, main)
    assert leaks and leaks[0][1] == "data"


def test_trap_timezone_shifts_process_local_time():
    with sim_environment():
        offset_h = -time.timezone / 3600 if not time.daylight else -time.altzone / 3600
        assert offset_h == 14


def test_stall_is_explained():
    clock = SimClock(START)

    async def main():
        never = asyncio.Event()

        async def waiter():
            await never.wait()

        await asyncio.create_task(waiter(), name="attend-pour-toujours")

    with pytest.raises(SimulationStalled) as info:
        run_virtual(clock, main)
    assert "attend-pour-toujours" in str(info.value)


def test_real_network_is_refused():
    clock = SimClock(START)

    async def main():
        await asyncio.open_connection("example.com", 80)

    with sim_environment(), pytest.raises((RealIOInSimulation, OSError)) as info:
        run_virtual(clock, main)
    assert isinstance(info.value, RealIOInSimulation) or "simulation" in str(info.value)


def test_socket_connect_is_refused():
    with sim_environment():
        s = socket.socket()
        try:
            with pytest.raises(RealIOInSimulation):
                s.connect(("127.0.0.1", 9))
        finally:
            s.close()
