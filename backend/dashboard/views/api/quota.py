from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET"])
def quota(request):
    try:
        from ai.quota import quota_tracker
    except Exception:
        return JsonResponse({"available": False})

    snap = quota_tracker.snapshot()
    return JsonResponse({
        "available": True,
        "today": snap.today,
        "month": snap.month,
        "roles": snap.roles,
        "projects": snap.projects,
        "limits": snap.limits,
    })
