"""La Forge, telle que la couche ``app`` la relie (ADR 0104, 0310) : sa fiche.

Ce dossier porte le port ``forge_settings`` (``store.py`` : les réglages d'une app forgée, rangés par les réglages du
serveur) et sa part de la console (``console/`` : l'onglet Apps forgées, son gabarit et sa feuille).
"""

from __future__ import annotations

from mika.app.domains.domain import Domain

FORGE = Domain(
    "forge",
)
