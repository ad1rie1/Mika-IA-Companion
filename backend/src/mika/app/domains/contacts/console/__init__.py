"""La part de l'annuaire dans la console (ADR 0298, 0310) : l'annuaire tel que la console le montre
(``directory.py`` : une entrée, à qui est un contact, la liste), son onglet de Personnes (``tabs.py`` : Annuaire), la
fiche dessinée d'un contact (``subject.py``), sa part de la file « À valider » (``queue.py``), ses deux onglets de la
fiche d'une personne, Ce qui l'identifie et Contacts (``person.py``), leurs gabarits (``templates/``) et leur feuille
(``static/`` : ``handmade/personnes_annuaire.css``, que la fiche d'une personne charge par sa part,
``PersonPart.styles``), sous les noms et aux adresses qu'ils avaient dans l'inspecteur.

Ce que les pages du cadre dessinent aussi reste dans l'inspecteur : les gabarits de Personnes (sa vue d'ensemble, Liens,
Présents, ce qu'ils partagent — ``handmade/personnes/``), et sa feuille, ``handmade/personnes.css``, que la fiche
d'une personne charge aussi (``app/handmade/person/``).
"""

from __future__ import annotations

from pathlib import Path

from mika.app.domains.contacts.console.person import PERSON_PART
from mika.app.domains.contacts.console.queue import QUEUE
from mika.app.domains.contacts.console.subject import ContactFiche
from mika.app.domains.contacts.console.tabs import TABS
from mika.app.domains.domain import ConsolePart
from mika.inspector.ui import console_folder
from mika.plugins.contacts.inspect import KIND

console_folder(Path(__file__).parent)

CONSOLE = ConsolePart(overviews={KIND: ContactFiche()}, drawn=TABS, queue=QUEUE, person=PERSON_PART)
