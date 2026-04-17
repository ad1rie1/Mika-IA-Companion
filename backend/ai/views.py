"""HTTP endpoints exposing quota usage for the AI layer.

    GET /api/ai/quota/           current-day + current-month snapshot
    GET /api/ai/quota/history    per-day rows for the last N days

Both are read-only; the tracker mutates only via the router.
"""
from __future__ import annotations

import logging

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ai.quota import quota_tracker

logger = logging.getLogger(__name__)


@require_http_methods(["GET"])
def quota_snapshot(request):
    """Return in-RAM totals for today + this month, per role + per project."""
    snap = quota_tracker.snapshot()
    return JsonResponse({
        "today": snap.today,
        "month": snap.month,
        "roles": snap.roles,
        "projects": snap.projects,
        "limits": snap.limits,
    })


@require_http_methods(["GET"])
def quota_history(request):
    """Historical per-day rows.

    Query params:
      days (int, default 14, cap 180)
      role (optional filter)
      project_id (optional filter — use 'null' to get only global calls)
    """
    from ai.models import AIQuotaUsage

    try:
        days = int(request.GET.get("days", 14))
    except (TypeError, ValueError):
        days = 14
    days = max(1, min(180, days))

    today = timezone.localdate()
    since = today.replace(day=1) if days > today.day else today.fromordinal(
        today.toordinal() - days + 1
    )

    qs = AIQuotaUsage.objects.filter(date__gte=since)
    role = request.GET.get("role")
    if role:
        qs = qs.filter(role=role)
    project_filter = request.GET.get("project_id")
    if project_filter == "null":
        qs = qs.filter(project_id__isnull=True)
    elif project_filter:
        try:
            qs = qs.filter(project_id=int(project_filter))
        except ValueError:
            return JsonResponse({"error": "project_id must be int"}, status=400)

    rows = [
        {
            "date": r.date.isoformat(),
            "role": r.role,
            "project_id": r.project_id,
            "provider": r.provider,
            "model": r.model,
            "call_count": r.call_count,
            "tokens_in": r.tokens_in,
            "tokens_out": r.tokens_out,
            "cost_usd": round(r.cost_usd, 6),
        }
        for r in qs.order_by("-date", "role", "project_id")
    ]
    return JsonResponse({"since": since.isoformat(), "rows": rows})
