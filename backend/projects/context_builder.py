"""Assemble the context for a single Project.advance() tick.

The runner's prompt is *very* different from a conversation prompt:
no emotion, no ruminations, no circadian tone — just the project's
frame + tasks + recent logs + resource scope. The LLM is asked to
produce structured output describing what it did / wants to do next.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)


@dataclass
class ProjectRunContext:
    """Everything a single advance tick needs, assembled."""
    project_id: int
    title: str
    description: str
    tone_directive: str
    instructions: list[str]
    out_of_scope: list[str]
    allowed_modules: list[str]
    resource_paths: list[str]
    contacts: list[str]
    requires_approval: bool
    todo_tasks: list[dict]            # [{id, description, order}, ...]
    in_progress_tasks: list[dict]
    blocked_tasks: list[dict]
    recent_logs: list[dict]           # last 5 logs, most recent first
    pending_actions_count: int
    runs_since_user_input: int


async def build(project_id: int) -> ProjectRunContext | None:
    """Load and serialize everything needed for one runner tick.

    Returns None if the project was deleted or became inactive between
    the caller's scheduling decision and this build call.
    """
    from projects.models import (
        Project,
        ProjectLog,
        ProjectPendingAction,
        ProjectTask,
    )

    try:
        p = await sync_to_async(
            lambda: Project.objects.filter(
                id=project_id, status=Project.Status.ACTIVE,
            ).first()
        )()
    except Exception:
        logger.debug("Project load failed", exc_info=True)
        return None
    if p is None:
        return None

    todos = await sync_to_async(
        lambda: list(
            ProjectTask.objects.filter(
                project=p, status=ProjectTask.Status.TODO,
            ).order_by("order", "created_at").values(
                "id", "description", "order",
            )[:10]
        )
    )()
    in_progress = await sync_to_async(
        lambda: list(
            ProjectTask.objects.filter(
                project=p, status=ProjectTask.Status.IN_PROGRESS,
            ).order_by("order", "created_at").values(
                "id", "description", "order",
            )[:5]
        )
    )()
    blocked = await sync_to_async(
        lambda: list(
            ProjectTask.objects.filter(
                project=p, status=ProjectTask.Status.BLOCKED,
            ).order_by("order", "created_at").values(
                "id", "description", "blocked_reason",
            )[:5]
        )
    )()

    recent_logs = await sync_to_async(
        lambda: list(
            ProjectLog.objects.filter(project=p)
            .order_by("-created_at")
            .values("action", "summary", "created_at")[:5]
        )
    )()

    pending_count = await sync_to_async(
        lambda: ProjectPendingAction.objects.filter(
            project=p, status=ProjectPendingAction.Status.PENDING,
        ).count()
    )()

    return ProjectRunContext(
        project_id=p.id,
        title=p.title,
        description=p.description,
        tone_directive=p.tone_directive,
        instructions=list(p.instructions or []),
        out_of_scope=list(p.out_of_scope or []),
        allowed_modules=list(p.allowed_modules or []),
        resource_paths=list(p.resource_paths or []),
        contacts=list(p.contacts or []),
        requires_approval=p.requires_approval,
        todo_tasks=todos,
        in_progress_tasks=in_progress,
        blocked_tasks=blocked,
        recent_logs=[
            {
                "action": r["action"],
                "summary": r["summary"],
                "when": r["created_at"].isoformat(),
            }
            for r in recent_logs
        ],
        pending_actions_count=pending_count,
        runs_since_user_input=p.runs_since_user_input,
    )


def to_system_prompt(ctx: ProjectRunContext) -> str:
    """Render the ProjectRunContext as a system prompt for the runner."""
    lines: list[str] = [
        f"TU ES EN TRAIN DE FAIRE AVANCER LE PROJET : {ctx.title}",
        "",
        "CADRE DU PROJET :",
        ctx.description or "(pas de description détaillée)",
        "",
    ]
    if ctx.tone_directive:
        lines += ["TON À UTILISER :", ctx.tone_directive, ""]
    if ctx.instructions:
        lines += ["CONSIGNES :"]
        lines += [f"  - {i}" for i in ctx.instructions]
        lines += [""]
    if ctx.out_of_scope:
        lines += ["HORS DE PORTÉE (n'y touche JAMAIS) :"]
        lines += [f"  - {o}" for o in ctx.out_of_scope]
        lines += [""]
    # Périmètre outillé du projet. L'appel du lanceur est une complétion
    # texte pure : aucun outil ne lui est transmis. La liste borne donc ce
    # qu'il peut *proposer*, et ne pas la rendre la laissait invisible du
    # modèle — le champ ne cadrait rien.
    if ctx.allowed_modules:
        lines += [
            "MODULES DANS LE PÉRIMÈTRE (tu ne les appelles pas toi-même ici : "
            "tu peux seulement proposer une action qui les utilise) :",
            "  " + ", ".join(ctx.allowed_modules),
            "",
        ]
    else:
        lines += [
            "MODULES DANS LE PÉRIMÈTRE : aucun. Ce projet n'autorise aucun "
            "outil — limite-toi à faire avancer les tâches.",
            "",
        ]

    if ctx.resource_paths:
        lines += [
            "RESSOURCES :",
            "  " + ", ".join(ctx.resource_paths),
            "",
        ]
    if ctx.contacts:
        lines += [
            "CONTACTS CONCERNÉS :",
            "  " + ", ".join(ctx.contacts),
            "",
        ]

    if ctx.in_progress_tasks:
        lines += ["TÂCHES EN COURS :"]
        for t in ctx.in_progress_tasks:
            lines += [f"  [{t['id']}] {t['description']}"]
        lines += [""]

    if ctx.todo_tasks:
        lines += ["TÂCHES À FAIRE :"]
        for t in ctx.todo_tasks:
            lines += [f"  [{t['id']}] {t['description']}"]
        lines += [""]

    if ctx.blocked_tasks:
        lines += ["TÂCHES BLOQUÉES :"]
        for t in ctx.blocked_tasks:
            lines += [
                f"  [{t['id']}] {t['description']}"
                f"  (raison : {t.get('blocked_reason', '')})"
            ]
        lines += [""]

    if ctx.recent_logs:
        lines += ["DERNIÈRES ACTIONS :"]
        for lg in ctx.recent_logs:
            lines += [f"  - [{lg['action']}] {lg['summary'][:140]}"]
        lines += [""]

    if ctx.pending_actions_count > 0:
        lines += [
            f"⚠ {ctx.pending_actions_count} action(s) en attente de "
            "validation utilisateur — ne re-propose pas la même action.",
            "",
        ]

    if ctx.requires_approval:
        # Aucun outil n'est transmis à cet appel : la file d'attente se
        # remplit par la clé `proposed_action` du JSON de sortie, la seule
        # que le lanceur sache lire (`runner._apply_structured`).
        lines += [
            "IMPORTANT : toute action à effet de bord (envoyer un mail, "
            "écrire un fichier, etc.) doit être soumise à l'utilisateur "
            "via la clé `proposed_action` du JSON de sortie. "
            "N'exécute RIEN directement.",
            "",
        ]

    # « Proposer une action » n'est offert que si le projet exige une
    # validation : ailleurs, la proposition n'a aucune file où atterrir.
    lines += [
        "CE QUE TU DOIS FAIRE MAINTENANT :",
        "  1. Avance d'UNE étape sur ce projet — au choix : marquer une "
        "tâche terminée, en commencer une nouvelle, "
        + ("proposer une action à valider, " if ctx.requires_approval else "")
        + "déclarer un blocage, ou créer de nouvelles tâches.",
        "  2. Termine par un JSON structuré décrivant ce que tu as fait :",
        "",
        "FORMAT DE SORTIE OBLIGATOIRE (la dernière ligne de ta réponse) :",
        "```json",
        "{",
        '  "summary": "phrase courte décrivant l\'action prise",',
        '  "task_updates": [{"id": 12, "status": "done", "result": "..."}],',
        '  "new_tasks": [{"description": "...", "order": 5}],',
    ]
    if ctx.requires_approval:
        lines += [
            '  "proposed_action": {"proposal": "...", "payload": {...}} | null,',
        ]
    lines += [
        '  "report_to_user": "texte à envoyer à l\'utilisateur" | null',
        "}",
        "```",
    ]
    return "\n".join(lines)
