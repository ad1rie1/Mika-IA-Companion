"""Teams, tel que la couche ``app`` le relie (ADR 0310) : sa fiche.

Pour l'heure elle ne dit que sa base ; le reste de ce qu'``app`` sait de lui la rejoint, lot par lot.
"""

from __future__ import annotations

from mika.app.domains.domain import Base, Domain

TEAMS = Domain(
    "teams",
    base=Base("teams", models="mika.adapters.teams.models",
              place="ce que l'extension Teams a apporté, et ce qui doit en repartir"),
)
