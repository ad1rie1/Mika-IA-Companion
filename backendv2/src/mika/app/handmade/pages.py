"""Les onglets des destinations de la console qui sont dessinés (ADR 0121), par « destination/onglet » : la console
les reçoit (``InspectorDeps.drawn``) et retombe sur leurs blocs si un dessin échoue. Chacun a sa forme (ADR 0177),
déclarée par le module de sa destination dans ``tabs/`` ; ``DRAWN`` en est la réunion."""

from __future__ import annotations

from mika.app.handmade.tabs import (
    approvals,
    apps,
    decisions,
    goals,
    identities,
    life,
    mail,
    memory,
    people,
    projects,
    senses,
    settings,
    system,
    teams,
    thoughts,
    threads,
    tools,
    wakeups,
)
from mika.inspector.ui import Drawn

DRAWN: dict[str, Drawn] = {
    # Elle : humeur et corps, pensées et nuits, mémoire
    **life.TABS,
    **thoughts.TABS,
    **memory.TABS,
    # Relations & échanges : le détail des personnes, identités, conversations, courrier, Teams
    **people.TABS,
    **identities.TABS,
    **teams.TABS,
    **threads.TABS,
    **mail.TABS,
    # Activité : décisions, buts, projets
    **decisions.TABS,
    **goals.TABS,
    **projects.TABS,
    # Outils, puis Connexions extérieures
    **tools.TABS,
    **senses.TABS,
    **wakeups.TABS,
    **apps.TABS,
    # Système : chaque page à part (des actions dans leurs lignes et leurs panneaux)
    **system.TABS,
    # Approbations : leur historique (les demandes en attente : leur panneau, dans le même vocabulaire)
    **approvals.TABS,
    # Réglages : les chiffres et les groupes au-dessus du formulaire des paramètres de chaque faculté (son panneau,
    # dans le même vocabulaire), la vue d'ensemble, les comptes, le journal des modifications, qui peut quoi
    **settings.TABS,
    # l'accueil est une page à lui (home.py) ; la Forge garde ses contrats d'interface
}
