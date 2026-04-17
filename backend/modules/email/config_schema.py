"""Config schema for the email module.

Account storage is owned by ``modules.email.models.EmailAccount`` — the
module has its own DB table, migrations, and (future) dashboard page
for the multi-account list. The generic config UI exposes *only* the
scalar knobs that drive the polling/analyzer layer.
"""
from __future__ import annotations

from configs.types import ConfigSection

CONFIG_SCHEMA = [
    ConfigSection(
        key="module_email", label="Modules · Email", icon="✉", order=71,
        description="Comptes gérés dans la table EmailAccount (page dédiée).",
    ),
]
