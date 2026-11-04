"""Le menu opérateur, indépendant des sections techniques des facultés.

Les routes et les fiches gardent leurs adresses. Le menu montre les groupes de pages (ADR 0178) : un lien vers une
destination (« vie », « memoire ») y est une colonne, son nom puis ses onglets, lus dans sa barre d'onglets même — on ne
les recopie pas ici ; une page sans onglets (En ce moment, Apps forgées) n'a que son nom. Une rubrique qui n'est
qu'une destination (« À valider », une seule file, ADR 0177 ; « Système ») nomme ses pages une à une, dans l'ordre et
sous le nom de leurs onglets (test_console_navigation.py). « Réglages » fait exception : une sélection d'entrées dans
un annuaire d'une cinquantaine de pages (le sien).

Les rubriques sont dans la barre du haut (ADR 0176) : chacune y a son nom court, et son menu commence par la question
à laquelle elle répond ; chaque lien y dit en quelques mots ce qu'on trouve derrière.
"""

from mika.inspector.catalog import MenuGroup, MenuLink

#: les rubriques dont les liens ne suivent pas les onglets de leurs destinations (voir plus haut)
SHORTCUT_GROUPS = ("Réglages",)

MENU = (
    MenuGroup("", "home", (MenuLink("Accueil", ""),)),
    # une seule file, une seule page (ADR 0177) : chaque lien en est un onglet
    MenuGroup("À valider", "check", (
        MenuLink("Tout ce qui attend", "approbations/en_attente", hint="Toutes les décisions qui t'attendent"),
        MenuLink("Courriers à envoyer", "approbations/courriers", hint="Ses mails, prêts à partir"),
        MenuLink("Réponses Teams", "approbations/teams", hint="Ce qu'elle poserait dans Teams"),
        MenuLink("Identités à confirmer", "approbations/identites", hint="Qui est qui, à valider"),
        MenuLink("Noms à relier", "approbations/noms", hint="Un nom dont on lui a parlé, une personne"),
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
        MenuLink("Teams", "teams", ("reglages/teams",), hint="Ce qu'elle lit et pose dans Teams"),
        MenuLink("Identités", "identites", hint="Par où chacun lui parle, qui est qui"),
    ), short="Échanges", question="Qui connaît-elle, qu'a-t-on dit ?"),
    MenuGroup("Activité", "activity", (
        MenuLink("Projets", "projets", hint="Ce qu'elle mène, pas à pas"),
        MenuLink("Buts et rappels", "buts", hint="Ce qu'elle veut faire, et quand"),
        MenuLink("Décisions", "decisions", hint="Pourquoi elle parle ou se tait"),
    ), question="Que fait-elle, pourquoi parle-t-elle ou se tait-elle ?"),
    MenuGroup("Outils", "tools", (
        MenuLink("Ses outils", "outils", ("reglages/serveurs-mcp",), hint="Ce qu'elle peut faire, d'où ça vient"),
        MenuLink("Apps forgées", "apps", hint="Ce qu'elle a construit"),
    ), question="Que peut-elle faire, et pour qui ?"),
    MenuGroup("Connexions extérieures", "plug", (
        MenuLink("Ses sens", "sens", ("reglages/flux", "reglages/appareils"), hint="Ce qu'elle lit, voit et reçoit"),
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
