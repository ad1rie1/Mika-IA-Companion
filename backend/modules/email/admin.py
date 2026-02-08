from django.contrib import admin

from modules.email.models import Contact, Email, EmailAccount


@admin.register(EmailAccount)
class EmailAccountAdmin(admin.ModelAdmin):
    list_display = ("pk", "name", "email_address", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "email_address")


@admin.register(Email)
class EmailAdmin(admin.ModelAdmin):
    list_display = ("pk", "account", "from_address", "subject", "direction", "priority", "email_date")
    list_filter = ("direction", "priority", "is_read", "notified", "account")
    search_fields = ("from_address", "to_addresses", "subject")
    readonly_fields = ("fetched_at",)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("pk", "email_address", "display_name", "emails_received", "emails_sent", "last_seen")
    search_fields = ("email_address", "display_name")
    readonly_fields = ("first_seen", "last_seen")
