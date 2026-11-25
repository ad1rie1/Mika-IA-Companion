"""La part de l'annuaire dans la console (ADR 0298, 0310) : la fiche dessinée d'un contact (``subject.py``).

Ses gabarits sont encore sous ``inspector/templates/handmade/`` ; ils rejoindront ce dossier. Les pages du cadre qui
croisent l'annuaire et d'autres domaines (l'annuaire de Personnes, À valider, la fiche d'une personne) lisent
``subject.py``.
"""

from __future__ import annotations

from mika.app.domains.contacts.console.subject import ContactFiche
from mika.app.domains.domain import ConsolePart
from mika.plugins.contacts.inspect import KIND

CONSOLE = ConsolePart(overviews={KIND: ContactFiche()})
