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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"[{self.role}] {self.content[:60]}"


class Memory(models.Model):
    summary = models.TextField()
    keywords = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "memories"

    def __str__(self):
        return self.summary[:80]


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
    """An episodic memory — a log of something that happened.
    Importance decays over time; very old souvenirs get pruned."""

    content = models.TextField()
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

    def __str__(self):
        return f"[{self.importance:.1f}] {self.content[:80]}"


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

    def __str__(self):
        valid = "valid" if self.is_valid else "INVALID"
        return f"[{valid} {self.confidence:.1f}] {self.content[:80]}"


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
