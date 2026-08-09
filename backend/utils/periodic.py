"""PeriodicLoop — the background-loop pattern the engine repeats.

Three subsystems run their own dedicated loop (memory consolidation, the
sleep cycle, the project runner) and had written the same twenty lines three
times: an idempotent ``start``, a ``stop`` that cancels and swallows
``CancelledError``, and a ``while self._running`` body wrapping one call in
``try/except`` so a single bad tick doesn't kill the loop forever.

Identical code in three places is a slow leak: the day one of them learns
something — say, that ``CancelledError`` must be re-raised rather than
logged — the other two don't. Notably, the reason all three swallow
exceptions is not defensiveness, it is that these loops have no supervisor:
nothing restarts them, so a loop that dies stays dead until the process does.

Deliberately minimal: no jitter, no backoff, no supervision tree. It exists
to stop the pattern being retyped, not to become a scheduler — the module
plugin scheduler in ``modules/manager.py`` is a different thing with
different needs (per-module intervals, detached ticks) and does not use this.
"""

from __future__ import annotations

import asyncio
import logging
import time
import weakref
from typing import Awaitable, Callable

from utils.degradation import degradations

logger = logging.getLogger(__name__)

# Every live loop, so the health page can answer "when did each of these
# last actually work?" without any subsystem having to register itself.
# Weak so the throwaway loops tests build don't accumulate; the real ones
# are held by their singletons.
_LOOPS: weakref.WeakSet[PeriodicLoop] = weakref.WeakSet()


def active_loops() -> list[PeriodicLoop]:
    """All loops still alive in this process, by name."""
    return sorted(_LOOPS, key=lambda loop: loop.name)


class PeriodicLoop:
    """Runs an async callable every ``interval`` seconds until stopped.

    The first run happens *after* one interval, not immediately: every
    caller wants "start ticking from now on", and firing during startup put
    load on the process exactly when it was busiest.
    """

    def __init__(
        self,
        name: str,
        tick: Callable[[], Awaitable[None]],
        interval: float,
    ) -> None:
        self.name = name
        self._tick = tick
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._running = False
        # "Running" says a task exists, which is exactly what a loop stuck on
        # a persistent `database is locked` also says. The age of the last
        # *successful* tick is the fact that distinguishes them.
        self.last_success_at: float | None = None
        # Deliberately not cleared on success: the age above says whether the
        # loop is up to date, this says how it breaks when it breaks.
        self.last_error: str = ""
        _LOOPS.add(self)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def interval(self) -> float:
        return self._interval

    async def start(self, interval: float | None = None) -> None:
        """Start ticking. Idempotent — a second call is a no-op."""
        if self._running:
            return
        if interval is not None:
            self._interval = interval
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"loop:{self.name}")
        logger.info("%s loop started (interval=%ss)", self.name, self._interval)

    async def stop(self) -> None:
        """Cancel the loop and wait for it to unwind. Idempotent."""
        self._running = False
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info("%s loop stopped", self.name)

    async def _run(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                # Re-checked after the sleep: stop() may have been called
                # while we were waiting, and running one more tick during
                # shutdown writes to a database that is being torn down.
                if self._running:
                    await self._tick()
                    self.last_success_at = time.time()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                # Nothing supervises this loop, so a propagating exception
                # would silently end it for the lifetime of the process.
                self.last_error = f"{type(exc).__name__}: {exc}"
                degradations.record(f"boucle {self.name}", exc)
                logger.exception("%s loop error", self.name)
