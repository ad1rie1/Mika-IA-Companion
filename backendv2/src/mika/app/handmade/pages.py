"""Les onglets des destinations de la console qui sont dessinés (ADR 0121), par « destination/onglet » : la console
les reçoit (``InspectorDeps.drawn``) et retombe sur leurs blocs si un dessin échoue. Chacun a sa forme (ADR 0177),
déclarée par le module de sa destination dans ``tabs/`` ; ``DRAWN`` en est la réunion. Les fiches dessinées des
objets (``subjects/``) se réunissent ici aussi (``OVERVIEWS``) : celles du cadre, puis celles que chaque domaine
inscrit dans sa part de la console (``ConsolePart.overviews``, ADR 0310)."""

from __future__ import annotations

from mika.app.domains import DOMAINS, part
from mika.app.domains.senses.console import tabs as senses
from mika.app.handmade.subjects import agenda as agenda_fiche
from mika.app.handmade.subjects import goal as goal_fiche
from mika.app.handmade.subjects import handle as handle_fiche
from mika.app.handmade.subjects import mail as mail_fiche
from mika.app.handmade.subjects import project as project_fiche
from mika.app.handmade.subjects import server as server_fiche
from mika.app.handmade.subjects import teams as teams_fiche
from mika.app.handmade.tabs import (
    agendas,
    approvals,
    decisions,
    goals,
    identities,
    life,
    mail,
    memory,
    people,
    projects,
    settings,
    system,
    teams,
    thoughts,
    threads,
    tools,
)
from mika.inspector.ui import Drawn, Overview

#: la part de la console de chaque domaine qui a sa fiche (ADR 0310), dans l'ordre des fiches
PARTS = tuple(part(d.console, "CONSOLE") for d in DOMAINS if d.console is not None)

#: les vues d'ensemble des fiches dessinées, par sorte d'objet (``Inspection.subject``) : celles du cadre, puis
#: celles des domaines
OVERVIEWS: dict[str, Overview] = {
    server_fiche.KIND: server_fiche.ServerOverview(),
    handle_fiche.KIND: handle_fiche.HandleOverview(),
    project_fiche.KIND: project_fiche.ProjectFiche(),
    goal_fiche.KIND: goal_fiche.GoalFiche(),
    teams_fiche.CONVERSATION: teams_fiche.ConversationFiche(),
    teams_fiche.REPLY: teams_fiche.ReplyFiche(),
    mail_fiche.ACCOUNT: mail_fiche.AccountFiche(),
    mail_fiche.MAIL: mail_fiche.MailFiche(),
    mail_fiche.DRAFT: mail_fiche.DraftFiche(),
    agenda_fiche.KIND: agenda_fiche.AgendaFiche(),
    **{kind: overview for console in PARTS for kind, overview in console.overviews.items()},
}

DRAWN: dict[str, Drawn] = {
    # Elle : humeur et corps, pensées et nuits, mémoire
    **life.TABS,
    **thoughts.TABS,
    **memory.TABS,
    # Relations & échanges : le détail des personnes, identités, conversations, courrier, Teams, agendas
    **people.TABS,
    **identities.TABS,
    **teams.TABS,
    **agendas.TABS,
    **threads.TABS,
    **mail.TABS,
    # Activité : décisions, buts, projets
    **decisions.TABS,
    **goals.TABS,
    **projects.TABS,
    # Outils, puis Connexions extérieures
    **tools.TABS,
    **senses.TABS,
    # Système : chaque page à part (des actions dans leurs lignes et leurs panneaux)
    **system.TABS,
    # Approbations : leur historique (les demandes en attente : leur panneau, dans le même vocabulaire)
    **approvals.TABS,
    # Réglages : les chiffres et les groupes au-dessus du formulaire des paramètres de chaque faculté (son panneau,
    # dans le même vocabulaire), la vue d'ensemble, les comptes, le journal des modifications, qui peut quoi
    **settings.TABS,
    # puis ceux que chaque domaine inscrit dans sa part de la console (``ConsolePart.drawn``, ADR 0310)
    **{key: drawn for console in PARTS for key, drawn in console.drawn.items()},
    # l'accueil est une page à lui (home.py) ; la Forge garde ses contrats d'interface
}
