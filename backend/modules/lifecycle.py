"""ModuleLifecycle — start, stop, enable, disable, uninstall.

Also the single place where a module's ``on_event`` is attached to and
detached from the event bus. That pairing is the point: previously the bus
looped over ``self._modules`` and filtered on ``is_running`` at delivery
time, so "is this module subscribed?" had no answer other than re-deriving
it from lifecycle state on every event. Subscribing at start and
unsubscribing at stop makes the subscriber list *the* truth, which is what
lets ``event_bus.stats()`` be worth reading.

The table lifecycle (``install_tables`` / ``uninstall``) lives here too. It
is a second schema-management system running alongside Django migrations —
modules declare ``managed = False`` models and get their tables created by
``schema_editor`` on enable. That is a real trade, made deliberately: a
module Mika writes at runtime cannot ship a migration, and requiring one
would mean she cannot create a module that stores anything.
"""

from __future__ import annotations

import logging
from typing import Callable

from asgiref.sync import sync_to_async

from modules.base import BaseModule
from modules.registry import ModuleRegistry
from utils.eventbus import DeliveryMode, EventBus, PRIORITY_DEFAULT

logger = logging.getLogger(__name__)


class ModuleLifecycle:
    """Owns the transitions a module goes through, and its bus attachment."""

    def __init__(
        self,
        registry: ModuleRegistry,
        bus: EventBus,
        *,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._registry = registry
        self._bus = bus
        # Fired after any transition that can change the set of running
        # modules. The aggregators memoise over that set, and a stale tool
        # list outlives the module it came from — a disabled module's tools
        # stayed callable until the next restart.
        self._on_change = on_change or (lambda: None)

    # ── Bus attachment ────────────────────────────────────────────

    def _subscribe(self, module: BaseModule) -> None:
        """Attach ``module.on_event`` under the module's own name.

        Naming the subscription after the module is what makes "a module
        does not receive its own events" fall out of the bus's generic
        ``receive_own`` rule instead of being a special case in the emitter.

        ``EVENT_PATTERN`` / ``EVENT_MODE`` / ``EVENT_TIMEOUT`` let a module
        narrow what it is woken for and how. The defaults reproduce the old
        behaviour exactly: every event, awaited, unbounded.
        """
        self._bus.subscribe(
            module.on_event,
            name=module.name,
            pattern=getattr(module, "EVENT_PATTERN", "*"),
            mode=DeliveryMode(getattr(module, "EVENT_MODE", DeliveryMode.AWAIT)),
            priority=getattr(module, "EVENT_PRIORITY", PRIORITY_DEFAULT),
            timeout=getattr(module, "EVENT_TIMEOUT", None),
        )

    def _unsubscribe(self, module: BaseModule) -> None:
        self._bus.unsubscribe(module.name)

    async def _start_module(self, module: BaseModule) -> bool:
        """Start one module and attach it to the bus. Never raises.

        The bus attachment happens only on a successful start: a module
        whose ``instantiate()`` blew up is not in a state to handle events,
        and delivering to it would turn one broken plugin into a stream of
        exceptions on every signal in the system.
        """
        try:
            await module._do_start()
        except Exception:
            logger.exception("Failed to start module %s", module.name)
            module._running = False
            return False
        self._subscribe(module)
        self._on_change()
        return True

    async def _stop_module(self, module: BaseModule) -> None:
        """Detach from the bus first, then stop. Never raises.

        Order matters: unsubscribing after ``shutdown()`` leaves a window in
        which an event can reach a module whose connections are already
        closed.
        """
        self._unsubscribe(module)
        try:
            await module._do_stop()
        except Exception:
            logger.exception("Error stopping module %s", module.name)
        self._on_change()

    # ── Schema ────────────────────────────────────────────────────

    def install_tables(self, name: str) -> list[str]:
        """Create any missing tables for the module's declared models.

        Safe to call repeatedly; existing tables are left untouched.
        Returns the list of newly created table names.
        """
        from modules.schema_ops import create_tables_for
        from modules.state_model import ModuleState

        module = self._registry.get_registered(name)
        if module is None:
            raise KeyError(f"Module '{name}' is not registered")

        models = self._registry.safe_models(module)
        created = create_tables_for(models) if models else []

        state, _ = ModuleState.objects.get_or_create(name=name)
        known = set(state.installed_tables or [])
        known.update(created)
        state.installed_tables = sorted(known)
        state.save(update_fields=["installed_tables", "updated_at"])

        return created

    def install_missing_at_boot(self) -> None:
        """Create tables declared in code but absent from the database.

        This is what makes adding a model to an enabled module a
        zero-ceremony operation: on the next boot, the table appears.
        """
        for module in self._registry.all_registered():
            name = module.name
            if not self._registry.is_enabled_in_state(name):
                continue
            if not self._registry.safe_models(module):
                continue
            try:
                self.install_tables(name)
            except Exception:
                logger.exception("install_missing_at_boot failed for %s", name)

    # ── Enable / disable / uninstall ──────────────────────────────

    async def enable(self, name: str, *, notify_ai) -> None:
        """Mark a module enabled, install its tables, and start it.

        Idempotent: if already enabled and running, does nothing.
        """
        module = self._registry.get_registered(name)
        if module is None:
            raise KeyError(f"Module '{name}' is not registered")

        # Sync ORM + schema_editor work is dispatched to a thread: this
        # coroutine is awaited from an HTTP handler on the event loop.
        await sync_to_async(self._registry.upsert_state, thread_sensitive=True)(
            name, enabled=True,
        )
        await sync_to_async(self.install_tables, thread_sensitive=True)(name)

        if not module.is_available():
            logger.info(
                "Module '%s' enabled but not available yet (config missing)", name,
            )
            return

        if not self._registry.is_active(name):
            module.set_notify_ai(notify_ai)
            self._registry.activate(module)

        if not module.is_running:
            if not await self._start_module(module):
                return

        self._on_change()
        logger.info("Module '%s' enabled", name)

    async def disable(self, name: str) -> None:
        """Mark a module disabled and stop it. Tables are preserved."""
        module = self._registry.get_registered(name)
        if module is None:
            raise KeyError(f"Module '{name}' is not registered")

        await sync_to_async(self._registry.upsert_state, thread_sensitive=True)(
            name, enabled=False,
        )

        if module.is_running:
            await self._stop_module(module)
        else:
            self._unsubscribe(module)

        self._registry.deactivate(name)
        self._on_change()
        logger.info("Module '%s' disabled (tables preserved)", name)

    async def uninstall(self, name: str) -> None:
        """Stop the module and drop every table it owns.

        DESTRUCTIVE. All data in the module's tables is lost.
        """
        from modules.schema_ops import drop_tables_for
        from modules.state_model import ModuleState

        module = self._registry.get_registered(name)
        if module is None:
            raise KeyError(f"Module '{name}' is not registered")

        if module.is_running:
            await self._stop_module(module)
        else:
            self._unsubscribe(module)

        models = self._registry.safe_models(module)
        if models:
            await sync_to_async(drop_tables_for, thread_sensitive=True)(models)

        await sync_to_async(
            lambda: ModuleState.objects.filter(pk=name).delete(),
            thread_sensitive=True,
        )()
        self._registry.deactivate(name)
        self._on_change()
        logger.warning("Module '%s' uninstalled (tables dropped)", name)

    # ── Bulk ──────────────────────────────────────────────────────

    async def start_all(self) -> None:
        """Drop user-disabled modules, create missing tables, start the rest."""
        def _collect_disabled() -> list[str]:
            return [
                m.name for m in self._registry.active()
                if not self._registry.is_enabled_in_state(m.name)
            ]

        disabled = await sync_to_async(_collect_disabled, thread_sensitive=True)()
        for name in disabled:
            logger.info("Module '%s' disabled via ModuleState, skipping", name)
            self._registry.deactivate(name)

        try:
            await sync_to_async(
                self.install_missing_at_boot, thread_sensitive=True,
            )()
        except Exception:
            logger.exception("install_missing_at_boot failed")

        for module in self._registry.active():
            await self._start_module(module)

    async def stop_all(self) -> None:
        """Stop every running module, most-recently-started first."""
        for module in reversed(self._registry.active()):
            if module.is_running:
                await self._stop_module(module)
            else:
                self._unsubscribe(module)
