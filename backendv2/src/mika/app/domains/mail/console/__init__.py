"""La part du courrier dans la console (ADR 0121, 0173, 0177, 0310) : ses onglets dessinés (``tabs.py``), ses trois
fiches — une boîte, un mail, un brouillon (``subject.py``) —, sa rubrique de réglages (``settings.py`` : Courrier ›
Paramètres), leurs gabarits (``templates/``), leur feuille et leurs scripts (``static/``), sous les noms et aux
adresses qu'ils avaient dans l'inspecteur.
"""

from __future__ import annotations

from pathlib import Path

from mika.app.domains.domain import ConsolePart
from mika.app.domains.mail.console.settings import sections
from mika.app.domains.mail.console.subject import ACCOUNT, DRAFT, MAIL, AccountFiche, DraftFiche, MailFiche
from mika.app.domains.mail.console.tabs import TABS
from mika.inspector.ui import console_folder

console_folder(Path(__file__).parent)

CONSOLE = ConsolePart(overviews={ACCOUNT: AccountFiche(), MAIL: MailFiche(), DRAFT: DraftFiche()}, drawn=TABS,
                      sections=sections)
