"""Conscience — observations, décisions, planification.

Ce qu'elle a perçu, ce qu'elle en a décidé, ce qu'elle a prévu.

Le journal des décisions reçoit une ligne à **chaque** cycle, quelle qu'en soit
l'issue : à 30 s d'intervalle cela fait ~2 880 lignes par jour. C'est la table
que le balayage de rétention borne en priorité, et c'est pourquoi elle est
paginée serré ici.
"""
from __future__ import annotations

import logging

from django.shortcuts import render

from GestionSysteme import tables
from GestionSysteme.nav import item_for
from GestionSysteme.shell import page_context

logger = logging.getLogger(__name__)


def conscience(request, tab: str | None = None):
    item = item_for("conscience")
    current = item.tab(tab)
    ctx = page_context(
        request, item=item, active_key="conscience", active_tab=current.key,
    )
    ctx.update({
        "observations": _observations,
        "decisions": _decisions,
        "planification": _scheduled,
    }[current.key](request))
    return render(request, f"gestion/conscience/{current.key}.html", ctx)


def _observations(request) -> dict:
    from conscience.models import Observation

    categories = list(
        Observation.objects.order_by("category")
        .values_list("category", flat=True).distinct()[:50]
    )

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    search = fs.add(tables.search_filter(request, "q", "Recherche", placeholder="dans le résumé"))
    status = fs.add(tables.select_filter(
        request, "statut", "État",
        [("pending", "en attente"), ("acted", "traitée"),
         ("skipped", "ignorée"), ("failed", "échouée")],
    ))
    category = fs.add(tables.select_filter(
        request, "categorie", "Catégorie", [(c, c) for c in categories if c],
    ))

    qs = Observation.objects.order_by("-created_at")
    if search.value:
        qs = qs.filter(summary__icontains=search.value)
    if status.value:
        qs = qs.filter(status=status.value)
    if category.value:
        qs = qs.filter(category=category.value)

    return {
        "filterset": fs,
        "page": tables.paginate(request, qs, per_page=fs.per_page),
        "status_tones": {
            "pending": "warn", "acted": "ok", "skipped": "", "failed": "danger",
        },
    }


def _decisions(request) -> dict:
    from conscience.models import ConscienceLog

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    decision = fs.add(tables.select_filter(
        request, "decision", "Décision", [("act", "agir"), ("wait", "attendre")],
    ))

    qs = ConscienceLog.objects.order_by("-created_at")
    if decision.value:
        qs = qs.filter(decision=decision.value)

    idle = None
    try:
        from conscience.engine import conscience_engine
        idle = conscience_engine.get_idle_seconds()
    except Exception:
        logger.debug("compteur d'inactivité indisponible", exc_info=True)

    return {
        "filterset": fs,
        "page": tables.paginate(request, qs, per_page=fs.per_page),
        "idle_seconds": idle,
        "total_logs": ConscienceLog.objects.count(),
    }


def _scheduled(request) -> dict:
    from conscience.models import ScheduledAction

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    status = fs.add(tables.select_filter(
        request, "statut", "État",
        [("pending", "en attente"), ("executed", "exécutée"),
         ("cancelled", "annulée"), ("failed", "échouée")],
    ))

    qs = ScheduledAction.objects.order_by("scheduled_at")
    if status.value:
        qs = qs.filter(status=status.value)

    return {"filterset": fs, "page": tables.paginate(request, qs, per_page=fs.per_page)}
