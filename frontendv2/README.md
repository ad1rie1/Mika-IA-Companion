# Mika — le client de tous les jours (frontendv2)

Le client web d'une personne qui a un compte (ADR 0187) : le chat avec Mika (et le mode pro pour une opératrice),
puis Projets, Outils, Mail, Teams, Téléphone, Agenda, Contacts, Carte et Paramètres. Il a la forme de la maquette validée (`maquette/`, à ne pas
modifier) et parle au moteur par le protocole du chat (`backendv2/docs/protocole-chat.md`) et par l'API par personne
(`backendv2/docs/protocole-moi.md`) : chaque écran ne montre que ce qui est à la personne connectée, ou qu'on lui
partage (ADR 0188).

## Le lancer

```bash
npm install
npm run dev        # http://localhost:4173 (port fixe, admis d'office par le moteur), vise http://localhost:8001
npm run build      # tsc (l'application, puis vite.config.ts et tools/) puis vite build : la vraie barrière
npm test           # vitest (src/ ; tools/ : extAssets, les règles des feuilles lues sur le disque, styles.test.ts,
                   # chaque paquet qu'importe src/ déclaré dans package.json, dependencies.test.ts, et aucune
                   # minuterie qui relise hors de sa liste, timers.test.ts)
npm run preview    # le résultat de build, sur le même port
```

- Un autre moteur : `VITE_BACKEND_ORIGIN` dans `.env.local` (voir `.env.example`). Le moteur doit admettre la page :
  sans `--origin`, il admet d'office les ports 3000 et 4173 de localhost et de 127.0.0.1 ; avec, il n'admet que les
  origines données (`python -m mika serve --origin <adresse>` remplace celles du développement).
- La page et le moteur doivent avoir le même nom d'hôte (`localhost` avec `localhost`, `127.0.0.1` avec
  `127.0.0.1`) : le cookie de session est `SameSite=Lax`.
- Adresse de capture : `?vrm=0` coupe la VRM (portrait seul), `?theme=dark|light` force le thème sans le retenir.
- Sur un téléphone (760 px de large ou moins), son coin est masqué et son portrait paraît seul : sa VRM ne se charge
  pas (ni three, ni le modèle). Elle se charge si la fenêtre s'élargit (`mika/view.ts::startVrmWhenShown`).

## Ce qui est lu ailleurs, jamais copié

`tools/extAssets.ts` sert en développement et en aperçu, sous des adresses stables :

| Adresse | Fichiers |
|---|---|
| `/ext/fonts/…` | `backendv2/src/mika/inspector/static/fonts/` (Inter, Inter Display) |
| `/ext/avatar/…` | `frontend/Android/app/src/main/assets/avatar/` (ses portraits et `manifest.json`, sous licence, non versionnés) |
| `/ext/models/…` | `frontend/Web/public/models/` (`default.vrm`, la sienne, non versionnée ; sinon `mika-libre.vrm`, le modèle libre du dépôt, ADR 0252) |

`vite build` ne les embarque pas : un déploiement sert ces trois chemins à côté de `dist/`, ou donne
`VITE_MIKA_VRM_URL` (la VRM) et `VITE_MIKA_AVATAR_URL` (le dossier des portraits). Sans police, la page prend celle
du système ; sans portraits, ses ronds restent à leur couleur ; sans aucune des deux VRM, son portrait reste.

La carte ne joint que ce serveur : ses tuiles, ses polices et ses icônes sont des chemins de l'API, posés sur son
adresse absolue (MapLibre lit ses tuiles dans un travailleur né d'une adresse `blob:`, où un chemin seul ne se résout
pas : un client construit sans `VITE_BACKEND_ORIGIN`, servi à la même adresse que le serveur, prend celle de la page).
Une photo d'une fiche ne vient que de lui aussi (`GET …/carte/photo/<ref>`, l'adresse refaite depuis sa référence :
`api/carte.ts::photoUrl`), comme une photo de profil Teams (ADR 0300 : `GET …/teams/photo`, l'adresse même que l'API
donne — `api/teams.ts::teamsPhotoUrl` ne charge rien d'autre). Les seules adresses du dehors du code sont des liens
qu'on ouvre soi-même dans un autre onglet, sans référent (`screens/carte/sources.ts::outLink` : http ou https
seulement) — « Ouvrir dans OpenStreetMap », les sources d'une fiche (Google Maps, l'auteur d'un avis ou d'une photo,
OpenStreetMap, l'office de tourisme, la Licence Ouverte) — et les espaces de noms XML (SVG, GPX) ; aucune requête ne
les joint.

Les modules purs du client web sont réutilisés sans copie par l'alias `@web` (→ `frontend/Web/src`) :
`network/api.ts` et `WebSocketClient.ts`, `types/`, et `ui/chatSync`, `approvals`, `toolActivity`, `proMarkdown`,
`strands`, `verdicts`, `bubbles`, `inlineMarkup`, `messageNotes`, `emojis` (`insertEmoji`), `LoginOverlay`
(`bootstrapClosed`). Un changement de leur comportement se fait là-bas, pour les deux clients.

## Structure (`src/`)

| Dossier | Rôle |
|---|---|
| `main.ts` | le démarrage : `whoami()` → la connexion ou l'application ; `/ws` fermé en 4401 → `whoami`, puis la connexion si la session ne vaut plus ; le direct branché sur chaque client de la connexion |
| `live/` | le direct (ADR 0308, voir « Le direct » plus bas) : `live.ts` — la trame `changed` lue (`parseChanged`, pur), le service (`live` : `bind`, `onChange`, `onAny` — plusieurs sujets, un appel par trame —, `onResync`, `onVisible`), un écran face à lui (`Freshness`), une lecture à la fois (`OneAtATime`) |
| `login/` | la carte de connexion, et celle du premier compte (`needs_bootstrap`, code de premier démarrage) |
| `shell/` | le cadre porté de `maquette.js` : barre du haut, routes `#écran/onglet/objet`, barre de titre et onglets, palette Ctrl K, menus, fenêtres, toasts, thème, icônes |
| `mika/` | Mika : ce qu'on sait d'elle (`state.ts`, plié des trames ; `store.ts`, qui le garde et le diffuse), sa ligne d'état, ses facettes et son visage (`view.ts`, `labels.ts` ; `view.ts` écrit aussi les lignes de la carte « Ce qu'elle fait » — une facette et une promesse, que sa colonne du chat reprend telles quelles, un projet et son statut en mots — et décide quand sa VRM se charge), son visage en rond (`face.ts`), où elle en est d'une réponse qu'elle prépare (`work.ts` : la ligne et son chrono, ADR 0306), ses portraits (`portraits.ts`), son élément unique (`corner.ts`) et sa VRM (`vrm.ts`, chargée à part) |
| `screens/chat/` | le chat : `chat.ts` (les trames, l'état du fil, l'orchestration des gestes), `approvals.ts` (les cartes d'accord et « Tout accepter »), `strands.ts` (les fils de travail et leurs commandes), `composer.ts` (le champ : pièces jointes, emojis, compteur, phrase préremplie, envoi), `older.ts` (« Messages plus anciens » : d'où repartir, comment ce qui revient se recoud au fil chargé, pur), `markup.ts` (le balisage de la maquette, pur) |
| `screens/projets/` | Projets (ADR 0291, d'après la maquette validée : `maquette/ecrans/projets2.js` et ses suites) : `index.ts`, `projets.ts` (l'état, les lectures gardées, les gestes : un envoi, puis tout se relit ; ce qui est saisi, où chaque cadre a défilé et le curseur tiennent d'un dessin à l'autre ; un refus se dit à l'endroit du geste), `routes.ts` (les adresses de la maquette, la clé d'une attente : pur), `state.ts` (les filtres, ce qui est choisi, les groupes d'« À faire » et des objectifs : pur), `gestures.ts` (un geste traduit en requête — trancher en nommant le plan lu, un accord avec le condensé lu, ajouter ou modifier un objectif, un jalon, un ticket, les seuls réglages changés, un lien : pur), `diagram.ts` (les calculs du diagramme des objectifs : ses lignes, la part faite, l'axe qui se resserre, les fantômes sans date, les flèches : pur), `time.ts`, `tones.ts` (la couleur d'un état, depuis les codes du serveur), `md.ts` (un petit Markdown, échappé d'abord), `parts.ts` (les morceaux partagés : les trois zones — `trio` —, les sections du panneau, pastilles, barres en segments, lignes liées, champs et formulaires, le panneau qui s'ouvre, un texte venu d'ailleurs — `outside`), `views/` (une vue par fichier : `todo.ts` « À faire », `sheet.ts` la barre de titre, la grille, la tête d'une fiche et la Vue d'ensemble, `objectives.ts`, `diagram.ts`, `tickets.ts`, `activity.ts`, `more.ts` Dépendances, Listes et « Modifier le projet »), `tabs.ts` (où se branchent les onglets écrits à part : `registerTab`) ; l'onglet **Code** : `code.ts` (ses lectures gardées, la forme du diff, la branche choisie, fusionner, modifier une pull request, y répondre), `codeparts.ts` (ses adresses, la coloration simple d'une ligne en jetons de texte, un diff mis en lignes — unifié ou côte à côte —, la demande de fusion : pur), `paint.ts` (le contenu d'un fichier et les lignes d'un diff posés après le dessin par insertion de texte, jamais en HTML), `screens/projets/views/code.ts` (Fichiers, Commits, Branches) et `screens/projets/views/codehost.ts` (Pull requests, Issues, CI : ce qui se joue avec l'hôte) ; l'onglet **Documentation** : `documentation.ts` (ses lectures gardées, les brouillons, l'éditeur gardé d'un dessin à l'autre, ses gestes), `docparts.ts` (ses adresses, l'arborescence, le chemin d'une page, le brouillon et son conflit : pur), `docmd.ts` (le rendu d'une page en lecture : échappé, rien d'ailleurs n'y est chargé ; pur), `editor.ts` (l'éditeur : Milkdown, par Crepe — chargé à la demande, son propre morceau), `screens/projets/views/docs.ts` (Pages, Images, Décisions), `dialogs.ts` (la confirmation d'une fusion, le mot sur ce qui a changé) |
| `screens/mail/` | Mail : `index.ts` (l'écran et sa pastille), `mail.ts` (l'état, les gestes), `markup.ts` (le rendu de la maquette, pur), `compose.ts` (les destinataires proposés, la fenêtre d'un mail), `live.ts` (ce que le direct fait relire : la page affichée, le mail ouvert, ce qui se repeint en place ou redessine la liseuse — pur), `format.ts` (niveaux de partage, adresses, texte d'un mail, « [À COMPLÉTER », pur) |
| `screens/teams/` | Teams : `index.ts`, `teams.ts` (l'état, les gestes), `markup.ts`, `format.ts` (états, modes, jours, mentions, qui a écrit — « Toi » sur un compte à toi seulement —, les réactions et qui les a posées, les cartes du fil, l'adresse d'une réponse) |
| `screens/telephone/` | Téléphone : `index.ts`, `view.ts` (le rendu, pur ; la scène de la position, `positionScene` : son point et sa précision, que la vraie carte — `map/view.ts` et `map/live.ts`, comme la Carte — et le plan montrent) |
| `screens/agenda/` | Agenda (ADR 0309, lot 6 ; d'après la maquette validée : `maquette/ecrans/agenda.js` et ses suites) : `index.ts` (l'écran : la route — la vue, l'événement, la proposition ou la date de sa mémoire ouverte, les invitations, les fenêtres —, les lectures gardées — ses agendas, la période affichée, l'événement ouvert, ses invitations, ce que Mika propose — et le direct `agenda`, les gestes : créer, modifier et sa portée, dupliquer, supprimer, répondre, décider de ce que Mika propose, « Mika te le rappelle », la recherche), `view.ts` (le dessin, pur : la barre de titre, la colonne de gauche, Jour et Semaine en grille horaire, Mois, Planning, la recherche, le bandeau de ce que Mika propose, la fiche d'un événement, d'une proposition, d'une date de sa mémoire, le volet des invitations), `model.ts` (pur : les occurrences d'une période, leur sorte, leur couleur — celle du fournisseur rapprochée de la palette —, les chevauchements en colonnes, les journées en bandes, les mots d'un moment, d'une répétition — et la règle RFC 5545 d'un choix du formulaire —, d'un rappel, les adresses `#agenda/…`), `dates.ts` (pur : des jours sans heure d'été, un instant à l'heure du fuseau du serveur, les bornes et les mots de chaque vue), `form.ts` (la fenêtre d'un événement — ce qu'une modification envoie : ce qui a changé, `fieldsOf` —, la portée d'une série, répondre avec un mot), `share.ts` (partager un agenda), `display.ts` (ce que ce navigateur retient : les agendas décochés, la vue), `chat.ts` (la carte d'accord d'un ajout dans le chat : l'événement qu'elle ajouterait) |
| `screens/contacts/` | Contacts (ADR 0298, d'après la maquette validée `maquette/ecrans/contacts.js`) : `index.ts` (l'état : la liste lue par pages — la recherche, la sorte —, la fiche ouverte, gardée par contact ; les gestes : choisir, « Afficher les suivants », « Oublier ce contact » et la croix d'un fait après confirmation, « Lui présenter quelqu'un »), `view.ts` (la liste, la fiche, ses adresses vers Mail, Teams et Téléphone : pur) |
| `screens/carte/` | Carte (ADR 0194 à 0196, 0259) : `index.ts` (le cadre : les onglets, les lectures communes, la carte gardée d'un dessin à l'autre et son cadrage, ce qui garde la main d'un dessin à l'autre, la visionneuse des photos, la palette ; il délègue le dessin et les gestes à l'onglet montré, et chaque contrôleur reçoit de lui ce qu'il lui faut, jamais l'état d'un autre onglet), `explorer.ts` (Explorer : la recherche, ses filtres et son ordre, les adresses, le regard de Mika, la fiche d'un lieu et « Actualiser », « Itinéraire jusqu'ici », « Ajouter au voyage » — son menu, que les Événements partagent), `events.ts` (Événements : quand, quoi, où, la liste, ce que Mika a trouvé, la fiche d'un événement et ses gestes), `fiche.ts` (la fiche d'un lieu — Google Maps, OpenStreetMap, l'office de tourisme, les événements tout près —, celle d'un événement, la bande des photos, la visionneuse : pur), `agenda.ts` (l'onglet Événements : les jours d'une recherche, les groupes par jour, le jour d'un voyage où tombe un événement, la phrase pour Mika : pur), `sources.ts` (ce que disent les sources et comment on les cite : liens sûrs, numéros, notes en étoiles, photos servies par ce serveur, dates de lecture, ligne de couverture : pur), `photos.ts` (les photos chargées quand elles paraissent, la visionneuse), `itinerary.ts` (Itinéraire : les points et leurs propositions, le calcul, le regard de Mika, tes choix, le GPX, « En faire un voyage »), `trip.ts` (Voyages : la liste et le voyage ouvert, ses gestes — l'un après l'autre, montrés avant que le serveur les dise —, « Sur la route », la note d'un arrêt, optimiser, un lieu ajouté à un voyage), `modals.ts` (les fenêtres « Nouveau voyage », « Le voyage », « Ajouter un arrêt »), `drag.ts` (glisser un arrêt : la cible, l'indice, le suivi du pointeur), `view.ts` (Explorer et sa liste notée, Itinéraire, Voyages et l'éditeur d'un voyage — la note d'un arrêt en place, les épingles de « Sur la route » —, les fenêtres d'un voyage, les actions d'un voyage dans la barre de titre, le cadre de la carte : pur), `format.ts` (l'ordre des arrêts et où un geste les met, une note changée, ce dont le trajet d'un voyage dépend, ce que la fenêtre d'un voyage envoie, le jour d'un lieu croisé le long du trajet, tes choix d'itinéraire face à ceux d'un trajet de Mika, jusqu'où une recherche est allée, la fiche d'un lieu dans la route, les cuisines d'une liste, le GPX d'un itinéraire, les phrases préparées pour Mika, le contrôle qui garde la main d'un dessin à l'autre : pur), `requests.ts` (ménager ce qui sort du serveur : les adresses gardées par texte, le trajet d'un voyage gardé pour ses arrêts et relu après le dernier geste, les gestes l'un après l'autre, ce qui n'est plus là (404) : sans DOM) |
| `map/` | Ce qui sert à toute carte (Téléphone, Carte, les miniatures du chat) : `info.ts` (le fond de carte servi, `GET /api/moi/carte/fond`, lu une fois pour la page et relu, quand un écran se relit, s'il a plus de cinq minutes), `mapgeo.ts` (ce qu'elle couvre, une précision en cercle, le zoom, une zone, une distance), `polyline.ts` (`decodePolyline6`, la même que `backendv2/src/mika/ports/maps.py`), `mapstyle.ts` (le style Protomaps, clair ou sombre, sans les points d'intérêt qui n'apprennent rien : une attraction sans nom, ou nommée « Immeuble », « Maison »…), `base.ts` (une carte MapLibre : adresses absolues, la session, les commandes en français, le nord toujours en haut, le thème, `restyle`, des tuiles en échec de suite qui font revenir le plan, une image vide pour une icône que la planche n'a pas), `view.ts` (`MapView` : épingles numérotées, roses pour ce que Mika a fait, secondaires — plus petites, sans numéro : les lieux de « Sur la route » —, tracés, la position et le cercle de sa précision, `fitBounds` ; une position seule s'ouvre centrée, au zoom de sa précision ; un cadrage demandé se fait même sur une scène inchangée, et une scène vide garde la vue, sauf quand l'écran demande le fond de carte), `live.ts` (le cycle de vie d'une carte vivante, le même pour la Carte et la Position du Téléphone : si elle se montre, la monter, la reposer d'un dessin à l'autre, une autre carte servie qui se repose sur elle, seul le dernier montage qui se pose, ses échecs — tuiles, chargement, WebGL — qui laissent le plan sans réessayer, et les mots de sa note), `scene.ts` et `drawn.ts` (ce qu'une carte montre, comment une vue la cadre — `sceneFraming` : sur l'écran Carte, une zone d'au moins ~200 m et jusqu'au zoom 17, sur une miniature, ~2 km et 12,5 au plus —, et son plan dessiné sans tuile ; la position peut porter sa précision, un cercle que la zone tient), `notes.ts` et `cards.ts` (ses notes de carte et leur miniature), `minis.ts` (les miniatures d'une liste : créées quand elles paraissent, quatre vivantes au plus ; ce qu'elles montrent, lu une fois pour la page et relu quand il a changé), `words.ts` (distances, durées, ce qu'un trajet en voiture peut éviter — la seule table de ces libellés —, dates d'un voyage, en long et en court), `load.ts` (MapLibre et la vue, chargés une fois et à part) |
| `screens/outils/` | Outils : `index.ts`, `matrix.ts` (la matrice des droits et les lignes de « Services », pur), `agendas.ts` (« Tes agendas » : le tableau de droits de chaque agenda à toi, réglé ici, ADR 0309) |
| `screens/parametres/` | Paramètres : `index.ts` (routes, routes d'action, gestes délégués, sous-onglets), `page.ts` (ce qu'une page et son hôte se doivent), `form.ts` (lignes et barre d'enregistrement), `words.ts` (les mots des niveaux et des états), une page par sous-onglet (`account`, `mail`, `teams`, `agendas` — ses comptes d'agenda, la fiche d'un compte, « Brancher un agenda » par sorte, ADR 0309 —, `phones`, `shares`, `mcp`) |
| `api/` | `moi.ts` (`getJson`, `sendJson`, `sendForm`, `apiUrl`), `me.ts` (`GET /api/moi`), et un client typé par domaine : `mail`, `teams`, `phone`, `contacts` (ses contacts, la fiche d'un contact, l'oublier : `protocole-moi.md` § 12), `rights`, `settings`, `shares`, `mcp`, `projects` (ses projets, « À faire », la fiche, le registre, ses gestes, ses réglages, son activité, le diagramme de ses objectifs : `protocole-moi.md` § 11), `projectCode` (le code d'un projet : fichiers, commits et leur diff, branches, pull requests, issues, CI) et `projectDocs` (sa documentation — pages, versions, images, enregistrer en nommant la version lue — et ses décisions), `carte` (lieux et leurs filtres, fiches, « Actualiser », événements, photos, adresses, itinéraires, regards, voyages, et le fond de carte : `protocole-moi.md` § 10), `agenda` (ses agendas, une période, un événement, chercher, ses invitations et ce que Mika propose, écrire, répondre, décider, ses comptes, le tableau de droits d'un agenda : `protocole-moi.md` § 13) |
| `shell/dom.ts` | les aides du DOM ; une photo de profil qui ne vient pas laisse ses initiales (`keepInitialsOnBrokenPhotos`, posé au démarrage) |
| `shared/` | ce que plusieurs écrans partagent : `kit.ts` (lectures en cache — une relecture forcée, ou demandée après une invalidation, suit celle en cours, un 404 efface ce qu'on avait lu —, erreurs, dates, copier, confirmer), `store.ts` (les lectures partagées, dont ta dernière position, celle du Téléphone et de la Carte), `storage.ts` (le stockage du navigateur, sans jamais lever), `names.ts` (« de Léa », « d'Adrien » : `ofName`, que `screens/mail/format.ts` réexporte) |
| `shell/ages.ts` | les âges affichés (« il y a 3 min ») repeints d'ici toutes les 30 s, l'onglet au premier plan, par chaque écran abonné (Teams, Paramètres, Téléphone), sans rien relire |
| `shell/counts.ts` | les pastilles de la barre du haut, relues dans `GET /api/moi` (au démarrage, quand le direct dit `me`, à chaque ouverture de la connexion, après un geste ; l'onglet caché, à son retour) ; la même lecture donne le nom du compte, que le menu du compte suit quand on l'a changé ailleurs (un autre appareil, la console) |
| `styles/` | `base.css` et `chat.css` portés de la maquette, `ecrans/` pour chaque écran, `app.css` pour ce qu'elle ne montrait pas |

Mika n'a qu'un élément (`#mika-corner`) : son visage dans la pastille du haut, ou en grand dans la colonne du chat
(`[data-mika-scene]`). Le cadre la gare avant de redessiner un écran et la reloge après (`corner.park()` /
`corner.lodge()`), comme la maquette.

## Le direct

Rien ne se relit à intervalles (ADR 0308). Le serveur pousse sur `/ws` une trame `changed` qui dit quoi a changé,
jamais le contenu — les sujets, leurs clés et ce que chaque écran relit : `backendv2/docs/protocole-moi.md`, § 2 bis,
la seule source. `live/live.ts` la reçoit et réveille les écrans abonnés à un sujet, avec les clés nommées (ou tout le
domaine) ; chacun relit la route qu'il montre, une lecture à la fois, et ce qui n'a pas changé ne se redessine pas ;
un écran qui relit tout pour plusieurs sujets (Paramètres) ne le fait qu'une fois par trame (`onAny`). Ce qui ne doit
pas sauter sous les doigts tient : une sélection cochée dans Mail retarde la relecture de la liste, la réponse
commencée, une saisie et le défilement restent. Une boîte, un compte Teams ou un projet qui n'est plus à toi (retiré,
plus partagé) ramène à la liste — « Toutes les réceptions » dans Mail — au lieu de dire « Introuvable ». Un écran au
second plan, ou l'onglet caché, ne relit rien : il se relit à son retour ; à chaque ouverture de la connexion, la
première comprise (l'écran lu au démarrage l'a été pendant la poignée de main), ce qui est affiché se relit une fois
(rien n'est rattrapé). Les copies partagées (`shared/store.ts::followChanges`) suivent leurs sujets. Les âges affichés
(« relevée il y a », le dernier signe de l'extension Teams, « vu il y a ») avancent d'eux-mêmes, repeints d'ici toutes
les 30 s sans rien relire (`shell/ages.ts`), sauf sous une saisie ; Projets ne s'y abonne pas (son dessin relance ses
lectures périmées). Les minuteries qui relisent encore — une pause de la saisie, une lecture unique au démarrage pour
la palette, le trajet d'un voyage après tes gestes, les notes préchargées autour de toi, la connexion Microsoft d'une
boîte (ce qu'elles attendent ne passe pas par le journal) — sont listées avec leur raison dans `tools/timers.test.ts`,
qui échoue sur toute autre (une pause attendue dans une boucle ou un `new Promise` y compte comme une relecture).

## Ce que fait chaque écran aujourd'hui

- **Chat** : le fil (historique, rattrapage par curseur, accusés, « Mika écrit… », ses bulles l'une après l'autre,
  repères de jour), le champ (pièces jointes, emojis, Entrée pour envoyer), ses cartes d'accord au-dessus du champ,
  ses fichiers (`/files/<id>`), la bulle de sa position, la recherche dans les messages chargés et la liste des
  fichiers échangés (« Enregistrer » sur les siens comme sur tes pièces, tant qu'elles sont gardées, ADR 0215). En
  haut du fil, « Messages plus anciens » remonte la conversation page après page (`strand_history` avec `id` vide) :
  en mémoire, ce qui est chargé n'a pas de borne, la recherche et Ctrl K en profitent ; seul le cache du navigateur se
  limite aux derniers messages. À droite, Mika en grand, son humeur (les facettes de `emotion_blend`), ce à quoi elle repense et
  ce qu'elle a promis. Pour une opératrice : « Pro » (fils de travail, ses outils en direct, Markdown), 👍/👎 et
  « pourquoi ? », « Tout accepter » (pour l'onglet).
  Une carte d'accord d'un ajout à l'agenda (`agenda.write`, ADR 0309) montre l'événement qu'elle ajouterait (son
  agenda, quand, où, « Mika te le rappelle », lus dans `GET …/agenda/proposals`), « Modifier » (dans l'Agenda) et la
  proposition qui y attend ; ses boutons sont ceux de toute carte.
  Une carte d'accord pour un brouillon de mail ou une réponse Teams devient un lien vers Mail ou Teams, où elle se
  relit et se décide (ADR 0191) ; « Tout accepter » ne la décide pas. Le lien ouvre le brouillon même
  (`#mail/messages/brouillon/<id>`, `#teams/brouillons/<id>`), sur une ligne compacte. Sur un téléphone, deux liens ou
  plus se replient sous une ligne qui les déplie (« 2 brouillons à relire · Mail · Teams »), et la bande des cartes
  défile au-delà de 28 % de la hauteur : le fil reste lisible. Le bouton des accords y garde un mot (« Un par un »,
  « Tout accepter »). Sur l'écran Chat, les toasts passent au-dessus du champ et de ses cartes, jamais dessus
  (`--toast-bottom`, posée par le chat).
  Ses notes de carte (ADR 0196 : `look`, `map`, `trip`, `protocole-chat.md` § 4) se lisent ici, à côté de
  `@web/ui/messageNotes` qui garde la bulle 📍 seule (l'ancien client web les ignore), et se gardent avec le message ;
  chacune devient une carte miniature sous ses bulles, qui s'ouvre dans l'écran Carte. Une sorte inconnue s'ignore ; une
  note vidée (un regard oublié, un voyage supprimé) ne montre rien. Une miniature montre d'abord son plan dessiné ; quand
  elle paraît, ce qu'elle montre se lit (`GET /api/moi/carte/regards/<ref>`, `/api/moi/voyages/<ref>`) et une vraie
  carte, non interactive, prend sa place — quatre à la fois au plus, rendues quand elles sortent de la vue. Aucune ne
  demande d'itinéraire : un voyage s'y dessine en reliant ses arrêts, un regard avec le tracé qu'elle a gardé. Ce
  qu'elles montrent se lit une fois pour la page, chat et écran Carte ensemble : un voyage changé dans l'un se relit
  dans l'autre quand sa miniature reparaît.
- **Projets** (ADR 0291, 0294, `protocole-moi.md` § 11) : l'écran de la maquette validée, en **trois zones sur toute la
  largeur** — la liste, le contenu découpé en volets, un panneau latéral (l'état, les propriétés, ce qui est lié avec
  son statut, les gestes). Sur un écran moyen le panneau se replie sous l'en-tête du détail ; sur un téléphone il
  devient le volet « Infos », et la liste puis le détail sont deux pages. Ses adresses sont celles de la maquette :
  `#projets/a-faire[/<projet>/<attente>]`, `#projets/projets`, `#projets/projets/<id>[/<onglet>/…]`.
  **À faire** : ce qui t'attend dans tous tes projets, groupé par projet, dans l'ordre du serveur ; au centre ce qu'il
  faut lire pour décider (ce qui partirait pour un accord, le plan d'un projet et ses questions, le plan d'un ticket,
  la question posée, un point d'arrêt et sa preuve, un élément à ta charge, le ticket d'une pull request à fusionner), à droite la décision : accorder ou refuser
  (avec le condensé lu ; un accord dit ce qu'il concerne, où il part et pourquoi), valider un plan ou demander une révision, accepter ou écarter un ticket, valider ou refuser
  son plan (la requête nomme le plan lu), répondre, valider ou refuser un point d'arrêt, changer un statut. Ce qui ne
  se fait pas ici dit pourquoi, avec les mots du serveur (`why`) ; une pull request à fusionner s'ouvre dans l'onglet
  Code. **Projets** : la grille des cartes (l'état, où il en est, ses objectifs en une barre, ses compteurs, ses
  liens, par qui il est mené — servis avec la liste, `card` : la grille ne lit aucune fiche), les projets archivés (« Désarchiver ») et « Nouveau projet »
  (ses champs sont ceux que le serveur décrit).
  **La fiche** : sa tête (piloter — une consigne, lancer maintenant, la pause, la reprise —, « Modifier le projet » en
  sections, archiver) et ses onglets. **Vue d'ensemble** : une grille de cartes (où il en est, ses objectifs, son
  code et son dernier commit, ses tickets par étape du parcours, ses dépendances, ce qui t'attend, son prochain passage — quand,
  sur quoi, son rythme, ses consignes en attente). **Objectifs** : la liste serrée — une
  ligne par objectif —, le détail (ses jalons en étapes et leurs preuves, sa branche et sa pull request, ses comptes
  rendus, lus dans le fil d'activité), une mission (son rythme, ses passages), « Ajouter un objectif » (ponctuel ou
  mission ; ce qui peut la déclencher et les façons de vérifier un jalon sont ceux que la fiche sert, `forms`), Modifier, Rouvrir, Terminer, Retirer, « Ajouter un jalon », le modifier, le retirer, valider un point
  d'arrêt ; et **le diagramme**, en deux modes — Avancement, Dans le temps (l'axe se resserre, ou passe en semaines,
  pour que la première date et aujourd'hui tiennent à l'écran ; ce qui n'a pas commencé est un fantôme, sans date).
  **Tickets** : la liste, ses filtres et sa recherche, « Nouveau ticket », le détail en volets (Description, Plan,
  Fil, Historique), le panneau (son parcours en six étapes, servi — `journey` : l'étape fine en précision, les étapes
  sautées quand il ne produit pas de code —, ses propriétés, ce qui est lié : son objectif, sa pull request avec son
  statut, son issue avec son état), l'Historique (l'histoire de ses étapes, et ce qui est arrivé à ses objectifs), Modifier, et les gestes du moment (ceux que `can` ouvre). **Activité** : le Fil (par
  jour, ses filtres par sorte et par objectif, le graphique des trente derniers jours, les totaux de toute son histoire), les Exécutions (le détail pas
  à pas), le Carnet. **Dépendances** : le schéma (le projet au centre, ce dont il dépend, ce qui dépend de lui), le
  panneau d'un lien (depuis quand, pourquoi, ce qu'il donne — en lecture —, le commit que montre la vue, les demandes
  dans les deux sens, « Lui demander quelque chose » : un ticket ouvert chez le projet lu, au nom de la personne),
  « Ajouter une dépendance » (le mot du lien s'y saisit), le volet des demandes. **Listes**, seulement pour un projet
  qui en a une : en colonnes par statut ou en tableau ; un statut et à qui est un élément se changent sur la carte,
  « Ajouter » y pose un élément. **Modifier le projet** : un champ que le serveur réserve (`can`, `why`) se montre
  verrouillé avec sa raison, et ne part jamais.
  **Code**, en six sous-onglets (`#projets/projets/<id>/code/<sous-onglet>/…`) : **Fichiers** (le choix de la branche,
  l'arborescence un dossier à la fois — les entrées cachées se disent, sans se lister —, le fichier en chasse fixe avec
  ses numéros de ligne et une coloration simple, son dernier commit et son historique ; un fichier binaire ou trop gros
  se dit ; un fichier Markdown — le README d'abord — se lit rendu, par le rendu des pages de documentation, sans
  charger aucune image, avec une bascule Rendu | Source), **Commits** (la ligne de temps par jour, le filtre par
  branche, le commit et son diff unifié ou côte à côte, ses fichiers changés en sommaire ; un fichier coupé se relit
  seul), **Pull requests** (la liste ; Résumé avec les jalons et leurs preuves, Commits, Fichiers, Échanges ; le
  panneau : sa fusion, sa relecture, ses vérifications une à une, ses conflits, sa branche, le ticket et l'objectif
  liés ; **Modifier** et **répondre** avec `rights.pull_write` ; **Fusionner** : une confirmation dit ce qui va être
  fusionné, la demande nomme le commit de tête qu'elle vient de relire, puis le panneau dit la suite — demandée,
  fusionnée, refusée avec les mots du serveur ; le même geste part d'« À faire »), **Branches** (le tableau pleine
  largeur, le panneau d'une branche), **Issues** (Description, Échanges, l'état chez l'hôte, le ticket lié et son
  étape — un ticket proposé s'y accepte ou s'y écarte quand son registre le dit (`can`) —, sa pull request, l'accord qui
  attend sur une réponse) et **CI** (les vérifications par commit, une à une, la fin du journal d'un échec). Tout texte de l'hôte est
  présenté comme venu d'ailleurs, échappé ; la source d'un fichier et les lignes d'un diff sont posées par insertion
  de texte (`paint.ts`), jamais en HTML ; un fichier Markdown rendu passe par `docmd.ts`, échappé d'abord.
  **Documentation**, en trois sous-onglets (`…/documentation/pages|modifier|historique/<chemin>`, `…/images/<nom>`,
  `…/decisions/<n>`) : **Pages** (l'arborescence, la recherche, Nouvelle page ; en lecture la page rendue, son
  sommaire, sa dernière modification — une personne dans le navigateur, Mika, un outil par MCP —, ses versions ; son
  historique, revenir à une version ; renommer, déplacer, supprimer), **Images** (la grille, téléverser, copier le
  lien, retirer) et **Décisions** (la liste, le choix, le contexte, les options écartées, la raison, ce qu'elle
  remplace ; créer, modifier, remplacer, retirer, remettre en vigueur). **Le mode Modifier est un éditeur : Milkdown,
  par son éditeur Crepe** (`@milkdown/crepe`, licence MIT — la bibliothèque de la maquette validée ; `editor.ts`), chargé à
  la demande : son morceau (≈ 1,2 Mo, 371 ko compressé) ne pèse pas sur le reste du client. Sa barre d'outils et son
  menu à la barre oblique sont en français ; ses couleurs sont celles du client, en clair et en sombre (les variables
  `--crepe-…` de `styles/ecrans/projets.css` ; le thème des blocs de code vient de `@codemirror/theme-one-dark`, que
  Crepe apporte déjà et que `package.json` déclare parce que `src/` l'importe). **Enregistrer** demande un mot sur ce
  qui a changé et envoie le Markdown avec la version lue (en `multipart/form-data`) ; si la page a changé depuis, le
  refus du serveur se dit et **ce qui est écrit reste** : on relit, puis on reprend sur la version actuelle. Une page
  modifiée et pas enregistrée le montre (sa tête, l'arbre, l'onglet), quitter la vue le dit, et le brouillon attend.
  Une image — par le bouton, glissée, collée — part au serveur, puis s'insère dans la page. **Rien de ce qu'une page
  contient ne s'exécute ni ne se charge d'ailleurs** : en lecture, un rendu échappé (`docmd.ts`) ; dans l'éditeur, ce
  que la bibliothèque laisse passer a été vérifié (un lien n'a d'adresse que http(s), mailto, tel ou relative ; du
  HTML écrit dans le Markdown s'affiche comme du texte) ; dans les deux, seules les images de l'espace de
  documentation, servies par l'API, sont chargées — toute autre adresse d'image se dit, sans être chargée.
  L'écran ne recalcule aucune règle : pas de bouton sans `can` ou `rights`, les libellés d'étape et de statut sont
  ceux du serveur (seule la couleur d'un état se choisit ici), rien de ce qui est saisi n'est vérifié ici, et un
  geste refusé se dit sur place avec les mots du serveur (un 409 relit ce qu'on lisait). Un texte venu d'ailleurs
  (`outside` : une issue d'un inconnu, un commentaire de l'hôte, la fin d'un journal de CI, la sortie d'une commande)
  est cité dans sa présentation à lui, échappé, sans lien ni balisage ; un lien venu d'ailleurs ne s'ouvre que s'il
  est http ou https. Ce que l'API ne sert pas ne s'invente pas ici. Sa pastille : `counts.projects` de `GET /api/moi`.
- **Mail** : ses boîtes et celles qu'on lui partage (à leur niveau : lire, préparer, s'en servir ; une boîte partagée
  dit son non-lu à côté de son niveau, et celle qu'on ne fait que lire reste hors de Toutes les réceptions et de la
  pastille, ADR 0200), dossiers et non-lus, « Réponse attendue » (ce qu'elle juge appeler une réponse), la liste
  (recherche, filtres, dont « Où Mika est passée » ; sur chaque ligne, ce que son tri en a fait : « lu par son tri »,
  « en attente de son tri », « tri deviné », champ `triage`, ADR 0240), la liseuse (ce qu'elle en sait, HTML isolé dans
  son cadre, images distantes, pièces ; elle se ferme quand la vue ne montre plus ce qu'elle lit), lu à l'ouverture
  selon `read_on_open`, répondre, transférer, ranger (archiver, suivre, déplacer dans un dossier, corbeille, un mail ou
  la sélection ; Suppr met à la corbeille la sélection, sinon le mail ouvert ; un geste se voit aussitôt, sans
  attendre le serveur qui range mail par mail : un mail rangé quitte la liste, et une lecture qui ne le sait pas encore
  ne le remontre pas, `keptRows` ; ce que le serveur refuse revient ; ADR 0302), écrire avec les destinataires proposés, une copie cachée et des fichiers joints (nouveau message, réponse,
  transfert ; 25 Mo par pièce, ADR 0214), « Préremplir avec Mika » (elle s'y met tout de suite ; où elle en est se
  suit sur une ligne de « Ce qu'elle en sait », relue par `GET …/mail/work` à chaque étape que le direct pousse, ADR
  0306 et 0308 :
  `mika/work.ts`), « Corriger » dans la réponse en place et la fenêtre d'un mail (les fautes, sans changer les mots :
  le texte corrigé remplace le tien, « Annuler » dans le toast ; éteint tant qu'aucun modèle ne corrige, ADR 0307 :
  `screens/mail/compose.ts::correctField`), ses brouillons (exactement ce qui
  partira : envoyer, retoucher, refuser, reprendre). Ses correspondants sont dans Contacts (ADR 0298) : l'ancien
  onglet `#mail/contacts` y mène ; écrire propose toujours ses correspondants (`GET …/mail/contacts`), et
  `#mail/messages/ecrire/<adresse>[/<nom>]` ouvre un mail nouveau, le destinataire posé (« Écrire » d'une fiche de
  Contacts). Ses correspondants gardent leurs initiales : l'API du courrier ne dit pas encore leur photo de Teams (ADR
  0300). Sa pastille ne compte que ses brouillons qui
  attendent ta décision.
- **Teams** : ses discussions (un tête-à-tête au nom de l'autre personne, comme dans Teams), le fil (tes messages à
  droite, les mentions ; sur un compte qu'on te partage, ceux de son propriétaire à gauche, à son nom), ses réponses en
  carte et « Ses brouillons » (une carte par réponse sur un téléphone ; `#teams/brouillons/<id>` y surligne une
  réponse), ton message par l'extension du compte, sous le nom de qui y est connecté dans Teams (ADR 0189),
  « Préremplir avec Mika » (elle s'y met tout de suite ; où elle en est se suit sur une ligne au-dessus du champ,
  l'étape et son chrono, relue par `GET …/teams/work` à chaque étape que le direct pousse, sans redessiner le champ,
  ADR 0306 et 0308),
  « Corriger » à côté (les fautes de ton message, sans changer ses mots, ADR 0307 : le même que dans Mail).
  Ta réponse dans une discussion rend sans objet celle qu'elle y avait préparée : refusée
  (« Répondu autrement »), sa carte le dit (ADR 0199). « Comment ça part » relit tes droits par `api/rights.ts`, la
  lecture que Paramètres et Outils partagent. Chaque personne a la photo de son profil Teams à la place de ses
  initiales, quand l'extension l'a téléchargée (ADR 0300) : dans le fil, la liste (un tête-à-tête, l'autre personne,
  même quand le dernier message est le tien), la tête du fil, les participants ; un groupe garde son carré (son image
  n'est pas captée). Sous un message, ses réactions : chacune son emoji (sa clé de Teams quand le serveur ne le
  connaît pas) et son compte, la tienne en couleur (sur un compte à toi seulement), qui a réagi au survol (« Claire
  Dubois, Sophie Laurent, toi et 2 autres »). La citation (ADR 0305), comme dans Teams : « Citer » au survol d'un
  message (au doigt, en le touchant), dans un tête-à-tête ou un groupe où tu peux écrire (ni canal ni réunion : le
  serveur n'y cite pas) ; sa carte au-dessus du champ (un × l'enlève), et ton
  message part avec `reply_to` ; une réponse citée montre sa carte au-dessus de son texte, qui mène au message cité
  quand il est chargé (`quoteCard`, `TeamsScreen.quote`, `goToMessage`).
- **Téléphone** : ses téléphones, les conversations que l'application a lues, leurs fils, ses propositions et leur
  sort, sa dernière position — sur une vraie carte quand le serveur en sert une qui la couvre (ADR 0193 : ses tuiles,
  polices et icônes viennent du serveur seul, `GET /api/moi/carte/fond` ; MapLibre se charge avec l'onglet), sinon sur
  le plan dessiné de la Carte : le point et le cercle de sa précision, à l'échelle (~300 m autour au moins), aucune rue
  inventée. Répondre d'ici et « Préremplir » (ADR 0189, 0191) n'ont pas encore de route dans l'API
  (et l'application Android devra envoyer sans redemander le geste) : le champ le dit (sur un téléphone, sa note seule).
  « Lui en parler dans le chat », dans le menu d'un fil, ouvre le chat avec une phrase qui nomme la conversation. Pas
  d'onglet Notifications tant que l'application ne lit que les messageries (ADR 0233) : il ne ferait que redire
  Messages ; `#telephone/notifications` retombe sur Messages, et Paramètres › Téléphones dit ce que l'application lit.
  Mika ne lit les messages du téléphone que pour ses propriétaires : à un autre compte (`owner` de `GET /api/moi`),
  Messages le dit et mène à Position. Une autre carte servie, relue quand l'onglet se relit (au plus toutes les cinq
  minutes : aucun sujet du direct ne la dit ; des
  polices ajoutées, une autre source, une autre zone), se repose sur la carte ouverte. Une carte qui ne se dessine pas
  (pas de WebGL, MapLibre qui ne vient pas, ses tuiles en échec de suite) laisse le plan dessiné et sa note, sans
  réessayer à chaque dessin — jusqu'à une autre carte servie.
- **Agenda** (ADR 0309, lot 6 ; `protocole-moi.md` § 13) : tous ses agendas en un écran, la forme de la maquette
  validée — celui du système (« Mon agenda »), ceux qu'elle branche (Google, Outlook, CalDAV, un abonnement), ceux qu'on
  lui partage et « L'agenda de Mika », sa mémoire montrée comme un agenda (ce qu'elle t'a promis, ce qu'elle retient de
  ta vie), en rose et en lecture seule. À gauche : « Créer », le mini-mois, les agendas par groupe — les cocher ne change
  que l'affichage, retenu par ce navigateur (les masquer, dans Paramètres, coupe aussi Mika) —, leur menu (n'afficher
  que lui, sa couleur, le partager, ses paramètres), un compte en panne, « Brancher un agenda ». Jour et Semaine en
  grille horaire (les chevauchements en colonnes, les journées en bandes, maintenant en ligne, un créneau vide touché
  crée un événement à son heure), Mois, Planning (quatre semaines), la recherche (titres, lieux, descriptions,
  personnes, des 90 derniers jours à l'année qui vient, dans les agendas cochés : aucun coché, elle le dit sans rien
  demander au serveur). Une invitation sans réponse est en pointillés, « peut-être »
  hachuré, un refus disparaît ; ce que Mika propose d'ajouter est hachuré de rose, dans la grille et en tête de la vue
  (Refuser · Modifier · Ajouter, tel qu'il a été lu). La fiche d'un événement, dans un volet : quand et où il en est,
  répondre à une invitation (et la réponse que Mika a préparée : l'envoyer, en changer le mot, « Non merci » ; une
  série : « Ta réponse vaut pour toute la série » ; d'ici sans pouvoir répondre — un partage, le privé d'une autre, un
  serveur CalDAV qui ne transmet pas les réponses —, pas de boutons, la ligne `respond_why`), Modifier
  (pas une invitation), Dupliquer ou « Copier dans mes agendas », Supprimer (ou Retirer une invitation : la refuser),
  « Demander à Mika », la répétition en mots, le lieu, un lien de visio (http ou https seulement, dans un autre onglet),
  les participants et leur réponse, les rappels du fournisseur et « Mika te le rappelle » (« Changer », son
  propriétaire), « Ajouté par Mika ». La fenêtre d'un événement : quand (journée entière, le fuseau), la répétition et
  « Personnalisée », le lieu, un lien de visio collé, la description, l'agenda où il s'écrit, les participants (ses
  correspondants, ou une adresse), les rappels du fournisseur — une notification ou un e-mail, autant que le
  fournisseur en garde (cinq chez Google et en CalDAV, un chez Outlook ; aucun pour le système, où Mika rappelle) —,
  « Mika te le rappelle », occupé ou disponible, privé ; une modification n'envoie que ce qui a changé (une description
  que la zone de texte a seulement relue — ses fins de ligne — ne repart pas), une série
  demande sa portée (cet événement, celui-ci et les suivants, tous), et la fenêtre revient telle quelle si le serveur
  refuse. Partager un agenda (le sien : lire, lire et préparer, s'en servir, avec une personne qui a un compte ; ça ne
  change rien chez Google ou Microsoft). Sur un téléphone : Planning d'abord, le mois se déplie sous le titre, les
  agendas dans un menu, « + » pour créer, la fiche en page. Adresses : `#agenda/<vue>`, `#agenda/evenement/<n°>[/<occurrence>]`,
  `#agenda/proposition/<n°>`, `#agenda/memoire/<réf>`, `#agenda/invitations`, `#agenda/nouveau`,
  `#agenda/modifier/…`, `#agenda/partager/<agenda>`. Le direct `agenda` relit ses agendas, la période affichée,
  l'événement ouvert, ses invitations et ce que Mika propose ; l'agenda de Mika se relit à l'ouverture de l'écran.
  Ce que l'API ne sert pas ne se montre pas : « Ce que Mika en sait » d'un événement, créer une visio chez le
  fournisseur, « Trouver un créneau avec eux », la visibilité « Publique », « Déjà répondu » des invitations, « Voir sur
  la carte » d'un lieu. Sa pastille : `counts.agenda` de `GET /api/moi` (ses invitations, et ce que Mika propose dont
  elle décide).
- **Contacts** (ADR 0298 ; `#contacts`, `#contacts/<n°>`) : tous ceux que Mika connaît pour toi — vus dans tes
  comptes Teams et tes boîtes (les tiens et ceux qu'on te partage), sur ton téléphone, ou dont tu lui as parlé — et
  leurs organisations, entre Téléphone et Carte dans les deux barres. À gauche : la recherche (un nom, un e-mail, un
  numéro), Tous / Personnes / Organisations avec leurs nombres, chaque contact avec sa photo de Teams quand un compte
  Teams où tu lis la garde (ADR 0300 ; sinon ses initiales, une organisation son carré — de même sur sa fiche et parmi
  les personnes d'une organisation), son organisation (sinon son poste)
  et d'où il vient (Teams, chaque boîte, WhatsApp, SMS, raconté) ; la liste se lit par pages de cent (« Afficher les
  suivants »). À droite, sa fiche : son nom, son poste, son organisation, « parle aussi à Mika » (relié à une personne
  qui lui a écrit ; « a un compte » si elle n'a jamais écrit) ; Écrire (Mail, le
  destinataire posé, si une de tes boîtes envoie), Teams (sa conversation), Message (son fil du téléphone) ; d'où il
  vient et le dernier échange ; « Ce qui l'identifie » (chaque identifiant, d'où elle le tient ; un contact du
  téléphone par le nom que lui donne ton carnet, jamais sa clé) et, pour une organisation, « Ses personnes parmi tes
  contacts » ; « Ce que Mika en sait » — son poste, son service et son organisation, d'après son profil Teams ou son
  adresse, puis ce qu'elle a compris de ses derniers messages (lot 6 de l'ADR 0298), chaque fait d'où il vient et sa
  confiance, avec une croix pour ceux d'un de tes comptes : confirmée, elle le lui fait oublier (`fact/forget`), et il
  ne se réapprend pas — ; « Où vous
  vous croisez » (ses conversations Teams, son dernier mail dans chaque boîte, ses fils du téléphone, chacun vers son
  écran) ; d'où vient ce qu'elle en sait ; « Oublier ce contact », après confirmation — quand tout ce que tu en vois
  vient de tes comptes (sinon le serveur dit ce que la fiche montre déjà : une part vient d'un compte qu'on te partage
  ou d'un compte à elle, une opératrice l'oublie depuis la console) ; s'il est aussi vu ailleurs, seule ta part
  s'efface, avec la même réponse. Rien ne dit de qui d'autre c'est le contact : le serveur ne le sert pas. « Lui présenter quelqu'un » ouvre le chat avec une phrase à
  compléter : la fiche naît de ce que tu lui racontes. Sur un téléphone, la liste puis la fiche, avec son retour.
- **Carte** (ADR 0194 à 0196, 0259) : sur la carte du serveur (la même que Téléphone), ou sur le plan dessiné de ce
  qu'elle montre quand elle ne se dessine pas. Quatre onglets : Explorer, Événements, Itinéraire, Voyages. Trois sources
  disent ce qu'est un lieu, chacune nommée là où elle parle : OpenStreetMap (l'index de ce serveur), l'office de
  tourisme (DATAtourisme, une base de ce serveur) et Google Maps (le cache des notes et des avis de ce serveur) ; la
  forme des fiches et des événements : la maquette de l'app Android (`frontend/Android/maquette/ecrans/carte-avis.js`, corrigée : Google
  Maps à la place de Tripadvisor), posée dans la colonne de gauche. **Explorer** cherche dans l'index des lieux du
  serveur (rien ne sort) : un nom, une catégorie, « Autour de moi » (`near=ici` : la dernière position de son
  téléphone, que le serveur connaît, et qui précharge les notes de ta case — la liste se relit une fois quelques
  secondes plus tard ; une position oubliée, son 409 se dit et la zone de la carte prend le relais) ou « Dans cette
  zone » (le cadre de la carte, recherché de nouveau quand on la déplace), et une adresse (Géoplateforme, relayée : seul
  le texte part). Sous la recherche, ses filtres : ouvert maintenant, ce que le serveur sait reconnaître (terrasse,
  végétarien, vegan, accessible, à emporter, livraison), « 4 et plus » (la note Google), la cuisine parmi celles de la
  liste ; l'ordre (les plus proches, les mieux notés) en tête de la liste. Chaque ligne dit la note Google et le nombre
  d'avis, le prix, la cuisine, ouvert ou fermé (« Fermé · ouvre demain 12:00 »), avec une vignette quand le lieu a une
  photo dont on sait l'auteur — cité juste sous la ligne, lié (« Photo : Camille R. · Google Maps » ; sa licence pour une
  photo de l'office de tourisme) ; sans auteur (un regard de Mika, qui n'en garde pas), pas de vignette (R2, ADR 0269).
  Au-dessus, la ligne des notes, dès qu'un lieu a une note, quelle que soit la couverture (« Notes : Google Maps »,
  « Notes Google Maps lues aujourd'hui à 22:00 », et ce que le serveur en dit) ; un regard de Mika noté l'a aussi, et ses
  lieux gardent leur note, leur prix et leur cuisine. « Actualiser » dans une fiche refait aussi sa ligne de la liste.
  Choisir un lieu (dans la liste ou sur la carte) ouvre sa **fiche** à la place de la liste (`#carte/explorer/lieu-<id>`,
  son objet d'OpenStreetMap d'abord) : la bande des photos (le plan d'abord, qui recadre la carte, puis les photos de
  l'office de tourisme et de Google, chacune avec sa source, son auteur lié et sa licence ; le compte des photos sur
  la tuile du plan ; sans photo, le plan seul), ouvert ou fermé, la cuisine, le prix, la note (« · Google Maps » tant
  que le bloc Google n'est pas là) ; « Itinéraire », « Ajouter au voyage », « Appeler » et « Site » quand on les a,
  « En parler à Mika » ; le bloc **Google Maps** (la note, le nombre d'avis, le prix et sa fourchette, le résumé, ce que
  Google ajoute à la fiche, les avis — chacun avec son auteur lié et sa date en mots, un long avis replié —, « Voir sur
  Google Maps », la date du cache et « Actualiser », qui dit en mots ce qui n'a pas pu se relire ; un lieu que Google
  ne connaît pas le dit, avec la raison du serveur) ; les infos pratiques d'OpenStreetMap (sous « © les contributeurs
  d'OpenStreetMap », la date de l'extrait, « Corriger sur OpenStreetMap ») ; ce qu'en dit l'office de tourisme (sa
  description, ses labels, ses tarifs, ses contacts, son auteur et sa date, la Licence Ouverte) ; les événements tout
  près. Une photo ne se charge que quand elle paraît (la première relève d'une photo de Google coûte un appel compté),
  et s'ouvre dans la **visionneuse** (sa légende, son auteur lié, sa licence pour l'office de tourisme, d'où elle vient ;
  les flèches du clavier). **Événements** (entre Explorer et Itinéraire) : quand (aujourd'hui, ce week-end, cette
  semaine jusqu'au dimanche, des dates — des jours de Paris, l'heure des dates des événements, quel que soit le fuseau
  du navigateur), quoi (les thèmes du serveur, « Gratuit »), un texte, autour de moi ou dans la zone de la carte ; la
  liste groupée par jour (son quand, son lieu, son prix, sa distance, une vignette avec son auteur et sa licence), leurs épingles sur la carte, la couverture de la zone (« lue en partie : cases lues 11 sur 21 ») ; la fiche
  d'un événement (`#carte/evenements/e:<uuid>`) : quand, où (son lieu nommé ouvre sa fiche), combien, le programme, ses
  dates, ses contacts, ses photos, son auteur et sa date sous la Licence Ouverte ; « Itinéraire », « Ajouter au voyage »
  (au jour du voyage où il tombe), « En parler à Mika ». Ce que Mika a trouvé en événements s'y montre en rose
  (`#carte/evenements/regard-<n>` ; sa miniature du chat y mène, et un regard d'événements ouvert dans Explorer — une
  miniature touchée avant d'être lue — y part en remplaçant l'adresse : « Retour » ramène au chat) ; une fiche n'est
  « trouvée par Mika » que si l'événement est dans ce regard. Une fiche ouverte par un lien d'une fiche de l'autre
  onglet (« Bientôt, tout près », le lieu d'un événement) a un retour qui y ramène (« Retour au lieu », « Retour à
  l'événement »). Autour de toi,
  l'index élargit ses cercles jusqu'à trouver : au-delà de 20 km, la légende ne dit plus « autour de ta position » mais
  « les plus proches que l'index connaisse · jusqu'à … km » (le classement mêle pertinence et distance). La carte se
  cadre sur ce que dit la colonne : des lieux à quelques mètres les uns des autres se départagent (jusqu'au zoom 17), une
  recherche relancée se recadre même quand elle rend les mêmes lieux, et ce que Mika avait cherché, s'il ne se lit pas
  (oublié ou en panne), ramène la carte sur le fond de carte (tant qu'il se lit, elle attend). La fiche d'un
  lieu mène à « Itinéraire jusqu'ici », « Ajouter au voyage » (ses voyages, les dates en court : « 3–7 avr. ») et « En
  parler à Mika » ; sur un téléphone, où la carte et la liste défilent ensemble, elle reste collée en bas de l'écran, et
  un lieu choisi sur la carte la ramène en vue. **Itinéraire** : ses points
  (un lieu, une adresse, « Ma position »), voiture, vélo ou à pied, péages, autoroutes ou ferries évités, la durée, la
  distance et l'heure d'arrivée, les consignes, un GPX fait dans le navigateur, « En faire un voyage », « Envoyer à
  Mika ». **Voyages** : la liste en cartes (leurs miniatures), « Nouveau voyage » (en voiture, ce qu'il évite), et
  l'éditeur jour par jour — les tronçons, ses arrêts en rose (retirables, comme les tiens), glisser une poignée (ou ses
  flèches au clavier) pour réordonner d'un jour à l'autre, « Noter » (le crayon : la note d'un arrêt se corrige ou
  s'efface en place, Entrée l'enregistre, Échap annule ; elle se lit à part, « ajouté par Mika » n'est qu'une marque),
  « Ajouter un arrêt », « Sur la route » (les lieux le long du trajet, « jour N » en tête de leur ligne, ajoutés au bon
  jour ; sur la carte, en épingles secondaires — plus petites, sans numéro — qui ne la recadrent pas, et qu'on touche
  pour retrouver leur ligne), « Le voyage » (le crayon du titre : ses cases « En voiture, éviter » ne se montrent qu'en
  voiture, et un voyage qui la quitte ne les envoie plus), et dans la barre de titre, une fois le voyage lu (ni pendant
  sa lecture, ni introuvable), « Optimiser l'ordre », le GPX du serveur, « Demander à Mika », qui ouvre le chat avec une
  phrase préremplie (le mode pro, s'il était choisi, cède la place). Ce qu'elle a cherché ou montré s'ouvre ici
  (`#carte/explorer/regard-<n>`, `#carte/itineraire/regard-<n>`), ses lieux en rose ; oublié (404), l'écran le dit, et
  une autre panne se réessaie. Son trajet s'y montre tel qu'elle l'a gardé (son mode, ce qu'il évitait), et ne se recalcule qu'au premier changement (ou
  « Recalculer ») ; son mode et ses cases ne deviennent pas les tiens : tes choix ne viennent que de tes gestes, et un
  trajet que tu commences (« Itinéraire jusqu'ici ») les reprend, quand modifier le sien garde les siens. Sans index,
  sans adresses ou sans itinéraires, l'endroit qui en a besoin dit le message du serveur (503) et le reste marche.
  Ce qui sort du serveur est borné par compte (`protocole-moi.md` § 10 ; un 429 se dit à l'endroit qui l'a reçu) :
  une adresse ne se demande que si le texte en a l'air (un chiffre, ou cinq caractères), après 0,7 s sans frappe, une
  fois par texte (la carte qu'on bouge ne la redemande pas) ; le trajet d'un voyage se garde pour ses arrêts (un autre
  ordre, un autre mode : il se relit 1,5 s après le dernier geste, et le trajet d'avant ne se montre pas en attendant),
  et « Sur la route » ne se recherche que si le trajet a changé. Les gestes sur un voyage se font l'un après l'autre ; un
  arrêt lâché à sa place n'envoie rien ; chaque ajout a sa clé d'envoi (un double clic, un réessai ne l'ajoutent qu'une
  fois). Le voyage se relit après le dernier geste fini (une lecture partie avant lui est suivie d'une autre) ; une
  relecture en panne après des gestes tous aboutis garde ce qu'ils ont posé (le serveur l'a écrit) et le dit, après
  un refus le dernier voyage lu fait foi. Un point d'itinéraire retapé rend le trajet montré passé : ni consignes, ni GPX, ni « En faire un voyage »
  avant de le choisir. La carte ne tourne pas (pas de boussole pour revenir au nord) ; la main reste sur le contrôle
  qu'on touchait d'un dessin à l'autre, et un arrêt déplacé au clavier se dit à un lecteur d'écran.
- **Outils** : la matrice de ses droits, ressource par ressource — chaque outil, nommé pour elle (son libellé, ADR
  0208), par chaque canal et à chaque moment, la décision même de la porte d'offre, et pourquoi (la part de la ligne
  qui la concerne ; la ligne même et sa page dans la console, pour une opératrice : ADR 0209). Les chiffres du menu
  comptent des outils, chacun une fois. Ses comptes disent la règle d'envoi qui vaut pour eux, leurs outils sont ceux
  de leur famille. Sur un téléphone, on choisit le canal dont la colonne se lit. « Services » : ceux de Mika qui lui
  sont ouverts (celui du système, « Le web », sous un titre et un but écrits pour elle ; ceux de l'opératrice, sans
  leur but : la ligne de son catalogue, écrite pour Mika), les siens et ceux qu'on lui partage (leur état et leur but,
  même sans case ouverte). Le pourquoi d'une case d'app redit la ligne de son app ou de son projet (ADR 0219). Ses accords se décident dans le chat : le chapeau le dit, et l'onglet « Accords » attend une route qui rende ses cartes.
  « Tes agendas » (ADR 0309), sous les ressources : le tableau de chaque agenda à toi (`#outils/droits/ag:<agenda>`),
  qui se règle ici, case par case — Lire ; Ajouter, modifier, supprimer ; Répondre aux invitations ; Ce qu'elle en garde
  —, la ligne d'un partage se retire avec lui, « Revenir au tableau de départ » ; qui, par où et quand, et l'ordre des
  lignes, restent à la console. Un agenda qu'on te partage n'y est pas : son tableau est à son propriétaire.
- **Paramètres** : son compte (nom, mot de passe ; « Lui demander » ouvre le chat, « Qu'est-ce que tu sais de moi ? »
  posé dans le champ), ses boîtes (ajouter, régler — dont ses consignes de tri : où ranger, de quoi te prévenir,
  ADR 0243 ; « Tout garder en local », ADR 0249 —, tester, connecter à Microsoft, retirer), ses comptes Teams (les
  régler, la clé de leur extension, montrée une fois, l'extension même à télécharger — ADR 0246 —, les retirer), et pour chacun comment part ce que Mika y prépare
  (ADR 0207 : préparer d'elle-même et comment ça part, ligne par ligne et par défaut ; qui écrit et l'ordre des lignes
  restent à la console), ses téléphones (révoquer, télécharger l'application), ses partages, ses services MCP
  (brancher un service distant, régler chacun de ses outils — coupé, il lit, il agit —, le retirer ; ses en-têtes
  secrets gardés ne suivent pas une adresse qui mène à un autre serveur : la fiche les redemande sous leur champ avant
  l'envoi, ou « Retirer ses en-têtes », ADR 0236 ; ceux qu'on lui partage, en lecture, sous « Partagé avec toi »), ses agendas (ADR 0309 : ses comptes — leur état, leurs
  agendas, leur panne en mots —, ce qu'on lui partage et l'agenda de Mika, « Dans l'Agenda » pour ce navigateur ; la
  fiche d'un compte — son nom, sa connexion, se reconnecter, déconnecter, synchroniser, le retirer ; ses agendas : leur
  nom (celui du système change pour de bon, un agenda branché en prend un à lui ici seulement), leur couleur, « Dans
  l'Agenda » (le masquer coupe aussi Mika), « Mika te le rappelle », leurs droits ; leurs partages — ; « Brancher un
  agenda » : un agenda de ce serveur, Google — l'adresse de retour collée, ou le retour direct —, Outlook.com /
  Microsoft 365 — un code, la fin de son attente poussée par le direct —, CalDAV essayé puis choisi, un abonnement
  iCal). Une route d'action ouvre la fenêtre qu'un bouton promet, depuis un
  autre écran ou la palette : `#parametres/mcp/+brancher`, `#parametres/compte/+mot-de-passe`,
  `#parametres/partages/+partager` (l'adresse redevient celle de l'onglet).
- **Partout** : la pastille de Mika (ce qu'elle fait, son humeur) ouvre « Ce qu'elle fait » ; Ctrl K cherche un écran,
  un onglet, un fil de travail, ou un mot dans tout le texte des messages chargés (le passage trouvé en titre, dix
  résultats par groupe au plus) : choisir un message ouvre son fil et l'y montre, surligné un instant ; le menu du
  compte change le thème et déconnecte. Sur un téléphone, les boutons de la barre de titre, réduits à leur icône,
  gardent leur nom (`title` et `aria-label`, posés par le cadre d'après leur libellé) ; ceux de la tête d'une section
  de Paramètres ou d'une fenêtre gardent leur libellé. La barre du haut a dix rubriques (l'Agenda après Téléphone) ;
  la barre du bas en garde huit (Projets après le chat, l'Agenda après Téléphone), Carte, Outils et Réglages passant
  sous « Plus » (ADR 0309) ; Paramètres s'y dit « Réglages ». Sur un écran large, les libellés des rubriques se
  replient sous 1440 px, et « Rechercher partout » se réduit à sa loupe sous 1880 px (`styles/ecrans/agenda.css`).
