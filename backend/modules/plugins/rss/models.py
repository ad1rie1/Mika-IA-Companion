"""RSS module models — feeds and seen entries for deduplication."""

from django.db import models


class RSSFeed(models.Model):
    """A configured RSS/Atom feed to monitor."""

    name = models.CharField(max_length=200)
    url = models.URLField(max_length=500, unique=True)
    is_active = models.BooleanField(default=True)
    last_polled = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "modules"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.url[:50]})"


class RSSEntry(models.Model):
    """A seen RSS entry — used for deduplication and browsing."""

    feed = models.ForeignKey(RSSFeed, on_delete=models.CASCADE, related_name="entries")
    entry_hash = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=500)
    link = models.URLField(max_length=500, blank=True, default="")
    summary = models.TextField(blank=True, default="")
    author = models.CharField(max_length=200, blank=True, default="")
    published = models.CharField(max_length=100, blank=True, default="")
    seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "modules"
        ordering = ["-seen_at"]
        unique_together = [("feed", "entry_hash")]

    def __str__(self):
        return self.title[:80]
