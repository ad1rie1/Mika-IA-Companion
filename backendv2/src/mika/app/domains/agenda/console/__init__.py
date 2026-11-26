"""La part de l'agenda dans la console (ADR 0309, 0310) : ses onglets dessinés (``tabs.py``), la fiche d'un agenda
(``subject.py`` : où mène aussi un agenda partagé), l'onglet « Agendas » de la fiche d'une personne et son compte (``person.py``), ce qu'ils lisent
(``reads.py``), le tableau de droits d'un agenda, réglé dans Réglages › Droits (``rights.py``), sa rubrique de réglages (``settings.py`` : Agendas › Paramètres), leurs gabarits (``templates/`` : les
morceaux des pages « Agendas » aussi, ``handmade/agendas/_agendas.html``), leur script et leur feuille (``static/`` :
``handmade/agendas.css``, que la fiche d'une personne charge par sa part, ``PersonPart.styles``), sous les noms et aux
adresses qu'ils avaient dans l'inspecteur.
"""

from __future__ import annotations

from pathlib import Path

from mika.app.domains.agenda.console.person import PERSON_PART
from mika.app.domains.agenda.console.queue import QUEUE
from mika.app.domains.agenda.console.rights import TABLE
from mika.app.domains.agenda.console.settings import sections
from mika.app.domains.agenda.console.subject import KIND, AgendaFiche, shared
from mika.app.domains.agenda.console.tabs import TABS
from mika.app.domains.domain import ConsolePart
from mika.inspector.ui import console_folder

console_folder(Path(__file__).parent)

CONSOLE = ConsolePart(overviews={KIND: AgendaFiche()}, drawn=TABS, sections=sections, queue=QUEUE,
                      person=PERSON_PART, shared=shared, table=TABLE)
