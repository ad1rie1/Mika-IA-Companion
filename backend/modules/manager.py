"""Central plugin registry, scheduler, tool aggregator, and event bus."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from typing import Any, Awaitable, Callable

from asgiref.sync import sync_to_async
from django.urls import path

from modules.base import BaseModule
from modules.types import (
    AIDecision,
    ModuleCapability,
    ModuleEvent,
    ModuleNotification,
    ModuleStatus,
    ModuleTool,
    ModuleView,
)

logger = logging.getLogger(__name__)

DEFAULT_TICK_INTERVAL = 60  # seconds


def _is_owner(person_id: str) -> bool:
    """Is this person allowed to see owner-scoped (private) module context?

    Trusted: configured owners, authenticated users (``user_*``), and Mika's own
    internal channels (``conscience*``, ``module_*``). Anonymous web guests
    (``anon_*``) and external contacts are not.
    """
    if not person_id:
        return False
    from django.conf import settings

    if person_id in getattr(settings, "OWNER_PERSON_IDS", []):
        return True
    return person_id.startswith(("user_", "conscience", "module_"))


class ModuleManager:
    """Central plugin registry, scheduler, tool aggregator, and event bus.

    The core never imports specific modules — they register themselves
    via ``ModulesConfig.ready()``. The manager handles:

    - Module lifecycle (start / stop)
    - Per-module cron scheduling
    - Generic ``ModuleTool`` aggregation (no provider-specific knowledge;
      the AI provider translates the list to its native tool format)
    - Context aggregation for the system prompt
    - Auto-mounted HTTP routes
    - Inter-module event bus
    - ``notify_ai`` callback injected into every module
    """

    def __init__(self) -> None:
        # All modules ever registered, including disabled ones.
        self._registered: dict[str, BaseModule] = {}
        # Active modules: those the manager currently considers runnable.
        self._modules: dict[str, BaseModule] = {}
        self._scheduler_task: asyncio.Task | None = None
        self._tick_interval: int = DEFAULT_TICK_INTERVAL
        self._tools_cache: list[ModuleTool] | None = None
        self._conscience_callback: Callable[[ModuleEvent], Awaitable[None]] | None = None

    # ── Registration ──────────────────────────────────────────────

    def register(self, module: BaseModule) -> None:
        if module.name in self._registered:
            raise ValueError(f"Module '{module.name}' is already registered")

        self._registered[module.name] = module

        # Absorb config schema REGARDLESS of availability — the whole
        # point of surfacing it in the UI is to let the user configure
        # a module that can't run yet because its settings are empty.
        try:
            entries = module.config_schema()
        except Exception:
            logger.exception("config_schema() failed for module %s", module.name)
            entries = []
        if entries:
            from configs.registry import registry as config_registry
            config_registry.register(entries)
            logger.debug(
                "Module '%s' registered %d config schema entries",
                module.name, len(entries),
            )

        if not module.is_available():
            logger.info(
                "Module '%s' not available (preconditions unmet), skipping",
                module.name,
            )
            return

        # Note: ModuleState is NOT consulted here. Querying the DB from
        # AppConfig.ready() triggers Django's APPS_NOT_READY warning and
        # breaks on a fresh install before the migration for ModuleState
        # has been applied. The enabled/disabled filter is applied in
        # start_all() instead, where the ORM is fully live.
        module.set_notify_ai(self._notify_ai)
        self._modules[module.name] = module
        self._tools_cache = None
        logger.info("Module registered: %s", module.name)

    def get_module(self, name: str) -> BaseModule | None:
        return self._modules.get(name)

    def get_registered(self, name: str) -> BaseModule | None:
        """Return a module whether or not it is currently enabled."""
        return self._registered.get(name)

    def list_all(self) -> list[dict[str, Any]]:
        """List every registered module with its enable/running state."""
        from modules.state_model import ModuleState

        states: dict[str, ModuleState] = {
            s.name: s for s in ModuleState.objects.all()
        }
        result = []
        for name, module in self._registered.items():
            state = states.get(name)
            result.append({
                "name": name,
                "enabled": state.enabled if state else True,
                "running": module.is_running,
                "available": module.is_available(),
                "installed_tables": state.installed_tables if state else [],
                "has_models": bool(self._safe_models(module)),
                "system": bool(getattr(module, "SYSTEM", False)),
            })
        return result

    # ── ModuleState helpers ───────────────────────────────────────

    def _is_enabled_in_state(self, name: str) -> bool:
        """Return whether the module is marked enabled in ModuleState.

        Defaults to True for modules that have never been toggled, so
        existing deployments keep their current behavior.
        """
        try:
            from modules.state_model import ModuleState
            state = ModuleState.objects.filter(pk=name).first()
        except Exception:
            # DB not migrated yet during bootstrap — assume enabled.
            return True
        return True if state is None else state.enabled

    @staticmethod
    def _safe_models(module: BaseModule) -> list:
        try:
            return list(module.get_models() or [])
        except Exception:
            logger.exception("get_models() failed for module %s", module.name)
            return []

    def _upsert_state(
        self,
        name: str,
        *,
        enabled: bool | None = None,
        installed_tables: list[str] | None = None,
    ) -> None:
        from modules.state_model import ModuleState

        defaults: dict[str, Any] = {}
        if enabled is not None:
            defaults["enabled"] = enabled
        if installed_tables is not None:
            defaults["installed_tables"] = installed_tables
        ModuleState.objects.update_or_create(name=name, defaults=defaults)

    # ── Schema lifecycle (enable / disable / uninstall) ──────────

    def install_tables(self, name: str) -> list[str]:
        """Create any missing tables for the module's declared models.

        Safe to call repeatedly; existing tables are left untouched.
        Returns the list of newly created table names.
        """
        from modules.schema_ops import create_tables_for
        module = self._registered.get(name)
        if module is None:
            raise KeyError(f"Module '{name}' is not registered")

        models = self._safe_models(module)
        created = create_tables_for(models) if models else []

        # Merge newly created tables into the recorded list.
        from modules.state_model import ModuleState
        state, _ = ModuleState.objects.get_or_create(name=name)
        known = set(state.installed_tables or [])
        known.update(created)
        state.installed_tables = sorted(known)
        state.save(update_fields=["installed_tables", "updated_at"])

        return created

    def install_missing_at_boot(self) -> None:
        """For every registered + enabled module, create tables that are
        declared in code but not yet present in the database.

        This is what makes adding a new model to an enabled module a
        zero-ceremony operation: on next boot, the table appears.
        """
        for name, module in self._registered.items():
            if not self._is_enabled_in_state(name):
                continue
            if not self._safe_models(module):
                continue
            try:
                self.install_tables(name)
            except Exception:
                logger.exception("install_missing_at_boot failed for %s", name)

    async def enable(self, name: str) -> None:
        """Mark a module enabled, install its tables, and start it.

        Idempotent: if already enabled and running, does nothing.
        """
        module = self._registered.get(name)
        if module is None:
            raise KeyError(f"Module '{name}' is not registered")

        # Sync ORM + schema_editor work must be dispatched to a thread
        # because this coroutine is awaited from an HTTP handler running
        # inside the event loop.
        await sync_to_async(self._upsert_state, thread_sensitive=True)(
            name, enabled=True,
        )
        await sync_to_async(self.install_tables, thread_sensitive=True)(name)

        if not module.is_available():
            logger.info(
                "Module '%s' enabled but not available yet (config missing)",
                name,
            )
            return

        if module.name not in self._modules:
            module.set_notify_ai(self._notify_ai)
            self._modules[module.name] = module

        if not module.is_running:
            try:
                await module._do_start()
            except Exception:
                logger.exception("Failed to start module %s on enable()", name)
                module._running = False
                return

        self.invalidate_tools_cache()
        logger.info("Module '%s' enabled", name)

    async def disable(self, name: str) -> None:
        """Mark a module disabled and stop it.

        Tables are preserved; call ``uninstall()`` to drop them.
        """
        module = self._registered.get(name)
        if module is None:
            raise KeyError(f"Module '{name}' is not registered")

        await sync_to_async(self._upsert_state, thread_sensitive=True)(
            name, enabled=False,
        )

        if module.is_running:
            try:
                await module._do_stop()
            except Exception:
                logger.exception("Error stopping module %s on disable()", name)

        self._modules.pop(name, None)
        self.invalidate_tools_cache()
        logger.info("Module '%s' disabled (tables preserved)", name)

    async def uninstall(self, name: str) -> None:
        """Stop the module and drop every table it owns.

        DESTRUCTIVE. All data in the module's tables is lost.
        """
        from modules.schema_ops import drop_tables_for
        from modules.state_model import ModuleState

        module = self._registered.get(name)
        if module is None:
            raise KeyError(f"Module '{name}' is not registered")

        if module.is_running:
            try:
                await module._do_stop()
            except Exception:
                logger.exception("Error stopping module %s on uninstall()", name)

        models = self._safe_models(module)
        if models:
            await sync_to_async(drop_tables_for, thread_sensitive=True)(models)

        await sync_to_async(
            lambda: ModuleState.objects.filter(pk=name).delete(),
            thread_sensitive=True,
        )()
        self._modules.pop(name, None)
        self.invalidate_tools_cache()
        logger.warning("Module '%s' uninstalled (tables dropped)", name)

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start_all(self) -> None:
        """Start all registered modules and the cron scheduler.

        Modules that need to produce speech should emit events via the
        event bus or call ``pipeline.router.perceive()`` directly with
        an ``Intent.INTERNAL_TRIGGER`` Perception.
        """
        from configs.service import config_service

        self._tick_interval = config_service.get(
            "modules.cron_tick_interval", default=DEFAULT_TICK_INTERVAL,
        )

        # Filter out modules that the user has explicitly disabled.
        # Done here (not in register()) to avoid querying the ORM during
        # AppConfig.ready(). Dispatch the sync ORM reads to a thread
        # because we're running inside the ASGI event loop.
        def _collect_disabled() -> list[str]:
            return [
                name for name in list(self._modules)
                if not self._is_enabled_in_state(name)
            ]
        disabled = await sync_to_async(_collect_disabled, thread_sensitive=True)()
        for name in disabled:
            logger.info("Module '%s' disabled via ModuleState, skipping", name)
            self._modules.pop(name, None)

        # Create any tables declared by enabled modules but not yet
        # present in the database (e.g. a new model added since last boot,
        # or a freshly imported third-party module).
        try:
            await sync_to_async(self.install_missing_at_boot, thread_sensitive=True)()
        except Exception:
            logger.exception("install_missing_at_boot failed")

        for module in self._modules.values():
            try:
                await module._do_start()
            except Exception:
                logger.exception("Failed to start module %s", module.name)
                module._running = False

        # Start the cron scheduler
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info(
            "Plugin scheduler started (default interval=%ds)", self._tick_interval
        )

    async def stop_all(self) -> None:
        if self._scheduler_task and not self._scheduler_task.done():
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            logger.info("Cron scheduler stopped")

        for module in reversed(list(self._modules.values())):
            if module.is_running:
                try:
                    await module._do_stop()
                except Exception:
                    logger.exception("Error stopping module %s", module.name)

    # ── Scheduler (per-module intervals) ──────────────────────────

    async def _scheduler_loop(self) -> None:
        """Tick every second, dispatch worker_cron() per-module interval."""
        last_tick: dict[str, float] = {}
        while True:
            try:
                await asyncio.sleep(1)
                now = time.time()
                # Snapshot so a concurrent enable()/disable() that mutates
                # self._modules cannot break iteration.
                for module in list(self._modules.values()):
                    if not module.is_running:
                        continue
                    interval = module.CRON_INTERVAL or self._tick_interval
                    last = last_tick.get(module.name, 0.0)
                    if now - last >= interval:
                        last_tick[module.name] = now
                        try:
                            await module.worker_cron()
                        except Exception:
                            logger.exception(
                                "Error in worker_cron() for module %s",
                                module.name,
                            )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scheduler error")

    # ── Tool Aggregation ──────────────────────────────────────────

    def collect_tools(self) -> list[ModuleTool]:
        """Aggregate ``return_tools()`` from all running modules.

        Handlers are transparently wrapped with logging before being
        exposed, so every consumer (ClaudeProvider's MCP server, future
        OpenAI/Gemini function-calling back-ends, the admin UI) gets
        the same observability for free.
        """
        if self._tools_cache is not None:
            return self._tools_cache
        tools: list[ModuleTool] = []
        seen_names: set[str] = set()
        for module in self._modules.values():
            if not module.is_running:
                continue
            for tool in module.return_tools():
                if tool.name in seen_names:
                    logger.warning(
                        "Duplicate tool name '%s' from module '%s', skipping",
                        tool.name, module.name,
                    )
                    continue
                seen_names.add(tool.name)
                tools.append(dataclasses.replace(
                    tool, handler=self._wrap_handler(tool.name, tool.handler),
                ))
        self._tools_cache = tools
        return tools

    def get_tools_for_modules(self, module_names: list[str]) -> list[ModuleTool]:
        """Subset of ``collect_tools()`` scoped to a module allow-list."""
        wanted = set(module_names)
        by_name = {}
        for module_name in wanted:
            module = self._modules.get(module_name)
            if module is None or not module.is_running:
                continue
            by_name.update({t.name: module_name for t in module.return_tools()})
        return [t for t in self.collect_tools() if by_name.get(t.name) in wanted]

    @staticmethod
    def _wrap_handler(name: str, handler):
        """Wrap a tool handler with call/return/error logging."""
        async def logged_handler(params):
            logger.info("tool called: %s (params=%s)", name, params)
            try:
                result = await handler(params)
                logger.info("tool %s returned: %s", name, str(result)[:200])
                return result
            except Exception:
                logger.exception("tool %s failed", name)
                raise
        return logged_handler

    def get_tool_names(self) -> list[str]:
        """Return all registered tool names for ``allowed_tools``."""
        return [t.name for t in self.collect_tools()]

    def invalidate_tools_cache(self) -> None:
        """Force rebuild of the tool cache on next access."""
        self._tools_cache = None

    # ── Capabilities ─────────────────────────────────────────────

    def collect_capabilities(self) -> dict[str, list[ModuleCapability]]:
        """Collect capabilities from all running modules.

        Returns {module_name: [capabilities]}.
        Used by the Conscience to know what actions are available
        without loading all MCP tools.
        """
        result: dict[str, list[ModuleCapability]] = {}
        for module in self._modules.values():
            if module.is_running:
                caps = module.get_capabilities()
                if caps:
                    result[module.name] = caps
        return result

    def collect_capabilities_summary(self) -> str:
        """Format capabilities as a readable summary for prompts.

        Example output:
          [email] Lire, lister et chercher dans les emails recus
          [email] Envoyer des emails
          [wake] Programmer un reveil spontane
        """
        lines: list[str] = []
        for module_name, caps in self.collect_capabilities().items():
            for cap in caps:
                lines.append(f"[{module_name}] {cap.description}")
        return "\n".join(lines)

    # ── Context Aggregation ───────────────────────────────────────

    def collect_context(self, person_id: str = "") -> str:
        """Collect per-person context strings from all running modules.

        Modules with ``CONTEXT_VISIBILITY == "owner"`` (the default) are only
        injected for trusted/owner persons, so private info (unread emails,
        pending wakes) never leaks into an anonymous guest's prompt.
        """
        owner = _is_owner(person_id)
        parts: list[str] = []
        for module in self._modules.values():
            if not module.is_running:
                continue
            if getattr(module, "CONTEXT_VISIBILITY", "owner") == "owner" and not owner:
                continue
            ctx = module.get_context(person_id)
            if ctx:
                parts.append(f"[{module.name}] {ctx}")
        return "\n".join(parts)

    # ── Route Collection ──────────────────────────────────────────

    def collect_routes(self) -> list:
        """Collect and namespace all module HTTP routes.

        Returns Django URL patterns mounted under
        ``/api/modules/{module_name}/{route.path}``.
        """
        patterns = []
        for module in self._modules.values():
            for route in module.get_routes():
                url_path = (
                    f"{module.name}/{route.path}" if route.path else module.name
                )
                url_name = route.name or f"module_{module.name}_{route.path or 'index'}"
                patterns.append(path(url_path, route.handler, name=url_name))
        return patterns

    # ── Dashboard Views ──────────────────────────────────────────

    def collect_views(self, *, only_running: bool = True) -> dict[str, list[ModuleView]]:
        """Gather dashboard views declared by modules.

        ``only_running`` filters to modules that are currently running
        (the UI default). Pass ``False`` to introspect everything
        registered, running or not.
        Returned mapping is ``{module_name: [ModuleView, ...]}`` with
        each list sorted by ``order``.
        """
        result: dict[str, list[ModuleView]] = {}
        pool = self._modules if only_running else self._registered
        for name, module in pool.items():
            if only_running and not module.is_running:
                continue
            try:
                views = list(module.get_views() or [])
            except Exception:
                logger.exception("get_views() failed for module %s", name)
                continue
            if views:
                views.sort(key=lambda v: (v.order, v.label))
                result[name] = views
        return result

    def get_view(self, module_name: str, view_key: str) -> ModuleView | None:
        """Look up a single running module's view by key."""
        module = self._modules.get(module_name)
        if not module or not module.is_running:
            return None
        for view in module.get_views() or []:
            if view.key == view_key:
                return view
        return None

    # ── Conscience Wiring ────────────────────────────────────────

    def set_conscience(
        self, callback: Callable[[ModuleEvent], Awaitable[None]]
    ) -> None:
        """Wire the Conscience engine to receive all events."""
        self._conscience_callback = callback
        logger.info("Conscience callback registered")

    # ── Event Bus ─────────────────────────────────────────────────

    async def emit_event(self, event: ModuleEvent) -> None:
        """Broadcast an event to Conscience first, then to all modules."""
        # Forward to Conscience (if wired)
        if self._conscience_callback:
            try:
                await self._conscience_callback(event)
            except Exception:
                logger.exception("Error forwarding event to conscience")

        for module in self._modules.values():
            if module.name != event.source_module and module.is_running:
                try:
                    await module.on_event(event)
                except Exception:
                    logger.exception(
                        "Error in on_event() for module %s", module.name
                    )

        # Wake projects scheduled on "event:<type>" — without this hook the
        # rule parsed fine but could never fire (notify_event had no caller).
        try:
            from projects.runner import project_runner
            await project_runner.notify_event(event.event_type)
        except Exception:
            logger.debug("Project event notification failed", exc_info=True)

    # ── Notify AI ─────────────────────────────────────────────────

    async def _notify_ai(self, notification: ModuleNotification) -> AIDecision:
        """Wake Claude with a module notification and all available tools.

        This callback is injected into every module via ``set_notify_ai()``.
        Constructs an INTERNAL_TRIGGER Perception and routes it so the
        notification flows through the same pipeline as any other input.
        """
        from pipeline.perception import Perception
        from pipeline.router import perceive

        # Build a structured prompt from the notification
        prompt = (
            f"[NOTIFICATION du module '{notification.source_module}']\n"
            f"Resume: {notification.summary}\n"
            f"Details: {notification.details}\n"
            f"Urgence: {notification.urgency}\n"
        )
        if notification.suggested_action:
            prompt += f"Action suggeree: {notification.suggested_action}\n"

        # Person ID — use metadata override if provided (e.g. Telegram user)
        person_id = notification.metadata.get(
            "person_id", f"module_{notification.source_module}"
        )

        logger.info(
            "[notify_ai/%s] person=%s | %s",
            notification.source_module, person_id, notification.summary,
        )

        perception = Perception.from_internal_trigger(
            prompt,
            source=notification.source_module,
            person_id=person_id,
            metadata={
                "urgency": notification.urgency,
                "suggested_action": notification.suggested_action,
                **notification.metadata,
            },
        )

        output = await perceive(perception)
        if output is None:
            # Router should always return a SpeechOutput for INTERNAL_TRIGGER,
            # but be defensive for future routing changes.
            return AIDecision(response_text="", emotion=None, tool_calls_made=[])

        return AIDecision(
            response_text=output.text,
            emotion=output.emotion_data,
            tool_calls_made=output.tool_calls,
        )

    # ── Status ────────────────────────────────────────────────────

    def get_all_status(self) -> list[ModuleStatus]:
        """Return status of all registered modules."""
        return [m.get_status() for m in self._modules.values()]


module_manager = ModuleManager()
