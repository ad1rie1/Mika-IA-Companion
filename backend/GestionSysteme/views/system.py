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

    # L'état du murmure : sans lui, « elle n'a rien à dire » et « le quota est
    # épuisé », « personne n'est connecté » ou « le rôle n'est pas mappé » sont
    # rigoureusement indiscernables depuis l'extérieur — c'est un mécanisme
    # dont le comportement normal est le silence.
    try:
        from conscience.murmure import etat_murmure
        murmure = etat_murmure()
    except Exception:
        logger.exception("état du murmure indisponible")
        murmure = {}

    # Cadence des appels de fond et disjoncteurs, par provider : un chantier
    # qui « attend » et une extraction qui « repasse au tick suivant » sont,
    # sans ce bloc, indiscernables d'un mécanisme qui n'a rien à faire.
    try:
        from ai.router import ai_router
        cadence = ai_router.cadence_stats()
    except Exception:
        logger.exception("cadence des appels de fond indisponible")
        cadence = {"fond": {"providers": [], "roles": []}, "disjoncteurs": []}

    subscriptions = bus.get("subscriptions", [])
    boucles = sorted(_loops_snapshot(), key=lambda b: (not b["en_retard"], b["nom"]))
    failing = sorted([s for s in subscriptions if s.get("failed")], key=lambda s: -s["failed"])
    return {
        "murmure": murmure,
        "fond": cadence["fond"],
        "disjoncteurs": cadence["disjoncteurs"],
        "disjoncteurs_ouverts": [
            d for d in cadence["disjoncteurs"] if d["etat"] != "ferme"
        ],
        "sites_page": tables.paginate(request, sites, per_page=50, page_param="p_sites"),
        "total_events": degradations.total(),
        "distinct_sites": len(sites),
        "bus_emitted": bus.get("emitted", 0),
        "subscriptions_page": tables.paginate(request, subscriptions, per_page=25, page_param="p_bus"),
        "failing_count": len(failing),
        "failing_subscriptions": failing,
        "boucles": boucles,
        "boucles_muettes": [b for b in boucles if b["en_retard"]],
    }


# Une boucle est déclarée en retard bien après sa période : elles ticquent
# entre 1 s et 60 s, et un tick lent ne doit pas allumer la page.
_LOOP_LATE_FACTOR = 10


def _loops_snapshot() -> list[dict]:
    """Chaque boucle de fond avec l'âge de son dernier tick *réussi*.

    Isolé comme le reste de la vue : c'est la page qu'on ouvre parce que
    quelque chose est cassé.
    """
    import time

    try:
        from utils.periodic import active_loops
        loops = active_loops()
    except Exception:
        logger.exception("inventaire des boucles indisponible")
        return []

    now = time.time()
    rows = []
    for loop in loops:
        age = None if loop.last_success_at is None else now - loop.last_success_at
        rows.append({
            "nom": loop.name,
            "running": loop.is_running,
            "interval": loop.interval,
            "age_seconds": age,
            "last_error": loop.last_error,
            "en_retard": bool(
                loop.is_running
                and (age is None or age > _LOOP_LATE_FACTOR * max(loop.interval, 1))
            ),
        })
    return rows


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

    from ai.config_schema import PROVIDERS
    providers = []
    for name, label in PROVIDERS:
        details = []
        if name != "ollama":
            details.append(("Clé d’API", bool(cfg(f"ai.{name}.api_key"))))
        if name in {"ollama", "ollama_cloud"}:
            details.append(("URL de base", cfg(f"ai.{name}.base_url") or "(défaut)"))
        providers.append({"name": label, "details": details})

    models = []
    try:
        models = config_service.list_rows("ai.models", decrypt_secrets=False)
    except Exception:
        logger.debug("liste des modèles déclarés indisponible", exc_info=True)

    fs = tables.FilterSet(show_per_page=False)
    search = fs.add(tables.search_filter(request, "modele", "Modèle", placeholder="nom, fournisseur, identifiant"))
    if search.value:
        models = [m for m in models if search.value.casefold() in " ".join(str(m.get("payload", {}).get(k, "")) for k in ("internal_name", "provider", "model_id")).casefold()]
    return {
        "roles": roles,
        "router_error": "",
        "providers": providers,
        "models_page": tables.paginate(request, models, per_page=25), "model_filters": fs,
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

    # Le cache de prompt, par rôle : la seule mesure qui dise si le préfixe
    # stable est réellement relu d'un tour à l'autre (et donc si le TTL de
    # ``ai.claude.cache_ttl`` convient). Isolé : un agrégat indisponible ne
    # retire pas l'écran des quotas.
    try:
        from ai.router import cache_stats
        cache = cache_stats.snapshot()
    except Exception:
        logger.exception("agrégat du cache de prompt indisponible")
        cache = []

    from projects.models import Project
    projects = sorted(snap.projects.items(), key=lambda entry: (-entry[1]["tokens_month"], entry[0]))
    project_page = tables.paginate(request, projects, per_page=25)
    titles = dict(Project.objects.filter(pk__in=[pid for pid, _ in project_page.rows]).values_list("pk", "title"))
    project_page.rows = [{"pid": pid, "title": titles.get(int(pid)), **usage} for pid, usage in project_page.rows]
    return {
        "available": True,
        "today": snap.today,
        "month": snap.month,
        "roles": snap.roles,
        "projects_page": project_page,
        "limits": snap.limits,
        "cache": cache,
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
