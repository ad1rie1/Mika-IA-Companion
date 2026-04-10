"""Conscience models — observations and decision logs."""

from django.db import models


class Observation(models.Model):
    """A signal observed, interpreted, and stored by the Conscience.

    This is the Conscience's short-term buffer. Each module event or
    external signal becomes an Observation after interpretation.
    """

    class Category(models.TextChoices):
        COMMUNICATION = "communication"  # email, telegram, chat
        EMOTIONAL = "emotional"          # mood overflow, shift
        MEMORY = "memory"                # souvenir surfacing
        TEMPORAL = "temporal"            # time-based triggers
        EXTERNAL = "external"            # RSS, news, APIs (future)
        SYSTEM = "system"                # wake, connect, startup

    # Raw signal
    source = models.CharField(max_length=100)
    event_type = models.CharField(max_length=100)
    raw_data = models.JSONField(default=dict)

    # Interpretation (filled by interpreter pipeline)
    summary = models.TextField(blank=True)
    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        default=Category.SYSTEM,
    )
    pertinence = models.FloatField(default=0.5)
    emotional_reaction = models.CharField(max_length=30, blank=True, default="")
    emotional_intensity = models.FloatField(default=0.0)

    # Memory link (if this observation created a souvenir)
    souvenir = models.ForeignKey(
        "memory.Souvenir",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="observations",
    )

    # Decision tracking — state machine replaces simple acted_upon boolean
    class Status(models.TextChoices):
        PENDING = "pending"    # Awaiting decision
        ACTED = "acted"        # Decision made, action taken
        SKIPPED = "skipped"    # Evaluated but below threshold
        FAILED = "failed"      # Action attempted but failed

    acted_upon = models.BooleanField(default=False)  # kept for backward compat
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    action_response = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at", "acted_upon"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["category", "-pertinence"]),
        ]

    def __str__(self):
        return f"[{self.source}/{self.event_type}] {self.summary[:60]}"


class ConscienceLog(models.Model):
    """Trace of each conscience decision cycle."""

    observations_count = models.IntegerField(default=0)
    max_pertinence = models.FloatField(default=0.0)
    global_mood = models.CharField(max_length=30, blank=True, default="")
    global_intensity = models.FloatField(default=0.0)
    idle_seconds = models.IntegerField(default=0)
    decision = models.CharField(max_length=30)  # "act" | "wait" | "skip"
    reason = models.CharField(max_length=200, blank=True, default="")
    memory_actions = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.decision}] {self.reason[:60]} ({self.created_at:%H:%M})"


class ScheduledAction(models.Model):
    """A deferred action scheduled by the conscience or Claude.

    Created via the schedule_action tool. Picked up by the conscience
    decision loop when scheduled_at <= now, contributing to the score
    as Factor 6. Executed during _act() alongside pending observations.
    """

    class Status(models.TextChoices):
        PENDING = "pending"
        EXECUTED = "executed"
        CANCELLED = "cancelled"

    scheduled_at = models.DateTimeField()
    prompt = models.TextField()
    priority = models.FloatField(default=0.5)
    source = models.CharField(max_length=50)
    context_data = models.JSONField(default=dict)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["scheduled_at"]
        indexes = [
            models.Index(fields=["status", "scheduled_at"]),
        ]

    def __str__(self):
        return f"[{self.status}] {self.prompt[:60]} @ {self.scheduled_at:%H:%M}"
