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
    # Structural metadata for non-text parts of the originating perception
    # (images, audio, files). Binary content lives elsewhere (disk + media
    # model); this list records kind/mime/name/etc. so retrieval knows what
    # was attached without touching raw bytes.
    attachments_meta = models.JSONField(default=list, blank=True)
    # True for the scaffolding prompt of an INTERNAL_TRIGGER perception
    # ("Un visiteur vient de se connecter, accueille-le...", module
    # notify_ai briefs). Mika never heard those words from anyone, so the
    # consolidator must not mine them for souvenirs or connaissances — her
    # *reply* (role=assistant) is a real memory and stays included.
    is_internal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # pk as secondary sort — auto_now_add collides for rapid inserts
        ordering = ["created_at", "pk"]
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
    decayed_at = models.DateTimeField(
        null=True, blank=True,
        help_text=(
            "Anchor for time-based decay. Decay multiplies the CURRENT "
            "importance by rate^(days since this stamp), so conscience boosts "
            "and hand-set importances survive instead of being recomputed "
            "from age alone."
        ),
    )

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


class PersonProfile(models.Model):
    """Mika's model of another person — theory of mind.

    One row per person-type Entity. Synthesizes what Mika knows + assumes
    about this specific person: relational stance, preferred conversation
    style, topics they care about, topics to avoid. Regenerated by the
    consolidator when enough new material has accumulated about them.

    Complements:
      - PersonMood (emotion/) : how Mika *feels* toward them (dynamic PAD state)
      - This model          : what Mika *knows / assumes* about them (semantic)
    """

    class Closeness(models.TextChoices):
        STRANGER = "stranger", "Stranger"
        ACQUAINTANCE = "acquaintance", "Acquaintance"
        FRIEND = "friend", "Friend"
        CLOSE = "close", "Close"

    class PreferredTone(models.TextChoices):
        DIRECT = "direct", "Direct"
        GENTLE = "gentle", "Gentle"
        PLAYFUL = "playful", "Playful"
        FORMAL = "formal", "Formal"
        UNKNOWN = "unknown", "Unknown"

    entity = models.OneToOneField(
        Entity, on_delete=models.CASCADE, related_name="profile",
    )
    summary = models.TextField(
        blank=True, default="",
        help_text="Third-person paragraph: 'X est quelqu'un qui...'",
    )
    closeness = models.CharField(
        max_length=20, choices=Closeness.choices, default=Closeness.STRANGER,
    )
    preferred_tone = models.CharField(
        max_length=20, choices=PreferredTone.choices, default=PreferredTone.UNKNOWN,
    )
    topics_of_interest = models.JSONField(default=list)
    sensitive_topics = models.JSONField(default=list)
    # Bookkeeping — drives regeneration gating
    interaction_count = models.IntegerField(default=0)
    last_interaction_at = models.DateTimeField(null=True, blank=True)
    last_souvenir_id = models.IntegerField(default=0)
    confidence = models.FloatField(default=0.5)
    generated_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_interaction_at"]
        indexes = [
            models.Index(fields=["-last_interaction_at"]),
            models.Index(fields=["-generated_at"]),
        ]

    def __str__(self):
        return f"[{self.closeness}] {self.entity.name}: {self.summary[:60]}"


class Commitment(models.Model):
    """Something Mika said she'd do for someone.

    Detected by the extractor when Mika's own messages contain commitment
    language ("je te ferai...", "je te promets..."). Resolved when the
    conscience acts on it (honored) or when it ages out beyond `due_at`
    without action (dropped).

    Note: the person link is nullable — if Mika makes a generic commitment
    ("je ferai cette recette") without a clear addressee, we still want
    to track it.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        HONORED = "honored", "Honored"
        DROPPED = "dropped", "Dropped"

    description = models.TextField()
    person = models.ForeignKey(
        Entity, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="commitments_to_me",
        limit_choices_to={"entity_type": "person"},
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING,
    )
    due_at = models.DateTimeField(null=True, blank=True)
    # Where this came from — the souvenir that created it, if any.
    source_souvenir = models.ForeignKey(
        Souvenir, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="commitments",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["status", "-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["person", "status"]),
        ]

    def __str__(self):
        who = self.person.name if self.person else "—"
        return f"[{self.status}] to {who}: {self.description[:60]}"


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


class DailyJournal(models.Model):
    """First-person recap of a single day.

    Produced by the SleepCycle's light-sleep phase (between ~23h and midnight).
    Gives Mika a causal, narrative thread through the day's events —
    something the atomic Souvenirs cannot provide since they're disconnected.
    One row per calendar date; re-running the phase on the same day refreshes
    the narrative in place.
    """

    date = models.DateField(unique=True)
    narrative = models.TextField(
        help_text="First-person paragraph covering the day's arc.",
    )
    # Top souvenirs of the day, stored as ids (snapshot, not relational —
    # if a souvenir is pruned later, the journal still makes sense).
    key_moments = models.JSONField(default=list)
    dominant_emotion = models.CharField(max_length=30, blank=True, default="")
    persons_interacted = models.JSONField(default=list)
    # Snapshots of active ruminations at day's end. Stored as
    # [{"summary": "...", "emotion": "...", "intensity": 0.x}, ...].
    # Dream phase reads these to decide if a nightmare theme is warranted.
    unresolved_at_sleep = models.JSONField(default=list)
    word_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["-date"]),
        ]

    def __str__(self):
        return f"[{self.date}] {self.narrative[:80]}"


class Dream(models.Model):
    """A dream Mika had during sleep — a creative association built during
    the SleepCycle's REM phase.

    Dreams stitch together 2-3 recent souvenirs (potentially from distant
    themes) with optionally one active rumination, producing a short
    oneiric narrative that the LLM generates. High-vividness dreams can
    surface in the next morning's prompt so Mika can mention them.

    We never delete dreams on decay — they're rare, cheap to store,
    and form an auditable trace of the character's "inner life".
    """

    class DreamType(models.TextChoices):
        ASSOCIATIVE = "associative", "Associative"
        NIGHTMARE = "nightmare", "Nightmare"
        PLEASANT = "pleasant", "Pleasant"
        MUNDANE = "mundane", "Mundane"

    # "Night of" the dream — the calendar date the sleep cycle started on
    # (e.g. a dream at 03h on the 18th has night_of = 17). Used to group
    # dreams per night and to decide eligibility for morning recall.
    night_of = models.DateField()
    content = models.TextField(
        help_text="The dream narrative: 2-4 short sentences, first-person.",
    )
    dream_type = models.CharField(
        max_length=20,
        choices=DreamType.choices,
        default=DreamType.ASSOCIATIVE,
    )
    # 0 = barely recall it, 1 = vivid. Gates whether the dream is eligible
    # for morning prompt injection (threshold ~0.6).
    vividness = models.FloatField(default=0.5)
    source_souvenirs = models.ManyToManyField(
        Souvenir, blank=True, related_name="dreams",
    )
    source_rumination = models.ForeignKey(
        "conscience.Rumination",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="dreams",
    )
    emotion = models.CharField(
        max_length=30, blank=True, default="",
        help_text="Dominant emotion of the dream.",
    )
    # Set when the dream is first surfaced in a system prompt, so we
    # don't re-mention the same dream across multiple turns.
    recalled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-night_of"]),
            models.Index(fields=["recalled_at", "-vividness"]),
        ]

    def __str__(self):
        return f"[{self.night_of}|{self.dream_type}|{self.vividness:.1f}] {self.content[:60]}"
