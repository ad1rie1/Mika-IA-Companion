# 0121 — Elle, en ce moment : une page dessinée à la main, qui croise ses facultés

**Contexte.** La console est un back-office que les facultés déclarent (ADR 0025, 0029) : chacune verse ses
données dans une vingtaine de blocs génériques (`Table`, `Fields`, `Stats`, `Timeline`, `Chart`…) rendus par un
seul gabarit. C'est ce qui la rend complète et sûre : tout ce qu'une faculté sait se voit, se nomme et se teste,
sans effort. Mais la propriétaire la trouvait pauvre à lire, et la cause tient au contrat, pas au style :

- tout se ressemble — des cartes de chiffres, une liste, une pagination, une aide repliée — que la page parle de
  ses besoins, de ses pensées ou d'un épisode ;
- le vocabulaire n'a aucun mot du domaine : un mélange d'émotions, le plan plaisir × éveil, une journée où l'on
  voit qu'une tristesse a suivi une conversation et précédé une nuit courte, rien de cela n'est un bloc ;
- une page appartient à un propriétaire, quand la question de l'opératrice — « comment va-t-elle, et pourquoi ? »
  — traverse l'humeur, le corps, les besoins, l'attention, ses liens et ce qu'elle entreprend.

La constellation (ADR 0103) avait déjà montré l'autre voie : une page faite à la main, composée dans `app/`.

**Décision.**
- **Les blocs déclarés restent la règle** pour la longue traîne : paramètres, listes d'objets, fiches, actions
  auditées. **Une question qui traverse les facultés a sa page dessinée à la main**, composée dans `app/` — la seule
  couche qui peut lire les contrats *et* se servir du code d'une faculté (ses phrases, ses libellés) ; l'inspecteur
  ne nomme toujours aucune faculté.
- **La première : « En ce moment »** (`/inspecteur/maintenant`, menu « sa rubrique » › En ce moment,
  `app/handmade/now.py`, gabarits `handmade/now/`). Dans le cadre de la console
  (menu, vitaux, thème), réservée aux opérateurs. Elle croise, lus aux faits au même instant que son prompt :
  - **son humeur** en mots (« à peine confuse, elle qui est d'habitude contente »), le mélange de ses facettes, ce
    que son prompt lui en dit (cité tel quel), et le **plan plaisir × éveil** : où elle est, son repos, la trace de
    ses 24 dernières heures, quelques émotions en repères ;
  - **ses dernières 24 heures sur un seul axe** : humeur (au-dessus ou au-dessous du neutre), énergie, sommeil
    (lu au journal), ses trois besoins, et ses paroles, initiatives et pensées en points qui mènent à l'épisode ;
    une colonne par mesure dit toutes les valeurs de cet instant au survol ;
  - **son corps** (éveillée depuis, énergie, où elle est, ce qu'elle fait, sa nuit), **ses besoins** (tension,
    tendance sur l'heure, un vide ressenti), **ce qui lui trotte dans la tête** (ses pensées, ce qu'elle attend avec
    espoir ou inquiétude, le rêve dont elle s'est réveillée) ;
  - **les gens** : qui est en ligne ou écrit, sa propriétaire, la proximité, ce qu'elle ressent envers chacun,
    l'attachement, ce qui attend une réponse — une conversation de moins de quinze minutes n'est pas une attente
    (ADR 0115) —, un silence plus long que d'habitude, une rancune ;
  - **le fil de sa journée** (une conversation en une ligne, ses pensées, son sommeil, ses manques et ses
    retrouvailles, ce qu'elle a mené à bout), **ce qu'elle entreprend** (ses buts et leur avancée, sa retenue,
    ce qui vient) et **aujourd'hui en chiffres**.
- **La deuxième : la vue d'ensemble d'une personne**, le premier onglet de sa fiche, ouvert par défaut
  (`/inspecteur/fiche/person/<clé>`, `app/handmade/person/`, gabarits `handmade/person/`).
  Une page à côté de la fiche faisait doublon : la fiche garde son en-tête, ses actions (proximité, nommer, oublier) et
  ses onglets — le détail de chaque faculté —, et s'ouvre sur ce qu'elle vit avec cette personne. La console reçoit
  ces vues de la composition (`InspectorDeps.overviews`, par type d'objet, `inspector.ui.Overview`) : elle n'en sait
  que l'onglet, et une vue qui échoue la laisse retomber sur ses onglets. `/inspecteur/personne/<clé>` mène à la
  fiche. **Son en-tête est dessiné aussi** (`Overview.head`, gabarit `handmade/person/head.html`), sur tous ses onglets :
  son nom en grand, un avatar de la couleur de ce qu'elle ressent (et sa présence), propriétaire, proximité, en
  ligne ou en train d'écrire, depuis quand et combien elles se parlent, par où (« 1 adresse · web, vérifiée ») et ce
  qu'elle ferait envers elle maintenant ; la console y ajoute ses actions. Il remplace un sous-titre à l'horodatage
  brut, des badges de divulgation et cinq lignes de faits qui redisaient la proximité — le détail technique reste
  dans les onglets Synthèse et Adresses. Elle répond à « qu'est-ce qu'elle vit avec cette personne ? » :
  - **qui elle est pour elle** : propriétaire, proximité, en ligne ou en train d'écrire, depuis quand elles
    s'écrivent ; ce qu'elle ressent envers elle et ce que son prompt lui en dit ; la chaleur, l'attachement, une
    rancune, un repli, des excuses qui ont compté ; un moment difficile (``memory.hard_times``) ;
  - **leur histoire** : vingt-six semaines de jours échangés, une case par jour de la couleur de ce qu'elle
    ressentait en lui écrivant (ses balises au fil), les heures où la personne écrit (et celles qu'elle a apprises),
    son rythme, qui ouvre leurs conversations, son délai de réponse, les étapes de leur lien ;
  - **ce qu'elle sait d'elle**, par la seule porte de sa mémoire (`contracts.memory.KNOWLEDGE`, sous toutes les clés
    où elle a pu la noter) : les moments de sa vie, ses croyances avec leur confiance et leurs témoins, ses
    souvenirs, ce que la personne dit d'elle-même, ce qu'elle lui a caché ;
  - **ce qu'elle lit d'elle** (son ton, celui du moment, son dernier message en facettes), **ce qui reste en
    suspens** (une réponse attendue, ses promesses, ses pensées, les buts qui la concernent, une prise de nouvelles
    prévue), **son entourage** (ses liens, ce qu'on lui en a raconté) et **leurs derniers mots**, chacun menant à
    « pourquoi a-t-elle dit ça ? ».
  La personne se nomme par son nom, jamais par un pronom (« de » et « que » s'élident devant une voyelle). « En ce
  moment » y mène depuis chaque personne.
- **Rien en ligne** (politique de sécurité de la console) : les longueurs sont des attributs SVG, les couleurs des
  classes — `sw-<émotion>` pose `--sw` —, sur les jetons de la console (clair, sombre).
- **Un graphe ne grossit pas avec l'écran.** Les 24 heures ont une hauteur fixe en pixels et suivent la largeur :
  le tracé s'étire en largeur seulement (`preserveAspectRatio="none"`, traits d'épaisseur constante), et les textes
  et les points vivent hors de l'étirement, placés en pourcentage. Les courbes de toute la console (`inspector/svg.py`)
  suivent désormais le même principe : dessinées sur 960 × 240 puis agrandies à pleine largeur, leur texte et leur
  hauteur grossissaient d'une fois et demie sur un grand écran.
- **Ses onglets sont dessinés aussi**, un par un (`Overview.tabs`, `render_tab` ; `app/handmade/person/<onglet>.py`,
  gabarits `handmade/person/tabs/`) : **les données restent celles de la faculté** — ses lignes, ses cellules, sa
  pagination, sa recherche —, seule la forme change ; une forme qu'un onglet ne reconnaît pas, ou un échec, rend la
  main aux blocs de la faculté. Échanges est une conversation jour par jour (la personne à gauche, elle à droite de la
  couleur de sa balise ; sous un message reçu ce qu'il est devenu, sous sa réponse son « pourquoi » et son épisode).
  Mémoire est quatre cartes (les moments de sa vie, ses promesses, ce qu'elle croit, ses souvenirs). Adresses,
  Fichiers, Pièces reçues, Buts et Projets sont des listes en cartes : chaque onglet dit par libellé de colonne le
  titre, les étiquettes, le texte et la date (`lists.Roles`) ; l'état ordinaire (« anodin », « actif »), un champ
  vide, le nom de la personne de la fiche et une pagination d'une seule page se taisent. **Ce que la vue d'ensemble
  résume** — Synthèse, Lien, Ce qu'elle devine, Affect, Pensées — est rangé au bout de la barre, sous « Le détail »
  (`Overview.folded`), et dessiné bloc par bloc (`blocks.py` : des tuiles, des faits, des cartes, un fil) ; un
  formulaire (fixer la proximité) s'y dessine à sa place, préparé par la console au nom de la personne (`Forms`).
- **La troisième : Personnes** (`/inspecteur/personnes`, `app/handmade/people.py`, gabarits `handmade/people/`,
  feuille `people.css`), la page d'entrée de la destination : ses trois onglets (l'annuaire des identités, les liens,
  les présents) répondaient chacun pour une faculté. Elle les croise, une carte par personne — ce qu'elle est pour
  elle, ce qu'elle ressent envers elle, l'attachement, ce qui se passe entre elles (en ligne, en pleine conversation,
  une réponse attendue, un silence plus long que d'habitude, une rancune), ce qu'elle en sait, son rythme —, avec qui
  est là et qui lui manque ; on cherche par nom ou par adresse, on filtre par proximité ou par présence, trente cartes
  par page, qui est là d'abord puis qui a écrit le plus récemment. Les trois onglets restent, sous « Le détail »
  (`/inspecteur/personnes/<onglet>`). La carte d'une personne est commune à « En ce moment » et à Personnes
  (`handmade.person_card`).
- **Les onglets des destinations sont dessinés aussi** (`InspectorDeps.drawn`, par « destination/onglet », ou
  « destination/préfixe-* » ; `inspector.ui.Drawn` ; la table `app/handmade/pages.py::DRAWN`). La console produit
  l'onglet comme avant, prépare les formulaires de ses actions (`Forms` : par emplacement, leur jeton, leurs champs,
  leur retour ; `forms.of(blocs, sujet)` en prépare d'autres au nom d'un objet), puis le donne au dessin
  (`Pages.drawn`) : son HTML prend la place de ses blocs, ses formulaires dessinés à leur place par les macros de la
  console. Demandée en tableau (`vue_…=table`, `wants_table`), une liste revient au rendu par défaut (un tableau
  sobre) ; un dessin qui échoue ou qui ne reconnaît pas sa forme aussi. Trois façons :
  - **bloc par bloc** (`Blocks`, `blocks.py`) pour la plupart — Elle, Mémoire, Identités, Décisions, Buts, Projets,
    Outils, Flux, Réveils, Apps, Teams, le détail de Personnes, Brouillons et Contacts du courrier, l'historique des
    approbations, les pages de Système et de Réglages qui ne sont pas des formulaires : des chiffres en tuiles, des
    faits en grille, une liste en cartes, un fil, un espace de travail (sa navigation à côté), ses actions ; les
    données d'exploitation (modèles, appels, stockage, opérations, vues, état) en tableaux sobres
    (`Blocks("table")`). Une liste sans rôles déclarés tire les siens de ses colonnes (`lists._title_of` : la colonne
    qui la nomme, celle qui mène où mène la ligne, son premier texte ; sa date à droite du titre) ; une liste sans
    long texte se lit en **lignes serrées**, ses étiquettes à côté du titre. Les listes d'une page sont numérotées
    comme la console les numérote (leur ancre, leur pagination, `vue_…`) ;
  - **une forme à lui** (`Shaped`) : Conversations › Messages (le fil jour par jour de la fiche, pour tout le monde),
    Ses réponses jugées, **Système › Processus** (`system.py`, lu à l'ordonnanceur : une barre de leurs états, ce qui
    échoue ou est retenu avec sa dernière erreur en clair et son prochain essai, une carte par faculté),
    **Système › Santé** (lu au rapport de santé : son verdict, ses dix contrôles en tuiles, ce qui ne va pas d'abord ;
    `Drawn.panel` faux : il dit ce que disait le panneau), **Pensées › Journal et rêves** (`nights.py` : son
    journal en page de carnet, ce qu'elle en raconte, sa journée en cours, puis une carte par nuit — son journal et
    ses rêves ensemble), **Outils › Qui reçoit quoi** (`tools.py` : une grille, ses lots en lignes, les situations
    en colonnes rangées par ce qui se passe — elle répond, elle prend la parole, personne n'écoute —, chaque case en
    main, à la demande ou pas offert, et menant au catalogue sur ce lot dans cette situation),
    **Courrier › Réception et Envoyés** (`mail.py` : une
    boîte aux lettres — une ligne par message, douze par page, et sous la liste une liseuse, `?lire=<clé>` : l'onglet
    « Message » de la fiche du mail, ses actions préparées à son nom, ses listes numérotées à part) ;
  - **sous ce que garde la console** (`Drawn.last`) : **Système › File de sortie** — ses chiffres, ses états et son panneau
    « à traiter », la liste des effets en lignes (l'état ordinaire, « parti » du premier coup, se tait).
- **L'accueil est dessiné à la main** (`/inspecteur/`, `app/handmade/home.py`, gabarits `handmade/home/`) : ce qui
  attend l'opératrice (l'onglet « À traiter » en lignes, une par page où décider : la plus grave, la plus précise),
  comment elle va (son humeur, son corps, ses besoins, lus comme « En ce moment »), qui est là, la journée en
  chiffres et ses derniers épisodes ; il se relit seul.
- **Toute page de la console est dessinée** : les blocs d'une page qui n'a pas de dessin à elle (une fiche, un
  épisode, « pourquoi a-t-elle dit ça ? », un événement, une action) passent par les mêmes macros
  (`handmade/shared/drawn.html`, importées par `page.html`), et les panneaux de la console sont écrits dans le même
  vocabulaire : les demandes en attente, les réglages (l'annuaire, un formulaire, ses enregistrements, ses
  commandes), les paramètres d'une faculté, un compte, « à traiter », « Rejouer avec… », la connexion. Les champs, les
  noms et les boutons restent ceux de la console ; `handmade/base.css` est chargée partout (ses classes ne touchent
  qu'elles). **Seules les vues de la Forge gardent le rendu de la console** (`InspectorDeps.plain_owners`) : ses apps
  déclarent leur interface par un contrat.
- **Le menu et les onglets disent la même chose** (`app/console_menu.py`, `test_console_navigation.py`) : dans une
  rubrique, une destination a un seul lien (la page entière : Mémoire, Personnes, Courrier…) ou un lien par onglet —
  tous ses onglets, dans leur ordre, sous leur nom (Humeur, Postures, Besoins, Sommeil et rythme… ; les sept onglets
  des décisions ; ceux des outils et des flux et capteurs ; les quatorze pages de Système). Un onglet porte le nom
  de son lien, et un nom qui ne disait pas ce que montre la page a changé (« Table de l'arbitre », « Ce qu'elle
  remarque », « Règles de divulgation », « Ce que son prompt en dit » — devenu « Régler ses outils », ADR 0122). Deux exceptions : « À valider », des
  raccourcis nommés par la tâche, et « Réglages », une sélection dans l'annuaire de ses cinquante pages.
- **Rangées dans des dossiers** : le code dans `app/handmade/` (ce qu'elles partagent dans `__init__.py` ; `home.py`,
  `now.py`, `people.py`, `person/` ; `lists.py` et `blocks.py`, les listes et les blocs en cartes ;
  `conversations.py`, `system.py`, `mail.py` ; `pages.py`, la table des onglets dessinés), les gabarits dans
  `inspector/templates/handmade/` (`macros.html`, `home/`, `now/`, `people/`, `person/`, `person/tabs/`,
  `conversations/`, `system/`, `mail/`, `reglages/` et `approbations/` (les panneaux de la console : l'annuaire, une
  page de réglages, ses enregistrements, les paramètres d'une faculté, un compte, les demandes en attente), `shared/` :
  `drawn.html` les macros des blocs, `list_macros.html` les listes, `rejouer.html`, `outil.html`, `action.html`), les
  feuilles et le script dans `inspector/static/handmade/` (`base.css` le vocabulaire commun, `home.css`,
  `now.css`, `person.css`, `people.css`, `system.css`, `mail.css`, `live.js`) ; une page dessinée charge les
  feuilles qu'elle déclare (`Overview.styles`, `Drawn.styles`).
- **Elle se relit seule** : `handmade/live.js` remplace le fragment (`/inspecteur/_maintenant`, 401 sans session d'opérateur)
  toutes les 20 s, en pause onglet caché ; sans script, c'est une page complète. **Chaque partie se lit à part** :
  une lecture qui échoue tait sa carte (« Impossible de lire… »), jamais la page.

**Conséquences.** Une page dessinée à la main coûte plus qu'une vue déclarée et ne gagne pas seule ce qu'une faculté
ajoute : elle se réserve aux quelques questions qui le méritent ; le reste passe par les macros communes. Tests : `tests/protocol/test_now_page.py` et
`test_person_page.py` (accès, une vraie conversation, une pensée, un moment et un souvenir lus sur la page, chaque
onglet dessiné et ses formulaires gardés, le
fragment, une adresse inconnue, une partie en échec), `test_people_page.py`, `test_home_page.py`, `test_drawn_pages.py` (chaque onglet
de `DRAWN` s'ouvre, Conversations, Processus, le retour en tableau, un dessin cassé), `test_mail_workspace.py` (la
liseuse) ; l'aperçu de la console
l'exporte, sans son script.
