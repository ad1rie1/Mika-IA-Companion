"""La part du téléphone dans la console (ADR 0120, 0177, 0310) : le mot de son canal, quand une demande d'accord le
pose en contexte — jamais une personne. Ses pages sont celles de Ses sens et de la fiche d'une personne."""

from __future__ import annotations

from mika.app.domains.domain import ConsolePart, QueuePart
from mika.contracts import phone as phone_c

CONSOLE = ConsolePart(queue=QueuePart(channels={phone_c.OWNER: "téléphone"}))
