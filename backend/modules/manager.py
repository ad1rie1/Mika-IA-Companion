"""ModuleManager — the façade over the module subsystem.

It used to *be* the subsystem: registry, DDL, lifecycle, cron scheduler,
event bus, tool/capability/context/route/view aggregation, the notify_ai
bridge and status reporting, in one 739-line object with one shared cache
field. Each concern was defensible; together they meant every one of them
had to be re-read to change any other, and the event bus in particular was
not a bus at all — two of its three consumers were named inline.

The parts now live where they belong:

    modules/registry.py    who exists, who is active, what the DB says
    modules/lifecycle.py   start/stop/enable/disable/uninstall + bus attach
    modules/scheduler.py   per-module cron, detached, overlap-suppressed
    modules/collectors.py  tools, capabilities, context, routes, views
    modules/notify.py      the notify_ai bridge into the pipeline
    utils/eventbus.py      the actual bus — generic, with real subscribers

This class stays because ~23 call sites across the codebase say
``module_manager.<something>``, and because "the module subsystem" is a
genuine thing to hold a reference to. It owns no logic: every method here
is one line of delegation. When one of them grows a second line, that is
the signal it belongs in a collaborator instead.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from modules.base import BaseModule
from modules.collectors import ModuleCollectors, is_owner  # noqa: F401 (re-export)
from modules.lifecycle import ModuleLifecycle
from modules.notify import notify_ai
from modules.registry import ModuleRegistry
from modules.scheduler import DEFAULT_TICK_INTERVAL, CronScheduler
from modules.types import (
    ModuleCapability,
    ModuleEvent,
    ModuleStatus,
    ModuleTool,
    ModuleView,
)
from utils.eventbus import (
    PRIORITY_OBSERVER,
    DeliveryMode,
    event_bus,
)

logger = logging.getLogger(__name__)

# Kept as a module-level alias: ``modules.manager._is_owner`` was importable
# and a couple of call sites relied on it.
_is_owner = is_owner


class ModuleManager:
    """Registry, lifecycle, scheduling and aggregation for plugin modules.

    The core never imports specific modules — they register themselves from
    their app's ``ready()``.
    """

    def __init__(self) -> None:
        self.registry = ModuleRegistry()
        self.collectors = ModuleCollectors(self.registry)
        self.lifecycle = ModuleLifecycle(
            self.registry, event_bus, on_change=self.collectors.invalidate,
        )
        self.scheduler = CronScheduler(self.registry)
        self.bus = event_bus

    # ── Registration ──────────────────────────────────────────────

    def register(self, module: BaseModule) -> None:
        if self.registry.register(module):
            module.set_notify_ai(notify_ai)
            self.collectors.invalidate()

    def get_module(self, name: str) -> BaseModule | None:
        return self.registry.get(name)

    def get_registered(self, name: str) -> BaseModule | None:
        return self.registry.get_registered(name)

    def list_all(self) -> list[dict[str, Any]]:
        return self.registry.list_all()

    # ── Schema lifecycle ──────────────────────────────────────────

    def install_tables(self, name: str) -> list[str]:
        return self.lifecycle.install_tables(name)

    def install_missing_at_boot(self) -> None:
        self.lifecycle.install_missing_at_boot()

    async def enable(self, name: str) -> None:
        await self.lifecycle.enable(name, notify_ai=notify_ai)

    async def disable(self, name: str) -> None:
        await self.lifecycle.disable(name)

    async def uninstall(self, name: str) -> None:
        await self.lifecycle.uninstall(name)

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start_all(self) -> None:
        from configs.service import config_service

        await self.lifecycle.start_all()
        self.scheduler.start(default_interval=config_service.get(
            "modules.cron_tick_interval", default=DEFAULT_TICK_INTERVAL,
        ))

    async def stop_all(self) -> None:
        await self.scheduler.stop()
        await self.lifecycle.stop_all()
        await self.bus.cancel_inflight()

    # ── Aggregation ───────────────────────────────────────────────

    def collect_tools(self) -> list[ModuleTool]:
        return self.collectors.tools()

    def get_tools_for_modules(self, module_names: list[str]) -> list[ModuleTool]:
        return self.collectors.tools_for(module_names)

    def get_tool_names(self) -> list[str]:
        return self.collectors.tool_names()

    def invalidate_tools_cache(self) -> None:
        self.collectors.invalidate()

    def collect_capabilities(self) -> dict[str, list[ModuleCapability]]:
        return self.collectors.capabilities()

    def collect_capabilities_summary(self) -> str:
        return self.collectors.capabilities_summary()

    def collect_context(self, person_id: str = "") -> str:
        return self.collectors.context(person_id)

    def collect_routes(self) -> list:
        return self.collectors.routes()

    def collect_views(self, *, only_running: bool = True) -> dict[str, list[ModuleView]]:
        return self.collectors.views(only_running=only_running)

    def get_view(self, module_name: str, view_key: str) -> ModuleView | None:
        return self.collectors.view(module_name, view_key)

    # ── Event bus ─────────────────────────────────────────────────

    async def emit_event(self, event: ModuleEvent) -> None:
        """Announce that something happened. Delivery is the bus's problem."""
        await self.bus.emit(event)

    def set_conscience(
        self, callback: Callable[[ModuleEvent], Awaitable[None]]
    ) -> None:
        """Compatibility shim for the old hard-wired conscience hook.

        The conscience now subscribes itself (see ``ConscienceEngine
        .initialize``), which is why this no longer needs to exist — but the
        ASGI startup and a few tests still call it, and re-subscribing under
        the same name is idempotent, so it stays as a one-liner rather than
        a breaking change.

        ``PRIORITY_OBSERVER`` preserves the old ordering: the conscience saw
        every event before any module reacted to it, and downstream code
        reads the ``Observation`` it files.
        """
        self.bus.subscribe(
            callback,
            name="conscience",
            mode=DeliveryMode.AWAIT,
            priority=PRIORITY_OBSERVER,
        )
        logger.info("Conscience subscribed to the event bus")

    # ── Notify AI ─────────────────────────────────────────────────

    async def _notify_ai(self, notification) -> Any:
        """Retained for modules/tests holding a reference to the bound method."""
        return await notify_ai(notification)

    # ── Status ────────────────────────────────────────────────────

    def get_all_status(self) -> list[ModuleStatus]:
        return [m.get_status() for m in self.registry.active()]

    def bus_stats(self) -> dict[str, Any]:
        """Per-subscriber delivery counters — see ``EventBus.stats``."""
        return self.bus.stats()


module_manager = ModuleManager()
