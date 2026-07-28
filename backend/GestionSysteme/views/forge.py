"""Forge apps — l'espace des mini-modules que Mika écrit elle-même.

Une app forgée est un objet à part entière : elle a un manifeste, du code,
un état, une configuration éditable et ses propres pages. Jusqu'ici ces
quatre choses étaient dispersées, et de la pire manière — la configuration
d'une app atterrissait dans la **Configuration du cœur**, entre les clés
d'API et les seuils de la conscience, sous un intitulé « Forge · <titre> ».
Or ces sections sont créées **à l'exécution**, par du code que Mika écrit :
la page des réglages du système grandissait toute seule, et les réglages
d'une app se lisaient à trois écrans de ses pages.

Ici, la même règle que pour les modules : **une app, un espace**. Sous
``/gestion/forge/<app>/`` on trouve son état, ses commandes, sa
configuration et ses pages, dans une seule sous-navigation. L'espace existe
tant que l'app existe **sur disque** — désactivée ou cassée comprise, ce
qui est précisément le moment où on vient lire ses réglages et son journal.

Rien ici n'exécute quoi que ce soit : les commandes délèguent à
``ForgeModule.command`` et les pages à ``ForgeModule._run_handler``, dans
le bac à sable, avec sa deadline et son disjoncteur.
"""
from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from configs.service import config_service
from GestionSysteme import forms, panels
from GestionSysteme.shell import page_context
from GestionSysteme.views import config as config_view

logger = logging.getLogger(__name__)

FORGE_MODULE = "forge"

# Clés réservées par la coquille : une app ne peut pas nommer une vue ainsi,
# sinon sa page masquerait son état ou ses réglages.
RESERVED = {"etat", "configuration"}

# Commandes proposées dans l'espace, dans l'ordre où on les cherche. Le
# vocabulaire est celui de ``ForgeModule.command`` — la vue n'en invente
# aucune et n'en implémente aucune.
COMMANDES: tuple[tuple[str, str, str], ...] = (
    # (commande, libellé, confirmation)
    ("reload", "Recharger", ""),
    ("enable", "Activer", ""),
    ("disable", "Désactiver", "Arrêter cette app ? Son code et ses données sont conservés."),
    ("rollback", "Version précédente", "Restaurer la version archivée précédente ?"),
    ("reset_storage", "Vider les données", "Supprimer toutes les données stockées par cette app ?"),
    ("erase", "Effacer", "Effacer cette app ? Elle part à la corbeille et ses données sont supprimées."),
)


def config_section_key(app: str) -> str:
    """Clé de la section que la Forge enregistre pour cette app.

    Le préfixe vient de ``views.config``, qui décide ce qui est « du cœur » :
    deux définitions de la même convention, c'est la garantie qu'un jour une
    section d'app réapparaît dans la Configuration du système.
    """
    return f"{config_view.FORGE_SECTION_PREFIX}{app}"


# ── Accès à l'hôte ──────────────────────────────────────────────────────

def _host():
    """L'instance ForgeModule, ou None si le module n'est pas enregistré.

    None n'est pas une erreur : la Forge peut être désactivée. La liste le
    dit alors explicitement plutôt que de rendre une page vide.
    """
    from modules.manager import module_manager
    try:
        return module_manager.get_registered(FORGE_MODULE)
    except Exception:
        logger.exception("hôte Forge inaccessible")
        return None


def _infos(host) -> list[dict]:
    if host is None:
        return []
    try:
        return host.module_infos()
    except Exception:
        logger.exception("état des apps forgées illisible")
        return []


def _app_or_404(host, app: str) -> dict:
    info = next((i for i in _infos(host) if i["name"] == app), None)
    if info is None:
        raise Http404(f"App forgée inconnue : {app}")
    return info


def _panels_for(host, app: str) -> list:
    if host is None:
        return []
    try:
        from modules.plugins.forge.panels import panels_for_app
        return [p for p in panels_for_app(host, app) if p.key not in RESERVED]
    except Exception:
        logger.exception("pages de l'app forgée %s illisibles", app)
        return []


def has_config(app: str) -> bool:
    """L'app déclare-t-elle des réglages ?

    Lu sur le **registre**, pas sur l'instance : une app désactivée garde sa
    section (les valeurs survivent au reload et au disable), et c'est
    justement une app arrêtée qu'on vient reconfigurer.
    """
    from configs.registry import registry
    section = config_section_key(app)
    prefix = f"forge.{app}."
    return any(
        i.section == section or i.key.startswith(prefix)
        for i in registry.all_items()
    )


# ── Liste ───────────────────────────────────────────────────────────────

def forge_apps(request):
    host = _host()
    rows = []
    for info in _infos(host):
        name = info["name"]
        rows.append({
            "name": name,
            "title": info.get("title") or name,
            "status": info.get("status", "?"),
            "status_detail": info.get("status_detail"),
            "enabled": info.get("enabled"),
            "schedule": info.get("schedule") or "",
            "events": info.get("events") or [],
            "version": info.get("version"),
            "failures": int(info.get("failures") or 0),
            "context": info.get("context"),
            "panels": _panels_for(host, name),
            "has_config": has_config(name),
        })
    rows.sort(key=lambda r: str(r["title"]).lower())

    ctx = page_context(
        request,
        active_key="",
        active_space="forge_apps",
        title="Forge apps",
        description=(
            "Les mini-modules que Mika écrit elle-même. Chacun a son espace : "
            "état, configuration et pages au même endroit."
        ),
    )
    ctx.update({"rows": rows, "forge_absent": host is None})
    return render(request, "gestion/forge/liste.html", ctx)


# ── Espace d'une app ────────────────────────────────────────────────────

def _space_context(request, app: str, *, active_panel: str,
                   title: str = "", description: str = ""):
    host = _host()
    info = _app_or_404(host, app)
    ctx = page_context(
        request,
        active_key="",
        active_space="forge_apps",
        title=title or (info.get("title") or app),
        description=description,
    )
    ctx.update({
        "app_name": app,
        "app_label": info.get("title") or app,
        "info": info,
        "panels": _panels_for(host, app),
        "has_config": has_config(app),
        "active_panel": active_panel,
        "host": host,
    })
    return ctx


def forge_app(request, app: str):
    """Accueil de l'espace : l'état de l'app et ses commandes."""
    ctx = _space_context(
        request, app, active_panel="etat",
        description="État, source et journal de cette app.",
    )
    from modules.plugins.forge.panels import blocs_app

    try:
        blocs = blocs_app(ctx["host"], app, ctx["info"])
    except Exception as exc:
        logger.exception("fiche de l'app forgée %s en échec", app)
        blocs = [panels.Note(f"Fiche illisible : {exc}", tone="danger")]

    ctx.update({"blocks": list(panels.iter_blocks(panels.Blocks(items=blocs))),
                "commandes": COMMANDES})
    return render(request, "gestion/forge/espace.html", ctx)


@require_POST
def forge_app_command(request, app: str):
    """enable | disable | reload | rollback | erase | reset_storage.

    La cible est dans l'URL, pas dans une chaîne de requête : le bouton
    « Effacer » doit porter sur l'app dont la page est affichée, sans
    dépendre d'un paramètre qu'un lien partagé pourrait avoir perdu.
    """
    host = _host()
    _app_or_404(host, app)

    commande = request.POST.get("commande", "")
    if commande not in {c for c, _, _ in COMMANDES}:
        messages.error(request, "Commande inconnue.")
        return redirect("gestionsysteme:forge-app", app=app)

    try:
        resultat = async_to_sync(host.command)(app, commande)
    except Exception as exc:
        logger.exception("commande forge %s/%s en échec", app, commande)
        messages.error(request, f"Échec : {exc}")
        return redirect("gestionsysteme:forge-app", app=app)

    message = resultat.get("message") or f"« {commande} » exécuté."
    if resultat.get("ok"):
        messages.success(request, message)
    else:
        messages.error(request, message)

    # Effacée, l'app n'a plus d'espace : le retour se fait sur la liste,
    # sinon le redirect tomberait sur un 404 juste après un succès.
    if commande == "erase" and resultat.get("ok"):
        return redirect("gestionsysteme:forge-apps")
    return redirect("gestionsysteme:forge-app", app=app)


def forge_app_panel(request, app: str, panel: str):
    """Une page déclarée par l'app, exécutée dans le bac à sable."""
    ctx = _space_context(request, app, active_panel=panel)
    found = next((p for p in ctx["panels"] if p.key == panel), None)
    if found is None:
        raise Http404(f"Page inconnue : {app}/{panel}")

    ctx["page_title"] = found.label
    ctx["page_description"] = found.description
    block = panels.run_panel(request, f"forge/{app}", found)
    ctx.update({"panel": found, "blocks": list(panels.iter_blocks(block))})
    return render(request, "gestion/forge/panneau.html", ctx)


# ── Configuration de l'app ──────────────────────────────────────────────

def forge_app_config(request, app: str):
    """Les réglages déclarés par le manifeste de l'app.

    Même moteur de formulaires que le cœur et que les modules : le registre
    décrit les champs, la vue n'en connaît aucun. Une app qui ajoute une clé
    à son manifeste la voit apparaître ici sans qu'aucun code change — c'est
    déjà le cas aujourd'hui, la seule chose qui bouge est *où* elle apparaît.
    """
    section_key = config_section_key(app)
    items = config_view.items_for(section_key)

    if not items:
        ctx = _space_context(request, app, active_panel="configuration",
                             title="Configuration")
        ctx.update({"form": None, "record_lists": [], "section": None})
        return render(request, "gestion/forge/configuration.html", ctx)

    if request.method == "POST":
        form = forms.save_form(request, items, actor=forms.actor_for(request))
        for message in form.errors:
            messages.error(request, message)
        if form.saved:
            messages.success(request, f"{len(form.saved)} réglage(s) enregistré(s).")
        if not form.errors:
            return redirect("gestionsysteme:forge-app-config", app=app)
    else:
        form = forms.build_form(items)

    from configs.registry import registry
    section = next((s for s in registry.sections() if s.key == section_key), None)

    ctx = _space_context(
        request, app, active_panel="configuration", title="Configuration",
        description=(section.description if section else ""),
    )
    ctx.update({
        "form": form,
        "section": section,
        "section_key": section_key,
        "record_lists": _record_lists(section_key, items),
    })
    return render(request, "gestion/forge/configuration.html", ctx)


def _record_lists(section_key: str, items) -> list[dict]:
    """Listes d'objets de l'app, rendues comme celles du cœur.

    Les lignes réutilisent les routes ``config-record-*`` : la section leur
    appartient, donc le contrôle d'appartenance passe, et le retour est
    aiguillé vers cette page par ``config._back_to``.
    """
    out = []
    for item in forms.record_list_items(items):
        try:
            rows = config_service.list_rows(item.key, decrypt_secrets=False)
        except Exception as exc:
            out.append({"item": item, "rows": [], "columns": [], "error": str(exc),
                        "section_key": section_key})
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
            "section_key": section_key,
        })
    return out
