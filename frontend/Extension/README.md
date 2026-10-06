# Mika · Teams — l'extension de navigateur

Elle fait lire à Mika tes conversations **Teams web** (discussions privées, groupes, canaux, réunions) et lui permet
d'y répondre. Elle regarde ce que le client web de Teams reçoit déjà, et l'envoie au plugin Teams du serveur de Mika
(`backendv2/`) sur ta machine ; dans l'autre sens, elle relève ce que Mika a écrit et le pose dans Teams. Elle ne se
connecte nulle part en ton nom : elle n'utilise que ta session, dans l'onglet que tu as ouvert.

Chrome, Edge et Chromium 111 ou plus récents. Firefox n'est pas pris en charge pour l'instant.

## Installer

1. `chrome://extensions` → activer **Mode développeur** (en haut à droite).
2. **Charger l'extension non empaquetée** → choisir ce dossier (`frontend/Extension/`).
3. **Recharger l'onglet Teams** s'il était déjà ouvert : le script n'entre que dans une page chargée après.

Une mise à jour depuis la première version (celle des signaux d'appareil) oublie l'ancien jeton et l'ancienne file :
il faut coller la clé Teams.

## Brancher sur Mika

L'extension parle au plugin `teams` de Mika (`/api/teams/…`). Il lui faut la **clé Teams** (elle commence par
`mtk_`) :

- dans la console : Configuration › Teams ;
- ou en ligne de commande : `.venv/bin/python -m mika --data data/v2 teams key` (depuis `backendv2/`).

Dans la fenêtre de l'extension, colle l'adresse (`http://127.0.0.1:8001` par défaut) et la clé, puis
**Enregistrer** et **Tester**. « Tester » relève la boîte d'envoi de Mika sans rien y changer : « Mika répond et
accepte la clé », « clé refusée », un refus de Mika (Teams désactivé dans ses réglages), « pas de plugin Teams à
cette adresse (mettre à jour Mika) », ou l'erreur réseau.
La clé n'est jamais réaffichée (le champ dit seulement qu'elle est définie). Une adresse qui n'est pas sur cette
machine demande une permission supplémentaire, que Chrome affiche à l'enregistrement.

Une clé refusée arrête tout envoi jusqu'à ce que les réglages changent.

## Ce que Mika reçoit

Les messages neufs, **entiers** (4000 caractères au plus), avec leur conversation (son nom et sa nature : tête-à-tête,
groupe, canal, réunion), leur auteur, leur heure, et deux drapeaux :

- `own` : c'est **ton** message. Les tiens partent aussi : Mika a besoin des deux voix d'un fil, et c'est à ton
  message qu'elle voit qu'une réponse qu'elle avait préparée est partie ;
- `mentions_me` : le message te mentionne.

Les messages partent par lots (`POST /api/teams/inbox`) de 200 messages, 200 conversations et 512 Kio au plus ; un
lot trop gros pour le serveur est recoupé. Un message dont l'identifiant (ou celui de sa conversation) n'a pas une
forme que le serveur accepte est écarté avant de partir, pour ne pas faire refuser tout son lot. Mika injoignable :
nouvel essai après 15 s, puis 30, 60… jusqu'à 5 min.

- **Seulement ce qui est neuf.** Rien de ce qui précède l'installation, ni de plus de 24 heures. Le navigateur fermé
  la nuit, elle rattrape au matin ce qui est arrivé (sur 24 heures au plus). Remonter dans un vieil historique
  n'envoie rien. « Repartir de maintenant » oublie ce qui attend et ignore tout ce qui précède.
- **En pause**, rien n'est mis de côté : ce qui arrive pendant la pause ne lui sera jamais envoyé, et elle n'écrit
  rien dans Teams.
- **Exclure** une conversation : une ligne avec un morceau de son nom (ou de son identifiant). Une conversation
  exclue ne quitte jamais le navigateur, ni ses messages ni son nom ; ce qui attend dans la file est retiré, et ce
  que Mika voudrait y écrire est refusé.

## Ce que Mika écrit

Toutes les 30 s, et juste après chaque envoi, l'extension relève la boîte d'envoi de Mika
(`GET /api/teams/outbox`) et lui rend chaque issue (`POST /api/teams/outbox/<id>` : placé, envoyé, ou échec avec sa
raison). Le **mode** se décide chez Mika, pas ici ; la **signature** ajoutée à ses messages se règle aussi dans ses
réglages : l'extension pose le texte tel qu'elle le reçoit.

- **Brouillon** (le mode par défaut). Mika a préparé une réponse ; c'est toi qui l'envoies. Une notification dit
  « Mika a préparé une réponse pour Alice » ; un clic ouvre l'onglet Teams sur la conversation (un canal ou une
  réunion n'ont pas de lien direct : l'onglet est montré, la notification dit où aller). Quand cette conversation est
  ouverte, que l'onglet est visible, que la zone de saisie est vide et que tu n'écris pas ailleurs dans Teams, le
  texte s'y place. Tu le relis, tu le changes, tu l'envoies — ou pas. Un brouillon n'est placé qu'une fois dans ce
  navigateur, même si tu l'effaces ; passé son échéance, il n'est plus proposé (Mika le clôt de son côté).
  L'extension ne change jamais de conversation d'elle-même.
- **Validation.** Mika a écrit, tu as approuvé chez elle : le message part tout seul.
- **Autonome.** Mika envoie seule : le message part tout seul.

Un message à envoyer part par le **service de chat** du client Teams, avec l'authentification que le client utilise
lui-même pour ses propres requêtes (l'extension la voit passer et la garde dans la mémoire de l'onglet : elle n'est
jamais transmise, ni à l'extension, ni à Mika, ni journalisée). Si elle n'a pas encore été vue, le texte est placé
dans la zone de saisie de la conversation ouverte puis envoyé (bouton « Envoyer »). Sinon le message attend la relève
suivante ; à son échéance, Mika apprend « jamais envoyé : Teams pas ouvert ou envoi impossible ». Un envoi dont
l'issue est douteuse (Teams muet, service arrêté au milieu) n'est jamais retenté : Mika apprend qu'il faut vérifier.

La fenêtre de l'extension montre ce qui attend (avec un bouton « Ouvrir dans Teams ») et les 30 dernières issues,
avec 120 caractères du texte au plus.

## Ce qui part où

- Le texte des messages va de l'onglet Teams au serveur de Mika (local par défaut). De là, quand elle les lit, il
  part chez le **fournisseur du modèle** qu'elle utilise (Ollama Cloud, l'API Claude…), comme tout ce qu'elle lit.
- Dans le navigateur, l'extension garde (`chrome.storage.local`) la clé, les messages en attente d'envoi, les
  identifiants déjà vus (24 heures), ce que Mika veut écrire et ce qui en est advenu (les 30 dernières issues ; le
  bouton « Effacer » les retire).
- L'authentification du service de chat de Teams ne quitte jamais l'onglet.

Si c'est le Teams de ton travail, ce sont des échanges internes, et les messages de tes collègues, qui sortent de
l'entreprise vers un système personnel et vers un fournisseur de modèle ; et ce sont des messages écrits par une IA
qui partent en ton nom. Vérifie ce que la charte informatique en dit.

## Comment elle capte, comment elle écrit

`page/capture.js` est chargé **dans** la page (monde `MAIN`), avant le client Teams. Pour lire, il a deux sources,
dédoublonnées par l'identifiant du message :

- **le réseau** : les réponses JSON (`fetch`, `XMLHttpRequest`) dont l'adresse ressemble au service de chat, et
  les trames du WebSocket par lequel arrivent les messages en direct ;
- **la base IndexedDB du client**, relue toutes les 45 s (1,5 s de travail au plus) : elle rattrape ce que le réseau
  ne montre pas, comme une requête faite par un worker ou un message arrivé avant l'ouverture de l'onglet. Les bases
  sont ouvertes sans version et refermées aussitôt : l'extension n'en crée et n'en modifie aucune.

`lib/extract.js` reconnaît un message à sa **forme**, et non à une adresse : un contenu, une date, et un type, un
auteur ou une conversation. C'est la forme des messages du service de chat, stable depuis Skype. Les frappes en
cours, l'activité du fil, les appels et les messages supprimés sont écartés. Le HTML est lu sans `DOMParser`, que
les Trusted Types de la page interdisent.

Pour écrire (`lib/page.js` pour ce qui se calcule sans la page) :

- la **conversation ouverte** se lit dans l'historique de navigation que Teams range dans le `sessionStorage`
  (`tmp.session.<uuid>-mainWindowNavHistory`, l'entrée courante, `activeEntities.mainEntity.id`), sinon dans
  l'adresse de la page ;
- la **zone de saisie** est le premier élément visible parmi `[data-tid="ckeditor"][contenteditable="true"]`,
  `[data-tid*="ckeditor"][contenteditable="true"]` et `div[role="textbox"][contenteditable="true"]` ; le texte y
  entre par `document.execCommand("insertText")`, ligne à ligne, avec un saut de ligne simple entre deux lignes
  (jamais `innerHTML`, que les Trusted Types interdisent) ;
- l'**envoi par le service de chat** est un `POST <base>/v1/users/ME/conversations/<id>/messages`
  (`RichText/Html`, texte échappé, retours à la ligne en `<br>`, `clientmessageid` aléatoire, ton nom d'affichage),
  avec les en-têtes `authentication`, `authorization` ou `x-skypetoken` vus sur les requêtes du client vers
  `…/v1/users/ME/conversations`.

`content/relay.js` (monde isolé) relaie entre la page et `background.js`, en ne laissant passer que des formes
connues et bornées. `background.js` décide de ce qui part (`lib/signals.js`), tient la file, relève la boîte d'envoi
et suit chaque élément (`lib/outbox.js`) : un placement ou un envoi est marqué avant d'être fait, pour ne jamais
l'être deux fois. Tout l'état vit dans `chrome.storage.local`, parce qu'un service MV3 peut être arrêté à tout moment.

### Limites

Le chemin d'écriture n'a **pas encore été vérifié contre le vrai Teams** : il a été éprouvé sur une page de banc
(zone de saisie, historique de navigation, service de chat simulés), pas sur le client de Microsoft. Les sélecteurs
de la zone de saisie et du bouton « Envoyer », la forme de l'historique de navigation, et la forme exacte de la
requête d'envoi (en-têtes que le service exigerait en plus de l'authentification) sont à calibrer. Le client récent
fait une grande partie de ses requêtes depuis un worker, que l'extension ne voit pas : l'envoi passera alors par la
zone de saisie de la conversation ouverte.

### Quand Teams change

Microsoft modifie son client sans prévenir. Si plus rien n'arrive, ou que Mika n'arrive plus à écrire, ouvre
**Diagnostic de l'onglet Teams** :

- les réponses et trames lues côté réseau, et les messages qu'on en a tirés ;
- les bases locales trouvées, leurs magasins, leurs enregistrements et les messages qu'on en a tirés ;
- si ton identité a été trouvée (pour reconnaître tes propres messages et les mentions) ;
- **zone de saisie trouvée**, **conversation active connue**, **envoi par le service de chat possible** (oui ou
  non : l'existence de l'en-tête, jamais sa valeur), et ce qui a été placé ou envoyé depuis l'ouverture de l'onglet.

Le diagnostic ne montre aucun contenu. Si le réseau et la base locale ne donnent plus rien, c'est le format des
messages qui a changé : c'est `lib/extract.js` qu'il faut adapter. Si la zone de saisie ou la conversation active ne
sont plus trouvées, ce sont les sélecteurs de `page/capture.js` ou la lecture de l'historique dans `lib/page.js`.

## Tests

```bash
cd frontend/Extension && npm test     # node --test, sans dépendance
```

Ils couvrent la reconnaissance des messages (réponse du service de chat, trame du WebSocket, enregistrement de la
base locale, pièce jointe, message supprimé, HTML d'une réponse citée) ; ce qui part (nouveauté, pause, exclusion,
déjà vu, conversation inconnue, les deux voix et la mention, lots coupés sous 200 messages, 200 conversations et
512 Kio comptés en octets, recoupe après un 413, nom appris après coup, Retry-After, attente croissante) ; la boîte
d'envoi (un brouillon placé une seule fois même si la liste du serveur est en retard ou après un redémarrage, un
placement refusé qui redevient possible, échéance et exclusion dites en échec, un envoi marqué avant de partir et
jamais refait, envoi douteux ou interrompu jamais retenté, réponses 404/409/400 aux issues, journal borné à 120
caractères) ; et ce que lit la page (en-têtes d'authentification en `Headers`, en liste ou en objet, base du service
de chat, échappement HTML du corps d'envoi, identifiant client, conversation ouverte dans un historique de navigation
de formes diverses ou dans l'adresse).
