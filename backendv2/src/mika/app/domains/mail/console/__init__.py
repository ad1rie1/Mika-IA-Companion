"""La part du courrier dans la console (ADR 0121, 0177, 0310) : ses onglets dessinés (``tabs.py``), ses trois fiches —
une boîte, un mail, un brouillon (``subject.py``) —, leurs gabarits (``templates/``), leur feuille et leurs scripts
(``static/``), sous les noms et aux adresses qu'ils avaient dans l'inspecteur.
"""

from __future__ import annotations

from pathlib import Path

from mika.inspector.ui import console_folder

console_folder(Path(__file__).parent)
