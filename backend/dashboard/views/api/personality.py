from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET"])
def personality(request):
    from config.personality import personality as perso

    t = perso.temperament
    return JsonResponse({
        "name": perso.name,
        "description": perso.description,
        "language": perso.language,
        "greeting": perso.greeting,
        "tone": perso.tone,
        "traits": perso.traits,
        "quirks": perso.quirks,
        "values": perso.values,
        "interests": perso.interests,
        "vulnerabilities": perso.vulnerabilities,
        "speech_patterns": perso.speech_patterns,
        "mood_greetings": perso.mood_greetings,
        "temperament": {
            "volatility": t.volatility,
            "intensity_base": t.intensity_base,
            "recovery_speed": t.recovery_speed,
            "global_bleed": t.global_bleed,
            "default_mood": t.default_mood.value,
        },
    })
