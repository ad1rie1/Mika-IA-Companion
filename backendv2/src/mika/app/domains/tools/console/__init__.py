"""La part de ses outils venus d'ailleurs dans la console (ADR 0064, 0310) : la fiche dessinée d'un service branché
(``subject.py``) et ses gabarits (``templates/``), sous les noms et aux adresses qu'ils avaient dans l'inspecteur. Sa
feuille, ``handmade/outils.css``, reste dans l'inspecteur : les onglets de Ses outils, qui sont du cadre, la lisent
aussi.
"""

from __future__ import annotations

from pathlib import Path

from mika.inspector.ui import console_folder

console_folder(Path(__file__).parent)
