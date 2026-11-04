# L'API par personne — `/api/moi`

Ce document est pour qui écrit le client de tous les jours, `frontendv2/` : ce qu'il montre à la personne connectée,
et seulement à elle — ses boîtes, ses comptes Teams, ses téléphones, ses services, ce qu'on lui partage, ses droits.
Les décisions et leurs raisons sont les ADR 0187 à 0192 de [`decisions.md`](decisions.md) ; le code fait foi dans
[`app/moi/`](../src/mika/app/moi/__init__.py). La conversation reste sur `/ws` ([`protocole-chat.md`](protocole-chat.md)) ;
la console, celle des opérateurs, voit tout et ne passe pas par ici.

## 1. Qui demande

- Un navigateur s'authentifie comme pour le chat (§ 1 de `protocole-chat.md`) : `GET /auth/whoami` plante le cookie
  `csrftoken`, `POST /auth/login` ouvre la session. Un client natif présente son jeton `Authorization: Bearer mw_…`,
  **sans** `Origin`.
- Une lecture est un `GET`. Une écriture est un `POST` au corps JSON (64 Kio au plus : 413 au-delà), avec l'en-tête
  `X-CSRFToken` (la valeur du cookie). Un client natif ne fait que lire : une écriture qui présente un jeton porteur
  est refusée (403), même avec un cookie et un en-tête CSRF qu'il poserait lui-même.
- Un paramètre texte a sa borne (un destinataire 300 caractères, un objet 200, un mail 20 000…) : au-delà, il est
  **refusé** (400, `fields: {"<nom>": "N caractères au plus"}`), jamais coupé.
- Une écriture peut porter une clé d'envoi, `Idempotency-Key` (ou `nonce` dans le corps). Le même envoi, rejoué,
  ne refait rien et répond `"deduped": true`. Cela vaut pour ce qui passe par une action de la console (Mail, Teams,
  ses brouillons) et pour les créations (une boîte, un compte Teams, un service). Pour une création, la clé vaut tant
  que le serveur tourne. « Préremplir », redit, ne redemande rien et rend où en est la demande (`asked`, ou le
  brouillon qui attend : `draft`). Les autres réglages s'écrivent tels quels : les redire ne change rien de plus.
- Les réglages (boîtes, comptes Teams, services, partages) se relisent puis se réécrivent d'un seul tenant, sous le
  verrou que prend aussi la console : deux personnes qui enregistrent en même temps ne s'effacent pas. Une boîte réglée
  ailleurs pendant que tu l'enregistrais n'est pas écrasée (409 : rouvre-la, puis recommence) ; retirée entre-temps,
  elle ne revient pas (404).
- Qui n'est pas opératrice branche au plus dix ressources de chaque sorte (boîtes, comptes Teams, services : 409
  au-delà). Elle teste une boîte ou un service, ou relève ses boîtes, au plus trente fois par minute (429 au-delà).
- Toute réponse est `Cache-Control: no-store`, sauf les tuiles, polices et icônes de la carte (§ 5). Les instants sont en **millisecondes** depuis l'époque (0 : jamais).

Les erreurs sont `{"error": "…"}` en français, plus `fields` (un message par champ) quand un formulaire est refusé :

| Statut | Sens |
|---|---|
| 400 | une requête illisible, un paramètre faux, un champ refusé (`fields`) |
| 401 | pas de session (ou un jeton révoqué) |
| 403 | le jeton CSRF manque ou ne correspond pas ; un client natif qui écrit ; ce que ton partage n'ouvre pas, ou ce qui reste à son propriétaire (une ressource qu'on te partage) |
| 404 | introuvable — **ou pas à toi** : une ressource d'une autre personne n'existe pas, la réponse est la même |
| 409 | l'action n'est pas possible en ce moment (déjà décidée, une boîte qui ne peut pas envoyer, dix ressources déjà branchées…) |
| 429 | trop d'essais (changer son mot de passe ; tester, relever) |
| 502 | le serveur de la boîte n'a pas répondu |
| 503 | le domaine n'est pas branché (pas de courrier) |

Ce que fait une écriture de Mail ou de Teams passe par l'action que la console déclare pour la même chose, au nom de
la personne (`by` : son adresse `user_N`) : journalisée, dédoublonnée et auditée comme dans la console ; un réglage
qu'elle change (son nom, son mot de passe, une boîte, un compte Teams, un service, un partage, un téléphone révoqué)
est audité aussi (`moi.<geste>`). Une écriture réussie rend `{"ok": true, "message": "…"}`.

## 2. `GET /api/moi`

```json
{"username": "adrien", "name": "Adrien Moreau", "handle": "user_1", "person": "user_1", "operator": true,
 "owner": true, "counts": {"mail": 7, "teams": 1, "phone": 0}}
```

- `person` : la clé de sa personne (ce qu'une ressource nomme dans son propriétaire, `personne:<clé>`).
- `owner` : une de ses propriétaires — ce qui est « à toi » (sans propriétaire nommé) est à elle.
- `counts` : pour la barre du haut — `mail` : les non-lus de la réception de ses boîtes, et ses brouillons qui
  attendent ta décision (dans tes boîtes seulement) ; `teams` : ses réponses qui attendent ta décision ; `phone` : ses
  réponses offertes au téléphone.

## 3. Mail

Une boîte est à la personne quand elle est à son nom (`personne:<clé>`), ou « à toi » et qu'elle est une de ses
propriétaires (ADR 0185) ; celles de Mika restent à la console. Une boîte qu'on lui partage (§ 9) s'y ajoute, à son
niveau. Un mail (`ref` : la référence `boîte:Message-ID`, ou celle que donne l'adaptateur), un brouillon, un envoi
sont à la boîte qu'ils désignent.

### Lire

**`GET /api/moi/mail/boxes`** — ses boîtes :

```json
{"plugged": true, "read_on_open": "3s",
 "boxes": [{"key": "pro", "name": "Atelier", "address": "atelier@example.test", "level": "proprietaire",
            "ready": true, "can_send": true, "enabled": true, "voice": "elle", "signature": "",
            "last_poll": 1790790000000, "error": "", "drafts_waiting": 1, "owner_name": "",
            "folders": [{"name": "INBOX", "label": "Réception", "role": "inbox", "polled": true, "total": 12,
                         "unseen": 3}]}]}
```

`read_on_open` : quand un mail ouvert devient lu (`jamais`, `aussitot`, `3s`, `10s`, ADR 0175) — le client pose le
geste `read` lui-même. `level` : `proprietaire`, ou le niveau d'un partage (`lire`, `preparer`, `servir`) avec le nom
de son propriétaire (`owner_name`, vide pour une boîte à toi). `common` : une boîte « à toi », commune à ses
propriétaires (elle ne se partage pas à l'une d'elles, § 9). `voice` : comment elle y écrit (`elle`, `assistante`,
`proprietaire`). `drafts_waiting` : 0 pour une boîte qu'on ne te partage qu'en lecture.

**`GET /api/moi/mail/messages`** — une page de messages : `box` (vide : toutes ses boîtes), `folder` (vide : tous),
`q` (texte cherché), `state` (vide, `unread`, `flagged`, `noticed` : ceux qu'elle a remarqués, ou `needs_reply` :
ceux qu'elle juge appeler une réponse, pas encore lus d'elle), `page`, `size` (100 au plus).

```json
{"total": 32, "page": 1, "size": 25,
 "items": [{"ref": "pro:<projet@example.test>", "box": "pro", "folder": "INBOX",
            "from": {"name": "Léa Martin", "address": "lea@example.test"}, "to": [{"name": "", "address": "…"}],
            "subject": "…", "snippet": "…", "date": 1790790060000, "seen": false, "flagged": false,
            "answered": false, "attachments": 1, "html": true, "bulk": false,
            "her": {"noticed": true, "important": true, "needs_reply": true, "read": false, "how": "",
                    "draft": "", "asked": false}}]}
```

`her` (absent : `null`) dit ce qu'elle en a fait, à part de ton non-lu (`seen`, le drapeau du serveur) : remarqué,
important, réponse attendue, lu de son côté (`read`, `how`), un brouillon qui attend (`draft`), une réponse demandée
(`asked`). Dans une boîte qu'on ne te partage qu'en lecture, `draft` et `asked` restent vides : les réponses en
préparation sont l'affaire de son propriétaire.

**`GET /api/moi/mail/message?ref=`** — un mail entier : les champs d'une ligne, plus `cc`, `reply_to`,
`in_reply_to`, `body` (le texte), `complete`, `sent` (parti de sa boîte : un envoi qu'elle sait, ou rangé dans
« Envoyés »), `received` (une copie reçue ailleurs, en copie à soi : on y répond), `attachments`
(`[{"part": "0", "name", "mime", "size"}]`), `images` (`{"remote": true, "shown": false}` : des images distantes, et
si on les montre pour cet expéditeur — la liste du serveur, que seule une de ses propriétaires règle) et, dans `her`,
`summary` (ce qu'elle en a retenu).

**`GET /api/moi/mail/frame?ref=[&images=1]`** — le HTML du mail, purgé, dans son document isolé (ADR 0169), à poser
dans un `<iframe sandbox="allow-popups allow-popups-to-escape-sandbox allow-same-origin">` : sa politique
(`Content-Security-Policy`) ne laisse rien s'exécuter ni se charger du dehors, et ne se laisse poser que par les
origines du client. Ses images distantes seulement avec `images=1` (cette fois), ou si une de ses propriétaires les
montre pour son expéditeur. Un mail sans HTML : 404.

**`GET /api/moi/mail/file?ref=&part=`** — une pièce jointe, toujours en téléchargement (`attachment`, `nosniff`, bac à
sable), sous une sorte sûre seulement. Une pièce qui n'est plus sur le serveur : 404 ; un serveur muet : 502.

**`GET /api/moi/mail/drafts`** — ses brouillons dans tes boîtes (ADR 0191), et dans celles qu'on te partage pour
préparer ou t'en servir (`decides` faux : ils attendent l'accord de leur propriétaire), le plus récent d'abord :

```json
{"items": [{"id": "d1", "box": "pro", "state": "attend", "at": 1790790000000, "decided_at": 0, "by": "",
            "note": "", "in_reply_to": "pro:<projet@example.test>", "asked": false, "voice": "elle",
            "decides": true, "original": {"subject": "Maquettes du projet", "from": "Léa Martin"},
            "to": "lea@example.test", "cc": "", "subject": "Re: Maquettes", "body": "…", "quote": true,
            "edited": false, "to_fill": false,
            "preview": {"sender": "…", "to": "…", "cc": "", "subject": "…", "text": "…", "digest": "…",
                        "blocked": ""}}]}
```

`state` : `attend` (ta décision), `approuve`, `parti`, `refuse`, `echec`. `asked` : on le lui avait demandé (sinon
d'elle-même). `original` : le mail auquel il répond (`null` : un mail nouveau, ou plus dans la boîte). `preview`
(seulement quand il attend) est exactement ce qui partira ; son `digest` se renvoie pour l'envoyer tel qu'il a été
lu ; `blocked` dit pourquoi il ne peut pas partir tel quel (un `[À COMPLÉTER`).

**`GET /api/moi/mail/sent[?box=]`** — ce qui est parti de ses boîtes (les 100 derniers de chacune, le plus récent
d'abord) : `ref`, `box`, `to`, `cc`, `subject`, `snippet`, `date`, `by` (vide : elle, après un accord), `draft`,
`attachments`.

**`GET /api/moi/mail/contacts?q=[&box=&size=]`** — ses correspondants (ceux du courrier relevé), pour écrire :
`address`, `name`, `received`, `sent`, `last`.

### Écrire

| Route | Corps | Ce que ça fait |
|---|---|---|
| `POST /api/moi/mail/send` | `box`, `to`, `cc?`, `subject`, `body` | un mail nouveau ; il part tout de suite, et elle le sait (`email.sent`) |
| `POST /api/moi/mail/reply` | `ref`, `to`, `cc?`, `subject`, `body`, `quote` | une réponse, depuis la boîte du mail reçu (à un mail parti de ta boîte sans copie reçue, `sent` sans `received` : 409, on le transfère). Ses brouillons qui attendaient pour ce mail sont refusés, quel que soit qui répond, et une réponse demandée (« Préremplir ») est remplie : celle qu'elle finirait au travail ne se propose plus. Rien ne part deux fois (la seule fois où un partage touche aux brouillons du propriétaire, ADR 0188) |
| `POST /api/moi/mail/forward` | `ref`, `to`, `cc?`, `subject`, `body?`, `attachments` | le transférer, ses pièces avec si `attachments` |
| `POST /api/moi/mail/tidy` | `refs` (100 au plus), `gesture` | sur le serveur : `read`, `unread`, `archive`, `flag`, `unflag`, `trash` |
| `POST /api/moi/mail/prefill` | `ref`, `instruction?` | « Préremplir avec Mika » : elle écrit une réponse à son prochain moment de travail → `{"asked": true, "draft": ""}` ; un brouillon qui attend déjà : `{"draft": "<id>"}`. Jamais pour un mail parti de ta boîte (`sent`, même revenu en copie : 409) : on y répond soi-même |
| `POST /api/moi/mail/draft/send` | `id`, `seen` | l'envoyer tel qu'il a été lu (`seen` : le `digest` de son aperçu) |
| `POST /api/moi/mail/draft/edit` | `id`, `to`, `cc?`, `subject`, `body`, `quote` | ta version remplace la sienne (la sienne est gardée : elle apprendra) |
| `POST /api/moi/mail/draft/refuse` | `id`, `note?` | il ne partira pas ; elle le saura |
| `POST /api/moi/mail/draft/redo` | `id`, `instruction` | le refuser, et qu'elle en écrive un autre |
| `POST /api/moi/mail/images` | `ref`, `shown` | les images distantes de cet expéditeur : toujours, ou plus — pour tout le serveur : réservé à ses propriétaires (sinon 403) |
| `POST /api/moi/mail/poll` | `box` | relever sans attendre, par une boîte que tu peux relever : la relève passe sur toutes les boîtes prêtes du serveur, une demande suffit (trente par minute au plus, avec les tests : § 1) |

Une boîte qui ne peut pas envoyer (sa connexion pas prête) : 409. Une adresse invalide : 400 avec `fields`.

## 4. Teams

Un compte Teams est à la personne quand il est à son nom (`personne:<clé>`), ou « à toi » et qu'elle est une de ses
propriétaires (ADR 0186) ; un compte qu'on lui partage s'y ajoute, à son niveau (§ 9). Une conversation se désigne par
sa clé (`<compte>~<identifiant>`, l'identifiant seul pour le compte `principal`), un message par sa référence
(`ref`).

### Lire

**`GET /api/moi/teams/accounts`** — ses comptes : `key`, `name`, `level`, `owner_name` (un compte partagé),
`enabled`, `last_batch` (le dernier lot de son extension), `self_name` (son nom dans Teams), `extension_key`
(`{"hint", "created_at"}`, jamais la clé ; `null` : pas de clé, ou un compte qui ne t'est que partagé),
`drafts_waiting` (0 en lecture seule), `common` (un compte « à toi », commun à ses propriétaires) ; plus `plugged`
et `enabled` (Teams actif).

**`GET /api/moi/teams/conversations[?account=&q=&size=]`** — ses conversations, la plus récente d'abord : `key`,
`account`, `title`, `kind` (`dm`, `group`, `channel`, `meeting`, `other`), `last_at`, `messages`, `last` (son dernier
message, texte coupé), `her` (`{"state", "draft"}` : une réponse de Mika en chemin, sinon `null` — toujours `null`
en lecture seule).

**`GET /api/moi/teams/thread?conversation=[&before=&size=]`** — le fil (les plus récents ; `before` : avant cet
instant) : `key`, `account`, `title`, `kind`, `messages` (`ref`, `author`, `author_id`, `at`, `text`, `own` — écrit
par la personne du compte, `mentions_me`), `more`, `replies` (ses réponses dans cette conversation, voir ci-dessous ;
vides en lecture seule), `pending`, `under_way` (une réponse d'elle en chemin), `asked` (une réponse demandée, dont ses
essais ne sont pas épuisés — elle y a renoncé, « Préremplir » la relance —, sur un compte coché de Teams actif : sinon
elle ne s'y mettra pas) — ces deux-là toujours faux en lecture seule. `pending` : ce que tu as écrit toi-même (ADR 0189) et qui
n'est pas encore revenu dans le fil — `id`, `body`, `at`, `by`, `reason`, `state` : `en_file`, `envoi`, `pose`, puis,
pendant un jour, `inutilise` (pas parti à temps : l'extension ne l'a pas pris) ou `echec`.

**`GET /api/moi/teams/replies`** — ses réponses dans tes comptes (ADR 0191), la plus récente d'abord : `id`,
`account`, `conversation`, `title`, `in_reply_to`, `state` (`attend` ta décision, `approuve`, `en_file`, `pose` dans
Teams, `parti`, `inutilise`, `refuse`, `expire`, `echec`), `mode`, `at`, `decided_at`, `by`, `note`, `asked`,
`edited`, `expires`, `body`, `sent_text` (ce qui est vraiment parti), `to_fill`, et `preview` tant qu'elle attend
(`text` signature comprise, `digest`, `blocked`).

### Écrire

| Route | Corps | Ce que ça fait |
|---|---|---|
| `POST /api/moi/teams/send` | `conversation`, `body`, `reply_to?` | ton message (ADR 0189) : en file pour l'extension du compte, qui l'envoie sous le nom de sa personne (la tienne, ou celle de son propriétaire pour un compte qu'on te partage pour t'en servir), sans signature ni accord ; un `[À COMPLÉTER` : 400 |
| `POST /api/moi/teams/prefill` | `message`, `instruction?` | « Préremplir avec Mika » : elle prépare une réponse à ce message, selon le mode du compte ; une réponse en chemin : `{"draft": "<id>"}` ; déjà demandée : `{"asked": true}`. Teams coupé ou ce compte décoché : 409, elle n'y prépare rien |
| `POST /api/moi/teams/reply/send` | `id`, `seen` | l'envoyer telle qu'elle a été lue (`seen` : le `digest` de son aperçu) |
| `POST /api/moi/teams/reply/edit` | `id`, `body` | ta version remplace la sienne |
| `POST /api/moi/teams/reply/refuse` | `id`, `note?` | elle ne partira pas ; elle le saura |
| `POST /api/moi/teams/reply/redo` | `id`, `instruction` | la refuser, et qu'elle en écrive une autre |

Rien ne part sans l'extension de Teams ouverte dans un navigateur : la file attend, puis ce qui n'est pas parti à temps
ne part plus (`inutilise`). `reply/edit` accepte un texte à compléter (la réponse reste alors bloquée) ; `reply/send`
d'une réponse bloquée : 409.

## 5. Téléphone

Ce que l'application du téléphone a lu dans ses notifications (ADR 0120, 0190), sa position, ses téléphones. Écrire
soi-même depuis le web et « Préremplir » pour le téléphone (ADR 0189, 0191) n'ont pas encore de route : Mika y
répond quand on lui en parle dans le chat, et le téléphone demande le geste.

**`GET /api/moi/phone/conversations[?size=]`** — ses conversations, la plus récente d'abord : `key`
(`<appli>|<fil>`), `app`, `app_name`, `group`, `title` (le groupe, sinon qui écrit), `count`, `last_at`, `last`
(`id`, `at`, `own`, `sender`, `text` coupé), `her` (`{"state", "id"}` : une réponse de Mika en chemin, sinon `null`).

**`GET /api/moi/phone/thread?conversation=[&size=]`** — le fil : `messages` (`id`, `at`, `own`, `sender`, `text`),
`more`, `offers` (les réponses de Mika : `id`, `state` — `prepared`, `offered` au téléphone, puis `sent`, `other`,
`copied`, `ignored`, `failed` ou `expired` —, `at`, `expires`, `decided_at`, `reason`, `reply_to`, `text`).

**`GET /api/moi/phone/position`** — sa dernière position : `{"known": false}`, ou `known`, `coords`
(`{"lat", "lon"}`), `label`, `accuracy_m`, `at`.

**La carte de sa position** (ADR 0193) — servie par ce serveur seul, à qui est connecté (elle n'est à personne) ;
d'où viennent ses tuiles se règle dans la console (Réglages › Canaux › Carte de sa position). Ces routes sont les
seules dont le navigateur garde les réponses (`Cache-Control: private, max-age=86400`).

- **`GET /api/moi/phone/map`** — `ready` (sinon `reason`, en mots : aucune carte réglée, un fichier absent, un
  serveur injoignable — le client garde son plan dessiné), `kind` (`vecteur` : au schéma Protomaps ; `image`),
  `minzoom`, `maxzoom`, `bounds` (ouest, sud, est, nord ; `null` : partout), `attribution`, et les chemins de l'API
  à poser sur l'adresse du serveur : `tiles` (`…/tiles/{z}/{x}/{y}`), `glyphs` (`…/fonts/{fontstack}/{range}.pbf`,
  `null` sans polices : une carte sans noms), `sprite` (`…/sprites/v4`, la planche suit : `/light`, `/dark` ;
  `null` sans icônes).
- **`GET /api/moi/phone/map/tiles/{z}/{x}/{y}`** — une tuile, telle que l'archive la garde (`Content-Encoding: gzip`
  pour Protomaps : le navigateur l'ouvre) ; aucune là (hors de la zone, hors des zooms) : 204, une tuile vide ;
  aucune carte réglée : 404 ; la carte ne se lit pas : 503.
- **`GET /api/moi/phone/map/fonts/{pile}/{plage}.pbf`** — une plage de glyphes, de la première police de la pile qui
  est là ; **`GET /api/moi/phone/map/sprites/v4/{planche}.json|.png`** (`@2x` compris) — les icônes. Rien en dehors
  de leur dossier : 404.

**`GET /api/moi/phone/phones`** — ses téléphones (les jetons `mobile` de son compte, révoqués compris, jamais leur
secret) : `id`, `label` (« Android · fabricant modèle », composé par l'application), `created_at`, `last_used`,
`revoked`, `push` (il a dit où le notifier) ; plus `apk` (l'application est déposée sur le serveur).

**`GET /api/moi/phone/apk`** — l'application, `mika.apk`, à qui est connecté (ADR 0190) : sa session, ou un jeton
de son compte (celui de son téléphone, pour se mettre à jour), jamais un lien public. Pas encore déposée (le fichier `telephone/mika.apk` du dossier de
données) : 404.

**`POST /api/moi/phone/revoke`** `{"id"}` — révoquer un de ses téléphones : son jeton ne vaut plus rien, ses
connexions se ferment, ses messages restent. Déjà révoqué : 409 ; pas le sien : 404.

`counts.phone` (dans `GET /api/moi`) : ses réponses offertes au téléphone, qui attendent ton geste.

## 6. Outils : la matrice de tes droits

**`GET /api/moi/rights`** — ce que Mika fait de chacun de ses outils **pour toi**, par chaque canal et à chaque
moment, et seule quand elle travaille. Chaque case est la décision même de la porte d'offre (les deux portes, le
plafond, la condition d'un outil, une ressource à ton nom) ; pour un service ou une app de la Forge, la ligne de leurs
accès. Rien n'y montre les lignes d'une famille, ni les droits d'une autre personne.

```json
{"canals": [{"key": "web", "label": "Chat web"}, {"key": "salon", "label": "Un salon"},
            {"key": "mobile", "label": "App Android"}, {"key": "teams", "label": "Teams"},
            {"key": "courrier", "label": "Courrier"}, {"key": "seule", "label": "Elle seule"}],
 "moments": [{"key": "reply", "label": "quand elle te répond"},
             {"key": "initiative", "label": "quand elle te parle d'elle-même"},
             {"key": "work", "label": "quand elle travaille seule"}],
 "groups": [
   {"key": "families", "title": "Ses propres outils", "resources": [
     {"key": "famille:email", "title": "Courrier", "description": "…", "tools": [
       {"name": "email_read", "description": "…", "acts": false,
        "cells": {"web/reply": {"level": "seule", "keep": "public", "why": "ligne 1", "reason": "", "owned": false},
                  "salon/reply": {"level": "non", "keep": "rien", "why": "…", "reason": "", "owned": false},
                  "seule/work": {"…": "…"}}}]}]},
   {"key": "accounts", "title": "Tes comptes", "resources": [
     {"key": "courrier:pro", "kind": "mail", "title": "Atelier", "address": "…", "family": "famille:email",
      "rules": {"canal": "courrier:pro", "set": false, "default": {"…": "…"},
                "lines": [{"who": "tout le monde", "when": "toujours", "prepare": false, "reply": "accord",
                           "reply_words": "ton accord"}]}}]},
   {"key": "services", "title": "Services", "resources": [{"key": "mcp:meteo", "title": "Service « meteo »",
                                                           "tools": ["…"]}]},
   {"key": "apps", "title": "Apps de la Forge", "resources": []}]}
```

- Une case est `<canal>/<moment>` : `reply` et `initiative` pour chaque canal qui parle, `work` pour `seule`. Une case
  absente (`null`) : l'outil ne sert pas à ce moment.
- `level` : `seule` (elle s'en sert), `carte` (elle te demande, une carte dans ton chat), `toi` (ton accord), `non`.
  `keep` : ce qu'elle garde de ce qu'il rend (`public` un savoir, `perso` un souvenir, `prive` une confidence,
  `rien`). `why` : les lignes qui en décident, en mots, et le canal ou le plafond quand ils serrent. `reason` : ce qui
  le ferme avant ses lignes — `when` (la condition qu'il déclare sur qui est en face : `why` la dit), `needs` (son
  service n'est pas configuré), `fits` (les accès de sa ressource). `owned` : ouvert parce qu'une ressource de l'outil
  est à toi (une boîte à ton nom, ADR 0185).
- `accounts` : chaque boîte et chaque compte Teams à toi (pas ceux qu'on te partage : leur règle est l'affaire de
  leur propriétaire), avec sa famille d'outils (`family`, ses cases sont dans `families`) et la règle de son canal
  (`rules` : qui écrit, préparer d'elle-même, comment ça part — `seule`, `accord`, `brouillon`, `non` ; `set` faux :
  son minimum vital).
- Une case `owned` se lit au niveau de ce qui t'est ouvert : un partage « lire » n'ouvre que les outils qui lisent,
  « lire et préparer » aussi celui qui prépare une réponse, « s'en servir » aussi celui qui range.
- `services`, `apps` : seulement ceux qu'au moins une case t'ouvre.

## 7. Paramètres

Ce qu'une personne branche est à elle (ADR 0185, 0186) : à son nom, ou « à toi » si elle est une de ses
propriétaires — jamais à quelqu'un d'autre (le partager est une délégation, ADR 0188).

- **Les secrets.** Un secret (un mot de passe) ne repart jamais : laissé vide, il reste celui qui est gardé. Si la
  connexion change (serveur, port, sécurité, utilisateur, authentification), il faut le redonner (400 sur son champ) :
  il ne part jamais vers un autre hôte. L'envoi sans mot de passe à lui se sert de celui de la lecture : changer le
  serveur d'envoi demande alors l'un des deux (`smtp_password`, ou `password` dans le même envoi). Retirer un serveur
  (le vider : une boîte qui ne fait que lire) ne redemande rien.
- **Les serveurs.** Une personne qui n'est pas opératrice ne fait joindre que des serveurs sur Internet : ni la
  machine, ni le réseau privé où elle tourne (400 sur le champ de l'hôte). Cela se vérifie sur ce qu'elle vise : un
  serveur neuf, ou un serveur dont elle change le port ou la sécurité. Une boîte réglée par une opératrice sur la
  machine (DavMail) se règle encore (son nom, sa voix, son mot de passe…), tant qu'on n'en change pas la cible. Une
  boîte Microsoft ne joint que les serveurs de Microsoft (`…office365.com`, `…outlook.com`) : son jeton ne se présente
  nulle part ailleurs (400).
- **Les clés.** Une boîte ou un compte nouveau reçoit une clé tirée de son nom et d'un suffixe au hasard : une clé ne
  sert jamais deux fois (ce qu'une boîte retirée avait gardé ne se rouvre pas). Ce qui en dérive (à qui, actif, ses
  partages) est rejournalisé aussitôt.
- **Les bornes.** Dix boîtes et dix comptes Teams au plus, pour qui n'est pas opératrice (409). Une création redite
  avec la même clé d'envoi ne refait rien (§ 1).

| Route | Corps | Ce que ça fait |
|---|---|---|
| `POST /api/moi/account/name` | `name` | son nom (celui sous lequel elle la connaît) |
| `POST /api/moi/account/password` | `current`, `password` | son mot de passe ; toutes ses sessions se ferment, et ses jetons obtenus par connexion (ses téléphones) sont révoqués → `{"relogin": true}`. Cinq essais faux par minute au plus (comptés dès leur arrivée : des essais lancés ensemble n'en font pas plus) : 429 |
| `GET /api/moi/mail/box?box=` | — | les réglages d'une de ses boîtes : `values` (sans secret), `secrets` (`{"password": true}` : un secret est gardé), `ready`, `can_send`, `microsoft`, `signin` (une connexion Microsoft : `state`, `code`, `url`, `until`, `error`) |
| `POST /api/moi/mail/box/save` | `box?`, `values` | sans `box` : une boîte nouvelle → `{"box": "<clé>"}` ; avec : la régler (les bornes de la console : un port, une fenêtre de relève). `values` : `label`, `address`, `enabled`, `auth` (`password` ou `microsoft`), `imap_host`, `imap_port`, `imap_ssl`, `user`, `password`, `folders`, `sync_all`, `since_days`, `oauth_client_id`, `oauth_tenant`, `smtp_host`, `smtp_port`, `smtp_security`, `smtp_user`, `smtp_password`, `save_sent`, `voice`, `display_name`, `sender_name`, `tone`, `instructions`, `signature` |
| `POST /api/moi/mail/box/remove` | `box` | la retirer : plus relevée ; ce qu'elle en a appris reste |
| `POST /api/moi/mail/box/test` | `box` | essayer sa connexion (trente fois par minute au plus, avec les relèves : § 1) |
| `POST /api/moi/mail/box/microsoft` | `box` | connecter une boîte Microsoft (ADR 0166) : un code à entrer chez Microsoft (`GET …/mail/box` dit où en est la connexion) |
| `GET /api/moi/teams/account?account=` | — | les réglages d'un de ses comptes Teams : `values` (`label`, `enabled`, `display_name`, `tone`, `instructions`, `sign`, `signature`), `extension_key` |
| `POST /api/moi/teams/account/save` | `account?`, `values` | sans `account` : un compte nouveau ; avec : le régler |
| `POST /api/moi/teams/account/key` | `account` | une clé neuve pour son extension, rendue **cette fois seulement** (`key`) ; l'ancienne ne vaut plus |
| `POST /api/moi/teams/account/revoke` | `account` | retirer la clé : son extension est refusée jusqu'à une clé neuve |
| `POST /api/moi/teams/account/remove` | `account` | retirer le compte : sa clé part avec lui, et ce que son extension avait apporté (conversations, messages, brouillons) s'efface |

Ses téléphones et l'application se règlent par le § 5 (`/api/moi/phone/phones`, `/phone/revoke`, `/phone/apk`).

## 8. Ses services MCP

Un service qu'elle branche ici est à elle (`McpServer.owner`, ADR 0192), **distant** (une adresse https ; un service
local, qui lance une commande sur la machine, reste aux opérateurs). Il naît avec une seule ligne d'accès, la sienne
(un outil qui lit : `seule` ; qui agit : `carte`, elle lui demande ; ce qu'elle y lit : `prive`), la ligne par défaut
fermée ; ses outils arrivent coupés, à choisir un par un (ADR 0129). Ce que Mika en offre reste dans la matrice
(§ 6).

| Route | Corps | Ce que ça fait |
|---|---|---|
| `GET /api/moi/mcp/services` | — | `{"plugged", "items"}` — ses services : `name`, `purpose`, `when_to_use`, `enabled`, `url`, `headers` (des en-têtes sont gardés, jamais rendus), `state` (`jamais`, `connecte`, `erreur`, `panne`, `incomplet`, `inactif`), `detail`, `tools` (`remote`, `name`, `description`, `choice` — `non`, `lecture`, `action` ; vide : jamais choisi —, `new`, `changed`), `access` (ses lignes, en codes et en mots), `default` |
| `POST /api/moi/mcp/plug` | `name`, `purpose`, `url`, `headers?`, `when_to_use?` | le brancher ; un nom déjà pris : 400 ; une adresse sur la machine ou le réseau privé, pour une personne qui n'est pas opératrice : 400 ; dix services déjà à elle : 409 |
| `POST /api/moi/mcp/test` | `name` | rouvrir une session et relire ses outils → `{"ok", "message"}` (trente fois par minute au plus : § 1) |
| `POST /api/moi/mcp/tools` | `name`, `choices` (`{"<outil>": "non" \| "lecture" \| "action"}`) | choisir ses outils : un outil nouveau ou changé, tel que le service le propose maintenant ; un outil déjà choisi change de choix |
| `POST /api/moi/mcp/save` | `name`, `values` (`purpose`, `when_to_use`, `enabled`, `url`, `secret_headers`) | le régler ; des en-têtes laissés vides restent |
| `POST /api/moi/mcp/remove` | `name` | le retirer : plus joint ni offert |

## 9. Ses partages

Seul le propriétaire partage, et seulement avec une personne qui a un compte (ADR 0188). Une boîte ou un compte
Teams partagé apparaît chez la personne avec son niveau (`level` : `lire`, `preparer`, `servir`) et le nom de son
propriétaire (`owner_name`), dans `GET …/mail/boxes` et `GET …/teams/accounts` ; elle n'y fait que ce que son niveau
ouvre — `lire` : lire ; `preparer` : aussi « Préremplir avec Mika » (ses brouillons attendent l'accord du
propriétaire, quoi que dise la règle d'envoi de la ressource) ; `servir` : écrire, répondre, ranger, comme le
propriétaire. Décider de ses brouillons, régler la ressource et la repartager restent au propriétaire : un partage n'y
suffit pas (403). Un service partagé reçoit une ligne d'accès pour la personne : `lire`, ses outils qui lisent ;
`servir`, aussi ceux qui agissent, sur sa demande à elle (`preparer` n'a pas de sens pour un service : 400).

| Route | Corps | Ce que ça fait |
|---|---|---|
| `GET /api/moi/people` | — | les personnes à qui partager : chaque compte actif sauf toi (`person`, `name`, `owner` : une de ses propriétaires, à qui ce qui est « à toi » est déjà) |
| `GET /api/moi/shares` | — | `given` (ce que tu partages : `kind`, `key`, `title`, `person`, `name`, `level`) et `received` (ce qu'on te partage : `kind`, `key`, `title`, `level`, `owner_name`) |
| `POST /api/moi/shares/set` | `kind` (`mail`, `teams`, `mcp`), `key`, `person`, `level` | partager à ce niveau, avec une personne qui a un compte actif (sinon 400) ; un `level` vide retire le partage, même fait à un compte fermé depuis. Toi-même : 400, pour partager comme pour retirer. Une ressource « à toi » à une de ses propriétaires : 400 (elle est déjà à elle). Une ressource qu'on te partage (un service aussi) : 403 ; ni à toi ni partagée : 404 |
