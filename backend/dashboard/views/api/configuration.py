"""Dashboard API — configuration schema browser + editor.

Read-only:
  GET  /dashboard/api/config/schema    full registry grouped by section
  GET  /dashboard/api/config/values    current resolved values (secrets redacted)
  GET  /dashboard/api/config/rows?key=…  record_list rows (secrets redacted)
  GET  /dashboard/api/config/history   audit trail

Write:
  PATCH  /dashboard/api/config/values           {key, value}
  DELETE /dashboard/api/config/values?key=…     remove override
  POST   /dashboard/api/config/rows             {parent_key, payload}
  PATCH  /dashboard/api/config/rows/<row_id>    {parent_key, payload}
  DELETE /dashboard/api/config/rows/<row_id>?parent_key=…
"""
from __future__ import annotations

import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from configs.registry import registry
from configs.service import ValidationError, config_service

logger = logging.getLogger(__name__)


def _body(request) -> dict:
    try:
        return json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return {}


def _error(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": msg}, status=status)


# ── Schema + values ─────────────────────────────────────────────

@require_http_methods(["GET"])
def schema(request):
    """Full declarative schema. The UI builds all forms from this."""
    return JsonResponse({"sections": registry.render_schema()})


@require_http_methods(["GET"])
def values(request):
    """Effective values for every scalar item. Secrets redacted."""
    return JsonResponse({"values": config_service.snapshot_redacted()})


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
def value_write(request):
    if request.method == "DELETE":
        key = request.GET.get("key", "")
        if not key:
            return _error("key required")
        try:
            config_service.unset(key, actor=_actor(request))
        except KeyError as e:
            return _error(str(e), status=404)
        return JsonResponse({"ok": True})

    body = _body(request)
    key = body.get("key", "")
    if not key:
        return _error("key required")
    try:
        applied = config_service.set(key, body.get("value"), actor=_actor(request))
    except KeyError as e:
        return _error(str(e), status=404)
    except ValidationError as e:
        return _error(str(e))
    item = registry.get(key)
    redacted = config_service.snapshot_redacted().get(key)
    return JsonResponse({"ok": True, "key": key, "value": redacted if item and item.sensitive else applied})


# ── Record-list CRUD ────────────────────────────────────────────

@require_http_methods(["GET"])
def rows(request):
    parent_key = request.GET.get("key", "")
    if not parent_key:
        return _error("key required")
    try:
        rows = config_service.list_rows(parent_key, decrypt_secrets=False)
    except KeyError as e:
        return _error(str(e), status=404)
    return JsonResponse({"parent_key": parent_key, "rows": rows})


@csrf_exempt
@require_http_methods(["POST"])
def row_add(request):
    body = _body(request)
    parent_key = body.get("parent_key", "")
    payload = body.get("payload") or {}
    if not parent_key:
        return _error("parent_key required")
    try:
        created = config_service.add_row(parent_key, payload, actor=_actor(request))
    except KeyError as e:
        return _error(str(e), status=404)
    except ValidationError as e:
        return _error(str(e))
    return JsonResponse({"ok": True, "row": created})


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
def row_detail(request, row_id: str):
    parent_key = request.GET.get("parent_key") or (_body(request).get("parent_key", ""))
    if not parent_key:
        return _error("parent_key required")
    if request.method == "DELETE":
        try:
            config_service.delete_row(parent_key, row_id, actor=_actor(request))
        except KeyError as e:
            return _error(str(e), status=404)
        return JsonResponse({"ok": True})

    body = _body(request)
    payload = body.get("payload") or {}
    try:
        row = config_service.update_row(parent_key, row_id, payload, actor=_actor(request))
    except KeyError as e:
        return _error(str(e), status=404)
    except ValidationError as e:
        return _error(str(e))
    return JsonResponse({"ok": True, "row": row})


# ── History ─────────────────────────────────────────────────────

@require_http_methods(["GET"])
def history(request):
    from configs.models import ConfigChangeLog
    try:
        limit = max(1, min(500, int(request.GET.get("limit", 100))))
    except (TypeError, ValueError):
        limit = 100
    key = request.GET.get("key")
    qs = ConfigChangeLog.objects.order_by("-created_at")
    if key:
        qs = qs.filter(key=key)
    rows = [
        {
            "id": l.id,
            "key": l.key,
            "row_id": str(l.row_id) if l.row_id else None,
            "action": l.action,
            "before": l.before,
            "after": l.after,
            "actor": l.actor,
            "created_at": l.created_at.isoformat(),
        }
        for l in qs[:limit]
    ]
    return JsonResponse({"rows": rows, "total": len(rows)})


# ── Helpers ─────────────────────────────────────────────────────

def _actor(request) -> str:
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return str(user)
    return request.META.get("REMOTE_ADDR", "anon")
