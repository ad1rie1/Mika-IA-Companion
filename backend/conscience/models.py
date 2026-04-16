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

    class Status(models.TextChoices):
        PENDING = "pending"    # Awaiting decision
        ACTED = "acted"        # Decision made, action taken
        SKIPPED = "skipped"    # Evaluated but below threshold
        FAILED = "failed"      # Action attempted but failed

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    action_response = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
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


class Rumination(models.Model):
    """A persistent thought — a signal that was perceived as pertinent
    but never acted upon, that Mika keeps turning over in her head.

    Lifecycle:
      - created from an Observation that stayed pending > 30 min
        while having pertinence >= 0.5
      - decays ~5% intensity per decision cycle
      - bleeds emotional charge into global mood each cycle
      - status="resolved" when Mika speaks (intensity halved, may drop
        below 0.1 threshold) and "faded" when it decays out on its own
    """

    class Status(models.TextChoices):
        ACTIVE = "active"
        RESOLVED = "resolved"    # Mika spoke about it / got it off her chest
        FADED = "faded"          # Decayed naturally below threshold

    summary = models.TextField()
    themes = models.JSONField(default=list)
    # Emotional label (uses the 29-emotion vocabulary) that tints mood
    # while the rumination is active. Empty means no bleed.
    emotion = models.CharField(max_length=30, blank=True, default="")
    intensity = models.FloatField(default=0.5)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE,
    )
    observation = models.ForeignKey(
        "conscience.Observation",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="ruminations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-intensity", "-created_at"]
        indexes = [
            models.Index(fields=["status", "-intensity"]),
        ]

    def __str__(self):
        return f"[{self.status}:{self.intensity:.2f}] {self.summary[:60]}"


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
