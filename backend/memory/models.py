from django.db import models


class Conversation(models.Model):
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Conversation #{self.pk} ({self.started_at:%Y-%m-%d %H:%M})"


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=20)
    content = models.TextField()
    source = models.CharField(max_length=50, default="frontend")
    person_id = models.CharField(max_length=100, blank=True, default="")
    emotion = models.CharField(max_length=30, blank=True, default="")
    emotion_intensity = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["person_id", "created_at"]),
        ]

    def __str__(self):
        emotion_str = f" [{self.emotion}:{self.emotion_intensity:.1f}]" if self.emotion else ""
        return f"[{self.role}]{emotion_str} {self.content[:60]}"


# --- Contextual Memory System ---


class Theme(models.Model):
    """Reusable tag for categorizing memories (e.g. 'velo', 'cuisine', 'gaming')."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Entity(models.Model):
    """A person, object, place, or concept referenced in memories."""

    ENTITY_TYPES = [
        ("person", "Person"),
        ("object", "Object"),
        ("place", "Place"),
        ("concept", "Concept"),
    ]

    name = models.CharField(max_length=200)
    entity_type = models.CharField(max_length=50, choices=ENTITY_TYPES)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "entities"
        unique_together = [("name", "entity_type")]

    def __str__(self):
        return f"{self.name} ({self.entity_type})"


class Souvenir(models.Model):
    """An episodic memory — a log of something that happened, written from
    the VTuber's subjective point of view (colored by personality + emotion).
    Importance decays over time; very old souvenirs get pruned."""

    content = models.TextField()
    emotion = models.CharField(
        max_length=30, default="neutral",
        help_text="How the VTuber felt about this event",
    )
    themes = models.ManyToManyField(Theme, blank=True, related_name="souvenirs")
    entities = models.ManyToManyField(Entity, blank=True, related_name="souvenirs")
    importance = models.FloatField(default=1.0)
    occurred_at = models.DateTimeField()
    conversation = models.ForeignKey(
        Conversation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="souvenirs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["-importance"]),
            models.Index(fields=["-occurred_at"]),
        ]

    def __str__(self):
        return f"[{self.importance:.1f}/{self.emotion}] {self.content[:80]}"


class Connaissance(models.Model):
    """A durable knowledge fact about a person or thing.
    Can be invalidated if context changes, but requires persuasion."""

    content = models.TextField()
    themes = models.ManyToManyField(Theme, blank=True, related_name="connaissances")
    entities = models.ManyToManyField(Entity, blank=True, related_name="connaissances")
    confidence = models.FloatField(default=1.0)
    is_valid = models.BooleanField(default=True)
    source_souvenir = models.ForeignKey(
        Souvenir, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="derived_connaissances",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-confidence"]
        indexes = [
            models.Index(fields=["is_valid", "-confidence"]),
            models.Index(fields=["-updated_at"]),
        ]

    def __str__(self):
        valid = "valid" if self.is_valid else "INVALID"
        return f"[{valid} {self.confidence:.1f}] {self.content[:80]}"


class EmotionSnapshot(models.Model):
    """Periodic snapshot of the VTuber's emotional state."""
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="emotion_snapshots",
    )
    person_id = models.CharField(max_length=100, default="anonymous")
    primary_emotion = models.CharField(max_length=30)
    primary_intensity = models.FloatField()
    global_emotion = models.CharField(max_length=30, default="neutral")
    global_intensity = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"[{self.person_id}] {self.primary_emotion}:{self.primary_intensity:.1f} "
            f"(global: {self.global_emotion}) @ {self.created_at:%H:%M}"
        )


class EmotionalSummary(models.Model):
    """Aggregated emotional profile for a person over a time period.

    Built by the consolidator from raw EmotionSnapshots.
    Injected into the memory context so the VTuber remembers how she
    felt with each person over time.
    """

    PERIOD_CHOICES = [
        ("daily", "Daily"),
        ("weekly", "Weekly"),
    ]

    person_id = models.CharField(max_length=100, db_index=True)
    period_type = models.CharField(max_length=10, choices=PERIOD_CHOICES)
    period_start = models.DateField()
    dominant_emotion = models.CharField(max_length=30)
    dominant_intensity = models.FloatField(default=0.0)
    emotion_distribution = models.JSONField(default=dict)
    trend = models.CharField(max_length=20, default="stable")
    snapshot_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_start"]
        unique_together = [("person_id", "period_type", "period_start")]
        indexes = [
            models.Index(fields=["person_id", "-period_start"]),
        ]

    def __str__(self):
        return (
            f"[{self.person_id}] {self.period_type} {self.period_start}: "
            f"{self.dominant_emotion} ({self.trend})"
        )


class SelfNarrative(models.Model):
    """Mika's evolving autobiographical self-concept.

    Periodically regenerated by the consolidator from recent souvenirs +
    connaissances + emotional summaries. The most recent row is injected
    into the system prompt, so Mika has a running sense of "who she is
    becoming" that updates as her experiences accumulate.

    We keep the full history (one row per regeneration) so the evolution
    is auditable — you can see how the self-concept drifted over weeks.
    """

    content = models.TextField(
        help_text="First-person paragraph: 'Je suis quelqu'un qui...'",
    )
    # Top themes / people extracted from the source pool, stored as plain JSON
    # lists (no M2M — these are snapshots, not canonical references).
    key_themes = models.JSONField(default=list)
    key_people = models.JSONField(default=list)
    # Dominant emotional trend over the pool (derived from EmotionalSummary)
    dominant_mood = models.CharField(max_length=30, blank=True, default="")
    # Generator's self-reported confidence that this narrative is grounded.
    confidence = models.FloatField(default=0.7)
    # Bookkeeping so the consolidator can decide when to regenerate.
    source_souvenir_count = models.IntegerField(default=0)
    source_connaissance_count = models.IntegerField(default=0)
    # High-water mark of the souvenirs used — so we can tell "did N new
    # souvenirs accumulate since last narrative?" without re-reading all.
    last_souvenir_id = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"[{self.created_at:%Y-%m-%d}] {self.content[:80]}"


class ConsolidationLog(models.Model):
    """Tracks when the consolidation background task ran."""

    messages_processed = models.IntegerField()
    souvenirs_created = models.IntegerField(default=0)
    connaissances_created = models.IntegerField(default=0)
    last_message_id = models.IntegerField(default=0)
    ran_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-ran_at"]

    def __str__(self):
        return (
            f"Consolidation @ {self.ran_at:%H:%M}: "
            f"{self.souvenirs_created}S {self.connaissances_created}K"
        )
