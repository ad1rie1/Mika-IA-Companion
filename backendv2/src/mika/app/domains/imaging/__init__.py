"""Les dessins, tels que la couche ``app`` les relie (ADR 0061, 0063, 0317) : leur fiche.

Une passerelle qu'un seul plugin sert est un domaine (ADR 0317). Ce dossier porte leurs réglages (``settings.py`` :
leurs fournisseurs d'images, la clé de chacun, scellée, et qui dessine quoi).
"""

from __future__ import annotations

from mika.app.domains.domain import Domain

IMAGING = Domain(
    "imaging",
    settings="mika.app.domains.imaging.settings",
)
