"""La part des projets dans la console (ADR 0121, 0177, 0297, 0310) : Activité › Projets (``tabs.py``), la fiche d'un
projet (``subject.py``) et ses onglets — en liste et détail (``zones.py`` : ``goals.py``, ``diagram.py``,
``tickets.py``), son code (``code.py``) et son dépôt face au distant (``git.py``), sa documentation (``docs.py``), ses
dépendances (``links.py``), son activité (``activity.py``) —, leurs gabarits (``templates/``), leurs feuilles et leur
script (``static/``), sous les noms et aux adresses qu'ils avaient dans l'inspecteur.
"""

from __future__ import annotations

from pathlib import Path

from mika.inspector.ui import console_folder

console_folder(Path(__file__).parent)
