"""Dynamic module-view data + action endpoints.

Each running module can declare a list of ``ModuleView`` objects via
``get_views()``. The dashboard mounts them as:

    GET  /dashboard/api/modules/<module>/views                      list views
    GET  /dashboard/api/modules/<module>/views/<view>               JSON data
    GET  /dashboard/api/modules/<module>/views/<view>/items/<id>    per-row detail
    POST /dashboard/api/modules/<module>/views/<view>/actions/<key> side-effect

Handlers are awaited directly (Django 4+ supports async views). Query
params like ``page``, ``limit``, ``q`` are passed through via the
``request`` object — pagination and filtering are the handler's
responsibility.
"""
from __future__ import annotations

import json
import logging

from asgiref.sync import async_to_sync
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from dashboard.sanitize import sanitize_view_result

logger = logging.getLogger(__name__)


def _view_spec(view) -> dict:
    return {
        "key": view.key,
        "label": view.label,
        "icon": view.icon,
        "order": view.order,
        "has_detail": view.detail_handler is not None,
        "id_field": view.id_field,
        "actions": [
            {
                "key": a.key,
                "label": a.label,
                "method": a.method,
                "confirm": a.confirm,
            }
            for a in (view.actions or [])
        ],
    }


@require_http_methods(["GET"])
def list_views(request, module: str):
    from modules.manager import module_manager

    mod = module_manager.get_module(module)
    if not mod or not mod.is_running:
        return JsonResponse(
            {"error": f"Module '{module}' not running"}, status=404,
        )
    views = [_view_spec(v) for v in (mod.get_views() or [])]
    views.sort(key=lambda v: (v["order"], v["label"]))
    return JsonResponse({"module": module, "views": views})


@require_http_methods(["GET"])
def view_data(request, module: str, view_key: str):
    from modules.manager import module_manager

    view = module_manager.get_view(module, view_key)
    if view is None:
        return JsonResponse(
            {"error": f"View '{module}/{view_key}' not found"}, status=404,
        )
    if view.data_handler is None:
        return JsonResponse({})

    try:
        result = async_to_sync(view.data_handler)(request)
    except Exception as exc:
        logger.exception("data_handler failed for %s/%s", module, view_key)
        return JsonResponse(
            {"error": f"data_handler failed: {exc}"}, status=500,
        )

    if isinstance(result, JsonResponse):
        return result
    return JsonResponse(sanitize_view_result(result or {}, view))


@require_http_methods(["GET"])
def view_item(request, module: str, view_key: str, item_id: str):
    from modules.manager import module_manager

    view = module_manager.get_view(module, view_key)
    if view is None:
        return JsonResponse(
            {"error": f"View '{module}/{view_key}' not found"}, status=404,
        )
    if view.detail_handler is None:
        return JsonResponse(
            {"error": f"View '{module}/{view_key}' has no detail_handler"},
            status=404,
        )

    try:
        result = async_to_sync(view.detail_handler)(request, item_id)
    except Exception as exc:
        logger.exception(
            "detail_handler failed for %s/%s id=%s",
            module, view_key, item_id,
        )
        return JsonResponse(
            {"error": f"detail_handler failed: {exc}"}, status=500,
        )

    if isinstance(result, JsonResponse):
        return result
    if result is None:
        return JsonResponse({"error": "not found"}, status=404)
    return JsonResponse(sanitize_view_result(result, view))


@csrf_exempt
def view_action(request, module: str, view_key: str, action_key: str):
    from modules.manager import module_manager

    view = module_manager.get_view(module, view_key)
    if view is None:
        return JsonResponse(
            {"error": f"View '{module}/{view_key}' not found"}, status=404,
        )
    action = next(
        (a for a in (view.actions or []) if a.key == action_key), None,
    )
    if action is None:
        return JsonResponse(
            {"error": f"Action '{action_key}' not found"}, status=404,
        )
    if request.method != action.method:
        return JsonResponse(
            {"error": f"Method not allowed (expected {action.method})"},
            status=405,
        )

    try:
        result = async_to_sync(action.handler)(request)
    except Exception as exc:
        logger.exception(
            "action %s on %s/%s failed", action_key, module, view_key,
        )
        return JsonResponse(
            {"error": f"action failed: {exc}"}, status=500,
        )

    if isinstance(result, JsonResponse):
        return result
    return JsonResponse(result if result is not None else {"ok": True})
