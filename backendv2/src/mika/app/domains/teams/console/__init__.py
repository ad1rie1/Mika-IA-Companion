"""La part de Teams dans la console (ADR 0069, 0177, 0310) : ses onglets dessinés (``tabs.py``), ses deux fiches —
une conversation, une réponse qu'elle a préparée (``subject.py``) —, leurs gabarits (``templates/``) et leur feuille
(``static/``), sous les noms et aux adresses qu'ils avaient dans l'inspecteur ; sa rubrique de réglages
(``settings.py`` : Teams › Paramètres).
"""

from __future__ import annotations

from pathlib import Path

from mika.app.domains.domain import ConsolePart
from mika.app.domains.teams.console.settings import sections
from mika.app.domains.teams.console.subject import CONVERSATION, REPLY, ConversationFiche, ReplyFiche
from mika.app.domains.teams.console.tabs import TABS
from mika.inspector.ui import console_folder

console_folder(Path(__file__).parent)

CONSOLE = ConsolePart(overviews={CONVERSATION: ConversationFiche(), REPLY: ReplyFiche()}, drawn=TABS,
                      sections=sections)
