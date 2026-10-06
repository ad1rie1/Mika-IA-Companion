# Mika · Teams — l'extension de navigateur

Elle fait lire à Mika tes conversations **Teams web** (discussions privées, groupes, canaux, réunions) et lui permet
d'y répondre. Elle regarde ce que le client web de Teams reçoit déjà, et l'envoie au plugin Teams du serveur de Mika
(`backendv2/`) sur ta machine ; dans l'autre sens, elle relève ce que Mika a écrit et le pose dans Teams. Elle ne se
connecte nulle part en ton nom : elle n'utilise que ta session, dans l'onglet que tu as ouvert.

Chrome, Edge et Chromium 120 ou plus récents. Firefox n'est pas pris en charge pour l'instant.

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
machine doit être en `https://` (la clé et les messages ne traversent pas un réseau en clair : `http://` n'est accepté
que pour `127.0.0.1` et `localhost`), et demande une permission supplémentaire, que Chrome affiche à
l'enregistrement.

Une clé refusée arrête tout envoi jusqu'à ce que les réglages changent.

## Ce que Mika reçoit

Les messages neufs, **entiers** (4000 caractères au plus, coupés sans jamais casser un emoji), avec leur conversation
(son nom et sa nature : tête-à-tête, groupe, canal, réunion), leur auteur, leur heure, et deux drapeaux :

- `own` : c'est **ton** message. Les tiens partent aussi : Mika a besoin des deux voix d'un fil, et c'est à ton
  message qu'elle voit qu'une réponse qu'elle avait préparée est partie ;
- `mentions_me` : le message te mentionne.

Un message **modifié** repart avec son nouveau texte (même identifiant : Mika met le sien à jour) ; un message
**supprimé** part comme une suppression (`deleted: true`, texte vide : Mika efface sa copie), et plus aucun texte de
ce message ne repart ensuite. C'est soi exact qui compte pour `own` : l'identifiant de l'auteur doit être le tien
(`8:orgid:<uuid>`), pas seulement le contenir.

Les messages partent par lots (`POST /api/teams/inbox`) de 200 messages, 200 conversations et 512 Kio au plus ; un
lot trop gros pour le serveur est recoupé. Un message dont l'identifiant (ou celui de sa conversation) n'a pas une
forme que le serveur accepte est écarté avant de partir ; un message que le serveur juge illisible est écarté par lui
seul, le reste du lot passe (un 400 ne veut plus dire qu'un corps entier illisible). Mika injoignable : nouvel essai
après 15 s, puis 30, 60… jusqu'à 5 min. Un même lot refusé 8 fois de suite par la même erreur 5xx est écarté (et
noté), pour ne pas bloquer toute la file.

- **Seulement ce qui est neuf.** Rien de ce qui précède l'installation, ni de plus de 24 heures. Le navigateur fermé
  la nuit, elle rattrape au matin ce qui est arrivé (sur 24 heures au plus). Remonter dans un vieil historique
  n'envoie rien. « Repartir de maintenant » oublie ce qui attend et ignore tout ce qui précède.
- **En pause**, rien n'est mis de côté : ce qui est **écrit** pendant la pause ne lui sera jamais envoyé, même capté
  après la reprise (l'extension garde les intervalles de pause des dernières 24 heures et juge chaque message à son
  heure) ; les noms de conversation vus pendant la pause ne sont pas gardés (l'onglet les redit à la reprise) ; et
  elle n'écrit rien dans Teams. Les issues de ce qu'elle avait déjà écrit, elles, lui sont encore rendues.
- **Exclure** une conversation : une ligne avec un morceau de son nom (ou de son identifiant). Un tête-à-tête n'a
  pas de nom : il s'exclut par le **nom de la personne** qu'on y a vue écrire (de même un groupe sans sujet, par ses
  membres). Une conversation exclue ne quitte jamais le navigateur, ni ses messages ni son nom ; ce qui attend dans la
  file est retiré, et ce que Mika voudrait y écrire est refusé — c'est revérifié juste avant de placer ou d'envoyer.
  Tant que des exclusions sont réglées, un message dont on ne sait pas encore nommer la conversation (un groupe ou un
  canal dont le nom n'a pas été vu, un tête-à-tête où l'on n'a vu écrire que toi) **attend jusqu'à 2 minutes** qu'on
  l'apprenne, puis on décide avec ce qu'on sait.

## Ce que Mika écrit

Toutes les 30 s, et juste après chaque envoi, l'extension relève la boîte d'envoi de Mika
(`GET /api/teams/outbox`) et lui rend chaque issue sûre (`POST /api/teams/outbox/<id>` : placé, envoyé, ou échec avec
sa raison). Les issues partent avant chaque relève, même en pause ou pendant une attente de la file (pas après une
clé refusée), et sont gardées tant que Mika ne les a pas reçues, même quand elle ne liste plus l'élément ; une issue
qu'elle refuse 10 fois de suite (une 4xx autre que 401, 403, 404, 408, 409 et 429, redite de plus en plus espacée)
est abandonnée et notée au journal. Le **mode** se décide chez Mika, pas ici ; la **signature** ajoutée à ses
messages se règle aussi dans ses réglages : l'extension pose le texte tel qu'elle le reçoit.

- **Brouillon** (le mode par défaut). Mika a préparé une réponse ; c'est toi qui l'envoies. Une notification dit
  « Mika a préparé une réponse pour Alice » ; un clic ouvre l'onglet Teams sur la conversation (un canal ou une
  réunion n'ont pas de lien direct : l'onglet est montré, la notification dit où aller). Quand cette conversation est
  ouverte, que l'onglet est visible, que la zone de saisie est vide et que tu n'écris pas ailleurs dans Teams, le
  texte s'y place. Tu le relis, tu le changes, tu l'envoies — ou pas. Un brouillon n'est placé qu'une fois dans ce
  navigateur, même si tu l'effaces ; passé son échéance, il n'est plus proposé (Mika le clôt de son côté).
  L'extension ne change jamais de conversation d'elle-même.
- **Validation.** Mika a écrit, tu as approuvé chez elle : le message part tout seul.
- **Autonome.** Mika envoie seule : le message part tout seul.

Un message à envoyer est d'abord **réclamé** auprès de Mika (`{"result": "sending"}`) : un seul navigateur obtient la
réclamation, une seule fois (un 409 veut dire qu'un autre navigateur, ou une tentative d'avant dont la réponse s'est
perdue, l'a déjà : il n'est jamais envoyé d'ici), et l'élément disparaît alors de la liste pour tous. Puis il part par
le **service de chat** du client Teams, avec l'authentification que le client utilise lui-même pour ses propres
requêtes (l'extension la voit passer, sur un hôte de Teams seulement, et la garde dans la mémoire de l'onglet : elle
n'est jamais transmise, ni à l'extension, ni à Mika, ni journalisée), avec un `clientmessageid` tiré de l'identifiant
de l'élément (le même à chaque tentative), et 20 s au plus. Si l'authentification n'a pas encore été vue (ou est
périmée), le texte est placé dans la zone de saisie de la conversation ouverte puis envoyé (bouton « Envoyer »).

Une issue n'est dite que si elle est **sûre** :

- **envoyé** : le service de chat a répondu 2xx, ou la zone de saisie s'est vidée après « Envoyer » ;
- **échec** : rien n'est parti — le service a refusé le message (une 4xx autre que 408 et 429 ; un 401 ou un 403,
  l'authentification périmée, passe la main à la zone de saisie), la conversation est exclue, ou l'échéance est
  passée sans que l'envoi ait pu commencer ;
- **rien n'a commencé** (pas d'onglet Teams, onglet sans le script, page qui n'a pas pris la demande, conversation pas
  ouverte, zone de saisie occupée) : ce navigateur garde la réclamation et réessaie à la relève suivante ;
- **douteux** (5xx, 408, 429, coupure, plus de 20 s, texte resté dans la zone de saisie, onglet fermé ou muet après
  avoir pris la demande, service arrêté au milieu) : ni dit à Mika, ni **jamais** retenté. Mika le tranche elle-même :
  « envoyé » si ton message apparaît dans la conversation, « échec incertain » à l'échéance. Le journal de
  l'extension le note « issue incertaine ».

Un même onglet ne commence jamais deux fois l'envoi d'un même élément.

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

`page/capture.js` est chargé **dans** la page (monde `MAIN`), avant le client Teams. Pour lire, il a deux sources :

- **le réseau** : les réponses JSON (`fetch`, `XMLHttpRequest`) dont l'adresse ressemble au service de chat, et
  les trames du WebSocket par lequel arrivent les messages en direct (2 Mo au plus, lues après que Teams a traité
  l'événement ; `socket.constructor === WebSocket` reste vrai pour le client) ;
- **la base IndexedDB du client**, relue toutes les 45 s (1,5 s de travail au plus) : elle rattrape ce que le réseau
  ne montre pas, comme une requête faite par un worker ou un message arrivé avant l'ouverture de l'onglet. Les bases
  sont ouvertes sans version et refermées aussitôt : l'extension n'en crée et n'en modifie aucune.

Les deux sources sont dédoublonnées par **version** : l'identifiant du message et un condensé de son texte. Un message
modifié repasse ; une version plus ancienne qu'une déjà vue (un cache en retard) ne revient pas, ni le texte d'un
message déjà vu supprimé.

`lib/extract.js` reconnaît un message à sa **forme**, et non à une adresse : un contenu, une date, et un type, un
auteur ou une conversation. C'est la forme des messages du service de chat, stable depuis Skype. Les frappes en
cours, l'activité du fil et les appels sont écartés ; un message supprimé devient une suppression. Le HTML est lu
sans `DOMParser`, que les Trusted Types de la page interdisent.

Pour écrire (`lib/page.js` pour ce qui se calcule sans la page) :

- la **conversation ouverte** se lit dans l'historique de navigation que Teams range dans le `sessionStorage`
  (`tmp.session.<uuid>-mainWindowNavHistory`, l'entrée courante, `activeEntities.mainEntity.id`), sinon dans
  l'adresse de la page ;
- la **zone de saisie** est le premier élément visible parmi `[data-tid="ckeditor"][contenteditable="true"]`,
  `[data-tid*="ckeditor"][contenteditable="true"]` et `div[role="textbox"][contenteditable="true"]` ; le texte y
  entre par `document.execCommand("insertText")`, ligne à ligne, avec un saut de ligne simple entre deux lignes
  (jamais `innerHTML`, que les Trusted Types interdisent) ;
- l'**envoi par le service de chat** est un `POST <base>/v1/users/ME/conversations/<id>/messages`
  (`RichText/Html`, texte échappé, retours à la ligne en `<br>`, `clientmessageid` stable — 19 chiffres d'un condensé
  FNV-1a 64 bits de l'identifiant de l'élément —, ton nom d'affichage), avec les en-têtes `authentication`,
  `authorization` ou `x-skypetoken` vus sur les requêtes du client vers `…/v1/users/ME/conversations`, et seulement
  si cette requête allait vers un hôte de Teams (`*.teams.microsoft.com`, `*.teams.cloud.microsoft`,
  `teams.live.com`, `*.skype.com`, `*.teams.microsoft.us`).

`content/relay.js` (monde isolé) relaie entre la page et `background.js`, en ne laissant passer que des formes
connues et bornées : tant que la page n'a pas dit « commencé », rien n'est parti ; une fois qu'elle l'a dit, une réponse
qui manque laisse l'issue douteuse (la page ne commence pas une demande arrivée après l'échéance qu'on lui donne).
`background.js` décide de ce qui part (`lib/signals.js`), tient la file, relève la boîte d'envoi et suit chaque élément
(`lib/outbox.js`) : un placement, une réclamation ou un envoi est marqué avant d'être fait, pour ne jamais l'être deux
fois. Toute coupe de texte passe par `lib/text.js`, qui ne coupe jamais une paire de substitution (une moitié
d'emoji seule faisait refuser un lot entier). Tout l'état vit dans `chrome.storage.local` (sans plafond de taille,
`unlimitedStorage`), parce qu'un service MV3 peut être arrêté à tout moment.

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

Ils couvrent la coupe des textes (un emoji à la frontière, une moitié de paire déjà seule) et les versions d'un
message (modification, cache en retard, texte après suppression) ; la reconnaissance des messages (réponse du service
de chat, trame du WebSocket, enregistrement de la base locale, pièce jointe, suppression, modification, HTML d'une
réponse citée) ; ce qui part (nouveauté, pause jugée à l'heure du message et intervalles bornés, exclusion par le nom,
l'identifiant ou la personne, retenue le temps d'apprendre un nom, déjà vu, conversation inconnue, soi exact, les deux
voix et la mention, lots coupés sous 200 messages, 200 conversations et 512 Kio comptés en octets, recoupe après un
413, nom appris après coup, Retry-After, attente croissante, erreurs 5xx comptées, adresse https hors de cette
machine) ; la boîte d'envoi (un brouillon placé une seule fois même si la liste du serveur est en retard ou après un
redémarrage, un placement refusé qui redevient possible, échéance et exclusion dites en échec, réclamation accordée,
prise ailleurs ou sans réponse, un envoi marqué avant de partir et jamais refait, « rien n'a commencé » qui garde la
réclamation, envoi douteux ou interrompu ni dit ni retenté, issues gardées quand le serveur ne liste plus l'élément,
réponses 404/409/4xx/429/5xx aux issues et abandon après 10 refus, issue sans texte, journal borné à 120 caractères) ;
et ce que lit la page (en-têtes d'authentification en `Headers`, en liste ou en objet, base du service de chat et
hôtes de Teams seulement, échappement HTML du corps d'envoi, identifiant client stable, réponse du service de chat
sûre ou douteuse, conversation ouverte dans un historique de navigation de formes diverses ou dans l'adresse).
