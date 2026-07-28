"""Base class for all VTuber engine plugin modules."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from modules.types import (
    ModuleCapability,
    ModuleEvent,
    ModuleRoute,
    ModuleStatus,
    ModuleTool,
    ModuleView,
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

    # Infrastructure modules (files, project_tools) piggyback on the
    # module bus only to expose MCP tools to Claude. They are not
    # user-configurable plugins and are hidden from the dashboard's
    # "Gestion des modules" page. Real plugins under modules/plugins/
    # leave this as False.
    SYSTEM: bool = False

    # Who may see this module's get_context() in their conversation prompt:
    #   "owner"  — only Mika's operator / authenticated users (DEFAULT; private
    #              info like unread emails must not leak to anonymous guests)
    #   "public" — anyone Mika talks to
    CONTEXT_VISIBILITY: str = "owner"

    # ── Event bus subscription (see utils/eventbus.py) ────────────
    # How this module is wired to the bus when it starts. The defaults
    # reproduce the pre-bus behaviour: woken for every event, awaited by the
    # emitter, no deadline.
    #
    # Worth overriding, especially for modules Mika writes herself:
    #   EVENT_PATTERN = "email.*"   don't wake for signals you ignore anyway
    #   EVENT_MODE    = "spawn"     don't make the emitter wait on you
    #   EVENT_TIMEOUT = 10.0        a handler that hangs is not the emitter's
    #                               problem to inherit (AWAIT mode only)
    EVENT_PATTERN: str = "*"
    EVENT_MODE: str = "await"
    EVENT_PRIORITY: int = 50
    EVENT_TIMEOUT: float | None = None

    def __init__(self, name: str):
        self.name = name
        self._running = False
        self._started_at: float | None = None
        self._last_error: str | None = None
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

    # ── AI Capabilities & Tools ────────────────────────────────────

    def get_capabilities(self) -> list[ModuleCapability]:
        """Declare what this module can DO, in natural language.

        The Conscience reads these to know what actions are available
        without loading all MCP tools. When acting, only tools from
        relevant modules are loaded into Claude's prompt.

        Each capability links to its MCP tool names for selective loading.
        """
        return []

    def return_tools(self) -> list[ModuleTool]:
        """Return tools this module exposes to Claude. Default: none."""
        return []

    # ── HTTP Routes ───────────────────────────────────────────────

    def get_routes(self) -> list[ModuleRoute]:
        """Return HTTP routes this module serves.
        Auto-mounted under /api/modules/{name}/. Default: none."""
        return []

    # ── Dashboard Views ───────────────────────────────────────────

    def get_views(self) -> list[ModuleView]:
        """Return visualization pages this module contributes to the dashboard.

        Each ``ModuleView`` is auto-mounted under
        ``/dashboard/modules/{module}/{view.key}/`` (HTML shell) and
        ``/dashboard/api/modules/{module}/views/{view.key}`` (JSON).
        Side-effect ``actions`` get ``.../actions/{action.key}``.

        A view is only visible in the sidebar when the module is
        both *enabled* and *running*. Default: no views.
        """
        return []

    # ── Context Injection ─────────────────────────────────────────

    def get_context(self, person_id: str = "") -> str:
        """Return text to inject into Claude's system prompt for THIS person.

        E.g. 'Tu as 3 emails non lus.' Default: empty. ``person_id`` lets a
        module scope its context to the current interlocutor; combined with
        ``CONTEXT_VISIBILITY`` it prevents private info leaking to guests."""
        return ""

    # ── Outbound delivery ─────────────────────────────────────────

    async def deliver(self, output, interlocutor) -> bool:
        """Push an outbound message to a person via this module's external API.

        Implemented by modules that can *initiate* contact (Telegram, Discord:
        ``send_message(chat_id, ...)``). This is what lets Mika be proactive
        toward an external transport instead of only replying to it.

        ``output`` is the pipeline ``SpeechOutput``; ``interlocutor`` is the
        ``Interlocutor`` from the presence registry (holds ``delivery_ref``).
        Return ``True`` if delivered. Default: not deliverable.
        """
        return False

    # ── Inter-module Events ───────────────────────────────────────

    async def on_event(self, event: ModuleEvent) -> None:
        """React to an event emitted by another module. Default: ignore."""
        pass

    # ── Data models (owned by the module) ────────────────────────

    def get_models(self) -> list:
        """Return the Django model classes this module owns.

        Used by ModuleManager to auto-create tables via schema_editor
        when the module is enabled, and to drop them on uninstall.

        New modules should declare their models with
        ``class Meta: managed = False`` so Django's migration system
        ignores them — the table lifecycle is handled per-module.

        Existing modules whose tables were created through standard
        Django migrations may still list their models here: the
        installer detects already-present tables and does not
        re-create them.

        Default: no models.
        """
        return []

    # ── Configuration schema ──────────────────────────────────────

    def config_schema(self) -> list:
        """Return this module's config schema (sections + items).

        Collected by ModuleManager at registration time — *before* the
        ``is_available()`` check — so the UI can surface the settings a
        user needs to fill in to bring the module online.

        Default: no schema. Override to ship ``ConfigSection`` / ``ConfigItem``
        instances declared alongside the module.
        """
        return []

    # ── Monitoring ────────────────────────────────────────────────

    def get_status(self) -> ModuleStatus:
        """Return current module status for monitoring/debug."""
        uptime = (time.time() - self._started_at) if self._started_at else 0.0
        return ModuleStatus(
            name=self.name,
            running=self._running,
            available=self.is_available(),
            uptime_seconds=uptime,
            error=self._last_error,
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
        self._last_error = None
        try:
            await self.instantiate()
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            raise

    async def _do_stop(self) -> None:
        """Called by ModuleManager to stop the module."""
        self.logger.info("Stopping module: %s", self.name)
        self._running = False
        await self.shutdown()

    @property
    def is_running(self) -> bool:
        return self._running
