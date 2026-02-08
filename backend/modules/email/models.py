from django.db import models


class ProcessedEmail(models.Model):
    """Tracks emails that have been processed by the email module."""

    class Priority(models.TextChoices):
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"
        URGENT = "urgent"

    message_id = models.CharField(
        max_length=500, unique=True, db_index=True,
        help_text="RFC Message-ID header for deduplication",
    )
    uid = models.CharField(max_length=100, blank=True, default="")
    from_addr = models.CharField(max_length=500)
    subject = models.CharField(max_length=1000, blank=True, default="")
    body_preview = models.TextField(blank=True, default="")
    priority = models.CharField(
        max_length=20, choices=Priority.choices, default=Priority.LOW,
    )
    notified = models.BooleanField(default=False)
    replied = models.BooleanField(default=False)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "modules"
        ordering = ["-processed_at"]

    def __str__(self):
        return f"Email from {self.from_addr}: {self.subject[:60]}"
