"""Django admin for project management.

Built for quick human triage — list view shows priority, status, schedule,
next run, task progress. Detail pages let a human edit tone/instructions
and flip status, which takes effect on the runner's next tick.
"""
from django.contrib import admin

from projects.models import (
    Project,
    ProjectLog,
    ProjectPendingAction,
    ProjectPromptHistory,
    ProjectTask,
)


class ProjectTaskInline(admin.TabularInline):
    model = ProjectTask
    extra = 0
    fields = ("order", "status", "description", "blocked_reason", "completed_at")
    readonly_fields = ("completed_at",)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "title", "status", "priority", "origin", "emotion_policy",
        "schedule_rule", "next_run_at", "task_progress", "updated_at",
    )
    list_filter = ("status", "priority", "origin", "emotion_policy")
    search_fields = ("title", "description")
    readonly_fields = ("created_at", "updated_at", "last_run_at",
                       "runs_since_user_input")
    fieldsets = (
        ("Identity", {
            "fields": ("title", "description", "keywords", "origin",
                       "status", "priority", "owner"),
        }),
        ("Execution frame", {
            "fields": ("tone_directive", "emotion_policy", "instructions",
                       "out_of_scope", "requires_approval"),
        }),
        ("Resource scope", {
            "fields": ("allowed_modules", "resource_paths", "contacts"),
        }),
        ("Scheduling", {
            "fields": ("schedule_rule", "next_run_at", "last_run_at",
                       "runs_since_user_input"),
        }),
        ("Meta", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
    inlines = [ProjectTaskInline]

    @admin.display(description="Tasks")
    def task_progress(self, obj):
        total = obj.tasks.count()
        if total == 0:
            return "—"
        done = obj.tasks.filter(status=ProjectTask.Status.DONE).count()
        return f"{done}/{total}"


@admin.register(ProjectTask)
class ProjectTaskAdmin(admin.ModelAdmin):
    list_display = ("project", "order", "status", "description",
                    "updated_at", "completed_at")
    list_filter = ("status", "project")
    search_fields = ("description",)
    readonly_fields = ("created_at", "updated_at", "completed_at")


@admin.register(ProjectLog)
class ProjectLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "project", "action", "summary_short")
    list_filter = ("action", "project")
    readonly_fields = ("project", "action", "summary", "tools_used",
                       "task", "created_at")
    search_fields = ("summary",)

    @admin.display(description="Summary")
    def summary_short(self, obj):
        return obj.summary[:100]


@admin.register(ProjectPromptHistory)
class ProjectPromptHistoryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "project", "outcome", "duration_ms",
                    "system_prompt_short")
    list_filter = ("outcome", "project")
    readonly_fields = ("project", "system_prompt", "user_prompt",
                       "raw_response", "parsed_output", "outcome",
                       "duration_ms", "created_at")
    search_fields = ("system_prompt", "raw_response")

    @admin.display(description="System prompt")
    def system_prompt_short(self, obj):
        return (obj.system_prompt or "")[:100]

    # History rows are append-only — no admin creation, no edits
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ProjectPendingAction)
class ProjectPendingActionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "project", "status", "proposal_short",
                    "resolved_at")
    list_filter = ("status", "project")
    readonly_fields = ("project", "task", "proposal", "payload",
                       "created_at", "resolved_at", "execution_result")
    search_fields = ("proposal",)

    @admin.display(description="Proposal")
    def proposal_short(self, obj):
        return obj.proposal[:80]
