"""Le menu opérateur, indépendant des sections techniques des facultés.

Les routes et les fiches gardent leurs adresses. Le menu et les onglets disent la même chose (ADR 0121) : dans une
rubrique, une destination a soit un seul lien (la page entière : Mémoire, Personnes, Courrier…), soit un lien par
onglet — tous ses onglets, dans leur ordre et sous leur nom (test_console_navigation.py). Deux rubriques font
exception : « À valider », des raccourcis nommés par la tâche vers ce qui attend une décision, et « Réglages », une
sélection d'entrées dans un annuaire d'une cinquantaine de pages (le sien).
"""

from mika.inspector.catalog import MenuGroup, MenuLink

#: les rubriques dont les liens ne suivent pas les onglets de leurs destinations (voir plus haut)
SHORTCUT_GROUPS = ("À valider", "Réglages")

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
        MenuLink("En ce moment", "maintenant"),
        MenuLink("Humeur", "vie"),
        MenuLink("Postures", "vie/postures"),
        MenuLink("Besoins", "vie/needs"),
        MenuLink("Sommeil et rythme", "vie/rythme"),
        MenuLink("Monde et corps", "vie/monde"),
        MenuLink("Estime et récit", "vie/soi"),
        MenuLink("Qui elle devient", "vie/devenir"),
        MenuLink("Pensées", "pensees"),
        MenuLink("Ce qu'elle remarque", "pensees/remarque"),
        MenuLink("Attentes", "pensees/attentes"),
        MenuLink("Journal et rêves", "pensees/nuits"),
        MenuLink("Mémoire", "memoire"),
        MenuLink("Constellation", "constellation"),
    ), her=True),
    MenuGroup("Relations & échanges", "people", (
        MenuLink("Personnes", "personnes"),
        MenuLink("Conversations", "fil"),
        MenuLink("Courrier", "courrier", ("reglages/boites",)),
        MenuLink("Teams", "teams", ("reglages/teams",)),
        MenuLink("Identités et moyens de communication", "identites"),
    )),
    MenuGroup("Activité", "activity", (
        MenuLink("Projets", "projets"),
        MenuLink("Buts et rappels", "buts"),
        MenuLink("Table de l'arbitre", "decisions"),
        MenuLink("Que ferait-elle ?", "decisions/envers"),
        MenuLink("En cours", "decisions/en_cours"),
        MenuLink("Initiatives", "decisions/initiatives"),
        MenuLink("Ses choix", "decisions/selections"),
        MenuLink("Épisodes", "decisions/episodes"),
        MenuLink("Échéances", "decisions/echeances"),
    )),
    MenuGroup("Outils", "tools", (
        MenuLink("Ce qu'elle peut faire", "outils"),
        MenuLink("Venus d'ailleurs", "outils/serveurs", ("reglages/serveurs-mcp",)),
        MenuLink("Prêter à un agent", "outils/expose"),
        MenuLink("Apps forgées", "apps"),
    )),
    MenuGroup("Connexions extérieures", "plug", (
        MenuLink("Flux RSS", "sens/flux", ("reglages/flux",)),
        MenuLink("Caméra", "sens/camera"),
        MenuLink("Dessins", "sens/dessins"),
        MenuLink("Appareils", "sens/appareils", ("reglages/appareils",)),
        MenuLink("Localisation", "sens/positions"),
        MenuLink("Messages du téléphone", "sens/messages"),
        MenuLink("Réveils par API", "reveils", ("reglages/reveils",)),
        MenuLink("Dépôts Git", "reglages/depots"),
    )),
    MenuGroup("Réglages", "settings", (
        MenuLink("Tous les réglages", "reglages/apercu", ("reglages",)),
        MenuLink("Modèles de texte", "reglages/fournisseurs", ("reglages/roles",)),
        MenuLink("Modèles d’image", "reglages/images-fournisseurs", ("reglages/images-roles",)),
        MenuLink("Personnalité", "reglages/identite",
                 ("reglages/parole", "reglages/caractere", "reglages/vie", "reglages/document",
                  "reglages/temperament", "reglages/autrices")),
        MenuLink("Configuration des plugins", "reglages/plugins"),
        MenuLink("Transcription", "reglages/transcription"),
        MenuLink("Paramètres avancés", "reglages/comportement"),
        MenuLink("Comptes opérateurs", "reglages/comptes"),
        MenuLink("Droits", "reglages/droits"),
        MenuLink("Canaux", "reglages/canaux"),
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
        MenuLink("Diagnostic avancé", "systeme/etat"),
        MenuLink("Contributions", "systeme/contributions"),
        MenuLink("Toutes les vues", "systeme/vues"),
        MenuLink("Simulations", "systeme/simulations"),
    )),
)
