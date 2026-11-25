"""Teams, tel que la couche ``app`` le relie (ADR 0069, 0186, 0251, 0300, 0301, 0310) : sa fiche.

Ce dossier porte sa porte HTTP (``desk.py`` : ``/api/teams/…``, qui est aussi le port ``teams_keys`` : les clés de
l'extension, une par compte), son câblage (``wiring.py`` : son cache, le port ``teams`` ; la porte ; l'extension à
télécharger), son module de l'API par personne (``api.py`` : ses comptes, leurs conversations, les réponses qu'elle y
prépare ; ce qui attend son geste, pour la barre du haut), l'extension à télécharger (``extension.py``) et ses pages
de console (``console/``).
"""

from __future__ import annotations

from mika.app.domains.domain import Base, Domain

TEAMS = Domain(
    "teams",
    base=Base("teams", models="mika.adapters.teams.models",
              place="ce que l'extension Teams a apporté, et ce qui doit en repartir"),
    wiring="mika.app.domains.teams.wiring",
    api="mika.app.domains.teams.api",
)
