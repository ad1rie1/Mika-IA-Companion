from django.contrib import admin

from identity.models import Identity, IdentityClaim, IdentityHandle
from identity.trust import label_for


class IdentityHandleInline(admin.TabularInline):
    model = IdentityHandle
    extra = 0
    fields = ("person_id", "channel", "kind", "trust", "is_ephemeral", "last_seen")
    readonly_fields = ("last_seen",)


class IdentityClaimInline(admin.TabularInline):
    """The evidence ledger behind an identity's certainty."""

    model = IdentityClaim
    extra = 0
    fields = ("claimed_name", "kind", "status", "applied_weight", "evidence",
              "created_at")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


@admin.register(Identity)
class IdentityAdmin(admin.ModelAdmin):
    list_display = ("__str__", "entity", "certainty_label", "bound_via", "last_seen")
    list_filter = ("bound_via",)
    search_fields = ("display_name", "entity__name")
    readonly_fields = ("created_at", "last_seen", "bound_at")
    inlines = [IdentityHandleInline, IdentityClaimInline]

    @admin.display(description="Certitude", ordering="certainty")
    def certainty_label(self, obj):
        """Show the named level, not the raw float — 0.7 means nothing to a
        reader, "corroborated" does."""
        return f"{obj.certainty:.0%} · {label_for(obj.certainty).name.lower()}"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("entity")


@admin.register(IdentityHandle)
class IdentityHandleAdmin(admin.ModelAdmin):
    list_display = ("person_id", "channel", "kind", "trust", "is_ephemeral",
                    "identity", "last_seen")
    list_filter = ("channel", "kind", "trust", "is_ephemeral")
    search_fields = ("person_id", "display_name")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("identity")


@admin.register(IdentityClaim)
class IdentityClaimAdmin(admin.ModelAdmin):
    list_display = ("claimed_name", "kind", "status", "channel", "trust",
                    "applied_weight", "created_at")
    list_filter = ("status", "kind", "channel", "trust")
    search_fields = ("claimed_name", "evidence", "resolution_note")
    readonly_fields = ("created_at", "resolved_at", "applied_weight")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("identity", "handle")
