"""System introspection: consolidation history + AI router config.

These are tech-debug views — they surface configuration + background
work the user would otherwise have to tail logs for.
"""
from __future__ import annotations

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from dashboard.serializers import iso, paginate


@require_http_methods(["GET"])
def consolidation(request):
    """Recent ConsolidationLog rows — when the memory consolidator ran
    and what it produced (souvenirs extracted, connaissances built)."""
    from memory.models import ConsolidationLog

    limit, offset = paginate(request, default=50)
    qs = ConsolidationLog.objects.order_by("-ran_at")
    total = qs.count()
    rows = [
        {
            "id": l.id,
            "messages_processed": l.messages_processed,
            "souvenirs_created": l.souvenirs_created,
            "connaissances_created": l.connaissances_created,
            "last_message_id": l.last_message_id,
            "ran_at": iso(l.ran_at),
        }
        for l in qs[offset:offset + limit]
    ]
    return JsonResponse({
        "total": total, "limit": limit, "offset": offset, "rows": rows,
    })


@require_http_methods(["GET"])
def ai_config(request):
    """Effective AI routing: role → provider:model, plus configured
    providers + key presence (no secrets leaked — boolean only)."""
    try:
        from ai.router import ai_router, AIRole
    except Exception as e:
        return JsonResponse({"available": False, "error": str(e)})

    roles = []
    for role in AIRole:
        roles.append({
            "role": role.value,
            "provider": ai_router.get_provider_name(role),
            "model": ai_router.get_model(role),
        })

    providers = {
        "claude": {
            "oauth_configured": bool(getattr(settings, "CLAUDE_OAUTH_TOKEN", "")),
            "api_key_configured": bool(getattr(settings, "ANTHROPIC_API_KEY", "")),
            "default_model": getattr(settings, "CLAUDE_MODEL", ""),
            "light_model": getattr(settings, "CLAUDE_MODEL_LIGHT", ""),
        },
        "openai": {
            "api_key_configured": bool(getattr(settings, "OPENAI_API_KEY", "")),
            "base_url": getattr(settings, "OPENAI_BASE_URL", "") or "(default)",
        },
        "ollama": {
            "base_url": getattr(settings, "OLLAMA_BASE_URL", ""),
        },
    }

    knobs = {
        "AI_CALL_TIMEOUT": getattr(settings, "AI_CALL_TIMEOUT", None),
        "CONSOLIDATION_INTERVAL": getattr(settings, "CONSOLIDATION_INTERVAL", None),
        "CONSCIENCE_DECISION_INTERVAL": getattr(settings, "CONSCIENCE_DECISION_INTERVAL", None),
        "CONSCIENCE_COOLDOWN_SECONDS": getattr(settings, "CONSCIENCE_COOLDOWN_SECONDS", None),
        "CONSCIENCE_ACT_THRESHOLD": getattr(settings, "CONSCIENCE_ACT_THRESHOLD", None),
        "MEMORY_SHORT_TERM_LIMIT": getattr(settings, "MEMORY_SHORT_TERM_LIMIT", None),
        "MEMORY_DECAY_RATE": getattr(settings, "MEMORY_DECAY_RATE", None),
        "EMOTION_DECAY_RATE": getattr(settings, "EMOTION_DECAY_RATE", None),
        "CRON_TICK_INTERVAL": getattr(settings, "CRON_TICK_INTERVAL", None),
        "SLEEP_CYCLE_ENABLED": getattr(settings, "SLEEP_CYCLE_ENABLED", True),
    }

    return JsonResponse({
        "available": True,
        "roles": roles,
        "providers": providers,
        "knobs": knobs,
    })
