"""La part de la Forge dans la console (ADR 0104, 0310) : l'onglet dessiné des apps forgées (``tabs.py``), son gabarit
(``templates/``) et sa feuille (``static/``) — sous les noms et aux adresses qu'ils avaient dans l'inspecteur.
"""

from __future__ import annotations

from pathlib import Path

from mika.app.domains.domain import ConsolePart
from mika.app.domains.forge.console.queue import QUEUE
from mika.app.domains.forge.console.tabs import TABS
from mika.inspector.ui import console_folder

console_folder(Path(__file__).parent)

CONSOLE = ConsolePart(drawn=TABS, queue=QUEUE)
