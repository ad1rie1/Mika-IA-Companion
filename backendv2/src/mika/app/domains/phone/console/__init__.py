"""La part du téléphone dans la console (ADR 0120, 0177, 0310) : le mot de son canal, quand une demande d'accord le
pose en contexte — jamais une personne ; l'onglet Son téléphone de la fiche d'une personne (``person.py``) et son
gabarit (``templates/``), sous le nom qu'il avait dans l'inspecteur. Ce qu'il partage avec ses sens reste dans
l'inspecteur : les morceaux des pages du téléphone (``handmade/sens/macros.html``) et leur feuille
(``handmade/sens.css``). Ses autres pages sont celles de Ses sens."""

from __future__ import annotations

from pathlib import Path

from mika.app.domains.domain import ConsolePart, QueuePart
from mika.app.domains.phone.console.person import PERSON_PART
from mika.contracts import phone as phone_c
from mika.inspector.ui import console_folder

console_folder(Path(__file__).parent)

CONSOLE = ConsolePart(queue=QueuePart(channels={phone_c.OWNER: "téléphone"}), person=PERSON_PART)
