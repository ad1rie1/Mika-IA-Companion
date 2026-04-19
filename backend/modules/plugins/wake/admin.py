from django.contrib import admin

from modules.plugins.wake.models import WakeRequest


@admin.register(WakeRequest)
class WakeRequestAdmin(admin.ModelAdmin):
    list_display = ("pk", "source", "status", "created_at", "processed_at")
    list_filter = ("status", "source")
    readonly_fields = ("created_at",)
