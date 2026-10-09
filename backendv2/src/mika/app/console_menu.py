"""Le menu opérateur, indépendant des sections techniques des facultés.

Les routes et les fiches gardent leurs adresses. Un même ancien espace peut
alimenter plusieurs rubriques : dessins dans Activité, caméra dans Outils.
"""

from mika.inspector.catalog import MenuGroup, MenuLink

MENU = (
    MenuGroup("", "home", (MenuLink("Accueil", ""),)),
    MenuGroup("À valider", "check", (
        MenuLink("Actions à autoriser", "approbations/en_attente"),
        MenuLink("Brouillons de courrier", "courrier/brouillons"),
        MenuLink("Réponses Teams", "teams/reponses"),
        MenuLink("Identités à confirmer", "identites/revendications"),
        MenuLink("Noms à relier", "identites/noms"),
        MenuLink("Historique des autorisations", "approbations/historique"),
    )),
    MenuGroup("Elle", "heart", (
        MenuLink("Émotions et besoins", "vie"),
        MenuLink("Sommeil et rythme", "vie/rythme"),
        MenuLink("Pensées et attention", "pensees"),
        MenuLink("Mémoire", "memoire"),
        MenuLink("Journal et rêves", "pensees/nuits"),
        MenuLink("Estime et récit", "vie/soi"),
        MenuLink("Monde et corps", "vie/monde"),
    ), her=True),
    MenuGroup("Relations & échanges", "people", (
        MenuLink("Personnes", "personnes"),
        MenuLink("Conversations", "fil"),
        MenuLink("Courrier", "courrier", ("reglages/boites",)),
        MenuLink("Teams", "teams", ("reglages/teams",)),
        MenuLink("Identités et adresses", "identites"),
    )),
    MenuGroup("Activité", "activity", (
        MenuLink("Projets", "projets"),
        MenuLink("Buts et rappels", "buts"),
        MenuLink("En cours", "decisions/en_cours"),
        MenuLink("Décisions et initiatives", "decisions"),
        MenuLink("Échéances", "decisions/echeances"),
        MenuLink("Dessins", "sens/dessins"),
    )),
    MenuGroup("Outils & connexions", "tools", (
        MenuLink("Catalogue des outils", "outils"),
        MenuLink("Apps forgées", "apps"),
        MenuLink("Services MCP", "outils/serveurs", ("reglages/serveurs-mcp",)),
        MenuLink("Flux RSS", "sens/flux", ("reglages/flux",)),
        MenuLink("Caméra", "sens/camera"),
        MenuLink("Appareils", "sens/appareils", ("reglages/appareils",)),
        MenuLink("Réveils par API", "reveils", ("reglages/reveils",)),
        MenuLink("Dépôts Git", "reglages/depots"),
    )),
    MenuGroup("Réglages", "settings", (
        MenuLink("Tous les réglages", "reglages/apercu", ("reglages",)),
        MenuLink("Personnalité", "reglages/identite",
                 ("reglages/parole", "reglages/caractere", "reglages/vie", "reglages/document", "reglages/temperament")),
        MenuLink("Modèles de texte", "reglages/fournisseurs", ("reglages/roles",)),
        MenuLink("Modèles d’image", "reglages/images-fournisseurs", ("reglages/images-roles",)),
        MenuLink("Transcription", "reglages/transcription"),
        MenuLink("Comptes opérateurs", "reglages/comptes"),
        MenuLink("Paramètres avancés", "reglages/comportement"),
        MenuLink("Configuration des plugins", "reglages/plugins"),
        MenuLink("Historique des réglages", "reglages/journal"),
    )),
    MenuGroup("Système", "system", (
        MenuLink("Santé générale", "systeme/sante"),
        MenuLink("Processus", "systeme/processus"),
        MenuLink("Anomalies", "systeme/anomalies"),
        MenuLink("File de sortie", "systeme/sorties"),
        MenuLink("Moteur des modèles", "systeme/passerelle"),
        MenuLink("Écrans du monde", "systeme/monde"),
        MenuLink("Appels et coûts", "systeme/appels"),
        MenuLink("Stockage et sauvegardes", "systeme/stockage"),
        MenuLink("Journal d’événements", "systeme/chronologie"),
        MenuLink("Actions des opérateurs", "systeme/operations"),
        MenuLink("Diagnostic avancé", "systeme/etat", ("systeme/contributions", "systeme/vues")),
        MenuLink("Simulations", "systeme/simulations"),
    )),
)
