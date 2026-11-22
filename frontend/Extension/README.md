# Mika · Teams — l'extension de navigateur

Elle fait lire à Mika tes conversations **Teams web** (discussions privées, groupes, canaux, réunions) et lui permet
d'y répondre. Elle regarde ce que le client web de Teams reçoit déjà, et l'envoie au plugin Teams du serveur de Mika
(`backendv2/`) sur ta machine ; dans l'autre sens, elle relève ce que Mika a écrit et le pose dans Teams. Elle ne se
connecte nulle part en ton nom : elle n'utilise que ta session, dans l'onglet que tu as ouvert.

Chrome, Edge et Chromium 120 ou plus récents. Firefox n'est pas pris en charge pour l'instant.

## Installer

1. La prendre : dans frontendv2, Paramètres › Teams › ton compte › L'extension › **Télécharger** (un zip, ADR 0246 :
   le serveur le fait depuis ce dossier, tel qu'il est déployé), puis le décompresser ; ou, sur la machine du dépôt,
   ce dossier même (`frontend/Extension/`).
2. `chrome://extensions` → activer **Mode développeur** (en haut à droite).
3. **Charger l'extension non empaquetée** → choisir le dossier `mika-teams` décompressé (ou ce dossier-ci).
4. **Recharger l'onglet Teams** s'il était déjà ouvert : le script n'entre que dans une page chargée après.

Pour la mettre à jour : décompresser le nouveau zip par-dessus, puis ↻ (Recharger) sur sa carte dans
`chrome://extensions`. Chrome relit sa fenêtre sur le disque à chaque ouverture, mais garde son service d'arrière-plan
tant qu'on ne la recharge pas : sans ce geste, la fenêtre neuve parle à l'ancien service. La fenêtre le voit (la
version du `manifest.json` sur le disque n'est pas celle que Chrome a chargée, ou le service répond « demande
inconnue ») et l'affiche en haut, avec **Recharger l'extension et l'onglet Teams** : l'extension se recharge, puis son
nouveau service recharge les onglets Teams, seulement à cette demande et dans la minute.

Le zip emporte ses fichiers tels qu'ils sont, sans `tests/`, `package.json` ni ce `README.md` : un fichier qu'elle
charge se range ailleurs qu'à ces trois places.

Une mise à jour depuis la première version (celle des signaux d'appareil) oublie l'ancien jeton et l'ancienne file :
il faut coller la clé Teams.

## Brancher sur Mika

L'extension parle au plugin `teams` de Mika (`/api/teams/…`). Il lui faut la **clé Teams** (elle commence par
`mtk_`) :

- dans la console : Relations & échanges › Teams › Extension, sur le compte Teams de la personne (un compte par
  personne, chacun sa clé : ADR 0186) ;
- ou en ligne de commande : `.venv/bin/python -m mika --data data/v2 teams key --compte <clé>` (depuis `backendv2/` ;
  sans `--compte`, le compte `principal`).

Dans la fenêtre de l'extension, colle l'adresse (`http://127.0.0.1:8001` par défaut) et la clé, puis
**Enregistrer** et **Tester**. « Tester » enregistre d'abord une clé collée ou une adresse changée (on teste ce
qu'on voit), puis relève la boîte d'envoi de Mika sans rien y changer : « Mika répond et accepte la clé », « clé
refusée », un refus de Mika (Teams désactivé dans ses réglages), « pas de plugin Teams à cette adresse (mettre à
jour Mika) », l'accès que Chrome n'a pas donné, ou l'erreur réseau.
La clé n'est jamais réaffichée (le champ dit seulement qu'elle est définie). Une adresse qui n'est pas sur cette
machine doit être en `https://` (la clé et les messages ne traversent pas un réseau en clair : `http://` n'est accepté
que pour `127.0.0.1`, `localhost` et `[::1]`), et demande une permission supplémentaire, que Chrome affiche à
l'enregistrement.

En IPv6 : `http://[::1]:8001` vaut la machine locale, si le serveur écoute en IPv6 (`serve --host ::1`, ou `::`). Un
nom qui n'a qu'une adresse IPv6 (un enregistrement AAAA sans A) s'écrit comme un autre : c'est le système qui le
résout, et il ne répond que d'un réseau qui a l'IPv6 (sinon « Mika injoignable »). Une IPv6 littérale s'écrit entre
crochets (`https://[2001:db8::1]:8443`), mais le certificat du mandataire est celui de son nom : derrière Caddy,
garder le nom.

Une clé refusée arrête tout envoi jusqu'à ce que les réglages changent.

## Ce que Mika reçoit

Les messages neufs, **entiers** (4000 caractères au plus, coupés sans jamais casser un emoji), avec leur conversation
(son nom et sa nature : tête-à-tête, groupe, canal, réunion), leur auteur, leur heure, et deux drapeaux :

- `own` : c'est **ton** message. Les tiens partent aussi : Mika a besoin des deux voix d'un fil, et c'est à ton
  message qu'elle voit qu'une réponse qu'elle avait préparée est partie ;
- `mentions_me` : le message te mentionne.

Le texte est celui du HTML de Teams : une réponse citée tient sur une ligne (« … »), un **tableau** donne une ligne
par rangée, ses cellules séparées par « | » (et une ligne vide avant et après), un emoji garde son caractère, une
**image** collée ou jointe devient « [image] » et une pièce jointe « [pièce jointe : nom] ».

**Les images** (ADR 0258) partent aussi, elles-mêmes. L'extracteur relève celles du service d'images de Teams
(`https://….asm.skype.com/v1/objects/<id>/views/…`, 8 par message au plus) avec leur rang parmi les « [image] » du
texte ; aucune autre adresse n'est jamais ouverte. Le message part avec leur nombre (`images`) : Mika l'attend le
temps de les regarder. La page les télécharge une à une, par leur vue d'origine (`imgo`), avec les cookies du
navigateur comme Teams lui-même — affichées ou non —, 8 Mo au plus, PNG, JPEG, GIF ou WebP ; le service les trie comme
leur message (exclusions, pauses ; en direct, la fenêtre de 24 h) et les envoie à `POST /api/teams/image`
(`{conv, id, image, position, type, data}`, `data` en base64, sous la clé du compte) une fois le message chez Mika :
202 (gardée), 404 (son message n'y est pas encore : retentée 30 s plus tard, trois fois), 400 (pas une image de ce
type). L'historique envoie les images de chaque paquet juste après lui. Chez Mika, ce qu'elle y voit remplace
« [image] » dans le texte (« [image : … ] »), et frontendv2 les montre dans le fil.

**Les réactions** (ADR 0300, depuis 0.7.0) : un message part avec ses réactions quand la source les dit
(`properties.emotions`, un texte JSON ou une liste : `[{key, users: [{mri, time, value}]}]` ; à défaut le seul compte,
`annotationsSummary.emotions`) : `reactions: [{key, count, mine, by}]` — la clé de Teams (`like`, `heart`,
`1f44f_clappinghands`…), combien l'ont posée, si c'est la tienne, et qui (dix identifiants au plus, les premiers à
l'avoir posée ; le compte, lui, est entier) ; 20 réactions au plus par message. Une source qui n'en dit rien n'envoie
pas `reactions` (Mika garde les siennes) ; `[]` dit qu'il n'y en a plus. Un message dont les réactions changent
**repart**, sous le même identifiant (voir « dédoublonnées par version », plus bas) : Mika met les siennes à jour, sans
en faire un message neuf — une réaction ne lui fait rien remarquer, elle la lira avec le message.

**Les profils** (ADR 0298, depuis 0.6.0) : Teams garde dans le navigateur le profil des personnes croisées (base
`Teams:profiles`). La page le relit au plus toutes les 10 minutes et joint à chaque lot, dans `profiles`, celui des
auteurs et des personnes mentionnées de ses messages : `{id, name, email, title, company, department, tenant, phones,
avatar}` (l'identifiant Teams, le nom, l'e-mail ou à défaut l'identifiant de connexion s'il en a la forme — jamais celui
d'un invité, `…#ext#@…` —, le poste, l'entreprise, le service, l'organisation, trois numéros au plus, et l'empreinte de
sa photo, `avatarETag`, seulement s'il en a une : ADR 0300). Un profil ne part
qu'avec un message de cette personne (ou qui la mentionne) qui part lui-même — jamais pour une conversation exclue, rien
d'appris pendant une pause — et une seule fois tant qu'il ne change pas ; un profil qu'un envoi n'a pas pu joindre (plus
de 200 dans un paquet de l'historique) n'est pas marqué parti, et repartira. Mika en tire son annuaire : le contact de chaque personne, son
organisation, et la même personne reconnue au courrier par son e-mail. Le diagnostic de l'onglet dit combien de
profils il a lus.

**Les photos de profil** (ADR 0300, depuis 0.7.0) : quand un profil vient de partir (donc avec un message qui part :
jamais pour une conversation exclue, rien pendant une pause) et que l'empreinte de sa photo n'est pas déjà partie, le
service demande sa photo à l'onglet Teams (20 à la fois ; sans nouvelles, redemandée 5 min plus tard, six fois au
plus). La page la télécharge par l'adresse que Teams donne lui-même à ses avatars,
`https://<hôte de Teams>/api/mt/part/<région>/beta/users/<toi>/profilepicturev2/<personne>?displayname=…&size=HR64x64&avatarETag=…`,
avec les cookies du navigateur : la base se lit sur un avatar déjà affiché dans la page (sur son origine, et pour toi
seulement), et aucune autre adresse n'est jamais ouverte (`lib/page.js`, `avatarBase`, `photoUrl`). 64 px, 64 Ko au
plus, JPEG, PNG ou WebP. Le service ne l'envoie que si elle a été demandée, à cette empreinte, hors pause :
`POST /api/teams/photo` (`{person, etag, type, data}`, `data` en base64, sous la clé du compte) — 202 (gardée), 404
(une personne que Mika ne connaît pas, ou plus, ou une autre empreinte que celle de son profil) et 400 (pas une photo
de ce type) la règlent pour cette empreinte ; une coupure, un 403, un 429 ou un 5xx la font redemander (trois fois).
Une photo ne part qu'une fois par empreinte ; charger l'historique les renvoie toutes (comme les profils). Les images
de groupe ne partent pas encore.

Un message vu **sans sa conversation** (Teams diffuse parfois ainsi un message qu'on vient d'envoyer, puis complet)
n'est ni passé ni noté comme vu : sa version complète passe.

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

Tant qu'un onglet Teams est ouvert, l'extension tient une **connexion en direct** avec Mika (`/api/teams/live`, une
WebSocket, ADR 0251) : la clé part dans le premier message, jamais dans l'adresse, et Mika pousse sa boîte d'envoi dès
qu'elle change — ce qu'elle écrit est dans Teams dans la seconde. Ses signes de vie (toutes les 20 s, des deux côtés)
gardent le service de l'extension éveillé ; coupée, la connexion reprend de plus en plus espacée (2 s à 1 min), et
ce délai ne repart à 2 s qu'à la première boîte reçue (Mika accepte chaque connexion avant de la refuser).

Le protocole de `/api/teams/live` : l'extension se présente dans les 10 s par un premier message `hello`, sa clé dans
le champ `key` ; admise comme un relevé (la clé, l'état de Teams et du compte, la cadence), elle reçoit aussitôt
`{"type": "outbox", "items": […]}` — les éléments tels que les rend `GET /api/teams/outbox` —, puis la même trame à
chaque changement de la boîte (relue chaque seconde, la clé revérifiée), et `{"type": "ping"}` après 20 s sans
changement. Ce qu'elle envoie ensuite (ses signes de vie) est lu et ignoré ; les issues restent en HTTP. Mika ferme
en 4400 (rien de lisible), 4401 (clé refusée, ou retirée en cours de route), 4403 (une page web, Teams ou ce compte
coupés), 4404 (pas de Teams), 4408 (pas présentée à temps), 4409 (remplacée : au-delà de 4 connexions d'une clé, la
plus ancienne cède sa place) ou 4429 (trop d'échecs, ou trop de connexions pas encore présentées, de cette adresse).
Chaque refus accepte d'abord la connexion, pour que son code arrive au navigateur. Après 4401, 4403, 4404 ou 4409,
l'extension n'y revient qu'une minute plus tard.
Toutes les 30 s, et juste après chaque envoi, l'extension relève aussi la boîte d'envoi de Mika
(`GET /api/teams/outbox`) — le filet si la connexion tombe — et lui rend chaque issue sûre (`POST /api/teams/outbox/<id>` : placé, envoyé, ou échec avec
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
la première de ces trois voies qui s'offre, toutes avec le même identifiant client, tiré de l'identifiant de l'élément
(le même à chaque tentative : Teams reconnaît un message à lui) :

1. **Le worker de Teams** (ADR 0301, depuis 0.8.0), pour un tête-à-tête (`…@unq.gbl.spaces`) ou un groupe
   (`…@thread.v2`) — pas un canal (`@thread.tacv2`, `@thread.skype`), pas une réunion (`19:meeting_…`) : **la
   conversation n'a pas besoin d'être ouverte**. La page passe à son worker des commandes GraphQL en texte JSON ;
   envoyer, c'est `mutation autoSendMessage`. L'extension rejoue cette commande d'après un **modèle** capté lors d'un
   vrai envoi dans la page, texte, conversation, identifiants et heure refaits, et le worker envoie lui-même, avec sa
   propre connexion : aucun jeton n'est jamais lu ni touché. Il faut donc qu'un message soit parti **une fois** de la
   page (à la main, ou par la zone de saisie) depuis l'installation de 0.8.0 : le modèle est gardé par le service et
   survit aux rechargements. Un modèle de tête-à-tête et un de groupe, le plus récent de chacun ; à défaut, l'autre
   sert. Puis la réponse du worker est attendue 10 s.
2. **Le service de chat** du client Teams, avec l'authentification que le client utilise lui-même pour ses propres
   requêtes (l'extension la voit passer, sur un hôte de Teams seulement, et la garde dans la mémoire de l'onglet : elle
   n'est jamais transmise, ni à l'extension, ni à Mika, ni journalisée), 20 s au plus. Le Teams d'aujourd'hui fait ces
   requêtes dans son worker : l'authentification n'y est presque jamais vue.
3. **La zone de saisie** de la conversation ouverte : le texte y est placé puis envoyé (bouton « Envoyer »).

On ne passe à la voie suivante, dans la même tentative, que sur un « rien n'est parti » sûr : pour le worker, une
erreur explicite (un `status` d'échec, ou `response.errors` sans résultat) — l'élément ne repasse alors plus par le
worker dans cet onglet ; pour le service de chat, un 401 ou un 403. Le worker **muet** 10 s, ou qui répond avec des
erreurs **et** un résultat : le message est peut-être parti, l'issue est douteuse, et rien n'est renvoyé — jamais deux
envois. Une conversation pas ouverte, quand il ne reste que la zone de saisie : « rien n'a commencé » (on réessaie
plus loin).

Cette première voie repose sur le fonctionnement interne de Teams, que Microsoft change sans prévenir : une mise à jour
peut la casser. Une commande d'une autre forme n'est pas prise pour modèle (le diagnostic dit pourquoi), un worker qui
refuse passe la main, un worker qui se tait laisse l'issue douteuse ; la zone de saisie reste la voie sûre, et le
journal de l'extension dit par où chaque envoi est parti.

Une issue n'est dite que si elle est **sûre** :

- **envoyé** : le worker de Teams a répondu `success` sans erreur, le service de chat a répondu 2xx, ou la zone de
  saisie s'est vidée après « Envoyer » ;
- **échec** : rien n'est parti — le service a refusé le message (une 4xx autre que 408 et 429 ; un 401 ou un 403,
  l'authentification périmée, passe la main à la zone de saisie), la conversation est exclue, ou l'échéance est
  passée sans que l'envoi ait pu commencer ;
- **rien n'a commencé** (pas d'onglet Teams, onglet sans le script, page qui n'a pas pris la demande, conversation pas
  ouverte, zone de saisie occupée) : ce navigateur garde la réclamation et réessaie 4 s plus tard, six fois au plus
  (un onglet qui se charge, une zone de saisie pas encore là), puis à la relève suivante ;
- **douteux** (le worker de Teams muet 10 s, ou qui répond avec des erreurs et un résultat ; 5xx, 408, 429, coupure,
  plus de 20 s ; texte resté dans la zone de saisie ; onglet fermé ou muet après avoir pris la demande — 45 s —,
  service arrêté au milieu) : ni dit à Mika, ni **jamais** retenté. Mika le tranche elle-même :
  « envoyé » si ton message apparaît dans la conversation, « échec incertain » à l'échéance. Le journal de
  l'extension le note « issue incertaine ».

Un même onglet ne commence jamais deux fois l'envoi d'un même élément.

La fenêtre de l'extension montre ce qui attend (avec un bouton « Ouvrir dans Teams ») et les 30 dernières issues,
avec 120 caractères du texte au plus.

## Ce qui part où

- Le texte des messages va de l'onglet Teams au serveur de Mika (local par défaut). De là, quand elle les lit, il
  part chez le **fournisseur du modèle** qu'elle utilise (Ollama Cloud, l'API Claude…), comme tout ce qu'elle lit.
- Le profil des personnes dont un message part (voir plus haut) va au même serveur, et leur photo de profil (64 px).
- Dans le navigateur, l'extension garde (`chrome.storage.local`) la clé, les messages en attente d'envoi, les
  identifiants déjà vus et leur dernière version (24 heures), les profils des personnes (3000 au plus) et l'empreinte de
  ceux déjà partis, l'empreinte des photos parties et celles à demander (jamais leurs octets), ce que Mika veut écrire
  et ce qui en est advenu (les 30 dernières issues ; le bouton « Effacer » les retire), et le modèle d'envoi par le
  worker de Teams (une commande sans texte, sans conversation, sans identifiant : ADR 0301). Ce modèle ne quitte
  jamais le navigateur.
- L'authentification du service de chat de Teams ne quitte jamais l'onglet.

Si c'est le Teams de ton travail, ce sont des échanges internes, et les messages de tes collègues, qui sortent de
l'entreprise vers un système personnel et vers un fournisseur de modèle ; et ce sont des messages écrits par une IA
qui partent en ton nom. Vérifie ce que la charte informatique en dit.

## Comment elle capte, comment elle écrit

`page/capture.js` est chargé **dans** la page (monde `MAIN`), avant le client Teams. Pour lire, il a trois sources
(ADR 0251) :

- **le worker de Teams** : le Teams d'aujourd'hui fait vivre son service de chat, sa connexion en direct et sa base
  dans un worker (`precompiled-web-worker`) ; la page n'en voit que les réponses JSON qu'il lui passe, où un message
  passe dès qu'il arrive. `Worker` est enveloppé comme `WebSocket` : chaque réponse qui parle d'un message
  (`"content"` et `"messagetype"`, 2 Mo au plus) est lue, et une synchro ciblée suit ;
- **la base IndexedDB du client**, par **synchro ciblée** : les fiches de conversation (le magasin `conversations`,
  quelques centaines) sont relues à chaque signe — le worker parle d'un message, le titre de l'onglet change (il
  compte les non-lus) — et toutes les 5 s sinon ; pour chaque conversation dont la fiche a bougé
  (`P.conversationMarker`), seuls ses fils livrés depuis son **curseur** (moins une minute de recouvrement) sont relus,
  par l'index `latestDeliveryTimeByConversationId` de `replychains`. Une conversation sans curseur est relue sur 24 h.
  Les curseurs (le plus tard livré qu'on ait lu, la marque de la fiche) sont gardés par le service : un onglet rouvert
  ne relit que ce qui a changé depuis ; ils ne partent qu'avec le dernier lot qu'ils couvrent. Une fiche en avance sur
  ses fils (Teams les range en deux fois) est retentée pendant 45 s avant d'en prendre la marque. Le recouvrement
  grandit avec le temps écoulé depuis la dernière synchro (une veille, des fils remplis après coup). Les fiches passent
  de la plus active à la moins active ; un tour lit au moins une fiche et dure 1,5 s au plus ; le reste passe au tour
  suivant. Un lot que le service n'a pas reçu fait reprendre à la page les curseurs du service : un curseur ne
  passe jamais devant un lot perdu (le relais fait partir les lots l'un après l'autre). Les bases sont ouvertes sans version et refermées aussitôt : l'extension
  n'en crée et n'en modifie aucune ;
- **le réseau** : les réponses JSON (`fetch`, `XMLHttpRequest`) dont l'adresse ressemble au service de chat, et
  les trames des WebSockets de la page (2 Mo au plus, lues après que Teams a traité l'événement ;
  `socket.constructor === WebSocket` reste vrai pour le client) — le Teams d'aujourd'hui n'y passe plus ses messages.

Ce qui est capté part au service de l'extension 300 ms plus tard, et à Mika 400 ms après.

**L'historique** (Réglages › L'historique › « Charger tout l'historique », pour une première mise en service) :
l'onglet lit toute sa base, conversation par conversation — celles des fiches et celles qui n'ont que des fils —,
par pages de 200 fils (une transaction chacune : Teams écrit entre deux), en garde les 1 000 messages les plus récents
de chacune (Mika n'en garde pas plus) et les envoie au service par paquets de 150, chacun attendu avant le suivant
(180 s au plus ; le service s'en donne 120). Le service les trie : les exclusions et toutes les pauses gardées (les 50
dernières, quel que soit leur âge) valent toujours, et une conversation qu'on ne sait pas nommer ne part pas s'il y a
des exclusions ; ni fenêtre de 24 h, ni « avant l'activation », ni « déjà vu ». Il les range chez Mika marqués
`history` : ce qui a plus de 24 h, elle le garde déjà lu, sans le prendre pour du neuf. Une pause prise en route
arrête le chargement. Chaque chargement a son identifiant : les paquets d'un chargement d'avant ne comptent plus. Sans
nouvelles depuis 3 min (l'onglet fermé en route), il est tenu pour interrompu et peut être relancé. Le service n'en garde rien que ses comptes. Le relancer ne range rien deux fois : Mika reconnaît
un message à son identifiant, et le même message sous un autre (sa version en attente, une empreinte) est écarté
comme doublon.

Les deux sources sont dédoublonnées par **version** : l'identifiant du message, un condensé de son texte et, quand la
source les dit, de ses réactions (ADR 0300 ; sans réactions dites, la clé d'avant). Un message modifié, ou dont les
réactions ont changé, repasse ; une version plus ancienne qu'une déjà vue (un cache en retard) ne revient pas, ni le
texte d'un message déjà vu supprimé. Une clé déjà passée ne repasse que comme une version plus récente que toutes
celles vues (`version` avance quand une réaction change) : une réaction retirée, et le message redevient tel qu'il
était, repart quand même ; sans version dite, on ne saurait pas trancher, il ne repart pas. Le service garde la plus
récente version vue de chaque message (`ranks`, 24 h) pour juger de même.

`lib/extract.js` reconnaît un message à sa **forme**, et non à une adresse : un contenu, une date, et un type, un
auteur ou une conversation. C'est la forme des messages du service de chat, stable depuis Skype. Les frappes en
cours, l'activité du fil et les appels sont écartés ; un message supprimé devient une suppression. Le HTML est lu
sans `DOMParser`, que les Trusted Types de la page interdisent.

Pour écrire (`lib/page.js` pour ce qui se calcule sans la page) :

- la **conversation ouverte** se lit dans l'historique de navigation que Teams range dans le `sessionStorage`
  (`tmp.session.<uuid>-mainWindowNavHistory`, l'entrée courante, `activeEntities.mainEntity.id`), sinon dans
  l'adresse de la page ;
- la **zone de saisie** est le premier élément visible parmi `[data-tid="ckeditor"][contenteditable="true"]`,
  `[data-tid*="ckeditor"][contenteditable="true"]` et `div[role="textbox"][contenteditable="true"]`. C'est un
  CKEditor 5, dont la page pose l'instance sur l'élément (`ckeditorInstance`) : le texte entre dans son modèle, là où
  Teams lit ce qu'il envoie, par ses commandes (`insertText`, `shiftEnter` entre deux lignes), la sélection d'abord
  mise en fin de texte, une commande à la fois ; vide ou pas se lit dans ce modèle (`getData()`). Une frappe simulée
  (`document.execCommand("insertText")`) n'y entrait pas toujours : le texte s'affichait, l'éditeur le redessinait
  vide au clic sur Envoyer, rien ne partait, et la zone vidée passait pour un envoi. Elle ne sert plus qu'à un éditeur
  sans instance connue (jamais `innerHTML`, que les Trusted Types interdisent). Le bouton est
  `[data-tid="sendMessageCommands-send"]` (puis `newMessageCommands-send`, `button[name="send"]`) ; le journal de
  l'extension dit par où chaque envoi est parti ;
- l'**envoi par le worker de Teams** (ADR 0301) : `Worker.prototype.postMessage` est enveloppé — ce que la page passe
  à un worker de Teams (pas celui de la télémétrie) part tel quel, par le même appel. Au passage, une commande en texte
  JSON est lue sans être décodée (`P.workerCommandHead`) : le worker qui la reçoit, le plus haut numéro de requête vu,
  `rendererId` et `windowId`. Une commande `autoSendMessage` est décodée hors de l'appel de la page et donne le
  **modèle** (`P.workerSendTemplate`) : `content` vide, les listes de `computed` (mentions, liens…) vidées, `convId`,
  `originalConvId`, `correlationId`, `clientMessageId`, `actionId`, `originalSendPipelineTime` effacés, la file
  d'attente réduite à son préfixe (`<préfixe>_{mika:conversation}`), sans `requestId`, `rendererId` ni `windowId` ;
  la conversation ailleurs dans la commande devient une marque, et ce qui en reprend le texte est vidé. Elle est
  écartée si ce n'est pas une création (`action: "Create"`), si ce n'est ni un tête-à-tête ni un groupe, si le message
  porte une citation, un transfert, une pièce jointe, des données jointes, ou s'il reste une trace du message. Le modèle
  retient aussi la forme du contenu (les balises autour du texte, comme `<p><semantic-object>`…, et `<br>` ou un `<p>`
  par ligne ; sans attribut qui agisse ou porte un identifiant ; à défaut `<p>`, des `<br>`). Le relais le revérifie
  (demande `sendTemplate`), le service le garde, et le rend à l'onglet suivant (`sendTemplates`). Pour envoyer,
  `P.workerSendCommand` refait la commande : la conversation, `originalConvId`, `isBilateralChat` (la conversation finit
  par `@unq.gbl.spaces`), la file `<préfixe>_<conversation>`, `actionId` = `send_<clientMessageId>`, un
  `correlationId` neuf, l'heure, le texte échappé dans la forme lue, `requestId` = `m-<n>` avec `n` mille au-dessus du
  compteur de la page (jamais le numéro d'une requête en cours de la page) et au-dessus de notre dernière, `rendererId`
  et `windowId` de la page vivante. Elle part en texte JSON (un objet est ignoré) par le `postMessage` d'origine ; la
  réponse est celle qui porte ce `requestId` (`P.workerReplyOutcome`) ;
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
d'emoji seule faisait refuser un lot entier) ; le relais seul a sa copie de `cut`. Chrome n'injecte un même fichier
qu'une fois par cadre, quel que soit le monde : `lib/text.js`, chargé dans la page, ne l'était jamais dans le relais,
et chaque lot capté y tombait sans bruit. La page et le relais ne partagent donc aucun fichier
(`tests/relay.test.js` le garde, et fait tourner le relais seul, comme Chrome le charge). Tout l'état vit dans `chrome.storage.local` (sans plafond de taille,
`unlimitedStorage`), parce qu'un service MV3 peut être arrêté à tout moment.

### Limites

L'envoi par le worker de Teams a été **sondé à la main** sur le vrai Teams (2026-11-22 : une commande rejouée en
texte JSON est partie dans une conversation fermée), mais le code de 0.8.0 n'y a pas encore tourné : la forme exacte
du modèle et de la réponse du worker sont à confirmer au premier essai. Le reste du chemin d'écriture (zone de saisie,
historique de navigation, service de chat) a été éprouvé sur une page de banc et dans Teams pour la zone de saisie ;
les sélecteurs de la zone et du bouton « Envoyer », et la requête au service de chat, restent à calibrer si Teams
change.

### Quand Teams change

Microsoft modifie son client sans prévenir. Si plus rien n'arrive, ou que Mika n'arrive plus à écrire, ouvre
**Diagnostic de l'onglet Teams** :

- le worker de Teams : écouté ou non, ses réponses, celles qui parlaient d'un message, les messages qu'on en a tirés ;
- la base locale : les synchros, leur durée, les conversations suivies, celles relues de façon ciblée, les messages ;
- les réponses et trames lues côté réseau, et les messages qu'on en a tirés ;
- si ton identité a été trouvée (pour reconnaître tes propres messages et les mentions) ;
- les photos de profil : demandées, téléchargées, envoyées, écartées, en échec — et combien de fois aucun avatar n'était
  encore affiché dans l'onglet (sans lui, la page ne sait pas l'adresse des photos : ouvrir la liste des conversations) ;
- **zone de saisie trouvée**, **conversation active connue**, **envoi par le worker de Teams possible** (oui ou non,
  et la date du modèle : sans modèle, envoyer une fois un message à la main ; sans commande vue de la page à son
  worker, l'onglet vient de s'ouvrir), **envoi par le service de chat possible** (oui ou non : l'existence de
  l'en-tête, jamais sa valeur), et ce qui a été placé ou envoyé depuis l'ouverture de l'onglet, par quelle voie ;
- les commandes de la page à son worker : combien, combien d'envois lus comme modèle, combien écartés et pourquoi (le
  dernier), et, pour l'envoi par le worker, les refus (passés à la voie suivante), les silences (issue douteuse) et les
  réponses arrivées trop tard. La fenêtre de l'extension dit aussi, hors diagnostic, si l'envoi sans ouvrir la
  conversation est possible et depuis quand.

Le diagnostic ne montre aucun contenu. Si le réseau et la base locale ne donnent plus rien, c'est le format des
messages qui a changé : c'est `lib/extract.js` qu'il faut adapter. Si la zone de saisie ou la conversation active ne
sont plus trouvées, ce sont les sélecteurs de `page/capture.js` ou la lecture de l'historique dans `lib/page.js`. Si les
envois de la page ne donnent plus de modèle, ou que le worker refuse ou se tait, c'est la commande `autoSendMessage`
qui a changé : `P.workerSendTemplate` et `P.workerSendCommand` dans `lib/page.js` ; d'ici là, tout part par la zone de
saisie.

## Tests

```bash
cd frontend/Extension && npm test     # node --test, sans dépendance
```

Ils couvrent la coupe des textes (un emoji à la frontière, une moitié de paire déjà seule) et les versions d'un
message (modification, cache en retard, texte après suppression) ; la reconnaissance des messages (réponse du service
de chat, trame du WebSocket, enregistrement de la base locale, pièce jointe, suppression, modification, HTML d'une
réponse citée ; les réactions sous leurs deux formes, leur compte seul, rien de dit ou aucune ; l'empreinte d'une photo
de profil) ; ce qui part (nouveauté, pause jugée à l'heure du message et intervalles bornés, exclusion par le nom,
l'identifiant ou la personne, retenue le temps d'apprendre un nom, déjà vu, conversation inconnue, soi exact, les deux
voix et la mention, lots coupés sous 200 messages, 200 conversations et 512 Kio comptés en octets, recoupe après un
413, nom appris après coup, Retry-After, attente croissante, erreurs 5xx comptées, adresse https hors de cette
machine, IPv6 entre crochets et `[::1]` local) ; la boîte d'envoi (un brouillon placé une seule fois même si la liste du serveur est en retard ou après un
redémarrage, un placement refusé qui redevient possible, échéance et exclusion dites en échec, réclamation accordée,
prise ailleurs ou sans réponse, un envoi marqué avant de partir et jamais refait, « rien n'a commencé » qui garde la
réclamation, envoi douteux ou interrompu ni dit ni retenté, issues gardées quand le serveur ne liste plus l'élément,
réponses 404/409/4xx/429/5xx aux issues et abandon après 10 refus, issue sans texte, journal borné à 120 caractères) ;
et ce que lit la page (en-têtes d'authentification en `Headers`, en liste ou en objet, base du service de chat et
hôtes de Teams seulement, échappement HTML du corps d'envoi, identifiant client stable, réponse du service de chat
sûre ou douteuse, conversation ouverte dans un historique de navigation de formes diverses ou dans l'adresse ; la
marque d'une fiche de conversation, ce qu'il faut relire et depuis quand, un curseur qui n'avance jamais en arrière).
`tests/relay.test.js` fait tourner le relais seul, comme Chrome le charge (sources, curseurs, demandes au service,
l'ordre de l'historique) ; `tests/background.test.js` fait tourner le service tel quel avec de fausses API de Chrome,
`fetch` et `WebSocket` (curseurs gardés et rendus, historique marqué et trié, refus de Mika, la boîte poussée en
direct traitée sans relevé, la connexion fermée en pause ou sans clé, un message qui repart quand ses réactions
changent, une photo demandée puis envoyée une fois par empreinte, jamais pour une conversation exclue ni en pause) ;
`tests/reactions.test.js` garde les réactions (lecture, clé de version, ce qui part) et `tests/page.test.js` l'adresse
d'une photo de profil. L'envoi par le worker de Teams (ADR 0301) : `tests/worker-send.test.js` garde le modèle (rien du
message n'y reste, les refus), la commande refaite (texte JSON, conversation, tête-à-tête ou groupe, file, identifiants,
heure, texte échappé ligne à ligne dans la forme lue, numéro de requête), le début d'une commande et la réponse du
worker ; `tests/capture.test.js` fait tourner le script de la page tel quel avec un faux `Worker` (la commande de la
page passe telle quelle, son modèle part sans rien du message, l'envoi par le worker et sa réponse, le silence douteux
jamais renvoyé, le refus qui passe à la voie suivante, canaux et réunions, le modèle rendu après un rechargement) ; le
relais et le service gardent le modèle vérifié (`tests/relay.test.js`, `tests/background.test.js`).
