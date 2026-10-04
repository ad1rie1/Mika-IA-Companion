"""Persistence layer for user-editable config.

Three tables:

  ConfigValue       one-row override per key. Absent row = use schema default.
  ConfigRecordItem  rows of a ``record_list`` (one physical row per list
                    element — clean per-row audit + ordering).
  ConfigChangeLog   append-only audit trail. Sensitive diffs scrubbed.

All JSON values go through JSONField so numeric/boolean types are
preserved on round-trip.
"""
from __future__ import annotations

import uuid

from django.db import models


class ConfigValue(models.Model):
    """Scalar override for a single ConfigItem."""

    key = models.CharField(max_length=200, unique=True)
    value_json = models.JSONField(null=True, blank=True)
    # For secret items, this flag tells the service to run value_json
    # through decrypt() before handing out.
    encrypted = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["key"])]
        ordering = ["key"]

    def __str__(self):
        return f"{self.key} ({'enc' if self.encrypted else 'raw'})"


class ConfigRecordItem(models.Model):
    """One element of a record_list configuration.

    ``parent_key`` = the key of the enclosing ``ConfigItem`` (e.g.
    ``email.accounts``). ``row_id`` is a stable UUID — the handle
    modules use as a foreign key into their own domain models.
    """

    parent_key = models.CharField(max_length=200)
    row_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    payload = models.JSONField(default=dict)
    # Per-field encryption bookkeeping: list of field names that were
    # encrypted so read path knows what to decrypt.
    encrypted_fields = models.JSONField(default=list, blank=True)
    enabled = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["parent_key", "order"]),
            models.Index(fields=["row_id"]),
        ]
        ordering = ["parent_key", "order", "id"]

    def __str__(self):
        return f"{self.parent_key}[{self.order}] {self.row_id}"


class ConfigChangeLog(models.Model):
    """Audit trail. Never shown to Mika; admin-only."""

    key = models.CharField(max_length=200)
    row_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=20)  # set | unset | row_add | row_update | row_delete
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    actor = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["key", "-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.action} {self.key}"
