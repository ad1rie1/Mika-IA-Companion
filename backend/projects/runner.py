"""ProjectRunner — advance active projects on schedule or on idle.

Integration: the runner owns its own background loop (started from ASGI
lifespan, cadence ``projects.runner_interval``). Each tick:
  1. Lists projects whose schedule is due
  2. For each, assembles a ProjectRunContext and calls the LLM
  3. Parses the structured output, applies task updates, creates
     new tasks, queues pending actions (if `requires_approval`),
     and records a ProjectLog
  4. Bumps `next_run_at` via ``schedule.compute_next_run``

This is the "silent" Mika — no WS broadcast of her internal thinking,
unless `report_to_user` is produced (then we push a notification).

Bulk-safety: max `MAX_ADVANCES_PER_TICK` projects advanced per call to
avoid LLM bursts if a dozen projects fire at once.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Optional

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone

from ai.quota import QuotaExceeded, current_project_id
from ai.router import AIRole, ai_router
from projects import context_builder, schedule
from utils.parsing import strip_markdown_json

logger = logging.getLogger(__name__)


# Safety caps
MAX_ADVANCES_PER_TICK = 3         # at most N advances in a single tick
LLM_TIMEOUT_SECONDS = 90
RUNS_SINCE_INPUT_CAP = 10         # beyond this, force a pause until user comes back


# Regex to locate a JSON block at end of LLM response (fenced or bare).
# Anchored to the LAST `{` via rfind before use; the regex itself is
# kept as a defensive fallback for responses with trailing whitespace.
_JSON_TAIL_RE = re.compile(r"(\{[\s\S]*\})\s*$")


class ProjectRunner:
    """Singleton driving project advancement."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # Dedicated background loop (since 2026-04): previously piggy-backed
        # on the consolidator's 60s tick, now independent so `interval:30s`
        # schedules actually fire at 30s and a blocked 90s LLM call here
        # never starves memory consolidation.
        self._task: asyncio.Task | None = None
        self._running: bool = False
        self._interval: int = 30

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the dedicated runner loop. Idempotent."""
        if self._running:
            return
        from configs.service import config_service
        self._interval = int(
            config_service.get("projects.runner_interval", default=30)
        )
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Project runner loop started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        """Stop the loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Project runner loop stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                if self._running:
                    await self.tick()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Project runner loop error")

    async def tick(self) -> int:
        """One pass of the scheduler. Returns number of projects advanced.

        Safe to call frequently — cheap when nothing is due.
        """
        if self._lock.locked():
            # A previous tick is still running. Skip silently.
            return 0

        async with self._lock:
            return await self._tick_inner()

    async def _tick_inner(self) -> int:
        due = await self._list_due()
        if not due:
            return 0

        advanced = 0
        for project_id in due[:MAX_ADVANCES_PER_TICK]:
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
        except Exception:
            logger.debug("Due query failed", exc_info=True)
            return []

        due_ids: list[int] = []
        for p in projects:
            if p.runs_since_user_input >= RUNS_SINCE_INPUT_CAP:
                # Don't spin forever without user feedback
                continue
            try:
                if schedule.is_due(p):
                    due_ids.append(p.id)
            except Exception:
                logger.debug("is_due raised for project %s", p.id, exc_info=True)

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
        user_prompt = (
            "Fais avancer le projet d'une étape. Rappel du format de sortie "
            "obligatoire : termine par un bloc JSON avec summary / task_updates "
            "/ new_tasks / report_to_user."
        )

        raw = ""
        outcome = "ok"
        started = time.time()

        # Attribute this LLM call to the project so the quota tracker
        # charges `Project.monthly_token_budget`.
        token = current_project_id.set(project_id)
        try:
            raw = await asyncio.wait_for(
                ai_router.complete(
                    role=AIRole.MEMORY_EXTRACTION,  # re-use light model
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                ),
                timeout=LLM_TIMEOUT_SECONDS,
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
        await self._bump_next_run(project_id)
        return True

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
        except Exception:
            logger.debug("history write failed for project %s", project_id,
                         exc_info=True)
            return

        # Ring-buffer prune — delete the oldest rows beyond the cap.
        try:
            await sync_to_async(
                lambda: _prune_history(project_id=project_id, keep=size)
            )()
        except Exception:
            logger.debug("history prune failed for project %s", project_id,
                         exc_info=True)

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
            except Exception:
                logger.debug("Failed to update task %s", task_id, exc_info=True)

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
            except Exception:
                logger.debug("Failed to create task", exc_info=True)

        # 3. Proposed action (if the LLM output includes one) → pending queue
        # Projects using `requires_approval=True` should route proposals through
        # a dedicated structure. We accept `proposed_action` in the JSON too.
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
            except Exception:
                logger.debug("Failed to queue pending action", exc_info=True)

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
            except Exception:
                logger.debug("Report broadcast failed", exc_info=True)

        # 5. The main advance log
        await self._record_log(
            ctx.project_id,
            action=ProjectLog.Action.ADVANCED,
            summary=summary,
        )

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
        except Exception:
            logger.debug("ProjectLog write failed", exc_info=True)

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
        except Exception:
            logger.debug("bump_next_run failed", exc_info=True)

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
        except Exception:
            logger.debug("notify_user_input failed", exc_info=True)

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
        except Exception:
            logger.debug("notify_event failed", exc_info=True)

    # ── Broadcast helpers ────────────────────────────────────────

    async def _broadcast_pending_action(self) -> None:
        """Push an inner_state_update so the frontend shows the badge."""
        try:
            from pipeline.broadcast import broadcast_inner_state_update
            await broadcast_inner_state_update()
        except Exception:
            logger.debug("pending action broadcast failed", exc_info=True)

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
        except Exception:
            logger.debug("project_report broadcast failed", exc_info=True)


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
    and trailing text. Returns None if nothing parseable is found."""
    if not raw:
        return None
    # First, try the cleanest case: whole string is JSON
    candidate = strip_markdown_json(raw.strip())
    try:
        return json.loads(candidate)
    except Exception:
        pass
    # Anchor on the LAST opening brace — prose before the final JSON
    # block (e.g. "Mes {reflexions}... voici: {real json}") would poison
    # a greedy regex that spans from the first `{`.
    stripped = raw.strip()
    last_open = stripped.rfind("{")
    if last_open != -1:
        try:
            return json.loads(stripped[last_open:])
        except Exception:
            pass
    # Defensive fallback on the regex path (rarely useful now that rfind
    # covers the common case, but harmless and keeps behavior if the
    # trailing structure looks unusual).
    m = _JSON_TAIL_RE.search(stripped)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


# Singleton
project_runner = ProjectRunner()
