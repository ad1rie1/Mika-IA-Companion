"""ModuleRegistry — who exists, and which of them the user wants running.

Split out of ``ModuleManager``, which had grown twelve responsibilities into
one object: registry, DDL, lifecycle, cron, event bus, five kinds of
aggregation, the notify_ai bridge and status. That is survivable when the
module list is fixed and written by hand. It stops being survivable when
modules are authored at runtime by Mika herself, because every one of those
concerns then has to be correct under hot reload, partial failure and
arbitrary handler code.

This object does one thing: it knows which modules exist, which are active,
and what the database says about whether they should be. It performs no I/O
beyond reading ``ModuleState`` and never starts anything — see
``modules.lifecycle``.
"""

from __future__ import annotations

import logging
from typing import Any

from modules.base import BaseModule

logger = logging.getLogger(__name__)


class ModuleRegistry:
    """Bookkeeping for registered and active modules."""

    def __init__(self) -> None:
        # Everything ever registered, including modules the user disabled
        # and modules whose preconditions are unmet. The dashboard needs to
        # list a module precisely when it *cannot* run, so the user can go
        # fill in the config that would let it.
        self._registered: dict[str, BaseModule] = {}
        # The subset the manager currently considers runnable.
        self._active: dict[str, BaseModule] = {}

    # ── Registration ──────────────────────────────────────────────

    def register(self, module: BaseModule) -> bool:
        """Record a module. Returns whether it landed in the active set.

        Raises ``ValueError`` on a duplicate name — unlike the event bus,
        a duplicate here is a genuine programming error (two apps claiming
        the same plugin), not a legitimate re-registration.
        """
        if module.name in self._registered:
            raise ValueError(f"Module '{module.name}' is already registered")

        self._registered[module.name] = module
        self._absorb_config_schema(module)

        if not module.is_available():
            logger.info(
                "Module '%s' not available (preconditions unmet), skipping",
                module.name,
            )
            return False

        # ModuleState is deliberately NOT consulted here: registration runs
        # from AppConfig.ready(), where touching the ORM raises Django's
        # APPS_NOT_READY warning and breaks a fresh install whose migration
        # for ModuleState has not been applied yet. The enabled/disabled
        # filter is applied at start-up instead, where the ORM is live.
        self._active[module.name] = module
        logger.info("Module registered: %s", module.name)
        return True

    @staticmethod
    def _absorb_config_schema(module: BaseModule) -> None:
        """Publish the module's config schema regardless of availability.

        The whole point of surfacing a schema in the UI is to let the user
        configure a module that *cannot run yet* because its settings are
        empty — so this must happen before the availability check, not after.
        """
        try:
            entries = module.config_schema()
        except Exception:
            logger.exception("config_schema() failed for module %s", module.name)
            return
        if not entries:
            return
        from configs.registry import registry as config_registry
        config_registry.register(entries)
        logger.debug(
            "Module '%s' registered %d config schema entries",
            module.name, len(entries),
        )

    # ── Lookup ────────────────────────────────────────────────────

    def get(self, name: str) -> BaseModule | None:
        """An active module, or None. Disabled modules are invisible here."""
        return self._active.get(name)

    def get_registered(self, name: str) -> BaseModule | None:
        """A module whether or not it is currently enabled."""
        return self._registered.get(name)

    def active(self) -> list[BaseModule]:
        return list(self._active.values())

    def running(self) -> list[BaseModule]:
        return [m for m in self._active.values() if m.is_running]

    def all_registered(self) -> list[BaseModule]:
        return list(self._registered.values())

    def activate(self, module: BaseModule) -> None:
        self._active[module.name] = module

    def deactivate(self, name: str) -> BaseModule | None:
        return self._active.pop(name, None)

    def is_active(self, name: str) -> bool:
        return name in self._active

    # ── Persisted enable/disable state ────────────────────────────

    @staticmethod
    def is_enabled_in_state(name: str) -> bool:
        """What ``ModuleState`` says. Unknown modules default to enabled.

        Defaulting to True keeps a module that has never been toggled
        behaving as it did before the enable/disable feature existed.
        """
        try:
            from modules.state_model import ModuleState
            state = ModuleState.objects.filter(pk=name).first()
        except Exception:
            # DB not migrated yet during bootstrap — assume enabled.
            return True
        return True if state is None else state.enabled

    @staticmethod
    def upsert_state(
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

    @staticmethod
    def safe_models(module: BaseModule) -> list:
        """``get_models()`` with the blast radius of a bad plugin contained."""
        try:
            return list(module.get_models() or [])
        except Exception:
            logger.exception("get_models() failed for module %s", module.name)
            return []

    # ── Reporting ─────────────────────────────────────────────────

    def list_all(self) -> list[dict[str, Any]]:
        """Every registered module with its enable/running state."""
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
                "has_models": bool(self.safe_models(module)),
                "system": bool(getattr(module, "SYSTEM", False)),
            })
        return result
