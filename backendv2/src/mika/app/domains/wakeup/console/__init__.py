"""La part des réveils par API dans la console (ADR 0068, 0310) : leur onglet dessiné (``tabs.py``), la fiche d'un
réveil (``subject.py``), leur page de réglages (``settings.py``), leurs gabarits (``templates/``) et leur feuille (``static/``) — sous les noms et aux adresses
qu'ils avaient dans l'inspecteur.
"""

from __future__ import annotations

from pathlib import Path

from mika.app.domains.domain import ConsolePart
from mika.app.domains.wakeup.console.settings import sections
from mika.app.domains.wakeup.console.subject import KIND, WakeupFiche
from mika.app.domains.wakeup.console.tabs import TABS
from mika.inspector.ui import console_folder

console_folder(Path(__file__).parent)

CONSOLE = ConsolePart(overviews={KIND: WakeupFiche()}, drawn=TABS, sections=sections)
