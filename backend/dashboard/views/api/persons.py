from __future__ import annotations

from django.db.models import Count
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from dashboard.serializers import iso, paginate, pick


@require_http_methods(["GET"])
def persons(request):
    from memory.models import Entity, PersonProfile, Commitment
    from emotion.engine import emotion_engine
    from emotion import pad

    persons = {}
    for entity in Entity.objects.filter(entity_type="person"):
        persons[entity.name] = {
            "name": entity.name,
            "entity_id": entity.id,
            "profile": None,
            "affect": None,
            "commitments_pending": 0,
        }

    for p in PersonProfile.objects.select_related("entity"):
        if p.entity.name in persons:
            persons[p.entity.name]["profile"] = {
                "summary": p.summary,
                "closeness": p.closeness,
                "preferred_tone": p.preferred_tone,
                "topics_of_interest": list(p.topics_of_interest or []),
                "sensitive_topics": list(p.sensitive_topics or []),
                "interaction_count": p.interaction_count,
                "confidence": round(p.confidence, 3),
                "last_interaction_at": iso(p.last_interaction_at),
                "generated_at": iso(p.generated_at),
            }

    for c in Commitment.objects.filter(status="pending").values(
        "person__name"
    ).annotate(n=Count("id")):
        name = c["person__name"]
        if name and name in persons:
            persons[name]["commitments_pending"] = c["n"]

    affect = []
    for pid, mood in emotion_engine.person_moods.items():
        label, intensity = pad.pad_to_label(mood.dynamic.position)
        speed = pad.norm(mood.dynamic.velocity)
        affect.append({
            "person_id": pid,
            "emotion": label.value,
            "intensity": round(intensity, 3),
            "velocity": round(speed, 3),
            "last_interaction": mood.last_interaction,
            "history_size": len(mood.history),
        })

    return JsonResponse({
        "profiles": list(persons.values()),
        "live_affect": affect,
    })


@require_http_methods(["GET"])
def commitments(request):
    from memory.models import Commitment

    limit, offset = paginate(request, default=50)
    status = pick(request, "status")
    qs = Commitment.objects.select_related("person").order_by("status", "-created_at")
    if status:
        qs = qs.filter(status=status)
    total = qs.count()
    rows = [
        {
            "id": c.id,
            "description": c.description,
            "person": c.person.name if c.person_id else None,
            "status": c.status,
            "due_at": iso(c.due_at),
            "created_at": iso(c.created_at),
            "resolved_at": iso(c.resolved_at),
        }
        for c in qs[offset:offset + limit]
    ]
    return JsonResponse({"total": total, "limit": limit, "offset": offset, "rows": rows})
