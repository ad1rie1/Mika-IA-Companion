"""Le menu opérateur, indépendant des sections techniques des facultés.

Les routes et les fiches gardent leurs adresses. Le menu et les onglets disent la même chose (ADR 0121) : dans une
rubrique, une destination a soit un seul lien (la page entière : Mémoire, Personnes, Courrier…), soit un lien par
onglet — tous ses onglets, dans leur ordre et sous leur nom (test_console_navigation.py). Deux rubriques font
exception : « À valider », des raccourcis nommés par la tâche vers ce qui attend une décision, et « Réglages », une
sélection d'entrées dans un annuaire d'une cinquantaine de pages (le sien).

Les rubriques sont dans la barre du haut (ADR 0176) : chacune y a son nom court, et son menu commence par la question
à laquelle elle répond ; chaque lien y dit en quelques mots ce qu'on trouve derrière.
"""

from mika.inspector.catalog import MenuGroup, MenuLink

#: les rubriques dont les liens ne suivent pas les onglets de leurs destinations (voir plus haut)
SHORTCUT_GROUPS = ("À valider", "Réglages")

MENU = (
    MenuGroup("", "home", (MenuLink("Accueil", ""),)),
    MenuGroup("À valider", "check", (
        MenuLink("Actions à autoriser", "approbations/en_attente", hint="Ce qu'elle attend de toi avant d'agir"),
        MenuLink("Brouillons de courrier", "courrier/brouillons", hint="Ses réponses, prêtes à partir"),
        MenuLink("Réponses Teams", "teams/reponses", hint="Ce qu'elle poserait dans Teams"),
        MenuLink("Identités à confirmer", "identites/revendications", hint="Qui est qui, à valider"),
        MenuLink("Noms à relier", "identites/noms", hint="Un nom dont on lui a parlé, une personne"),
        MenuLink("Historique des autorisations", "approbations/historique", hint="Ce que tu as permis ou refusé"),
    ), question="Qu'est-ce qui attend ta décision ?"),
    MenuGroup("Elle", "heart", (
        MenuLink("En ce moment", "maintenant", hint="Son état et ses dernières 24 heures"),
        MenuLink("Humeur", "vie", hint="Ce qu'elle ressent, et pourquoi"),
        MenuLink("Postures", "vie/postures", hint="Son attitude envers chacun"),
        MenuLink("Besoins", "vie/needs", hint="Compagnie, s'exprimer, apprendre"),
        MenuLink("Sommeil et rythme", "vie/rythme", hint="Ses nuits, son énergie"),
        MenuLink("Monde et corps", "vie/monde", hint="Où elle est, ce qu'elle fait"),
        MenuLink("Estime et récit", "vie/soi", hint="Ce qu'elle pense d'elle-même"),
        MenuLink("Qui elle devient", "vie/devenir", hint="Ce qui change en elle"),
        MenuLink("Pensées", "pensees", hint="Ce qui lui trotte dans la tête"),
        MenuLink("Ce qu'elle remarque", "pensees/remarque", hint="Ce qui l'a frappée"),
        MenuLink("Attentes", "pensees/attentes", hint="Ce qu'elle espère ou redoute"),
        MenuLink("Journal et rêves", "pensees/nuits", hint="Ses nuits, en récits"),
        MenuLink("Mémoire", "memoire", hint="Souvenirs, croyances, promesses"),
        MenuLink("Constellation", "constellation", hint="Sa mémoire en points, en direct"),
    ), her=True, question="Comment va-t-elle, à quoi pense-t-elle, que retient-elle ?"),
    MenuGroup("Relations & échanges", "people", (
        MenuLink("Personnes", "personnes", hint="Les gens qu'elle connaît"),
        MenuLink("Conversations", "fil", hint="Ce qui s'est dit, jour par jour"),
        MenuLink("Courrier", "courrier", hint="Ses boîtes aux lettres"),
        MenuLink("Teams", "teams", ("reglages/teams",), hint="Ce qu'elle lit et pose dans Teams"),
        MenuLink("Identités et moyens de communication", "identites", hint="Par où chacun lui parle"),
    ), short="Échanges", question="Qui connaît-elle, qu'a-t-on dit ?"),
    MenuGroup("Activité", "activity", (
        MenuLink("Projets", "projets", hint="Ce qu'elle mène, pas à pas"),
        MenuLink("Buts et rappels", "buts", hint="Ce qu'elle veut faire, et quand"),
        MenuLink("Table de l'arbitre", "decisions", hint="Comment elle choisit quoi faire"),
        MenuLink("Que ferait-elle ?", "decisions/envers", hint="Envers une personne : ce qui la pousse, la retient"),
        MenuLink("En cours", "decisions/en_cours", hint="Ce qu'elle fait en ce moment"),
        MenuLink("Initiatives", "decisions/initiatives", hint="Ce qu'elle fait d'elle-même"),
        MenuLink("Ses choix", "decisions/selections", hint="Ce qu'elle a choisi, et pourquoi"),
        MenuLink("Épisodes", "decisions/episodes", hint="Ses moments, du début à la fin"),
        MenuLink("Échéances", "decisions/echeances", hint="Ce qui arrive bientôt"),
    ), question="Que fait-elle, pourquoi parle-t-elle ou se tait-elle ?"),
    MenuGroup("Outils", "tools", (
        MenuLink("Ce qu'elle peut faire", "outils", hint="Ses outils, et qui peut quoi"),
        MenuLink("Venus d'ailleurs", "outils/serveurs", ("reglages/serveurs-mcp",), hint="Les services MCP branchés"),
        MenuLink("Prêter à un agent", "outils/expose", hint="Ses outils, pour un autre agent"),
        MenuLink("Apps forgées", "apps", hint="Ce qu'elle a construit"),
    ), question="Que peut-elle faire, et pour qui ?"),
    MenuGroup("Connexions extérieures", "plug", (
        MenuLink("Flux RSS", "sens/flux", ("reglages/flux",), hint="Ce qu'elle lit chaque jour"),
        MenuLink("Caméra", "sens/camera", hint="Ce qu'elle voit"),
        MenuLink("Dessins", "sens/dessins", hint="Ce qu'on lui montre"),
        MenuLink("Appareils", "sens/appareils", ("reglages/appareils",), hint="Les objets reliés"),
        MenuLink("Localisation", "sens/positions", hint="Ce que les téléphones lui disent"),
        MenuLink("Messages du téléphone", "sens/messages", hint="WhatsApp et SMS, lus pour toi"),
        MenuLink("Réveils par API", "reveils", ("reglages/reveils",), hint="Ce qui peut la réveiller"),
        MenuLink("Dépôts Git", "reglages/depots", hint="Le jeton de ses dépôts distants"),
    ), short="Connexions", question="Que perçoit-elle du dehors, qui la fait agir ?"),
    MenuGroup("Réglages", "settings", (
        MenuLink("Tous les réglages", "reglages/apercu", ("reglages",), hint="L'annuaire, avec sa recherche"),
        MenuLink("Modèles de texte", "reglages/fournisseurs", ("reglages/roles",), hint="Qui pense, qui écrit"),
        MenuLink("Modèles d’image", "reglages/images-fournisseurs", ("reglages/images-roles",), hint="Qui dessine"),
        MenuLink("Personnage", "reglages/identite",
                 ("reglages/parole", "reglages/caractere", "reglages/vie", "reglages/document",
                  "reglages/temperament", "reglages/autrices"), hint="Identité, portrait, tempérament, autrices"),
        MenuLink("Configuration des plugins", "reglages/plugins", hint="Les sens et les services branchés"),
        MenuLink("Transcription", "reglages/transcription", hint="La voix en texte"),
        MenuLink("Paramètres avancés", "reglages/comportement", hint="Les réglages internes de chaque faculté"),
        MenuLink("Comptes opérateurs", "reglages/comptes", hint="Qui pilote la console"),
        MenuLink("Droits", "reglages/droits", hint="Ce qu'elle a, ressource par ressource"),
        MenuLink("Canaux", "reglages/canaux", hint="Par où ça lui arrive, ce qui passe"),
        MenuLink("Historique des réglages", "reglages/journal", hint="Qui a changé quoi"),
    ), question="Que décides-tu pour elle ?"),
    MenuGroup("Système", "system", (
        MenuLink("Santé générale", "systeme/sante", hint="Le verdict, contrôle par contrôle"),
        MenuLink("Processus", "systeme/processus", hint="Ce qui tourne, ce qui échoue"),
        MenuLink("Anomalies", "systeme/anomalies", hint="Ce qui a déraillé"),
        MenuLink("File de sortie", "systeme/sorties", hint="Ce qui part, ce qui coince"),
        MenuLink("Moteur des modèles", "systeme/passerelle", hint="Créneaux, quotas, qui sert quoi"),
        MenuLink("Écrans du monde", "systeme/monde", hint="Les clients du monde connectés"),
        MenuLink("Appels et coûts", "systeme/appels", hint="Par jour, rôle, fournisseur, modèle"),
        MenuLink("Stockage et sauvegardes", "systeme/stockage", hint="Bases, instantanés, archives"),
        MenuLink("Journal d’événements", "systeme/chronologie", hint="Tout ce qui lui est arrivé"),
        MenuLink("Actions des opérateurs", "systeme/operations", hint="Ce que les opérateurs ont fait"),
        MenuLink("Diagnostic avancé", "systeme/etat", hint="Le mécanisme, de près"),
        MenuLink("Contributions", "systeme/contributions", hint="Qui projette quoi"),
        MenuLink("Toutes les vues", "systeme/vues", hint="Chaque vue déclarée"),
        MenuLink("Simulations", "systeme/simulations", hint="Les rapports du simulateur"),
    ), question="La machine tient-elle ?"),
)
