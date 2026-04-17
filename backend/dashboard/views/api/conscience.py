from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from dashboard.serializers import iso, paginate, pick


@require_http_methods(["GET"])
def observations(request):
    from conscience.models import Observation

    limit, offset = paginate(request, default=50)
    status = pick(request, "status")
    category = pick(request, "category")
    qs = Observation.objects.order_by("-created_at")
    if status:
        qs = qs.filter(status=status)
    if category:
        qs = qs.filter(category=category)
    total = qs.count()
    rows = [
        {
            "id": o.id,
            "source": o.source,
            "event_type": o.event_type,
            "summary": o.summary,
            "category": o.category,
            "pertinence": round(o.pertinence, 3),
            "emotional_reaction": o.emotional_reaction,
            "emotional_intensity": round(o.emotional_intensity, 3),
            "status": o.status,
            "action_response": o.action_response[:400] if o.action_response else "",
            "created_at": iso(o.created_at),
        }
        for o in qs[offset:offset + limit]
    ]
    return JsonResponse({"total": total, "limit": limit, "offset": offset, "rows": rows})


@require_http_methods(["GET"])
def conscience_logs(request):
    from conscience.models import ConscienceLog

    limit, offset = paginate(request, default=50)
    qs = ConscienceLog.objects.order_by("-created_at")
    total = qs.count()
    rows = [
        {
            "id": l.id,
            "observations_count": l.observations_count,
            "max_pertinence": round(l.max_pertinence, 3),
            "global_mood": l.global_mood,
            "global_intensity": round(l.global_intensity, 3),
            "idle_seconds": l.idle_seconds,
            "decision": l.decision,
            "reason": l.reason,
            "memory_actions": l.memory_actions,
            "created_at": iso(l.created_at),
        }
        for l in qs[offset:offset + limit]
    ]
    try:
        from conscience.engine import conscience_engine
        idle = round(conscience_engine.get_idle_seconds(), 1)
    except Exception:
        idle = None
    return JsonResponse({
        "total": total, "limit": limit, "offset": offset,
        "rows": rows, "idle_seconds": idle,
    })


@require_http_methods(["GET"])
def ruminations(request):
    from conscience.models import Rumination

    limit, offset = paginate(request, default=50)
    status = pick(request, "status")
    qs = Rumination.objects.order_by("-intensity", "-created_at")
    if status:
        qs = qs.filter(status=status)
    total = qs.count()
    rows = [
        {
            "id": r.id,
            "summary": r.summary,
            "themes": r.themes,
            "emotion": r.emotion,
            "intensity": round(r.intensity, 3),
            "status": r.status,
            "created_at": iso(r.created_at),
            "updated_at": iso(r.updated_at),
        }
        for r in qs[offset:offset + limit]
    ]
    return JsonResponse({"total": total, "limit": limit, "offset": offset, "rows": rows})


@require_http_methods(["GET"])
def scheduled_actions(request):
    from conscience.models import ScheduledAction

    limit, offset = paginate(request, default=50)
    qs = ScheduledAction.objects.order_by("scheduled_at")
    total = qs.count()
    rows = [
        {
            "id": a.id,
            "scheduled_at": iso(a.scheduled_at),
            "prompt": a.prompt,
            "priority": round(a.priority, 3),
            "source": a.source,
            "status": a.status,
            "created_at": iso(a.created_at),
            "executed_at": iso(a.executed_at),
        }
        for a in qs[offset:offset + limit]
    ]
    return JsonResponse({"total": total, "limit": limit, "offset": offset, "rows": rows})
