"""La part de l'annuaire dans la console (ADR 0298, 0310) : la fiche dessinée d'un contact (``subject.py``), sa part
de la file « À valider » (``queue.py``) et ses deux onglets de la fiche d'une personne, Ce qui l'identifie et
Contacts (``person.py``).

Ses gabarits sont encore sous ``inspector/templates/handmade/`` ; ils rejoindront ce dossier, avec ceux de Personnes
qu'ils côtoient (``handmade/personnes/``).
"""

from __future__ import annotations

from mika.app.domains.contacts.console.person import PERSON_PART
from mika.app.domains.contacts.console.queue import QUEUE
from mika.app.domains.contacts.console.subject import ContactFiche
from mika.app.domains.domain import ConsolePart
from mika.plugins.contacts.inspect import KIND

CONSOLE = ConsolePart(overviews={KIND: ContactFiche()}, queue=QUEUE, person=PERSON_PART)
