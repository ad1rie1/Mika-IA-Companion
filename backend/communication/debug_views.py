"""Developer-facing endpoints for manually driving the sleep cycle.

These are gated by Django's DEBUG flag so they never expose in prod.
They exist because the natural sleep cycle only triggers after 23h with
15 min of idle — untestable without waiting or system clock tricks.

Endpoints (all at /api/dev/sleep/*):
    POST   phase      body {"phase": "awake"|"light_sleep"|"rem"|"deep_sleep"}
                      Force the observable phase + push a broadcast.
    POST   journal    Trigger a journal write for today (LLM call).
    POST   dream      Trigger a dream generation (LLM call, may noop if
                      fewer than 2 recent souvenirs exist).
    POST   digest     Run the rumination digestion phase now.
    POST   wake       Shortcut: set phase to AWAKE and push broadcast.
    GET    status     Current phase + latest journal + latest dream summary.

None of these touch the eligibility gates — they bypass them on purpose
so you can see the phases play out during the day.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date

from asgiref.sync import async_to_sync, sync_to_async
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


VALID_PHASES = {"awake", "light_sleep", "rem", "deep_sleep"}


def _forbidden_if_not_debug():
    if not settings.DEBUG:
        return JsonResponse(
            {"error": "debug endpoints disabled (DEBUG=False)"},
            status=403,
        )
    return None


@csrf_exempt
@require_http_methods(["POST"])
def force_phase(request):
    """Force a sleep phase. Triggers a WS broadcast so the frontend
    reacts immediately (dim lights, close eyes, etc.)."""
    err = _forbidden_if_not_debug()
    if err:
        return err

    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    phase = (body.get("phase") or "").strip().lower()
    if phase not in VALID_PHASES:
        return JsonResponse(
            {
                "error": f"invalid phase '{phase}'",
                "valid": sorted(VALID_PHASES),
            },
            status=400,
        )

    from memory.sleep import sleep_cycle

    async_to_sync(sleep_cycle._set_phase)(phase)
    return JsonResponse(
        {"ok": True, "phase": sleep_cycle.phase},
    )


@csrf_exempt
@require_http_methods(["POST"])
def force_journal(request):
    """Trigger the light-sleep journal phase right now (today's date).
    Bypasses the once-per-day gate so it can be called repeatedly."""
    err = _forbidden_if_not_debug()
    if err:
        return err

    from memory.sleep import sleep_cycle

    # Reset the per-day guard so we actually re-run the LLM call
    sleep_cycle._last_journal_date = None

    try:
        async_to_sync(sleep_cycle._write_journal_if_due)(date.today())
    except Exception as e:
        logger.exception("Debug journal failed")
        return JsonResponse({"error": str(e)}, status=500)

    # Report what we got
    from memory.models import DailyJournal

    journal = DailyJournal.objects.filter(date=date.today()).first()
    return JsonResponse(
        {
            "ok": True,
            "journal": (
                {
                    "date": journal.date.isoformat(),
                    "narrative": journal.narrative,
                    "dominant_emotion": journal.dominant_emotion,
                    "word_count": journal.word_count,
                }
                if journal
                else None
            ),
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def force_dream(request):
    """Generate a dream right now. Bypasses the probability + per-night
    cap gates. Reports the generated Dream or explains why it did not
    produce one (typically: not enough recent souvenirs)."""
    err = _forbidden_if_not_debug()
    if err:
        return err

    from memory.sleep import sleep_cycle

    # Temporarily bypass probability + cap
    import memory.sleep as sleep_mod

    original_prob = sleep_mod.DREAM_PROBABILITY
    sleep_mod.DREAM_PROBABILITY = 1.0
    saved_count = sleep_cycle._dreams_this_night
    sleep_cycle._dreams_this_night = 0

    try:
        current_night = sleep_cycle._night_of(sleep_mod.datetime.now())
        try:
            async_to_sync(sleep_cycle._maybe_dream)(current_night)
        except Exception as e:
            logger.exception("Debug dream failed")
            return JsonResponse({"error": str(e)}, status=500)
    finally:
        sleep_mod.DREAM_PROBABILITY = original_prob
        # Don't restore saved_count — if we actually dreamt, the new value
        # should stick to respect the cap on subsequent natural calls.

    from memory.models import Dream

    dream = Dream.objects.order_by("-pk").first()
    return JsonResponse(
        {
            "ok": True,
            "dream": (
                {
                    "id": dream.pk,
                    "night_of": dream.night_of.isoformat(),
                    "type": dream.dream_type,
                    "vividness": dream.vividness,
                    "emotion": dream.emotion,
                    "content": dream.content,
                }
                if dream
                else None
            ),
            "reason_if_none": (
                None
                if dream
                else "no dream was produced — check souvenir count (need >= 2 in last 7 days)"
            ),
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def force_digest(request):
    """Run the deep-sleep digestion phase now. Processes ruminations
    older than 2h even if we're in broad daylight."""
    err = _forbidden_if_not_debug()
    if err:
        return err

    from memory.sleep import sleep_cycle

    try:
        processed = async_to_sync(sleep_cycle._digest_ruminations)()
    except Exception as e:
        logger.exception("Debug digest failed")
        return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"ok": True, "processed": processed})


@csrf_exempt
@require_http_methods(["POST"])
def wake_up(request):
    """Shortcut: force AWAKE phase."""
    err = _forbidden_if_not_debug()
    if err:
        return err

    from memory.sleep import SleepPhase, sleep_cycle

    async_to_sync(sleep_cycle._set_phase)(SleepPhase.AWAKE)
    return JsonResponse({"ok": True, "phase": sleep_cycle.phase})


@require_http_methods(["GET"])
def sleep_status(request):
    """Snapshot of sleep state: current phase + today's journal + last
    night's dream. Cheap, no LLM, safe in prod (but we gate anyway)."""
    err = _forbidden_if_not_debug()
    if err:
        return err

    from datetime import timedelta
    from memory.models import DailyJournal, Dream
    from memory.sleep import sleep_cycle

    journal = DailyJournal.objects.filter(date=date.today()).first()
    last_night = date.today() - timedelta(days=1)
    dream = (
        Dream.objects.filter(night_of=last_night).order_by("-vividness").first()
    )

    return JsonResponse(
        {
            "phase": sleep_cycle.phase,
            "dreams_this_night": sleep_cycle._dreams_this_night,
            "last_dream_night": (
                sleep_cycle._last_dream_night.isoformat()
                if sleep_cycle._last_dream_night
                else None
            ),
            "today_journal": (
                {
                    "date": journal.date.isoformat(),
                    "narrative": journal.narrative[:200],
                    "dominant_emotion": journal.dominant_emotion,
                }
                if journal
                else None
            ),
            "last_dream": (
                {
                    "night_of": dream.night_of.isoformat(),
                    "type": dream.dream_type,
                    "vividness": dream.vividness,
                    "content": dream.content[:200],
                    "recalled": dream.recalled_at is not None,
                }
                if dream
                else None
            ),
        }
    )
