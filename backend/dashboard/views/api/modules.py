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

    all_info = module_manager.list_all()
    statuses = {s.name: s for s in module_manager.get_all_status()}

    rows = []
    for info in all_info:
        name = info["name"]
        mod = module_manager.get_registered(name)
        status = statuses.get(name)
        interval = getattr(mod, "CRON_INTERVAL", None) if mod else None
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
            "capabilities": [c.value for c in caps.get(name, [])],
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
