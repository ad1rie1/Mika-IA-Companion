"""ConfigRegistry — aggregates schemas declared by each app/module.

Apps expose their schema via a ``config_schema.py`` module containing a
module-level ``CONFIG_SCHEMA`` list (sections + items). At startup
``ConfigsConfig.ready()`` walks every installed app and imports that
module if present.

Modules (BaseModule subclasses) can also register through
``ConfigRegistry.register_module(module)`` — ModuleManager does this on
``register()``.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Iterable

from configs.types import ConfigItem, ConfigSection

logger = logging.getLogger(__name__)


class ConfigRegistry:
    def __init__(self) -> None:
        self._sections: dict[str, ConfigSection] = {}
        self._items: dict[str, ConfigItem] = {}         # by full key

    # ── Registration ────────────────────────────────────────────

    def register(self, entries: Iterable) -> None:
        """Absorb a list of ConfigSection / ConfigItem entries."""
        for e in entries or ():
            if isinstance(e, ConfigSection):
                self._sections.setdefault(e.key, e)
            elif isinstance(e, ConfigItem):
                if e.key in self._items:
                    logger.warning("Config key %s re-declared, ignoring duplicate", e.key)
                    continue
                self._items[e.key] = e
            else:
                logger.warning("Unknown schema entry %r", e)

    def register_replace(self, entries: Iterable) -> None:
        """Comme ``register()`` mais une clé re-déclarée REMPLACE la
        précédente au lieu d'être ignorée.

        Réservé aux déclarants dynamiques (modules forgés) dont le schéma
        change légitimement en cours d'exécution — le hot reload d'un
        module doit pouvoir mettre à jour libellés et défauts.
        """
        replaced: list[str] = []
        for e in entries or ():
            if isinstance(e, ConfigSection):
                self._sections[e.key] = e
            elif isinstance(e, ConfigItem):
                self._items[e.key] = e
                replaced.append(e.key)
            else:
                logger.warning("Unknown schema entry %r", e)

        # A replaced item can carry a different `default`, so any value the
        # service already memoized for that key is stale.
        if replaced:
            self._invalidate_service_cache(replaced)

    @staticmethod
    def _invalidate_service_cache(keys: list[str]) -> None:
        try:
            from configs.service import config_service
            for key in keys:
                config_service._invalidate(key)
        except Exception:  # pragma: no cover — service optional at import time
            logger.debug("config cache invalidation skipped", exc_info=True)

    def unregister(self, *, key_prefix: str = "", section_key: str = "") -> int:
        """Retire des entrées déclarées dynamiquement.

        Les ``ConfigValue`` en base ne sont PAS touchées — réactiver le
        déclarant retrouve ses valeurs. Retourne le nombre d'items retirés.
        """
        removed = 0
        if key_prefix:
            for key in [k for k in self._items if k.startswith(key_prefix)]:
                del self._items[key]
                removed += 1
        if section_key:
            self._sections.pop(section_key, None)
        return removed

    def autodiscover(self) -> None:
        """Import ``<app_label>.config_schema`` for every installed app."""
        from django.apps import apps as django_apps
        import importlib

        for app_config in django_apps.get_app_configs():
            mod_name = f"{app_config.name}.config_schema"
            try:
                mod = importlib.import_module(mod_name)
            except ModuleNotFoundError:
                continue
            except Exception:
                logger.exception("Failed to import %s", mod_name)
                continue
            entries = getattr(mod, "CONFIG_SCHEMA", None)
            if entries:
                self.register(entries)
                logger.debug("Registered %d schema entries from %s", len(entries), mod_name)

        logger.info(
            "ConfigRegistry: %d sections, %d items",
            len(self._sections), len(self._items),
        )

    # ── Query ───────────────────────────────────────────────────

    def get(self, key: str) -> ConfigItem | None:
        return self._items.get(key)

    def all_items(self) -> list[ConfigItem]:
        return list(self._items.values())

    def sections(self) -> list[ConfigSection]:
        """Sections in declared order (``order`` ASC, then label)."""
        return sorted(
            self._sections.values(),
            key=lambda s: (s.order, s.label),
        )

    def by_section(self) -> "OrderedDict[str, list[ConfigItem]]":
        """Return sections → items, preserving declared order."""
        out: "OrderedDict[str, list[ConfigItem]]" = OrderedDict()
        # seed all sections so empty ones stay visible
        for s in self.sections():
            out[s.key] = []
        for item in self._items.values():
            out.setdefault(item.section, []).append(item)
        return out

    # ── Sérialisation ───────────────────────────────────────────
    #
    # Il n'y en a plus. ``render_schema()`` mettait le schéma à plat en JSON
    # pour l'ancien dashboard rendu dans le navigateur ; GestionSystème lit
    # le registre directement (``views/config.py``, ``forms.py``) et rend
    # côté serveur. Rien ne doit revenir : sérialiser le schéma est la porte
    # par laquelle un endpoint réexposerait ``sensitive`` et ``default``
    # sans passer par ``snapshot_redacted()``.


registry = ConfigRegistry()
