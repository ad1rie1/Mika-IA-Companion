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

import asyncio
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from configs import secrets
from configs.registry import registry
from configs.types import ConfigItem, choice_values

logger = logging.getLogger(__name__)

Subscriber = Callable[[str, Any], None]
_UNSET = object()


class ValidationError(ValueError):
    pass


# ── Async-context safety ────────────────────────────────────────
#
# Config reads are synchronous *by design*: they happen in provider
# constructors, in engine ``__init__``s, in prompt builders — call sites
# that cannot become coroutines without turning the whole tree async. But
# half of them run under the ASGI loop, where Django refuses ORM access on
# the loop thread, and both failure modes were silent-ish:
#
#   - ``list_rows()`` had no cache at all, so ``ai.models`` was read on
#     *every* AI call and raised SynchronousOnlyOperation mid-conversation
#     ("Oups, j'ai eu un petit bug..." on every turn).
#   - ``get()`` swallowed the very same exception in ``_resolve``'s
#     ``except Exception`` and returned the schema default, so a provider
#     key configured in the dashboard read back as *absent*.
#
# The query is therefore handed to a dedicated worker thread and waited on.
# It blocks the loop for the duration of one indexed row read on a WAL
# database — microseconds — which is the price of keeping the read
# synchronous at ~200 call sites. A single worker is deliberate: it mirrors
# ``sync_to_async(thread_sensitive=True)``, keeps one long-lived SQLite
# connection, and serialises config reads the way they already were.
_db_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="config-db")


def in_async_context() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def db_read(fn: Callable, *args, **kwargs):
    """Run a synchronous ORM query, whatever context the caller is in.

    Inline when called from a sync context (the vast majority: startup,
    dashboard views, management commands); off-loop otherwise.
    """
    if not in_async_context():
        return fn(*args, **kwargs)

    def _call():
        from django.db import close_old_connections
        # The worker owns its own thread-local connection; drop it if it
        # went stale (CONN_MAX_AGE, health check) rather than reusing a
        # dead handle for the lifetime of the process.
        close_old_connections()
        return fn(*args, **kwargs)

    return _db_pool.submit(_call).result()


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

    def _resolve(self, key: str, item: ConfigItem | None,
                 *, with_origin: bool = False) -> Any:
        """Valeur effective. ``with_origin`` renvoie ``(valeur, ligne_existe)``.

        Le drapeau distingue « enregistré à cette valeur » de « laissé au
        défaut du schéma » : les deux lisent la même valeur, et seule
        l'existence d'une ligne ``ConfigValue`` épingle le réglage contre une
        évolution future du défaut.
        """
        # 1. DB value (seeded from .env on first boot, see seed_from_env())
        row = db_read(_fetch_value_row, key)
        if row is not None:
            raw = row.value_json
            if row.encrypted and raw is not None:
                raw = secrets.decrypt(raw)
            return (raw, True) if with_origin else raw

        # 2. schema default — ``env_fallback`` is never consulted at
        # runtime, only during ``seed_from_env()`` to materialise an
        # initial ConfigValue row on an empty database.
        value = item.default if item is not None else _UNSET
        return (value, False) if with_origin else value

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
        before, deja_enregistre = self._resolve(key, item, with_origin=True)

        # Rien n'a bougé : ni écriture, ni ligne de journal, ni réveil des
        # abonnés. Enregistrer une section soumet *tous* les champs qui
        # étaient à l'écran, donc sans ce court-circuit déplacer un seul
        # curseur d'« IA · Providers » évinçait les douze instances de
        # providers en cache et ajoutait onze lignes de journal où
        # ``before == after`` — dans la table même qu'on ouvre pour
        # répondre à « qu'est-ce que j'ai changé ».
        #
        # La ligne doit *déjà* exister : soumettre explicitement la valeur
        # du schéma la matérialise, et c'est ce qui épingle le réglage
        # contre une évolution future du défaut — la distinction que
        # ``BoundField.is_default`` affiche.
        if deja_enregistre and before == coerced:
            return coerced

        stored = coerced
        encrypted = False
        if item.sensitive:
            # Do not re-encrypt if the UI omitted the value (caller should
            # use a sentinel; we interpret "" / None as "unchanged" here).
            if stored in (None, ""):
                # Return a redacted marker, not `before`: this is a no-op, and
                # handing the *decrypted* current secret back to a caller that
                # merely submitted a blank field is a leak waiting for the one
                # caller that doesn't redact its own response.
                return secrets.redact(before) if before else before
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
        backend = backends.resolve(parent_key)
        return db_read(backend.list_rows, item, decrypt_secrets=decrypt_secrets)

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
        # Invalidate BEFORE notifying: a subscriber that reacts by calling
        # get() must not read the pre-change cached value.
        self._invalidate(parent_key)
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
        # Invalidate BEFORE notifying: a subscriber that reacts by calling
        # get() must not read the pre-change cached value.
        self._invalidate(parent_key)
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
        # Invalidate BEFORE notifying: a subscriber that reacts by calling
        # get() must not read the pre-change cached value.
        self._invalidate(parent_key)
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

def _fetch_value_row(key: str):
    """The one ConfigValue read behind ``get()``. Returns None if unreadable.

    "Unreadable" stays broad on purpose — a config read legitimately
    precedes a usable database (module imports run before ``migrate``, and
    the test suite blocks DB access at collection time), and falling back to
    the schema default is the right answer there.

    ``SynchronousOnlyOperation`` is the one exception that must *not* be
    absorbed: it says the caller is on the event loop, not that the database
    is unreachable. Swallowed, it handed back the schema default for a key
    that *was* configured — a dashboard-set provider token reading as
    absent, with nothing logged. ``db_read`` above means it can no longer be
    raised here; this re-raise is what stops it becoming silent again.
    """
    from django.core.exceptions import SynchronousOnlyOperation

    try:
        from configs.models import ConfigValue
        return ConfigValue.objects.filter(key=key).first()
    except SynchronousOnlyOperation:
        raise
    except Exception:
        logger.debug("Config key %s unreadable (database not ready)", key, exc_info=True)
        return None


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
            allowed = choice_values(item.choices)
            if allowed and value not in allowed:
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
