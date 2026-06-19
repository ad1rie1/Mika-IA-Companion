from __future__ import annotations

from django.db.models import Count
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from dashboard.serializers import iso, paginate, pick


@require_http_methods(["GET"])
def souvenirs(request):
    from memory.models import Souvenir

    limit, offset = paginate(request, default=50)
    order = request.GET.get("order", "-occurred_at")
    if order not in ("-occurred_at", "-importance", "-created_at"):
        order = "-occurred_at"

    qs = Souvenir.objects.prefetch_related("themes", "entities").order_by(order)
    theme = pick(request, "theme")
    entity = pick(request, "entity")
    if theme:
        qs = qs.filter(themes__name=theme)
    if entity:
        qs = qs.filter(entities__name=entity)
    qs = qs.distinct()

    total = qs.count()
    rows = [
        {
            "id": s.id,
            "content": s.content,
            "emotion": s.emotion,
            "importance": round(s.importance, 3),
            "occurred_at": iso(s.occurred_at),
            "created_at": iso(s.created_at),
            "themes": [t.name for t in s.themes.all()],
            "entities": [
                {"name": e.name, "type": e.entity_type} for e in s.entities.all()
            ],
        }
        for s in qs[offset:offset + limit]
    ]
    return JsonResponse({"total": total, "limit": limit, "offset": offset, "rows": rows})


@require_http_methods(["GET"])
def connaissances(request):
    from memory.models import Connaissance

    limit, offset = paginate(request, default=80)
    include_invalid = request.GET.get("include_invalid") == "1"
    theme = pick(request, "theme")
    entity = pick(request, "entity")

    qs = Connaissance.objects.prefetch_related("themes", "entities")
    if not include_invalid:
        qs = qs.filter(is_valid=True)
    if theme:
        qs = qs.filter(themes__name=theme)
    if entity:
        qs = qs.filter(entities__name=entity)
    qs = qs.distinct().order_by("-confidence", "-updated_at")
    total = qs.count()
    rows = [
        {
            "id": c.id,
            "content": c.content,
            "confidence": round(c.confidence, 3),
            "is_valid": c.is_valid,
            "themes": [t.name for t in c.themes.all()],
            "entities": [
                {"name": e.name, "type": e.entity_type} for e in c.entities.all()
            ],
            "updated_at": iso(c.updated_at),
            "created_at": iso(c.created_at),
        }
        for c in qs[offset:offset + limit]
    ]
    return JsonResponse({"total": total, "limit": limit, "offset": offset, "rows": rows})


@require_http_methods(["GET"])
def themes(request):
    from memory.models import Theme

    limit, offset = paginate(request, default=100)
    qs = (
        Theme.objects
        .annotate(
            souvenir_count=Count("souvenirs", distinct=True),
            connaissance_count=Count("connaissances", distinct=True),
        )
        .order_by("-souvenir_count", "name")
        .values("id", "name", "souvenir_count", "connaissance_count")
    )
    total = qs.count()
    rows = list(qs[offset:offset + limit])
    return JsonResponse({"total": total, "limit": limit, "offset": offset, "rows": rows})


@require_http_methods(["GET"])
def entities(request):
    from memory.models import Entity

    limit, offset = paginate(request, default=100)
    entity_type = pick(request, "type")
    qs = Entity.objects.annotate(
        souvenir_count=Count("souvenirs", distinct=True),
        connaissance_count=Count("connaissances", distinct=True),
    )
    if entity_type:
        qs = qs.filter(entity_type=entity_type)
    qs = qs.order_by("-souvenir_count", "name").values(
        "id", "name", "entity_type", "souvenir_count", "connaissance_count",
    )
    total = qs.count()
    rows = list(qs[offset:offset + limit])
    return JsonResponse({"total": total, "limit": limit, "offset": offset, "rows": rows})


@require_http_methods(["GET"])
def messages(request):
    from memory.models import Message

    limit, offset = paginate(request, default=50, cap=500)
    person_id = pick(request, "person_id")
    conversation_id = pick(request, "conversation_id")
    role = pick(request, "role")

    qs = Message.objects.order_by("-created_at")
    if person_id:
        qs = qs.filter(person_id=person_id)
    if conversation_id:
        qs = qs.filter(conversation_id=conversation_id)
    if role:
        qs = qs.filter(role=role)
    total = qs.count()
    rows = [
        {
            "id": m.id,
            "conversation_id": m.conversation_id,
            "role": m.role,
            "content": m.content,
            "source": m.source,
            "person_id": m.person_id,
            "emotion": m.emotion,
            "emotion_intensity": round(m.emotion_intensity, 3),
            "attachments_meta": m.attachments_meta,
            "created_at": iso(m.created_at),
        }
        for m in qs[offset:offset + limit]
    ]
    return JsonResponse({"total": total, "limit": limit, "offset": offset, "rows": rows})
