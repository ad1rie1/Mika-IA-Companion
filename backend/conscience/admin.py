from django.contrib import admin

from conscience.models import ConscienceLog, Observation


@admin.register(Observation)
class ObservationAdmin(admin.ModelAdmin):
    list_display = [
        "source",
        "event_type",
        "category",
        "pertinence",
        "emotional_reaction",
        "acted_upon",
        "created_at",
    ]
    list_filter = ["category", "acted_upon", "source"]
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
