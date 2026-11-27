"""La part de la carte dans la console (ADR 0310) : ses rubriques de réglages (``settings.py`` : Réglages › Carte et
téléphone, sauf les notifications du téléphone), et l'onglet Voyages et l'onglet Sa position de la fiche d'une
personne, avec le GPX d'un voyage (``person.py``), et leurs gabarits (``templates/``), sous les noms qu'ils avaient
dans l'inspecteur ; les morceaux des pages de la localisation (``location.py`` : une position, ce que les téléphones
lui ont dit), que Sa position et Ses sens › Localisation dessinent tous deux. Ce qu'ils partagent avec ses sens reste
dans l'inspecteur : les morceaux de gabarit de ces pages (``handmade/sens/macros.html``) et leur feuille
(``handmade/sens.css``). Ses sens › Localisation est dessinée par ses sens.
"""

from __future__ import annotations

from pathlib import Path

from mika.app.domains.domain import ConsolePart
from mika.app.domains.maps.console.person import PERSON_PART
from mika.app.domains.maps.console.settings import sections
from mika.inspector.ui import console_folder

console_folder(Path(__file__).parent)

CONSOLE = ConsolePart(sections=sections, person=PERSON_PART)
