"""Les réveils par API, tels que la couche ``app`` les relie (ADR 0068, 0310) : leur fiche.

Ce dossier porte leur porte HTTP (``desk.py`` : ``POST /api/wake/<nom>``, le port ``wakeup``), leurs réglages et leurs
clés (``settings.py``) et leur câblage (``wiring.py``). Leurs pages de console et leur commande le rejoindront.
"""

from __future__ import annotations

from mika.app.domains.domain import Domain

WAKEUP = Domain(
    "wakeup",
    needs=("projects",),
    wiring="mika.app.domains.wakeup.wiring",
)
