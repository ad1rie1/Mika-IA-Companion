"""Système — santé technique, routage IA, quotas, consolidation, journal.

L'onglet **Santé** est le plus important et n'existait quasiment pas avant.

Le moteur avale ses pannes délibérément : une boucle de fond n'a pas de
superviseur, et ne pas savoir qui est quelqu'un ne doit jamais coûter sa
réponse à cette personne. Le prix de ce choix, c'est qu'une panne partielle
devient indiscernable du fonctionnement normal — un bloc de prompt vide parce
que sa requête lève ressemble exactement à un bloc qui n'a rien à dire, et
personne ne suit les journaux DEBUG sur une installation personnelle.

Un site avec un compteur à quatre chiffres et un premier passage à l'heure du
démarrage n'est pas un incident passager : c'est une fonction qui n'a jamais
marché dans ce processus.
"""
from __future__ import annotations

import logging

from django.shortcuts import render

from GestionSysteme import tables
from GestionSysteme.nav import item_for
from GestionSysteme.shell import page_context

logger = logging.getLogger(__name__)


def system(request, tab: str | None = None):
    item = item_for("system")
    current = item.tab(tab)
    ctx = page_context(
        request, item=item, active_key="system", active_tab=current.key,
    )
    ctx.update({
        "sante": _health,
        "routage": _routing,
        "quota": _quota,
        "consolidation": _consolidation,
        "journal-config": _config_log,
    }[current.key](request))
    return render(request, f"gestion/system/{current.key}.html", ctx)


# ── Santé ───────────────────────────────────────────────────────────────

def _health(request) -> dict:
    from utils.degradation import degradations
    from utils.eventbus import event_bus

    sites = sorted(
        degradations.snapshot(), key=lambda s: s.get("count", 0), reverse=True,
    )
    try:
        bus = event_bus.stats()
    except Exception:
        logger.exception("statistiques du bus indisponibles")
        bus = {"emitted": 0, "subscriptions": []}

    subscriptions = bus.get("subscriptions", [])
    return {
        "sites_page": tables.paginate(request, sites, per_page=50),
        "total_events": degradations.total(),
        "distinct_sites": len(sites),
        "bus_emitted": bus.get("emitted", 0),
        "subscriptions": subscriptions,
        "failing": [s for s in subscriptions if s.get("failed")],
    }


# ── Routage IA ──────────────────────────────────────────────────────────

def _routing(request) -> dict:
    """Ce que chaque rôle appelle réellement.

    Un rôle non associé lève ``UnconfiguredRoleError`` au moment de l'appel :
    la page doit le montrer comme un état à corriger, pas planter avec lui.
    """
    from configs.service import config_service

    roles = []
    try:
        from ai.router import AIRole, ai_router
        for role in AIRole:
            entry = {"role": role.value, "provider": "", "model": "", "error": ""}
            try:
                entry["provider"] = ai_router.get_provider_name(role) or ""
                entry["model"] = ai_router.get_model(role) or ""
            except Exception as exc:
                entry["error"] = str(exc)
            roles.append(entry)
    except Exception as exc:
        logger.exception("routeur IA indisponible")
        roles = []
        return {"roles": roles, "router_error": str(exc), "providers": [], "models": []}

    def cfg(key, default=""):
        try:
            return config_service.get(key, default=default)
        except Exception:
            return default

    providers = [
        {
            "name": "claude",
            "details": [
                ("Jeton OAuth", bool(cfg("ai.claude.oauth_token"))),
                ("Clé d'API", bool(cfg("ai.claude.api_key"))),
            ],
        },
        {
            "name": "openai",
            "details": [
                ("Clé d'API", bool(cfg("ai.openai.api_key"))),
                ("URL de base", cfg("ai.openai.base_url") or "(défaut)"),
            ],
        },
        {
            "name": "ollama",
            "details": [("URL de base", cfg("ai.ollama.base_url") or "(défaut)")],
        },
    ]

    models = []
    try:
        models = config_service.list_rows("ai.models", decrypt_secrets=False)
    except Exception:
        logger.debug("liste des modèles déclarés indisponible", exc_info=True)

    return {
        "roles": roles,
        "router_error": "",
        "providers": providers,
        "models": models,
        "unconfigured": [r for r in roles if r["error"] or not r["model"]],
    }


# ── Quotas ──────────────────────────────────────────────────────────────

def _quota(request) -> dict:
    try:
        from ai.quota import quota_tracker
    except Exception:
        return {"available": False}

    try:
        snap = quota_tracker.snapshot()
    except Exception:
        logger.exception("instantané de quota indisponible")
        return {"available": False}

    return {
        "available": True,
        "today": snap.today,
        "month": snap.month,
        "roles": snap.roles,
        "projects": snap.projects,
        "limits": snap.limits,
    }


# ── Consolidation ───────────────────────────────────────────────────────

def _consolidation(request) -> dict:
    from memory.models import ConsolidationLog

    return {"page": tables.paginate(
        request, ConsolidationLog.objects.order_by("-ran_at"),
        per_page=tables.read_per_page(request, default=50),
    )}


# ── Journal de configuration ────────────────────────────────────────────

def _config_log(request) -> dict:
    """Qui a changé quoi, et quand.

    Les valeurs sensibles sont déjà remplacées par un marqueur à l'écriture :
    le journal ne contient jamais un secret en clair, même pour l'opérateur.
    """
    from configs.models import ConfigChangeLog

    fs = tables.FilterSet(per_page=tables.read_per_page(request, default=50))
    key = fs.add(tables.search_filter(
        request, "cle", "Clé", placeholder="ex. ai.claude",
    ))
    action = fs.add(tables.select_filter(
        request, "action", "Action",
        [("set", "écriture"), ("unset", "réinitialisation"),
         ("row_add", "ligne ajoutée"), ("row_update", "ligne modifiée"),
         ("row_delete", "ligne supprimée")],
    ))

    qs = ConfigChangeLog.objects.order_by("-created_at")
    if key.value:
        qs = qs.filter(key__icontains=key.value)
    if action.value:
        qs = qs.filter(action=action.value)

    return {"filterset": fs, "page": tables.paginate(request, qs, per_page=fs.per_page)}
