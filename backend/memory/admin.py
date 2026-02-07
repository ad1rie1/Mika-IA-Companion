from django.contrib import admin

from memory.models import Conversation, Memory, Message


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


@admin.register(Memory)
class MemoryAdmin(admin.ModelAdmin):
    list_display = ("pk", "summary", "keywords", "created_at")
