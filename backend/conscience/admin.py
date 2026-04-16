from django.contrib import admin

from conscience.models import ConscienceLog, Observation, ScheduledAction


@admin.register(Observation)
class ObservationAdmin(admin.ModelAdmin):
    list_display = [
        "source",
        "event_type",
        "category",
        "pertinence",
        "emotional_reaction",
        "status",
        "created_at",
    ]
    list_filter = ["category", "status", "source"]
    search_fields = ["summary", "event_type"]
    readonly_fields = ["raw_data", "created_at"]


@admin.register(ConscienceLog)
class ConscienceLogAdmin(admin.ModelAdmin):
    list_display = [
        "decision",
        "reason",
        "observations_count",
        "max_pertinence",
        "global_mood",
        "idle_seconds",
        "created_at",
    ]
    list_filter = ["decision"]


@admin.register(ScheduledAction)
class ScheduledActionAdmin(admin.ModelAdmin):
    list_display = ["pk", "prompt_short", "scheduled_at", "priority", "source", "status"]
    list_filter = ["status", "source"]
    readonly_fields = ["created_at", "executed_at"]

    @admin.display(description="Prompt")
    def prompt_short(self, obj):
        return obj.prompt[:80] + "..." if len(obj.prompt) > 80 else obj.prompt
