"""Identity layer — the durable bridge between who memory talks ABOUT and where
Mika can REACH them.

Conversation teaches Mika *names* (memory ``Entity`` of type ``person``: "Bob",
"X"). Delivery needs *handles* (``tg_123``, the web ``user_7`` group). This layer
joins the two so concern-based routing ("this news concerns X") can resolve to an
actual deliverable address.

- ``Identity``       — one canonical person, optionally linked to a memory Entity.
- ``IdentityHandle`` — one reachable address for that person on one channel.

Reachability is *runtime* state (see ``communication.presence``); this layer is
the *persistent* knowledge that the address exists at all, so Mika can decide to
reach out to someone who isn't currently connected.
"""

from django.db import models


class Identity(models.Model):
    """A canonical person Mika knows, unifying memory presence and reachable handles."""

    display_name = models.CharField(max_length=200, blank=True, default="")
    # Link to the memory entity this person corresponds to (the name conversation
    # learns). Nullable: a handle may exist before memory has formed an entity.
    entity = models.ForeignKey(
        "memory.Entity",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="identities",
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "identities"
        ordering = ["-last_seen"]
        indexes = [models.Index(fields=["entity"])]

    def __str__(self):
        return self.display_name or f"Identity #{self.pk}"


class IdentityHandle(models.Model):
    """One reachable address for an identity on a given channel."""

    KINDS = [("consumer", "Consumer"), ("module", "Module")]

    identity = models.ForeignKey(
        Identity, on_delete=models.CASCADE, related_name="handles"
    )
    channel = models.CharField(max_length=50)            # "web", "telegram", "email"
    person_id = models.CharField(max_length=100, db_index=True)  # tg_123, user_7, ...
    kind = models.CharField(max_length=20, choices=KINDS, default="module")
    delivery_ref = models.CharField(max_length=255, blank=True, default="")  # chat_id / group
    display_name = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("channel", "person_id")]
        ordering = ["-last_seen"]
        indexes = [models.Index(fields=["person_id"])]

    def __str__(self):
        return f"{self.person_id}@{self.channel}"
