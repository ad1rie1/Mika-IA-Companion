"""Le courrier, tel que la couche ``app`` le relie (ADR 0310) : sa fiche.

Pour l'heure elle ne dit que sa base ; le reste de ce qu'``app`` sait de lui la rejoint, lot par lot.
"""

from __future__ import annotations

from mika.app.domains.domain import Base, Domain

MAIL = Domain(
    "mail",
    base=Base("mail", models="mika.adapters.mail.models",
              place="le courrier relevé, avec ses pièces jointes et ses images"),
    settings="mika.app.domains.mail.settings",
    wiring="mika.app.domains.mail.wiring",
    api="mika.app.domains.mail.api",
    live="mika.app.domains.mail.live",
)
