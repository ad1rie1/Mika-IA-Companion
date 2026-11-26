"""Les onglets des destinations de la console qui sont dessinés (ADR 0121), par « destination/onglet » : la console
les reçoit (``InspectorDeps.drawn``) et retombe sur leurs blocs si un dessin échoue. Chacun a sa forme (ADR 0177),
déclarée par le module de sa destination dans ``tabs/`` ; ``DRAWN`` en est la réunion. Les fiches dessinées des
objets (``subjects/``) se réunissent ici aussi (``OVERVIEWS``) : celles du cadre, puis celles que chaque domaine
inscrit dans sa part de la console (``ConsolePart.overviews``, ADR 0310)."""

from __future__ import annotations

from mika.app.domains import DOMAINS, gathered, part
from mika.app.handmade.subjects import goal as goal_fiche
from mika.app.handmade.subjects import handle as handle_fiche
from mika.app.handmade.tabs import (
    approvals,
    decisions,
    goals,
    identities,
    life,
    memory,
    people,
    settings,
    system,
    thoughts,
    threads,
    tools,
)
from mika.inspector.ui import Drawn, Overview

#: la part de la console de chaque domaine qui a sa fiche (ADR 0310), dans l'ordre des fiches, et qui l'apporte
BROUGHT = tuple((f"le domaine « {d.name} »", part(d.console, "CONSOLE")) for d in DOMAINS if d.console is not None)
PARTS = tuple(console for _, console in BROUGHT)

# une sorte de fiche ou un onglet que deux disent — un domaine qui reprend un onglet du cadre — est refusé à l'import
# (``gathered``), au lieu que le dernier l'emporte sans bruit

#: les vues d'ensemble des fiches dessinées, par sorte d'objet (``Inspection.subject``) : celles du cadre, puis
#: celles des domaines
OVERVIEWS: dict[str, Overview] = gathered("une sorte de fiche de ConsolePart.overviews", [
    ("le cadre", {handle_fiche.KIND: handle_fiche.HandleOverview(), goal_fiche.KIND: goal_fiche.GoalFiche()}),
    *((who, console.overviews) for who, console in BROUGHT),
])

DRAWN: dict[str, Drawn] = gathered("un onglet de ConsolePart.drawn", [
    # Elle : humeur et corps, pensées et nuits, mémoire
    ("le cadre (tabs/life.py)", life.TABS),
    ("le cadre (tabs/thoughts.py)", thoughts.TABS),
    ("le cadre (tabs/memory.py)", memory.TABS),
    # Relations & échanges : le détail des personnes, identités, conversations, courrier, Teams, agendas
    ("le cadre (tabs/people.py)", people.TABS),
    ("le cadre (tabs/identities.py)", identities.TABS),
    ("le cadre (tabs/threads.py)", threads.TABS),
    # Activité : décisions, buts
    ("le cadre (tabs/decisions.py)", decisions.TABS),
    ("le cadre (tabs/goals.py)", goals.TABS),
    # Outils
    ("le cadre (tabs/tools.py)", tools.TABS),
    # Système : chaque page à part (des actions dans leurs lignes et leurs panneaux)
    ("le cadre (tabs/system.py)", system.TABS),
    # Approbations : leur historique (les demandes en attente : leur panneau, dans le même vocabulaire)
    ("le cadre (tabs/approvals.py)", approvals.TABS),
    # Réglages : les chiffres et les groupes au-dessus du formulaire des paramètres de chaque faculté (son panneau,
    # dans le même vocabulaire), la vue d'ensemble, les comptes, le journal des modifications, qui peut quoi
    ("le cadre (tabs/settings.py)", settings.TABS),
    # puis ceux que chaque domaine inscrit dans sa part de la console (``ConsolePart.drawn``, ADR 0310)
    *((who, console.drawn) for who, console in BROUGHT),
    # l'accueil est une page à lui (home.py) ; la Forge garde ses contrats d'interface
])
