"""MCP adapter — exposes project management to Claude as tools.

So Mika, during a normal conversation, can say "OK je vais gérer ça
comme un projet" and actually create one via ``create_project``, then
add tasks with ``add_project_task``, check where she's at with
``list_projects`` / ``get_project_details``, etc.

This is not a plugin: the projects subsystem lives in
``backend/projects/`` (models, runner, scheduler, HTTP views). This
file is the thin MCP layer that plugs its tools into the module bus
so Mika can invoke them during a chat turn. The tools are registered
by ``ProjectsConfig.ready()``, not by ``modules.apps``.
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async

from modules.base import BaseModule
from modules.types import (
    ModuleCapability,
    ModuleTool,
    ToolParameter,
    ToolParameterType,
)

logger = logging.getLogger(__name__)


VALID_PRIORITIES = {"low", "normal", "high", "urgent"}
VALID_ORIGINS = {"user", "self"}
VALID_EMOTION_POLICIES = {"off", "muted", "full"}
VALID_TASK_STATUSES = {"todo", "in_progress", "done", "blocked"}


class ProjectToolsModule(BaseModule):
    """Exposes create_project / add_project_task / ... to the LLM."""

    SYSTEM = True

    def __init__(self):
        super().__init__("project_tools")

    async def instantiate(self) -> None:
        logger.info("ProjectTools module ready")

    async def shutdown(self) -> None:
        pass

    def capabilities(self) -> list[ModuleCapability]:
        return [
            ModuleCapability(
                description=(
                    "Gerer des projets (confies par l'utilisateur ou tes propres "
                    "initiatives). Les projets ont un cadre d'execution strict "
                    "(ton, instructions, outils autorises, schedule). Par defaut "
                    "les emotions sont DESACTIVEES pour les projets — ne passe "
                    "en 'full' ou 'muted' que si l'utilisateur le demande."
                ),
                tool_names=[
                    "create_project", "list_projects", "get_project_details",
                    "add_project_task", "update_project_task",
                    "propose_project_action", "update_project",
                ],
            ),
        ]

    def return_tools(self) -> list[ModuleTool]:
        return [
            ModuleTool(
                name="create_project",
                description=(
                    "Créer un nouveau projet. Usage typique : l'utilisateur "
                    "te confie un travail récurrent (mails pro, veille, suivi d'un "
                    "dossier), tu appelles ce tool pour formaliser le cadre. "
                    "IMPORTANT : par défaut emotion_policy='off' (mode pro). "
                    "Ne mets 'full' ou 'muted' que si l'utilisateur a explicitement "
                    "demandé une tonalité émotionnelle."
                ),
                parameters=[
                    ToolParameter(name="title", type=ToolParameterType.STRING,
                                  description="Titre court du projet"),
                    ToolParameter(name="description", type=ToolParameterType.STRING,
                                  description="Description du cadre / objectif",
                                  required=False),
                    ToolParameter(name="tone_directive", type=ToolParameterType.STRING,
                                  description="Ton à utiliser (ex: 'langage soutenu, "
                                              "factuel, pas d'emojis')",
                                  required=False),
                    ToolParameter(name="emotion_policy", type=ToolParameterType.STRING,
                                  description="'off' (défaut) | 'muted' | 'full'",
                                  required=False),
                    ToolParameter(name="instructions", type=ToolParameterType.ARRAY,
                                  description="Consignes positives, liste de strings",
                                  required=False),
                    ToolParameter(name="out_of_scope", type=ToolParameterType.ARRAY,
                                  description="Choses à NE PAS faire, liste de strings",
                                  required=False),
                    ToolParameter(name="requires_approval", type=ToolParameterType.BOOLEAN,
                                  description="True si l'utilisateur doit approuver "
                                              "les actions à effet de bord",
                                  required=False),
                    ToolParameter(name="allowed_modules", type=ToolParameterType.ARRAY,
                                  description="Modules autorisés (ex: ['email', 'files'])",
                                  required=False),
                    ToolParameter(name="resource_paths", type=ToolParameterType.ARRAY,
                                  description="Chemins / dossiers pertinents",
                                  required=False),
                    ToolParameter(name="contacts", type=ToolParameterType.ARRAY,
                                  description="Emails / contacts en scope",
                                  required=False),
                    ToolParameter(name="schedule_rule", type=ToolParameterType.STRING,
                                  description="Règle de récurrence : '' (manuel), "
                                              "'interval:5m', 'cron:0 9 * * MON-FRI', "
                                              "'idle:30m', 'event:email.new'",
                                  required=False),
                    ToolParameter(name="priority", type=ToolParameterType.STRING,
                                  description="'low' | 'normal' (défaut) | 'high' | 'urgent'",
                                  required=False),
                    ToolParameter(name="origin", type=ToolParameterType.STRING,
                                  description="'user' (défaut, si l'utilisateur t'a "
                                              "confié) | 'self' (ta propre initiative)",
                                  required=False),
                    ToolParameter(name="keywords", type=ToolParameterType.ARRAY,
                                  description="Mots-clés pour reconnaître quand "
                                              "l'utilisateur parle du projet",
                                  required=False),
                ],
                handler=self._tool_create,
            ),
            ModuleTool(
                name="list_projects",
                description="Liste les projets actifs avec leur progression.",
                parameters=[],
                handler=self._tool_list,
            ),
            ModuleTool(
                name="get_project_details",
                description="Détail complet d'un projet (tasks, logs récents, "
                            "pending actions).",
                parameters=[
                    ToolParameter(name="project_id", type=ToolParameterType.INTEGER,
                                  description="ID du projet"),
                ],
                handler=self._tool_details,
            ),
            ModuleTool(
                name="add_project_task",
                description="Ajouter une tâche à un projet existant.",
                parameters=[
                    ToolParameter(name="project_id", type=ToolParameterType.INTEGER,
                                  description="ID du projet"),
                    ToolParameter(name="description", type=ToolParameterType.STRING,
                                  description="Ce qu'il y a à faire"),
                    ToolParameter(name="order", type=ToolParameterType.INTEGER,
                                  description="Ordre dans la liste (optionnel)",
                                  required=False),
                ],
                handler=self._tool_add_task,
            ),
            ModuleTool(
                name="update_project_task",
                description="Mettre à jour l'état d'une tâche "
                            "(la passer en cours, la finir, la bloquer).",
                parameters=[
                    ToolParameter(name="task_id", type=ToolParameterType.INTEGER,
                                  description="ID de la tâche"),
                    ToolParameter(name="status", type=ToolParameterType.STRING,
                                  description="'todo' | 'in_progress' | 'done' | 'blocked'"),
                    ToolParameter(name="result", type=ToolParameterType.STRING,
                                  description="Résultat / ce que tu as fait",
                                  required=False),
                    ToolParameter(name="blocked_reason", type=ToolParameterType.STRING,
                                  description="Raison du blocage si status='blocked'",
                                  required=False),
                ],
                handler=self._tool_update_task,
            ),
            ModuleTool(
                name="propose_project_action",
                description=(
                    "Soumettre une action à l'utilisateur pour validation avant "
                    "exécution (e.g. envoyer un mail en son nom)."
                ),
                parameters=[
                    ToolParameter(name="project_id", type=ToolParameterType.INTEGER,
                                  description="ID du projet"),
                    ToolParameter(name="proposal", type=ToolParameterType.STRING,
                                  description="Description humaine de l'action proposée"),
                    ToolParameter(name="payload", type=ToolParameterType.OBJECT,
                                  description="Payload structuré (ex: "
                                              "{\"kind\": \"send_email\", \"to\": \"...\", "
                                              "\"subject\": \"...\", \"body\": \"...\"})"),
                    ToolParameter(name="task_id", type=ToolParameterType.INTEGER,
                                  description="ID de la tâche concernée (optionnel)",
                                  required=False),
                ],
                handler=self._tool_propose_action,
            ),
            ModuleTool(
                name="update_project",
                description="Modifier un champ du projet (pause, tune du ton, "
                            "changement de schedule, etc).",
                parameters=[
                    ToolParameter(name="project_id", type=ToolParameterType.INTEGER,
                                  description="ID du projet"),
                    ToolParameter(name="status", type=ToolParameterType.STRING,
                                  description="'active' | 'paused' | 'completed' | 'abandoned'",
                                  required=False),
                    ToolParameter(name="tone_directive", type=ToolParameterType.STRING,
                                  description="Nouveau ton à utiliser",
                                  required=False),
                    ToolParameter(name="schedule_rule", type=ToolParameterType.STRING,
                                  description="Nouvelle règle de récurrence",
                                  required=False),
                    ToolParameter(name="priority", type=ToolParameterType.STRING,
                                  description="Nouvelle priorité",
                                  required=False),
                ],
                handler=self._tool_update_project,
            ),
        ]

    # ── Handlers ─────────────────────────────────────────────────

    async def _tool_create(self, args: dict) -> dict:
        from django.utils import timezone

        from projects import schedule as sched
        from projects.models import Project

        title = (args.get("title") or "").strip()
        if not title:
            return {"content": [{"type": "text", "text": "Erreur : title obligatoire."}]}

        priority = args.get("priority", "normal")
        if priority not in VALID_PRIORITIES:
            priority = "normal"

        origin = args.get("origin", "user")
        if origin not in VALID_ORIGINS:
            origin = "user"

        ep = args.get("emotion_policy", "off")
        if ep not in VALID_EMOTION_POLICIES:
            ep = "off"

        def _create():
            p = Project.objects.create(
                title=title[:150],
                description=str(args.get("description") or "")[:2000],
                tone_directive=str(args.get("tone_directive") or "")[:2000],
                emotion_policy=ep,
                instructions=list(args.get("instructions") or []),
                out_of_scope=list(args.get("out_of_scope") or []),
                requires_approval=bool(args.get("requires_approval", False)),
                allowed_modules=list(args.get("allowed_modules") or []),
                resource_paths=list(args.get("resource_paths") or []),
                contacts=list(args.get("contacts") or []),
                schedule_rule=str(args.get("schedule_rule") or "")[:120],
                priority=priority,
                origin=origin,
                keywords=list(args.get("keywords") or []),
            )
            if p.schedule_rule:
                try:
                    p.next_run_at = sched.compute_next_run(
                        p.schedule_rule, timezone.now(),
                    )
                    p.save(update_fields=["next_run_at"])
                except Exception:
                    pass
            return p

        try:
            p = await sync_to_async(_create)()
        except Exception as e:
            logger.exception("create_project failed")
            return {"content": [{"type": "text", "text": f"Erreur création: {e}"}]}

        return {
            "content": [{
                "type": "text",
                "text": (
                    f"Projet #{p.pk} créé : {p.title}. "
                    f"Politique émotionnelle : {p.emotion_policy}. "
                    f"Schedule : {p.schedule_rule or 'manuel'}. "
                    f"Approval required : {p.requires_approval}."
                ),
            }]
        }

    async def _tool_list(self, _args: dict) -> dict:
        from projects.models import Project, ProjectTask

        def _load():
            out = []
            for p in Project.objects.filter(
                status=Project.Status.ACTIVE,
            ).order_by("-priority", "-updated_at")[:20]:
                total = ProjectTask.objects.filter(project=p).count()
                done = ProjectTask.objects.filter(
                    project=p, status=ProjectTask.Status.DONE,
                ).count()
                out.append(
                    f"#{p.pk} [{p.priority}] {p.title} "
                    f"({done}/{total} tâches, ep={p.emotion_policy}, "
                    f"schedule={p.schedule_rule or '—'})"
                )
            return out

        lines = await sync_to_async(_load)()
        body = "\n".join(lines) if lines else "(aucun projet actif)"
        return {"content": [{"type": "text", "text": body}]}

    async def _tool_details(self, args: dict) -> dict:
        from projects.models import Project, ProjectLog, ProjectTask

        pid = int(args.get("project_id", 0))

        def _load():
            try:
                p = Project.objects.get(pk=pid)
            except Project.DoesNotExist:
                return None
            tasks = list(
                ProjectTask.objects.filter(project=p).order_by("order", "created_at")
            )
            logs = list(
                ProjectLog.objects.filter(project=p).order_by("-created_at")[:5]
            )
            lines = [
                f"Projet #{p.pk} : {p.title}",
                f"Status : {p.status} | Priority : {p.priority} | "
                f"Emotion policy : {p.emotion_policy}",
                f"Schedule : {p.schedule_rule or 'manuel'} | "
                f"Next run : {p.next_run_at.isoformat() if p.next_run_at else '—'}",
                f"Tone directive : {p.tone_directive or '—'}",
                f"Instructions : {p.instructions}",
                "",
                f"Tâches ({len(tasks)}) :",
            ]
            for t in tasks:
                lines.append(f"  [{t.status}] ({t.id}) {t.description[:100]}")
            lines.append("")
            lines.append("Derniers logs :")
            for lg in logs:
                lines.append(f"  [{lg.action}] {lg.summary[:100]}")
            return "\n".join(lines)

        body = await sync_to_async(_load)()
        if body is None:
            return {"content": [{"type": "text", "text": f"Projet #{pid} introuvable."}]}
        return {"content": [{"type": "text", "text": body}]}

    async def _tool_add_task(self, args: dict) -> dict:
        from projects.models import Project, ProjectTask

        pid = int(args.get("project_id", 0))
        desc = (args.get("description") or "").strip()
        if not desc:
            return {"content": [{"type": "text", "text": "Erreur : description obligatoire."}]}
        order = args.get("order")

        def _add():
            try:
                p = Project.objects.get(pk=pid)
            except Project.DoesNotExist:
                return None
            o = order if isinstance(order, int) else (
                (ProjectTask.objects.filter(project=p)
                 .order_by("-order").values_list("order", flat=True).first() or -1) + 1
            )
            t = ProjectTask.objects.create(
                project=p, description=desc[:2000], order=o,
            )
            return t

        t = await sync_to_async(_add)()
        if t is None:
            return {"content": [{"type": "text", "text": f"Projet #{pid} introuvable."}]}
        return {
            "content": [{
                "type": "text",
                "text": f"Tâche #{t.pk} ajoutée au projet #{pid}.",
            }]
        }

    async def _tool_update_task(self, args: dict) -> dict:
        from django.utils import timezone
        from projects.models import ProjectTask

        tid = int(args.get("task_id", 0))
        status = (args.get("status") or "").strip().lower()
        if status not in VALID_TASK_STATUSES:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Erreur : status doit être parmi {sorted(VALID_TASK_STATUSES)}.",
                }]
            }

        def _upd():
            try:
                t = ProjectTask.objects.get(pk=tid)
            except ProjectTask.DoesNotExist:
                return None
            t.status = status
            if args.get("result"):
                t.result = str(args["result"])[:2000]
            if args.get("blocked_reason"):
                t.blocked_reason = str(args["blocked_reason"])[:500]
            if status == "done" and not t.completed_at:
                t.completed_at = timezone.now()
            t.save()
            return t

        t = await sync_to_async(_upd)()
        if t is None:
            return {"content": [{"type": "text", "text": f"Tâche #{tid} introuvable."}]}
        return {
            "content": [{
                "type": "text",
                "text": f"Tâche #{t.pk} → {t.status}.",
            }]
        }

    async def _tool_propose_action(self, args: dict) -> dict:
        from projects.models import Project, ProjectPendingAction

        pid = int(args.get("project_id", 0))
        proposal = (args.get("proposal") or "").strip()
        payload = args.get("payload") or {}
        task_id = args.get("task_id")
        if not proposal:
            return {"content": [{"type": "text", "text": "Erreur : proposal obligatoire."}]}
        if not isinstance(payload, dict):
            return {"content": [{"type": "text", "text": "Erreur : payload doit être un objet."}]}

        def _create():
            try:
                p = Project.objects.get(pk=pid)
            except Project.DoesNotExist:
                return None
            return ProjectPendingAction.objects.create(
                project=p,
                task_id=task_id if isinstance(task_id, int) else None,
                proposal=proposal[:2000],
                payload=payload,
            )

        pa = await sync_to_async(_create)()
        if pa is None:
            return {"content": [{"type": "text", "text": f"Projet #{pid} introuvable."}]}

        # Ping the frontend
        try:
            from pipeline.broadcast import broadcast_inner_state_update
            await broadcast_inner_state_update()
        except Exception:
            pass

        return {
            "content": [{
                "type": "text",
                "text": (
                    f"Action #{pa.pk} mise en file d'attente pour validation "
                    f"utilisateur : {proposal[:120]}"
                ),
            }]
        }

    async def _tool_update_project(self, args: dict) -> dict:
        from django.utils import timezone
        from projects import schedule as sched
        from projects.models import Project

        pid = int(args.get("project_id", 0))

        def _upd():
            try:
                p = Project.objects.get(pk=pid)
            except Project.DoesNotExist:
                return None
            if args.get("status") in dict(Project.Status.choices):
                p.status = args["status"]
            if args.get("tone_directive") is not None:
                p.tone_directive = str(args["tone_directive"])[:2000]
            if args.get("priority") in VALID_PRIORITIES:
                p.priority = args["priority"]
            if "schedule_rule" in args:
                p.schedule_rule = str(args["schedule_rule"] or "")[:120]
                try:
                    p.next_run_at = sched.compute_next_run(
                        p.schedule_rule, timezone.now(),
                    )
                except Exception:
                    p.next_run_at = None
            p.save()
            return p

        p = await sync_to_async(_upd)()
        if p is None:
            return {"content": [{"type": "text", "text": f"Projet #{pid} introuvable."}]}
        return {
            "content": [{
                "type": "text",
                "text": f"Projet #{p.pk} mis à jour (status={p.status}, priority={p.priority}).",
            }]
        }
