# Mika — le client de tous les jours (frontendv2)

Le client web d'une personne qui a un compte (ADR 0187) : le chat avec Mika (et le mode pro pour une opératrice),
puis Outils, Mail, Teams, Téléphone, Carte et Paramètres. Il a la forme de la maquette validée (`maquette/`, à ne pas
modifier) et parle au moteur par le protocole du chat (`backendv2/docs/protocole-chat.md`) et par l'API par personne
(`backendv2/docs/protocole-moi.md`) : chaque écran ne montre que ce qui est à la personne connectée, ou qu'on lui
partage (ADR 0188).

## Le lancer

```bash
npm install
npm run dev        # http://localhost:4173 (port fixe, admis d'office par le moteur), vise http://localhost:8001
npm run build      # tsc (l'application, puis vite.config.ts et tools/) puis vite build : la vraie barrière
npm test           # vitest
npm run preview    # le résultat de build, sur le même port
```

- Un autre moteur : `VITE_BACKEND_ORIGIN` dans `.env.local` (voir `.env.example`). Le moteur doit admettre la page :
  sans `--origin`, il admet d'office les ports 3000 et 4173 de localhost et de 127.0.0.1 ; avec, il n'admet que les
  origines données (`python -m mika serve --origin <adresse>` remplace celles du développement).
- La page et le moteur doivent avoir le même nom d'hôte (`localhost` avec `localhost`, `127.0.0.1` avec
  `127.0.0.1`) : le cookie de session est `SameSite=Lax`.
- Adresse de capture : `?vrm=0` coupe la VRM (portrait seul), `?theme=dark|light` force le thème sans le retenir.

## Ce qui est lu ailleurs, jamais copié

`tools/extAssets.ts` sert en développement et en aperçu, sous des adresses stables :

| Adresse | Fichiers |
|---|---|
| `/ext/fonts/…` | `backendv2/src/mika/inspector/static/fonts/` (Inter, Inter Display) |
| `/ext/avatar/…` | `frontend/Android/app/src/main/assets/avatar/` (ses portraits et `manifest.json`, sous licence, non versionnés) |
| `/ext/models/…` | `frontend/Web/public/models/` (`default.vrm`, ~100 Mo, sous licence, non versionnée) |

`vite build` ne les embarque pas : un déploiement sert ces trois chemins à côté de `dist/`, ou donne
`VITE_MIKA_VRM_URL` (la VRM) et `VITE_MIKA_AVATAR_URL` (le dossier des portraits). Sans police, la page prend celle
du système ; sans portraits, ses ronds restent à leur couleur ; sans VRM, son portrait reste.

La carte ne joint que ce serveur : ses tuiles, ses polices et ses icônes sont des chemins de l'API, posés sur son
adresse absolue (MapLibre lit ses tuiles dans un travailleur né d'une adresse `blob:`, où un chemin seul ne se résout
pas : un client construit sans `VITE_BACKEND_ORIGIN`, servi à la même adresse que le serveur, prend celle de la page).
Les seules adresses du dehors du code sont le lien « Ouvrir dans OpenStreetMap » et les espaces de noms XML (SVG,
GPX), qu'aucune requête ne joint.

Les modules purs du client web sont réutilisés sans copie par l'alias `@web` (→ `frontend/Web/src`) :
`network/api.ts` et `WebSocketClient.ts`, `types/`, et `ui/chatSync`, `approvals`, `toolActivity`, `proMarkdown`,
`strands`, `verdicts`, `bubbles`, `inlineMarkup`, `messageNotes`, `emojis` (`insertEmoji`), `LoginOverlay`
(`bootstrapClosed`). Un changement de leur comportement se fait là-bas, pour les deux clients.

## Structure (`src/`)

| Dossier | Rôle |
|---|---|
| `main.ts` | le démarrage : `whoami()` → la connexion ou l'application ; `/ws` fermé en 4401 → `whoami`, puis la connexion si la session ne vaut plus |
| `login/` | la carte de connexion, et celle du premier compte (`needs_bootstrap`, code de premier démarrage) |
| `shell/` | le cadre porté de `maquette.js` : barre du haut, routes `#écran/onglet/objet`, barre de titre et onglets, palette Ctrl K, menus, fenêtres, toasts, thème, icônes |
| `mika/` | Mika : ce qu'on sait d'elle (`state.ts`, plié des trames ; `store.ts`, qui le garde et le diffuse), sa ligne d'état, ses facettes et son visage (`view.ts`, `labels.ts`), son visage en rond (`face.ts`), ses portraits (`portraits.ts`), son élément unique (`corner.ts`) et sa VRM (`vrm.ts`, chargée à part) |
| `screens/chat/` | le chat : `chat.ts` (les trames, l'état, les gestes), `markup.ts` (le balisage de la maquette, pur) |
| `screens/mail/` | Mail : `index.ts` (l'écran et sa pastille), `mail.ts` (l'état, les gestes), `markup.ts` (le rendu de la maquette, pur), `compose.ts` (les destinataires proposés, la fenêtre d'un mail), `format.ts` (niveaux de partage, adresses, texte d'un mail, « [À COMPLÉTER », pur) |
| `screens/teams/` | Teams : `index.ts`, `teams.ts` (l'état, les gestes), `markup.ts`, `format.ts` (états, modes, jours, mentions) |
| `screens/telephone/` | Téléphone : `index.ts`, `view.ts` (le rendu, pur ; si la vraie carte se montre, et ce que l'onglet en fait : `liveWanted`, `mapStep`), `livemap.ts` (la carte de sa position sur `map/base.ts` : le point et le cercle de sa précision) |
| `screens/carte/` | Carte (ADR 0194 à 0196) : `index.ts` (les onglets, les lectures, les gestes, la carte gardée d'un dessin à l'autre), `view.ts` (Explorer, Itinéraire, Voyages et l'éditeur d'un voyage, le cadre de la carte : pur), `format.ts` (l'ordre des arrêts et où un geste les met, ce dont le trajet d'un voyage dépend, le jour d'un lieu croisé le long du trajet, le GPX d'un itinéraire, les phrases préparées pour Mika, le contrôle qui garde la main d'un dessin à l'autre : pur), `requests.ts` (ménager ce qui sort du serveur : les adresses gardées par texte, le trajet d'un voyage gardé pour ses arrêts et relu après le dernier geste, les gestes l'un après l'autre : sans DOM) |
| `map/` | Ce qui sert à toute carte (Téléphone, Carte, les miniatures du chat) : `info.ts` (la carte servie, `GET /api/moi/phone/map`, lue une fois pour la page et relue toutes les cinq minutes), `mapgeo.ts` (ce qu'elle couvre, une précision en cercle, le zoom, une zone, une distance), `polyline.ts` (`decodePolyline6`, la même que `backendv2/src/mika/ports/maps.py`), `mapstyle.ts` (le style Protomaps, clair ou sombre), `base.ts` (une carte MapLibre : adresses absolues, la session, les commandes en français, le nord toujours en haut, le thème, `restyle`, des tuiles en échec de suite qui font revenir le plan), `view.ts` (`MapView` : épingles numérotées, roses pour ce que Mika a fait, tracés, `fitBounds`), `scene.ts` et `drawn.ts` (ce qu'une carte montre, et son plan dessiné sans tuile), `notes.ts` et `cards.ts` (ses notes de carte et leur miniature), `minis.ts` (les miniatures d'une liste : créées quand elles paraissent, quatre vivantes au plus ; ce qu'elles montrent, lu une fois pour la page et relu quand il a changé), `words.ts` (distances, durées, dates d'un voyage), `load.ts` (MapLibre et la vue, chargés une fois et à part) |
| `screens/outils/` | Outils : `index.ts`, `matrix.ts` (la matrice des droits, pure) |
| `screens/parametres/` | Paramètres : `index.ts` (routes, gestes délégués, sous-onglets), `page.ts` (ce qu'une page et son hôte se doivent), `form.ts` (lignes et barre d'enregistrement), `kit.ts` (lectures en cache — une relecture forcée suit celle en cours, un 404 efface ce qu'on avait lu —, erreurs, dates, copier, confirmer), `store.ts` (les lectures partagées), `words.ts` (les mots des niveaux et des états), une page par sous-onglet (`account`, `mail`, `teams`, `phones`, `shares`, `mcp`) |
| `api/` | `moi.ts` (`getJson`, `sendJson`, `apiUrl`), `me.ts` (`GET /api/moi`), et un client typé par domaine : `mail`, `teams`, `phone`, `rights`, `settings`, `shares`, `mcp`, `carte` (lieux, adresses, itinéraires, regards, voyages : `protocole-moi.md` § 10) |
| `shell/counts.ts` | les pastilles de la barre du haut, relues dans `GET /api/moi` (au démarrage, chaque minute, au retour sur l'onglet, après un geste) |
| `styles/` | `base.css` et `chat.css` portés de la maquette, `ecrans/` pour chaque écran, `app.css` pour ce qu'elle ne montrait pas |

Mika n'a qu'un élément (`#mika-corner`) : son visage dans la pastille du haut, ou en grand dans la colonne du chat
(`[data-mika-scene]`). Le cadre la gare avant de redessiner un écran et la reloge après (`corner.park()` /
`corner.lodge()`), comme la maquette.

## Ce que fait chaque écran aujourd'hui

- **Chat** : le fil (historique, rattrapage par curseur, accusés, « Mika écrit… », ses bulles l'une après l'autre,
  repères de jour), le champ (pièces jointes, emojis, Entrée pour envoyer), ses cartes d'accord au-dessus du champ,
  ses fichiers (`/files/<id>`), la bulle de sa position, la recherche dans les messages chargés et la liste des
  fichiers échangés. À droite, Mika en grand, son humeur (les facettes de `emotion_blend`), ce à quoi elle repense et
  ce qu'elle a promis. Pour une opératrice : « Pro » (fils de travail, ses outils en direct, Markdown), 👍/👎 et
  « pourquoi ? », « Tout accepter » (pour l'onglet).
  Une carte d'accord pour un brouillon de mail ou une réponse Teams devient un lien vers Mail ou Teams, où elle se
  relit et se décide (ADR 0191) ; « Tout accepter » ne la décide pas.
  Ses notes de carte (ADR 0196 : `look`, `map`, `trip`, `protocole-chat.md` § 4) se lisent ici, à côté de
  `@web/ui/messageNotes` qui garde la bulle 📍 seule (l'ancien client web les ignore), et se gardent avec le message ;
  chacune devient une carte miniature sous ses bulles, qui s'ouvre dans l'écran Carte. Une sorte inconnue s'ignore ; une
  note vidée (un regard oublié, un voyage supprimé) ne montre rien. Une miniature montre d'abord son plan dessiné ; quand
  elle paraît, ce qu'elle montre se lit (`GET /api/moi/carte/regards/<ref>`, `/api/moi/voyages/<ref>`) et une vraie
  carte, non interactive, prend sa place — quatre à la fois au plus, rendues quand elles sortent de la vue. Aucune ne
  demande d'itinéraire : un voyage s'y dessine en reliant ses arrêts, un regard avec le tracé qu'elle a gardé. Ce
  qu'elles montrent se lit une fois pour la page, chat et écran Carte ensemble : un voyage changé dans l'un se relit
  dans l'autre quand sa miniature reparaît.
- **Mail** : ses boîtes et celles qu'on lui partage (à leur niveau : lire, préparer, s'en servir), dossiers et
  non-lus, la liste (recherche, filtres, « Où Mika est passée »), la liseuse (ce qu'elle en sait, HTML isolé dans son
  cadre, images distantes, pièces), lu à l'ouverture selon `read_on_open`, répondre, transférer, écrire avec les
  destinataires proposés, « Préremplir avec Mika », ses brouillons (exactement ce qui partira : envoyer, retoucher,
  refuser, reprendre), les contacts.
- **Teams** : ses discussions, le fil (ses messages à droite, les mentions), ses réponses en carte et « Ses
  brouillons », ton message par l'extension du compte, sous le nom de qui y est connecté dans Teams (ADR 0189),
  « Préremplir avec Mika ».
- **Téléphone** : ses téléphones, les conversations que l'application a lues, leurs fils, ses propositions et leur
  sort, sa dernière position — sur une vraie carte quand le serveur en sert une qui la couvre (ADR 0193 : ses tuiles,
  polices et icônes viennent du serveur seul, `GET /api/moi/phone/map` ; MapLibre se charge avec l'onglet), sinon sur
  le plan dessiné. Répondre d'ici et « Préremplir » (ADR 0189, 0191) n'ont pas encore de route dans l'API
  (et l'application Android devra envoyer sans redemander le geste) : le champ le dit.
  Une autre carte servie, relue pendant que l'onglet est ouvert (des polices ajoutées, une autre source, une autre
  zone), se repose sur la carte ouverte. Une carte qui ne se dessine pas (pas de WebGL, MapLibre qui ne vient pas, ses
  tuiles en échec de suite) laisse le plan dessiné et sa note, sans réessayer à chaque dessin — jusqu'à une autre carte
  servie.
- **Carte** (ADR 0194 à 0196) : sur la carte du serveur (la même que Téléphone), ou sur le plan dessiné de ce qu'elle
  montre quand elle ne se dessine pas. **Explorer** cherche dans l'index des lieux du serveur (rien ne sort) : un nom,
  une catégorie, « Autour de moi » (la dernière position de son téléphone) ou « Dans cette zone » (le cadre de la carte,
  recherché de nouveau quand on la déplace), et une adresse (Géoplateforme, relayée : seul le texte part) ; la fiche d'un
  lieu mène à « Itinéraire jusqu'ici », « Ajouter au voyage » et « En parler à Mika ». **Itinéraire** : ses points
  (un lieu, une adresse, « Ma position »), voiture, vélo ou à pied, péages, autoroutes ou ferries évités, la durée, la
  distance et l'heure d'arrivée, les consignes, un GPX fait dans le navigateur, « En faire un voyage », « Envoyer à
  Mika ». **Voyages** : la liste en cartes (leurs miniatures), « Nouveau voyage », et l'éditeur jour par jour — les
  tronçons, ses arrêts en rose (retirables, comme les tiens), glisser une poignée (ou ses flèches au clavier) pour
  réordonner d'un jour à l'autre, « Ajouter un arrêt », « Sur la route » (les lieux le long du trajet, ajoutés au bon
  jour), « Optimiser l'ordre », le GPX du serveur, « Demander à Mika », qui ouvre le chat avec une phrase préremplie
  (le mode pro, s'il était choisi, cède la place). Ce qu'elle a cherché ou montré s'ouvre ici (`#carte/explorer/regard-<n>`,
  `#carte/itineraire/regard-<n>`), ses lieux en rose ; son trajet s'y montre tel qu'elle l'a gardé (son mode, ce qu'il
  évitait), et ne se recalcule qu'au premier changement (ou « Recalculer »). Sans index, sans adresses ou sans
  itinéraires, l'endroit qui en a besoin dit le message du serveur (503) et le reste marche.
  Ce qui sort du serveur est borné par compte (`protocole-moi.md` § 10 ; un 429 se dit à l'endroit qui l'a reçu) :
  une adresse ne se demande que si le texte en a l'air (un chiffre, ou cinq caractères), après 0,7 s sans frappe, une
  fois par texte (la carte qu'on bouge ne la redemande pas) ; le trajet d'un voyage se garde pour ses arrêts (un autre
  ordre, un autre mode : il se relit 1,5 s après le dernier geste, et le trajet d'avant ne se montre pas en attendant),
  et « Sur la route » ne se recherche que si le trajet a changé. Les gestes sur un voyage se font l'un après l'autre ; un
  arrêt lâché à sa place n'envoie rien ; chaque ajout a sa clé d'envoi (un double clic, un réessai ne l'ajoutent qu'une
  fois). Un point d'itinéraire retapé rend le trajet montré passé : ni consignes, ni GPX, ni « En faire un voyage »
  avant de le choisir. La carte ne tourne pas (pas de boussole pour revenir au nord) ; la main reste sur le contrôle
  qu'on touchait d'un dessin à l'autre, et un arrêt déplacé au clavier se dit à un lecteur d'écran.
- **Outils** : la matrice de ses droits, ressource par ressource — chaque outil, par chaque canal et à chaque moment,
  la décision même de la porte d'offre, et pourquoi ; ses comptes avec leur règle d'envoi ; ses services.
- **Paramètres** : son compte (nom, mot de passe), ses boîtes (ajouter, régler, tester, connecter à Microsoft,
  retirer), ses comptes Teams (et la clé de leur extension, montrée une fois), ses téléphones (révoquer, télécharger
  l'application), ses partages, ses services MCP (brancher un service distant, ses outils, le retirer).
- **Partout** : la pastille de Mika (ce qu'elle fait, son humeur) ouvre « Ce qu'elle fait » ; Ctrl K cherche un écran,
  un onglet, un message récent ou un fil ; le menu du compte change le thème et déconnecte.
