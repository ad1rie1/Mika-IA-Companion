"""AI quota usage — per-role + per-project daily aggregates.

One row per (role, project_id, date). Project_id is nullable so non-project
calls (conversation, memory, emotion, etc.) still aggregate cleanly.
"""
from __future__ import annotations

from django.db import models


class AIQuotaUsage(models.Model):
    """Daily aggregated usage for a given (role, project) tuple.

    Rows are upserted by ``ai.quota.QuotaTracker.record`` after every
    successful LLM call. The tracker maintains in-RAM totals for fast
    limit checks; this table is the durable backing store used on
    startup to re-hydrate the tracker and by the HTTP endpoint.
    """

    role = models.CharField(max_length=40, db_index=True)
    # Null when the call was not attached to a specific project
    # (conversation, memory extraction, sleep cycle, conscience, ...).
    project_id = models.IntegerField(null=True, blank=True, db_index=True)
    date = models.DateField(db_index=True)

    provider = models.CharField(max_length=20, default="")
    model = models.CharField(max_length=80, default="")

    call_count = models.IntegerField(default=0)
    tokens_in = models.BigIntegerField(default=0)
    tokens_out = models.BigIntegerField(default=0)
    cost_usd = models.FloatField(default=0.0)

    last_at = models.DateTimeField(auto_now=True)

    class Meta:
        # One aggregate per (role, project, date, provider, model).
        # Provider+model are in the key because a role may be reconfigured
        # mid-day; we keep both breakdowns rather than overwriting.
        unique_together = ("role", "project_id", "date", "provider", "model")
        indexes = [
            models.Index(fields=["date", "role"]),
            models.Index(fields=["date", "project_id"]),
        ]

    def __str__(self):
        scope = f"project={self.project_id}" if self.project_id else "global"
        return (
            f"[{self.date}] {self.role} ({scope}) "
            f"{self.call_count} calls / {self.tokens_in + self.tokens_out} tok / "
            f"${self.cost_usd:.4f}"
        )
