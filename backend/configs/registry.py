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

from configs.types import (
    ConfigItem, ConfigRecord, ConfigSection, choice_options,
)

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

    # ── Serialization (for API) ─────────────────────────────────

    def render_schema(self) -> list[dict]:
        """Shape consumed by the Dashboard config page."""
        sections_by_key = {s.key: s for s in self._sections.values()}
        grouped = self.by_section()
        out = []
        for section_key, items in grouped.items():
            section = sections_by_key.get(section_key) or ConfigSection(
                key=section_key, label=section_key.capitalize(),
            )
            out.append({
                "key": section.key,
                "label": section.label,
                "icon": section.icon,
                "description": section.description,
                "items": [_item_to_dict(i) for i in items],
            })
        out.sort(key=lambda s: sections_by_key.get(s["key"], ConfigSection("","",order=999)).order)
        return out


def _item_to_dict(i: ConfigItem) -> dict:
    d = {
        "key": i.key,
        "type": i.type,
        "label": i.label,
        "group": i.group,
        "description": i.description,
        "hint": i.hint,
        "default": i.default,
        "choices": list(choice_options(i.choices)) if i.choices else [],
        "min": i.min,
        "max": i.max,
        "sensitive": i.sensitive,
        "hot_reload": i.hot_reload,
        "restart_required": i.restart_required,
        "readonly": i.readonly,
        "env_fallback": i.env_fallback or None,
        "min_items": i.min_items,
        "max_items": i.max_items,
    }
    if i.record is not None:
        d["record"] = {
            "name": i.record.name,
            "label": i.record.label,
            "description": i.record.description,
            "fields": [_item_to_dict(f) for f in i.record.fields],
        }
    return d


registry = ConfigRegistry()
