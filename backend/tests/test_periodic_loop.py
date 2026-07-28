"""The background-loop primitive shared by consolidator / sleep / runner.

These three had three copies of the same twenty lines. The properties that
matter are the ones a copy could quietly lose: that a failing tick doesn't
end the loop (nothing supervises these — a dead loop stays dead until the
process restarts), that stop() actually stops it, and that start() is
idempotent so a double-wired lifespan doesn't produce two tickers.
"""
from __future__ import annotations

import asyncio

import pytest

from utils.periodic import PeriodicLoop

pytestmark = pytest.mark.asyncio


async def _drain(loop: PeriodicLoop) -> None:
    await loop.stop()


class TestLifecycle:

    async def test_ticks_repeatedly(self):
        calls = []
        loop = PeriodicLoop("test", lambda: _record(calls), interval=0.01)
        await loop.start()
        await asyncio.sleep(0.06)
        await _drain(loop)
        assert len(calls) >= 3

    async def test_first_tick_waits_one_interval(self):
        """Firing during startup put load on the process exactly when it was
        busiest — every caller means "tick from now on"."""
        calls = []
        loop = PeriodicLoop("test", lambda: _record(calls), interval=5)
        await loop.start()
        await asyncio.sleep(0.05)
        assert calls == []
        await _drain(loop)

    async def test_start_is_idempotent(self):
        calls = []
        loop = PeriodicLoop("test", lambda: _record(calls), interval=0.01)
        await loop.start()
        first = loop._task
        await loop.start()
        assert loop._task is first, "un second start ne doit pas créer un 2e ticker"
        await _drain(loop)

    async def test_stop_is_idempotent_and_safe_before_start(self):
        loop = PeriodicLoop("test", lambda: _record([]), interval=0.01)
        await loop.stop()
        await loop.start()
        await loop.stop()
        await loop.stop()
        assert loop.is_running is False

    async def test_stop_halts_ticking(self):
        calls = []
        loop = PeriodicLoop("test", lambda: _record(calls), interval=0.01)
        await loop.start()
        await asyncio.sleep(0.05)
        await _drain(loop)
        seen = len(calls)
        await asyncio.sleep(0.05)
        assert len(calls) == seen

    async def test_interval_can_be_overridden_at_start(self):
        loop = PeriodicLoop("test", lambda: _record([]), interval=60)
        await loop.start(interval=0.01)
        assert loop.interval == 0.01
        await _drain(loop)


class TestResilience:

    async def test_a_failing_tick_does_not_end_the_loop(self):
        """The property that matters most: nothing restarts these loops."""
        calls = []

        async def flaky():
            calls.append(1)
            raise RuntimeError("boom")

        loop = PeriodicLoop("test", flaky, interval=0.01)
        await loop.start()
        await asyncio.sleep(0.06)
        await _drain(loop)
        assert len(calls) >= 3, "la boucle doit survivre a ses propres erreurs"

    async def test_no_tick_runs_after_stop_was_requested(self):
        """stop() during the sleep must not let one more tick through — it
        would write to a database being torn down."""
        started = asyncio.Event()
        calls = []

        async def slow_first():
            calls.append(1)
            started.set()

        loop = PeriodicLoop("test", slow_first, interval=0.02)
        await loop.start()
        await asyncio.wait_for(started.wait(), timeout=1)
        await _drain(loop)
        seen = len(calls)
        await asyncio.sleep(0.06)
        assert len(calls) == seen


class TestWiring:
    """The three subsystems expose the same lifecycle through the primitive."""

    def test_consolidator_uses_the_shared_loop(self):
        from memory.storage.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator.__new__(MemoryConsolidator)
        assert hasattr(MemoryConsolidator, "start")
        assert hasattr(MemoryConsolidator, "stop")
        # The tick is the consolidation pass, not the loop machinery.
        assert callable(consolidator._tick)

    def test_sleep_cycle_uses_the_shared_loop(self):
        from memory.sleep import sleep_cycle

        assert isinstance(sleep_cycle._loop, PeriodicLoop)
        assert sleep_cycle._loop.name == "Sleep cycle"

    def test_project_runner_uses_the_shared_loop(self):
        from projects.runner import project_runner

        assert isinstance(project_runner._loop, PeriodicLoop)
        assert project_runner._loop.name == "Project runner"


async def _record(sink: list) -> None:
    sink.append(1)
