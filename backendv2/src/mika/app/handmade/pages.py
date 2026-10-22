"""Les onglets des destinations de la console qui sont dessinés (ADR 0121), par « destination/onglet » : la console
les reçoit (``InspectorDeps.drawn``) et retombe sur leurs blocs si un dessin échoue. Un onglet sans forme à lui est
dessiné bloc par bloc (``Blocks``)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade import blocks, conversations, mail, nights, running, senses, system, tools
from mika.inspector.ui import UI, Drawn


class Blocks(Drawn):
    """Un onglet dessiné bloc par bloc : des tuiles, des faits, des listes, un fil, ses formulaires (ceux que la
    console a préparés, avec leur jeton).
    ``tables`` : ses listes en cartes (``cards``), ou en tableaux sobres (``table`` : l'exploitation) ; ``styles`` :
    la feuille de son panneau, s'il en a un (Prêter à un agent)."""

    def __init__(self, tables: str = "cards", *styles: str) -> None:
        self.tables = tables
        self.styles = styles

    def render(self, ui: UI, items: Sequence[Any], query: Mapping[str, str],
               forms: Mapping[str, Any] | None = None) -> Any:
        drawn = blocks.page(ui, items, query, tables=self.tables, forms=forms)
        # rien à dessiner, mais un panneau qui a sa feuille (Prêter à un agent) : dessiné quand même, pour la charger
        return Markup("") if drawn is None and self.styles else drawn


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
        return self.draw(ui, items, query, forms or {}) if self.forms else self.draw(ui, items, query)


CARDS = Blocks()
#: des données d'exploitation (des modèles, des appels, des tables) : en colonnes
TABLES = Blocks("table")

DRAWN: dict[str, Drawn] = {
    # Elle : humeur et corps, pensées et nuits, mémoire
    **{f"vie/{t}": CARDS for t in ("humeur", "postures", "needs", "rythme", "monde", "soi", "devenir")},
    **{f"pensees/{t}": CARDS for t in ("pensees", "remarque", "attentes")},
    "pensees/nuits": Shaped(nights.nights, "handmade/nights.css"),
    **{f"memoire/{t}": CARDS for t in ("souvenirs", "croyances", "recues", "place", "promesses", "moments",
                                        "voir-venir", "consolidation")},
    # Relations & échanges : le détail des personnes, identités, conversations, courrier, Teams
    **{f"personnes/{t}": CARDS for t in ("personnes", "liens", "presents")},
    **{f"identites/{t}": CARDS for t in ("annuaire", "revendications", "noms", "politique")},
    **{f"teams/{t}": CARDS for t in ("conversations", "reponses", "extension")},
    "fil/messages": Shaped(conversations.messages),
    "fil/jugees": Shaped(conversations.judged),
    "fil/questions": CARDS,
    "courrier/reception": Shaped(mail.box, "handmade/mail.css", forms=True),
    "courrier/envoyes": Shaped(mail.box, "handmade/mail.css", forms=True),
    **{f"courrier/{t}": CARDS for t in ("brouillons", "contacts")},
    # Activité : décisions, buts, projets, dessins
    **{f"decisions/{t}": CARDS for t in ("maintenant", "envers", "initiatives", "selections", "episodes",
                                          "echeances")},
    "decisions/en_cours": Shaped(running.running, "handmade/decisions.css"),
    **{f"buts/{t}": CARDS for t in ("vivants", "clos")},
    **{f"projets/{t}": CARDS for t in ("tous", "toutes_executions", "toutes_decisions")},
    # Outils, puis Connexions extérieures
    "outils/tous": tools.Catalogue(), "outils/serveurs": tools.Elsewhere(),
    "outils/expose": Blocks("cards", "handmade/tools.css"),
    **{f"sens/{t}": CARDS for t in ("flux", "camera", "dessins", "appareils")},
    "sens/messages": Shaped(senses.messages, "handmade/senses.css"),
    "sens/positions": Shaped(senses.positions, "handmade/senses.css"),
    "reveils/reveils": CARDS, "apps/apps": CARDS,
    # Système : chaque page à part (des actions dans leurs lignes et leurs panneaux)
    "systeme/processus": Shaped(system.processes, "handmade/system.css"),
    "systeme/sorties": Shaped(system.outbox, "handmade/system.css", panel=False, forms=True),
    "systeme/sante": Shaped(system.health, "handmade/system.css", panel=False),
    **{f"systeme/{t}": CARDS for t in ("anomalies", "chronologie", "monde", "contributions", "simulations")},
    **{f"systeme/{t}": TABLES for t in ("passerelle", "appels", "stockage", "operations", "vues", "etat")},
    # Approbations : leur historique (les demandes en attente : leur panneau, dans le même vocabulaire)
    "approbations/historique": CARDS,
    # Réglages : les chiffres et les groupes au-dessus du formulaire des paramètres de chaque faculté (son panneau,
    # dans le même vocabulaire), la vue d'ensemble, les comptes, le journal des modifications
    "reglages/comportement": CARDS, "reglages/comportement-*": CARDS, "reglages/comptes": CARDS,
    "reglages/journal": TABLES,
    # l'accueil est une page à lui (home.py) ; la Forge garde ses contrats d'interface
}
