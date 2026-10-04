"""Persistent activation state for plugin modules.

Tracks, per module, whether it is currently enabled and which model
tables have been installed via schema_editor (vs. via Django's
standard migration pipeline). Used by ModuleManager to make
enable/disable/uninstall operations idempotent across restarts and
to install freshly declared model tables on boot.
"""

from django.db import models


class ModuleState(models.Model):
    """One row per known module. Created on first registration."""

    name = models.CharField(max_length=64, primary_key=True)
    enabled = models.BooleanField(
        default=True,
        help_text="Whether the module should be started at boot.",
    )
    installed_tables = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of db_table names created by schema_editor for "
            "unmanaged models owned by this module. Used for diffing "
            "on boot and for safe drop on uninstall."
        ),
    )
    schema_version = models.IntegerField(default=1)
    installed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "modules"
        ordering = ["name"]

    def __str__(self):
        flag = "on" if self.enabled else "off"
        return f"{self.name} [{flag}]"
