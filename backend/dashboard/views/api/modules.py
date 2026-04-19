"""Module-layer introspection and lifecycle control.

GET  /dashboard/api/modules                    list every registered module
                                               (running, enabled, available,
                                                capabilities, cron, tables)
POST /dashboard/api/modules/<name>/enable      mark enabled, install tables,
                                               and start
POST /dashboard/api/modules/<name>/disable     stop and mark disabled
                                               (tables preserved)
POST /dashboard/api/modules/<name>/uninstall   stop and drop tables
                                               (DESTRUCTIVE)
"""
from __future__ import annotations

import json

from asgiref.sync import async_to_sync
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


def _module_rows():
    from modules.manager import module_manager

    try:
        caps = module_manager.collect_capabilities()
    except Exception:
        caps = {}
    try:
        views_by_module = module_manager.collect_views()
    except Exception:
        views_by_module = {}

    all_info = module_manager.list_all()
    statuses = {s.name: s for s in module_manager.get_all_status()}

    rows = []
    for info in all_info:
        # Hide infrastructure modules (files, project_tools) that only
        # use the bus to expose MCP tools — they are not user-configurable
        # plugins and should not show up in "Gestion des modules".
        if info.get("system"):
            continue
        name = info["name"]
        mod = module_manager.get_registered(name)
        status = statuses.get(name)
        interval = getattr(mod, "CRON_INTERVAL", None) if mod else None
        views = [
            {
                "key": v.key,
                "label": v.label,
                "icon": v.icon,
                "url": f"/dashboard/modules/{name}/{v.key}/",
            }
            for v in views_by_module.get(name, [])
        ]
        rows.append({
            "name": name,
            "enabled": info["enabled"],
            "running": info["running"],
            "available": info["available"],
            "has_models": info["has_models"],
            "installed_tables": info["installed_tables"],
            "uptime_seconds": round(status.uptime_seconds, 1) if status else 0.0,
            "error": getattr(status, "error", None) if status else None,
            "details": getattr(status, "details", None) if status else None,
            "cron_interval": interval,
            "capabilities": [c.description for c in caps.get(name, [])],
            "views": views,
        })
    return rows


@require_http_methods(["GET"])
def modules(request):
    from modules.manager import module_manager

    return JsonResponse({
        "modules": _module_rows(),
        "tool_names": module_manager.get_tool_names(),
        "total_tools": len(module_manager.get_tool_names()),
    })


def _run_action(name: str, action: str):
    from modules.manager import module_manager

    fn = getattr(module_manager, action)
    try:
        async_to_sync(fn)(name)
    except KeyError:
        return JsonResponse(
            {"error": f"Module '{name}' is not registered"}, status=404,
        )
    except Exception as exc:
        return JsonResponse(
            {"error": f"{action} failed: {exc}"}, status=500,
        )

    row = next(
        (r for r in _module_rows() if r["name"] == name), None,
    )
    return JsonResponse({"ok": True, "action": action, "module": row})


@csrf_exempt
@require_http_methods(["POST"])
def module_enable(request, name: str):
    return _run_action(name, "enable")


@csrf_exempt
@require_http_methods(["POST"])
def module_disable(request, name: str):
    return _run_action(name, "disable")


@csrf_exempt
@require_http_methods(["POST"])
def module_uninstall(request, name: str):
    # Require an explicit confirm flag in the body so a mis-routed
    # click in the dashboard cannot nuke a module's tables.
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        body = {}
    if not body.get("confirm"):
        return JsonResponse(
            {
                "error": (
                    "uninstall is destructive; pass "
                    '{"confirm": true} in the body to proceed'
                ),
            },
            status=400,
        )
    return _run_action(name, "uninstall")
