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

    from configs.service import config_service

    providers = {
        "claude": {
            "oauth_configured": bool(config_service.get("ai.claude.oauth_token", default="")),
            "api_key_configured": bool(config_service.get("ai.claude.api_key", default="")),
            "default_model": config_service.get("ai.claude.default_model", default=""),
            "light_model": config_service.get("ai.claude.light_model", default=""),
        },
        "openai": {
            "api_key_configured": bool(config_service.get("ai.openai.api_key", default="")),
            "base_url": config_service.get("ai.openai.base_url", default="") or "(default)",
        },
        "ollama": {
            "base_url": config_service.get("ai.ollama.base_url", default=""),
        },
    }

    knobs = {
        "ai.call_timeout_seconds": config_service.get("ai.call_timeout_seconds", default=None),
        "memory.consolidation_interval": config_service.get("memory.consolidation_interval", default=None),
        "conscience.decision_interval": config_service.get("conscience.decision_interval", default=None),
        "conscience.cooldown_seconds": config_service.get("conscience.cooldown_seconds", default=None),
        "conscience.act_threshold": config_service.get("conscience.act_threshold", default=None),
        "memory.short_term_limit": config_service.get("memory.short_term_limit", default=None),
        "memory.decay_rate": config_service.get("memory.decay_rate", default=None),
        "emotion.decay_rate": config_service.get("emotion.decay_rate", default=None),
        "modules.cron_tick_interval": config_service.get("modules.cron_tick_interval", default=None),
        "SLEEP_CYCLE_ENABLED": getattr(settings, "SLEEP_CYCLE_ENABLED", True),
    }

    return JsonResponse({
        "available": True,
        "roles": roles,
        "providers": providers,
        "knobs": knobs,
    })


@require_http_methods(["GET"])
def health(request):
    """Swallowed failures + event-bus delivery counters.

    The engine degrades rather than crashes on purpose — a background loop
    has no supervisor, and not knowing who someone is must never cost them
    their answer. The cost of that choice is that a partial failure looks
    exactly like normal operation: an empty prompt block, a missing panel
    card, a drive that never relieves. Nobody tails DEBUG logs on a personal
    install.

    So this is the page that answers "is anything quietly broken?". A site
    with a four-figure count and a `first_seen` at boot is a feature that has
    never worked in this process, not a transient.
    """
    from utils.degradation import degradations
    from utils.eventbus import event_bus

    sites = degradations.snapshot()
    bus = event_bus.stats()
    return JsonResponse({
        "degradations": {
            "total_events": degradations.total(),
            "distinct_sites": len(sites),
            "sites": sites,
        },
        "event_bus": {
            "emitted": bus["emitted"],
            "subscriptions": bus["subscriptions"],
            "failing": [s for s in bus["subscriptions"] if s["failed"]],
        },
    })
