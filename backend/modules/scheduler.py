"""CronScheduler — per-module periodic work, detached from each other.

Kept separate from ``utils.periodic.PeriodicLoop`` on purpose: that one runs
*one* callable on *one* interval and is deliberately minimal. This one has
different requirements — a per-module interval, a tick that must not block
its neighbours, and overlap suppression — and merging them would give the
three quiet background loops machinery they do not need.

Two properties are load-bearing and easy to lose in a rewrite:

*Detached ticks.* Awaiting each module inline made the shared scheduler only
as fast as its slowest member: an IMAP fetch, or an RSS poll that then ran
each new entry through an LLM, held up Forge, wake and camera for as long as
it took — and a hung socket held them up forever.

*Skip, don't queue.* If a module's previous tick is still running its turn is
skipped, so a module slower than its own interval degrades to "as often as it
can" instead of accumulating an unbounded backlog it will never work off.
"""

from __future__ import annotations

import asyncio
import logging
import time

from modules.base import BaseModule
from modules.registry import ModuleRegistry

logger = logging.getLogger(__name__)

DEFAULT_TICK_INTERVAL = 60  # seconds


class CronScheduler:
    """Ticks once a second, dispatching ``worker_cron()`` per module interval."""

    def __init__(self, registry: ModuleRegistry) -> None:
        self._registry = registry
        self._task: asyncio.Task | None = None
        # In-flight detached ticks, one per module. Held so they are not
        # garbage-collected mid-run, and consulted to suppress overlap.
        self._ticks: dict[str, asyncio.Task] = {}
        self._interval: int = DEFAULT_TICK_INTERVAL

    @property
    def interval(self) -> int:
        return self._interval

    def start(self, *, default_interval: int = DEFAULT_TICK_INTERVAL) -> None:
        """Idempotent: a second call while running is a no-op."""
        self._interval = default_interval
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="module-scheduler")
        logger.info(
            "Plugin scheduler started (default interval=%ds)", self._interval,
        )

    async def stop(self) -> None:
        """Cancel the loop, then reap ticks it detached.

        Detached ticks outlive the loop that spawned them, so shutdown has to
        reap them explicitly — otherwise a module is stopped while its own
        cron is still mid-write.
        """
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Cron scheduler stopped")
        self._task = None

        inflight = [t for t in self._ticks.values() if not t.done()]
        for task in inflight:
            task.cancel()
        if inflight:
            await asyncio.gather(*inflight, return_exceptions=True)
        self._ticks.clear()

    async def _loop(self) -> None:
        last_tick: dict[str, float] = {}
        while True:
            try:
                await asyncio.sleep(1)
                now = time.time()
                # Snapshot: a concurrent enable()/disable() mutating the
                # registry must not break iteration mid-tick.
                for module in self._registry.running():
                    interval = module.CRON_INTERVAL or self._interval
                    if now - last_tick.get(module.name, 0.0) < interval:
                        continue

                    running = self._ticks.get(module.name)
                    if running is not None and not running.done():
                        logger.debug(
                            "Skipping cron for %s: previous tick still running",
                            module.name,
                        )
                        continue

                    last_tick[module.name] = now
                    self._spawn(module)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scheduler error")

    def _spawn(self, module: BaseModule) -> None:
        """Run one module's ``worker_cron`` off the scheduler's await chain.

        A strong reference is kept until completion: a bare ``create_task``
        can be garbage-collected mid-flight, and an exception in a dropped
        task vanishes without a trace.
        """
        task = asyncio.create_task(
            self._run_once(module), name=f"cron:{module.name}",
        )
        self._ticks[module.name] = task
        task.add_done_callback(
            lambda t, name=module.name: self._ticks.pop(name, None)
            if self._ticks.get(name) is t else None
        )

    @staticmethod
    async def _run_once(module: BaseModule) -> None:
        try:
            await module.worker_cron()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error in worker_cron() for module %s", module.name)
