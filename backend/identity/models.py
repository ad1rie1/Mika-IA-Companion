"""Identity layer — the durable bridge between who memory talks ABOUT and where
Mika can REACH them, plus how sure she is that the two are the same person.

Conversation teaches Mika *names* (memory ``Entity`` of type ``person``: "Bob",
"X"). Delivery needs *handles* (``tg_123``, the web ``user_7`` group). This layer
joins the two so concern-based routing ("this news concerns X") can resolve to an
actual deliverable address.

- ``Identity``       — one canonical person, optionally linked to a memory Entity.
- ``IdentityHandle`` — one reachable address for that person on one channel.
- ``IdentityClaim``  — one piece of evidence for or against "this handle is X".

Reachability is *runtime* state (see ``communication.presence``); this layer is
the *persistent* knowledge that the address exists at all, so Mika can decide to
reach out to someone who isn't currently connected.

The certainty model lives in ``identity/trust.py`` (pure functions). The short
version: an authenticated session *proves* who you are, a platform account only
proves you came back, and a public room proves nothing — so on anything but a
login, being recognized is something you have to earn, claim by claim.
"""

from django.db import models

from identity.trust import Certainty


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
    # How sure Mika is that this identity really is `entity`. 0 when nothing
    # has been established. Moved by IdentityClaims, capped by the trust
    # ceiling of the channel the evidence arrived on (see identity.trust).
    certainty = models.FloatField(
        default=float(Certainty.UNKNOWN),
        help_text="0..1 — how sure Mika is this identity is the linked entity",
    )
    # Set when a claim is accepted or a session authenticates. Kept alongside
    # `certainty` so the dashboard can say *when* she decided to believe.
    bound_at = models.DateTimeField(null=True, blank=True)
    # Which channel produced the strongest evidence so far ("web", "telegram").
    bound_via = models.CharField(max_length=50, blank=True, default="")
    # Free-text trace of why she believes it, written by the accepting tool.
    binding_reason = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "identities"
        ordering = ["-last_seen"]
        indexes = [
            models.Index(fields=["entity"]),
            models.Index(fields=["-certainty"]),
        ]

    def __str__(self):
        return self.display_name or f"Identity #{self.pk}"

    @property
    def is_bound(self) -> bool:
        """True when Mika has actually settled on who this is."""
        return self.entity_id is not None and self.certainty >= float(Certainty.BOUND)


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

    # What the transport itself proves about this handle, at the time it was
    # last seen. Stored rather than recomputed because it is a property of
    # how the handle was established, and the ceiling it implies must hold
    # even when the person is offline (proactive outreach reads this too).
    trust = models.CharField(
        max_length=20, default="public",
        help_text="ChannelTrust value: authenticated | account | public | internal",
    )
    # Anonymous per-connection handles (anon_*) are bookkeeping, not people.
    # Flagged so the retention sweep can drop them without touching the
    # handles that represent someone Mika actually knows.
    is_ephemeral = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("channel", "person_id")]
        ordering = ["-last_seen"]
        indexes = [
            models.Index(fields=["person_id"]),
            models.Index(fields=["is_ephemeral", "last_seen"]),
        ]

    def __str__(self):
        return f"{self.person_id}@{self.channel}"


class IdentityClaim(models.Model):
    """One piece of evidence about who is behind a handle.

    Claims are how "se laisser convaincre" is made auditable: every reason
    Mika has to believe (or stop believing) that ``handle`` is ``claimed_name``
    is a row, with who produced it and what it was worth. The current
    certainty on ``Identity`` is the running total; this is the ledger.

    A claim starts ``PENDING``. Mika resolves it herself through the
    ``identity_*`` tools — accepting one binds the handle to a memory Entity
    and raises certainty; rejecting one records the doubt so the same
    assertion doesn't quietly get re-counted next turn.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        ACCEPTED = "accepted", "Acceptee"
        REJECTED = "rejected", "Rejetee"

    class Kind(models.TextChoices):
        # Weights for these live in identity.trust.EVIDENCE_WEIGHTS —
        # keep the values in sync with the keys there.
        SELF_DECLARED = "self_declared", "Dit qui il/elle est"
        PASSIVE_INFERENCE = "passive_inference", "Deduit passivement"
        SHARED_MEMORY = "shared_memory", "Sait quelque chose que seul X sait"
        VOUCHED = "vouched", "Presente par quelqu'un de confiance"
        AUTHENTICATED = "authenticated", "Prouve par le transport"
        CONTRADICTED = "contradicted", "S'est trompe sur un fait partage"
        DENIED = "denied", "Nie etre cette personne"
        REVOKED = "revoked", "Mika ne le croit plus"

    identity = models.ForeignKey(
        Identity, on_delete=models.CASCADE, related_name="claims",
    )
    handle = models.ForeignKey(
        IdentityHandle, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="claims",
    )
    # The name being asserted ("Thomas"). Matched against memory Entities by
    # name when the claim is accepted.
    claimed_name = models.CharField(max_length=200)
    kind = models.CharField(
        max_length=30, choices=Kind.choices, default=Kind.SELF_DECLARED,
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PENDING,
    )
    # What was said / observed, verbatim enough to re-judge later.
    evidence = models.TextField(blank=True, default="")
    # Channel the evidence arrived on — caps how much it can ever be worth.
    channel = models.CharField(max_length=50, blank=True, default="")
    trust = models.CharField(max_length=20, default="public")
    # Certainty delta actually applied when resolved (0 while pending).
    applied_weight = models.FloatField(default=0.0)
    # Mika's own words about why she accepted or rejected it.
    resolution_note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["identity", "status"]),
        ]

    def __str__(self):
        return f"[{self.status}] {self.claimed_name} ({self.kind})"
