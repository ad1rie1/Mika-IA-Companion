"""Ses sens (ses flux, sa caméra, ses appareils), tel que la couche ``app`` le relie (ADR 0310) : sa fiche.

Ce dossier porte sa part de la console (``console/`` : les onglets de Ses sens et leurs gabarits). Ses onglets
montrent aussi les messages du téléphone et sa localisation, rangés dans la même destination : ils lisent le
téléphone et la carte. Pour l'heure la fiche ne dit que sa base et ces besoins ; le reste de ce qu'``app`` sait de
lui la rejoint.
"""

from __future__ import annotations

from mika.app.domains.domain import Base, Domain

SENSES = Domain(
    "senses",
    needs=("maps", "phone"),
    base=Base("feeds", models="mika.adapters.feeds.models",
              place="les flux suivis et leurs articles"),
)
