from django.contrib import admin

from modules.rss.models import RSSEntry, RSSFeed


@admin.register(RSSFeed)
class RSSFeedAdmin(admin.ModelAdmin):
    list_display = ["name", "url", "is_active", "last_polled"]
    list_filter = ["is_active"]
    search_fields = ["name", "url"]


@admin.register(RSSEntry)
class RSSEntryAdmin(admin.ModelAdmin):
    list_display = ["title", "feed", "author", "seen_at"]
    list_filter = ["feed"]
    search_fields = ["title", "summary"]
    readonly_fields = ["entry_hash", "seen_at"]
