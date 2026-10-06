# Le protocole du chat — `/ws`

Ce document est pour qui écrit un client de conversation : le frontend web, l'application Android
(`frontend/Android/`), un client natif quelconque. Les décisions et leurs raisons sont dans les ADR
[0038](adr/0038-les-bords.md), [0051](adr/0051-l-adaptateur-du-monde.md), [0056](adr/0056-le-fil-le-chat-et-ce-que-voit-la-personne.md)
et [0062](adr/0062-l-application-mobile-une-messagerie-et-des-fichiers.md) ; le code fait foi dans
[`adapters/web/app.py`](../src/mika/adapters/web/app.py) (routes, session), [`adapters/web/protocol.py`](../src/mika/adapters/web/protocol.py)
(trames, limites) et [`adapters/web/hub.py`](../src/mika/adapters/web/hub.py) (qui reçoit quoi). Le monde 3D a son
propre protocole : [`protocole-monde.md`](protocole-monde.md).

## 1. S'authentifier

Il n'y a pas de conversation anonyme : `serve` exige un compte. Deux chemins, selon ce qu'est le client.

**Un navigateur** a une session :

1. `GET /auth/whoami` plante le cookie lisible `csrftoken` et dit `{authenticated, auth_required, needs_bootstrap}`
   (plus `username`, `display_name`, `person_id`, `operator` une fois connecté).
2. `POST /auth/login {username, password}` avec l'en-tête `X-CSRFToken` (la valeur du cookie) : cookie `sessionid`
   (`HttpOnly`, 14 jours). `POST /auth/bootstrap` crée le premier compte (opérateur) tant qu'il n'en existe aucun.
3. `/ws` s'ouvre avec le cookie, depuis une origine déclarée (`--origin`) ; une origine inconnue est refusée avant
   l'ouverture (le client voit un échec de poignée de main, HTTP 403).
4. Déconnexion : `GET` ou `POST /auth/logout` avec l'en-tête CSRF.

**Un client natif** (application mobile, moteur de jeu) n'a ni cookie ni `Origin` : il présente un jeton porteur,
`Authorization: Bearer mw_…`, **toujours sans en-tête `Origin`** (avec une, seule la session compte et le jeton est
ignoré).

- `POST /auth/token` :

  ```json
  {"username": "bea", "password": "…", "label": "Android · Google Pixel 8", "client": "mobile"}
  ```

  `client` : `mobile` pour une application qui reçoit hors ligne (une messagerie : Mika peut y écrire à la
  personne absente), `screen` (le défaut) pour un écran ou un moteur. Réponse 200, `Cache-Control: no-store` :

  ```json
  {"token": "mw_…", "token_id": 12, "client": "mobile", "authenticated": true, "auth_required": true,
   "needs_bootstrap": false, "username": "bea", "display_name": "Béa", "person_id": "user_3", "operator": false}
  ```

  Le jeton n'est montré qu'une fois : garde-le chiffré. Erreurs `{"error": "…"}` en français : 400 (champ manquant,
  `client` inconnu), 401 (identifiants invalides), 403 (une `Origin` : un navigateur), 429 avec `Retry-After`
  (les échecs comptent avec ceux de `/auth/login` : 5 par nom et adresse, 20 par adresse, par minute). Un serveur
  plus ancien répond 404.
- `GET /auth/whoami` avec le jeton : les mêmes champs, plus `client` et `token_id` ; `authenticated: false` pour un
  jeton inconnu ou révoqué.
- `DELETE /auth/token` avec le jeton : il ne vaut plus rien, ses connexions se ferment en 4401 → `{"ok": true}` ;
  401 pour un jeton déjà invalide.
- Un jeton dure jusqu'à ce qu'on le rende, qu'un opérateur le révoque (Console › Comptes, ou
  `mika token revoke <id>`), ou — pour un jeton obtenu par mot de passe — que le mot de passe change ou que le
  compte soit désactivé. Au-delà de dix jetons obtenus par connexion, le moins récemment utilisé est révoqué.
- `mika token create <compte> --client mobile|screen --label …` en donne un sans mot de passe (serveur arrêté).

## 2. Ouvrir la connexion

`ws(s)://<serveur>/ws`. En-têtes d'un client natif :

| En-tête | Valeur | Rôle |
|---|---|---|
| `Authorization` | `Bearer mw_…` | le compte |
| `X-Mika-Presence` | `here` (défaut) ou `away` | quelqu'un regarde-t-il l'écran ? |

**Présente** (`here`, ou rien) : le serveur annonce la personne et envoie de lui-même, dans l'ordre, un `history`
`initial` (les 50 derniers messages), un `emotion_update` et un `inner_state_update`. Le client envoie ensuite
`sync` seulement s'il a déjà un curseur.

**Absente** (`away` : l'application en arrière-plan, qui ne fait que recevoir) : personne n'est annoncé, rien n'est
envoyé de lui-même — ni fil, ni visage, ni panneau. Le client envoie **toujours** `sync` (son curseur, ou `0`). Ce
qui est adressé à la personne arrive quand même (sa parole, les accusés, les rattrapages), sans voix.

Fermetures :

| Code | Sens | Que faire |
|---|---|---|
| 4401 | jeton ou session invalide, révoqué, ou droits changés | ne pas réessayer en boucle : `GET /auth/whoami` avec le jeton ; `authenticated: false` → écran de connexion ; `true` → se reconnecter |
| 1008 / poignée de main 403 | origine refusée (un navigateur), ou pas d'authentification | terminal |
| 1009 | trame trop grande | — |
| autre | réseau | se reconnecter (attente 1 s × 1,5, plafonnée à 30 s, remise à zéro à l'ouverture) |

Une connexion silencieuse peut être morte sans le dire (un portable en veille, un mandataire) : le client envoie
`ping` toutes les 20 s et se reconnecte quand ses pings restent sans réponse — deux pongs manqués, soit 50 s sans
**aucune** trame reçue au premier plan. Le client web juge sur le ping et non sur le silence (un ping parti depuis
plus de 30 s sans qu'aucune trame l'ait suivi) : un onglet caché, que le navigateur ne réveille plus qu'une fois par
minute et à qui rien n'arrive de lui-même, reçoit son `pong` et n'est pas coupé pour son seul silence. Un `pong` ne
double pas une trame en cours de montée (un `chat` et ses fichiers, sur des données mobiles) : tant qu'il reste des
octets à envoyer, ce silence ne prouve rien — le client web compte le délai du ping depuis le moment où son tampon
s'est vidé, et l'application Android ne le compte qu'une fois sa montée achevée. Le serveur laisse de même environ
cinq minutes au pong de ses propres pings WebSocket avant de fermer (1011).

## 3. Ce que le client envoie

| Trame | Champs | Notes |
|---|---|---|
| `ping` | `t` (libre, d'ordinaire l'heure en ms) | → `pong` avec le même `t` ; jamais mise en file |
| `sync` | `after_id` | le plus grand identifiant de message **affiché** ; `0` = rien de fiable → les 50 derniers |
| `chat` | `message`, `client_msg_id`, `attachments?` | voir ci-dessous |
| `presence` | `here` (booléen) | l'application passe au premier plan (`true`) ou le quitte (`false`) |
| `composing` | `on` (booléen) | la personne commence à écrire un message (`true`) ou cesse (`false`) ; authentifié seulement |
| `read` | `up_to` (un identifiant de message) | jusqu'où la personne a lu son fil, si elle l'a permis ; authentifié seulement |
| `approval` | `id`, `decision` (`accept` \| `refuse`), `digest` | décider d'une carte d'accord (§4, `approvals`) ; authentifié seulement |

`chat` :

```json
{"type": "chat", "message": "regarde ça", "client_msg_id": "c1mx3k2-7",
 "attachments": [{"name": "photo.jpg", "type": "image/jpeg", "data": "<base64>"}]}
```

- `message` : 2 000 caractères au plus (`too_long` au-delà : jamais coupé en silence).
- `client_msg_id` : 64 caractères au plus ; le serveur dédoublonne par lui (un renvoi après une coupure rend
  `accepted` et ne produit pas de seconde réponse). Renvoie tout message non accusé à la reconnexion, sans en garder
  plus de 4 en vol sans accusé (chaque accusé fait partir le suivant) : une file vidée d'un bloc dépasse la limite
  ci-dessous.
- `attachments` (clé absente s'il n'y en a pas) : 5 au plus, 5 Mio chacun ; `data` en base64 **sans retour à la
  ligne** (le serveur décode strictement ; un préfixe `data:…;base64,` est toléré). Les images sont décrites, l'audio
  transcrit, les documents lus ; les octets ne sont jamais gardés. Une trame entière ne dépasse pas ~34 Mio (et
  OkHttp n'en envoie pas plus de 16 Mio d'un coup).
- Débit : 20 `chat` par 10 s ; `sync` et `identify` 12 par 10 s (au-delà, ignorés). Au plus 8 `chat` en attente
  sur une connexion, comptés à la réception : au-delà, `overloaded` — les derniers d'une rafale, jamais les premiers.

`presence` : revenir vaut tout de suite (la personne est là ; un visage et un panneau frais suivent) ; partir vaut
après 20 s (prendre une photo et revenir n'écrit rien). 6 écritures au journal par minute et par connexion au plus ;
au-delà, le dernier état voulu s'applique dès que la fenêtre le permet. Sans effet sur une connexion anonyme.

`composing` : le début et la fin d'une saisie, jamais une frappe. `true` au premier caractère d'un message ;
`false` quand le champ est vidé ou après 6 s sans frappe. L'envoi (`chat`) clôt la saisie de lui-même : rien à
envoyer de plus (le prochain caractère redit `true`). Seulement sur une transition, jamais en file ; sans effet sur
une connexion anonyme ou ouverte en arrière-plan. Tant que la personne écrit, la réponse à son message
d'avant attend la suite (une seule réponse au tour entier) et Mika ne lui écrit pas d'elle-même — au plus 45 s de
saisie continue : au-delà, le serveur tient lui-même la saisie pour finie. Aucune trame en retour, et rien ne
s'affiche (pas de « Mika voit que tu écris »). 12 écritures au journal par minute et par connexion au plus ; au-delà,
le dernier état voulu s'applique dès que la fenêtre le permet.

`read` : « lu jusqu'ici », le plus grand identifiant de message que la personne a vu (la conversation à l'écran, ou
« Marquer comme lu » sur une notification) — une seule valeur, jamais l'heure où l'on est en ligne ni le temps passé
à l'écran. Un client ne l'envoie que si la personne l'a permis (« Lui dire quand j'ai lu », activé par défaut) :
coupé, rien ne part. Il envoie la dernière valeur à l'ouverture (après `sync`) et à chaque avance, jamais en file.
Le serveur ignore une valeur qui n'avance pas ce qu'il sait déjà de ce compte, ou qui n'est pas dans son fil ; la
trame compte dans le débit de `sync`, et s'écrit au journal 6 fois par minute et par connexion au plus (au-delà, la
dernière valeur voulue s'applique dès que la fenêtre le permet). Mika sait alors si ce qu'elle a écrit d'elle-même
a été vu : par messagerie, un message pas encore lu ne la fait pas se sentir ignorée (trois jours au plus), et le
délai de réponse qu'elle attend court à partir de la lecture.

`identify` ne sert plus : une connexion authentifiée l'ignore, l'identité vient de la session ou du jeton.

`approval` (ADR 0064) : `digest` est **celui de la carte affichée** — le serveur refuse un accord sur autre chose que
ce qui a été montré (`changed`). Refuser n'exige pas d'empreinte. Compte dans le débit de `sync` (12 par 10 s).

## 4. Ce que le serveur envoie

**`ack`** — le sort d'un message, une fois par message (deux pour `no_reply`) :

```json
{"type": "ack", "client_msg_id": "c1mx3k2-7", "status": "accepted",
 "rejected_attachments": [{"name": "film.mp4", "reason": "too_large"}]}
```

| `status` | Sens |
|---|---|
| `accepted` | reçu (y compris un renvoi) |
| `rate_limited`, `overloaded` | non reçu : trop vite, ou trop de messages en attente sur cette connexion |
| `too_long`, `empty`, `attachments_rejected` | non reçu : le message lui-même (`rejected_attachments[].reason` : `too_many`, `too_large`, `invalid`) |
| `no_reply` | **second** accusé d'un message reçu : la réponse ne viendra pas ; `reason` : `no_model`, `unreachable`, `timeout`, `too_late`, `error` (et, pour une opératrice, `detail` et `href`) |

Un statut inconnu est un refus. Pour `no_reply`, la bulle reste « envoyée » : une note dit « Mika n'a pas pu
répondre — réessaie ».

**`speech`** — sa parole :

```json
{"type": "speech", "text": "Avec plaisir [LAUGH] !", "emotion": "happy", "emotion_intensity": 0.6,
 "emotion_blend": [{"emotion": "happy", "weight": 0.8}], "emotion_state": {}, "source": "reply",
 "person_id": "user_3", "speak": false, "voice_reason": "…", "voice_persona": "speaking",
 "voice_profile": {"pitch": 1.0, "rate": 1.0, "gain": 1.0},
 "message_id": 812, "user_message_id": 811, "client_msg_id": "c1mx3k2-7",
 "attachments": [{"id": "9f2c…", "name": "courses.md", "kind": "file", "mime": "text/markdown", "size": 312,
                  "url": "/files/9f2c…", "available": true}]}
```

- `text` porte des jetons de voix (`[SIGH]`, `[LAUGH]`, `[BREATH]`, `[PAUSE:400]`) : un client sans voix les retire.
- Texte vide : elle a choisi de ne pas répondre — sauf `voice_reason: "asleep"` : elle dort, elle répondra à son
  réveil (« Mika dort — elle te répondra à son réveil »).
- `voice_persona: "inner"` : une pensée à voix haute ; `message_id`, `user_message_id` et `client_msg_id` sont nuls,
  elle n'est pas dans le fil. À montrer seulement à l'écran regardé, **jamais en notification** (le serveur ne
  l'envoie d'ailleurs pas à une connexion absente).
- `source: "error"` sans identifiant : un texte de repli, pas une parole d'elle.
- `user_message_id` / `client_msg_id` rattachent la réponse à la question (la bulle reçoit son identifiant).
- `attachments` : les fichiers qu'elle envoie (§6). Toujours présent, souvent vide.
- `speak` n'est vrai que pour un seul écran regardé de la personne (celui qui a demandé, sinon le plus récemment
  actif) ; jamais pour une connexion absente.

**`history`** — un morceau du fil :

```json
{"type": "history", "mode": "catchup", "last_id": 812, "truncated": false, "life": "a41f…", "reset": false,
 "messages": [{"id": 811, "role": "user", "text": "regarde ça", "ts": 1790601612771, "source": "mobile",
               "emotion": "", "emotion_intensity": 0.0, "attachments": [{"name": "photo.jpg", "kind": "image"}]},
              {"id": 812, "role": "assistant", "text": "Avec plaisir !", "ts": 1790601615002, "source": "reply",
               "emotion": "happy", "emotion_intensity": 0.6, "attachments": []}]}
```

- `mode` : `initial` (à l'ouverture, ou `reset`) ou `catchup` (réponse à `sync`, ou les messages d'une rafale et la
  question d'un tour posé d'un autre appareil, juste avant la `speech` qui y répond).
- `ts` en **millisecondes** depuis l'époque Unix.
- `text` d'un message de la personne : ce qu'elle a tapé ; ses fichiers par leur nom et leur sorte (`image`,
  `audio`, `file`). Un message de Mika : sans jetons de voix ; ses fichiers comme dans `speech`.
- `life` : l'empreinte de sa vie (le même journal). Si elle change, ou si `reset` est vrai, vide ce que tu montres
  (sauf tes messages encore en partance) avant de fusionner.
- `truncated` : le rattrapage ne porte que les 200 derniers ; dis-le plutôt que de laisser croire qu'il ne manque
  rien.
- Le curseur est le plus grand `id` **affiché** ; on ordonne par `id`, jamais par `ts`.

**`approvals`** — les cartes d'accord de la personne (ADR 0064) : un appel qu'elle veut faire à un service
extérieur et qui attend **son** accord. La liste entière à chaque changement (et après chaque décision) ; à
l'ouverture, seulement s'il y en a — **pars d'une liste vide à chaque connexion**. Montre exactement la dernière
liste reçue (une carte absente n'attend plus rien) :

```json
{"type": "approvals", "items": [{"id": 905, "title": "Appeler « prevision » (meteo) : {\"ville\": \"Lyon\"}",
  "text": "Service : meteo\nOutil : prevision\nCe qui partira :\n{\n \"ville\": \"Lyon\"\n}",
  "digest": "3f9c…", "blocked": "", "expires_at": 1790602215002}]}
```

- `text` : exactement ce qui partira (à montrer tel quel, en texte brut, jamais interprété).
- `blocked` non vide : ça ne peut pas partir tel quel (l'outil a changé, n'est plus servi, la carte a expiré) — ne
  propose que « refuser ».
- `expires_at` (ms, ou `null`) : passé ce moment, la carte ne vaut plus (le serveur la refuse au nom du délai).
- Une carte n'arrive qu'aux connexions **authentifiées** de la personne qu'elle concerne. Pas de notification
  système pour elle : la parole de Mika qui l'accompagne en fait une.

**`approval_result`** — le sort d'une décision : `{"type": "approval_result", "id": 905, "status": "approved"}` ;
`status` : `approved`, `rejected`, `unknown` (déjà décidée, ou inconnue), `changed` (ce qui partirait a changé :
relis la carte), `blocked`, `expired`, `forbidden` (pas à toi de décider). Une liste `approvals` à jour suit.

**`emotion_update`** (son visage entre deux tours, seulement vers un écran regardé), **`inner_state_update`**
(`{"inner_state": {…}}` : sommeil `sleep_phase`, `energy`, lieu `place`, ce qu'elle y fait `activity`
(`{"name": "draw", "label": "dessiner", "since": …, "until": …}` en millisecondes, `until` nul : jusqu'à ce qu'elle
s'arrête ; `null` : rien ; un client tait un nom qu'il ne connaît pas), `circadian`, besoins `drives`, `estime`,
`identity`, ce qui lui trotte dans la tête `ruminations`, `today_journal` (avec son `title`), `last_dream`,
`self_narrative` ; `projects` pour une propriétaire ; `person_scope: false` = cette trame ne parle de personne, garde
les sections personnelles), **`pong`**.

## 5. Notifier

Pour une application qui reçoit en arrière-plan : notifie une `speech` (ou une ligne `assistant` d'un rattrapage)
quand l'application n'est pas au premier plan, que `voice_persona` vaut `speaking`, que `message_id` n'est pas nul,
que le texte n'est pas vide, que l'identifiant dépasse le dernier lu ou notifié, et qu'elle ne répond pas à une
question posée **d'un autre appareil** (`client_msg_id` qui n'est pas à toi). Ne notifie pas le tout premier fil
reçu (curseur à zéro). Un rattrapage = une seule notification groupée.

Avec un jeton `mobile` vivant, elle peut écrire la première quand tu n'es devant aucun écran (un rappel échu, une
prise de nouvelles) : la parole arrive à la connexion absente, ou attend dans le fil jusqu'au prochain `sync`. Ses
retenues valent toujours (pas de harcèlement, pas la nuit hors rappel).

## 6. Les fichiers qu'elle envoie

Chaque entrée d'`attachments` d'un message de Mika :

| Champ | Sens |
|---|---|
| `id` | 32 caractères hexadécimaux |
| `name`, `mime`, `size` | ce qu'elle a envoyé (`size` en octets) |
| `kind` | `image` ou `file` |
| `url` | `/files/<id>`, relatif au serveur |
| `available` | faux une fois retiré par la rétention (un an, ou au-delà d'un volume par personne) |

Le `mime` est celui qu'elle a déclaré (`text/x-python`, `text/markdown`…) : il sert à choisir l'application qui
l'ouvrira. Les fichiers d'une personne qu'on fait oublier disparaissent avec ses lignes du fil (ils ne sont pas
« retirés » : ils n'existent plus). Une trame sans texte (silence, sommeil, réponse impossible) et une pensée à voix
haute portent `attachments: []`.

`GET /files/<id>` avec le jeton (ou la session d'un navigateur) — seulement pour un fichier parti avec un de ses
messages, dans le fil de ce compte : 200 en pièce jointe
(`Content-Disposition: attachment; filename*=UTF-8''…`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`,
`Content-Security-Policy: sandbox`) ; 404 pour un fichier inconnu **ou** qui n'est pas à toi (la même réponse) ; 410
pour un fichier retiré (ou dont les octets manquent) ; 401 sans compte (y compris un jeton posé à côté d'une
`Origin`, sans cookie) ; 429 au-delà de 60 téléchargements par minute ; un identifiant mal formé, 404 avant même de
regarder le compte. Le type n'est donné que
parmi des types sûrs (texte, Markdown, CSV, JSON, PNG, JPEG, WebP, GIF, PDF) ; sinon `application/octet-stream`.

## 7. Derrière un mandataire

Le mandataire doit laisser passer `Authorization` et `X-Mika-Presence` à la mise à niveau WebSocket, et garder la
connexion au-delà des pings du client (`proxy_read_timeout 120s` chez nginx) : voir
[`deploy/README.md`](../deploy/README.md).
