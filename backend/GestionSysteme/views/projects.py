"""Projets — les engagements de travail explicites de Mika.

Rappel qui gouverne l'affichage : un projet a **`emotion_policy = off` par
défaut**. Quand il est actif et correspond au tour en cours, Mika laisse
tomber son étiquette d'émotion, son bloc de variabilité et tout raisonnement
affectif. C'est le mode professionnel — et c'est la première chose que la
page annonce, parce que c'est ce qui surprend.

L'approbation d'une action réutilise l'exécuteur de charge utile existant
(``projects.views._execute_pending_payload``) au lieu de le réimplémenter :
un second chemin d'envoi d'e-mail est exactement la façon dont l'un des deux
se met à diverger, et celui-ci a des effets de bord réels.
"""
from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from GestionSysteme import tables
from GestionSysteme.nav import item_for
from GestionSysteme.shell import page_context

logger = logging.getLogger(__name__)


def projects(request, tab: str | None = None):
    item = item_for("projects")
    current = item.tab(tab)
    ctx = page_context(
        request, item=item, active_key="projects", active_tab=current.key,
    )
    ctx.update({
        "actifs": _active,
        "attente": _pending,
        "journal": _log,
    }[current.key](request))
    return render(request, f"gestion/projects/{current.key}.html", ctx)


# ── Liste ───────────────────────────────────────────────────────────────

def _active(request) -> dict:
    from django.db.models import Count, Q

    from projects.models import Project

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    search = fs.add(tables.search_filter(request, "q", "Recherche", placeholder="titre"))
    status = fs.add(tables.select_filter(
        request, "statut", "État",
        [(v, l) for v, l in Project.Status.choices],
        default="active", all_label="Tous",
    ))

    qs = Project.objects.select_related("owner").annotate(
        n_tasks=Count("tasks", distinct=True),
        n_done=Count("tasks", filter=Q(tasks__status="done"), distinct=True),
        n_blocked=Count("tasks", filter=Q(tasks__status="blocked"), distinct=True),
    )
    if search.value:
        qs = qs.filter(title__icontains=search.value)
    if status.value:
        qs = qs.filter(status=status.value)
    qs = qs.order_by("-priority", "-updated_at")

    page = tables.paginate(request, qs, per_page=fs.per_page)
    for project in page.rows:
        project.progress = (project.n_done / project.n_tasks) if project.n_tasks else 0.0

    return {"filterset": fs, "page": page}


def project_detail(request, project_id: int):
    from projects.models import Project, ProjectLog, ProjectPendingAction, ProjectTask

    project = Project.objects.select_related("owner").filter(pk=project_id).first()
    if project is None:
        raise Http404("Projet introuvable")

    tasks = ProjectTask.objects.filter(project=project).order_by("order", "id")
    done = sum(1 for t in tasks if t.status == "done")

    item = item_for("projects")
    ctx = page_context(
        request, item=item, active_key="projects", active_tab="actifs",
        title=project.title,
        description=project.description or "Engagement de travail.",
    )
    ctx.update({
        "project": project,
        "tasks": tasks,
        "progress": (done / len(tasks)) if tasks else 0.0,
        "done_count": done,
        "pending": ProjectPendingAction.objects.filter(
            project=project, status="pending",
        ).order_by("-created_at"),
        "logs_page": tables.paginate(
            request,
            ProjectLog.objects.filter(project=project).select_related("task"),
            per_page=25,
        ),
    })
    return render(request, "gestion/projects/detail.html", ctx)


# ── Actions en attente ──────────────────────────────────────────────────

def _pending(request) -> dict:
    from projects.models import ProjectPendingAction

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    status = fs.add(tables.select_filter(
        request, "statut", "État",
        [(v, l) for v, l in ProjectPendingAction.Status.choices],
        default="pending", all_label="Tous",
    ))

    qs = ProjectPendingAction.objects.select_related("project", "task")
    if status.value:
        qs = qs.filter(status=status.value)
    qs = qs.order_by("-created_at")

    return {"filterset": fs, "page": tables.paginate(request, qs, per_page=fs.per_page)}


@require_POST
def pending_action(request, action_id: int):
    """Approuver ou rejeter une action proposée par le lanceur de projets."""
    from projects.models import ProjectLog, ProjectPendingAction

    action = (
        ProjectPendingAction.objects.select_related("project")
        .filter(pk=action_id).first()
    )
    if action is None:
        raise Http404("Action introuvable")

    back = request.POST.get("retour") or reverse(
        "gestionsysteme:projects-tab", args=["attente"],
    )

    if action.status != ProjectPendingAction.Status.PENDING:
        messages.error(request, f"Cette action est déjà « {action.status} ».")
        return redirect(back)

    decision = request.POST.get("decision", "")
    note = (request.POST.get("note") or "")[:500]

    if decision == "approuver":
        action.status = ProjectPendingAction.Status.APPROVED
        action.user_note = note
        action.resolved_at = timezone.now()
        action.save()

        # L'exécution de la charge utile n'est PAS réimplémentée ici : c'est
        # elle qui envoie réellement un e-mail. Un envoi qui échoue marque
        # l'action « failed », jamais « exécutée ».
        from projects.views import _execute_pending_payload
        try:
            result = _execute_pending_payload(action)
            action.status = ProjectPendingAction.Status.EXECUTED
            action.execution_result = str(result)[:2000]
            messages.success(request, "Action approuvée et exécutée.")
        except Exception as exc:
            logger.exception("exécution de l'action %s en échec", action_id)
            action.status = ProjectPendingAction.Status.FAILED
            action.execution_result = f"erreur : {exc}"[:2000]
            messages.error(request, f"Approuvée, mais l'exécution a échoué : {exc}")
        action.save()

    elif decision == "rejeter":
        action.status = ProjectPendingAction.Status.REJECTED
        action.user_note = note
        action.resolved_at = timezone.now()
        action.save()
        ProjectLog.objects.create(
            project=action.project,
            action=ProjectLog.Action.REPORTED,
            summary=f"Action rejetée par l'opérateur : {note or 'sans motif'}",
        )
        messages.success(request, "Action rejetée.")

    else:
        messages.error(request, "Décision inconnue.")
        return redirect(back)

    _after_user_input(action.project_id)
    return redirect(back)


def _after_user_input(project_id: int) -> None:
    """Signale au lanceur qu'un humain est intervenu, puis rafraîchit l'IHM.

    Sans le premier appel, ``runs_since_user_input`` continue de grimper et le
    garde-fou finit par geler le projet alors qu'on vient précisément de lui
    répondre. Les deux sont isolés : une notification manquée ne doit pas
    transformer une approbation réussie en erreur affichée.
    """
    try:
        from projects.runner import project_runner
        async_to_sync(project_runner.notify_user_input)(project_id)
    except Exception:
        logger.debug("notification du lanceur impossible", exc_info=True)

    try:
        from pipeline.broadcast import broadcast_inner_state_update
        async_to_sync(broadcast_inner_state_update)()
    except Exception:
        logger.debug("rafraîchissement de l'état interne impossible", exc_info=True)


# ── Journal d'exécution ─────────────────────────────────────────────────

def _log(request) -> dict:
    from projects.models import Project, ProjectLog

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    project = fs.add(tables.select_filter(
        request, "projet", "Projet",
        [(str(p.pk), p.title) for p in Project.objects.order_by("title")[:200]],
    ))
    action = fs.add(tables.select_filter(
        request, "action", "Action",
        [(v, l) for v, l in ProjectLog.Action.choices],
    ))

    qs = ProjectLog.objects.select_related("project", "task")
    if project.value:
        qs = qs.filter(project_id=project.value)
    if action.value:
        qs = qs.filter(action=action.value)
    qs = qs.order_by("-created_at")

    return {"filterset": fs, "page": tables.paginate(request, qs, per_page=fs.per_page)}
