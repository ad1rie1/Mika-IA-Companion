from __future__ import annotations

from django.db.models import Count
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from dashboard.serializers import iso, paginate, pick


@require_http_methods(["GET"])
def persons(request):
    """Paginated list of known persons (server-side {total, limit, offset, rows})."""
    from memory.models import Entity, Commitment

    limit, offset = paginate(request, default=25)
    q = pick(request, "q")

    qs = (
        Entity.objects.filter(entity_type="person")
        .select_related("profile")
        .order_by("-profile__last_interaction_at", "name")
    )
    if q:
        qs = qs.filter(name__icontains=q)
    total = qs.count()

    # Pending commitments per person, in one aggregation (avoids N+1).
    pending = {
        c["person_id"]: c["n"]
        for c in Commitment.objects.filter(status="pending")
        .values("person_id")
        .annotate(n=Count("id"))
    }

    rows = []
    for e in qs[offset:offset + limit]:
        p = getattr(e, "profile", None)
        rows.append({
            "entity_id": e.id,
            "name": e.name,
            "has_profile": p is not None,
            "closeness": p.closeness if p else None,
            "preferred_tone": p.preferred_tone if p else None,
            "interaction_count": p.interaction_count if p else 0,
            "confidence": round(p.confidence, 3) if p else None,
            "last_interaction_at": iso(p.last_interaction_at) if p else None,
            "commitments_pending": pending.get(e.id, 0),
        })

    return JsonResponse({"total": total, "limit": limit, "offset": offset, "rows": rows})


@require_http_methods(["GET"])
def person_detail(request, entity_id):
    """Full detail for one person: profile + pending commitments + live affect (RAM)."""
    from memory.models import Entity, Commitment
    from emotion.engine import emotion_engine
    from emotion import pad

    e = (
        Entity.objects.filter(entity_type="person", id=entity_id)
        .select_related("profile")
        .first()
    )
    if e is None:
        return JsonResponse({"error": "not found"}, status=404)

    p = getattr(e, "profile", None)
    profile = None
    if p is not None:
        profile = {
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

    commitments = [
        {
            "id": c.id,
            "description": c.description,
            "due_at": iso(c.due_at),
            "created_at": iso(c.created_at),
        }
        for c in Commitment.objects.filter(person_id=entity_id, status="pending").order_by(
            "-created_at"
        )
    ]

    # Live affect (RAM): person_id ↔ entity has no FK in the schema. Match
    # only on a stable id-based key (never the display name). None if no match.
    affect = None
    key = str(entity_id)
    for pid, mood in emotion_engine.person_moods.items():
        if pid == key:
            label, intensity = pad.pad_to_label(mood.dynamic.position)
            affect = {
                "person_id": pid,
                "emotion": label.value,
                "intensity": round(intensity, 3),
                "velocity": round(pad.norm(mood.dynamic.velocity), 3),
                "last_interaction": mood.last_interaction,
                "history_size": len(mood.history),
            }
            break

    return JsonResponse({
        "entity_id": e.id,
        "name": e.name,
        "profile": profile,
        "commitments": commitments,
        "affect": affect,
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
