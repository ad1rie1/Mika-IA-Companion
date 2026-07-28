"""Admin Django — filet de secours.

L'édition normale des flux se fait dans GestionSystème (Modules → RSS →
Configuration), qui écrit dans ces mêmes tables via ``config_backend``.
"""
from django.contrib import admin

from modules.plugins.rss.models import RSSEntry, RSSFeed


@admin.register(RSSFeed)
class RSSFeedAdmin(admin.ModelAdmin):
    list_display = [
        "name", "category", "url", "is_active",
        "last_polled", "error_count", "entries_total",
    ]
    list_filter = ["is_active", "category", "emit_events"]
    search_fields = ["name", "url", "keywords"]
    readonly_fields = [
        "last_polled", "last_success_at", "last_error", "last_error_at",
        "error_count", "entries_total", "etag", "http_last_modified",
        "created_at",
    ]


@admin.register(RSSEntry)
class RSSEntryAdmin(admin.ModelAdmin):
    list_display = ["title", "feed", "author", "published_at", "is_read", "is_notable"]
    list_filter = ["feed", "is_read", "is_notable"]
    search_fields = ["title", "summary", "author"]
    readonly_fields = ["entry_hash", "seen_at"]
