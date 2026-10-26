"""Les fiches dessinées des objets qui n'avaient que les onglets de leur faculté (ADR 0121) : un but, un réveil, une
conversation et une réponse Teams, un compte, un mail, un brouillon. Chacune est une ``Overview`` dans son module ; la
composition les reçoit toutes ici (``OVERVIEWS``, par sorte d'objet). Les apps de la Forge gardent le rendu de la
console (``plain_owners``).

Chaque fiche dessine son en-tête et son onglet principal (ses formulaires sont ceux que la console a préparés) ; ses
autres onglets se dessinent bloc par bloc. Ce qu'elles partagent est dans ``fiche_parts.py``.
"""

from __future__ import annotations

from mika.app.handmade import goal, mail_fiches, teams_fiches, wakeup
from mika.inspector.ui import Overview

#: les vues d'ensemble de ces fiches, par sorte d'objet (``Inspection.subject``)
OVERVIEWS: dict[str, Overview] = {
    goal.KIND: goal.GoalFiche(),
    wakeup.KIND: wakeup.WakeupFiche(),
    teams_fiches.CONVERSATION: teams_fiches.ConversationFiche(),
    teams_fiches.REPLY: teams_fiches.ReplyFiche(),
    mail_fiches.ACCOUNT: mail_fiches.AccountFiche(),
    mail_fiches.MAIL: mail_fiches.MailFiche(),
    mail_fiches.DRAFT: mail_fiches.DraftFiche(),
}
