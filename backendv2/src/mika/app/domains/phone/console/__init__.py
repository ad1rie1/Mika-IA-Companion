"""La part du téléphone dans la console (ADR 0120, 0177, 0310) : le mot de son canal, quand une demande d'accord le
pose en contexte — jamais une personne ; l'onglet Son téléphone de la fiche d'une personne (``person.py``). Ses autres
pages sont celles de Ses sens."""

from __future__ import annotations

from mika.app.domains.domain import ConsolePart, QueuePart
from mika.app.domains.phone.console.person import PERSON_PART
from mika.contracts import phone as phone_c

CONSOLE = ConsolePart(queue=QueuePart(channels={phone_c.OWNER: "téléphone"}), person=PERSON_PART)
