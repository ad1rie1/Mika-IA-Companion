"""La part de la carte dans la console (ADR 0310) : ses rubriques de réglages (``settings.py`` : Réglages › Carte et
téléphone, sauf les notifications du téléphone). Elle n'a ni gabarit ni feuille à elle : l'onglet Voyages et l'onglet
Sa position de la fiche d'une personne, et Ses sens › Localisation, sont dessinés au cadre ou par ses sens.
"""

from __future__ import annotations

from mika.app.domains.domain import ConsolePart
from mika.app.domains.maps.console.settings import sections

CONSOLE = ConsolePart(sections=sections)
