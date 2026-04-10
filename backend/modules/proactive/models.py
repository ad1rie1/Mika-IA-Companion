from django.db import models


class ProactiveLog(models.Model):
    """Tracks proactive messages to prevent spam and enable analysis."""

    class TriggerType(models.TextChoices):
        IDLE_CHAT = "idle_chat"
        MOOD_OVERFLOW = "mood_overflow"
        MEMORY_RECALL = "memory_recall"
        TIME_GREETING = "time_greeting"

    trigger = models.CharField(max_length=30, choices=TriggerType.choices)
    prompt_context = models.TextField(help_text="Context sent to Claude")
    response = models.TextField(blank=True, default="")
    emotion = models.CharField(max_length=30, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "modules"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Proactive [{self.trigger}] at {self.created_at:%H:%M}"
