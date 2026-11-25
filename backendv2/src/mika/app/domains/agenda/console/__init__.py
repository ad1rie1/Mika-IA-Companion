"""La part de l'agenda dans la console (ADR 0309, 0310) : ses onglets dessinés (``tabs.py``), la fiche d'un agenda
(``subject.py``), ce qu'ils lisent (``reads.py``, que l'onglet « Agendas » de la fiche d'une personne lit aussi), sa
rubrique de réglages (``settings.py`` : Agendas › Paramètres), leurs gabarits (``templates/``) et leur script
(``static/``), sous les noms et aux adresses qu'ils avaient dans l'inspecteur. Ce qu'ils partagent avec la fiche d'une
personne reste dans l'inspecteur : les morceaux des pages « Agendas » (``handmade/agendas/_agendas.html``) et leur
feuille (``handmade/agendas.css``).
"""

from __future__ import annotations

from pathlib import Path

from mika.app.domains.agenda.console.settings import sections
from mika.app.domains.agenda.console.subject import KIND, AgendaFiche
from mika.app.domains.agenda.console.tabs import TABS
from mika.app.domains.domain import ConsolePart
from mika.inspector.ui import console_folder

console_folder(Path(__file__).parent)

CONSOLE = ConsolePart(overviews={KIND: AgendaFiche()}, drawn=TABS, sections=sections)
