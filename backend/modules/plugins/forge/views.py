"""Routes HTTP de la Forge, et exécution des vues déclarées par un module forgé.

- ``build_routes`` monte ``/api/modules/forge/…`` (list / command / source /
  logs) pour piloter les modules depuis curl ou le front.
- ``_make_data_handler`` exécute le handler ``view_<clé>`` d'un module forgé
  et borne sa charge utile. Il est appelé par ``panels.py``, qui en fait une
  page dans l'espace de la Forge.

Les pages d'administration vivaient ici du temps du ``dashboard`` ; elles sont
dans ``panels.py`` depuis, avec la pagination et les filtres que le rendu
serveur permet.
"""

from __future__ import annotations

import json
import logging

from asgiref.sync import sync_to_async
from django.http import JsonResponse

from modules.types import ModuleRoute

logger = logging.getLogger("module.forge")

# Repli de ``forge.max_view_payload_kb`` — même valeur que le ``default``
# déclaré dans ``config_schema.py``.
MAX_VIEW_PAYLOAD_BYTES = 512 * 1024

# ── Vues des modules forgés ───────────────────────────────────────


def _make_data_handler(host, module_name: str, view_key: str, *, page_params=()):
    async def handler(request):
        lm = host._loaded.get(module_name)
        if lm is None:
            return {"error": f"module forgé '{module_name}' non chargé"}
        params = {k: v for k, v in request.GET.items()}
        for key in ("page", *page_params):
            try:
                params[key] = max(1, int(params.get(key, 1)))
            except (TypeError, ValueError):
                params[key] = 1
        try:
            params["per_page"] = max(1, min(200, int(params.get("per_page", 25))))
        except (TypeError, ValueError):
            params["per_page"] = 25
        ok, result, error = await host._run_handler(
            lm, f"view_{view_key}", (params,),
            source="view", count_failure=False,
        )
        if not ok:
            return {"error": error}
        return _normalize_view_result(result)
    return handler


def _normalize_view_result(result):
    from configs.runtime import cfg_int

    if not isinstance(result, dict):
        return {"error": 'La vue doit renvoyer {"version": 2, "blocks": [...]}'}
    try:
        encoded = json.dumps(result, default=str, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        return {"error": f"payload non sérialisable: {exc}"}
    plafond_ko = cfg_int("forge.max_view_payload_kb",
                         MAX_VIEW_PAYLOAD_BYTES // 1024, mini=8, maxi=8192)
    if len(encoded.encode("utf-8", errors="replace")) > plafond_ko * 1024:
        return {"error": f"payload de vue trop gros ({plafond_ko} Ko max) — "
                         "pagine avec params['page'] / params['per_page']"}
    return json.loads(encoded)


# ── Routes HTTP techniques (/api/modules/forge/…) ─────────────────


def build_routes(host) -> list[ModuleRoute]:

    async def route_list(request):
        infos = await sync_to_async(host.module_infos,
                                    thread_sensitive=False)()
        return JsonResponse({"modules": infos})

    async def route_command(request):
        if request.method != "POST":
            return JsonResponse({"error": "POST attendu"}, status=405)
        try:
            body = json.loads(request.body or b"{}")
        except ValueError:
            return JsonResponse({"error": "JSON invalide"}, status=400)
        name = str(body.get("name") or "")
        command = str(body.get("command") or "")
        if command == "erase" and not body.get("confirm"):
            return JsonResponse(
                {"error": 'erase est destructif — ajoute {"confirm": true}'},
                status=400,
            )
        result = await host.command(name, command)
        return JsonResponse(result, status=200 if result["ok"] else 400)

    async def route_source(request):
        name = request.GET.get("name", "")
        from modules.plugins.forge import store
        try:
            data = await sync_to_async(store.read_module,
                                       thread_sensitive=False)(name)
        except store.StoreError as exc:
            return JsonResponse({"error": str(exc)}, status=404)
        versions = await sync_to_async(store.list_versions,
                                       thread_sensitive=False)(name)
        return JsonResponse({
            "name": name,
            "manifest": data["manifest_raw"],
            "code": data["code"],
            "state": data["state"],
            "versions": versions,
        })

    async def route_logs(request):
        name = request.GET.get("name") or None
        try:
            limit = min(int(request.GET.get("limit", 50)), 300)
        except ValueError:
            limit = 50
        logs = await sync_to_async(host._logs_since_all,
                                   thread_sensitive=False)(name, limit)
        return JsonResponse({"logs": logs})

    return [
        ModuleRoute(path="", handler=route_list, method="GET",
                    name="forge_list"),
        ModuleRoute(path="command", handler=route_command, method="POST",
                    name="forge_command"),
        ModuleRoute(path="source", handler=route_source, method="GET",
                    name="forge_source"),
        ModuleRoute(path="logs", handler=route_logs, method="GET",
                    name="forge_logs"),
    ]
