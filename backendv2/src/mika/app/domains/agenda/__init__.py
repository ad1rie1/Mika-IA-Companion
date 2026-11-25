"""L'agenda, tel que la couche ``app`` le relie (ADR 0310) : sa fiche.

Pour l'heure elle ne dit que sa base ; le reste de ce qu'``app`` sait de lui la rejoint, lot par lot.
"""

from __future__ import annotations

from mika.app.domains.domain import Base, Domain

AGENDA = Domain(
    "agenda",
    base=Base("agenda", models="mika.adapters.agenda.models",
              place="les agendas : ceux de ce serveur, et la copie de ceux qu'on a branchés"),
)
