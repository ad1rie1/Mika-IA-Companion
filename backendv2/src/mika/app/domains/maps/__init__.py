"""La carte et les voyages (ADR 0193–0196, 0244–0245, 0256, 0295) et la localisation (ADR 0119), tels que la couche
``app`` les relie (ADR 0310) : leur fiche.

Ce dossier porte leur module de l'API par personne (``api.py`` : le fond de carte, les lieux, les fiches, les
événements, les photos, les adresses, les itinéraires et tes voyages), leur commande (``cli.py`` : ``mika carte``) et
les points du réchauffage des caches de la carte (``warm_points.py`` : la dernière position de chacun).
"""

from __future__ import annotations

from mika.app.domains.domain import Domain

MAPS = Domain(
    "maps",
    cli="mika.app.domains.maps.cli",
)
