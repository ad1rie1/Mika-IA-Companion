"""Vues dashboard + routes HTTP de la Forge.

- Une page d'administration « Forge » (Option A générique, onglets) :
  état des modules forgés, journal, stockage. Détail par module en modale.
- Chaque vue déclarée par un module forgé devient une page sidebar
  ``/dashboard/modules/forge/<module>__<vue>/`` — payload assaini
  (aucun HTML brut d'un module forgé n'atteint le navigateur).
- Routes techniques sous ``/api/modules/forge/`` pour piloter les
  modules (list / command / source / logs) depuis curl ou le front.
"""

from __future__ import annotations

import json
import logging

import yaml
from asgiref.sync import sync_to_async
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dashboard.sanitize import STRIPPED_KEYS, sanitize_payload
from modules.types import ModuleRoute, ModuleView, ModuleViewAction

logger = logging.getLogger("module.forge")

MAX_VIEW_PAYLOAD_BYTES = 512 * 1024

# Le même garde-fou s'applique désormais à TOUS les modules (le dashboard le
# pose lui-même) — on réexporte l'implémentation partagée plutôt que d'en
# maintenir deux versions qui peuvent diverger.
_STRIPPED_KEYS = STRIPPED_KEYS
sanitize_view_payload = sanitize_payload


# ── Vues des modules forgés ───────────────────────────────────────


def _make_data_handler(host, module_name: str, view_key: str):
    async def handler(request):
        lm = host._loaded.get(module_name)
        if lm is None:
            return {"error": f"module forgé '{module_name}' non chargé"}
        params = {k: v for k, v in request.GET.items()}
        for int_key in ("page", "limit", "offset"):
            if int_key in params:
                try:
                    params[int_key] = int(params[int_key])
                except ValueError:
                    params.pop(int_key)
        ok, result, error = await host._run_handler(
            lm, f"view_{view_key}", (params,),
            source="view", count_failure=False,
        )
        if not ok:
            return {"error": error}
        return _normalize_view_result(result)
    return handler


def _make_detail_handler(host, module_name: str, view_key: str):
    async def handler(request, item_id: str):
        lm = host._loaded.get(module_name)
        if lm is None:
            return {"error": f"module forgé '{module_name}' non chargé"}
        ok, result, error = await host._run_handler(
            lm, f"view_{view_key}_detail", (str(item_id)[:256],),
            source="view", count_failure=False,
        )
        if not ok:
            return {"error": error}
        if result is None:
            return None
        return _normalize_view_result(result)
    return handler


def _normalize_view_result(result):
    if not isinstance(result, dict):
        result = {"value": result}
    try:
        encoded = json.dumps(result, default=str)
    except (TypeError, ValueError) as exc:
        return {"error": f"payload non sérialisable: {exc}"}
    if len(encoded.encode("utf-8", errors="replace")) > MAX_VIEW_PAYLOAD_BYTES:
        return {"error": "payload de vue trop gros (512 Ko max) — pagine "
                         "avec params['page'] / params['limit']"}
    return sanitize_view_payload(json.loads(encoded))


def _forged_views(host) -> list[ModuleView]:
    views: list[ModuleView] = []
    for lm in host._loaded.values():
        for mv in lm.manifest.views:
            if f"view_{mv.key}" not in lm.handlers:
                continue  # déclarée mais pas implémentée → pas de page morte
            has_detail = f"view_{mv.key}_detail" in lm.handlers
            views.append(ModuleView(
                key=f"{lm.name}__{mv.key}",
                label=f"{lm.manifest.title} · {mv.label}",
                icon=mv.icon,
                order=200 + mv.order,
                id_field=mv.id_field,
                data_handler=_make_data_handler(host, lm.name, mv.key),
                detail_handler=(
                    _make_detail_handler(host, lm.name, mv.key)
                    if has_detail else None
                ),
            ))
    return views


# ── Page d'administration Forge ───────────────────────────────────


def _admin_data_handler(host):
    async def handler(request):
        infos = await sync_to_async(host.module_infos,
                                    thread_sensitive=False)()
        module_rows = [
            {
                "name": i["name"],
                "titre": i.get("title", i["name"]),
                "statut": i["status"],
                "schedule": i.get("schedule") or "—",
                "events": ", ".join(i.get("events") or []) or "—",
                "échecs": i.get("failures", 0),
                "erreur": (i.get("last_error") or i.get("status_detail")
                           or "")[:120],
                "version": i.get("version"),
            }
            for i in infos
        ]
        logs = await sync_to_async(_recent_logs, thread_sensitive=False)(200)
        storage = await sync_to_async(_storage_stats,
                                      thread_sensitive=False)()
        return {
            "tabs": [
                {"key": "modules", "label": "Modules",
                 "columns": [
                     {"key": "name", "label": "Nom"},
                     {"key": "titre", "label": "Titre"},
                     {"key": "statut", "label": "Statut"},
                     {"key": "schedule", "label": "Schedule"},
                     {"key": "events", "label": "Événements"},
                     {"key": "échecs", "label": "Échecs"},
                     {"key": "erreur", "label": "Dernière erreur"},
                     {"key": "version", "label": "v"},
                 ],
                 "rows": module_rows},
                {"key": "journal", "label": "Journal",
                 "columns": [
                     {"key": "quand", "label": "Quand"},
                     {"key": "module", "label": "Module"},
                     {"key": "niveau", "label": "Niveau"},
                     {"key": "source", "label": "Source"},
                     {"key": "message", "label": "Message"},
                 ],
                 "rows": logs},
                {"key": "stockage", "label": "Stockage",
                 "columns": [
                     {"key": "module", "label": "Module"},
                     {"key": "collection", "label": "Collection"},
                     {"key": "lignes", "label": "Lignes"},
                 ],
                 "rows": storage},
            ],
        }
    return handler


def _admin_detail_handler(host):
    async def handler(request, item_id: str):
        name = str(item_id)
        infos = await sync_to_async(host.module_infos,
                                    thread_sensitive=False)()
        info = next((i for i in infos if i["name"] == name), None)
        if info is None:
            return None
        try:
            from modules.plugins.forge import store
            data = await sync_to_async(store.read_module,
                                       thread_sensitive=False)(name)
            manifest_yaml = yaml.safe_dump(
                data["manifest_raw"], allow_unicode=True, sort_keys=False,
            )
            code = data["code"]
        except Exception as exc:
            manifest_yaml, code = f"(illisible: {exc})", ""
        logs = await sync_to_async(_recent_logs,
                                   thread_sensitive=False)(30, name)
        fields = [
            {"key": "name", "label": "Nom", "value": name},
            {"key": "status", "label": "Statut",
             "value": info["status"]
                      + (f" — {info['status_detail']}"
                         if info.get("status_detail") else "")},
            {"key": "schedule", "label": "Schedule",
             "value": info.get("schedule") or "—"},
            {"key": "handlers", "label": "Handlers",
             "value": ", ".join(info.get("handlers") or []) or "—"},
            {"key": "next", "label": "Prochain tick",
             "value": info.get("next_run_at") or "—"},
            {"key": "manifest", "label": "Manifest", "value": manifest_yaml},
            {"key": "code", "label": "module.py",
             "value": code[:4000] + ("…" if len(code) > 4000 else "")},
            {"key": "logs", "label": "Derniers logs",
             "value": "\n".join(f"{r['quand']} [{r['niveau']}/{r['source']}] "
                                f"{r['message']}" for r in logs) or "—"},
        ]
        return {"fields": fields}
    return handler


def _recent_logs(limit: int, name: str | None = None) -> list[dict]:
    from modules.plugins.forge.models import ForgeLog
    qs = ForgeLog.objects.all()
    if name:
        qs = qs.filter(module_name=name)
    rows = qs.order_by("-created_at")[:limit]
    return [
        {
            "quand": r.created_at.strftime("%d/%m %H:%M:%S"),
            "module": r.module_name,
            "niveau": r.level,
            "source": r.source,
            "message": r.message[:200],
        }
        for r in rows
    ]


def _storage_stats() -> list[dict]:
    from django.db.models import Count
    from modules.plugins.forge.models import ForgeRecord
    rows = (
        ForgeRecord.objects.values("module_name", "collection")
        .annotate(n=Count("id"))
        .order_by("module_name", "collection")
    )
    return [
        {"module": r["module_name"], "collection": r["collection"],
         "lignes": r["n"]}
        for r in rows
    ]


def _reload_all_action(host):
    async def handler(request):
        results = {}
        for name in list(host._loaded) + list(host._load_errors):
            outcome = await host.command(name, "reload")
            results[name] = outcome["message"]
        return {"ok": True, "results": results}
    return handler


def build_views(host) -> list[ModuleView]:
    admin = ModuleView(
        key="forge",
        label="Forge",
        icon="⚒",
        order=5,
        id_field="name",
        data_handler=_admin_data_handler(host),
        detail_handler=_admin_detail_handler(host),
        actions=[
            ModuleViewAction(
                key="reload_all",
                label="Tout recharger",
                handler=_reload_all_action(host),
                confirm="Recharger tous les modules forgés ?",
            ),
        ],
    )
    return [admin] + _forged_views(host)


# ── Routes HTTP techniques (/api/modules/forge/…) ─────────────────


def build_routes(host) -> list[ModuleRoute]:

    async def route_list(request):
        infos = await sync_to_async(host.module_infos,
                                    thread_sensitive=False)()
        return JsonResponse({"modules": infos})

    @csrf_exempt
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
        logs = await sync_to_async(_recent_logs,
                                   thread_sensitive=False)(limit, name)
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
