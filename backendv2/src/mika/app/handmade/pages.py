"""Les onglets des destinations de la console qui sont dessinés (ADR 0121), par « destination/onglet » : la console
les reçoit (``InspectorDeps.drawn``) et retombe sur leurs blocs si un dessin échoue. Chacun a sa forme (ADR 0177) :
ceux de chaque destination sont déclarés par son module de ``tabs/`` ; les autres, plus anciens, ici."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from mika.app.handmade import conversations, mail, nights, rights, running, senses, system, tools
from mika.app.handmade.tabs import (
    approvals,
    apps,
    decisions,
    goals,
    identities,
    life,
    memory,
    people,
    projects,
    settings,
    teams,
    thoughts,
    threads,
    wakeups,
)
from mika.app.handmade.tabs import senses as sense_tabs
from mika.app.handmade.tabs import system as system_tabs
from mika.app.handmade.tabs import tools as tool_tabs
from mika.inspector.ui import UI, Drawn


class Shaped(Drawn):
    """Un onglet qui a sa forme à lui (``draw``), sur la feuille commune (``handmade/base.css``, chargée partout)
    et, s'il en a une, la sienne. ``last`` : sous les blocs et le panneau que la console garde ; ``panel`` faux : il
    dit ce que disait le panneau ; ``forms`` : il reçoit les formulaires que la console a préparés."""

    def __init__(self, draw: Callable[..., Any], *styles: str, last: bool = False, panel: bool = True,
                 forms: bool = False) -> None:
        self.draw = draw
        self.styles = styles
        self.last, self.panel, self.forms = last, panel, forms

    def render(self, ui: UI, items: Sequence[Any], query: Mapping[str, str],
               forms: Mapping[str, Any] | None = None) -> Any:
        # ``Forms`` est un ``dict`` : vide (aucune action dans les blocs), il garde son jeton
        return self.draw(ui, items, query, forms if forms is not None else {}) if self.forms \
            else self.draw(ui, items, query)


DRAWN: dict[str, Drawn] = {
    # Elle : humeur et corps, pensées et nuits, mémoire
    **life.TABS,
    **thoughts.TABS,
    "pensees/nuits": Shaped(nights.nights, "handmade/nights.css"),
    **memory.TABS,
    # Relations & échanges : le détail des personnes, identités, conversations, courrier, Teams
    **people.TABS,
    **identities.TABS,
    **teams.TABS,
    "fil/jugees": Shaped(conversations.judged),
    **threads.TABS,
    "courrier/reception": Shaped(mail.box, "handmade/mail.css", forms=True),
    "courrier/envoyes": Shaped(mail.box, "handmade/mail.css", forms=True),
    "courrier/brouillons": Shaped(mail.drafts, "handmade/mail.css", forms=True),
    "courrier/contacts": Shaped(mail.contacts, "handmade/mail.css", forms=True),
    # Activité : décisions, buts, projets
    **decisions.TABS,
    "decisions/en_cours": Shaped(running.running, "handmade/decisions.css"),
    **goals.TABS,
    **projects.TABS,
    # Outils, puis Connexions extérieures
    "outils/tous": tools.Catalogue(), "outils/serveurs": tools.Elsewhere(),
    **tool_tabs.TABS,
    **sense_tabs.TABS,
    "sens/messages": Shaped(senses.messages, "handmade/senses.css"),
    "sens/positions": Shaped(senses.positions, "handmade/senses.css"),
    **wakeups.TABS,
    **apps.TABS,
    # Système : chaque page à part (des actions dans leurs lignes et leurs panneaux)
    "systeme/processus": Shaped(system.processes, "handmade/system.css"),
    "systeme/sorties": Shaped(system.outbox, "handmade/system.css", panel=False, forms=True),
    "systeme/sante": Shaped(system.health, "handmade/system.css", panel=False),
    **system_tabs.TABS,
    # Approbations : leur historique (les demandes en attente : leur panneau, dans le même vocabulaire)
    **approvals.TABS,
    # Réglages : les chiffres et les groupes au-dessus du formulaire des paramètres de chaque faculté (son panneau,
    # dans le même vocabulaire), la vue d'ensemble, les comptes, le journal des modifications, qui peut quoi
    **settings.TABS,
    "reglages/droits": Shaped(rights.page, "handmade/tools.css", "handmade/rights.css", panel=False, forms=True),
    # l'accueil est une page à lui (home.py) ; la Forge garde ses contrats d'interface
}
