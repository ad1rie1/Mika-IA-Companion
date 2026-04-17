from __future__ import annotations

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from dashboard.serializers import iso, paginate


@require_http_methods(["GET"])
def sleep(request):
    from memory.sleep import sleep_cycle
    from memory.models import DailyJournal, Dream

    today = timezone.localdate()
    journal = DailyJournal.objects.filter(date=today).first()
    last_dream = Dream.objects.order_by("-created_at").first()

    return JsonResponse({
        "phase": sleep_cycle.phase,
        "today_journal": (
            {
                "date": journal.date.isoformat(),
                "narrative": journal.narrative,
                "dominant_emotion": journal.dominant_emotion,
                "persons_interacted": journal.persons_interacted,
                "unresolved_at_sleep": journal.unresolved_at_sleep,
                "word_count": journal.word_count,
                "updated_at": iso(journal.updated_at),
            } if journal else None
        ),
        "last_dream": (
            {
                "night_of": last_dream.night_of.isoformat(),
                "content": last_dream.content,
                "dream_type": last_dream.dream_type,
                "vividness": round(last_dream.vividness, 3),
                "emotion": last_dream.emotion,
                "recalled_at": iso(last_dream.recalled_at),
                "created_at": iso(last_dream.created_at),
            } if last_dream else None
        ),
    })


@require_http_methods(["GET"])
def dreams(request):
    from memory.models import Dream

    limit, offset = paginate(request, default=30)
    qs = Dream.objects.order_by("-created_at")
    total = qs.count()
    rows = [
        {
            "id": d.id,
            "night_of": d.night_of.isoformat(),
            "content": d.content,
            "dream_type": d.dream_type,
            "vividness": round(d.vividness, 3),
            "emotion": d.emotion,
            "recalled_at": iso(d.recalled_at),
            "created_at": iso(d.created_at),
        }
        for d in qs[offset:offset + limit]
    ]
    return JsonResponse({"total": total, "limit": limit, "offset": offset, "rows": rows})


@require_http_methods(["GET"])
def journals(request):
    from memory.models import DailyJournal

    limit, offset = paginate(request, default=30)
    qs = DailyJournal.objects.order_by("-date")
    total = qs.count()
    rows = [
        {
            "id": j.id,
            "date": j.date.isoformat(),
            "narrative": j.narrative,
            "dominant_emotion": j.dominant_emotion,
            "persons_interacted": j.persons_interacted,
            "word_count": j.word_count,
            "updated_at": iso(j.updated_at),
        }
        for j in qs[offset:offset + limit]
    ]
    return JsonResponse({"total": total, "limit": limit, "offset": offset, "rows": rows})
