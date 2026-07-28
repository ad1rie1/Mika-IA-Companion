"""Modules — la liste, et l'espace dédié de chacun.

C'est ici que se joue la demande « un truc différent d'aujourd'hui ».

**Avant :** un module qui déclarait des vues obtenait des entrées dispersées
dans le menu global, rendues par un script générique côté navigateur ; sa
configuration était ailleurs, dans la page Configuration ; son état encore
ailleurs, dans « Gestion des modules ». Trois endroits pour un seul objet. Et
une page n'apparaissait que si le module **tournait** — donc les réglages d'un
module en panne étaient inatteignables depuis le menu, précisément quand on en
avait besoin.

**Maintenant :** un module a un **espace**. Sous
``/gestion/modules/<nom>/`` on trouve son état, son cycle de vie, sa
configuration et ses panneaux, dans une seule sous-navigation. L'espace existe
dès que le module est **enregistré**, qu'il tourne ou non.
"""
from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from configs.service import config_service
from GestionSysteme import forms, panels
from GestionSysteme.nav import item_for
from GestionSysteme.shell import page_context
from GestionSysteme.views import config as config_view

logger = logging.getLogger(__name__)

# Clés de panneau réservées par la coquille — un module ne peut pas les
# utiliser, sinon sa page masquerait l'état ou les réglages.
RESERVED = {"etat", "configuration"}


# ── Liste ───────────────────────────────────────────────────────────────

def modules(request):
    from modules.manager import module_manager

    rows = []
    try:
        infos = [i for i in module_manager.list_all() if not i.get("system")]
    except Exception:
        logger.exception("liste des modules indisponible")
        infos = []

    try:
        statuses = {s.name: s for s in module_manager.get_all_status()}
    except Exception:
        statuses = {}
    try:
        capabilities = module_manager.collect_capabilities()
    except Exception:
        capabilities = {}

    for info in infos:
        name = info["name"]
        module = module_manager.get_registered(name)
        status = statuses.get(name)
        try:
            module_panels = panels.panels_for(name)
        except Exception:
            module_panels = []
        rows.append({
            "name": name,
            "label": panels.label_for(name),
            "enabled": info.get("enabled"),
            "running": info.get("running"),
            "available": info.get("available"),
            "has_models": info.get("has_models"),
            "installed_tables": info.get("installed_tables") or [],
            "uptime": getattr(status, "uptime_seconds", 0.0) if status else 0.0,
            "error": getattr(status, "error", None) if status else None,
            "cron_interval": getattr(module, "CRON_INTERVAL", None) if module else None,
            "capabilities": [c.description for c in capabilities.get(name, [])],
            "panels": module_panels,
            "has_config": panels.has_config_section(name),
        })
    rows.sort(key=lambda r: r["label"].lower())

    item = item_for("modules")
    ctx = page_context(request, item=item, active_key="modules")
    ctx.update({
        "rows": rows,
        "tools": _tool_rows(),
    })
    return render(request, "gestion/modules/liste.html", ctx)


def _tool_rows() -> list[dict]:
    """Outils MCP exposés par les modules en marche, attribués à leur source.

    On itère les modules plutôt que d'utiliser la liste agrégée : celle-ci
    perd le lien entre un outil et le module qui l'a déclaré, or c'est
    justement ce qu'on veut lire ici.
    """
    from modules.manager import module_manager

    rows: list[dict] = []
    seen: set[str] = set()
    try:
        infos = module_manager.list_all()
    except Exception:
        return rows
    for info in infos:
        if not info.get("running"):
            continue
        module = module_manager.get_registered(info["name"])
        if module is None:
            continue
        try:
            tools = module.return_tools() or []
        except Exception:
            logger.debug("outils illisibles pour %s", info["name"], exc_info=True)
            continue
        for tool in tools:
            if tool.name in seen:
                continue
            seen.add(tool.name)
            rows.append({
                "name": tool.name,
                "description": tool.description,
                "module": module.name,
                "params": [p.name for p in (tool.parameters or [])],
            })
    rows.sort(key=lambda r: (r["module"], r["name"]))
    return rows


# ── Espace d'un module ──────────────────────────────────────────────────

def _space_or_404(module: str) -> dict:
    from modules.manager import module_manager

    try:
        infos = {i["name"]: i for i in module_manager.list_all()}
    except Exception:
        infos = {}
    info = infos.get(module)
    if info is None or info.get("system"):
        raise Http404(f"Module inconnu : {module}")

    module_panels = panels.panels_for(module)
    status = None
    try:
        status = next(
            (s for s in module_manager.get_all_status() if s.name == module), None,
        )
    except Exception:
        logger.debug("état du module %s indisponible", module, exc_info=True)

    return {
        "module_name": module,
        "module_label": panels.label_for(module),
        "info": info,
        "status": status,
        "panels": [p for p in module_panels if p.key not in RESERVED],
        "has_config": panels.has_config_section(module),
    }


def _space_context(request, module: str, *, active_panel: str, title: str = "", description: str = ""):
    space = _space_or_404(module)
    ctx = page_context(
        request,
        item=None,
        active_key="modules",
        module_space=module,
        title=title or space["module_label"],
        description=description,
    )
    ctx.update(space)
    ctx["active_panel"] = active_panel
    return ctx


def module_space(request, module: str):
    """Page d'accueil de l'espace : l'état du module."""
    ctx = _space_context(
        request, module, active_panel="etat",
        description="État du module, cycle de vie et accès à ses pages.",
    )

    info = ctx["info"]
    status = ctx["status"]
    from modules.manager import module_manager

    instance = module_manager.get_registered(module)
    ctx.update({
        "cron_interval": getattr(instance, "CRON_INTERVAL", None) if instance else None,
        "capabilities": _capabilities(module),
        "tools": [t for t in _tool_rows() if t["module"] == module],
        "uptime": getattr(status, "uptime_seconds", 0.0) if status else 0.0,
        "error": getattr(status, "error", None) if status else None,
        "details": getattr(status, "details", None) if status else None,
        "installed_tables": info.get("installed_tables") or [],
    })
    return render(request, "gestion/modules/espace.html", ctx)


def _capabilities(module: str) -> list[str]:
    from modules.manager import module_manager
    try:
        return [c.description for c in module_manager.collect_capabilities().get(module, [])]
    except Exception:
        return []


def module_panel(request, module: str, panel: str):
    """Un panneau déclaré par le module, ou sa configuration."""
    if panel == "configuration":
        return _module_config(request, module)

    found = panels.find_panel(module, panel)
    if found is None or found.key in RESERVED:
        raise Http404(f"Panneau inconnu : {module}/{panel}")

    ctx = _space_context(
        request, module, active_panel=panel,
        title=found.label, description=found.description,
    )
    block = panels.run_panel(request, module, found)
    ctx.update({
        "panel": found,
        "blocks": list(panels.iter_blocks(block)),
    })
    return render(request, "gestion/modules/panneau.html", ctx)


@require_POST
def module_action(request, module: str, panel: str, action: str):
    found = panels.find_panel(module, panel)
    if found is None:
        raise Http404(f"Panneau inconnu : {module}/{panel}")

    note = panels.run_action(request, module, found, action)
    if note.tone == "danger":
        messages.error(request, note.text)
    elif note.tone == "warn":
        messages.warning(request, note.text)
    else:
        messages.success(request, note.text)

    # Retour sur l'écran exact d'où l'action est partie : la fiche ouverte et
    # les filtres en place sont dans la chaîne de requête, que le formulaire
    # d'action reporte sur son URL.
    cible = reverse("gestionsysteme:module-panel", args=[module, panel])
    encodee = request.GET.urlencode()
    return redirect(f"{cible}?{encodee}" if encodee else cible)


# ── Configuration du module (espace dynamique) ──────────────────────────

def _module_config(request, module: str):
    """Les réglages du module, rendus par le même moteur que le cœur.

    C'est le point de la demande « espace de configuration dynamique » : rien
    ici ne connaît un module en particulier. Le registre décrit les champs, le
    moteur de formulaires les rend, et un module qui déclare une nouvelle clé
    la voit apparaître sans qu'aucune vue ne change.
    """
    section_key = panels.config_section_key(module)
    items = config_view.items_for(section_key)

    if not items:
        ctx = _space_context(
            request, module, active_panel="configuration", title="Configuration",
        )
        ctx.update({"form": None, "record_lists": [], "section": None})
        return render(request, "gestion/modules/configuration.html", ctx)

    if request.method == "POST":
        form = forms.save_form(request, items, actor=forms.actor_for(request))
        for message in form.errors:
            messages.error(request, message)
        if form.saved:
            messages.success(request, f"{len(form.saved)} réglage(s) enregistré(s).")
        if not form.errors:
            return redirect("gestionsysteme:module-panel", module=module, panel="configuration")
    else:
        form = forms.build_form(items)

    from configs.registry import registry
    section = next((s for s in registry.sections() if s.key == section_key), None)

    ctx = _space_context(
        request, module, active_panel="configuration",
        title="Configuration",
        description=(section.description if section else ""),
    )
    ctx.update({
        "form": form,
        "section": section,
        "section_key": section_key,
        "record_lists": _module_record_lists(section_key, items),
    })
    return render(request, "gestion/modules/configuration.html", ctx)


def _module_record_lists(section_key: str, items) -> list[dict]:
    out = []
    for item in forms.record_list_items(items):
        try:
            rows = config_service.list_rows(item.key, decrypt_secrets=False)
        except Exception as exc:
            out.append({"item": item, "rows": [], "columns": [], "error": str(exc)})
            continue
        out.append({
            "item": item,
            "columns": [f.label or f.key for f in item.record.fields],
            "rows": [
                {"row": row, "values": [v for _, v in forms.row_summary(item, row)]}
                for row in rows
            ],
            "error": "",
            "full": item.max_items is not None and len(rows) >= item.max_items,
            # Les lignes réutilisent les routes de configuration : la section
            # est celle du module, donc les contrôles d'appartenance passent.
            "section_key": section_key,
        })
    return out


# ── Cycle de vie ────────────────────────────────────────────────────────

@require_POST
def module_lifecycle(request, module: str):
    """Activer / désactiver / désinstaller.

    La désinstallation supprime les tables du module : elle exige une
    confirmation explicite dans le corps de la requête, pour qu'un clic mal
    routé ne puisse pas l'emporter.
    """
    from modules.manager import module_manager

    action = request.POST.get("action", "")
    back = reverse("gestionsysteme:module-space", args=[module])

    mapping = {"activer": "enable", "desactiver": "disable", "desinstaller": "uninstall"}
    method = mapping.get(action)
    if method is None:
        messages.error(request, "Action inconnue.")
        return redirect(back)

    if method == "uninstall" and request.POST.get("confirmation") != module:
        messages.error(
            request,
            "Désinstallation annulée : le nom du module doit être saisi exactement.",
        )
        return redirect(back)

    try:
        async_to_sync(getattr(module_manager, method))(module)
    except KeyError:
        raise Http404(f"Module inconnu : {module}")
    except Exception as exc:
        logger.exception("%s a échoué pour %s", method, module)
        messages.error(request, f"Échec : {exc}")
        return redirect(back)

    messages.success(request, {
        "enable": "Module activé et démarré.",
        "disable": "Module arrêté et désactivé. Ses tables sont conservées.",
        "uninstall": "Module désinstallé et ses tables supprimées.",
    }[method])
    return redirect(back)
