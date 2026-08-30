"""ProjectRunner — advance active projects on schedule or on idle.

Integration: the runner owns its own background loop (started from ASGI
lifespan, cadence ``projects.runner_interval``). Each tick:
  1. Lists projects whose schedule is due
  2. For each, assembles a ProjectRunContext, ouvre l'atelier du projet et
     appelle la BOUCLE D'OUTILS avec la trousse de cet atelier
  3. Parses the structured output, applies task updates, creates
     new tasks, queues pending actions (if `requires_approval`),
     enregistre le travail dans git et records a ProjectLog
  4. Bumps `next_run_at` via ``schedule.compute_next_run``

**Le lanceur agit, il ne décrit plus.** Il appelait ``ai_router.complete`` —
une complétion texte, aucun outil transmis — et son seul canal vers le monde
était ``proposed_action``, dont un seul ``kind`` était câblé (``send_email``).
Un projet logiciel s'arrêtait donc sur du code correct déposé dans un
``JSONField`` que rien n'exécutait. Il tient maintenant une trousse bornée à
l'atelier du projet (voir :mod:`projects.toolkit`), et ``proposed_action``
redevient ce qu'il aurait dû être : le sas de ce qui SORT de la machine.

This is the "silent" Mika — no WS broadcast of her internal thinking,
unless `report_to_user` is produced (then we push a notification).

Bulk-safety: max `MAX_ADVANCES_PER_TICK` projects advanced per call to
avoid LLM bursts if a dozen projects fire at once, et
``MAX_TOOL_TURNS`` tours de boucle d'outils par avance — une boucle qui
tourne en rond consommerait sinon un budget entier sur un seul tick.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from asgiref.sync import sync_to_async
from django.utils import timezone

from ai.chat import ChatPrompt
from ai.quota import QuotaExceeded, current_project_id
from ai.router import AIRole, UnconfiguredRoleError, ai_router
from configs.runtime import cfg_int
from projects import context_builder, schedule, toolkit, workspace
from utils.parsing import strip_markdown_json
from utils.periodic import PeriodicLoop
from utils.degradation import degradations

logger = logging.getLogger(__name__)


# Safety caps. Configurables sous ``projects.*`` ; ces constantes restent le
# repli exact quand le registre est hors d'atteinte.
MAX_ADVANCES_PER_TICK = 3         # at most N advances in a single tick
LLM_TIMEOUT_SECONDS = 90
# Tours de boucle d'outils qu'une avance s'autorise. Le défaut des
# providers est 10 ; lire un fichier avant de l'éditer en coûte déjà deux,
# donc un atelier en demande un peu plus qu'une conversation.
MAX_TOOL_TURNS = 12
RUNS_SINCE_INPUT_CAP = 10         # beyond this, force a pause until user comes back


class ProjectRunner:
    """Singleton driving project advancement."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # Dedicated background loop (since 2026-04): previously piggy-backed
        # on the consolidator's 60s tick, now independent so `interval:30s`
        # schedules actually fire at 30s and a blocked 90s LLM call here
        # never starves memory consolidation.
        self._loop = PeriodicLoop("Project runner", self.tick, interval=30)

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the dedicated runner loop. Idempotent."""
        from configs.service import config_service
        await self._loop.start(
            interval=int(config_service.get("projects.runner_interval", default=30)),
        )

    async def stop(self) -> None:
        """Stop the loop gracefully."""
        await self._loop.stop()

    async def tick(self) -> int:
        """One pass of the scheduler. Returns number of projects advanced.

        Safe to call frequently — cheap when nothing is due.
        """
        if self._lock.locked():
            # A previous tick is still running. Skip silently.
            return 0

        async with self._lock:
            return await self._tick_inner()

    async def advance_now(self, project_id: int) -> bool:
        """Force a single advance tick for one project, bypassing the
        schedule and the due-list. Used by the dashboard 'advance now'
        button. Returns True if the advance succeeded.

        Returns False (without raising) if another tick is in flight, so
        the caller can surface a 'busy, retry' message instead of an error.
        """
        if self._lock.locked():
            return False
        async with self._lock:
            try:
                return await self._advance(project_id)
            except Exception:
                logger.exception("Manual advance failed for id=%s", project_id)
                await self._log_error(project_id, "Exception during manual advance")
                return False
            finally:
                # Une avance manuelle EST une intervention humaine. Le
                # garde-fou compte les passages que personne n'a demandés, et
                # `_bump_next_run` vient d'en compter un de plus : sans cette
                # remise à zéro, appuyer sur le bouton rapprochait le projet
                # du plafond au lieu de l'en éloigner. Inconditionnel — ce qui
                # est constaté ici, c'est le clic, pas la réponse de l'IA.
                await self.notify_user_input(project_id)

    async def _tick_inner(self) -> int:
        due = await self._list_due()
        if not due:
            return 0

        advanced = 0
        plafond = cfg_int(
            "projects.max_advances_per_tick", MAX_ADVANCES_PER_TICK, mini=1,
        )
        for project_id in due[:plafond]:
            try:
                success = await self._advance(project_id)
                if success:
                    advanced += 1
            except Exception:
                logger.exception("Project advance failed for id=%s", project_id)
                await self._log_error(project_id, "Exception during advance")
        return advanced

    # ── Due detection ────────────────────────────────────────────

    async def _list_due(self) -> list[int]:
        """Project IDs that should advance now.

        Combined criteria:
          - Active
          - Either next_run_at <= now (for interval/cron/event) OR rule
            is "idle" with conscience idle >= window
          - Haven't hit the runs_since_user_input cap
        """
        from projects.models import Project

        try:
            projects = await sync_to_async(
                lambda: list(
                    Project.objects.filter(status=Project.Status.ACTIVE)
                )
            )()
        except Exception as exc:
            degradations.record("projects: due query", exc)
            return []

        due_ids: list[int] = []
        cap = cfg_int("projects.runs_since_input_cap", RUNS_SINCE_INPUT_CAP, mini=1)
        for p in projects:
            if p.runs_since_user_input >= cap:
                # Don't spin forever without user feedback
                continue
            try:
                if schedule.is_due(p):
                    due_ids.append(p.id)
            except Exception as exc:
                degradations.record("projects: is_due raised for project", exc)

        # Priority ordering — build an id→priority map once to avoid an
        # O(N) linear scan inside the sort key (was O(N² log N)).
        priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
        priority_by_id = {p.id: p.priority for p in projects}
        due_ids.sort(
            key=lambda pid: priority_order.get(
                priority_by_id.get(pid, "normal"), 2
            )
        )
        return due_ids

    # ── Single advance ───────────────────────────────────────────

    async def _advance(self, project_id: int) -> bool:
        """Run one advance tick for a project. Returns True on success."""
        ctx = await context_builder.build(project_id)
        if ctx is None:
            logger.info("Project %s no longer eligible — skipping", project_id)
            return False

        system_prompt = context_builder.to_system_prompt(ctx)
        # Le rappel doit énumérer exactement les clés que le prompt système
        # déclare : `proposed_action` n'existe que sur un projet qui exige
        # une validation, sinon la proposition n'a pas de file où atterrir.
        cles = (
            "summary / task_updates / new_tasks / proposed_action / report_to_user"
            if ctx.requires_approval
            else "summary / task_updates / new_tasks / report_to_user"
        )
        user_prompt = (
            "Fais avancer le projet d'une étape. Rappel du format de sortie "
            f"obligatoire : termine par un bloc JSON avec {cles}."
        )

        raw = ""
        outcome = "ok"
        started = time.time()
        outils_appeles: list[str] = []

        # L'atelier : un dossier réel, créé à la volée. Un projet qui n'écrit
        # jamais rien n'a jamais de dossier — rien à migrer sur une
        # installation existante.
        atelier = await sync_to_async(workspace.atelier_de)(project_id, ctx.title)
        await atelier.git_initialiser()
        trousse = toolkit.construire_trousse(
            atelier, commande_de_test=ctx.test_command,
        )

        # Attribute this LLM call to the project so the quota tracker
        # charges `Project.monthly_token_budget`.
        token = current_project_id.set(project_id)
        try:
            raw, outils_appeles = await asyncio.wait_for(
                ai_router.chat_with_tools(
                    role=self._role_de_travail(),
                    prompt=ChatPrompt(
                        # Le cadre d'un projet ne bouge pas d'un tick à
                        # l'autre ; l'état du chantier, si. Les séparer fait
                        # tomber le cadre du bon côté du point de césure du
                        # cache, gratuitement.
                        system_stable=system_prompt,
                        message=user_prompt,
                    ),
                    tools=trousse,
                    max_turns=cfg_int(
                        "projects.max_tool_turns_per_advance",
                        MAX_TOOL_TURNS, mini=1,
                    ),
                ),
                timeout=cfg_int(
                    "projects.llm_timeout_seconds", LLM_TIMEOUT_SECONDS, mini=1,
                ),
            )
        except QuotaExceeded as qe:
            logger.warning(
                "Project %s: quota dépassé — %s. Pause du prochain run.",
                project_id, qe,
            )
            await self._save_prompt_history(
                project_id=project_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_response="",
                parsed_output=None,
                outcome="quota_exceeded",
                duration_ms=int((time.time() - started) * 1000),
            )
            await self._log_error(project_id, f"Quota atteint: {qe}")
            await self._bump_next_run(project_id)
            return False
        except asyncio.TimeoutError:
            logger.warning("Project %s: LLM timed out", project_id)
            outcome = "timeout"
            await self._save_prompt_history(
                project_id=project_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_response="",
                parsed_output=None,
                outcome=outcome,
                duration_ms=int((time.time() - started) * 1000),
            )
            await self._log_error(project_id, "LLM timeout")
            await self._bump_next_run(project_id)
            return False
        except UnconfiguredRoleError as exc:
            logger.warning(
                "Project %s: avance ignorée — IA non configurée: %s",
                project_id, exc,
            )
            await self._save_prompt_history(
                project_id=project_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_response="",
                parsed_output=None,
                outcome="error",
                duration_ms=int((time.time() - started) * 1000),
            )
            await self._log_error(project_id, f"IA non configurée: {exc}")
            await self._bump_next_run(project_id)
            return False
        except Exception:
            logger.exception("Project %s: LLM call failed", project_id)
            outcome = "error"
            await self._save_prompt_history(
                project_id=project_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_response="",
                parsed_output=None,
                outcome=outcome,
                duration_ms=int((time.time() - started) * 1000),
            )
            await self._log_error(project_id, "LLM call failed")
            await self._bump_next_run(project_id)
            return False
        finally:
            current_project_id.reset(token)

        duration_ms = int((time.time() - started) * 1000)

        if not raw or not raw.strip():
            await self._save_prompt_history(
                project_id=project_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_response="",
                parsed_output=None,
                outcome="empty",
                duration_ms=duration_ms,
            )
            await self._log_error(project_id, "LLM returned empty response")
            await self._bump_next_run(project_id)
            return False

        structured = _extract_json_tail(raw)
        if structured is None:
            # LLM didn't follow the JSON contract — still record what it said
            logger.warning(
                "Project %s: no JSON in LLM output, logging raw", project_id,
            )
            await self._save_prompt_history(
                project_id=project_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_response=raw,
                parsed_output=None,
                outcome="json_miss",
                duration_ms=duration_ms,
            )
            await self._record_log(
                project_id,
                action="advanced",
                summary=raw.strip()[:500],
            )
            await self._bump_next_run(project_id)
            return True

        await self._save_prompt_history(
            project_id=project_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            raw_response=raw,
            parsed_output=structured,
            outcome="ok",
            duration_ms=duration_ms,
        )
        await self._apply_structured(ctx, structured, raw=raw)
        await self._enregistrer_le_travail(
            atelier, structured.get("summary") or "travail", outils_appeles,
        )
        await self._bump_next_run(project_id)
        return True

    @staticmethod
    def _role_de_travail() -> AIRole:
        """``PROJECT_WORK`` s'il est mappé, sinon celui d'avant.

        Le lanceur empruntait ``MEMORY_EXTRACTION`` avec le commentaire
        « re-use light model » : un petit modèle suffit à remplir un JSON, il
        ne suffit pas à tenir une boucle d'outils. Le rôle dédié existe donc —
        mais exiger son mappage casserait toute installation qui met à jour,
        au moment précis où ses projets se mettent à travailler. Le repli est
        la continuité, pas un défaut de conception.
        """
        try:
            ai_router._resolve(AIRole.PROJECT_WORK)  # noqa: SLF001 — sonde de mappage
        except UnconfiguredRoleError:
            return AIRole.MEMORY_EXTRACTION
        except Exception:  # noqa: BLE001 — un registre illisible ne doit pas bloquer
            return AIRole.MEMORY_EXTRACTION
        return AIRole.PROJECT_WORK

    async def _enregistrer_le_travail(
        self, atelier, resume: str, outils: list[str],
    ) -> None:
        """Un commit par tick AYANT modifié quelque chose.

        Pas de commit vide : un historique où chaque tick laisse une trace ne
        se relit plus, et c'est justement la relecture qu'on cherche — c'est
        elle qui transforme « approuver une charge utile JSON » en « relire un
        diff ».
        """
        try:
            sha = await atelier.git_commit(resume)
        except Exception as exc:  # noqa: BLE001 — l'historique n'est pas le travail
            degradations.record("projects: commit de l'atelier", exc)
            return
        if not sha:
            return
        suffixe = f" · outils : {', '.join(outils[:8])}" if outils else ""
        await self._record_log(
            atelier.project_id,
            action="committed",
            summary=f"[{sha}] {resume[:200]}{suffixe}",
        )

    # ── Prompt history buffer ────────────────────────────────────

    async def _save_prompt_history(
        self,
        *,
        project_id: int,
        system_prompt: str,
        user_prompt: str,
        raw_response: str,
        parsed_output: Optional[dict],
        outcome: str,
        duration_ms: int,
    ) -> None:
        """Persist the LLM prompt/response pair + prune to the configured
        rolling-buffer size. No-op when the size is set to 0 (opt-out).

        Never raises — a history write failure must not block the runner.
        """
        from configs.service import config_service
        size = int(config_service.get("projects.prompt_history_size") or 0)
        if size <= 0:
            return
        try:
            from projects.models import ProjectPromptHistory
        except ImportError:
            return

        try:
            await sync_to_async(ProjectPromptHistory.objects.create)(
                project_id=project_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw_response=raw_response,
                parsed_output=parsed_output,
                outcome=outcome,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            degradations.record("projects: history write failed for project", exc)
            return

        # Ring-buffer prune — delete the oldest rows beyond the cap.
        try:
            await sync_to_async(
                lambda: _prune_history(project_id=project_id, keep=size)
            )()
        except Exception as exc:
            degradations.record("projects: history prune failed for project", exc)

    # ── Applying LLM output ──────────────────────────────────────

    async def _apply_structured(
        self, ctx: context_builder.ProjectRunContext, data: dict, raw: str
    ) -> None:
        """Translate the LLM's JSON into DB writes + log entries."""
        from projects.models import (
            Project,
            ProjectLog,
            ProjectPendingAction,
            ProjectTask,
        )

        summary = str(data.get("summary") or "").strip()[:500] or "advanced"

        # 1. Task updates
        for upd in (data.get("task_updates") or []):
            task_id = upd.get("id")
            new_status = str(upd.get("status") or "").strip().lower()
            result = str(upd.get("result") or "").strip()[:2000]
            blocked_reason = str(upd.get("blocked_reason") or "").strip()[:500]

            if not task_id or new_status not in {
                "todo", "in_progress", "done", "blocked",
            }:
                continue
            try:
                task = await sync_to_async(
                    lambda tid=task_id: ProjectTask.objects.filter(
                        pk=tid, project_id=ctx.project_id,
                    ).first()
                )()
                if not task:
                    continue
                task.status = new_status
                if result:
                    task.result = result
                if blocked_reason:
                    task.blocked_reason = blocked_reason
                if new_status == "done":
                    task.completed_at = timezone.now()
                await sync_to_async(task.save)()
            except Exception as exc:
                degradations.record("projects: update task", exc)

        # 2. New tasks
        for nt in (data.get("new_tasks") or []):
            desc = str(nt.get("description") or "").strip()
            if not desc:
                continue
            order = int(nt.get("order") or 0) if isinstance(nt.get("order"), (int, float)) else 0
            try:
                await sync_to_async(ProjectTask.objects.create)(
                    project_id=ctx.project_id,
                    description=desc[:2000],
                    order=order,
                )
            except Exception as exc:
                degradations.record("projects: create task", exc)

        # 3. Proposed action (if the LLM output includes one) → pending queue
        # `proposed_action` n'est plus le seul canal d'action du lanceur — il
        # écrit et exécute lui-même dans son atelier — mais il reste le sas de
        # ce qui SORT de la machine, et c'est le sens qu'il aurait dû avoir
        # depuis le début. Le prompt ne le déclare que sur un projet qui exige
        # une validation : ailleurs il n'y a pas de file où atterrir, donc la
        # proposition est journalisée plutôt que perdue en silence.
        proposed = data.get("proposed_action")
        if isinstance(proposed, dict) and ctx.requires_approval:
            try:
                await sync_to_async(ProjectPendingAction.objects.create)(
                    project_id=ctx.project_id,
                    proposal=str(proposed.get("proposal") or summary)[:2000],
                    payload=proposed.get("payload") or {},
                )
                await self._record_log(
                    ctx.project_id,
                    action=ProjectLog.Action.AWAITING_APPROVAL,
                    summary=f"Action proposée : {str(proposed.get('proposal') or summary)[:200]}",
                )
                await self._broadcast_pending_action()
            except Exception as exc:
                degradations.record("projects: queue pending action", exc)
        elif proposed:
            # Pas de file d'attente (projet sans validation requise) ou forme
            # inattendue : le lanceur n'exécute aucun effet de bord, donc la
            # proposition ne mène nulle part. Elle est journalisée — visible
            # au tableau de bord et réinjectée dans « DERNIÈRES ACTIONS ».
            libelle = (
                str(proposed.get("proposal") or summary)
                if isinstance(proposed, dict)
                else str(proposed)
            )
            await self._record_log(
                ctx.project_id,
                action=ProjectLog.Action.BLOCKED,
                summary=f"Action proposée non traitée : {libelle[:300]}",
            )

        # 4. Report to user (optional — broadcast as speech)
        report = data.get("report_to_user")
        if report and isinstance(report, str) and report.strip():
            try:
                await self._broadcast_report(ctx, report.strip())
                await self._record_log(
                    ctx.project_id,
                    action=ProjectLog.Action.REPORTED,
                    summary=f"Report: {report.strip()[:200]}",
                )
            except Exception as exc:
                degradations.record("projects: report broadcast", exc)

        # 5. The main advance log
        await self._record_log(
            ctx.project_id,
            action=ProjectLog.Action.ADVANCED,
            summary=summary,
        )

        # 6. Think out loud about it. Generated from the intended action +
        #    what came back, by a small dedicated call — never the raw
        #    summary, which reads like a report, not a thought. Muet en mode
        #    professionnel, ce qui supprime l'appel dans le cas par défaut.
        await self._murmur(ctx, summary, data)

    async def _murmur(self, ctx, summary: str, data: dict) -> None:
        """Voice a short inner thought about this tick. Silence is fine.

        Délégation à `conscience.murmure`, qui porte désormais les six gardes
        et l'unique chemin de diffusion. Deux changements de comportement, tous
        deux voulus :

        1. La porte `emotion_policy == "off"` n'est pas supprimée — elle change
           de main. Elle devient la première des six gardes et, contrairement au
           `return` sec d'avant, elle se **journalise** : `etat_murmure()` dit
           « mode_professionnel » au lieu de ne rien dire du tout.
        2. Le runner hérite des cinq autres gardes, dont deux qui comptent ici :
           l'audience (il diffusait jusqu'ici vers un groupe potentiellement
           vide, en payant l'appel pour ça) et le quota, désormais partagé avec
           la conscience — c'est le même personnage qui pense à voix haute, et
           un quota par appelant n'aurait aucun sens.

        `_broadcast_inner_thought` a été supprimée : `murmure._diffuser` la
        reproduit au champ près. La garder, c'était garder un second chemin de
        diffusion sans aucune garde devant.
        """
        from conscience.murmure import murmurer
        from conscience.murmure_reglage import tuning as murmure_tuning

        # Le murmure part APRÈS le `reset` du ContextVar de `_advance` : sans
        # cette repose, l'appel INNER_VOICE sort avec project_id=None et
        # n'est jamais facturé à `Project.monthly_token_budget`.
        token = current_project_id.set(ctx.project_id)
        try:
            intended = str(
                (data.get("proposed_action") or {}).get("proposal")
                or (data.get("new_tasks") or [""])[0]
                or f"avancer sur « {ctx.title} »"
            )
            await murmurer(
                intended, summary,
                mode_professionnel=(ctx.emotion_policy == "off"),
                tuning=murmure_tuning(),
            )
        except Exception as exc:
            degradations.record("projects: inner thought failed (non-fatal)", exc)
        finally:
            current_project_id.reset(token)

    # ── Persistence helpers ──────────────────────────────────────

    async def _record_log(
        self, project_id: int, action: str, summary: str,
        task_id: Optional[int] = None,
    ) -> None:
        from projects.models import ProjectLog
        try:
            await sync_to_async(ProjectLog.objects.create)(
                project_id=project_id,
                action=action,
                summary=summary,
                task_id=task_id,
            )
        except Exception as exc:
            degradations.record("projects: projectlog write", exc)

    async def _log_error(self, project_id: int, summary: str) -> None:
        from projects.models import ProjectLog
        await self._record_log(
            project_id, ProjectLog.Action.ERROR, summary,
        )

    async def _bump_next_run(self, project_id: int) -> None:
        """Advance next_run_at + last_run_at + runs_since_user_input."""
        from projects.models import Project
        try:
            p = await sync_to_async(
                lambda: Project.objects.filter(pk=project_id).first()
            )()
            if p is None:
                return
            now = timezone.now()
            p.last_run_at = now
            p.runs_since_user_input = p.runs_since_user_input + 1
            try:
                p.next_run_at = schedule.compute_next_run(p.schedule_rule, now)
            except Exception:
                p.next_run_at = None
            await sync_to_async(p.save)(
                update_fields=["last_run_at", "next_run_at", "runs_since_user_input"]
            )
        except Exception as exc:
            degradations.record("projects: bump_next_run", exc)

    # ── External signals ─────────────────────────────────────────

    async def notify_user_input(self, project_id: int) -> None:
        """Call when the user interacts with a project (talks about it,
        approves/rejects an action). Resets the runs_since_user_input
        counter so the cap is lifted."""
        from projects.models import Project
        try:
            await sync_to_async(
                lambda: Project.objects.filter(pk=project_id).update(
                    runs_since_user_input=0,
                )
            )()
        except Exception as exc:
            degradations.record("projects: notify_user_input", exc)

    async def notify_event(self, event_name: str) -> None:
        """Handle "event:<name>" schedule rules by setting next_run_at=now
        on matching projects. Called by a module bus subscriber."""
        from projects.models import Project
        try:
            needle = f"event:{event_name}"
            candidates = await sync_to_async(
                lambda: list(
                    Project.objects.filter(
                        status=Project.Status.ACTIVE,
                        schedule_rule__iexact=needle,
                    )
                )
            )()
            now = timezone.now()
            for p in candidates:
                p.next_run_at = now
                await sync_to_async(p.save)(update_fields=["next_run_at"])
        except Exception as exc:
            degradations.record("projects: notify_event", exc)

    # ── Broadcast helpers ────────────────────────────────────────

    async def _broadcast_pending_action(self) -> None:
        """Push an inner_state_update so the frontend shows the badge."""
        try:
            from pipeline.broadcast import broadcast_inner_state_update
            await broadcast_inner_state_update()
        except Exception as exc:
            degradations.record("projects: pending action broadcast", exc)

    async def _broadcast_report(
        self, ctx: context_builder.ProjectRunContext, text: str,
    ) -> None:
        """Push a project report to the frontend. Uses a dedicated WS
        event type so it's not mistaken for regular conversation speech."""
        from channels.layers import get_channel_layer
        from pipeline.broadcast import BROADCAST_GROUP
        try:
            layer = get_channel_layer()
            await layer.group_send(
                BROADCAST_GROUP,
                {
                    "type": "communication.broadcast",
                    "data": {
                        "type": "project_report",
                        "project_id": ctx.project_id,
                        "project_title": ctx.title,
                        "text": text,
                    },
                },
            )
        except Exception as exc:
            degradations.record("projects: project_report broadcast", exc)


def _prune_history(project_id: int, keep: int) -> int:
    """Delete ProjectPromptHistory rows beyond the `keep` most recent
    for a given project. Returns the number of deleted rows.

    Sync function — run via `sync_to_async` from the caller. Kept at
    module level so it's easy to test in isolation and plug into admin.
    """
    from projects.models import ProjectPromptHistory
    ids_to_keep = list(
        ProjectPromptHistory.objects
        .filter(project_id=project_id)
        # -id as secondary tie-breaker: when many rows share the same
        # microsecond (SQLite), ordering by created_at alone is ambiguous.
        .order_by("-created_at", "-id")
        .values_list("id", flat=True)[:keep]
    )
    if not ids_to_keep:
        return 0
    deleted, _ = (
        ProjectPromptHistory.objects
        .filter(project_id=project_id)
        .exclude(id__in=ids_to_keep)
        .delete()
    )
    return deleted


def _extract_json_tail(raw: str) -> Optional[dict]:
    """Pull the final JSON block out of an LLM response. Tolerates fences
    and trailing text. Returns None if nothing parseable is found.

    L'ancrage sur la derniere accolade ouvrante, ecrit ici parce que le
    helper partage etait gourmand du premier ``{``, vit desormais dans
    ``utils.parsing`` : les six autres appelants payaient le defaut.
    """
    if not raw:
        return None
    try:
        data = json.loads(strip_markdown_json(raw))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


# Singleton
project_runner = ProjectRunner()
