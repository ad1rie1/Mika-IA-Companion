# La carte de la console

Ce que chaque entrée du menu de `/inspecteur/` montre, et sous quelle forme. Le menu visible vit dans
`app/console_menu.py` ; les destinations (adresses, onglets, libellés) dans `app/console.py` ; les réglages dans
`app/reglages.py` ; les pages dessinées à la main dans `app/handmade/` (gabarits `inspector/templates/handmade/`,
feuilles `inspector/static/handmade/`, la table `app/handmade/pages.py::DRAWN`). Les décisions sont dans les ADR
0025, 0029, 0042, 0045, 0103 et 0121 à 0124.

Trois règles tiennent toute la console :

1. **Toute information en table est paginée.** Une vue qui oublie de paginer est
   découpée par le rendu (25 lignes, `?pg<n>=`) ; une pagination à curseur
   (le journal) sait revenir aux plus récents et au début.
2. **Une page de configuration ne montre qu'un sujet.** Chaque section de
   réglages est découpée en sous-pages ; chaque champ dit ce qu'il fait, sous lui
   (jamais seulement au survol).
3. **Un champ ne se montre que s'il sert.** Un choix limité est un sélecteur
   (modèle, budgets, rôle) ; un champ qui ne vaut que pour un type de fournisseur
   n'apparaît qu'avec lui ; ce que le SDK ou la CLI sait déjà (URL, hôte,
   commande) est rangé dans « Options avancées ».

## Le menu

| Rubrique | Entrées | La question de l'opératrice |
|---|---|---|
| **Accueil** | — | « Tout va bien ? Que dois-je faire ? » |
| **À valider** | Actions à autoriser · Brouillons de courrier · Réponses Teams · Identités à confirmer · Noms à relier · Historique des autorisations | « Qu'est-ce qui attend ma décision ? » |
| **Sa rubrique**, à son nom | En ce moment · Humeur · Postures · Besoins · Sommeil et rythme · Monde et corps · Estime et récit · Qui elle devient · Pensées · Ce qu'elle remarque · Attentes · Journal et rêves · Mémoire · Constellation | « Comment va-t-elle, à quoi pense-t-elle, que retient-elle ? » |
| **Relations & échanges** | Personnes · Conversations · Courrier · Teams · Identités et moyens de communication | « Qui connaît-elle, qu'a-t-on dit ? » |
| **Activité** | Projets · Buts et rappels · Table de l'arbitre · Que ferait-elle ? · En cours · Initiatives · Ses choix · Épisodes · Échéances | « Que fait-elle, pourquoi parle-t-elle ou se tait-elle ? » |
| **Outils** | Ce qu'elle peut faire · Venus d'ailleurs · Prêter à un agent · Apps forgées | « Que peut-elle faire, et pour qui ? » |
| **Connexions extérieures** | Flux RSS · Caméra · Dessins · Appareils · Localisation · Messages du téléphone · Réveils par API · Dépôts Git | « Que perçoit-elle du dehors, qui la fait agir ? » |
| **Réglages** | Tous les réglages · Modèles de texte · Modèles d'image · Personnalité · Configuration des plugins · Transcription · Paramètres avancés · Comptes opérateurs · Historique des réglages | « Que décide l'opératrice ? » |
| **Système** | Santé générale · Processus · Anomalies · File de sortie · Moteur des modèles · Écrans du monde · Appels et coûts · Stockage et sauvegardes · Journal d'événements · Actions des opérateurs · Diagnostic avancé · Contributions · Toutes les vues · Simulations | « La machine tient-elle ? » |

Le menu regroupe les destinations de `app/console.py` sans changer leurs adresses : liens, fiches, vues des
facultés et formulaires gardent les leurs (`InspectorDeps.menu` transmet la présentation à l'inspecteur). Dans une
rubrique, une destination a soit un seul lien (la page entière), soit un lien par onglet, dans leur ordre et sous
leur nom (`tests/protocol/test_console_navigation.py`) ; À valider et Réglages font exception : des raccourcis
nommés par la tâche. Sa rubrique porte son nom, lu dans sa persona au rendu (`MenuGroup.her`, ADR 0070). La page
la plus précise allume le bon lien : une fiche ouverte depuis une liste allume l'entrée de cette liste (un
brouillon : « À valider › Brouillons de courrier »). Les compteurs restent sur les sous-pages ; une rubrique
affiche un point d'attention, sans additionner des listes qui peuvent contenir la même demande. La recherche
globale trouve aussi les pages de la console, sans tenir compte des accents.

Toute la console est dessinée (ADR 0121) : les onglets des destinations sur les données de leur faculté (des
chiffres en tuiles, des faits en grille, des listes en cartes ou en lignes serrées, des tableaux sobres pour
l'exploitation, les formulaires à leur place) ; les fiches, les épisodes, « pourquoi a-t-elle dit ça ? » et les
panneaux (réglages, comptes, demandes en attente) dans le même vocabulaire. Seules les vues de la Forge gardent le
rendu de la console : ses apps déclarent leur interface par un contrat.

## Page par page

### Accueil

Dessiné à la main (`app/handmade/home.py`), il répond à trois questions et se relit seul (le fragment
`/inspecteur/_accueil`, `handmade/live.js`) :

- **Ce qui t'attend** : une ligne par page où décider (chaque onglet qui demande une action : accords en attente,
  brouillons, revendications…), puis les réponses en échec, *aucun modèle configuré*, les processus en échec
  d'affilée, les anomalies, la sauvegarde à faire et les contrôles de santé qui ne passent pas ; chacune mène à sa
  page.
- **Comment elle va** : son humeur en mots, son corps, ses besoins, qui est là (les lectures d'« En ce moment »).
- **Sa journée** : la journée en chiffres et ses huit derniers épisodes. Les courbes des 24 heures sont sur
  « En ce moment ».

### Sa rubrique

- **En ce moment** (`/inspecteur/maintenant`, `app/handmade/now.py`) répond à « comment va-t-elle, et pourquoi ? »
  en croisant ses facultés au même instant que son prompt : son humeur en mots et sur le plan plaisir × éveil, ses
  24 dernières heures sur un seul axe (humeur, énergie, sommeil, besoins, paroles et pensées), son corps, ses
  besoins, ses pensées, les gens, le fil de sa journée, ce qu'elle entreprend et la journée en chiffres. Elle se
  relit toutes les 20 s ; une lecture qui échoue tait sa carte.
- **Humeur, Postures, Besoins, Sommeil et rythme, Monde et corps, Estime et récit, Qui elle devient** : un onglet
  par question ; l'état présent d'abord, son historique ensuite.
- **Pensées, Ce qu'elle remarque, Attentes, Journal et rêves** : les pensées vivantes et les attentes au premier
  plan, les historiques et les règles repliés ; le journal et les récits de ses nuits se lisent comme des
  documents.
- **Mémoire** : Souvenirs, Croyances, Promesses, La vie des autres, Voir venir, Consolidation, Pièces reçues, Place
  des pièces. Les éléments se lisent en listes (contenu, sensibilité, état ; origine et détails repliés). La
  consolidation montre d'abord les passages à reprendre, leur état et leur cause, avec la reprise sur place.
- **Constellation** (`/inspecteur/constellation`, `app/constellation.py`, ADR 0103) : sa mémoire en une boule de
  points, chacun près de ses voisins de sens, et ce qui la parcourt en direct (une parole et sa provenance, un
  élément qui naît, la nuit, un rêve et ses sources).

### Relations & échanges

- **Personnes** (`/inspecteur/personnes`, `app/handmade/people.py`) : une carte par personne — ce qu'elle est pour
  elle, ce qu'elle ressent, ce qui se passe entre elles, ce qu'elle en sait —, qui est là, qui lui manque, une
  recherche et des filtres (proximité, en ligne). L'annuaire, les liens et les présents restent sous « Le détail ».
- **La fiche d'une personne** s'ouvre sur sa **vue d'ensemble** (`app/handmade/person/`) : ce qu'elle ressent
  envers elle, leur histoire, ce qu'elle sait d'elle, ce qui reste en suspens, leurs derniers mots. Les onglets des
  facultés suivent, dessinés sur leurs données (Échanges en conversation, Mémoire en cartes, les listes en
  cartes) ; ce que la vue d'ensemble résume (Synthèse, Lien, Ce qu'elle devine, Affect, Pensées) est rangé au bout
  de la barre, sous « Le détail ». L'onglet **Fichiers** montre ce qu'elle lui a envoyé (une page par fichier,
  téléchargement opérateur, ADR 0062) ; **Son téléphone** et **Sa position** n'apparaissent que si elle en a
  (`@f.inspect(..., shown=)`).
- **Conversations** : Messages, un fil jour par jour (le texte, l'interlocuteur, la date, le lien vers
  l'explication d'une réponse ; la colonne « réponse » dit pourquoi un message est resté sans réponse et y mène) ;
  les questions sans réponse ; **Ses réponses jugées**, les avis de l'opératrice (ADR 0113).
- **Courrier** : Réception et Envoyés en boîte aux lettres (une ligne par message, douze par page, le message
  ouvert dans une liseuse sous la liste, `?lire=`), Brouillons, Contacts. Le compte, le dossier et les filtres se
  gardent dans la pagination et au retour d'un message ; consulter n'envoie rien et ne marque rien comme lu. Un
  mail HTML est reconstruit avec une liste de balises autorisées, sans scripts, styles ni images distantes ; sa
  version texte reste accessible ; un message long se lit en parties de 50 000 caractères au plus. Les brouillons
  qu'elle propose sont distingués de ceux du serveur. Les boîtes se règlent dans Réglages › Plugins › Boîtes aux
  lettres.
- **Teams** (ADR 0069) : Conversations, Réponses (ses réponses rédigées à la place de la personne et leur sort),
  Extension (la clé, le mode).
- **Identités et moyens de communication** : Moyens de communication, Identités à confirmer, Noms à relier (un nom
  dont on lui a parlé, porté par une personne qu'elle connaît : relié depuis sa fiche, ou écarté — jamais deviné,
  ADR 0048), Règles de divulgation.
- Dans la console, une *adresse* (une identité qui parle pour une personne : un compte, un téléphone, un compte
  extérieur) se dit **moyen de communication** ; les clés techniques restent (l'onglet `adresses`, le paramètre
  `handle`). La fiche d'un moyen de communication (`fiche/handle/<clé>`) s'ouvre sur **En bref**
  (`app/handmade/handles.py`) : quatre tuiles (par où, ce que le canal prouve, si elle peut lui écrire d'elle-même,
  son dernier message), *Le canal*, *Qui écrit d'ici* (pour qui il parle, ses droits de propriétaire, ses autres
  moyens), *Ce que ça ouvre* (une ligne par sorte de chose, en privé et en public, et pourquoi), le verdict pas à pas
  replié. Son *Fil* est en bulles ; *Verdict* et *Ses autres moyens de communication* passent sous « Le détail » ;
  *Revendication* ne se montre pas pour un compte authentifié.

### Activité

**Projets** (ADR 0031) : un projet est une boîte noire qu'on pilote, distincte d'un but.

- **Ses projets** : cadres (actifs, en pause, objectifs ouverts, exécutions sur 24 h, accords en attente,
  archivés), puis la liste — mode (Mika ou impersonnel), pour qui, état, objectifs, prochaine exécution, dernier
  compte rendu ; en détail : priorité, plage de travail, agenda, outils, dépôt distant, ce qui sort. « Créer un
  projet » a sa page : le projet, ses objectifs (un par ligne, ponctuels et constants), son mode et ses outils, son
  rythme et sa plage, sa liberté, son dépôt distant.
- **Exécutions** : toutes, filtrables par projet et par verdict ; chacune mène à son épisode (prompt, outils,
  appels, décision) et à son commit.
- **Décisions techniques** : toutes, filtrables par projet et par statut.
- **La fiche** gouverne, onglet par onglet : *Vue d'ensemble* (ce qui attend ta décision, trois cartes, le cadre,
  les objectifs, les dernières exécutions, les décisions en vigueur) · *Objectifs* (chaque ligne se lance, se
  coche, se modifie, se retire ; un constant ne se coche pas) · *Exécutions* (issue, verdict, preuve, commit,
  durée) · *Décisions* (contexte, options, raison ; remplacer, retirer) · *Fichiers* (dossiers à parcourir, lire,
  télécharger, déposer) · *Dépôt git* (historique paginé, un commit en diff coloré, ce qui n'est pas enregistré, le
  dépôt distant : pousser, récupérer, régler) · *Comportement et outils* (modifier le projet, ce que veut dire son
  mode, son rythme, ses outils et leurs noms) · *Carnet* (consignes, ses notes, ce qu'on en a fait, ce qui sort de
  la machine). En tête : lancer maintenant, pause, reprendre, consigne, archiver, restaurer — les formulaires
  d'onglet (`inline`) et les actions de ligne n'y sont jamais.

**Buts et rappels** : les buts vivants (rappels, explorations) et les buts clos. La fiche d'un but : Résumé, Cadre
et réglages, Séances, Carnet, Décisions, Épisodes et prompts ; elle pilote (ADR 0030) : modifier le cadre,
avancer maintenant, rouvrir, priorité, plan de travail.

**Décisions** :

- **Table de l'arbitre** : preuves → score → taux, la politique.
- **Que ferait-elle ?** : pour une personne, ses lignes, ce qui la pousse, ce qui la retient, dans combien de temps
  elle agirait en moyenne ; la fiche d'une personne y mène.
- **En cours** (`app/handmade/running.py`) : une phrase sur ce qu'elle fait (« elle répond à Adrien depuis 12 s »,
  ou rien et son dernier épisode), ce qui tourne en arrière-plan ; ce qui attend (chaque voie, ses places occupées
  et sa file, les questions sans réponse, les actions à autoriser, les ressources réservées) ; ses huit derniers
  épisodes, chacun vers sa page. Le relevé est daté, avec un lien pour l'actualiser.
- **Initiatives** : budget du jour, période réfractaire, ignorées.
- **Ses choix**, **Épisodes** (filtres sorte, issue, cible), **Échéances**.

**Un épisode** a sa page, en onglets : Résumé (résultat, durée, événements et paroles, message déclencheur, ses
dernières paroles — lu dans le journal, sans rien lancer), Déroulé, Ce qu'elle a dit, Prompt, Outils, Appels de
modèle, Décision.

**Pourquoi a-t-elle dit ça ?** (ADR 0042) : une page par parole (`/inspecteur/parole/<seq>`), liée depuis le fil,
l'onglet « Échanges » d'une personne, chaque épisode et chaque événement de parole : ce qu'elle a dit ; ce qui
l'a fait parler (le message, ou la ligne exacte de l'arbitre pas à pas) ; les sections de son prompt, nommées ;
ce dont elle s'est souvenue, avec le texte ; ses outils et leurs résultats ; l'avis de l'opératrice (« Ton avis »).
Les clés techniques sont dans « Détails techniques ».

- « Rejouer avec… », sur cette page et dans l'onglet « Prompt » d'un épisode : le prompt gardé (la trace, 14 jours)
  renvoyé tel quel à un fournisseur déclaré, par `Gateway.try_on` — un seul appel, derrière tout le fond, sous le
  rôle à part `trial` (Système › Appels et coûts ne le mêle pas à « répondre »). La page montre côte à côte ce
  qu'elle a vraiment dit et ce que l'autre modèle répond, avec durée, jetons et coût ; un appel d'outil est
  affiché, jamais exécuté, et la CLI de Claude Code reçoit le prompt sans ses outils (elle le dit). Rien n'est
  livré, rien n'entre au fil ni dans sa mémoire, rien n'est gardé au-delà de la page : seule une ligne
  `runtime.operated` (`console.rejouer`, sujet : l'épisode) entre au journal, avant l'envoi. Une trace tronquée ou
  expirée désactive les boutons ; un prompt servi en local qui partirait vers un service hébergé est signalé avant
  l'envoi (il mêle les personnes).
- La même adresse, avec le numéro d'un message reçu resté sans réponse, répond à « Pourquoi n'a-t-elle pas
  répondu ? » : la fin d'épisode qui l'a réglé et sa cause en mots (un silence choisi, ce qui l'a fait taire, trop
  tard, une panne), puis ce qu'elle avait sous les yeux et ses outils, ou l'appel de modèle en échec.

### Outils (ADR 0064, 0122, 0123, 0128, 0129, 0130)

- **Ce qu'elle peut faire** (`outils/tous`, `?q=`, `?lot=`) : une grille. Ses familles d'outils en lignes, chacune
  s'ouvre sur ses outils (ce qu'il fait, son nom, ses appels des 14 derniers jours) ; les situations en colonnes,
  par ce qui se passe (elle répond à sa propriétaire, un compte, une inconnue, un salon ; d'elle-même, à sa
  propriétaire ; seule sur un but, un projet, un brouillon). Une case cochée : elle peut s'en servir là ; la
  décocher le lui retire (restreindre seulement) ; un tiret : pas prévu, et pourquoi au survol. Dessous, replié, le
  texte exact que son prompt porte sur ses outils. `?outil=<nom>` ouvre sa fiche : où elle peut s'en servir,
  réglable par situation (comme prévu, retiré ; sous la main ou à chercher quand le fournisseur diffère), ses
  derniers appels vers leur épisode, ses arguments lus du schéma, sa condition d'offre et la règle vérifiée à
  l'exécution.
- **Venus d'ailleurs** (`outils/serveurs`, l'onglet du plugin MCP) : les services branchés (état, outils servis /
  proposés, à revoir, son genre et ses trois réglages — badge et vitale), puis les outils que ses apps lui donnent
  (la vue de la Forge, dessous). La fiche d'un serveur a trois onglets (ADR 0130) : *En bref* (son état, ses outils
  servis, à revoir, ses appels ; ses réglages en quatre réponses ; ce qu'elle en lit ; *qui peut quoi* — ses outils
  servis devant toi, chaque personne que le service ouvre, les autres comptes, quand elle travaille seule, et ce
  qu'elle en garde ; pour qui et quand ; le côté technique replié), *Réglages du service* (dessiné : un genre pour
  aller vite, puis quatre questions — avec qui, quand, avant de se servir d'un outil elle…, ce qu'elle y lit elle…),
  *Ses outils* (dessiné : « À regarder », un choix par outil nouveau ou changé — coupé, lecture, action —, puis ce
  qui lit et ce qui agit, chacun avec ce qu'il fait devant qui et où il s'écarte du service ; une ligne se déplie sur
  son réglage, d'un seul envoi — servi, lit ou agit, avant de s'en servir, ce qu'elle en retient, ce qu'elle lit de
  lui —, ses exceptions par situation et par personne repliées dedans ; `?outil=` l'ouvre ; un outil changé est
  suspendu) ; sous « Le détail », *État* (ce qui a été déclaré, ce qu'il répond, ce qu'il dit de lui-même — jamais
  lu par elle —, « Tester la connexion ») et *Appels* (pour qui, seule ou sur accord, l'issue, qui a décidé). La
  connexion se règle par « Modifier la connexion ». Une alerte dit ce que le genre ne dit pas : un service qui ne
  sert à personne, des outils plus libres que lui.
- **Prêter à un agent** (`outils/expose`) : la console en lecture — créer, renouveler ou fermer son jeton (montré
  une seule fois, avec sa ligne `claude mcp add`), l'ouvrir au réseau ou l'y fermer (ADR 0126 : sa ligne prend alors
  l'adresse par laquelle on lit la console), choisir ce qu'elle montre (ses pages d'office et d'autres, ses
  vues, ses fiches, « pourquoi ») ; ses outils prêtés — des points `/mcp/pret/<nom>` à déclarer (`?nouveau`), régler
  (`?pret=<nom>` : lecture seule ou non, ses outils), renouveler et retirer, avec ce que chacun sert et ses derniers
  appels ; replié en bas, le relais MCP du moteur Claude Code (lu).
- Les anciennes pages mènent ici : `outils/qui`, `outils/texte` → `outils/tous` ; `outils/outils_apps` →
  `outils/serveurs`.
- **Apps forgées** : le catalogue (recherche par nom ou titre) ; la fiche d'une app : État, Vues, Réglages, Code,
  Base, Journal, Vécu. Les commandes de maintenance sont sur État et Code ; Vues garde les actions de l'app,
  Réglages sa configuration.

### Connexions extérieures

- **Flux RSS** (recherche dans les titres et résumés), **Caméra**, **Dessins**, **Appareils** (le jeton des
  appareils) ; chaque page renvoie aux réglages de son plugin, et un état vide explique comment commencer.
- **Messages du téléphone** (`sens/messages`, `app/handmade/senses.py`, ADR 0120) : le téléphone de chaque personne,
  puis ses conversations (un contact, un groupe), repliées, qui s'ouvrent en bulles jour par jour ; huit
  conversations par personne quand on regarde tout le monde, toutes quand on en choisit une (`?personne=`, des
  puces) ; puis les réponses qu'elle a proposées et leur sort.
- **Localisation** (`sens/positions`, ADR 0119) : une ligne par personne, ses téléphones réunis (ses autres moyens de
  communication dépliés), puis ce que les téléphones lui ont dit, par pages (`?avant=`) ; le même filtre par
  personne.
- **Réveils par API** (ADR 0068, 0117) : les réveils et leurs derniers appels ; la fiche d'un réveil : État (sa clé,
  générée ici et montrée une fois ; comment l'appeler), Appels.
- **Dépôts Git** : le jeton avec lequel ses projets poussent vers leur dépôt distant (jamais réaffiché, jamais dans
  le journal).

### À valider

- **Actions à autoriser** : une carte par demande — ce qui partira exactement, avant les boutons ; le contexte ; les
  arguments techniques à part ; une note facultative —, approuver ou refuser. Une demande bloquée dit pourquoi et
  désactive l'approbation ; l'accord porte sur l'empreinte du contenu vu.
- **Brouillons de courrier**, **Réponses Teams**, **Identités à confirmer**, **Noms à relier** : des raccourcis vers
  les onglets de leur destination.
- **Historique des autorisations** : décisions et exécutions, avec la capacité (pas seulement un numéro), paginé.

### Réglages

Aucune page n'a de sélecteur de pages en tête : le menu de gauche, les onglets et **Tous les réglages** y mènent.
Tous les réglages est l'annuaire, construit à partir des pages déclarées sans charger leurs valeurs : catégories,
descriptions courtes, recherche par plusieurs mots sans tenir compte des accents ; les paramètres internes y sont
repliés à part, ouverts quand une recherche les trouve. Une liste d'entrées (des fournisseurs, des boîtes…) se lit
en fiches (`handmade/reglages/enregistrements.html`) avec leurs valeurs non secrètes, la modification et le retrait
confirmé, et peut se décrire en mots (`SettingsSection.describe`) : un fournisseur dit son type, s'il la fait
parler, sa clé, son modèle, les rôles qui le désignent, ses bornes en mots et ses appels des dernières 24 h ; son
bouton « Détail » déplie sa consommation et ses temps de réponse sur 24 h et sur 7 jours (appels, échecs, temps
moyen, médian, les plus lents, attente d'un créneau, jetons lus et écrits, part lue depuis le cache, coût), puis
rôle par rôle (`CallLog.profile`).

| Rubrique | Sous-page | Contenu |
|---|---|---|
| Intelligence | Fournisseurs (menu : Modèles de texte) | chaque fournisseur a sa page : type, modèle (**sélecteur** chargé chez le fournisseur, même pour un fournisseur pas encore enregistré), connexion, clé ; options avancées repliées (URL, hôte, commande, créneaux, température…) ; ses budgets (contexte, sortie, caractères par jeton) ; un échec est journalisé, sans basculement |
| | Qui sert quoi | un sélecteur par rôle, rangés par famille (voix, mémoire, compréhension, sens, travail), et ce qui sert **vraiment** chaque rôle après replis — sauf `polish` (rendre naturel), qui n'en a pas |
| | Fournisseurs d'images, Qui dessine quoi (menu : Modèles d'image) | les fournisseurs d'images et leurs rôles (`draw`, `edit`, `own`), ADR 0061 |
| Personnage (menu : Personnalité) | Identité | nom, nature, description, langue, fuseau |
| | Ton et parole | ton, façons de parler, salutations (le ton de ses bonjours, jamais recopiées), ses exemples de voix en chat |
| | Caractère | traits, manies, fragilités, valeurs, centres d'intérêt |
| | Sa vie | sa vie d'IA VTuber à sa façon, ses goûts et avis, ce qui est vrai d'elle (ADR 0047) |
| | Tempérament | en tête, **la forme de son caractère** : une figure de tous ses curseurs (les 27 du caractère et son chronotype), rangés par famille ; la forme proposée pleine, celle d'aujourd'hui en pointillé, la valeur de chaque sommet dans une bulle au survol, au clavier ou au toucher ; ses traits les plus marqués en mots. Puis **partir d'un profil** : changer le sélecteur dessine la différence sur la figure sans rien remplir (`static/handmade/temperament.js`) ; « Pré-remplir » (`?profil=<clé>`) ouvre le formulaire sur ses valeurs, rien n'est enregistré avant « Enregistrer » ; ses 18 profils repliés, chacun avec sa silhouette. Puis ses curseurs, l'humeur de fond, sa réaction, sa défense, ce que pilote chaque curseur ; **Voir l'effet** (`app/handmade/temperament.py`, `SettingsSection.prefill`) |
| | Autrices | en tête, **où elles écrivent** : flux par flux (le chat, chaque boîte mail, Teams, le téléphone), l'autrice qui y écrit, ce qu'elle récrit et ce qui l'en empêcherait (aucun modèle au rôle « rendre naturel », Teams désactivé). Puis **ses autrices** en cartes, sous leur nom (où elles écrivent, leurs codes en bref ; ajouter, modifier, retirer), et **Qui écrit où**, une ligne par flux (`app/authors.py`, `app/handmade/authors.py`, ADR 0124) |
| | Import / export | le document YAML, revenir au fichier, l'historique des révisions |
| Canaux | Dépôts git | le jeton de ses dépôts distants (aussi : Connexions extérieures › Dépôts Git) |
| | Notifications du téléphone | la clé Firebase (collée ici ou posée en fichier), d'où elle vient, les téléphones notifiables, ce qui est parti, le dernier échec (ADR 0077) |
| Plugins (menu : Configuration des plugins) | Vue d'ensemble des plugins | accès aux connexions et aux comportements ; lien vers les vues d'utilisation ; les réglages des apps restent dans la Forge |
| | Boîtes aux lettres | chaque boîte a sa page (lire, envoyer, sa voix, initiative) |
| | Teams | la clé de l'extension, le mode de ses réponses (brouillon, accord, autonome), sa signature |
| | Outils extérieurs (MCP) | chaque serveur a sa page : **à quoi il sert, pour elle** (obligatoire), quand s'en servir, actif ; à une adresse (URL, jeton scellé, autorité) ou sur cette machine (commande, arguments, variables, variables secrètes scellées, réseau, dossiers partagés) ; avec qui (toi, les comptes, des personnes choisies), quand, en main ; ce qu'elle fait seule ; ce qu'elle en garde ; bornes. Nom fixe (il entre dans le nom de ses outils). ADR 0064, 0128 |
| | Flux RSS | adresses suivies |
| | Transcription | service, modèle, clé |
| | Appareils | jeton des appareils |
| | Réveils par API | chaque réveil a sa page : **à quoi il sert** (obligatoire), actif, consignes (elles priment sur le texte d'un appel, cité), projet, impersonnel, outils (lots), ignorer son rythme, à qui rendre compte, bornes. Nom fixe (la fin de son URL). Sa clé se génère sur sa fiche (Connexions extérieures › Réveils par API), montrée une fois. ADR 0068 |
| Paramètres avancés | Vue d'ensemble | provenance des paramètres, ce que pilote chaque curseur |
| | une page par faculté | ses paramètres **rangés par groupe** (un groupe = une page), chacun avec sa valeur, sa provenance, ses bornes et son sens ; une surcharge se pose en changeant la valeur ; **Voir l'effet** : avant d'enregistrer, les lignes de l'arbitre et les faits partagés qui changeraient maintenant avec les valeurs tapées (avant → après) — rien n'est écrit ni journalisé, ce qui s'est accumulé n'est pas rejoué |
| Comptes opérateurs | Comptes | liste paginée, créer, modifier (opérateur, actif, mot de passe) — audité ; sur la page d'un compte, ses applications connectées (téléphone, moteur : sorte, origine, dernier usage, jamais le secret), douze par page, et « révoquer » — audité (ADR 0062) |
| Historique des réglages | Journal des modifications | chaque réglage enregistré, chaque rejournalisation des paramètres |

### Système

| Groupe | Page | Contenu |
|---|---|---|
| Surveillance | Santé générale | le verdict ; les dix contrôles en tuiles, ceux en panne d'abord, chacun avec son constat, son détail et un lien vers son diagnostic ; **ses projections** : une jauge en demi-cercle (combien sont à jour), une ligne par projection (son nom en clair, sa faculté, son niveau, une barre : où elle en est du journal), la quarantaine, les vues lentes en barres (la pire fois, un trait pour la dernière) (`app/handmade/system.py::projections`) |
| | Processus | ceux qui échouent d'abord : passages, échecs, dernière erreur, en cours |
| | Anomalies | échecs d'évaluation, traces du journal (supplanté, oubli…), échecs de processus gardés au journal ; une page sans anomalie le dit |
| | File de sortie | (`app/handmade/system.py::outbox`) à quoi elle sert et le chemin de ce qui part (écrit au journal → en route → parti, et ce qui est à traiter) ; **À traiter** (le filtre d'état le suit, 8 par page, Relancer / Marquer comme vu, l'erreur, ce qu'il faut vérifier) ; **ce qui part, par sorte**, en mots (ses messages, ce que montrent ses écrans, ce qu'elle fait au dehors — l'action nommée —, le ménage), une barre empilée parti / en route / à traiter / vu ; **les derniers départs**, filtrés par état, avec leur heure et leur événement |
| | Moteur des modèles | par fournisseur : créneaux occupés / total, quota ; par rôle : qui sert vraiment |
| | Écrans du monde | les clients de `/ws/world` (client, moteur, qui, rôles), qui tient le bail d'hôte et qui l'attend ; par hôte, la révision chargée et ce qui lui manque (ancres, assets, révision dépassée), en avertissement tant qu'il est connecté. ADR 0051 |
| | Appels et coûts | par jour, rôle, fournisseur, **modèle** ; derniers appels paginés |
| | Stockage et sauvegardes | taille des bases, dernier instantané ; la dernière sauvegarde (ce qui s'est écrit depuis), la dernière vérification, les archives gardées |
| Journaux | Journal d'événements | le journal, filtrable, paginé dans les deux sens |
| | Actions des opérateurs | ce que les opérateurs ont fait |
| Anatomie | Diagnostic avancé · Contributions · Toutes les vues | le mécanisme |
| Outils | Simulations | les rapports |

## Les formes

- **Cadres** (`Stats`) : un nombre, un état ; toujours en tête de page, jamais
  plus de six.
- **Tables** : une ligne entière mène à sa fiche ; le détail se déplie sous la
  ligne par un chevron ; le compte total s'affiche au-dessus ; 25 lignes par
  page par défaut. Une collection en fiches ou en fil passe en tableau sobre par
  « Tableau » (`vue_pg<n>=table`), qui garde les filtres et la pagination, même sans
  JavaScript.
- **Courbes** : une échelle par courbe, la table des valeurs repliée dessous. Un
  graphe a une hauteur fixe et s'étire en largeur seulement (`inspector/svg.py`).
- **Fiches** (`Fields`) : libellé à gauche, valeur à droite, deux colonnes au
  plus en largeur. Une fiche de collection ou de réglage mène à sa page sur toute
  sa surface.
- **Formulaires** : un groupe = un cadre titré avec sa phrase d'explication ;
  l'aide de chaque champ sous lui ; les options rarement utiles repliées sous
  « Options avancées » ; une seule barre « Enregistrer » par page. Une saisie non
  enregistrée se signale et la sortie est protégée ; les erreurs ont un résumé
  navigable au clavier.
- **Actions d'en-tête** : une barre de boutons ; le formulaire s'ouvre en
  panneau sous l'en-tête, un seul à la fois.

## Composants communs et langage de la Forge

- `kernel/inspect.py` décrit les blocs natifs ; `kernel/envelope.py` valide
  et documente leur représentation JSON pour les apps (version 2 conservée).
- `inspector/render.py` prépare les cellules, liens, filtres, tableaux,
  graphiques et paginations ; les valeurs des graphiques utilisent le même
  composant de table que les autres vues.
- `_cells.html`, `_forms.html` et `_navigation.html` fournissent les primitives
  réutilisables ; `_blocks.html` les compose en sections, grilles, détails,
  statistiques et formulaires. Chaque occurrence d'un formulaire reçoit son
  propre identifiant, même si la même action apparaît plusieurs fois.
- `Workspace` compose une navigation latérale et un contenu ; `Toolbar`
  regroupe des actions ; `ActionSlot.presentation="button"` ouvre le formulaire
  à la demande ; `Text.secondary` ajoute un aperçu et `Prose.reading` un
  document lisible. Ces primitives sont aussi disponibles dans le langage
  JSON de la Forge ; le HTML brut reste réservé au lecteur natif nettoyé.
- `Table.layout` et `Column.role` présentent une table en fiches ou en fil ;
  l'enveloppe Forge accepte ces champs facultatifs.
- `Column.detail=True` range une information secondaire dans le détail de
  chaque ligne, sans perdre sa valeur, son lien ou la pagination. Dans une app
  Forge : `{"label": "Identifiant", "detail": true}`.
- `Head.action_tabs` limite les commandes globales d'une fiche aux onglets où
  elles servent. Une app conserve ses propres actions dans ses blocs de vue.
- Les filtres d'une app sont déclarés dans `manifest.yaml` (`params`) et
  rendus par l'hôte : recherche, entier, liste ou booléen. Le formulaire garde
  l'app et la vue sélectionnées et repart de la première page après filtrage.
- Sans pagination explicite, chaque table reçoit une page de 25 lignes et un
  compteur, même vide. Un historique à curseur annonce que son total est
  inconnu. La navigation reste disponible sur sa dernière page.
- Les téléchargements natifs sont déclarés par le propriétaire de la fiche
  (`Faculty.download`) et servis par une route commune authentifiée. Le nom du
  fichier est nettoyé et la réponse force le téléchargement sans mise en cache.
  Ce mécanisme n'ajoute pas de HTML arbitraire au langage des apps Forge.

Pour une vue Forge avec plusieurs grandes collections, utiliser un nom par
pagination (facultatif, `page` reste accepté) :

```json
{"type": "table", "title": "Articles", "columns": ["Titre"],
 "rows": [["Un article"]],
 "pagination": {"param": "page_articles", "page": 1, "total": 51, "per_page": 25}}
```

L'app lit `params.get("page_articles", 1)`, borne le numéro selon son total,
puis découpe ses données. Une deuxième table utilise par exemple
`page_alertes`. Ces paramètres sont des entiers bornés par l'hôte, conservés
dans les liens entre vues et réservés à la pagination. Sections, grilles,
statistiques, courbes, détails de ligne et formulaires se combinent dans la
même enveloppe, sans HTML ni JavaScript fournis par l'app.

## Vérifier la console

Les contrôles HTTP sont dans `tests/fixtures/console_html.py` (structure de chaque document : un seul titre
principal, identifiants uniques, aucun lien ni formulaire imbriqué, en-têtes associés aux colonnes, pagination),
`tests/protocol/test_console_apercu.py`, `test_console_workflows.py`, `test_console_settings.py`,
`test_console_navigation.py` et `test_inspector_pages.py` (sous `tests/protocol/`), `tests/unit/test_forge_console.py`,
`tests/unit/test_console_pagination.py` et `tests/contract/test_mail_feeds.py`.

`tests/browser/console.cjs` les complète avec un vrai navigateur : menu au clavier, mode sans JavaScript,
recherche des rubriques, champs conditionnels, filtres, état des formulaires, panneaux imbriqués, expiration de
session, contrastes et largeur de chaque page exportée à 390 et 1440 px. Depuis `backendv2`, avec Playwright
disponible pour Node (ou son dossier dans `NODE_PATH`) et Chrome installé :

```bash
.venv/bin/python -m mika console apercu --out /tmp/mika-console-apercu
MIKA_CONSOLE_PREVIEW=/tmp/mika-console-apercu node --test tests/browser/console.cjs
```

`mika console apercu` exporte chaque page, en clair et en sombre, d'une Mika neuve sur des données fictives
(modèle factice, port de courrier simulé, rien ne sort de la machine, POST refusés).
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` permet de préciser un autre exécutable Chromium. Le navigateur emploie un profil
temporaire ; les pages et ressources sont servies par interception depuis l'export et les fichiers source, et les
requêtes vers un autre hôte sont bloquées. Aucun compte de l'installation n'est utilisé.
