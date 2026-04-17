from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from dashboard.serializers import iso, paginate


@require_http_methods(["GET"])
def narrative(request):
    from memory.models import SelfNarrative

    limit, offset = paginate(request, default=20)
    qs = SelfNarrative.objects.order_by("-created_at")
    total = qs.count()
    rows = [
        {
            "id": n.id,
            "content": n.content,
            "key_themes": n.key_themes,
            "key_people": n.key_people,
            "dominant_mood": n.dominant_mood,
            "confidence": round(n.confidence, 3),
            "source_souvenir_count": n.source_souvenir_count,
            "source_connaissance_count": n.source_connaissance_count,
            "created_at": iso(n.created_at),
        }
        for n in qs[offset:offset + limit]
    ]
    return JsonResponse({"total": total, "limit": limit, "offset": offset, "rows": rows})
