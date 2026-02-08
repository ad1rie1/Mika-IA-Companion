from django.contrib import admin

from modules.email.models import ProcessedEmail
from modules.wake.models import WakeRequest


@admin.register(WakeRequest)
class WakeRequestAdmin(admin.ModelAdmin):
    list_display = ("pk", "source", "status", "created_at", "processed_at")
    list_filter = ("status", "source")
    readonly_fields = ("created_at",)


@admin.register(ProcessedEmail)
class ProcessedEmailAdmin(admin.ModelAdmin):
    list_display = ("pk", "from_addr", "subject", "priority", "notified", "replied", "processed_at")
    list_filter = ("priority", "notified", "replied")
    search_fields = ("from_addr", "subject")
    readonly_fields = ("processed_at",)
