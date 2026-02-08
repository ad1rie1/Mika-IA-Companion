"""Base class for all VTuber engine plugin modules."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from modules.types import (
    ModuleEvent,
    ModuleRoute,
    ModuleStatus,
    ModuleTool,
)

if TYPE_CHECKING:
    from modules.types import AIDecision, ModuleNotification


class BaseModule(ABC):
    """Base class for all VTuber engine plugin modules.

    Lifecycle (managed by ModuleManager):
      1. __init__(name)       — constructor, no I/O
      2. is_available()       — check preconditions (config, deps)
      3. instantiate()        — start resources (connections, tasks)
      4. worker_cron()        — periodic work (called by scheduler)
      5. shutdown()           — release resources

    AI integration:
      - return_tools()        — expose tools to Claude
      - get_context()         — inject text into Claude system prompt
      - self._notify_ai(n)    — wake Claude with structured info

    Infrastructure:
      - get_routes()          — declare HTTP endpoints (auto-mounted)
      - on_event(event)       — react to inter-module events
      - get_status()          — monitoring / debug
    """

    # Override to set a custom cron interval in seconds.
    # None = use the global CRON_TICK_INTERVAL from settings.
    CRON_INTERVAL: int | None = None

    def __init__(self, name: str):
        self.name = name
        self._running = False
        self._started_at: float | None = None
        self.logger = logging.getLogger(f"module.{name}")
        self._notify_ai: Callable[
            [ModuleNotification], Awaitable[AIDecision]
        ] | None = None

    # ── Lifecycle ─────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Check whether this module CAN run (config present, deps ok).
        Called before instantiate(). Return False to skip gracefully."""
        return True

    @abstractmethod
    async def instantiate(self) -> None:
        """Initialise the module: open connections, start background tasks."""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Release all resources held by the module."""
        ...

    # ── Cron ──────────────────────────────────────────────────────

    async def worker_cron(self) -> None:
        """Called periodically by the scheduler.
        Override for periodic work. Default: no-op."""
        pass

    # ── AI Tools ──────────────────────────────────────────────────

    def return_tools(self) -> list[ModuleTool]:
        """Return tools this module exposes to Claude. Default: none."""
        return []

    # ── HTTP Routes ───────────────────────────────────────────────

    def get_routes(self) -> list[ModuleRoute]:
        """Return HTTP routes this module serves.
        Auto-mounted under /api/modules/{name}/. Default: none."""
        return []

    # ── Context Injection ─────────────────────────────────────────

    def get_context(self) -> str:
        """Return text to inject into Claude's system prompt.
        E.g. 'Tu as 3 emails non lus.' Default: empty."""
        return ""

    # ── Inter-module Events ───────────────────────────────────────

    async def on_event(self, event: ModuleEvent) -> None:
        """React to an event emitted by another module. Default: ignore."""
        pass

    # ── Monitoring ────────────────────────────────────────────────

    def get_status(self) -> ModuleStatus:
        """Return current module status for monitoring/debug."""
        uptime = (time.time() - self._started_at) if self._started_at else 0.0
        return ModuleStatus(
            name=self.name,
            running=self._running,
            available=self.is_available(),
            uptime_seconds=uptime,
        )

    # ── Internal (called by ModuleManager — do NOT override) ─────

    def set_notify_ai(
        self,
        fn: Callable[[ModuleNotification], Awaitable[AIDecision]],
    ) -> None:
        """Injected by ModuleManager. Modules call ``self._notify_ai(...)``."""
        self._notify_ai = fn

    async def _do_start(self) -> None:
        """Called by ModuleManager to start the module."""
        self.logger.info("Starting module: %s", self.name)
        self._running = True
        self._started_at = time.time()
        await self.instantiate()

    async def _do_stop(self) -> None:
        """Called by ModuleManager to stop the module."""
        self.logger.info("Stopping module: %s", self.name)
        self._running = False
        await self.shutdown()

    @property
    def is_running(self) -> bool:
        return self._running
