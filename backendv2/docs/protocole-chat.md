# Le protocole du chat — `/ws`

Ce document est pour qui écrit un client de conversation : le frontend web, l'application Android
(`frontend/Android/`), un client natif quelconque. Les décisions et leurs raisons sont les ADR 0038, 0051, 0056,
0062 et 0077 de [`decisions.md`](decisions.md) ; le code fait foi dans
[`adapters/web/app.py`](../src/mika/adapters/web/app.py) (routes, session), [`adapters/web/protocol.py`](../src/mika/adapters/web/protocol.py)
(trames, limites) et [`adapters/web/hub.py`](../src/mika/adapters/web/hub.py) (qui reçoit quoi). Le monde 3D a son
propre protocole : [`protocole-monde.md`](protocole-monde.md).

## 1. S'authentifier

Il n'y a pas de conversation anonyme : `serve` exige un compte. Deux chemins, selon ce qu'est le client.

**Un navigateur** a une session :

1. `GET /auth/whoami` plante le cookie lisible `csrftoken` et dit `{authenticated, auth_required, needs_bootstrap}`
   (plus `username`, `display_name`, `person_id`, `operator` une fois connecté).
2. `POST /auth/login {username, password}` avec l'en-tête `X-CSRFToken` (la valeur du cookie) : cookie `sessionid`
   (`HttpOnly`, 14 jours). `POST /auth/bootstrap` crée le premier compte (opérateur) tant qu'il n'en existe aucun ;
   depuis une autre machine que celle du serveur, il porte aussi `code`, le code de premier démarrage écrit au
   journal du serveur (`whoami` le dit : `bootstrap_code_required`) — sans lui, 403.
   Ces routes (et `/auth/token`, `/auth/push`, `/api/perceptions`, les décisions) lisent un corps JSON de 64 Kio au
   plus : au-delà, 413.
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
  (les échecs comptent avec ceux de `/auth/login` : 5 par nom et adresse, 20 par adresse, par minute).
- `GET /auth/whoami` avec le jeton : les mêmes champs, plus `client` et `token_id` ; `authenticated: false` pour un
  jeton inconnu ou révoqué.
- `DELETE /auth/token` avec le jeton : il ne vaut plus rien, ses connexions se ferment en 4401 → `{"ok": true}` ;
  401 pour un jeton déjà invalide.
- Un jeton dure jusqu'à ce qu'on le rende ou qu'un opérateur le révoque (Console › Comptes, ou
  `mika token revoke <id>`). Un compte désactivé rend muets tous ses jetons ; un jeton obtenu par mot de passe est en
  plus révoqué quand le mot de passe change ou que le compte est désactivé. Au-delà de dix jetons obtenus par
  connexion, le moins récemment utilisé est révoqué.
- `mika token create <compte> --client mobile|screen --label …` en donne un sans mot de passe (serveur arrêté).
- `POST /auth/push` avec un jeton `mobile` : où notifier le téléphone fermé (§ 5) —

  ```json
  {"token": "<jeton Firebase du téléphone>", "key": "<32 octets, base64>"}
  ```

  → `{"ok": true, "available": true|false}` (`available` : le serveur a une clé Firebase ; sinon rien ne partira),
  `Cache-Control: no-store`. 400 (jeton Firebase manquant ou avec des espaces, clé qui n'est pas 32 octets en
  base64), 401 (jeton invalide), 403 (une `Origin`, ou un jeton `screen`). Redire la même chose ne coûte rien ; un
  même jeton Firebase quitte tout autre jeton de l'application. `DELETE /auth/push` retire l'inscription ; rendre ou
  révoquer le jeton de l'application la retire aussi.

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
qui est adressé à la personne arrive quand même (sa parole, les accusés, les rattrapages), sans voix. L'application
Android n'ouvre une telle connexion que le temps d'envoyer une réponse écrite dans une notification : fermée, elle
ne garde rien d'ouvert, ce qui coûterait cher en batterie, et reçoit par Firebase (§ 5, ADR 0077).

Fermetures :

| Code | Sens | Que faire |
|---|---|---|
| 4401 | jeton ou session invalide, révoqué, ou droits changés | ne pas réessayer en boucle : `GET /auth/whoami` avec le jeton ; `authenticated: false` → écran de connexion ; `true` → se reconnecter |
| poignée de main refusée (HTTP 403) | origine inconnue (un navigateur), ou client natif sans jeton | terminal |
| 1009 | trame trop grande | — |
| autre | réseau | se reconnecter (attente 1 s × 1,5, plafonnée à 30 s, remise à zéro à l'ouverture) |

Une connexion silencieuse peut être morte sans le dire (un portable en veille, un mandataire) : le client envoie
`ping` toutes les 20 s et se reconnecte quand ses pings restent sans réponse — deux pongs manqués, soit 50 s sans
**aucune** trame reçue au premier plan. Deux précautions :

- juger sur le ping, pas sur le silence : un onglet caché, que le navigateur ne réveille plus qu'une fois par
  minute, reçoit son `pong` et ne doit pas être coupé pour son seul silence (le client web coupe quand un ping est
  parti depuis plus de 30 s sans qu'aucune trame l'ait suivi) ;
- compter le délai du ping une fois la montée finie : tant qu'un `chat` et ses fichiers montent (sur des données
  mobiles), le `pong` attend derrière eux et ce silence ne prouve rien.

Le serveur laisse de même environ cinq minutes au pong de ses propres pings WebSocket avant de fermer (1011).

## 3. Ce que le client envoie

| Trame | Champs | Notes |
|---|---|---|
| `ping` | `t` (libre, d'ordinaire l'heure en ms) | → `pong` avec le même `t` ; jamais mise en file |
| `sync` | `after_id` | le plus grand identifiant de message **affiché** ; `0` = rien de fiable → les 50 derniers |
| `chat` | `message`, `client_msg_id`, `attachments?`, `mode?` | voir ci-dessous |
| `presence` | `here` (booléen) | l'application passe au premier plan (`true`) ou le quitte (`false`) |
| `composing` | `on` (booléen) | la personne commence à écrire un message (`true`) ou cesse (`false`) ; authentifié seulement |
| `read` | `up_to` (un identifiant de message) | jusqu'où la personne a lu son fil, si elle l'a permis ; authentifié seulement |
| `where` | `lat`, `lon`, `accuracy?`, `label?`, `age_ms?` — ou `off: true` | où est la personne, si elle l'a permis (ADR 0119) ; authentifié seulement |
| `approval` | `id`, `decision` (`accept` \| `refuse`), `digest` | décider d'une carte d'accord (§4, `approvals`) ; authentifié seulement |
| `verdict` | `message_id`, `verdict` (`ok` \| `ko` \| vide), `comment?` | juger une de ses réponses (ADR 0113) ; opératrice authentifiée seulement |
| `strand` | `id`, `title`, `description`, `archived` | régler un de ses fils de travail (ADR 0164) ; opératrice authentifiée seulement |
| `strand_history` | `id`, `before?` | les messages d'un de ses fils de travail (ADR 0164) ; opératrice authentifiée seulement |

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
  transcrit, les documents lus ; puis les octets sont **gardés** côté serveur (ADR 0106 : relus de près, reliés à ce
  qu'elle en retient, oubliés avec la personne) — rien ne change pour le client, qui ne reçoit pas de clé. Une trame
  entière ne dépasse pas ~34 Mio (et OkHttp n'en envoie pas plus de 16 Mio d'un coup).
- `mode` (clé absente d'ordinaire) : `"pro"` demande une réponse de travail (ADR 0116, ci-dessous). Toute autre
  valeur vaut « absent ». Honoré seulement sur une connexion **authentifiée d'opératrice** ; ailleurs, le message est
  ordinaire, sans erreur. Un renvoi garde son `mode`.
- `strand` (clé absente d'ordinaire, ADR 0164) : le fil de travail où le message est écrit — un identifiant que le
  client choisit (1 à 40 lettres, chiffres, `_` ou `-`), propre au compte. Honoré seulement avec `mode: "pro"` ;
  sinon, ou invalide, le message va au fil avec elle, sans erreur. Un renvoi garde son `strand`.
- Débits : 20 `chat` par 10 s ; 12 par 10 s pour `sync`, `read`, `where`, `approval`, `verdict`, `strand` et
  `strand_history` réunis (au-delà, ignorées). Au plus 8 `chat` en attente sur une connexion, comptés à la réception : au-delà, `overloaded` — les
  derniers d'une rafale, jamais les premiers.

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
Le serveur ignore une valeur qui n'avance pas ce qu'il sait déjà de ce compte, ou qui n'est pas dans son fil ; il
l'écrit au journal 6 fois par minute et par connexion au plus (au-delà, la dernière valeur voulue s'applique dès que
la fenêtre le permet). Mika sait alors si ce qu'elle a écrit d'elle-même a été vu.

`where` (ADR 0119) : où est la personne, d'après son téléphone, si elle l'a permis (« Lui dire où je suis », coupé
par défaut) et **seulement application au premier plan** — rien en arrière-plan, même connexion ouverte :

```json
{"type": "where", "lat": 45.764043, "lon": 4.835659, "accuracy": 12, "label": "Rue de la République, Lyon",
 "age_ms": 1500}
```

- `lat`, `lon` : des nombres finis dans leurs bornes (sinon la trame est ignorée) ; `accuracy` : la précision en
  mètres (absente ou 0 : inconnue) ; `label` : le nom du lieu que le téléphone a trouvé (une ligne, 200 caractères au
  plus ; absent : aucun) ; `age_ms` : l'âge de la mesure **au moment de l'envoi** (une mesure de plus de 24 h est
  ignorée).
- Le client envoie la dernière position à l'ouverture et à chaque déplacement, jamais en file. Le serveur ne réécrit
  pas une position qui n'a pas bougé (même lieu, moins de 50 m, moins de 10 min depuis la dernière écrite) ; 6
  écritures au journal par minute et par connexion au plus (au-delà, la suivante passera).
- `{"type": "where", "off": true}` : la personne ne le permet pas (ou plus) — sa dernière position s'efface (rien
  d'écrit s'il n'y en avait pas). Le client peut le redire à chaque ouverture tant que le réglage est coupé.
- Mika ne la regarde qu'en tête-à-tête avec cette personne, pour elle seule ; chaque regard se voit dans le fil
  (`notes`, §4). Aucune trame en retour.

**Le mode pro** (ADR 0116) : un « mode Claude Code » dans le chat. Le message reçoit une réponse de travail — sans
seconde passe, sans son tempérament ni sa voix de chat, longue et structurée s'il le faut, en Markdown — et ses
outils se voient en direct (trame `tool`, §4). Le dernier message d'une rafale décide du mode de la réponse.

**Les fils de travail** (ADR 0164) : en mode pro, le client tient des fils à part, chacun son contexte — un client de
chat à plusieurs conversations, où le fil avec Mika se cache. Un message pro porte son `strand` ; Mika n'y relit que
les messages de ce fil, sous son titre et sa petite description, et y répond dans ce fil. Deux fils sont deux tours :
une question dans l'un ne supplante pas la réponse qui s'écrit dans l'autre. Ouvrir un fil, c'est choisir un
identifiant neuf et y écrire (`/clear` dans le client web) ; rien ne s'efface, un fil se range en l'archivant. Tout
reste dans sa vie : elle s'en souvient comme du reste.

L'identité vient toujours de la session ou du jeton : il n'y a pas de trame pour se présenter.

`approval` (ADR 0064) : `digest` est **celui de la carte affichée** — le serveur refuse un accord sur autre chose que
ce qui a été montré (`changed`). Refuser n'exige pas d'empreinte.

`strand` (ADR 0164) : le réglage entier d'un de ses fils de travail — `title` (120 caractères au plus) et
`description` (2 000 au plus ; ce que Mika relit en tête de ce fil, à chaque message), vides permis, et `archived`
(booléen). Le dernier réglage vaut ; un fil peut se régler avant son premier message. Réponse : `strand_result` ; la
liste `strands` suit, à tous ses écrans d'opératrice.

`strand_history` (ADR 0164) : les 200 derniers messages du fil `id` avant `before` (un identifiant de message ; absent :
les plus récents), pour un écran qui ouvre un fil sans en avoir les messages. Réponse : un `history` de mode `strand`.

`verdict` (ADR 0113) : son opératrice dit si une de ses réponses était adaptée (`ok`) ou non (`ko`), et, si elle veut,
ce qu'elle aurait dû dire ou pourquoi (`comment`, 2 000 caractères au plus) ; un `verdict` vide retire l'avis. Le
dernier avis vaut. Il passe par le chemin des actions de la console (`transcript.juger`, audité). Réponse :
`verdict_result`.

## 4. Ce que le serveur envoie

**`ack`** — le sort d'un message, une fois par message (deux pour `no_reply`) :

```json
{"type": "ack", "client_msg_id": "c1mx3k2-7", "status": "accepted",
 "rejected_attachments": [{"name": "film.mp4", "reason": "too_large"}]}
```

| `status` | Sens |
|---|---|
| `accepted` | reçu (y compris un renvoi) |
| `rate_limited`, `overloaded` | non reçu : trop vite, ou trop de messages en attente (sur cette connexion, ou dans tout le serveur) |
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
- Une **ligne vide** dans `text` sépare deux bulles : sa réponse en plusieurs messages, comme quelqu'un qui écrit
  vraiment (ADR 0112). Le serveur garde **un** message (un `message_id`, une notification, un souvenir) ; le client
  montre ses bulles l'une après l'autre, « Mika écrit… » entre deux, au rythme de la frappe — à l'arrivée seulement :
  dans l'historique, elles sont là toutes. Ses fichiers vont sous la dernière.
- Texte vide : pas de parole à montrer (« Mika écrit… » cesse, la bulle de la personne reçoit son identifiant). Elle
  a choisi de ne pas répondre ; sauf `voice_reason: "asleep"` (elle dort, elle répondra à son réveil), ou un second
  `ack` `no_reply` qui suit : la réponse n'a pas pu venir.
- `voice_reason` : pourquoi la voix parle ou se tait. Le serveur pose lui-même `silence` et `asleep` (une trame sans
  texte), `other_tab` (un autre écran parle), `pro` (réponse de travail) et `error_fallback_muted` (texte de repli) ;
  toute autre valeur est informative.
- `voice_persona: "inner"` : une pensée à voix haute ; `message_id`, `user_message_id` et `client_msg_id` sont nuls,
  elle n'est pas dans le fil. À montrer seulement à l'écran regardé, **jamais en notification** (le serveur ne
  l'envoie d'ailleurs pas à une connexion absente).
- `source: "error"` sans identifiant : un texte de repli, pas une parole d'elle.
- `user_message_id` / `client_msg_id` rattachent la réponse à la question (la bulle reçoit son identifiant).
- `attachments` : les fichiers qu'elle envoie (§6). Toujours présent, souvent vide.
- `notes` (absente s'il n'y en a pas) : les petites bulles de ce qu'elle a fait en écrivant ce message (ADR 0119) —
  `[{"kind": "location", "text": "Rue de la République, Lyon", "at": 1790601490000}]` : elle a regardé où était la
  personne ; `text` est le lieu (ou des coordonnées, ou vide une fois oublié), `at` l'instant de la mesure (ms). Le
  client compose la bulle (« 📍 Mika a regardé où tu es · Rue de la République, Lyon · position de 14:10 ») et la
  montre juste avant sa réponse ; une sorte inconnue s'ignore ; une liste illisible ne fait jamais perdre le message.
- `speak` n'est vrai que pour un seul écran regardé de la personne (celui qui a demandé, sinon le plus récemment
  actif) ; jamais pour une connexion absente.
- `mode` : présent sur une parole, `"pro"` ou `""` ; absent d'une trame sans texte ou de repli. Une réponse pro
  (ADR 0116) : `speak` toujours faux, `voice_reason:
  "pro"` ; son texte peut porter du **Markdown** (blocs de code, `code`, gras, italique, listes, titres, tableaux,
  citations, liens) et forme **une seule bulle** — une ligne vide ne la coupe pas, pas de rythme de frappe.
- `strand` (absent hors d'un fil de travail, ADR 0164) : le fil de travail où elle répond. Le client la range dans ce
  fil, jamais dans le fil avec elle.

**`history`** — un morceau du fil :

```json
{"type": "history", "mode": "catchup", "last_id": 812, "truncated": false, "life": "a41f…", "reset": false,
 "messages": [{"id": 811, "role": "user", "text": "regarde ça", "ts": 1790601612771, "source": "mobile",
               "emotion": "", "emotion_intensity": 0.0, "attachments": [{"name": "photo.jpg", "kind": "image"}]},
              {"id": 812, "role": "assistant", "text": "Avec plaisir !", "ts": 1790601615002, "source": "reply",
               "emotion": "happy", "emotion_intensity": 0.6, "attachments": []}]}
```

- `mode` : `initial` (à l'ouverture, ou `reset`) ou `catchup` (réponse à `sync`, ou les messages d'une rafale et la
  question d'un tour posé d'un autre appareil, juste avant la `speech` qui y répond) ; `strand` : la réponse à
  `strand_history`, avec `strand` (le fil) et `more` (il en reste de plus anciens) — son `last_id` n'est pas un
  curseur.
- `initial` et `catchup` portent tout le compte, fils de travail compris : une ligne d'un fil de travail porte
  `strand` (ADR 0164) ; le client la range dans ce fil. Un seul curseur suffit donc à tout rattraper.
- `ts` en **millisecondes** depuis l'époque Unix.
- `text` d'un message de la personne : ce qu'elle a tapé ; ses fichiers par leur nom et leur sorte (`image`,
  `audio`, `file`). Un message de Mika : sans jetons de voix ; ses fichiers comme dans `speech`.
- Une ligne d'elle jugée, **pour une connexion d'opératrice seulement** : `verdict` (`ok` \| `ko`) et `verdict_note`
  (ce qu'elle aurait dû dire, ou vide) — absents sinon (ADR 0113).
- Une ligne d'elle porte `notes` comme la `speech` (absente s'il n'y en a pas, ADR 0119).
- Une ligne écrite en mode pro (ADR 0116) porte `mode: "pro"` (absent sinon) ; une ligne d'elle en mode pro porte
  aussi `tools` : `[{"name": "memory_search", "ok": true}, …]`, les outils dont elle s'est servie, dans l'ordre des
  appels (leurs noms seulement ; liste vide possible).
- Une ligne `user` que tu montres déjà — tapée sur cet appareil, pas encore rattachée à un `id` — s'**adopte** au
  lieu de s'ajouter : la plus ancienne de tes bulles sans identifiant au même texte reçoit l'`id` de la ligne. La
  `speech` ne rattache que le dernier message d'une rafale (`user_message_id`, `client_msg_id`) : les précédents
  arrivent dans le `catchup` qui la précède, et une question encore sans réponse revient dans le fil d'une
  reconnexion. Sans adoption, ils s'affichent deux fois.
- `life` : l'empreinte de sa vie (le même journal). Si elle change, ou si `reset` est vrai, vide ce que tu montres
  (sauf tes messages encore en partance) avant de fusionner, et repars du `last_id` de ce fil pour ton curseur.
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

**`verdict_result`** — le sort d'un avis : `{"type": "verdict_result", "message_id": 812, "verdict": "ko", "comment":
"…", "status": "ok"}` ; `status` : `ok`, `invalid` (pas une de ses réponses, ou oubliée), `forbidden` (pas une
opératrice), `failed` (réessayer).

**`tool`** — ses outils en direct, pendant une réponse en mode pro (ADR 0116). Seulement aux connexions
**regardées et authentifiées d'opératrice** de la personne à qui elle répond ; jamais dans l'historique, jamais
notifiée, jamais gardée par le serveur — un client la garde **en mémoire seulement** :

```json
{"type": "tool", "episode": "01JB…", "reply_to": 811, "phase": "start", "call_id": "toolu_01…",
 "name": "memory_search", "args": "{\"query\": \"anniversaire de Léa\"}", "at": 1790601613001}
{"type": "tool", "episode": "01JB…", "reply_to": 811, "phase": "end", "call_id": "toolu_01…",
 "name": "memory_search", "args": "…", "ok": true, "result": "3 souvenirs : …", "duration_ms": 182, "at": 1790601613183}
{"type": "tool", "episode": "01JB…", "reply_to": 811, "phase": "note", "text": "Je regarde…", "at": 1790601613190}
{"type": "tool", "episode": "01JB…", "reply_to": 811, "phase": "done", "outcome": "done", "at": 1790601619002}
```

| `phase` | Champs | Sens |
|---|---|---|
| `start` | `call_id`, `name`, `args` | un outil part |
| `end` | `call_id`, `name`, `args`, `ok`, `result`, `duration_ms` | il a fini (`ok` faux : échec, ou appel refusé — un `end` **sans `start`** préalable crée sa ligne) |
| `note` | `text` | ce qu'elle a écrit entre deux appels d'outils |
| `done` | `outcome` | l'épisode est fini (`done`, `failed`, `timeout`, `abstained`, `superseded`, `preempted`, `cancelled`…) |

- `reply_to` : l'`id` du message auquel elle répond, le `user_message_id` de la `speech` qui suivra (ou `null`).
- `episode` : une réponse supplantée (un nouveau message pendant qu'elle travaille) peut être suivie d'un nouvel
  épisode, au même `reply_to`.
- `args` (JSON, en texte) et `result` (texte brut) : bornés à 2 000 caractères (`…[coupé]`) ; à montrer en texte
  brut, jamais interprétés.
- `strand` (absent hors d'un fil de travail, ADR 0164) : le fil de travail où elle répond.
- `done` et la `speech` arrivent dans un ordre ou dans l'autre.
- Un client qui ne connaît pas la trame l'ignore.

**`strands`** — ses fils de travail (ADR 0164), aux seules connexions **authentifiées d'opératrice** : à
l'ouverture (après le `history` initial, le visage et le panneau), après un réglage (`strand`) et après chaque message écrit dans un fil. La
liste entière, du plus récemment actif au plus ancien, archivés compris :

```json
{"type": "strands", "items": [{"id": "s1mx4k2", "title": "Devis Intelligent Networks",
  "description": "Le commercial d'IN ; montants HT.", "archived": false, "count": 12,
  "first_at": 1790601612771, "last_at": 1790605212771, "opener": "liste moi les devis"}]}
```

- `first_at`, `last_at` en millisecondes ; `count` : ses messages (0 pour un fil seulement réglé) ; `opener` : le début
  de son premier message (120 caractères au plus), de quoi le nommer sans titre.

**`strand_result`** — le sort d'un réglage : `{"type": "strand_result", "id": "s1mx4k2", "status": "ok"}` ;
`status` : `ok`, `invalid` (un champ trop long), `forbidden` (pas une opératrice), `failed` (réessayer).

**`emotion_update`** — son visage entre deux tours, seulement vers un écran regardé : `person_id`, `emotion`,
`emotion_intensity`, `emotion_blend` (`[{"emotion", "weight"}]`) et `emotion_state`, comme dans `speech` :
`{"person": {emotion, intensity}, "global": {emotion, intensity}, "message": {emotion, intensity, blend}}` (sa
posture envers la personne, son humeur, le visage du message).

**`inner_state_update`** — le panneau de sa vie intérieure, `{"inner_state": {…}}` :

| Clé | Ce que c'est |
|---|---|
| `sleep_phase`, `energy`, `circadian` | son sommeil, son énergie, son rythme |
| `place` | où elle est |
| `activity` | ce qu'elle y fait : `{"name": "draw", "label": "dessiner", "since": …, "until": …}` en ms (`until` nul : jusqu'à ce qu'elle s'arrête) ; `null` : rien. Un client tait un nom qu'il ne connaît pas. |
| `night` | sa dernière nuit, du réveil jusqu'au milieu de sa journée (absente sinon) : `{"slept_h": 7.5, "broken": 1, "short": false}` — heures dormies à la demi-heure, fois où on l'a tirée du sommeil, nuit courte |
| `drives`, `estime` | ses besoins, son estime |
| `ruminations` | ce qui lui trotte dans la tête |
| `today_journal` (avec son `title`), `last_dream`, `self_narrative` | sa journée, son dernier rêve, son récit |
| `identity` | qui elle a en face : `known_as`, `certainty`, `level`, `trust`, `pending_claims` |
| `person_profile`, `pending_commitments` | ce qu'elle sait de la personne et ce qu'elle lui a promis, si sa fiche lui est ouverte |
| `projects`, `pending_project_actions` | pour une propriétaire : ses projets, et les actions qui attendent son accord (`id`, `project_title`, `proposal`, `owner_label`, `kind_label`…) |
| `person_scope` | `false` : cette trame ne parle de personne, garde les sections personnelles |

Une action de projet se décide par `POST /api/projects/pending/<id>/approve` (ou `/reject`), corps
`{"note": "…"}` facultatif, avec la session et l'en-tête CSRF, opératrice seulement : `{"ok": true, "status"}` ; 401
sans compte, 403 pour qui n'est pas opératrice, 400 pour une autre décision, 404 pour une action inconnue ou déjà
décidée, 409 (`status` : `changed`, `blocked`) quand ce qui partirait a changé — à décider alors depuis la console.

**`pong`** — la réponse à `ping`, avec son `t`.

## 5. Notifier

**Par la connexion** (l'application ouverte, ou quittée depuis peu) : notifie une `speech` (ou une ligne `assistant`
d'un rattrapage) quand l'application n'est pas au premier plan, que `voice_persona` vaut `speaking`, que
`message_id` n'est pas nul, que le texte n'est pas vide, que l'identifiant dépasse le dernier lu ou notifié, et
qu'elle ne répond pas à une question posée **d'un autre appareil** (`client_msg_id` qui n'est pas à toi). Ne
notifie pas le tout premier fil reçu (curseur à zéro). Un rattrapage = une seule notification groupée.

**Par Firebase** (l'application fermée, ADR 0077) : le serveur applique la même règle à chaque parole qu'il livre, et
l'envoie à chaque téléphone inscrit (`POST /auth/push`) du compte qui ne la regarde pas par une connexion vivante
(à l'écran, `here`, et une trame reçue depuis moins de 45 s) : une connexion « absente » ou muette peut recevoir la
même parole par les deux chemins — dédoublonne par `id`. Firebase ne garantit pas l'ordre : ne compare pas à un
« dernier notifié ». La réponse à une question posée d'un navigateur ne part pas ; celle
posée du téléphone (une réponse depuis la notification, connexion refermée depuis), si. C'est un message Firebase de
**données**, de priorité haute :

```json
{"v": "1", "n": "<nonce, base64>", "c": "<chiffré, base64>"}
```

`c` est le clair chiffré en AES-256-GCM avec la clé du téléphone, le nonce `n` (12 octets) et les données associées
`fr.qwartz.mika/push/v1` (étiquette de 16 octets à la fin, comme en Java). Le clair :

```json
{"t": "speech", "id": 4242, "text": "Tu es rentrée ?", "ts": 1791000000000, "files": 0}
```

`id` : l'identifiant du message dans le fil (comparer au dernier lu et notifié : la connexion a pu l'apporter
d'abord) ; `text` sans jetons prosodiques, coupé à 2 400 octets (« … ») ; `ts` en ms ; `files` : le nombre de
fichiers joints, à télécharger une fois connecté. Une autre `v`, un chiffré qui ne s'ouvre pas, un `t` inconnu :
rien n'est montré. La parole n'est pas dans le fil du téléphone tant qu'il ne s'est pas reconnecté (`sync`) ; ne
l'y insère pas avec son `id` — ton curseur dépasserait des messages jamais reçus.

Avec un jeton `mobile` vivant, elle peut écrire la première quand tu n'es devant aucun écran (un rappel échu, une
prise de nouvelles) : la parole part par Firebase si le téléphone est inscrit, et attend dans le fil jusqu'au
prochain `sync`. Ses retenues valent toujours (pas de harcèlement, pas la nuit hors rappel).

**Une réponse qu'elle propose** d'envoyer à ta place dans WhatsApp ou Messages (ADR 0120, § 5 bis) a son propre
clair. Elle part à **chaque** téléphone inscrit du compte, l'application ouverte ou non :

```json
{"t": "phone_draft", "id": 1234, "app": "whatsapp", "thread": "<clé de conversation du téléphone>",
 "to": "Léa", "text": "Oui, j'arrive vers 20 h !", "exp": 1791007200000, "ts": 1791000000000}
```

`id` : la proposition (à rendre dans `/api/phone/settled`) ; `thread` : la clé opaque que le téléphone a donnée à
la conversation (il y retrouve l'action « Répondre » de la notification) ; `exp` : passé cet instant (ms), ne la
montre plus ; `text` est coupé pour tenir dans Firebase. Montre-la comme une demande d'autorisation (« Envoyer »,
« Écrire autre chose », « Ignorer ») : rien ne part sans ton geste.

## 5 bis. Les messages du téléphone (ADR 0120)

Si tu le permets (« Lui montrer mes messages », coupé par défaut), l'application lit les notifications de WhatsApp et
de Messages et les pousse au serveur. Les deux routes passent sous le jeton de l'application (`mw_…`, client
`mobile`, sans `Origin`) et sont réservées à une propriétaire : sans jeton valable, 401 ; un jeton d'écran, une
`Origin`, un compte qui n'est pas propriétaire, ou le plugin coupé, 403 ; un corps illisible, 400 ; plus de 2 Mio,
413 ; trop de requêtes (120 par minute), 429 avec `Retry-After`.

- `POST /api/phone/inbox` :

  ```json
  {"messages": [{"id": "<hex, 8 à 64>", "app": "whatsapp", "thread": "<hex>", "title": "", "group": false,
                 "sender": "<hex>", "name": "Léa", "text": "Tu viens samedi ?", "time": 1791000000000,
                 "own": false}]}
  ```

  200 messages au plus. `app` : `whatsapp`, `whatsapp_business`, `messages` ou `samsung_messages`. `id`, `thread` et
  `sender` sont des empreintes calculées par le téléphone (l'expéditeur est vide quand c'est toi qui as écrit,
  `own`). `title` est le nom du groupe. `time` est en ms. Un message illisible (clé qui n'est pas en hex, appli
  inconnue, texte vide, date invraisemblable) est écarté seul. Réponse : `{"ok": true, "accepted", "known",
  "dropped"}`. Un même `id` renvoyé est « connu », jamais réécrit.
- `POST /api/phone/settled` :

  ```json
  {"items": [{"id": 1234, "result": "sent", "reason": ""}]}
  ```

  `result` : `sent` (sa réponse est partie), `other` (tu as écrit autre chose), `copied` (l'action « Répondre »
  n'existait plus : le texte a été copié), `ignored` ou `failed`. `reason` : un code (`no_action`,
  `send_error`). Seul le premier sort compte. Réponse : `{"ok": true, "settled", "unknown"}`.

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
`Content-Security-Policy: sandbox; default-src 'none'`) ; 404 pour un fichier inconnu **ou** qui n'est pas à toi (la même réponse) ; 410
pour un fichier retiré (ou dont les octets manquent) ; 401 sans compte (y compris un jeton posé à côté d'une
`Origin`, sans cookie) ; 429 au-delà de 60 téléchargements par minute ; un identifiant mal formé, 404 avant même de
regarder le compte. Le type n'est donné que
parmi des types sûrs (texte, Markdown, CSV, JSON, PNG, JPEG, WebP, GIF, PDF) ; sinon `application/octet-stream`.

## 7. Derrière un mandataire

Le mandataire doit laisser passer `Authorization` et `X-Mika-Presence` à la mise à niveau WebSocket. Les pings du
client (toutes les 20 s) tiennent dans n'importe quel délai de lecture ; ce qui dimensionne le mandataire, c'est la
console : voir [`deploy/README.md`](../deploy/README.md).
