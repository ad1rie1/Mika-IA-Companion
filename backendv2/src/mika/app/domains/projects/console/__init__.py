"""La part des projets dans la console (ADR 0121, 0177, 0297, 0310) : Activité › Projets (``tabs.py``), la fiche d'un
projet (``subject.py``) et ses onglets — en liste et détail (``zones.py`` : ``goals.py``, ``diagram.py``,
``tickets.py``), son code (``code.py``) et son dépôt face au distant (``git.py``), sa documentation (``docs.py``), ses
dépendances (``links.py``), son activité (``activity.py``) —, sa rubrique de réglages (``settings.py`` : Dépôts
Git), l'onglet Projets de la fiche d'une personne et son compte (``person.py``), sa sorte dans Réglages › Droits
(``RIGHTS`` : un projet par ligne, son tableau réglé sur sa fiche, onglet Accès), leurs gabarits (``templates/``),
leurs feuilles et leur script (``static/``), sous les noms et aux adresses qu'ils avaient dans l'inspecteur.
"""

from __future__ import annotations

from pathlib import Path

from mika.app.domains.domain import ConsolePart, RightsSort
from mika.app.domains.projects.console.person import PERSON_PART
from mika.app.domains.projects.console.queue import QUEUE
from mika.app.domains.projects.console.settings import sections
from mika.app.domains.projects.console.subject import KIND, ProjectFiche
from mika.app.domains.projects.console.tabs import TABS
from mika.inspector.ui import console_folder

console_folder(Path(__file__).parent)

#: sa sorte dans Réglages › Droits : un projet par ligne ; ce qu'une personne a de chacun, rangé sous « projets »
RIGHTS = RightsSort("projets", title="Projets", hint="le voir, le piloter, ses fichiers, ses apps",
                    prefix="project:", sort="projets")

CONSOLE = ConsolePart(overviews={KIND: ProjectFiche()}, drawn=TABS, sections=sections, queue=QUEUE,
                      person=PERSON_PART, rights=RIGHTS)
