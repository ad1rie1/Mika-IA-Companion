from django.contrib import admin

from identity.models import Identity, IdentityHandle


class IdentityHandleInline(admin.TabularInline):
    model = IdentityHandle
    extra = 0


@admin.register(Identity)
class IdentityAdmin(admin.ModelAdmin):
    list_display = ("__str__", "entity", "last_seen")
    search_fields = ("display_name",)
    inlines = [IdentityHandleInline]


@admin.register(IdentityHandle)
class IdentityHandleAdmin(admin.ModelAdmin):
    list_display = ("person_id", "channel", "kind", "identity", "last_seen")
    list_filter = ("channel", "kind")
    search_fields = ("person_id", "display_name")
