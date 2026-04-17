from __future__ import annotations

from django.db.models import Count
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from dashboard.serializers import iso


@require_http_methods(["GET"])
def projects(request):
    from projects.models import Project, ProjectPendingAction, ProjectTask

    qs = Project.objects.order_by("-updated_at")
    rows = []
    for p in qs:
        task_counts = dict(
            ProjectTask.objects.filter(project=p)
            .values_list("status")
            .annotate(n=Count("id"))
            .values_list("status", "n")
        )
        rows.append({
            "id": p.id,
            "title": p.title,
            "description": p.description,
            "status": p.status,
            "priority": p.priority,
            "origin": p.origin,
            "emotion_policy": p.emotion_policy,
            "schedule_rule": p.schedule_rule,
            "next_run_at": iso(p.next_run_at),
            "last_run_at": iso(p.last_run_at),
            "runs_since_user_input": p.runs_since_user_input,
            "tasks": task_counts,
            "owner": p.owner.name if p.owner_id else None,
            "created_at": iso(p.created_at),
        })
    pending = [
        {
            "id": a.id,
            "project_id": a.project_id,
            "proposal": a.proposal,
            "status": a.status,
            "created_at": iso(a.created_at),
        }
        for a in ProjectPendingAction.objects.filter(status="pending").order_by(
            "-created_at"
        )[:50]
    ]
    return JsonResponse({"projects": rows, "pending_actions": pending})
