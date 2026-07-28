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

def _declared_model_names() -> list[str]:
    """Current set of internal_name values from the ai.models record_list.

    Used to populate the choices of every ``ai.role.*`` select at schema
    render time — the registry can't carry dynamic choices, so we inject
    them here just before the frontend reads the schema.
    """
    try:
        rows = config_service.list_rows("ai.models", decrypt_secrets=False)
    except KeyError:
        return []
    out: list[str] = []
    for row in rows:
        if not row.get("enabled", True):
            continue
        name = ((row.get("payload") or {}).get("internal_name") or "").strip()
        if name and name not in out:
            out.append(name)
    return out


@require_http_methods(["GET"])
def schema(request):
    """Full declarative schema. The UI builds all forms from this.

    Sections keyed ``module_<name>`` that belong to a user-disabled
    module are filtered out so the config page stays focused on active
    plugins. A disabled module is still re-enabled from the "Gestion
    des modules" page.

    Also injects the current set of declared-model internal names into
    every ``ai.role.*`` select, so roles can only be mapped to a model
    that actually exists.
    """
    sections = registry.render_schema()
    try:
        from modules.state_model import ModuleState
        disabled = set(
            ModuleState.objects.filter(enabled=False).values_list(
                "name", flat=True,
            )
        )
    except Exception:
        disabled = set()
    if disabled:
        sections = [
            s for s in sections
            if not (
                s.get("key", "").startswith("module_")
                and s["key"][len("module_"):] in disabled
            )
        ]

    model_names = _declared_model_names()
    for section in sections:
        if section.get("key") != "ai_roles":
            continue
        for item in section.get("items", []):
            if item.get("type") == "select" and item.get("key", "").startswith("ai.role."):
                item["choices"] = model_names

    return JsonResponse({"sections": sections})


@require_http_methods(["GET"])
def values(request):
    """Effective values for every scalar item. Secrets redacted."""
    return JsonResponse({"values": config_service.snapshot_redacted()})


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


def _declared_model_references(internal_name: str) -> list[str]:
    """Locations that reference a declared model by its internal name.

    Currently checks every ``ai.role.*`` scalar. Modules may later
    reference models too — extend here when they do.
    """
    refs: list[str] = []
    from ai.router import AIRole
    for role in AIRole:
        cfg_key = f"ai.role.{role.value}"
        try:
            val = (config_service.get(cfg_key, default="") or "").strip()
        except KeyError:
            continue
        if val == internal_name:
            refs.append(f"rôle IA · {role.value}")
    return refs


@require_http_methods(["PATCH", "DELETE"])
def row_detail(request, row_id: str):
    parent_key = request.GET.get("parent_key") or (_body(request).get("parent_key", ""))
    if not parent_key:
        return _error("parent_key required")
    if request.method == "DELETE":
        # Ref-check: refuse deletion of a declared model that's still
        # wired into a role (or, later, a module). The user must unmap
        # it first.
        if parent_key == "ai.models":
            try:
                rows = config_service.list_rows(parent_key, decrypt_secrets=False)
            except KeyError:
                rows = []
            target = next((r for r in rows if str(r.get("row_id")) == str(row_id)), None)
            if target is not None:
                name = ((target.get("payload") or {}).get("internal_name") or "").strip()
                if name:
                    refs = _declared_model_references(name)
                    if refs:
                        return _error(
                            "Modèle utilisé par : " + ", ".join(refs)
                            + ". Retire ces associations avant de supprimer.",
                            status=409,
                        )
        try:
            config_service.delete_row(parent_key, row_id, actor=_actor(request))
        except KeyError as e:
            return _error(str(e), status=404)
        except ValidationError as e:
            # A backend may refuse a deletion outright (deleting the last
            # active admin locks everyone out). Answer it like any other
            # refused write instead of surfacing a 500.
            return _error(str(e), status=409)
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
