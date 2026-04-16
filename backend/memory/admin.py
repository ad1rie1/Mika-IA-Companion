from django.contrib import admin

from memory.models import (
    Commitment, Connaissance, Conversation, EmotionalSummary, EmotionSnapshot,
    Entity, Message, PersonProfile, SelfNarrative, Souvenir, Theme,
)


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ("role", "content", "source", "created_at")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("pk", "started_at", "ended_at")
    inlines = [MessageInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("pk", "conversation", "role", "source", "created_at")
    list_filter = ("role", "source")


@admin.register(Souvenir)
class SouvenirAdmin(admin.ModelAdmin):
    list_display = ("pk", "content_short", "emotion", "importance", "occurred_at")
    list_filter = ("emotion", "themes")
    search_fields = ("content",)
    filter_horizontal = ("themes", "entities")

    @admin.display(description="Contenu")
    def content_short(self, obj):
        return obj.content[:80] + "..." if len(obj.content) > 80 else obj.content


@admin.register(Connaissance)
class ConnaissanceAdmin(admin.ModelAdmin):
    list_display = ("pk", "content_short", "confidence", "is_valid", "created_at")
    list_filter = ("is_valid", "themes")
    search_fields = ("content",)
    filter_horizontal = ("themes", "entities")

    @admin.display(description="Contenu")
    def content_short(self, obj):
        return obj.content[:80] + "..." if len(obj.content) > 80 else obj.content


@admin.register(Theme)
class ThemeAdmin(admin.ModelAdmin):
    list_display = ("pk", "name")
    search_fields = ("name",)


@admin.register(Entity)
class EntityAdmin(admin.ModelAdmin):
    list_display = ("pk", "name", "entity_type")
    list_filter = ("entity_type",)
    search_fields = ("name",)


@admin.register(EmotionSnapshot)
class EmotionSnapshotAdmin(admin.ModelAdmin):
    list_display = ("pk", "person_id", "primary_emotion", "primary_intensity", "created_at")
    list_filter = ("person_id", "primary_emotion")
    readonly_fields = ("created_at",)


@admin.register(EmotionalSummary)
class EmotionalSummaryAdmin(admin.ModelAdmin):
    list_display = ("pk", "person_id", "period_type", "period_start", "dominant_emotion", "trend", "snapshot_count")
    list_filter = ("person_id", "period_type", "trend")
    readonly_fields = ("created_at", "updated_at")


@admin.register(SelfNarrative)
class SelfNarrativeAdmin(admin.ModelAdmin):
    list_display = ("pk", "content_short", "dominant_mood", "confidence", "created_at")
    list_filter = ("dominant_mood",)
    readonly_fields = ("created_at",)

    @admin.display(description="Narrative")
    def content_short(self, obj):
        return obj.content[:120] + "..." if len(obj.content) > 120 else obj.content


@admin.register(PersonProfile)
class PersonProfileAdmin(admin.ModelAdmin):
    list_display = (
        "pk", "entity", "closeness", "preferred_tone",
        "interaction_count", "last_interaction_at", "generated_at",
    )
    list_filter = ("closeness", "preferred_tone")
    search_fields = ("entity__name", "summary")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Commitment)
class CommitmentAdmin(admin.ModelAdmin):
    list_display = ("pk", "status", "person", "description_short", "due_at", "created_at")
    list_filter = ("status",)
    search_fields = ("description", "person__name")
    readonly_fields = ("created_at", "resolved_at")

    @admin.display(description="Description")
    def description_short(self, obj):
        return obj.description[:100] + "..." if len(obj.description) > 100 else obj.description
