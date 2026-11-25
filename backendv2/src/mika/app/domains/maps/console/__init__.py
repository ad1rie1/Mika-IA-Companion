"""La part de la carte dans la console (ADR 0310) : ses rubriques de réglages (``settings.py`` : Réglages › Carte et
téléphone, sauf les notifications du téléphone), et l'onglet Voyages et l'onglet Sa position de la fiche d'une
personne, avec le GPX d'un voyage (``person.py``). Ses sens › Localisation est dessinée par ses sens.
"""

from __future__ import annotations

from mika.app.domains.domain import ConsolePart
from mika.app.domains.maps.console.person import PERSON_PART
from mika.app.domains.maps.console.settings import sections

CONSOLE = ConsolePart(sections=sections, person=PERSON_PART)
