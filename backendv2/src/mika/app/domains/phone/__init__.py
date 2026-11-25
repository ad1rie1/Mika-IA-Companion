"""Les messages du téléphone, tels que la couche ``app`` les relie (ADR 0120, 0310) : leur fiche.

Ce dossier porte leur porte HTTP (``desk.py`` : ``/api/phone/…``, le port ``phone``) et leur module de l'API par
personne (``api.py`` : ses téléphones, ses messages, sa position, l'application à télécharger). Sa position se lit
dans la localisation : il lit la carte.
"""

from __future__ import annotations

from mika.app.domains.domain import Domain

PHONE = Domain(
    "phone",
    needs=("maps",),
)
