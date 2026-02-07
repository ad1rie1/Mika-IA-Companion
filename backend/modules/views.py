import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from modules.manager import module_manager

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
async def wake(request):
    """Queue a wake request. The poll loop processes it within poll_interval."""
    body = json.loads(request.body) if request.body else {}
    wake_module = module_manager.get_module("wake")
    if not wake_module:
        return JsonResponse({"error": "Wake module not loaded"}, status=503)

    wake_id = await wake_module.trigger_wake(
        source=body.get("source", "api"),
        prompt=body.get("prompt"),
    )
    return JsonResponse({"status": "queued", "wake_id": wake_id})


@csrf_exempt
@require_POST
async def wake_now(request):
    """Create AND process a wake request immediately."""
    body = json.loads(request.body) if request.body else {}
    wake_module = module_manager.get_module("wake")
    if not wake_module:
        return JsonResponse({"error": "Wake module not loaded"}, status=503)

    wake_id = await wake_module.trigger_wake(
        source=body.get("source", "api"),
        prompt=body.get("prompt"),
    )
    await wake_module._process_pending()
    return JsonResponse({"status": "processed", "wake_id": wake_id})
