"""Dashboard API — provider introspection (list models, test connection).

Thin dispatcher: every provider implements ``list_models()`` and ``test()``
on itself. This view only looks up the provider class, instantiates it
with the currently-stored credentials (each ``__init__`` reads them from
``config_service``) and forwards the call.

No provider-specific SDK code lives here — that belongs in
``backend/ai/providers/<name>_provider.py``.
"""
from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from ai.router import _PROVIDER_CLASSES

logger = logging.getLogger(__name__)


def _err(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": msg}, status=status)


@require_http_methods(["GET"])
def list_models(request, provider: str):
    """List models available for the given provider, using stored credentials."""
    provider = provider.lower()
    if provider not in _PROVIDER_CLASSES:
        return _err(
            f"Provider inconnu '{provider}'. Disponibles : "
            f"{', '.join(_PROVIDER_CLASSES)}",
            status=404,
        )
    try:
        instance = _PROVIDER_CLASSES[provider]()
        models = async_to_sync(instance.list_models)()
    except ImportError as exc:
        return _err(f"SDK manquant pour {provider} : {exc}", status=500)
    except Exception as exc:
        logger.warning("list_models(%s) failed: %s", provider, exc)
        return _err(f"Impossible de récupérer la liste : {exc}", status=502)
    return JsonResponse({"provider": provider, "models": models})


@require_http_methods(["POST"])
def test_provider(request, provider: str):
    """Ping the provider to confirm credentials + reachability."""
    provider = provider.lower()
    if provider not in _PROVIDER_CLASSES:
        return _err(
            f"Provider inconnu '{provider}'. Disponibles : "
            f"{', '.join(_PROVIDER_CLASSES)}",
            status=404,
        )
    try:
        instance = _PROVIDER_CLASSES[provider]()
        result = async_to_sync(instance.test)()
    except Exception as exc:
        return JsonResponse(
            {"ok": False, "provider": provider, "error": str(exc)},
            status=200,
        )
    return JsonResponse({"provider": provider, **result})
