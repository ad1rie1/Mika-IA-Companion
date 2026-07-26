"""ConfigService — the runtime accessor.

Read path:
    get(key) → user override in ConfigValue → env_fallback from settings → schema default

Write path:
    set(key, value) → validate → encrypt if sensitive → persist → audit → notify

Record-list CRUD:
    list_rows / add_row / update_row / delete_row / reorder

Subscribers:
    Engines register ``on_change(key_prefix, callback)`` to get notified
    when a relevant key changes, enabling hot-reload without a restart.
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Callable

from configs import secrets
from configs.registry import registry
from configs.types import ConfigItem

logger = logging.getLogger(__name__)

Subscriber = Callable[[str, Any], None]
_UNSET = object()


class ValidationError(ValueError):
    pass


class ConfigService:
    """Singleton. Lazy-imports models to stay importable before Django apps load."""

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._cache_lock = threading.RLock()
        self._subscribers: list[tuple[str, Subscriber]] = []

    # ── Read ────────────────────────────────────────────────────

    def get(self, key: str, *, default: Any = _UNSET) -> Any:
        """Effective value. Order: DB override → env_fallback → schema default → provided default."""
        with self._cache_lock:
            if key in self._cache:
                return self._cache[key]

        item = registry.get(key)
        if item is None and default is _UNSET:
            raise KeyError(f"Unknown config key: {key}")

        value = self._resolve(key, item)
        if value is _UNSET:
            if default is not _UNSET:
                return default
            return None

        with self._cache_lock:
            self._cache[key] = value
        return value

    def _resolve(self, key: str, item: ConfigItem | None) -> Any:
        # 1. DB value (seeded from .env on first boot, see seed_from_env())
        try:
            from configs.models import ConfigValue
            row = ConfigValue.objects.filter(key=key).first()
        except Exception:
            row = None
        if row is not None:
            raw = row.value_json
            if row.encrypted and raw is not None:
                raw = secrets.decrypt(raw)
            return raw

        # 2. schema default — ``env_fallback`` is never consulted at
        # runtime, only during ``seed_from_env()`` to materialise an
        # initial ConfigValue row on an empty database.
        if item is not None:
            return item.default
        return _UNSET

    # ── One-shot seed from .env ─────────────────────────────────

    def seed_from_env(self) -> int:
        """Populate ConfigValue rows from ``env_fallback`` Django settings
        for every declared item that doesn't already have a DB row.

        Idempotent: a user-edited value is never overwritten. A user
        ``unset`` that later re-deletes the row will *not* be re-seeded
        because we mark every seeded key in ``_seed_complete`` below.

        Returns the number of rows materialised.
        """
        from django.conf import settings
        from configs.models import ConfigValue
        from configs.registry import registry

        # Guard: if the seed marker exists we've run once already.
        marker_key = "__seed_complete"
        if ConfigValue.objects.filter(key=marker_key).exists():
            return 0

        created = 0
        for item in registry.all_items():
            if item.type == "record_list":
                continue
            if not item.env_fallback:
                continue
            if ConfigValue.objects.filter(key=item.key).exists():
                continue
            env_value = getattr(settings, item.env_fallback, None)
            if env_value in (None, ""):
                continue
            stored = env_value
            encrypted = False
            if item.sensitive:
                stored = secrets.encrypt(str(env_value))
                encrypted = True
            ConfigValue.objects.create(
                key=item.key, value_json=stored, encrypted=encrypted,
                updated_by="env-seed",
            )
            created += 1

        ConfigValue.objects.create(
            key=marker_key, value_json={"count": created}, updated_by="env-seed",
        )
        if created:
            logger.info("ConfigService: seeded %d config values from .env", created)
        return created

    def snapshot(self) -> dict[str, Any]:
        """Effective value for every declared key (scalars only)."""
        out = {}
        for item in registry.all_items():
            if item.type == "record_list":
                continue
            try:
                out[item.key] = self.get(item.key)
            except Exception:
                out[item.key] = None
        return out

    def snapshot_redacted(self) -> dict[str, Any]:
        """Like ``snapshot()`` but secrets are returned as preview dicts."""
        out = {}
        for item in registry.all_items():
            if item.type == "record_list":
                continue
            try:
                val = self.get(item.key)
            except Exception:
                val = None
            if item.sensitive:
                out[item.key] = secrets.redact(val)
            else:
                out[item.key] = val
        return out

    # ── Write ───────────────────────────────────────────────────

    def set(self, key: str, value: Any, *, actor: str = "") -> Any:
        item = registry.get(key)
        if item is None:
            raise KeyError(f"Unknown config key: {key}")
        if item.readonly:
            raise ValidationError("Cette clé est en lecture seule")

        coerced = _coerce(item, value)
        _validate(item, coerced)

        from configs.models import ConfigValue, ConfigChangeLog
        before = self._resolve(key, item)

        stored = coerced
        encrypted = False
        if item.sensitive:
            # Do not re-encrypt if the UI omitted the value (caller should
            # use a sentinel; we interpret "" / None as "unchanged" here).
            if stored in (None, ""):
                return before
            stored = secrets.encrypt(str(stored))
            encrypted = True

        ConfigValue.objects.update_or_create(
            key=key,
            defaults={
                "value_json": stored,
                "encrypted": encrypted,
                "updated_by": actor,
            },
        )
        ConfigChangeLog.objects.create(
            key=key, action="set",
            before=_scrub_for_log(item, before),
            after=_scrub_for_log(item, coerced),
            actor=actor,
        )
        self._invalidate(key)
        self._notify(key, coerced)
        return coerced

    def unset(self, key: str, *, actor: str = "") -> None:
        """Remove the DB override — falls back to env/default."""
        from configs.models import ConfigValue, ConfigChangeLog
        item = registry.get(key)
        before = self._resolve(key, item)
        deleted, _ = ConfigValue.objects.filter(key=key).delete()
        if deleted:
            ConfigChangeLog.objects.create(
                key=key, action="unset",
                before=_scrub_for_log(item, before),
                after=None, actor=actor,
            )
        self._invalidate(key)
        self._notify(key, self.get(key, default=None))

    # ── Record-list CRUD (delegates to pluggable backend) ───────

    def list_rows(self, parent_key: str, *, decrypt_secrets: bool = False) -> list[dict]:
        from configs import backends
        item = self._require_record_list(parent_key)
        return backends.resolve(parent_key).list_rows(item, decrypt_secrets=decrypt_secrets)

    def add_row(self, parent_key: str, payload: dict, *, actor: str = "") -> dict:
        from configs import backends
        from configs.models import ConfigChangeLog
        item = self._require_record_list(parent_key)
        if item.max_items is not None:
            existing = backends.resolve(parent_key).list_rows(item)
            if len(existing) >= item.max_items:
                raise ValidationError(f"Limite atteinte ({item.max_items} éléments)")
        result = backends.resolve(parent_key).add_row(item, payload)
        ConfigChangeLog.objects.create(
            key=parent_key, row_id=None, action="row_add",
            before=None, after=_scrub_record(item.record, result.get("payload") or {}),
            actor=actor,
        )
        self._notify(parent_key, None)
        return result

    def update_row(self, parent_key: str, row_id: str, payload: dict, *, actor: str = "") -> dict:
        from configs import backends
        from configs.models import ConfigChangeLog
        item = self._require_record_list(parent_key)
        result = backends.resolve(parent_key).update_row(item, row_id, payload)
        ConfigChangeLog.objects.create(
            key=parent_key, row_id=None, action="row_update",
            before=None, after=_scrub_record(item.record, result.get("payload") or {}),
            actor=actor,
        )
        self._notify(parent_key, None)
        return result

    def delete_row(self, parent_key: str, row_id: str, *, actor: str = "") -> None:
        from configs import backends
        from configs.models import ConfigChangeLog
        item = self._require_record_list(parent_key)
        backends.resolve(parent_key).delete_row(item, row_id)
        ConfigChangeLog.objects.create(
            key=parent_key, row_id=None, action="row_delete",
            before=None, after=None, actor=actor,
        )
        self._notify(parent_key, None)

    def _require_record_list(self, parent_key: str) -> ConfigItem:
        item = registry.get(parent_key)
        if item is None or item.type != "record_list" or item.record is None:
            raise KeyError(f"{parent_key} is not a record_list")
        return item

    # ── Subscriptions ───────────────────────────────────────────

    def on_change(self, key_prefix: str, callback: Subscriber) -> None:
        """Call ``callback(key, new_value)`` when any key matching
        ``key_prefix`` changes. Prefix match — pass empty string to catch all."""
        self._subscribers.append((key_prefix, callback))

    def _notify(self, key: str, new_value: Any) -> None:
        for prefix, cb in self._subscribers:
            if key.startswith(prefix):
                try:
                    cb(key, new_value)
                except Exception:
                    logger.exception("Subscriber %r failed on %s", cb, key)

    # ── Cache ───────────────────────────────────────────────────

    def invalidate_cache(self, key: str | None = None) -> None:
        """Purge le cache de valeurs (tout, ou une clé).

        Utile aux déclarants dynamiques (forge) après un
        ``registry.register_replace`` qui change des défauts.
        """
        self._invalidate(key)

    def _invalidate(self, key: str | None = None) -> None:
        with self._cache_lock:
            if key is None:
                self._cache.clear()
            else:
                self._cache.pop(key, None)


# ── Helpers ─────────────────────────────────────────────────────

def _coerce(item: ConfigItem, value):
    t = item.type
    if value is None or value == "":
        return None if t not in ("str", "text", "secret") else value
    try:
        if t == "int":    return int(value)
        if t == "float":  return float(value)
        if t == "bool":   return bool(value) if not isinstance(value, str) else value.lower() in ("1", "true", "yes", "on")
        if t in ("str", "text", "secret"): return str(value)
        if t in ("select",):
            if item.choices and value not in item.choices:
                raise ValidationError(f"Valeur hors choix: {value!r}")
            return value
        if t in ("multiselect", "list"):
            if isinstance(value, str):
                return [v.strip() for v in value.split(",") if v.strip()]
            return list(value)
    except (TypeError, ValueError) as e:
        raise ValidationError(f"Type invalide pour {item.key}: {e}")
    return value


def _validate(item: ConfigItem, value) -> None:
    if value is None:
        return
    if item.min is not None and isinstance(value, (int, float)) and value < item.min:
        raise ValidationError(f"{item.key} doit être ≥ {item.min}")
    if item.max is not None and isinstance(value, (int, float)) and value > item.max:
        raise ValidationError(f"{item.key} doit être ≤ {item.max}")
    for v in item.validators or ():
        msg = v(value)
        if msg:
            raise ValidationError(msg)


def _scrub_for_log(item: ConfigItem | None, value):
    if item and item.sensitive and value not in (None, ""):
        return "***redacted***"
    return value


def _scrub_record(record, payload: dict) -> dict:
    if record is None:
        return payload
    out = dict(payload)
    for f in record.fields:
        if f.sensitive and out.get(f.key) not in (None, ""):
            out[f.key] = "***redacted***"
    return out


config_service = ConfigService()
