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
from GestionSysteme.retour import retour_sur
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
    qs = qs.order_by("-priority", "-updated_at", "-pk")

    page = tables.paginate(request, qs, per_page=fs.per_page)
    for project in page.rows:
        project.progress = (project.n_done / project.n_tasks) if project.n_tasks else 0.0

    from configs.runtime import cfg_int
    from projects.runner import RUNS_SINCE_INPUT_CAP
    return {"filterset": fs, "page": page,
            "runs_cap": cfg_int("projects.runs_since_input_cap", RUNS_SINCE_INPUT_CAP, mini=1)}


# ── Création / édition ──────────────────────────────────────────────────

def _project_or_404(project_id: int):
    from projects.models import Project

    project = Project.objects.select_related("owner").filter(pk=project_id).first()
    if project is None:
        raise Http404("Projet introuvable")
    return project


def project_new(request):
    from GestionSysteme.project_forms import ProjectForm

    if request.method == "POST":
        form = ProjectForm(request.POST)
        if form.is_valid():
            projet = form.save()
            messages.success(request, f"Projet « {projet.title} » créé.")
            return redirect("gestionsysteme:project-detail", project_id=projet.pk)
        messages.error(request, "Le formulaire comporte des erreurs.")
    else:
        form = ProjectForm()

    return _render_project_form(request, form, projet=None)


def project_edit(request, project_id: int):
    from GestionSysteme.project_forms import ProjectForm

    projet = _project_or_404(project_id)

    if request.method == "POST":
        form = ProjectForm(request.POST, instance=projet)
        if form.is_valid():
            form.save()
            messages.success(request, "Projet enregistré.")
            return redirect("gestionsysteme:project-detail", project_id=projet.pk)
        messages.error(request, "Le formulaire comporte des erreurs.")
    else:
        form = ProjectForm(instance=projet)

    return _render_project_form(request, form, projet=projet)


def _render_project_form(request, form, *, projet):
    item = item_for("projects")
    ctx = page_context(
        request, item=item, active_key="projects", active_tab="actifs",
        title=(f"Modifier · {projet.title}" if projet else "Nouveau projet"),
        description=(
            "Un projet créé ici a exactement le même statut qu'un projet "
            "que Mika s'est vu confier en conversation."
        ),
    )
    ctx.update({"form": form, "projet": projet})
    return render(request, "gestion/projects/formulaire.html", ctx)


@require_POST
def project_resume(request, project_id: int):
    """Remet à zéro le compteur de passages sans retour humain.

    C'était le seul cadenas sans clé de l'écran : au plafond, la fiche
    affichait « le projet n'avance plus » et n'offrait aucune action, parce
    que ``notify_user_input`` n'était appelée que sur résolution d'une action
    en attente — or un projet ``requires_approval=False``, le défaut, n'en
    produit jamais. Reprendre, c'est exactement ce que l'approbation faisait
    déjà, sans avoir besoin d'une proposition à approuver.
    """
    projet = _project_or_404(project_id)
    _after_user_input(projet.pk)
    messages.success(
        request,
        f"Compteur remis à zéro : « {projet.title} » peut repartir.",
    )
    return _return_project(request, projet)


@require_POST
def project_delete(request, project_id: int):
    projet = _project_or_404(project_id)
    titre = projet.title
    from projects import workspace
    try:
        corbeille = workspace.mettre_en_corbeille(projet.pk, titre)
    except Exception as exc:  # noqa: BLE001 — la fiche part quand même
        logger.warning("Atelier du projet %s non déplacé : %s", projet.pk, exc)
        corbeille = ""
    projet.delete()
    if corbeille:
        messages.success(
            request,
            f"Projet « {titre} » supprimé. Son atelier a été mis en corbeille "
            f"({corbeille}) — rien n'a été effacé.",
        )
    else:
        messages.success(request, f"Projet « {titre} » supprimé.")
    return redirect("gestionsysteme:projects")


# ── Tâches ──────────────────────────────────────────────────────────────

@require_POST
def task_create(request, project_id: int):
    from GestionSysteme.project_forms import ProjectTaskForm
    from projects.models import ProjectTask

    projet = _project_or_404(project_id)
    form = ProjectTaskForm(request.POST)
    if form.is_valid():
        tache = form.save(commit=False)
        tache.project = projet
        if not tache.order:
            dernier = ProjectTask.objects.filter(project=projet).order_by("-order").first()
            tache.order = (dernier.order + 1) if dernier else 1
        tache.save()
        messages.success(request, "Tâche ajoutée.")
    else:
        messages.error(request, _premier_message(form) or "Tâche invalide.")
    return _return_project(request, projet)


@require_POST
def task_update(request, project_id: int, task_id: int):
    from projects.models import ProjectTask

    projet = _project_or_404(project_id)
    tache = ProjectTask.objects.filter(project=projet, pk=task_id).first()
    if tache is None:
        raise Http404("Tâche introuvable")

    action = request.POST.get("action", "")

    if action == "supprimer":
        tache.delete()
        messages.success(request, "Tâche supprimée.")
    elif action == "etat":
        nouvel = request.POST.get("status", "")
        valides = {v for v, _ in ProjectTask.Status.choices}
        if nouvel not in valides:
            messages.error(request, "État de tâche inconnu.")
        else:
            tache.status = nouvel
            if nouvel != ProjectTask.Status.BLOCKED:
                tache.blocked_reason = ""
            tache.save(update_fields=["status", "blocked_reason"])
            messages.success(request, "Tâche mise à jour.")
    else:
        messages.error(request, "Action inconnue.")

    return _return_project(request, projet)


def _return_project(request, project):
    return redirect(retour_sur(
        request, reverse("gestionsysteme:project-detail", args=[project.pk]),
        prefix="/gestion/",
    ))


def _premier_message(form) -> str:
    for champ, erreurs in form.errors.items():
        if erreurs:
            return f"{champ} : {erreurs[0]}"
    return ""


def _lire_atelier(project) -> dict | None:
    """L'état du dossier de travail, ou None s'il n'existe pas encore.

    Sans cet écran, le travail existerait sur disque et resterait invisible :
    c'est exactement l'écart que ce sous-système avait déjà — un code correct
    dans un JSONField que personne ne regardait. Chaque lecture est isolée :
    on ouvre cette page justement quand quelque chose ne va pas.
    """
    from asgiref.sync import async_to_sync

    from projects import workspace

    try:
        atelier = workspace.atelier_existant(project.pk, project.title)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Atelier du projet %s illisible : %s", project.pk, exc)
        return None
    if atelier is None:
        return None

    infos: dict = {"racine": str(atelier.racine)}
    try:
        infos["fichiers"] = atelier.arborescence()
    except Exception as exc:  # noqa: BLE001
        infos["fichiers"] = []
        infos["erreur_fichiers"] = str(exc)
    for cle, appel in (("diff", atelier.git_diff), ("historique", atelier.git_journal)):
        try:
            infos[cle] = async_to_sync(appel)()
        except Exception as exc:  # noqa: BLE001
            infos[cle] = ""
            infos[f"erreur_{cle}"] = str(exc)
    return infos


def project_detail(request, project_id: int):
    from django.db.models import Count, Q
    from projects.models import ProjectLog, ProjectPendingAction, ProjectTask, ProjectPromptHistory
    from configs.runtime import cfg_int
    from projects.runner import RUNS_SINCE_INPUT_CAP

    from GestionSysteme.project_forms import ProjectTaskForm, TASK_STATUSES

    project = _project_or_404(project_id)

    tasks = ProjectTask.objects.filter(project=project)
    counts = tasks.aggregate(total=Count("pk"), done=Count("pk", filter=Q(status="done")),
                             blocked=Count("pk", filter=Q(status="blocked")))
    fs = tables.FilterSet(per_page=25, show_per_page=False, prefix="tasks")
    search = fs.add(tables.search_filter(request, "tache", "Tâche", placeholder="description, résultat"))
    status = fs.add(tables.select_filter(request, "etat_tache", "État", TASK_STATUSES))
    fs.preserve(request, page_param="p_taches")
    if search.value:
        tasks = tasks.filter(Q(description__icontains=search.value) | Q(result__icontains=search.value))
    if status.value:
        tasks = tasks.filter(status=status.value)
    atelier = _lire_atelier(project)
    if atelier is not None:
        atelier["files_page"] = tables.paginate(request, atelier.pop("fichiers"), per_page=25, page_param="p_fichiers")

    item = item_for("projects")
    ctx = page_context(
        request, item=item, active_key="projects", active_tab="actifs",
        title=project.title,
        description=project.description,
    )
    ctx.update({
        "project": project,
        "tasks_page": tables.paginate(request, tasks.order_by("order", "pk"), per_page=25, page_param="p_taches"),
        "task_filters": fs,
        "task_count": counts["total"],
        "blocked_count": counts["blocked"],
        "progress": counts["done"] / counts["total"] if counts["total"] else 0.0,
        "done_count": counts["done"],
        "pending_count": ProjectPendingAction.objects.filter(
            project=project, status="pending",
        ).count(),
        "logs_page": tables.paginate(
            request,
            ProjectLog.objects.filter(project=project).select_related("task").order_by("-created_at", "-pk"),
            per_page=25, page_param="p_journal",
        ),
        "prompts_page": tables.paginate(request,
            ProjectPromptHistory.objects.filter(project=project).defer("system_prompt", "raw_response", "parsed_output", "user_prompt").order_by("-created_at", "-pk"),
            per_page=10, page_param="p_prompts"),
        "task_form": ProjectTaskForm(),
        "task_statuses": TASK_STATUSES,
        "task_status_labels": dict(TASK_STATUSES),
        # Le plafond vient du lanceur : la fiche annonce « n / plafond » et
        # décide d'afficher la reprise, elle n'a pas à en garder sa copie.
        # Lu dans la configuration, pas sur la constante : celle-ci n'est plus
        # que le repli, et une fiche qui annonce « 7 / 10 » pendant que le
        # lanceur s'arrête à 5 se lit comme un projet bloqué sans raison.
        "runs_cap": cfg_int(
            "projects.runs_since_input_cap", RUNS_SINCE_INPUT_CAP, mini=1),
        "atelier": atelier,
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
    qs = _project_filter(request, fs, qs)
    if status.value:
        qs = qs.filter(status=status.value)
    qs = qs.order_by("-created_at", "-pk")

    return {"filterset": fs, "page": tables.paginate(request, qs, per_page=fs.per_page),
            "pending_selection": status.value == "pending",
            "project_selection": any(f.value for f in fs.filters if f.param == "projet")}


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

    # Jamais ``request.POST["retour"]`` tel quel : c'est une redirection
    # ouverte, et le contrôle existe déjà (``GestionSysteme.retour``).
    back = retour_sur(
        request, reverse("gestionsysteme:projects-tab", args=["attente"]),
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
            a_agi, result = _execute_pending_payload(action)
            action.status = (
                ProjectPendingAction.Status.EXECUTED if a_agi
                else ProjectPendingAction.Status.APPROVED
            )
            action.execution_result = str(result)[:2000]
            if a_agi:
                messages.success(request, "Action approuvée et exécutée.")
            else:
                # Approuvée sans exécuteur : le dire, plutôt que d'annoncer
                # une exécution qui n'a pas eu lieu.
                messages.warning(
                    request,
                    f"Action approuvée, mais rien n'a été exécuté : {result}",
                )
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
    from projects.models import ProjectLog

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    action = fs.add(tables.select_filter(
        request, "action", "Action",
        [(v, l) for v, l in ProjectLog.Action.choices],
    ))

    qs = ProjectLog.objects.select_related("project", "task")
    qs = _project_filter(request, fs, qs)
    if action.value:
        qs = qs.filter(action=action.value)
    qs = qs.order_by("-created_at", "-pk")

    return {"filterset": fs, "page": tables.paginate(request, qs, per_page=fs.per_page)}


def _project_filter(request, fs, queryset):
    project = fs.add(tables.search_filter(request, "projet", "Projet", placeholder="titre ou #identifiant"))
    value = project.value
    if not value:
        return queryset
    if value.lstrip("#").isdigit():
        pk = int(value.lstrip("#"))
        return queryset.filter(project_id=pk) if pk < 2**63 else queryset.none()
    return queryset.filter(project__title__icontains=value)
