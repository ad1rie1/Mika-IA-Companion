"""Le menu opérateur, indépendant des sections techniques des facultés.

Les routes et les fiches gardent leurs adresses. Le menu montre les groupes de pages (ADR 0178) : un lien vers une
destination (« vie », « memoire ») y est une colonne, son nom puis ses onglets, lus dans sa barre d'onglets même — on ne
les recopie pas ici ; une page sans onglets (En ce moment, Apps forgées) n'a que son nom. Une rubrique qui n'est
qu'une destination (« À valider », une seule file, ADR 0177 ; « Système ») nomme ses pages une à une, dans l'ordre et
sous le nom de leurs onglets (test_console_navigation.py) ; Système les range en trois colonnes, Surveiller, Journaux
et Anatomie (``MenuLink.column``, ADR 0202), et ses Journaux mènent aussi aux historiques des réglages et des
autorisations, qui restent dans leur rubrique. « Réglages » fait exception : une sélection d'entrées dans un annuaire
d'une cinquantaine de pages (le sien) ; les pages d'un même sujet y forment la barre d'onglets de son lien (``also``,
dans l'ordre déclaré). Les réglages d'un plugin n'y sont pas : ils vivent dans sa destination, derrière sa roue
(ADR 0173, 0206), et Réglages n'y mène que par « Configuration des plugins », leur vue d'ensemble, et l'annuaire.

Le menu fait foi (ADR 0202) : une destination porte le nom de son lien (``Destination.label`` dans
``app/console.py``), et le fil d'Ariane d'une page part de la rubrique du lien qui y mène (``catalog.menu_place``).
Les rubriques sont dans la barre du haut (ADR 0176) : chacune y a son nom court, et son menu commence par la question
à laquelle elle répond ; chaque lien, ou chaque colonne, y dit en quelques mots ce qu'on trouve derrière.

``MENU`` est le menu entier ; un serveur sert ``menu_for(reports)`` : Système › Anatomie › Simulations n'y est que s'il a
un dossier de rapports (``serve --reports``) : l'unité de service n'en passe pas, et sans lui la page reste vide.
Son adresse reste, comme son ancienne (``rapports``, ``MOVED``), et la recherche la trouve (audit du 2026-11-05,
C8-12).
"""

from dataclasses import replace
from pathlib import Path

from mika.app.domains import DOMAINS
from mika.inspector.catalog import MenuGroup, MenuLink

#: les rubriques dont les liens ne suivent pas les onglets de leurs destinations (voir plus haut)
SHORTCUT_GROUPS = ("Réglages",)

def _link(domain: str) -> MenuLink:
    """Le lien de menu d'un domaine qui a sa fiche (``Domain.menu``, ADR 0310) : la fiche dit ce qu'il est, ce menu dit
    où il est rangé."""
    found = next((d.menu for d in DOMAINS if d.name == domain), None)
    if found is None:
        raise ValueError(f"le domaine « {domain} » n'a pas de lien de menu dans sa fiche")
    return found



MENU = (
    MenuGroup("", "home", (MenuLink("Accueil", ""),)),
    # une seule file, une seule page (ADR 0177) : chaque lien en est un onglet
    MenuGroup("À valider", "check", (
        MenuLink("Tout ce qui attend", "approbations/en_attente", hint="Toutes les décisions qui t'attendent"),
        MenuLink("Courriers à envoyer", "approbations/courriers", hint="Ses mails, prêts à partir"),
        MenuLink("Réponses Teams", "approbations/teams", hint="Ce qu'elle poserait dans Teams"),
        MenuLink("Identités à confirmer", "approbations/identites", hint="Qui est qui, à valider"),
        MenuLink("Rapprochements", "approbations/rapprochements", hint="Deux fiches au même nom, des noms racontés"),
        MenuLink("Historique des autorisations", "approbations/historique", hint="Ce que tu as permis ou refusé"),
    ), question="Qu'est-ce qui attend ta décision ?"),
    MenuGroup("Elle", "heart", (
        MenuLink("En ce moment", "maintenant", hint="Son état et ses dernières 24 heures"),
        MenuLink("Humeur et corps", "vie", hint="Ce qu'elle ressent, son corps, qui elle devient"),
        MenuLink("Pensées et nuits", "pensees", hint="Ce qui lui trotte dans la tête, ses nuits"),
        MenuLink("Mémoire", "memoire", hint="Ce qu'elle retient, et de qui"),
        MenuLink("Constellation", "constellation", hint="Sa mémoire en points, en direct"),
    ), her=True, question="Comment va-t-elle, à quoi pense-t-elle, que retient-elle ?"),
    MenuGroup("Relations & échanges", "people", (
        MenuLink("Personnes", "personnes", hint="Les gens qu'elle connaît"),
        MenuLink("Conversations", "fil", hint="Avec qui elle parle, ce qui s'est dit"),
        MenuLink("Courrier", "courrier", hint="Ses boîtes aux lettres"),
        MenuLink("Teams", "teams", hint="Ce qu'elle lit et pose dans Teams"),
        MenuLink("Agendas", "agendas", hint="Tous les agendas du système, par personne"),
        MenuLink("Identités", "identites", hint="Par où chacun lui parle, qui est qui"),
    ), short="Échanges", question="Qui connaît-elle, qu'a-t-on dit ?"),
    MenuGroup("Activité", "activity", (
        MenuLink("Projets", "projets", hint="Ce qu'elle mène, pas à pas"),
        MenuLink("Buts et rappels", "buts", hint="Ce qu'elle veut faire, et quand"),
        MenuLink("Décisions", "decisions", hint="Pourquoi elle parle ou se tait"),
    ), question="Que fait-elle, pourquoi parle-t-elle ou se tait-elle ?"),
    MenuGroup("Outils", "tools", (
        MenuLink("Ses outils", "outils", hint="Ce qu'elle peut faire, d'où ça vient"),
        _link("forge"),  # les apps forgées
    ), question="Que peut-elle faire, et pour qui ?"),
    MenuGroup("Connexions extérieures", "plug", (
        MenuLink("Ses sens", "sens", hint="Ce qu'elle lit, voit et reçoit"),
        _link("wakeup"),  # les réveils par API
        MenuLink("Dépôts Git", "reglages/depots", hint="Le jeton de ses dépôts distants"),
    ), short="Connexions", question="Que perçoit-elle du dehors, qui la fait agir ?"),
    MenuGroup("Réglages", "settings", (
        MenuLink("Tous les réglages", "reglages/apercu", ("reglages",), hint="L'annuaire, avec sa recherche"),
        MenuLink("Modèles de texte", "reglages/fournisseurs", ("reglages/roles",), hint="Qui pense, qui écrit"),
        MenuLink("Modèles d’image", "reglages/images-fournisseurs", ("reglages/images-roles",), hint="Qui dessine"),
        # la page qui la décrit d'abord, l'outil d'import et d'export en dernier (C7-03 : l'ordre de la barre)
        MenuLink("Personnage", "reglages/identite",
                 ("reglages/portrait", "reglages/parole", "reglages/temperament", "reglages/autrices",
                  "reglages/document"), hint="Identité, portrait, tempérament, autrices"),
        # la vue d'ensemble : leurs réglages vivent dans leur destination, derrière sa roue (ADR 0206)
        MenuLink("Configuration des plugins", "reglages/plugins", hint="Où se règle chaque plugin"),
        # sa position, les lieux, les trajets, les données touristiques, les avis et leur réchauffage (ADR 0245,
        # 0250), les notifications du téléphone : une barre d'onglets (ADR 0197)
        MenuLink("Carte et téléphone", "reglages/carte",
                 ("reglages/lieux", "reglages/itineraires", "reglages/tourisme", "reglages/avis",
                  "reglages/rechauffage", "reglages/notifications"),
                 hint="Sa position, les lieux, les trajets, les données touristiques, les avis, les notifications"),
        MenuLink("Paramètres avancés", "reglages/comportement", hint="Les réglages internes de chaque faculté"),
        MenuLink("Comptes", "reglages/comptes", hint="Qui se connecte, qui pilote la console"),
        MenuLink("Droits", "reglages/droits", hint="Ce qu'elle a, ressource par ressource"),
        MenuLink("Canaux", "reglages/canaux", hint="Par où ça lui arrive, ce qui passe"),
        MenuLink("Historique des réglages", "reglages/journal", hint="Qui a changé quoi"),
    ), question="Que décides-tu pour elle ?"),
    # trois colonnes (ADR 0202) ; les journaux de qui a fait quoi réunis, les historiques restant dans leur rubrique
    MenuGroup("Système", "system", (
        MenuLink("Santé générale", "systeme/sante", column="Surveiller"),
        MenuLink("Processus", "systeme/processus", column="Surveiller"),
        MenuLink("Anomalies", "systeme/anomalies", column="Surveiller"),
        MenuLink("File de sortie", "systeme/sorties", column="Surveiller"),
        MenuLink("Moteur des modèles", "systeme/passerelle", column="Surveiller"),
        MenuLink("Écrans du monde", "systeme/monde", column="Surveiller"),
        MenuLink("Appels et coûts", "systeme/appels", column="Surveiller"),
        MenuLink("Stockage et sauvegardes", "systeme/stockage", column="Surveiller"),
        MenuLink("Journal d’événements", "systeme/chronologie", column="Journaux"),
        MenuLink("Gestes audités", "systeme/operations", column="Journaux"),
        MenuLink("Historique des réglages", "reglages/journal", column="Journaux"),
        MenuLink("Historique des autorisations", "approbations/historique", column="Journaux"),
        MenuLink("Diagnostic avancé", "systeme/etat", column="Anatomie"),
        MenuLink("Contributions", "systeme/contributions", column="Anatomie"),
        MenuLink("Toutes les vues", "systeme/vues", column="Anatomie"),
        MenuLink("Simulations", "systeme/simulations", column="Anatomie"),
    ), question="La machine tient-elle ?", columns=(
        ("Surveiller", "Ce qui tourne, ce qui coince, ce que ça coûte"),
        ("Journaux", "Qui a fait quoi, et quand"),
        ("Anatomie", "Le mécanisme, de près"),
    )),
)

#: la page des rapports de simulation : au menu seulement si le serveur a un dossier de rapports (``menu_for``)
REPORTS_PAGE = "systeme/simulations"


def menu_for(reports: Path | None) -> tuple[MenuGroup, ...]:
    """Le menu d'un serveur : ``MENU``, sans le lien de Simulations s'il n'a pas de dossier de rapports (``reports``,
    ``serve --reports``) — une page toujours vide n'aide à rien ; le développeur qui lance le serveur avec un dossier
    la retrouve au menu (C8-12)."""
    if reports is not None:
        return MENU
    return tuple(replace(group, items=tuple(link for link in group.items if link.target != REPORTS_PAGE))
                 for group in MENU)
