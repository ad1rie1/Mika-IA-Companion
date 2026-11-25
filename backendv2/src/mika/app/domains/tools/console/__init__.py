"""La part de ses outils venus d'ailleurs dans la console (ADR 0064, 0310) : la fiche dessinée d'un service branché
(``subject.py``), sa rubrique de réglages (``settings.py`` : la connexion de chaque serveur MCP, Ses outils ›
Paramètres) et ses gabarits (``templates/``), sous les noms et aux adresses qu'ils avaient dans l'inspecteur. Sa
feuille, ``handmade/outils.css``, reste dans l'inspecteur : les onglets de Ses outils, qui sont du cadre, la lisent
aussi.
"""

from __future__ import annotations

from pathlib import Path

from mika.app.domains.domain import ConsolePart
from mika.app.domains.tools.console.queue import QUEUE
from mika.app.domains.tools.console.settings import sections
from mika.app.domains.tools.console.subject import KIND, ServerOverview
from mika.inspector.ui import console_folder

console_folder(Path(__file__).parent)

CONSOLE = ConsolePart(overviews={KIND: ServerOverview()}, sections=sections, queue=QUEUE)
