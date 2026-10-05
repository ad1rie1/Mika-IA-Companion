# La carte de la console

Ce que chaque menu de `/inspecteur/` montre, et sous quelle forme. Référence de
la refonte du 30/09/2026 (ADR 0029) ; la carte vit dans `app/console.py`, les
réglages dans `app/reglages.py`.

Trois règles tiennent toute la console :

1. **Toute information en table est paginée.** Une vue qui oublie de paginer est
   découpée par le rendu (25 lignes, `?pg<n>=`) ; une pagination à curseur
   (le journal) sait revenir aux plus récents et au début.
2. **Une page de configuration ne montre qu'un sujet.** Chaque section de
   réglages est découpée en sous-pages rangées dans un sous-menu ; chaque champ
   dit ce qu'il fait, sous lui (jamais seulement au survol).
3. **Un champ ne se montre que s'il sert.** Un choix limité est un sélecteur
   (modèle, repli, rôle) ; un champ qui ne vaut que pour un type de fournisseur
   n'apparaît qu'avec lui ; ce que le SDK ou la CLI sait déjà (URL, hôte,
   commande) est rangé dans « Options avancées ».

## Étape 1 — les informations essentielles, par menu

| Groupe | Menu | La question de l'opérateur | L'essentiel |
|---|---|---|---|
| — | **Tableau de bord** | « Tout va bien ? Que dois-je faire ? » | ce qui attend (accords, brouillons, revendications, questions, apps cassées, processus en échec, modèles absents) · son état en ce moment · sa journée · ses derniers épisodes |
| Elle | **Humeur et corps** | « Comment va-t-elle ? » | humeur, postures envers chacun, besoins, rythme et sommeil, estime et récit |
| Elle | **Pensées et nuits** | « À quoi pense-t-elle ? » | pensées vivantes, ce qu'elle a remarqué, ce qu'elle attend, ses nuits (journal, rêves) |
| Elle | **Mémoire** | « Que retient-elle ? » | souvenirs, croyances, promesses, relecture (consolidation) |
| Ses relations | **Personnes** | « Qui connaît-elle ? » | personnes, liens (rythme, manque), présents ; sur la fiche, l'onglet « Fichiers » : ce qu'elle lui a envoyé (une page par fichier, téléchargement opérateur — ADR 0062) |
| Ses relations | **Identités** | « Qui parle derrière chaque adresse ? » | adresses, revendications, politique de confiance |
| Ses relations | **Conversations** | « Qu'a-t-on dit ? » | messages, questions sans réponse |
| Son activité | **Décisions** | « Pourquoi parle-t-elle ou se tait-elle ? » | table de l'arbitre maintenant, ce qui tourne en ce moment, budget d'initiatives, ses choix, épisodes, échéances |
| Son activité | **Buts** | « Que se propose-t-elle de faire ensuite ? » | buts vivants (rappels, explorations), buts clos |
| Son activité | **Projets** | « Que mène-t-elle comme travail ? » | ses projets (cartes et liste), toutes les exécutions, toutes les décisions techniques ; une fiche par projet |
| Son activité | **Ses outils** | « Que peut-elle faire, pour qui, et qu'en lit-elle ? » | tous ses outils (internes en lecture seule, extérieurs), qui reçoit quoi, ce qu'elle lit, outils de ses apps, serveurs extérieurs, ce que Mika expose (ADR 0064) |
| Son activité | **Approbations** | « Que veut-elle faire sortir ? » | en attente (décider), historique |
| Ses canaux | **Courrier** | « Lire et traiter les messages de quelle boîte ? » | comptes et dossiers en navigation, réception, brouillons de Mika, envoyés, contacts ; gestion des comptes dans Configuration |
| Ses canaux | **Flux et capteurs** | « Ce qu'elle perçoit du monde » | flux RSS, caméra, appareils |
| Ses canaux | **Apps forgées** | « Ses petites apps » | liste, état, cassées |
| Exploitation | **Configuration** | « Que décide l'opérateur ? » | sous-menu : Intelligence, Personnage, Canaux, Plugins, Comportement, Accès, Historique |
| Exploitation | **Système** | « La machine tient-elle ? » | sous-menu : Surveillance, Journaux, Anatomie, Outils |

Ce qui a changé de place : *Fil* devient **Conversations** (il partageait
l'icône ✉ avec le Courrier) ; *Sens* devient **Flux et capteurs** (le courrier
est lui aussi un sens) ; *Réglages* devient **Configuration** (les comptes
d'accès y ont leur place, l'historique aussi) ; *Initiatives* passe juste après
la table de l'arbitre.

## Étape 2 — pour chaque menu, ce qui doit se voir et se consulter

### Tableau de bord
- **À traiter** (cadres cliquables) : accords en attente, brouillons à décider,
  revendications, questions sans réponse, apps cassées, processus en échec
  d'affilée, anomalies, *aucun modèle configuré* — chacun mène à sa page.
- **En ce moment** (cadres) : humeur, énergie, sommeil, envie dominante,
  présents, épisodes en cours, file d'attente, heure.
- **Sa journée** (courbes 24 h) : énergie et pression de sommeil, besoins
  (les trois), valence et éveil, estime.
- **Aujourd'hui** (cadres) : épisodes par issue, coût des modèles.
- **Derniers épisodes** (table paginée).

### Projets (ADR 0031)
Un projet est une boîte noire qu'on pilote, distincte d'un but.
- **Ses projets** : cadres (actifs, en pause, objectifs ouverts, exécutions sur
  24 h, accords en attente, archivés), puis la liste — mode (Mika ou
  impersonnel), pour qui, état, objectifs, prochaine exécution, dernier compte
  rendu ; en détail : priorité, plage de travail, agenda, outils, dépôt distant,
  ce qui sort. « Créer un projet » a sa page : le projet, ses objectifs (un par
  ligne, ponctuels et constants), son mode et ses outils, son rythme et sa plage,
  sa liberté, son dépôt distant.
- **Exécutions** : toutes, filtrables par projet et par verdict ; chacune mène à
  son épisode (prompt, outils, appels, décision) et à son commit.
- **Décisions techniques** : toutes, filtrables par projet et par statut.
- **La fiche** gouverne, onglet par onglet : *Vue d'ensemble* (ce qui attend ta
  décision, trois cartes, le cadre, les objectifs, les dernières exécutions, les
  décisions en vigueur) · *Objectifs* (chaque ligne se lance, se coche, se
  modifie, se retire ; un constant ne se coche pas) · *Exécutions* (issue,
  verdict, preuve, commit, durée) · *Décisions* (contexte, options, raison ;
  remplacer, retirer) · *Fichiers* (dossiers à parcourir, lire, télécharger,
  déposer) · *Dépôt git* (historique paginé, un commit en diff coloré, ce qui
  n'est pas enregistré, le dépôt distant : pousser, récupérer, régler) ·
  *Comportement et outils* (modifier le projet, ce que veut dire son mode, son
  rythme, ses outils et leurs noms) · *Carnet* (consignes, ses notes, ce qu'on en
  a fait, ce qui sort de la machine). En tête : lancer maintenant, pause,
  reprendre, consigne, archiver, restaurer — les formulaires d'onglet
  (`inline`) et les actions de ligne n'y sont jamais.

### Humeur et corps · Pensées et nuits · Mémoire · Personnes · Identités · Conversations · Buts · Courrier · Flux et capteurs · Apps forgées
Ces pages sont **déclarées par les facultés** (`@f.inspect`) : leur contenu
reste le leur. La refonte y garantit la pagination de chaque table, remplace
les plafonds silencieux (10, 12, 20, 50, 64, 100, 200…) par des pages, et
corrige les défauts relevés (le compte « dans la boîte », les commits datés de
1970, le filtre d'autorité des buts clos, la 5ᵉ courbe perdue de l'accueil).

### Pourquoi a-t-elle dit ça ? (ADR 0042)
Une page par parole (`/inspecteur/parole/<seq>`), liée depuis le fil, l'onglet
« Échanges » d'une personne, chaque épisode et chaque événement de parole : ce
qu'elle a dit ; ce qui l'a fait parler (le message, ou la ligne exacte de
l'arbitre pas à pas) ; les sections de son prompt, nommées ; ce dont elle s'est
souvenue, avec le texte ; ses outils et leurs résultats. Les clés techniques
sont dans « Détails techniques ».

La même adresse, avec le numéro d'un message reçu resté sans réponse, répond à
« Pourquoi n'a-t-elle pas répondu ? » : la fin d'épisode qui l'a réglé et sa
cause en mots (un silence choisi, ce qui l'a fait taire, trop tard, une panne),
puis ce qu'elle avait sous les yeux et ses outils, ou l'appel de modèle en
échec. Dans le fil, la colonne « réponse » dit cette cause (« sans réponse :
s'est tue », « sans réponse : panne : délai dépassé ») et y mène.

### Décisions
- **Maintenant** : la table de l'arbitre (preuves → score → taux), la politique.
- **Que ferait-elle ?** *(nouveau)* : pour une personne, ses lignes, ce qui la
  pousse, ce qui la retient, dans combien de temps elle agirait en moyenne ; la
  fiche d'une personne y mène.
- **En cours** *(nouveau)* : épisodes ouverts (sorte, cible, depuis), files
  d'attente par voie, baux tenus.
- **Initiatives** : budget du jour, période réfractaire, ignorées.
- **Ses choix**, **Épisodes** (filtres sorte/issue/cible, pagination juste),
  **Échéances**.

### Ses outils (ADR 0064)
- **Tous ses outils** : une ligne par outil du registre (origine interne ou
  extérieure, lot et sa phrase, ce qu'il fait, à qui il est offert, appels des
  14 derniers jours) ; `?outil=<nom>` ouvre sa fiche (arguments lus du schéma,
  condition d'offre, règle vérifiée à l'exécution, qui le reçoit et pourquoi
  pas, derniers appels vers leur épisode). Un outil défini dans le code ne se
  règle pas ici : aucun formulaire.
- **Qui reçoit quoi** : lots × situations types (propriétaire, compte,
  inconnue, salon, initiative, pas, projet, tâche) — en main, à la demande, pas
  offert —, calculé par la porte d'offre du pipeline (`runtime.tools.offer`).
- **Ce qu'elle lit** : le texte exact de la règle de ses mains et du catalogue
  pour une situation, et ses outils en main / à la demande.
- **Ce que Mika expose** : le relais MCP du moteur Claude Code et la console en
  MCP (ses outils, son jeton).
- Ajoutés par les plugins : **Outils de ses apps** (Forge) ; **Serveurs extérieurs** (MCP : état, servis / proposés, à revoir — badge et vitale), et la fiche d'un serveur : *État* (ce qui a été déclaré, ce qu'il répond, ce qu'il dit de lui-même — jamais lu par elle —, « Tester la connexion »), *Ses outils* (ce qu'il propose, ce que l'opérateur en a décidé, « Régler l'outil » : activé, nature, accord, ce qu'elle lit ; un outil changé est suspendu), *Appels*.

### Approbations
- **En attente** : une carte par demande (ce qui partira, contexte, arguments),
  approuver / refuser.
- **Historique** : décisions et exécutions, avec la capacité (pas seulement un
  numéro), paginé.

### Configuration (sous-menu)
| Rubrique | Sous-page | Contenu |
|---|---|---|
| Intelligence | Fournisseurs | liste paginée ; chaque fournisseur a sa page : type, modèle (**sélecteur** chargé chez le fournisseur, même pour un fournisseur pas encore enregistré), connexion, clé ; options avancées repliées (URL, hôte, commande, créneaux, température…) ; repli = **sélecteur** parmi les autres fournisseurs |
| | Rôles | un sélecteur par rôle, rangés par famille (voix, compréhension, sens, travail), et ce qui sert **vraiment** chaque rôle après replis |
| | Contexte | la fenêtre que le prompt peut remplir |
| Personnage | Identité | nom, description, langue, fuseau |
| | Ton et parole | ton, façons de parler, salutations (le ton de ses bonjours, jamais recopiées) |
| | Caractère | traits, manies, fragilités, valeurs, centres d'intérêt |
| | Sa vie | sa vie d'IA VTuber à sa façon, ses goûts et avis, ce qui est vrai d'elle (ADR 0047) |
| | Tempérament | les huit curseurs, l'humeur de fond, ce que pilote chaque curseur |
| | Import / export | le document YAML, revenir au fichier, l'historique des révisions |
| Canaux | Dépôts git | le jeton avec lequel ses projets poussent vers leur dépôt distant (jamais réaffiché, jamais dans le journal) |
| Plugins | Vue d’ensemble des plugins | accès aux connexions et aux comportements ; lien vers les vues d’utilisation ; les réglages des apps restent dans la Forge |
| | Boîtes aux lettres | liste ; chaque boîte a sa page (lire, envoyer, sa voix, initiative) |
| | Outils extérieurs (MCP) | liste ; chaque serveur a sa page : **à quoi il sert, pour elle** (obligatoire), quand s'en servir, actif ; à une adresse (URL, jeton scellé, autorité) ou sur cette machine (commande, arguments, variables, variables secrètes scellées, réseau, dossiers partagés) ; pour qui, quand, en main ; bornes. Nom fixe (il entre dans le nom de ses outils). ADR 0064 |
| | Flux RSS | adresses suivies |
| | Transcription | service, modèle, clé |
| | Appareils | jeton des appareils |
| Comportement | Vue d'ensemble | provenance des paramètres, ce que pilote chaque curseur |
| | une page par faculté | ses paramètres **rangés par groupe** (un groupe = une page), chacun avec sa valeur, sa provenance, ses bornes et son sens ; une surcharge se pose en changeant la valeur |
| Accès | Comptes | liste paginée, créer, modifier (opérateur, actif, mot de passe) — audité ; sur la page d'un compte, ses applications connectées (téléphone, moteur : sorte, origine, dernier usage, jamais le secret) et « révoquer » — audité (ADR 0062) |
| Historique | Journal des modifications | chaque réglage enregistré, chaque rejournalisation des paramètres |

### Système (sous-menu)
| Rubrique | Sous-page | Contenu |
|---|---|---|
| Surveillance | Santé | contrôles, projections, quarantaine, vues lentes |
| | Processus | passages, échecs, dernière erreur, en cours |
| | Anomalies *(nouveau)* | échecs d'évaluation, traces du journal (supplanté, oubli…), échecs de processus gardés au journal |
| | Sorties *(nouveau)* | la file de sortie : en attente, échouées, orphelines, essais, dernière erreur |
| | Modèles en service *(nouveau)* | par fournisseur : créneaux occupés / total, repli ; par rôle : qui sert vraiment |
| | Le monde, côté écrans *(nouveau)* | les clients de `/ws/world` (client, moteur, qui, rôles), qui tient le bail d'hôte et qui l'attend ; par hôte, la révision chargée et ce qui lui manque (ancres, assets, révision dépassée), en avertissement tant qu'il est connecté. ADR 0051 |
| | Coûts et appels | par jour, rôle, fournisseur, **modèle** ; derniers appels paginés |
| | Stockage *(nouveau)* | taille des bases, dernier instantané ; la dernière sauvegarde (ce qui s'est écrit depuis), la dernière vérification, les archives gardées |
| Journaux | Chronologie | le journal, filtrable, paginé dans les deux sens |
| | Opérations | ce que les opérateurs ont fait |
| Anatomie | État et faits · Contributions · Toutes les vues | le mécanisme |
| Outils | Simulations | les rapports |

## Étape 3 — les formes

- **Cadres** (`Stats`) : un nombre, un état ; toujours en tête de page, jamais
  plus de six.
- **Tables** : une ligne entière mène à sa fiche ; le détail se déplie sous la
  ligne par un chevron ; le compte total s'affiche au-dessus ; 25 lignes par
  page par défaut.
- **Courbes** : une échelle par courbe, la table des valeurs repliée dessous.
- **Fiches** (`Fields`) : libellé à gauche, valeur à droite, deux colonnes au
  plus en largeur.
- **Formulaires** : un groupe = un cadre titré avec sa phrase d'explication ;
  l'aide de chaque champ sous lui ; les options rarement utiles repliées sous
  « Options avancées » ; une seule barre « Enregistrer » par page.
- **Actions d'en-tête** : une barre de boutons ; le formulaire s'ouvre en
  panneau sous l'en-tête, un seul à la fois.
- **Sous-menus** : les destinations riches (Configuration, Système) ont une
  colonne de navigation à gauche, rangée par rubrique ; les autres gardent des
  onglets.


## Contrôles de structure page par page — 30 septembre 2026

Le premier parcours couvre **128 pages et variantes**, exportées depuis une instance
fictive en clair et en sombre (`mika console apercu`). Chaque document est
contrôlé : un seul titre principal, identifiants uniques, aucun lien ni
formulaire imbriqué, en-têtes associés aux colonnes, pagination pour chaque table (détails
et valeurs des graphiques compris). Les fiches Forge sont vérifiées en plus
avec une app réelle de test, ses filtres, ses actions et ses réglages secrets.
Ces contrôles de structure ne prouvent pas que chaque parcours métier est
adapté : le premier passage laissait notamment un courrier trop technique,
sans navigation multi-compte visible et sans lecteur HTML. Les contrôles se trouvent dans `tests/fixtures/console_html.py`,
`tests/protocol/test_console_apercu.py` et `tests/unit/test_forge_console.py`.

| Pages examinées | Organisation et contrôles de structure |
|---|---|
| Tableau de bord | Attention → état présent → activité récente → courbes repliables. Suppression des compteurs d’approbations et de file redondants. Une limite de calcul des indicateurs journaliers est annoncée si elle est atteinte. |
| Humeur, postures, besoins, rythme, estime et récit | Chaque onglet affiche son propre titre et son explication ; valeurs détaillées des courbes accessibles par pages, sans suppression des points anciens. |
| Pensées, remarqué, attentes, nuits | Distinction entre état actuel et événements passés ; compte total affiché seulement lorsqu’il est connu. |
| Souvenirs, croyances, promesses, consolidation | Filtres conformes aux valeurs effectivement appliquées ; détails repliables ; titres et explications spécifiques. |
| Personnes, liens, présents | Annuaire, proximité et présence restent des lectures distinctes ; les liens de ligne et de cellule ne sont plus imbriqués. |
| Identités, revendications, politique | Consultation des preuves et règles ; les interventions restent sur les fiches concernées. |
| Conversations, questions sans réponse | Messages et demandes en attente séparés ; la dernière page du fil conserve le retour aux messages récents. |
| Décisions : maintenant, en cours, initiatives, choix, épisodes, échéances | Explication propre à chaque fonction ; retour disponible sur la dernière page de chaque historique. Les tableaux imbriqués ne décalent plus les paginations voisines. |
| Buts : projets, vivants, clos | Liste, état et historique restent séparés. Les fiches expliquent résumé, cadre, pas, carnet, effets, décisions, épisodes et atelier, et **pilotent** (ADR 0030) : modifier le cadre (pré-rempli), avancer maintenant, rouvrir, priorité, plan de travail en boutons, approuver ou refuser sur place, déposer, ouvrir et télécharger un fichier de l'atelier. |
| Approbations : en attente, historique | Décider depuis les cartes ; consulter les décisions et exécutions dans un historique paginé dans les deux sens. |
| Courrier : réception, brouillons, envoyés, contacts | Espace commun avec choix du compte, dossiers et boutons ; connexions et paramètres dans Configuration → Plugins → Boîtes aux lettres. L'ancienne page Comptes redirige vers ces réglages. |
| Fiches mail, brouillon et compte | Explications ajoutées aux onglets message, fil, informations retenues, brouillon, raisons, historique, état et voix. Les liens de configuration visent directement les pages actuelles. |
| Flux RSS, caméra, appareils | Liens explicites vers les réglages du plugin ; un état vide explique comment commencer. La caméra renvoie à ses paramètres, les capteurs à leur jeton d’accès. |
| Forge : catalogue | Recherche par nom ou titre ; état vide distinct d’une recherche sans résultat. |
| Forge : état, vues, réglages, code, journal, vécu | Les paramètres de vue sont de vrais filtres natifs. La configuration d’une app reste sur sa fiche : formulaire d’abord, valeurs effectives dans un détail. Journaux et exécutions ont chacun leur explication. |
| Configuration : fournisseurs, rôles, contexte | Listes paginées ; titre spécifique lors de l’ajout ou de la modification d’un fournisseur ; sélecteurs et aides communs. |
| Configuration : identité, parole, caractère, tempérament, document | Un sujet par page, aides sous les champs et erreurs rattachées aux contrôles. |
| Configuration : dépôts git, plugins, boîtes, flux, transcription, appareils | Point d’entrée « Plugins » et distinction explicite entre paramètres du moteur Forge et paramètres d’une app. |
| Configuration : comportement, chaque faculté et ses groupes | Navigation par rubrique conservée ; menu repliable sur petit écran. |
| Configuration : comptes, créer, modifier, journal | Titres d’action spécifiques ; liste et historique paginés ; protections du dernier opérateur et des secrets inchangées. |
| Système : santé, processus, anomalies, sorties, modèles, coûts, stockage | Informations d’exploitation distinctes des réglages ; nombres affichés avec leur portée réelle. |
| Système : chronologie, opérations, état, contributions, vues, simulations | Pagination commune, titres propres, détails et erreurs lisibles. |
| Fiches personne et identité | Objet en titre, explication de l’onglet consulté, retour à la rubrique et actions attachées à l’objet. |
| Épisode : déroulé, paroles, prompt, outils, appels, décision | Une explication spécifique est ajoutée à chaque onglet. |
| Recherche et formulaires d’action | Objectif explicite ; les liens vers une vue native retrouvent ses onglets et conservent les filtres. |

La vérification navigateur sur les 128 pages à 390 px ne constate aucun
débordement de la page : les grandes tables défilent dans leur propre cadre.
Les thèmes clair/sombre, le sous-menu mobile et les détails sont vérifiés
sur l’aperçu. Ce passage ne constitue pas une validation fonctionnelle de
tous les formulaires. Les parcours couverts par les tests utilisent des
données fictives ; aucun compte réel n’est utilisé.

### Reprise fonctionnelle du courrier

`test_mail_workspace.py` exerce les formulaires HTTP et la navigation avec
deux boîtes fictives : sélection conservée entre onglets, dossiers, recherche,
non-lus, pagination jusqu'au 530ᵉ message, lecture HTML et réponse envoyée par
le compte du message d'origine. Le rendu de ces données est également relu
dans le navigateur, sur ordinateur et à 390 px, sans session réelle.

- Réception : aperçu du message, expéditeur, date et état ; les diagnostics
  et les scores internes ne précèdent plus les messages.
- Message : corps lisible immédiatement ; répondre, répondre à tous,
  transférer et archiver ; actions secondaires et en-têtes repliables.
- Les mails HTML sont reconstruits avec une liste de balises autorisées,
  sans scripts, styles ni chargement d'images distantes. Leur version texte
  reste accessible. « Actualiser le dossier » complète le HTML des anciens
  messages déjà en cache, sans les marquer comme lus.
- Brouillons proposés par Mika et brouillons du serveur sont distingués.
  Envoyés réunit l'historique local et le dossier synchronisé du compte.
- Les nouveaux messages synchronisés gardent leur contenu complet. Un message
  long se lit en parties de 50 000 caractères au maximum, aux limites des
  lignes ou des mots. Les téléchargements texte et `.eml` contiennent le
  message entier. Les anciens extraits du cache sont signalés et peuvent
  être complétés explicitement depuis leur serveur.
- Les pièces jointes sont téléchargeables, y compris les messages `.eml`
  joints. Le transfert conserve le texte entier et, au choix, les pièces
  jointes. Il utilise le compte d'origine ; un échec de récupération empêche
  l'envoi incomplet. Les fichiers des nouveaux envois restent accessibles
  depuis Envoyés, même sans copie IMAP.
- Réception, envoyés, contacts et recherche parcourent tout le courrier
  conservé. Les copies IMAP et locales sont dédoublonnées, les conversations
  restent séparées par compte. Les filtres et compteurs sont appliqués en SQL
  avant de construire les objets de la page ; les listes ne chargent que des
  aperçus des corps.
- La synchronisation ne supprime plus les mails au-delà de 2 000 par dossier.
  « Charger des messages plus anciens » récupère 50 messages précédents sans
  les marquer comme lus ni les annoncer à Mika comme de nouvelles arrivées.
  L'historique affiché reste celui des messages effectivement synchronisés ;
  les pièces jointes reçues et sources originales nécessitent encore la
  présence du message sur son serveur.

### Reprise des autres pages et des parcours d'opérateur

Le second passage utilise des données fictives représentatives : deux personnes,
122 messages, 61 souvenirs, un projet, des pensées, 23 demandes d'approbation,
551 articles et des apps Forge exécutées dans leur bac à sable. Les tests HTTP
suivent les liens de pagination et les onglets des fiches, vérifient le résultat
des filtres et soumettent les formulaires de configuration et des apps.

| Pages | Correction et vérification |
|---|---|
| Conversations, questions et fiches personne/identité | Recherche par nom ou identifiant ; texte au premier plan et lecture complète avec paragraphes dans le détail ; contexte technique replié. Les messages d'une autre personne ne traversent pas le filtre. |
| Souvenirs, croyances, promesses | Contenu avant les identifiants et scores ; texte entier lisible ; recherche, personne et statut conservés entre les pages. La page 2 restitue les souvenirs anciens et une recherche vide ne restitue pas toute la mémoire. |
| Personnes, identités, liens | Nom, liens, proximité et activité utiles en premier ; preuves et données techniques dans les détails. Tous les onglets d'une personne restent consultables. |
| Humeur, postures, besoins, rythme, estime | Postures allégées ; indicateurs présents distincts de leur historique. Contrôle des valeurs et des références par les tests des vues. |
| Pensées, remarqué, attentes, nuits | Tables recentrées sur le contenu ; la dernière page conserve le retour aux événements récents, y compris lorsqu'elle est vide. |
| Buts : projets, vivants, clos et fiches | Projet, responsable, état et progression visibles ; limites et références détaillées. Tous les onglets d'un projet sont parcourus ; les liens Prompt, Outils, Appels et Décision ont des libellés explicites. |
| Décisions : maintenant et épisodes | Seuils explicatifs repliés ; filtres appliqués aussi aux statistiques. Une recherche rare peut continuer après une tranche sans résultat au lieu de masquer les épisodes plus anciens. |
| Approbations : en attente et historique | Résumé humain en titre, aperçu lisible, paramètres techniques secondaires ; demandes en attente paginées par 20, sans doublon ni perte de proposition. Un aperçu bloqué désactive l'approbation. |
| Flux RSS | Recherche dans les titres et résumés ; résumé dépliable ; consultation au-delà de 500 articles, y compris ceux d'un abonnement retiré. État des abonnements et activité séparés de la lecture. |
| Caméra et appareils | Accès distincts à la connexion d'un appareil et au rythme des observations ; les paramètres restent dans Configuration. |
| Forge : catalogue et fiches | Catalogue allégé ; commandes de maintenance limitées à État et Code. Vues garde les actions de l'app ; Réglages garde sa configuration. Création d'un relevé, validation des champs et enregistrement de paramètres testés par HTTP. |
| Configuration : fournisseurs, rôles, personnage, canaux, plugins, comportement, accès | Formulaires testés avec valeurs enregistrées, erreurs, champs conditionnels et secrets masqués ; les aides Courrier renvoient vers Réception, sans ancien onglet Comptes. |
| Système : sorties et coûts | Le filtre « échouées » vide ne montre plus les sorties réussies. Appels récents avant les ventilations de coûts ; détails de consommation repliés. |
| Navigation et rendu communs | Une redirection de fiche conserve ses filtres. Changer d'onglet retire les curseurs de l'ancienne table. Les colonnes secondaires se déplient avec leur valeur et leurs liens ; boutons de détail agrandis et reliés au contenu par `aria-controls`. |

Les contrôles sont dans `test_console_workflows.py`, `test_console_settings.py`,
`test_inspector_pages.py`, `test_forge_console.py`, les tests `test_inspect_*`,
`test_console_pagination.py` et `test_mail_feeds.py`. Les 162 pages et variantes exportées sont aussi
contrôlées dans le navigateur à 390 px ; les grandes tables défilent dans leur
cadre sans élargir toute la page. Les captures sont relues avec les scripts
communs actifs, en clair et en sombre. Ces vérifications n'utilisent pas de
compte externe réel.

## Composants communs et langage de la Forge

- `kernel/inspect.py` décrit les blocs natifs ; `kernel/envelope.py` valide
  et documente leur représentation JSON pour les apps (version 2 conservée).
- `inspector/render.py` prépare les cellules, liens, filtres, tableaux,
  graphiques et paginations. Les valeurs des graphiques utilisent maintenant
  exactement le même composant de table que les autres vues.
- `_cells.html`, `_forms.html` et `_navigation.html` fournissent les primitives
  réutilisables ; `_blocks.html` les compose en sections, grilles, détails,
  statistiques et formulaires. Chaque occurrence d’un formulaire reçoit son
  propre identifiant, même si la même action apparaît plusieurs fois.
- `Workspace` compose une navigation latérale et un contenu ; `Toolbar`
  regroupe des actions ; `ActionSlot.presentation="button"` ouvre le formulaire
  à la demande ; `Text.secondary` ajoute un aperçu et `Prose.reading` un
  document lisible. Ces primitives sont aussi disponibles dans le langage
  JSON de la Forge ; le HTML brut reste réservé au lecteur natif nettoyé.
- `Column.detail=True` range une information secondaire dans le détail de
  chaque ligne, sans perdre sa valeur, son lien ou la pagination. Dans une app
  Forge : `{"label": "Identifiant", "detail": true}`. Le contenu et les actions
  utiles restent visibles ; les références techniques restent consultables.
- `Head.action_tabs` limite les commandes globales d'une fiche aux onglets où
  elles servent. Une app conserve ses propres actions dans ses blocs de vue.
- Les filtres d’une app sont déclarés dans `manifest.yaml` (`params`) et
  rendus par l’hôte : recherche, entier, liste ou booléen. Le formulaire garde
  l’app et la vue sélectionnées et repart de la première page après filtrage.
- Sans pagination explicite, chaque table reçoit une page de 25 lignes et un
  compteur, même vide. Un historique à curseur annonce que son total est
  inconnu. La navigation reste disponible sur sa dernière page.
- Les téléchargements natifs sont déclarés par le propriétaire de la fiche
  (`Faculty.download`) et servis par une route commune authentifiée. Le nom du
  fichier est nettoyé et la réponse force le téléchargement sans mise en cache.
  Ce mécanisme n'ajoute pas de HTML arbitraire au langage des apps Forge.

### Vérifications des historiques et documents complets

- `test_mail_browse.py` vérifie 555 reçus, 555 envoyés et 555 brouillons dans
  SQLite : filtres, dernières pages, contacts, conversations de 1 110 messages,
  doublons et séparation des comptes. Une page de 25 mails ne matérialise que
  ces 25 aperçus. Les identifiants longs se résolvent sans charger l'archive.
- `test_mail_workspace.py` suit les 22 pages de recherche de 530 messages et
  les liens vers les anciens fils. Il soumet le formulaire de transfert,
  télécharge les fichiers, vérifie la protection de session et parcourt les
  pièces jointes au-delà de la première page.
- `test_mail_imap.py` utilise des serveurs locaux simulés : texte supérieur
  à 100 000 caractères, PDF binaire, message joint, transfert, citation,
  ancien cache et chargement de l'historique. Un changement d'UID ou un
  fichier absent est traité sans envoyer de message incomplet.
- Les articles RSS sont filtrés et paginés en SQL. Les épisodes ne s'arrêtent
  plus au 500ᵉ événement, leur issue reste visible en tête ; leurs appels de
  modèle ne s'arrêtent plus au 200ᵉ. Les versions de l'atelier se parcourent
  par pages au-delà des 500 derniers commits.
- Les brouillons avec une longue citation utilisent le même lecteur par
  parties. Un original provenant d'un cache incomplet bloque l'envoi d'une
  citation tant que le message original n'a pas été complété.

Ces vérifications portent sur des données fictives. Elles ne nécessitent ni
envoi vers une adresse réelle, ni modification des comptes de l'installation.

Validation finale : 897 tests exécutés avec succès (suite complète de 895 tests,
puis deux nouvelles régressions et les tests ciblés des derniers ajustements),
Ruff et `git diff --check` sans erreur. Le dernier passage navigateur couvre
157 pages et variantes à 390 px, sans débordement du document ; courrier,
transfert, épisodes et Forge sont également relus visuellement. Le serveur
du port 8001 a été rechargé ; santé et connexion répondent en HTTP 200.

Pour une vue Forge avec plusieurs grandes collections, utiliser un nom par
pagination (facultatif, `page` reste accepté) :

```json
{"type": "table", "title": "Articles", "columns": ["Titre"],
 "rows": [["Un article"]],
 "pagination": {"param": "page_articles", "page": 1, "total": 51, "per_page": 25}}
```

L’app lit `params.get("page_articles", 1)`, borne le numéro selon son total,
puis découpe ses données. Une deuxième table utilise par exemple
`page_alertes`. Ces paramètres sont des entiers bornés par l’hôte, conservés
dans les liens entre vues et réservés à la pagination. Sections, grilles,
statistiques, courbes, détails de ligne et formulaires continuent de se
combiner dans la même enveloppe, sans HTML ni JavaScript fournis par l’app.
