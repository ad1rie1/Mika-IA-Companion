"""HTTP endpoints for project management (user-facing, not debug-gated).

Routes all mounted under /api/projects/* via ``urls.py``.

    GET    /api/projects/                    list active projects
    POST   /api/projects/                    create a project manually
    GET    /api/projects/<id>                detail + tasks + recent logs
    PATCH  /api/projects/<id>                update fields (pause, retune, ...)
    POST   /api/projects/<id>/tasks          add a task
    PATCH  /api/projects/<id>/tasks/<tid>    update a task (status, reorder, ...)

    GET    /api/projects/pending/            list pending actions awaiting approval
    POST   /api/projects/pending/<id>/approve    approve + execute payload
    POST   /api/projects/pending/<id>/reject     reject with optional note

All responses are JSON. User notifications go via WebSocket inner_state
updates — the runner calls ``broadcast_inner_state_update`` itself when
state changes (new pending action, task done, etc.).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from asgiref.sync import async_to_sync
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from projects import schedule
from projects.models import (
    Project,
    ProjectLog,
    ProjectPendingAction,
    ProjectPromptHistory,
    ProjectTask,
)

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────


def _project_to_dict(p: Project, *, include_tasks: bool = False) -> dict:
    data = {
        "id": p.id,
        "title": p.title,
        "description": p.description,
        "status": p.status,
        "priority": p.priority,
        "origin": p.origin,
        "emotion_policy": p.emotion_policy,
        "tone_directive": p.tone_directive,
        "instructions": list(p.instructions or []),
        "out_of_scope": list(p.out_of_scope or []),
        "requires_approval": p.requires_approval,
        "allowed_modules": list(p.allowed_modules or []),
        "resource_paths": list(p.resource_paths or []),
        "contacts": list(p.contacts or []),
        "schedule_rule": p.schedule_rule,
        "next_run_at": p.next_run_at.isoformat() if p.next_run_at else None,
        "last_run_at": p.last_run_at.isoformat() if p.last_run_at else None,
        "runs_since_user_input": p.runs_since_user_input,
        "monthly_token_budget": p.monthly_token_budget,
        "keywords": list(p.keywords or []),
        "owner": p.owner.name if p.owner_id else None,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }
    if include_tasks:
        data["tasks"] = [
            _task_to_dict(t)
            for t in ProjectTask.objects.filter(project=p).order_by("order", "created_at")
        ]
    return data


def _task_to_dict(t: ProjectTask) -> dict:
    return {
        "id": t.id,
        "description": t.description,
        "status": t.status,
        "order": t.order,
        "blocked_reason": t.blocked_reason,
        "result": t.result,
        "created_at": t.created_at.isoformat(),
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
    }


def _pending_to_dict(a: ProjectPendingAction) -> dict:
    return {
        "id": a.id,
        "project_id": a.project_id,
        "project_title": a.project.title,
        "task_id": a.task_id,
        "proposal": a.proposal,
        "payload": a.payload,
        "status": a.status,
        "user_note": a.user_note,
        "created_at": a.created_at.isoformat(),
        "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
    }


def _parse_body(request) -> dict:
    try:
        return json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return {}


def _error(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": msg}, status=status)


# ── Project CRUD ────────────────────────────────────────────────


@require_http_methods(["GET"])
def list_projects(request):
    status_filter = request.GET.get("status", "")
    qs = Project.objects.all()
    if status_filter:
        qs = qs.filter(status=status_filter)
    return JsonResponse({
        "projects": [_project_to_dict(p) for p in qs.order_by(
            "-priority", "-updated_at",
        )],
    })


@csrf_exempt
@require_http_methods(["POST"])
def create_project(request):
    body = _parse_body(request)
    title = (body.get("title") or "").strip()
    if not title:
        return _error("title is required")

    # Build with whatever fields the user provided; others fall through
    # to model defaults.
    allowed_fields = {
        "description", "keywords", "origin", "status", "priority",
        "tone_directive", "emotion_policy", "instructions", "out_of_scope",
        "requires_approval", "allowed_modules", "resource_paths", "contacts",
        "schedule_rule", "monthly_token_budget",
    }
    kwargs = {k: body[k] for k in body.keys() & allowed_fields if body[k] is not None}
    kwargs["title"] = title[:150]

    # Compute initial next_run_at if a clock-based rule is provided
    rule = kwargs.get("schedule_rule") or ""
    if rule:
        try:
            kwargs["next_run_at"] = schedule.compute_next_run(rule, timezone.now())
        except Exception:
            kwargs["next_run_at"] = None

    try:
        p = Project.objects.create(**kwargs)
    except Exception as e:
        logger.exception("Project creation failed")
        return _error(f"creation failed: {e}", status=500)

    return JsonResponse({"ok": True, "project": _project_to_dict(p)})


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
def project_detail(request, project_id: int):
    try:
        p = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return _error("not found", status=404)

    if request.method == "GET":
        data = _project_to_dict(p, include_tasks=True)
        data["recent_logs"] = [
            {
                "action": log.action,
                "summary": log.summary,
                "created_at": log.created_at.isoformat(),
            }
            for log in ProjectLog.objects.filter(project=p).order_by("-created_at")[:20]
        ]
        data["pending_actions"] = [
            _pending_to_dict(a)
            for a in ProjectPendingAction.objects.filter(
                project=p, status=ProjectPendingAction.Status.PENDING,
            )
        ]
        return JsonResponse(data)

    if request.method == "DELETE":
        p.delete()
        return JsonResponse({"ok": True})

    # PATCH — partial update
    body = _parse_body(request)
    updatable = {
        "title", "description", "keywords", "status", "priority",
        "tone_directive", "emotion_policy", "instructions", "out_of_scope",
        "requires_approval", "allowed_modules", "resource_paths", "contacts",
        "schedule_rule", "monthly_token_budget",
    }
    for k, v in body.items():
        if k in updatable and v is not None:
            setattr(p, k, v)
    # Recompute next_run_at if schedule_rule changed
    if "schedule_rule" in body:
        try:
            p.next_run_at = schedule.compute_next_run(
                p.schedule_rule, timezone.now(),
            )
        except Exception:
            p.next_run_at = None
    p.save()
    return JsonResponse({"ok": True, "project": _project_to_dict(p)})


# ── Task endpoints ──────────────────────────────────────────────


@csrf_exempt
@require_http_methods(["POST"])
def add_task(request, project_id: int):
    try:
        p = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return _error("project not found", status=404)

    body = _parse_body(request)
    desc = (body.get("description") or "").strip()
    if not desc:
        return _error("description is required")

    order = body.get("order")
    if not isinstance(order, int):
        last = ProjectTask.objects.filter(project=p).order_by("-order").first()
        order = (last.order + 1) if last else 0

    t = ProjectTask.objects.create(
        project=p, description=desc[:2000], order=order,
    )
    return JsonResponse({"ok": True, "task": _task_to_dict(t)})


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
def task_detail(request, project_id: int, task_id: int):
    try:
        t = ProjectTask.objects.get(pk=task_id, project_id=project_id)
    except ProjectTask.DoesNotExist:
        return _error("task not found", status=404)

    if request.method == "DELETE":
        t.delete()
        return JsonResponse({"ok": True})

    body = _parse_body(request)
    if "description" in body:
        t.description = str(body["description"])[:2000]
    if "status" in body and body["status"] in dict(ProjectTask.Status.choices):
        t.status = body["status"]
        if t.status == ProjectTask.Status.DONE and not t.completed_at:
            t.completed_at = timezone.now()
    if "order" in body and isinstance(body["order"], int):
        t.order = body["order"]
    if "blocked_reason" in body:
        t.blocked_reason = str(body["blocked_reason"])[:500]
    if "result" in body:
        t.result = str(body["result"])[:2000]
    t.save()
    return JsonResponse({"ok": True, "task": _task_to_dict(t)})


# ── Pending actions ─────────────────────────────────────────────


@require_http_methods(["GET"])
def list_pending(request):
    project_id = request.GET.get("project_id")
    qs = ProjectPendingAction.objects.filter(
        status=ProjectPendingAction.Status.PENDING,
    ).select_related("project")
    if project_id:
        qs = qs.filter(project_id=project_id)
    return JsonResponse({
        "pending": [_pending_to_dict(a) for a in qs.order_by("-created_at")],
    })


@csrf_exempt
@require_http_methods(["POST"])
def approve_pending(request, action_id: int):
    """Approve a pending action and execute its payload.

    Payload execution is dispatched by `payload.kind`. Supported kinds:
      - "send_email": requires 'email' module available
      - "write_file": requires 'files' module (future)
      - Unknown kinds → execution is skipped, action marked executed with
        the payload recorded (audit only).
    """
    try:
        a = ProjectPendingAction.objects.select_related("project").get(pk=action_id)
    except ProjectPendingAction.DoesNotExist:
        return _error("pending action not found", status=404)
    if a.status != ProjectPendingAction.Status.PENDING:
        return _error(f"already {a.status}", status=400)

    body = _parse_body(request)
    note = str(body.get("note", ""))[:500]

    a.status = ProjectPendingAction.Status.APPROVED
    a.user_note = note
    a.resolved_at = timezone.now()
    a.save()

    # Execute
    try:
        result = _execute_pending_payload(a)
        a.status = ProjectPendingAction.Status.EXECUTED
        a.execution_result = str(result)[:2000]
    except Exception as e:
        logger.exception("Execution of pending action %s failed", action_id)
        a.status = ProjectPendingAction.Status.FAILED
        a.execution_result = f"error: {e}"[:2000]
    a.save()

    # Notify runner so it resets runs_since_user_input
    try:
        async_to_sync(_notify_project_input)(a.project_id)
    except Exception:
        pass

    # Push inner state refresh so frontend removes the badge
    try:
        from pipeline.broadcast import broadcast_inner_state_update
        async_to_sync(broadcast_inner_state_update)()
    except Exception:
        pass

    return JsonResponse({"ok": True, "pending": _pending_to_dict(a)})


@csrf_exempt
@require_http_methods(["POST"])
def reject_pending(request, action_id: int):
    try:
        a = ProjectPendingAction.objects.select_related("project").get(pk=action_id)
    except ProjectPendingAction.DoesNotExist:
        return _error("pending action not found", status=404)
    if a.status != ProjectPendingAction.Status.PENDING:
        return _error(f"already {a.status}", status=400)

    body = _parse_body(request)
    note = str(body.get("note", ""))[:500]

    a.status = ProjectPendingAction.Status.REJECTED
    a.user_note = note
    a.resolved_at = timezone.now()
    a.save()

    # Also create a ProjectLog entry explaining the rejection so the
    # runner sees it next tick.
    try:
        ProjectLog.objects.create(
            project_id=a.project_id,
            action=ProjectLog.Action.REPORTED,
            summary=f"Proposition rejetée par l'utilisateur"
                    + (f" : {note}" if note else ""),
        )
    except Exception:
        pass

    try:
        async_to_sync(_notify_project_input)(a.project_id)
    except Exception:
        pass

    try:
        from pipeline.broadcast import broadcast_inner_state_update
        async_to_sync(broadcast_inner_state_update)()
    except Exception:
        pass

    return JsonResponse({"ok": True, "pending": _pending_to_dict(a)})


async def _notify_project_input(project_id: int) -> None:
    from projects.runner import project_runner
    await project_runner.notify_user_input(project_id)


# ── Prompt history (audit) ──────────────────────────────────────


@require_http_methods(["GET"])
def project_prompt_history(request, project_id: int):
    """Return the rolling buffer of LLM prompt/response pairs for a project.

    Query params:
      limit (int, default 30, cap 100) — max rows returned (most recent first)
      full  (1/true to include the full system_prompt + raw_response;
             default is a compact summary to keep the payload small)
    """
    try:
        Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return _error("project not found", status=404)

    try:
        limit = int(request.GET.get("limit", 30))
    except (TypeError, ValueError):
        limit = 30
    limit = max(1, min(100, limit))

    full = request.GET.get("full", "").lower() in ("1", "true", "yes")

    qs = (
        ProjectPromptHistory.objects.filter(project_id=project_id)
        .order_by("-created_at", "-id")[:limit]
    )

    items: list[dict] = []
    for h in qs:
        row = {
            "id": h.id,
            "outcome": h.outcome,
            "duration_ms": h.duration_ms,
            "created_at": h.created_at.isoformat(),
            "parsed_output": h.parsed_output,
        }
        if full:
            row["system_prompt"] = h.system_prompt
            row["user_prompt"] = h.user_prompt
            row["raw_response"] = h.raw_response
        else:
            row["system_prompt_excerpt"] = (h.system_prompt or "")[:240]
            row["raw_response_excerpt"] = (h.raw_response or "")[:240]
        items.append(row)

    return JsonResponse({"history": items, "count": len(items)})


# ── Payload dispatch ────────────────────────────────────────────


def _execute_pending_payload(a: ProjectPendingAction) -> str:
    """Dispatch on `payload.kind`. Returns a short audit string."""
    kind = (a.payload or {}).get("kind")
    if not kind:
        return "no-kind payload (audit-only)"

    if kind == "send_email":
        # Delegate to the email module's tool if it's loaded. Schema:
        #   {"kind": "send_email", "to": "...", "subject": "...", "body": "..."}
        try:
            from modules.manager import module_manager
            em = module_manager.get_module("email")
        except Exception:
            em = None
        if em is None:
            return "email module not loaded — action logged only"
        # Best-effort — the email module exposes `send_email` as a tool.
        # We call a direct sync helper if available.
        send_fn = getattr(em, "send_email_sync", None)
        if send_fn:
            try:
                send_fn(
                    to=a.payload.get("to", ""),
                    subject=a.payload.get("subject", ""),
                    body=a.payload.get("body", ""),
                )
                return f"email sent to {a.payload.get('to', '')}"
            except Exception as e:
                return f"email send failed: {e}"
        return "email module lacks send_email_sync — action logged only"

    # Unknown kinds: audit-only
    return f"unsupported payload kind '{kind}' — logged for audit"
