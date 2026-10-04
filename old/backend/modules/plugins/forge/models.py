"""Modèles Django du système Forge.

Deux tables partagées par TOUS les modules forgés — les modules IA n'ont
jamais de DDL : leur « base de données » est un espace clé/valeur par
collections, quota-isé, dans ``ForgeRecord``.
"""

from django.db import models


class ForgeRecord(models.Model):
    """Une entrée de stockage d'un module forgé.

    L'espace de nommage est (module, collection, key) — l'API sandbox
    ``api.storage`` ne peut lire/écrire que dans son propre ``module_name``.
    """

    module_name = models.CharField(max_length=64, db_index=True)
    collection = models.CharField(max_length=64, default="default")
    key = models.CharField(max_length=128)
    value = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "modules"
        unique_together = [("module_name", "collection", "key")]
        ordering = ["module_name", "collection", "key"]

    def __str__(self):
        return f"{self.module_name}/{self.collection}/{self.key}"


class ForgeLog(models.Model):
    """Journal par module forgé : logs applicatifs (api.log/print) et
    événements système (chargement, erreurs, disjoncteur, commandes)."""

    class Level(models.TextChoices):
        DEBUG = "debug"
        INFO = "info"
        WARNING = "warning"
        ERROR = "error"

    module_name = models.CharField(max_length=64, db_index=True)
    level = models.CharField(
        max_length=16, choices=Level.choices, default=Level.INFO
    )
    source = models.CharField(
        max_length=32, default="system",
        help_text="system | tick | event | view | context | tool | test | print",
    )
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "modules"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.module_name}/{self.level}] {self.message[:60]}"
