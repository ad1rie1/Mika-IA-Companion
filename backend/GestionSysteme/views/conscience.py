"""Conscience — observations, décisions, planification.

Ce qu'elle a perçu, ce qu'elle en a décidé, ce qu'elle a prévu.

Le journal des décisions reçoit une ligne à **chaque** cycle, quelle qu'en soit
l'issue : à 30 s d'intervalle cela fait ~2 880 lignes par jour. C'est la table
que le balayage de rétention borne en priorité, et c'est pourquoi elle est
paginée serré ici.
"""
from __future__ import annotations

import logging

from django.contrib import messages
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from GestionSysteme import tables
from GestionSysteme.nav import item_for
from GestionSysteme.shell import page_context

logger = logging.getLogger(__name__)


@require_POST
def scheduled_action(request, action_id: int):
    """Résoudre explicitement une tentative ambiguë, sans rejouer son effet ici."""
    from conscience.models import ScheduledAction

    choix = request.POST.get("action")
    if choix not in {"retry", "close"}:
        return HttpResponseBadRequest("Action inconnue.")
    action = get_object_or_404(ScheduledAction, pk=action_id)
    contexte = action.context_data or {}
    borne = parse_datetime(str(contexte.get("reserved_until") or ""))
    maintenant = timezone.now()
    if (action.status != "uncertain"
            or request.POST.get("attempt_token", "") != contexte.get("attempt_token", "")
            or (borne and borne > maintenant)):
        messages.error(request, "Tentative encore en cours ou déjà traitée. Recharge la page.")
    else:
        # Conserver la preuve précédente et la décision humaine. Comparer le
        # contexte entier ferme aussi la course entre deux formulaires ouverts.
        nouveau = {**contexte, "operator_resolution": choix,
                   "operator_resolved_at": maintenant.isoformat()}
        nouveau.pop("attempt_token", None)
        nouveau.pop("reserved_until", None)
        compte = ScheduledAction.objects.filter(
            pk=action.pk, status="uncertain", context_data=contexte,
        ).update(
            status="pending" if choix == "retry" else "cancelled",
            reessayer_le=maintenant if choix == "retry" else None,
            raison_echec="Relance demandée après vérification." if choix == "retry" else "Close après vérification.",
            context_data=nouveau,
        )
        if compte:
            messages.success(request, "Relance planifiée." if choix == "retry" else "Intention close sans réexécution.")
        else:
            messages.error(request, "Cette tentative a déjà été traitée.")
    return redirect("gestionsysteme:conscience-tab", tab="planification")


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

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    search = fs.add(tables.search_filter(request, "q", "Recherche", placeholder="dans le résumé"))
    status = fs.add(tables.select_filter(
        request, "statut", "État",
        [("pending", "en attente"), ("acted", "traitée"),
         ("skipped", "ignorée"), ("failed", "échouée")],
    ))
    category_labels = {Observation.Category.COMMUNICATION: "Communication", Observation.Category.EMOTIONAL: "Émotion",
                       Observation.Category.MEMORY: "Mémoire", Observation.Category.TEMPORAL: "Temps",
                       Observation.Category.EXTERNAL: "Extérieur", Observation.Category.SYSTEM: "Système"}
    category = fs.add(tables.select_filter(request, "categorie", "Catégorie",
        [(value, category_labels.get(value, label)) for value, label in Observation.Category.choices]))

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


#: Les sept issues d'un cycle, en français. Le filtre n'en couvrait que trois,
#: et deux d'entre elles — poursuivre un chantier, en ouvrir un — n'existaient
#: pas encore : un cycle qui fait avancer un travail en silence était
#: indiscernable d'un cycle qui n'a rien fait. « retenue » : elle avait
#: décidé de parler, mais personne à qui, ni personne pour entendre — rien
#: n'a été tenté, ce n'est pas un échec.
_DECISION_FR = {
    "act": "parler",
    "poursuivre": "avancer un chantier",
    "travail_interne": "activité sans diffusion",
    "ouvrir": "ouvrir un chantier",
    "wait": "attendre",
    "skip": "rien à faire",
    "sans_audience": "retenue — personne pour entendre",
    "failed": "échouée",
}
_DECISION_TONS = {
    "act": "ok",
    "poursuivre": "ok",
    "travail_interne": "ok",
    "ouvrir": "ok",
    "failed": "danger",
    "wait": "warn",
    "sans_audience": "warn",
}


def _decisions(request) -> dict:
    from conscience.models import ConscienceLog

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    decision = fs.add(tables.select_filter(
        request, "decision", "Conduite", list(_DECISION_FR.items()),
    ))

    qs = ConscienceLog.objects.order_by("-created_at")
    if decision.value:
        qs = qs.filter(decision=decision.value)

    idle = None
    seuil = None
    try:
        from conscience.engine import conscience_engine
        idle = conscience_engine.get_idle_seconds()
        # Servi par le moteur et non écrit en dur : le gabarit affichait
        # « 0,50 » quoi que dise la configuration, donc l'écran qui existe pour
        # expliquer pourquoi elle se tait pouvait afficher un seuil qui n'est
        # pas celui qu'elle applique.
        seuil = conscience_engine._threshold
    except Exception:
        logger.debug("état du moteur de conscience indisponible", exc_info=True)

    return {
        "filterset": fs,
        "page": tables.paginate(request, qs, per_page=fs.per_page),
        "idle_seconds": idle,
        "act_threshold": seuil,
        "total_logs": ConscienceLog.objects.count(),
        "decision_labels": _DECISION_FR,
        "decision_tones": _DECISION_TONS,
    }


def _scheduled(request) -> dict:
    from django.db.models import Count, Q
    from django.db.models.functions import Greatest, Coalesce
    from django.utils import timezone
    from conscience.models import ScheduledAction

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    status = fs.add(tables.select_filter(request, "statut", "État", [
        ("pending", "En attente"), ("executed", "Exécutée"),
        ("cancelled", "Annulée"), ("failed", "Échouée"), ("uncertain", "À vérifier")], default="pending"))
    search = fs.add(tables.search_filter(request, "q", "Recherche", placeholder="consigne, source"))
    now = timezone.now()
    qs = ScheduledAction.objects.annotate(
        prochaine_tentative=Greatest("scheduled_at", Coalesce("reessayer_le", "scheduled_at")))
    counts = qs.aggregate(
        pending=Count("pk", filter=Q(status="pending")),
        due=Count("pk", filter=Q(status="pending", prochaine_tentative__lte=now)),
        failed=Count("pk", filter=Q(status="failed")),
        uncertain=Count("pk", filter=Q(status="uncertain")),
    )
    if status.value:
        qs = qs.filter(status=status.value)
    if search.value:
        qs = qs.filter(Q(prompt__icontains=search.value) | Q(source__icontains=search.value))
    # Une intention reportée doit apparaître à son prochain essai. L'historique
    # part des événements récents, au lieu d'enfouir le présent après des années.
    qs = qs.order_by("prochaine_tentative", "-priority", "pk") if status.value == "pending" else qs.order_by("-scheduled_at", "-pk")
    return {"filterset": fs, "page": tables.paginate(request, qs, per_page=fs.per_page),
            "scheduled_counts": counts, "now": now,
            "pending_selection": status.value == "pending" and not search.value}
