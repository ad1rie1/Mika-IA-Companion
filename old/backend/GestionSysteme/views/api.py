"""API de gestion : vitaux et schéma public du contrat de panneaux."""
from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from old.backend.GestionSysteme import shell


@require_GET
def vitals(request):
    return JsonResponse(shell.vitals())


@require_GET
def panel_schema(request):
    from old.backend.GestionSysteme.panel_schema import schema
    return JsonResponse(schema(), json_dumps_params={"ensure_ascii": False})
