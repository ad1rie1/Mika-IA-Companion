from django.db import models


class EmailAccount(models.Model):
    """An email account (IMAP + SMTP) managed by the email module."""

    name = models.CharField(max_length=100, help_text="Display name (e.g. 'Gmail Perso')")
    email_address = models.EmailField(unique=True)
    imap_host = models.CharField(max_length=255)
    imap_port = models.PositiveIntegerField(default=993)
    imap_user = models.CharField(max_length=255)
    imap_password = models.CharField(max_length=255)
    smtp_host = models.CharField(max_length=255, blank=True, default="")
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_user = models.CharField(max_length=255, blank=True, default="")
    smtp_password = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "modules"

    def __str__(self):
        return f"{self.name} ({self.email_address})"

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user)


class Email(models.Model):
    """A stored email (inbound or outbound)."""

    class Direction(models.TextChoices):
        INBOUND = "inbound"
        OUTBOUND = "outbound"

    class Priority(models.TextChoices):
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"
        URGENT = "urgent"

    account = models.ForeignKey(
        EmailAccount, on_delete=models.CASCADE, related_name="emails",
    )
    message_id = models.CharField(
        max_length=500, db_index=True,
        help_text="RFC Message-ID header for deduplication",
    )
    uid = models.CharField(max_length=100, blank=True, default="")
    in_reply_to = models.CharField(max_length=500, blank=True, default="")
    references = models.TextField(blank=True, default="")
    from_address = models.CharField(max_length=500)
    to_addresses = models.TextField(help_text="Comma-separated")
    cc_addresses = models.TextField(blank=True, default="")
    subject = models.CharField(max_length=1000, blank=True, default="")
    body_text = models.TextField(blank=True, default="")
    body_html = models.TextField(blank=True, default="")
    has_attachments = models.BooleanField(default=False)
    direction = models.CharField(
        max_length=10, choices=Direction.choices, default=Direction.INBOUND,
    )
    priority = models.CharField(
        max_length=20, choices=Priority.choices, default=Priority.LOW,
    )
    is_read = models.BooleanField(default=False)
    notified = models.BooleanField(default=False)
    replied = models.BooleanField(default=False)
    email_date = models.DateTimeField(null=True, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "modules"
        ordering = ["-email_date"]
        unique_together = [("account", "message_id")]

    def __str__(self):
        return f"{self.from_address}: {self.subject[:60]}"


class Contact(models.Model):
    """A contact auto-populated from email traffic."""

    email_address = models.EmailField(unique=True, db_index=True)
    display_name = models.CharField(max_length=255, blank=True, default="")
    emails_received = models.PositiveIntegerField(default=0)
    emails_sent = models.PositiveIntegerField(default=0)
    accounts = models.ManyToManyField(EmailAccount, blank=True, related_name="contacts")
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        app_label = "modules"
        ordering = ["-last_seen"]

    def __str__(self):
        if self.display_name:
            return f"{self.display_name} <{self.email_address}>"
        return self.email_address
