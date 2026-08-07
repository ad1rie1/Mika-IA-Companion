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
)

if TYPE_CHECKING:
    from modules.types import AIDecision, ModuleNotification


class BaseModule(ABC):
    """Base class for all VTuber engine plugin modules.

    **A module is required to have a name. Everything else is opt-in.**

    That used to be less true than it should be. ``instantiate`` and
    ``shutdown`` were ``@abstractmethod``, which is exactly backwards for the
    shape of module this codebase keeps growing: measured across the nine
    concrete modules, three of them (``memory_tools``, ``identity_tools``,
    ``project_tools``) implement *only* ``instantiate``, ``shutdown`` and
    ``return_tools`` — and the first two are empty, written solely to satisfy
    the ABC. They are tool facades over a subsystem the ASGI lifespan already
    owns; they have no resources to open. The abstract pair forced ceremony
    on precisely the modules with nothing to declare.

    Both are now no-ops by default. Override them when there is something to
    open and close.

    Hook usage across the nine concrete modules, for calibration:

        instantiate / shutdown / return_tools   9/9
        get_context                             6/9
        worker_cron / get_capabilities          5/9
        get_models                              5/9
        get_status                              4/9
        is_available / config_schema            3/9
        get_routes                              2/9
        on_event                                1/9

    Grouped by what you are opting into:

    Lifecycle (managed by ModuleManager)
      - is_available()       — preconditions unmet? return False, be skipped
      - instantiate()        — open connections, start tasks
      - shutdown()           — release them
      - worker_cron()        — periodic work, per ``CRON_INTERVAL``

    AI integration
      - return_tools()       — expose MCP tools
      - get_capabilities()   — describe what you can do, in prose
      - get_context()        — inject text into the system prompt
      - self._notify_ai(n)   — ask for Mika's attention (see modules/notify)

    Infrastructure
      - get_routes()         — HTTP endpoints, auto-mounted
      - get_panels()         — pages in the module's admin space
      - config_schema()      — settings, surfaced in the dashboard
      - get_models()         — Django models you own (see the caveat there)
      - on_event(event)      — react to the bus; see EVENT_* below
      - get_status()         — monitoring

    Outbound delivery is deliberately *not* here — see
    ``communication.delivery.Deliverable``.
    """

    # Override to set a custom cron interval in seconds.
    # None = use the global ``modules.cron_tick_interval`` config key.
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

    async def instantiate(self) -> None:
        """Open connections, start background tasks. Default: nothing to do.

        Not abstract: a tool facade over an already-running subsystem has no
        resources of its own, and forcing it to write ``return None`` here
        taught nobody anything.
        """
        return None

    async def shutdown(self) -> None:
        """Release everything ``instantiate`` opened. Default: nothing to do."""
        return None

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

    # ── Module space (GestionSystème) ─────────────────────────────

    def get_panels(self) -> list:
        """Return ``GestionSysteme.panels.ModulePanel`` pages for this module.

        Mounted inside the module's own space at
        ``/gestion/modules/{name}/p/{panel.key}/``, alongside its state and
        its configuration — rather than scattered through the global menu.

        A handler returns **typed blocks** (``Table`` / ``Fields`` / ``Stats``
        / ``Note`` / ``Prose`` / ``Template``) built from **typed cells**. A
        module declares an intent ("this is a warning badge", "this is a
        gauge"); it never emits markup. The rendering belongs to
        GestionSystème's templates, with Django's autoescaping on.

        This replaced ``get_views()``, which returned JSON that a browser
        script injected via ``innerHTML`` — so a module piping an email body
        or a scraped page through an ``html`` key was stored XSS on the admin
        interface, which also edits the provider API keys. Panels remove the
        class of bug rather than filtering it, and the old contract was
        deleted with the ``dashboard`` app rather than kept as a compatibility
        path with no consumer.

        Handlers may be sync or async. Default: no panels.
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
    #
    # `deliver()` used to live here, returning False. Measured: no module
    # implements it, and none ever did — the only implementer in the codebase
    # is `TelegramChannel`, which is a communication channel, not a module.
    # So this was a capability declared on the wrong class, whose default
    # answer was the only answer anyone ever got.
    #
    # It is now the `Deliverable` protocol in `communication.delivery`, which
    # the caller duck-types against. A module that genuinely can initiate
    # contact just grows the method; nothing needs to inherit anything.

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
