"""La part des dessins dans la console (ADR 0317) : leur rubrique de réglages (``settings.py`` : Réglages ›
Intelligence › Images, ses deux pages), sous les noms et aux adresses qu'elle avait au cadre. Ni gabarit ni feuille :
ses pages sont celles de tous les réglages."""

from __future__ import annotations

from mika.app.domains.domain import ConsolePart
from mika.app.domains.imaging.console.settings import sections

CONSOLE = ConsolePart(sections=sections)
