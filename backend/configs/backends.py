"""Storage backends for ``record_list`` config items.

The default backend persists rows in the generic ``ConfigRecordItem``
table — fine for simple lists that have no existing home.

Modules that already own a Django model (e.g. ``EmailAccount``,
``RSSFeed``) register a **custom backend** mapping their model's CRUD
to the same ``(list_rows / add_row / update_row / delete_row)`` API.
From the dashboard's point of view nothing changes — the editor form
still reads the record schema and sends JSON. Storage decoupling means
the module keeps exclusive ownership of its data while the config UI
acts as the edition front-end.
"""
from __future__ import annotations

import logging
from typing import Protocol

from configs import secrets
# Record rows go through the SAME coercion + validation as scalar config
# items. The local copy this replaced handled only int/float/bool, silently
# returned the raw string on a ValueError, and checked neither `select`
# choices nor min/max/validators — so `ai.models` accepted
# `temperature: "hot"` or `provider: "anthropicc"` verbatim, and the error
# surfaced much later as a ValueError mid-conversation in the AI router.
# (service imports backends lazily, so this direction is safe.)
from configs.service import _coerce, _validate
from configs.types import ConfigItem, ConfigRecord

logger = logging.getLogger(__name__)


class RecordListBackend(Protocol):
    """Interface every record_list storage must implement."""

    def list_rows(self, item: ConfigItem, *, decrypt_secrets: bool = False) -> list[dict]:
        ...

    def add_row(self, item: ConfigItem, payload: dict) -> dict:
        ...

    def update_row(self, item: ConfigItem, row_id: str, payload: dict) -> dict:
        ...

    def delete_row(self, item: ConfigItem, row_id: str) -> None:
        ...


# ── Default: ConfigRecordItem ───────────────────────────────────

class ConfigRecordItemBackend:
    """Stores rows in the generic ``configs.ConfigRecordItem`` table."""

    def list_rows(self, item, *, decrypt_secrets=False):
        from configs.models import ConfigRecordItem
        rows = ConfigRecordItem.objects.filter(parent_key=item.key).order_by("order", "id")
        out = []
        for r in rows:
            payload = dict(r.payload or {})
            for fname in r.encrypted_fields or []:
                raw = payload.get(fname)
                if not raw:
                    continue
                if decrypt_secrets:
                    payload[fname] = secrets.decrypt(raw)
                else:
                    payload[fname] = secrets.redact(secrets.decrypt(raw))
            out.append({
                "row_id": str(r.row_id),
                "payload": payload,
                "enabled": r.enabled,
                "order": r.order,
                "updated_at": r.updated_at.isoformat(),
            })
        return out

    def add_row(self, item, payload):
        from configs.models import ConfigRecordItem
        cleaned, encrypted = _clean_payload(item.record, payload)
        last = ConfigRecordItem.objects.filter(parent_key=item.key).order_by("-order").first()
        order = (last.order + 1) if last else 0
        row = ConfigRecordItem.objects.create(
            parent_key=item.key, payload=cleaned,
            encrypted_fields=encrypted, order=order,
        )
        return {"row_id": str(row.row_id), "payload": cleaned, "order": row.order}

    def update_row(self, item, row_id, payload):
        from configs.models import ConfigRecordItem
        try:
            row = ConfigRecordItem.objects.get(parent_key=item.key, row_id=row_id)
        except ConfigRecordItem.DoesNotExist:
            raise KeyError(f"Row {row_id} not found in {item.key}")
        before = dict(row.payload or {})
        cleaned, encrypted = _clean_payload(
            item.record, payload,
            existing=before, existing_encrypted=row.encrypted_fields or [],
        )
        row.payload = cleaned
        row.encrypted_fields = encrypted
        if "enabled" in payload:
            row.enabled = bool(payload["enabled"])
        if "order" in payload and isinstance(payload["order"], int):
            row.order = payload["order"]
        row.save()
        return {"row_id": str(row.row_id), "payload": cleaned, "order": row.order, "enabled": row.enabled}

    def delete_row(self, item, row_id):
        from configs.models import ConfigRecordItem
        ConfigRecordItem.objects.filter(parent_key=item.key, row_id=row_id).delete()


# ── Registry ────────────────────────────────────────────────────

_BACKENDS: dict[str, RecordListBackend] = {}
_DEFAULT = ConfigRecordItemBackend()


def register(parent_key: str, backend: RecordListBackend) -> None:
    """Route CRUD for ``parent_key`` through a custom backend.

    Called from modules that own their own storage (EmailAccount, RSSFeed, …).
    """
    _BACKENDS[parent_key] = backend
    logger.info("Record-list backend registered for %s: %s", parent_key, type(backend).__name__)


def resolve(parent_key: str) -> RecordListBackend:
    return _BACKENDS.get(parent_key, _DEFAULT)


# ── Helpers (extracted from ConfigService) ──────────────────────

_UNSET = object()


def _clean_payload(record: ConfigRecord | None, payload: dict, *,
                   existing: dict | None = None,
                   existing_encrypted: list[str] | None = None) -> tuple[dict, list[str]]:
    """Validate + coerce a record_list row. Returns (stored_payload, encrypted_field_names)."""
    if record is None:
        return dict(payload or {}), []
    existing = existing or {}
    existing_encrypted = existing_encrypted or []
    cleaned = {}
    encrypted = []
    for field in record.fields:
        incoming = payload.get(field.key, _UNSET)
        if field.sensitive:
            if incoming is _UNSET or incoming in (None, ""):
                if field.key in existing_encrypted and field.key in existing:
                    cleaned[field.key] = existing[field.key]
                    encrypted.append(field.key)
                continue
            cleaned[field.key] = secrets.encrypt(str(incoming))
            encrypted.append(field.key)
            continue

        if incoming is _UNSET:
            if field.key in existing:
                cleaned[field.key] = existing[field.key]
            elif field.default is not None:
                cleaned[field.key] = field.default
            continue

        value = _coerce(field, incoming)
        _validate(field, value)
        cleaned[field.key] = value
    return cleaned, encrypted


