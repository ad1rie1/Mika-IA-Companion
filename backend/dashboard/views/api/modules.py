"""Module-layer introspection.

Surfaces ``module_manager.get_all_status()`` + the MCP tools each module
exposes. Useful to see at a glance: who's running, who self-disabled
(missing config, imports), tool inventory.
"""
from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET"])
def modules(request):
    from modules.manager import module_manager

    statuses = module_manager.get_all_status()
    tool_names = module_manager.get_tool_names()

    try:
        caps = module_manager.collect_capabilities()
    except Exception:
        caps = {}

    rows = []
    for s in statuses:
        mod = module_manager.get_module(s.name)
        interval = getattr(mod, "CRON_INTERVAL", None) if mod else None
        rows.append({
            "name": s.name,
            "running": s.running,
            "available": s.available,
            "uptime_seconds": round(s.uptime_seconds, 1),
            "error": s.error,
            "details": s.details,
            "cron_interval": interval,
            "capabilities": [c.value for c in caps.get(s.name, [])],
        })

    return JsonResponse({
        "modules": rows,
        "tool_names": tool_names,
        "total_tools": len(tool_names),
    })
