from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from dashboard.serializers import iso, paginate, pick


@require_http_methods(["GET"])
def emotion(request):
    from emotion.engine import emotion_engine
    from emotion import pad
    from config.personality import personality

    persons = []
    for pid, mood in emotion_engine.person_moods.items():
        label, intensity = pad.pad_to_label(mood.dynamic.position)
        persons.append({
            "person_id": pid,
            "emotion": label.value,
            "intensity": round(intensity, 3),
            "pad": list(mood.dynamic.position),
            "velocity_magnitude": round(pad.norm(mood.dynamic.velocity), 3),
        })

    return JsonResponse({
        "global": emotion_engine.global_mood.to_dict(),
        "persons": persons,
        "analytics": emotion_engine.get_analytics(),
        "temperament": {
            "default_mood": personality.temperament.default_mood.value,
            "volatility": personality.temperament.volatility,
            "intensity_base": personality.temperament.intensity_base,
            "recovery_speed": personality.temperament.recovery_speed,
            "global_bleed": personality.temperament.global_bleed,
        },
    })


@require_http_methods(["GET"])
def emotion_history(request):
    from memory.models import EmotionSnapshot, EmotionalSummary

    limit, offset = paginate(request, default=60, cap=500)
    person_id = pick(request, "person_id")

    qs = EmotionSnapshot.objects.order_by("-created_at")
    if person_id:
        qs = qs.filter(person_id=person_id)
    total = qs.count()
    snaps = [
        {
            "id": s.id,
            "person_id": s.person_id,
            "primary_emotion": s.primary_emotion,
            "primary_intensity": round(s.primary_intensity, 3),
            "global_emotion": s.global_emotion,
            "global_intensity": round(s.global_intensity, 3),
            "created_at": iso(s.created_at),
        }
        for s in qs[offset:offset + limit]
    ]

    summaries = [
        {
            "person_id": s.person_id,
            "period_type": s.period_type,
            "period_start": s.period_start.isoformat(),
            "dominant_emotion": s.dominant_emotion,
            "dominant_intensity": round(s.dominant_intensity, 3),
            "trend": s.trend,
            "snapshot_count": s.snapshot_count,
        }
        for s in EmotionalSummary.objects.order_by("-period_start")[:30]
    ]

    return JsonResponse({
        "total": total, "limit": limit, "offset": offset,
        "snapshots": snaps, "summaries": summaries,
    })
