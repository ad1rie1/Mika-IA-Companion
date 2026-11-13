"""Les fiches dessinées des objets (ADR 0121), une par module, comme ``inspector/pages/subjects.py`` les sert : un
service branché (``server``), un moyen de communication (``handle``), un projet (``project``, son dépôt git dans
``project_git``), un but (``goal``), un réveil (``wakeup``), une conversation et une réponse Teams (``teams``), une
boîte, un mail et un brouillon (``mail``). Chacune est une ``Overview`` ; la composition les reçoit toutes ici
(``OVERVIEWS``, par sorte d'objet). La fiche d'une personne a son paquet (``person/``) ; les apps de la Forge gardent
le rendu de la console (``plain_owners``).

Chaque fiche dessine son en-tête et son onglet principal (ses formulaires sont ceux que la console a préparés) ; ses
autres onglets se dessinent à leur façon, ou bloc par bloc. Ce que la vue de sa faculté montre déjà, une fiche le lit
dans ses blocs ou dans l'en-tête qu'elle déclare ; le reste, par des fonctions de la faculté qu'elle déclare
(ADR 0218). Ce qu'elles partagent est dans ``parts.py``.
"""

from __future__ import annotations

from mika.app.handmade.subjects import goal, handle, mail, project, server, teams, wakeup
from mika.inspector.ui import Overview

#: les vues d'ensemble des fiches dessinées, par sorte d'objet (``Inspection.subject``)
OVERVIEWS: dict[str, Overview] = {
    server.KIND: server.ServerOverview(),
    handle.KIND: handle.HandleOverview(),
    project.KIND: project.ProjectFiche(),
    goal.KIND: goal.GoalFiche(),
    wakeup.KIND: wakeup.WakeupFiche(),
    teams.CONVERSATION: teams.ConversationFiche(),
    teams.REPLY: teams.ReplyFiche(),
    mail.ACCOUNT: mail.AccountFiche(),
    mail.MAIL: mail.MailFiche(),
    mail.DRAFT: mail.DraftFiche(),
}
