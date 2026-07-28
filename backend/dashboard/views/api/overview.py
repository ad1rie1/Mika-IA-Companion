from __future__ import annotations

from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from dashboard.serializers import iso


@require_http_methods(["GET"])
def overview(request):
    from config.personality import personality
    from emotion.engine import emotion_engine
    from emotion import circadian, pad
    from drives.engine import drive_engine
    from memory.models import (
        Conversation, Message, Souvenir, Connaissance, Theme, Entity,
        PersonProfile, Commitment, SelfNarrative, DailyJournal, Dream,
    )
    from conscience.models import Observation, ConscienceLog, Rumination
    from identity.models import Identity, IdentityClaim
    from projects.models import Project, ProjectPendingAction
    from memory.sleep import sleep_cycle

    g_label, g_intensity = pad.pad_to_label(
        emotion_engine.global_mood.dynamic.position
    )
    drive_engine.update()
    drives_snapshot = {
        k.value: round(s.tension, 3) for k, s in drive_engine.states.items()
    }
    dominant = drive_engine.get_dominant()
    state = circadian.current_state(profile=personality.circadian_profile)

    narrative = SelfNarrative.objects.first()
    now = timezone.now()
    last_24h = now - timedelta(hours=24)

    return JsonResponse({
        "vtuber": {
            "name": personality.name,
            "description": personality.description,
            "language": personality.language,
            "greeting": personality.greeting,
        },
        "timestamp": now.isoformat(),
        "emotion": {
            "global_label": g_label.value,
            "global_intensity": round(g_intensity, 3),
            "default_mood": personality.temperament.default_mood.value,
        },
        "drives": drives_snapshot,
        "dominant_drive": dominant.kind.value if dominant else None,
        "energy": round(drive_engine.energy_level(), 3),
        "circadian": {
            "phase": state.phase.value,
            "hour": state.hour,
            "energy": round(state.energy, 3),
        },
        "sleep_phase": sleep_cycle.phase,
        "counts": {
            "conversations": Conversation.objects.count(),
            "messages": Message.objects.count(),
            "messages_24h": Message.objects.filter(created_at__gte=last_24h).count(),
            "souvenirs": Souvenir.objects.count(),
            "connaissances": Connaissance.objects.filter(is_valid=True).count(),
            "connaissances_invalid": Connaissance.objects.filter(is_valid=False).count(),
            "themes": Theme.objects.count(),
            "entities": Entity.objects.count(),
            "persons": Entity.objects.filter(entity_type="person").count(),
            "person_profiles": PersonProfile.objects.count(),
            "commitments_pending": Commitment.objects.filter(status="pending").count(),
            "observations_pending": Observation.objects.filter(status="pending").count(),
            # A pending identity claim waits on a human, not on a loop: it is
            # deliberately not scored until someone decides, so it badges the
            # sidebar the same way a pending approval does.
            "identity": IdentityClaim.objects.filter(status="pending").count(),
            "identities_bound": Identity.objects.filter(entity__isnull=False).count(),
            "identities_unbound": Identity.objects.filter(entity__isnull=True).count(),
            "ruminations_active": Rumination.objects.filter(status="active").count(),
            "conscience_logs": ConscienceLog.objects.count(),
            "dreams": Dream.objects.count(),
            "journals": DailyJournal.objects.count(),
            "projects_active": Project.objects.filter(status="active").count(),
            "pending_actions": ProjectPendingAction.objects.filter(
                status="pending"
            ).count(),
            "tracked_persons_ram": len(emotion_engine.person_moods),
        },
        "current_narrative": (
            {
                "content": narrative.content,
                "created_at": iso(narrative.created_at),
                "dominant_mood": narrative.dominant_mood,
            } if narrative else None
        ),
    })
