from django.contrib import admin

from ai.models import AIQuotaUsage


@admin.register(AIQuotaUsage)
class AIQuotaUsageAdmin(admin.ModelAdmin):
    list_display = (
        "date", "role", "project_id", "provider", "model",
        "call_count", "tokens_in", "tokens_out", "cost_usd",
    )
    list_filter = ("date", "role", "provider", "model")
    search_fields = ("role", "model", "provider")
    readonly_fields = (
        "role", "project_id", "date", "provider", "model",
        "call_count", "tokens_in", "tokens_out", "cost_usd", "last_at",
    )
    ordering = ("-date", "role")
