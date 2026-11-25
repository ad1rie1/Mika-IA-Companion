"""Ses sens (ses flux, sa caméra, ses appareils), tel que la couche ``app`` le relie (ADR 0310) : sa fiche.

Pour l'heure elle ne dit que sa base ; le reste de ce qu'``app`` sait de lui la rejoint, lot par lot.
"""

from __future__ import annotations

from mika.app.domains.domain import Base, Domain

SENSES = Domain(
    "senses",
    base=Base("feeds", models="mika.adapters.feeds.models",
              place="les flux suivis et leurs articles"),
)
