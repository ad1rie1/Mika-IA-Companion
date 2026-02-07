from django.db import models


class WakeRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        PROCESSED = "processed"

    source = models.CharField(max_length=50, default="cron")
    prompt = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Wake #{self.pk} [{self.status}] from {self.source}"
