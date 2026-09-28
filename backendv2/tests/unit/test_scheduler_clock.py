"""Preuve M0 — horloge : un saut de +8 h donne au plus une exécution de
rattrapage (avec ``missed``), sans rafale ; la nuit du passage à l'heure
d'hiver, la tâche nocturne tourne une fois et date correctement sa nuit."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
from zoneinfo import ZoneInfo

from mika.kernel.builtin import KernelParams
from mika.kernel.clock import HOUR, MINUTE, instant, local, local_date_of_night, next_local
from mika.kernel.events import Payload
from mika.kernel.faculty import Faculty
from mika.sim.clock import run_virtual
from tests.fixtures.harness import build, events_of

PARIS = ZoneInfo("Europe/Paris")


@dataclass(frozen=True, slots=True)
class TickState:
    ticks: int = 0


class Ticked(Payload):
    missed: bool


TICKER = Faculty("ticker", state=TickState, init=lambda p: TickState())
TICKED = TICKER.event("ticked", Ticked)


@TICKER.reducer(TICKED)
def _ticked(s: TickState, e, cx) -> TickState:
    return replace(s, ticks=s.ticks + 1)


@TICKER.process("tic", max_quantum_s=300)
class Tic:
    def next_due(self, state, frame, last_run):
        return frame.now if last_run is None else last_run + 10 * MINUTE

    async def run(self, ctx):
        await ctx.emit(TICKED.draft(missed=ctx.missed is not None))


@dataclass(frozen=True, slots=True)
class DiaryState:
    last_at: int = 0


class Written(Payload):
    covers: str
    local_time: str


DIARY = Faculty("diary", state=DiaryState, init=lambda p: DiaryState())
WRITTEN = DIARY.event("written", Written)


@DIARY.reducer(WRITTEN)
def _written(s: DiaryState, e, cx) -> DiaryState:
    return replace(s, last_at=e.at)


@DIARY.process("journal-de-nuit", max_quantum_s=3600)
class NightJournal:
    def next_due(self, state, frame, last_run):
        tz = frame.env.tz_of(frame.root)
        after = state.last_at or (frame.now - 1)
        return next_local(after, 3, 30, tz)

    async def run(self, ctx):
        tz = ctx.frame.env.tz_of(ctx.frame.root)
        now = ctx.now
        await ctx.emit(WRITTEN.draft(covers=str(local_date_of_night(now, tz)),
                                     local_time=local(now, tz).strftime("%H:%M")))


def test_clock_jump_gives_one_catch_up_run(tmp_path):
    kernel, clock, _ = build(tmp_path, [TICKER])

    async def main():
        await kernel.start()
        await asyncio.sleep(30 * 60 + 1)
        before = kernel.mind.root.slices["ticker"].ticks
        clock.advance_to(clock.now() + 8 * HOUR)  # la machine a dormi huit heures
        kernel.scheduler.poke()
        await asyncio.sleep(60)
        after = kernel.mind.root.slices["ticker"].ticks
        await asyncio.sleep(11 * 60)
        later = kernel.mind.root.slices["ticker"].ticks
        ticks = [e.data.missed for e in events_of(kernel, "ticker.ticked")]
        await kernel.stop()
        return before, after, later, ticks

    before, after, later, ticks = run_virtual(kernel.deps.clock, main)
    assert before == 4
    assert after == before + 1, "une seule exécution de rattrapage"
    assert ticks[before] is True, "l'exécution de rattrapage le sait (missed)"
    assert later == after + 1 and ticks[-1] is False


def test_dst_fall_back_night(tmp_path):
    start = instant(datetime(2026, 10, 24, 12, 0, tzinfo=PARIS))
    kernel, clock, _ = build(tmp_path, [DIARY], start=start)

    async def main():
        await kernel.start()
        await kernel.set_params("kernel", KernelParams(tz="Europe/Paris"))
        kernel.scheduler.poke()
        await asyncio.sleep(3 * 24 * 3600)
        written = [(e.data.covers, e.data.local_time) for e in events_of(kernel, "diary.written")]
        await kernel.stop()
        return written

    written = run_virtual(kernel.deps.clock, main)
    assert written == [("2026-10-24", "03:30"), ("2026-10-25", "03:30"), ("2026-10-26", "03:30")]
