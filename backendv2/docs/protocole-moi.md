# L'API par personne — `/api/moi`

Ce document est pour qui écrit un client de tous les jours, `frontendv2/` ou l'application Android (ADR 0235) : ce qu'il montre à la personne connectée,
et seulement à elle — ses boîtes, ses comptes Teams, ses téléphones, ses services, ce qu'on lui partage, ses droits, sa
carte et ses voyages, ses projets, ses contacts, ses agendas. Les décisions et leurs raisons sont les ADR 0187 à 0192 de [`decisions.md`](decisions.md) (et,
pour la carte, 0193 à 0196 et 0229 ; pour les projets, 0282 et 0290 ; pour les contacts, 0298 ; pour l'agenda, 0309) ; le code fait foi dans
[`app/me/`](../src/mika/app/me/__init__.py). La conversation reste sur `/ws` ([`protocole-chat.md`](protocole-chat.md)) ;
la console, celle des opérateurs, voit tout et ne passe pas par ici.

## 1. Qui demande

- Un navigateur s'authentifie comme pour le chat (§ 1 de `protocole-chat.md`) : `GET /auth/whoami` plante le cookie
  `csrftoken`, `POST /auth/login` ouvre la session. Un client natif présente son jeton `Authorization: Bearer mw_…`,
  **sans** `Origin`.
- Une lecture est un `GET`. Une écriture est un `POST` au corps JSON (64 Kio au plus : 413 au-delà ; les envois de Mail
  acceptent aussi un `multipart/form-data`, § 3), avec l'en-tête `X-CSRFToken` (la valeur du cookie). L'application du
  téléphone (un jeton de client `mobile`) écrit sous son seul jeton, sans cookie ni CSRF (ADR 0235). Un autre client
  natif (`screen`) ne fait que lire : son écriture est refusée (403), même avec un cookie et un en-tête CSRF qu'il
  poserait lui-même.
- Un paramètre texte a sa borne (un destinataire 300 caractères, un objet 200, un mail 20 000…) : au-delà, il est
  **refusé** (400, `fields: {"<nom>": "N caractères au plus"}`), jamais coupé.
- Une écriture peut porter une clé d'envoi, `Idempotency-Key` (ou `nonce` dans le corps). Le même envoi, rejoué,
  ne refait rien et répond `"deduped": true`. Cela vaut pour ce qui passe par une action de la console (Mail, Teams,
  ses brouillons, tes voyages, l'agenda) et pour les créations (une boîte, un compte Teams, un service, un compte
  d'agenda). Pour une création, la clé vaut tant
  que le serveur tourne. « Préremplir », redit, ne redemande rien et rend où en est la demande (`asked`, ou le
  brouillon qui attend : `draft`). Les autres réglages s'écrivent tels quels : les redire ne change rien de plus.
- Les réglages (boîtes, comptes Teams, services, partages) se relisent puis se réécrivent d'un seul tenant, sous le
  verrou que prend aussi la console : deux personnes qui enregistrent en même temps ne s'effacent pas. Une boîte réglée
  ailleurs pendant que tu l'enregistrais n'est pas écrasée (409 : rouvre-la, puis recommence) ; retirée entre-temps,
  elle ne revient pas (404).
- Qui n'est pas opératrice branche au plus dix ressources de chaque sorte (boîtes, comptes Teams, services, comptes
  d'agenda : 409 au-delà). Elle teste une boîte, un service ou un serveur CalDAV, ou relève ses boîtes, au plus trente
  fois par minute (429 au-delà).
- Toute réponse est `Cache-Control: no-store`, sauf les tuiles, polices et icônes du fond de carte (§ 10). Les instants sont en **millisecondes** depuis l'époque (0 : jamais).

Les erreurs sont `{"error": "…"}` en français, plus `fields` (un message par champ) quand un formulaire est refusé ;
un réglage que son modèle refuse (une boîte, un compte Teams, un service, un partage) dit alors aussi dans `error`, en
une phrase, ce que disent ses champs, pour un client qui ne les place pas :

| Statut | Sens |
|---|---|
| 400 | une requête illisible, un paramètre faux, un champ refusé (`fields`) |
| 401 | pas de session (ou un jeton révoqué) |
| 403 | le jeton CSRF manque ou ne correspond pas ; un client natif qui n'est pas un téléphone et qui écrit ; ce que ton partage n'ouvre pas, ou ce qui reste à son propriétaire (une ressource qu'on te partage) |
| 404 | introuvable — **ou pas à toi** : une ressource d'une autre personne n'existe pas, la réponse est la même |
| 409 | l'action n'est pas possible en ce moment (déjà décidée, une boîte qui ne peut pas envoyer, dix ressources déjà branchées…) |
| 429 | trop d'essais (changer son mot de passe ; tester, relever) |
| 502 | le serveur de la boîte n'a pas répondu ; le serveur d'itinéraires a rendu un ordre illisible |
| 503 | le domaine n'est pas branché (pas de courrier ; pas d'index des lieux, d'adresses ou d'itinéraires), ou le service de la carte n'a pas répondu (le message dit lequel) |

Ce que fait une écriture de Mail ou de Teams passe par l'action que la console déclare pour la même chose, au nom de
la personne (`by` : son adresse `user_N`) : journalisée et dédoublonnée comme dans la console, auditée sous
`moi.<action>` (la console audite la même action sous sa clé nue : Système › Gestes audités dit d'où vient chacune) ;
un réglage qu'elle change (son nom, son mot de passe, une boîte, un compte Teams, un service, un partage, un téléphone
révoqué) est audité aussi (`moi.<geste>`). Une écriture réussie rend `{"ok": true, "message": "…"}`.

## 2. `GET /api/moi`

```json
{"username": "adrien", "name": "Adrien Moreau", "handle": "user_1", "person": "user_1", "operator": true,
 "owner": true, "counts": {"mail": 7, "teams": 1, "phone": 0, "projects": 3, "agenda": 2}, "correct": true}
```

- `person` : la clé de sa personne (ce qu'une ressource nomme dans son propriétaire, `personne:<clé>`).
- `owner` : une de ses propriétaires — ce qui est « à toi » (sans propriétaire nommé) est à elle.
- `counts` : pour la barre du haut, ce qui attend ta décision (ADR 0200) — `mail` : ses brouillons qui attendent,
  dans tes boîtes seulement (les non-lus ont leurs compteurs, dossier par dossier : `GET …/mail/boxes`) ; `teams` : ses
  réponses qui attendent ta décision ; `phone` : ses réponses offertes au téléphone ; `projects` : ce qui t'attend, toi,
  dans tes projets (« À faire », § 11) ; `agenda` : tes invitations qui attendent ta réponse, et ce que Mika propose
  d'écrire dans tes agendas dont tu décides (§ 13).
- `correct` : « Corriger » marche — un modèle est donné au rôle `correct` (ADR 0307) ; faux, le bouton reste éteint.

**`POST /api/moi/correct`** — « Corriger » (ADR 0307), dans le champ de Mail et de Teams : `text` (20 000 caractères au
plus) → `{"text", "changes", "refused"}`, le texte, ses fautes corrigées (orthographe, accents, accords, conjugaison,
homophones, ponctuation et ses espaces) **sans en changer les mots** : la réponse du modèle est alignée mot par mot
sur ton texte, et seules s'appliquent les corrections qui ne touchent pas aux mots. `changes` : combien de
corrections (0 : le texte tel quel) ; `refused` : combien de changements du modèle ont été écartés (un mot ajouté ou
retiré, un chiffre changé, un mot remplacé par un autre) — quand il en écarte plus qu'il n'en corrige, rien n'est
posé. Ses blancs de bord sont toujours les tiens. Un appel au modèle au premier plan, sans persona, une correction à la
fois par compte ; rien n'est gardé. Vide : 400 ; aucun modèle ne corrige : 409 ; une correction déjà en cours, ou plus
de vingt par minute et par compte : 429 ; trop long pour être corrigé d'un coup : 413 ; une réponse incomplète du
modèle (un refus) : 422 — jamais posée, même en partie ; le modèle n'a pas répondu : 502.

## 2 bis. Le direct : la trame `changed` (ADR 0308)

Rien ne se relit à intervalles. Ce qui change ce que montrent ces routes est poussé sur la connexion du chat (`/ws`,
[`protocole-chat.md`](protocole-chat.md)) que le client a déjà ouverte : une trame `changed` dit **quoi** a changé,
jamais le contenu, et l'écran relit la route qu'il montre. Seule une connexion authentifiée la reçoit, y compris celle
d'une application quittée depuis peu (`here` faux).

```json
{"type": "changed",
 "changes": [{"topic": "mail", "boxes": ["pro"]}, {"topic": "mail.drafts"}, {"topic": "me"}]}
```

| `topic` | Clés (absentes : tout le domaine) | Ce qu'on relit |
|---|---|---|
| `me` | — | `GET /api/moi` (les pastilles, son nom) |
| `mail` | `boxes` | `…/mail/boxes`, la page de `…/mail/messages` affichée (une de ces boîtes, ou toutes), le mail ouvert s'il est dans l'une d'elles, `…/mail/sent` |
| `mail.drafts` | `boxes` | `…/mail/drafts` |
| `mail.work` | `refs` | `…/mail/work?ref=` du mail ouvert, s'il est nommé |
| `teams` | `conversations` | `…/teams/accounts`, `…/teams/conversations`, le fil ouvert s'il est nommé |
| `teams.replies` | — | `…/teams/replies` |
| `teams.work` | `conversations` | `…/teams/work?conversation=` du fil ouvert, s'il est nommé |
| `phone` | `conversations` | `…/phone/conversations`, le fil ouvert s'il est nommé (ses `offers` avec) |
| `phone.position` | — | `…/phone/position` |
| `phone.phones` | — | `…/phone/phones` |
| `contacts` | — | les contacts (§ 12) |
| `agenda` | `calendars` | `…/agenda/calendars`, la période affichée (si elle montre un de ces agendas), l'événement ouvert, `…/agenda/invitations`, `…/agenda/proposals`, `…/agenda/accounts` (Paramètres › Agendas) — sans clé : tout l'agenda (un compte synchronisé, sa connexion, un réglage) |
| `projects` | `projects` | `…/projets`, « À faire », « Accords », la fiche ouverte si elle est nommée (et ses onglets) |
| `trips` | — | `…/voyages`, le voyage ouvert |
| `settings` | — | Paramètres : boîtes, comptes Teams, services, partages, droits (§ 6 à 9) |

- **Seulement ce que tu peux voir.** Une trame ne nomme que tes ressources et celles qu'on te partage, par les mêmes
  règles que ces routes : une boîte, une conversation ou un projet d'une autre personne n'y paraît jamais, même sans
  son contenu.
- **Regroupée.** Ce qui change en rafale (une relève de cinquante mails, un lot de l'extension Teams) part en une
  trame, ~150 ms après le premier changement. Un même `topic` part au plus trois fois d'affilée, puis une fois par
  seconde tant qu'il revient (une boîte qu'on range des heures durant, une étape après l'autre) : ce qui attend son
  tour part dès qu'il le peut, jamais perdu. Ce qui arrive pendant qu'une trame te part encore s'y réunit et part
  juste après, en une. Un `topic` inconnu se tait ; une clé inconnue se lit comme « tout le domaine ».
- **Sans clé, tout le domaine.** Ce qui ne se nomme pas (l'oubli d'un correspondant, une photo de profil, un contact
  réuni à un autre) part sans clé, à qui a quelque chose dans ce domaine. Ce qui change qui voit quoi part sans clé à
  toutes — celle qui vient de perdre l'accès doit le savoir aussi : les propriétaires et les partages d'une boîte ou
  d'un compte Teams (`contacts` compris), les accès d'un projet, ce qu'il lit des autres, son propriétaire, son niveau,
  archivé ou rendu (`projects`, `me`), une adresse reliée à une personne (tous les sujets), un réglage enregistré
  (`settings`, et `mail` ou `teams` pour une boîte, sa connexion Microsoft, un compte Teams, la clé de son extension ;
  `agenda` pour un compte d'agenda, un agenda réglé ou partagé, une connexion Google ou Microsoft),
  comme un nom ou un téléphone qui change (`me`, `phone.phones` — un téléphone qui reçoit ses notifications, ou ne les
  reçoit plus, compris). La fin de l'attente d'un code Microsoft part à qui lit la boîte (`mail`) et à son propriétaire
  (`settings`) ; la présence de l'extension Teams (sa connexion en direct qui s'ouvre ou se ferme, et au plus toutes
  les cinq minutes quand elle se manifeste) fait relire ses comptes à qui lit le compte (`teams`, sans clé — ou avec
  celles d'un lot du même instant, qui y suffit). Ce qui ne change rien de ce que montrent ces routes (une relève sans
  rien de neuf, un mail rangé à l'identique, un lot de l'extension déjà connu) ne dit rien.
- **Rien n'est rattrapé.** Une trame perdue pendant une coupure ne revient pas : à chaque ouverture de la connexion,
  le client relit une fois tout ce qu'il montre. Un écran au second plan ne relit rien ; il se relit à son retour.
- **Le courrier arrive dès qu'il est là**, même quand elle dort : une connexion IMAP IDLE par boîte qui le permet
  (l'attente relancée toutes les 8 min ; avant Python 3.14, `imaplib` ne la sait pas), sinon une relève chaque minute.
  Ce qu'elle en remarque suit son rythme à elle (`her`), pas celui de l'écran. Le `last_poll` d'une boîte
  (`…/mail/boxes`) dit son dernier rangement, par ce direct ou par sa relève ; `error`, la panne du direct pour une
  boîte qu'il observe (sa relève n'en dit ni n'en efface), sinon celle de sa relève — une connexion coupée qui se refait
  n'en est pas une. L'historique d'une boîte « tout garder » se dit une fois par passage et par dossier.

## 3. Mail

Une boîte est à la personne quand elle est à son nom (`personne:<clé>`), ou « à toi » et qu'elle est une de ses
propriétaires (ADR 0185) ; celles de Mika restent à la console. Une boîte qu'on lui partage (§ 9) s'y ajoute, à son
niveau. Un mail (`ref` : la référence `boîte:Message-ID`, ou celle que donne l'adaptateur), un brouillon, un envoi
sont à la boîte qu'ils désignent. Une boîte qu'on ne lui partage qu'en lecture n'entre dans aucune vue commune (`messages`,
`sent`, `contacts` sans `box`, ni `counts`) : elle se lit en la nommant (`box`), ADR 0200.

### Lire

**`GET /api/moi/mail/boxes`** — ses boîtes :

```json
{"plugged": true, "read_on_open": "3s", "microsoft_app": true,
 "boxes": [{"key": "pro", "name": "Atelier", "address": "atelier@example.test", "level": "proprietaire",
            "ready": true, "can_send": true, "enabled": true, "voice": "elle", "signature": "",
            "last_poll": 1790790000000, "error": "", "drafts_waiting": 1, "owner_name": "",
            "folders": [{"name": "INBOX", "label": "Réception", "role": "inbox", "polled": true, "total": 12,
                         "unseen": 3}]}]}
```

`microsoft_app` : le serveur a une application Microsoft, celle que Mika livre ou celle de l'instance (ADR 0238) —
une boîte Microsoft s'ajoute sans `oauth_client_id`, que le client ne demande plus. `read_on_open` : quand un mail ouvert devient lu (`jamais`, `aussitot`, `3s`, `10s`, ADR 0175) — le client pose le
geste `read` lui-même. `level` : `proprietaire`, ou le niveau d'un partage (`lire`, `preparer`, `servir`) avec le nom
de son propriétaire (`owner_name`, vide pour une boîte à toi). `common` : une boîte « à toi », commune à ses
propriétaires (elle ne se partage pas à l'une d'elles, § 9). `voice` : comment elle y écrit (`elle`, `assistante`,
`proprietaire`). `drafts_waiting` : 0 pour une boîte qu'on ne te partage qu'en lecture.

**`GET /api/moi/mail/messages`** — une page de messages : `box` (vide : toutes ses boîtes, sauf celles qu'on ne lui
partage qu'en lecture), `folder` (vide : tous),
`q` (texte cherché), `state` (vide, `unread`, `flagged`, `noticed` : ceux qu'elle a remarqués, ou `needs_reply` :
ceux qu'elle juge appeler une réponse et que personne n'a encore lus — ni elle, ni toi, ni un autre client, ce qu'elle
apprend à la relève ; ni `her.read`, sa part, ni `seen`, le drapeau du serveur qu'on peut remettre à non lu, ne le
disent en entier : la liste seule le dit), `page`, `size` (100 au plus).

```json
{"total": 32, "page": 1, "size": 25,
 "items": [{"ref": "pro:<projet@example.test>", "box": "pro", "folder": "INBOX",
            "from": {"name": "Léa Martin", "address": "lea@example.test"}, "to": [{"name": "", "address": "…"}],
            "subject": "…", "snippet": "…", "date": 1790790060000, "seen": false, "flagged": false,
            "answered": false, "attachments": 1, "html": true, "bulk": false,
            "her": {"noticed": true, "important": true, "needs_reply": true, "read": false, "how": "",
                    "draft": "", "asked": false, "alert": false, "filed": ""},
            "triage": "read"}]}
```

`her` (absent : `null`) dit ce qu'elle en a fait, à part de ton non-lu (`seen`, le drapeau du serveur) : remarqué,
important, réponse attendue, lu de son côté (`read`, `how`), un brouillon qui attend (`draft`), une réponse demandée
(`asked`), et ce que les consignes de tri de la boîte en ont fait (ADR 0243) : `alert` (te prévenir), `filed` (le
dossier où elles l'ont rangé, tant qu'il y est ; vide sinon). Dans une boîte qu'on ne te partage qu'en lecture, `draft` et `asked` restent vides : les réponses en
préparation sont l'affaire de son propriétaire.

`triage` dit ce que son tri a fait du mail (ADR 0240) : `read` (le modèle l'a lu), `guessed` (le repli seul, le modèle
n'ayant pas répondu, ou son tri coupé : son importance est devinée, jamais une réponse attendue), `bulk` (un envoi en
masse, jamais montré au modèle), `waiting` (relevé, pas encore trié : au relevé suivant, deux minutes après au plus) ;
vide sinon (un mail d'un dossier qu'elle ne relève pas, d'avant sa boîte, ou remarqué avant que son journal le dise).

**`GET /api/moi/mail/message?ref=`** — un mail entier : les champs d'une ligne, plus `cc`, `reply_to`,
`in_reply_to`, `body` (le texte), `complete` (faux : la copie gardée n'en est qu'une partie — le moteur la complète
sur le serveur en la lisant, et ne la rend telle quelle que si le serveur ne répond pas), `sent` (parti de sa boîte : un
envoi qu'elle sait, ou rangé dans
« Envoyés »), `received` (une copie reçue ailleurs, en copie à soi : on y répond), `attachments`
(`[{"part": "0", "name", "mime", "size"}]`), `images` (`{"remote": true, "shown": false}` : des images distantes, et
si on les montre pour cet expéditeur — la liste du serveur, que seule une de ses propriétaires règle) et, dans `her`,
`summary` (ce qu'elle en a retenu). Au premier niveau (pas dans `her`), `work` : où elle en est d'une réponse qu'elle y
prépare (ADR 0306), ou `null`.

**`work`, en direct** (ADR 0306) — le mail entier et le fil d'une conversation Teams disent où elle en est d'une réponse
qu'elle y prépare, demandée ou d'elle-même : `{"step", "label", "since", "started"}`. `step` : `waiting` (demandée,
pas encore commencée : elle s'y met, en une ou deux secondes — une minute après un essai qui a échoué, ou à la fin
de ce qui tient la conversation ou la boîte sans lui céder la place), `thinking` (elle réfléchit : elle compose, le modèle
écrit) ou `tool` (un de ses outils tourne ; `label` : son libellé, « Relire une de tes conversations Teams »). `since` :
le début de l'étape, `started` : celui du travail (ms ; pour `waiting`, la demande). Rien n'en est gardé : chaque
étape qui commence est poussée (`mail.work`, `teams.work`, § 2 bis), le client relit alors `work` et fait courir le
chrono entre deux étapes. `null` aussi en lecture seule : les réponses en préparation sont l'affaire du propriétaire.

**`GET /api/moi/mail/work?ref=`** — ce qu'on relit quand `mail.work` le nomme (§ 2 bis), pendant qu'elle y travaille,
sans relire le mail ni joindre son serveur : `{"work", "asked", "draft"}` (`draft` : son brouillon qui attend, dès qu'il est arrivé ;
`""` sinon).

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
            "to": "lea@example.test", "to_people": [{"name": "Léa Martin", "address": "lea@example.test"}],
            "cc": "", "subject": "Re: Maquettes", "body": "…", "quote": true,
            "edited": false, "to_fill": false,
            "preview": {"sender": "…", "to": "…", "cc": "", "subject": "…", "text": "…", "digest": "…",
                        "blocked": ""}}]}
```

`state` : `attend` (ta décision), `approuve`, `parti`, `refuse`, `echec`. `note` : ce qu'a dit qui a décidé (gardée à
part, l'oubli l'atteint), seulement sur une boîte à toi — celle d'un refus par son propriétaire ne se lit pas par un
partage, comme dans Teams. `asked` : on le lui avait demandé (sinon d'elle-même). `to_people` : ses destinataires, à leur nom quand la boîte les connaît (`to` reste le texte qu'on
retouche). `original` : le mail auquel il répond (`null` : un mail nouveau, ou plus dans la boîte). `preview`
(seulement quand il attend) est exactement ce qui partira ; son `digest` se renvoie pour l'envoyer tel qu'il a été
lu ; `blocked` dit pourquoi il ne peut pas partir tel quel (un `[À COMPLÉTER`).

**`GET /api/moi/mail/sent[?box=]`** — ce qui est parti de ses boîtes (les 100 derniers de chacune, le plus récent
d'abord) : `ref`, `box`, `to`, `cc` (des personnes, à leur nom quand la boîte le connaît), `subject`, `snippet`,
`date`, `by` (vide : elle, après un accord), `draft`, `attachments`.

**`GET /api/moi/mail/contacts?q=[&box=&size=]`** — ses correspondants (ceux du courrier relevé), pour écrire (les
destinataires proposés ; l'écran Contacts lit tout l'annuaire, § 12) :
`address`, `name`, `received`, `sent`, `last`. Un correspondant de plusieurs boîtes est une seule fiche : ses mails
comptés dans toutes, son dernier échange, le premier nom connu.

### Écrire

| Route | Corps | Ce que ça fait |
|---|---|---|
| `POST /api/moi/mail/send` | `box`, `to`, `cc?`, `bcc?`, `subject`, `body`, `files?` | un mail nouveau ; il part tout de suite, et elle le sait (`email.sent`) |
| `POST /api/moi/mail/reply` | `ref`, `to`, `cc?`, `bcc?`, `subject`, `body`, `quote`, `files?` | une réponse, depuis la boîte du mail reçu (à un mail parti de ta boîte sans copie reçue, `sent` sans `received` : 409, on le transfère). L'action du courrier (`email.repondre`, la même que la console) refuse dans le même geste ses brouillons qui attendaient pour ce mail, quel que soit qui répond (un brouillon décidé ailleurs pendant l'envoi n'a plus rien à refuser : la réponse partie s'écrit quand même), et une réponse demandée (« Préremplir ») est remplie : celle qu'elle finirait au travail ne se propose plus. Rien ne part deux fois (la seule fois où un partage touche aux brouillons du propriétaire, ADR 0188) |
| `POST /api/moi/mail/forward` | `ref`, `to`, `cc?`, `bcc?`, `subject`, `body?`, `attachments`, `files?` | le transférer, ses pièces avec si `attachments`, et `files` en plus |
| `POST /api/moi/mail/tidy` | `refs` (100 au plus), `gesture`, `folder?` | sur le serveur : `read`, `unread`, `archive`, `flag`, `unflag`, `trash` ; ou `move` avec `folder` (un dossier de leur boîte ; des mails d'une même boîte), ce qui y est déjà y reste → `{"moved": n}` (ADR 0200). Archiver, la corbeille et `move` rangent toute la sélection en une action (« Ranger la sélection ») et en une session IMAP par boîte ; un refus partiel se dit dans `message` (ADR 0302). Tous demandent « s'en servir » |
| `POST /api/moi/mail/prefill` | `ref`, `instruction?` | « Préremplir avec Mika » : elle s'y met tout de suite, même endormie, et écrit une réponse dans ses brouillons (ADR 0306 ; où elle en est : `work`) → `{"asked": true, "draft": ""}` ; un brouillon qui attend déjà : `{"draft": "<id>"}`. Jamais pour un mail parti de ta boîte (`sent`, même revenu en copie : 409) : on y répond soi-même |
| `POST /api/moi/mail/draft/send` | `id`, `seen` | l'envoyer tel qu'il a été lu (`seen` : le `digest` de son aperçu) |
| `POST /api/moi/mail/draft/edit` | `id`, `to`, `cc?`, `subject`, `body`, `quote` | ta version remplace la sienne (la sienne est gardée : elle apprendra) |
| `POST /api/moi/mail/draft/refuse` | `id`, `note?` | il ne partira pas ; elle le saura |
| `POST /api/moi/mail/draft/redo` | `id`, `instruction` | le refuser, et qu'elle en écrive un autre |
| `POST /api/moi/mail/images` | `ref`, `shown` | les images distantes de cet expéditeur : toujours, ou plus — pour tout le serveur : réservé à ses propriétaires (sinon 403) |
| `POST /api/moi/mail/poll` | `box` | relever sans attendre, par une boîte que tu peux relever : la relève passe sur toutes les boîtes prêtes du serveur, une demande suffit (trente par minute au plus, avec les tests : § 1) |

Une boîte qui ne peut pas envoyer (sa connexion pas prête) : 409. Une adresse invalide : 400 avec `fields`.

**Joindre des fichiers** (ADR 0214). `send`, `reply` et `forward` reçoivent, au lieu du JSON, un `multipart/form-data` :
les mêmes champs (un booléen vrai vaut `1`, `nonce` compris ; une fin de ligne CRLF, ce qu'écrit un formulaire, s'y
compte comme le `\n` du JSON), et chaque fichier sous `files`. Le corps entier tient en 51 Mio (413 au-delà) : un
mandataire placé devant le serveur doit laisser passer autant (nginx : `client_max_body_size 52m`, sinon il répond
lui-même 413, hors JSON). L'action du courrier juge les pièces : 25 Mo par pièce, dix pièces, 50 Mo en tout (400,
`fields: {"files": "…"}`). Un transfert auquel on ajoute des fichiers compte aussi, dans les dix pièces et les 50 Mo,
celles qu'il reprend (409) ; sans ajout, un mail au-delà de ces bornes se transfère encore tel quel. Joindre demande le
niveau qu'envoyer demande déjà, « s'en servir » (403 sinon). Une pièce
partie se lit dans le mail envoyé (`/mail/message`, `/mail/file`). `bcc` : ses copies cachées, qui vont dans l'enveloppe
et ne sont gardées ni par le serveur de Mika ni au journal ; seule la copie rangée dans « Envoyés » de la boîte les porte.

## 4. Teams

Un compte Teams est à la personne quand il est à son nom (`personne:<clé>`), ou « à toi » et qu'elle est une de ses
propriétaires (ADR 0186) ; un compte qu'on lui partage s'y ajoute, à son niveau (§ 9). Une conversation se désigne par
sa clé (`<compte>~<identifiant>`, l'identifiant seul pour le compte `principal`), un message par sa référence
(`ref`).

### Lire

**`GET /api/moi/teams/accounts`** — ses comptes : `key`, `name`, `level`, `owner_name` (un compte partagé),
`enabled`, `last_batch` (le dernier lot de son extension), `last_seen` (la dernière fois qu'elle s'est manifestée : un relevé, la connexion en direct, un lot — en mémoire depuis le démarrage du serveur, jamais plus tôt que `last_batch` ; c'est sur lui qu'on juge si elle est là), `self_name` (son nom dans Teams), `extension_key`
(`{"hint", "created_at"}`, jamais la clé ; `null` : pas de clé, ou un compte qui ne t'est que partagé),
`drafts_waiting` (0 en lecture seule), `common` (un compte « à toi », commun à ses propriétaires) ; plus `plugged`,
`enabled` (Teams actif) et `extension` (`{"version"}` : l'extension se télécharge ; `null` : elle n'est pas à côté
du serveur).

**`GET /api/moi/teams/extension`** — l'extension de navigateur en zip, `mika-teams-<version>.zip`, à qui est connecté
(ADR 0246) : sa session, ou un jeton de son compte, jamais un lien public. Le serveur le fait à la demande depuis le
dossier `frontend/Extension` du dépôt où il tourne ; il crée un dossier `mika-teams/`, à charger « non empaquetée ».
Pas de dossier, ou un manifeste illisible : 404.

**`GET /api/moi/teams/image?message=&image=`** — les octets d'une image d'un message (ADR 0258), son type tel quel
(`image/png`, `image/jpeg`, `image/gif`, `image/webp`), à qui peut lire le compte de ce message ; gardée un jour dans
le navigateur. Message ou image inconnus : 404.

**`GET /api/moi/teams/photo?account=&person=`** (ou `conversation=` à la place de `account` : le compte de cette
conversation) — la photo de profil d'une personne (ADR 0300 : 64 px, `image/jpeg`, `image/png` ou `image/webp`), que
l'extension a téléchargée de Teams, à qui peut lire ce compte : elle n'y est gardée que pour une personne qu'il a vue
(ses messages, une mention), comme le fil. `Cache-Control: private`, gardée un jour (son adresse change avec elle :
`v`), `X-Content-Type-Options: nosniff`. Personne inconnue, sans photo, ou un compte qui n'est pas à toi : 404. On
n'écrit pas son adresse : les réponses la donnent (`photo`), là où une personne paraît.

**`GET /api/moi/teams/conversations[?account=&q=&size=]`** — ses conversations, la plus récente d'abord : `key`,
`account`, `title` (son nom : pour un tête-à-tête — `kind` `dm`, ou un identifiant en `@unq.gbl.spaces` —, l'autre
personne, la dernière à y avoir écrit, sinon ce que Teams en dit — il ne s'y renomme pas : Teams n'en donne que la
liste de ses membres, toi compris, qu'on ne cherche pas ; pour toute autre, celui de Teams, vide sans titre — un
groupe, un canal, une réunion —, jamais le nom de qui y a parlé en dernier ; `q` le cherche, avec l'identifiant),
`kind` (`dm`, `group`, `channel`, `meeting`, `other`), `photo` (ADR 0300 : celle d'un tête-à-tête, la photo de
l'autre personne — la dernière à y avoir écrit, celle que nomme `title` —, même quand le dernier message est de toi ;
vide pour toute autre conversation, dont l'image de groupe n'est pas captée, et sans photo), `last_at`, `messages`,
`last` (son dernier message, texte coupé, comme un message du fil : ses réactions, la photo de son auteur), `her`
(`{"state", "draft"}` : une réponse de Mika en chemin, sinon `null` — toujours `null` en lecture seule, et pour une
réponse à laquelle on a répondu autrement).

**`GET /api/moi/teams/thread?conversation=[&before=&size=]`** — le fil (les plus récents ; `before` : avant cet
instant) : `key`, `account`, `title` (son nom, comme dans la liste), `kind`, `photo` (comme dans la liste),
`messages` (`ref`, `author`, `author_id`, `at`, `text`, `own` — écrit par la personne du compte : toi sur un compte
à toi, son propriétaire sur un compte qu'on te partage —, `mentions_me`, `images` : ses images, ADR 0258 — `id`,
`position` (son rang parmi les « [image] » du texte), `mime`, `seen` (ce que Mika y a vu, vide tant qu'elle ne l'a
pas regardée ; le texte le reprend déjà en « [image : … ] ») —, `reactions` : ses réactions, ADR 0300, dans l'ordre
de Teams — `key` (la clé de Teams : `like`, `heart`, `1f44f_clappinghands`…), `emoji` (vide si on ne le connaît
pas : montrer la clé), `count`, `mine` (la personne du compte en est), `names` (qui l'a posée, sous le nom que le
compte lui connaît, dix au plus, sans la personne du compte ; les autres se comptent) —, `photo` : l'adresse de la
photo de son auteur, vide sans photo —, `quote` : le message qu'il cite, ADR 0305, ou `null` — `author`, `author_id`,
`preview` (un extrait), `at` (ms), `ref` (sa référence ici, pour y aller ; vide : il n'est pas chez elle) ; `text` ne
le reprend pas), `more`, `replies` (ses réponses dans cette conversation, voir ci-dessous ;
vides en lecture seule), `pending`, `under_way` (une réponse d'elle en chemin), `asked` (une réponse demandée, dont ses
essais ne sont pas épuisés — elle y a renoncé, « Préremplir » la relance —, sur un compte coché de Teams actif : sinon
elle ne s'y mettra pas) — ces deux-là toujours faux en lecture seule —, `work` (où elle en est d'une réponse ici, en
direct : voir le mail entier ; `null` en lecture seule). `pending` : ce que tu as écrit toi-même (ADR 0189) et qui
n'est pas encore revenu dans le fil — `id`, `body`, `at`, `by`, `reason`, `state` : `en_file`, `envoi`, `pose`,
`parti` (au bout du fil seulement, sans `before` : l'extension l'a envoyé, son jumeau n'est pas encore revenu — un de
tes messages, le même texte aux espaces près, à moins de deux minutes, ADR 0251 ; 5 min au plus, il revient sinon
avec le lot suivant), puis, pendant un jour, `inutilise` (pas parti à temps : l'extension ne l'a pas pris) ou `echec`.

**`GET /api/moi/teams/work?conversation=`** — ce qu'on relit quand `teams.work` le nomme (§ 2 bis), pendant qu'elle y
travaille, sans relire le fil : `{"work", "asked", "under_way"}`, comme dans le fil (voir `work`, au mail entier).

**`GET /api/moi/teams/replies`** — ses réponses dans tes comptes (ADR 0191), la plus récente d'abord : `id`,
`account`, `conversation`, `title`, `in_reply_to`, `state` (`attend` ta décision, `approuve`, `en_file`, `pose` dans
Teams, `parti`, `inutilise`, `refuse`, `expire`, `echec`), `mode`, `at`, `decided_at`, `by`, `note` (ce qu'a dit qui
l'a refusée — sur un compte à toi seulement : un partage ne la lit pas), `asked`, `edited`, `expires`, `answered` (la
personne du compte a répondu autrement dans la discussion : elle ne partira pas — refusée avec la note « Répondu
autrement », ou sur le point de l'être, ADR 0199), `body`, `sent_text` (ce qui est vraiment parti), `to_fill`, et
`preview` tant qu'elle attend (`text` signature comprise, `digest`, `blocked`).

### Écrire

| Route | Corps | Ce que ça fait |
|---|---|---|
| `POST /api/moi/teams/send` | `conversation`, `body`, `reply_to?` | ton message (ADR 0189) — `reply_to` : la `ref` du message que tu cites (ADR 0305), cité dans Teams comme par « Citer » (dans un tête-à-tête aussi) : en file pour l'extension du compte, qui l'envoie sous le nom de sa personne (la tienne, ou celle de son propriétaire pour un compte qu'on te partage pour t'en servir), sans signature ni accord ; un `[À COMPLÉTER` : 400. Ses réponses qui attendaient un accord dans cette discussion ne partiront plus : le plugin les refuse (`answered`, ADR 0199), et une réponse demandée avant ne se prépare plus |
| `POST /api/moi/teams/prefill` | `message`, `instruction?` | « Préremplir avec Mika » : elle s'y met tout de suite, même endormie (ADR 0306 ; où elle en est : `work` du fil), et prépare une réponse à ce message, selon le mode du compte ; une réponse en chemin : `{"draft": "<id>"}` ; déjà demandée : `{"asked": true}`. Teams coupé ou ce compte décoché : 409, elle n'y prépare rien |
| `POST /api/moi/teams/reply/send` | `id`, `seen` | l'envoyer telle qu'elle a été lue (`seen` : le `digest` de son aperçu) ; une réponse à laquelle on a répondu autrement : 409 |
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
(`id`, `at`, `own`, `sender`, `text` coupé), `her` (`{"state", "id", "decided_at"}` : sa réponse en chemin, sinon
sa dernière réponse si elle suit le dernier message reçu, sinon `null` ; `decided_at` en ms, 0 tant qu'elle n'est pas
réglée).

**`GET /api/moi/phone/thread?conversation=[&size=]`** — le fil : `messages` (`id`, `at`, `own`, `sender`, `text`),
`more`, `offers` (les réponses de Mika : `id`, `state` — `prepared`, `offered` au téléphone, puis `sent`, `other`,
`copied`, `ignored`, `failed` ou `expired` —, `at`, `expires`, `decided_at`, `reason`, `reply_to`, `text`).

**`GET /api/moi/phone/position`** — sa dernière position : `{"known": false}`, ou `known`, `coords`
(`{"lat", "lon"}`), `label`, `accuracy_m`, `at`. Elle se montre sur le fond de carte, servi avec la carte (§ 10).

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
accès. Rien n'y montre les lignes d'une famille, ni les droits d'une autre personne : le pourquoi d'une case ne dit que
la part de la ligne qui te concerne (ADR 0209).

```json
{"canals": [{"key": "web", "label": "Chat web"}, {"key": "salon", "label": "Un salon"},
            {"key": "mobile", "label": "App Android"}, {"key": "teams", "label": "Teams"},
            {"key": "courrier", "label": "Courrier"}, {"key": "seule", "label": "Elle seule"}],
 "moments": [{"key": "reply", "label": "quand elle te répond"},
             {"key": "initiative", "label": "quand elle te parle d'elle-même"},
             {"key": "work", "label": "quand elle travaille seule"}],
 "groups": [
   {"key": "families", "title": "Ses propres outils", "resources": [
     {"key": "famille:email", "title": "Courrier", "description": "…", "href": "", "tools": [
       {"name": "email_read", "label": "Ouvrir un de tes mails", "description": "…", "acts": false,
        "cells": {"web/reply": {"level": "seule", "keep": "public", "why": "toi, toujours", "line": "",
                                "reason": "", "owned": false},
                  "salon/reply": {"level": "non", "keep": "rien", "why": "par défaut : personne", "line": "",
                                  "reason": "", "owned": false},
                  "seule/work": {"…": "…"}}}]}]},
   {"key": "accounts", "title": "Tes comptes", "resources": [
     {"key": "courrier:pro", "kind": "mail", "title": "Atelier", "address": "…", "family": "famille:email",
      "rules": {"canal": "courrier:pro", "set": false, "common": false, "default": {"…": "…"},
                "lines": [{"who": "tout le monde", "when": "toujours", "prepare": false, "reply": "accord",
                           "reply_words": "ton accord"}]}}]},
   {"key": "services", "title": "Services", "resources": [{"key": "mcp:meteo", "title": "Service « meteo »",
                                                           "description": "La météo d'une ville.", "href": "",
                                                           "tools": ["…"]}]},
   {"key": "apps", "title": "Apps de la Forge", "resources": []}]}
```

- Une case est `<canal>/<moment>` : `reply` et `initiative` pour chaque canal qui parle, `work` pour `seule`. Une case
  absente (`null`) : l'outil ne sert pas à ce moment.
- Un outil : `label`, ce qu'il fait, dit à la personne (« Te promettre un rappel », ADR 0208) — vide pour un outil
  venu d'ailleurs (un service, une app), que `description` nomme alors ; `description`, sa consigne au modèle (où
  « tu », c'est elle).
- `level` : `seule` (elle s'en sert), `carte` (elle te demande, une carte dans ton chat), `toi` (ton accord), `non`.
  `keep` : ce qu'elle garde de ce qu'il rend (`public` un savoir, `perso` un souvenir, `prive` une confidence,
  `rien`). `why` : pourquoi, dit à la personne (ADR 0209) — la part de la ligne qui décide qui la concerne : qui la
  désigne (toi, ses proches, tout le monde ; elle seule au travail) et quand (« tout le monde, quand elle répond »),
  ou « par défaut : personne » quand aucune ne la désigne ; puis « ce canal le restreint », ou la raison du plafond,
  s'ils ont serré. Jamais un numéro de ligne ni les autres personnes qu'elle nomme. Une case d'un service redit la
  ligne de son service ; celle d'une app, la ligne de son app ou de son projet (ADR 0219), sinon « les accès de cette
  app te l'ouvrent » (ou ne te l'ouvrent pas).
  `reason` : ce qui le ferme avant ses lignes — `when` (la condition qu'il déclare sur qui est en face : `why` la
  dit), `needs` (son service n'est pas configuré), `fits` (les accès de sa ressource). `owned` : ouvert parce qu'une
  ressource de l'outil est à toi (une boîte à ton nom, ADR 0185, ou qu'on te partage : `why` le dit).
- Pour une opératrice seulement (vides sinon) : `line`, la ligne même, telle que la console la dit (« ligne 2 —
  serré par le canal … ») ; `href` d'une famille, d'un service ou d'une app, la page de la console où se lit son
  tableau (`/admin/reglages/droits?detail=…`).
- `accounts` : chaque boîte et chaque compte Teams à toi (pas ceux qu'on te partage : leur règle est l'affaire de
  leur propriétaire), avec sa famille d'outils (`family` : ses outils sont les siens, les mêmes pour tous tes comptes
  de cette sorte, et ses cases sont dans `families`) et la règle qui vaut pour son canal, telle que le courrier et
  Teams la lisent (`rules` : qui écrit, préparer d'elle-même, comment ça part — `seule`, `accord`, `brouillon`,
  `non` ; `set` : la sienne ; sinon `common` : celle de tout son canal, réglée dans la console ; ni l'une ni l'autre :
  son minimum vital). Elle en règle préparer et comment ça part dans Paramètres (§ 7, ADR 0207).
- Une case `owned` se lit au niveau de ce qui t'est ouvert : un partage « lire » n'ouvre que les outils qui lisent,
  « lire et préparer » aussi celui qui prépare une réponse, « s'en servir » aussi celui qui range.
- `services`, `apps` : seulement ceux qu'au moins une case t'ouvre ; une app dit son titre. Un service qu'une personne
  a branché (`owner`, ADR 0192) dit son but (`description`, le `purpose` qu'elle lui a donné). Un service du système
  (`web`, son plugin actif) a un titre et un but écrits pour la personne par la composition (« Le web »,
  `app/system_mcp.py`, `SHOWN`, ADR 0219). Un service de l'opératrice, sans propriétaire, n'en dit rien (`description`
  vide) : son `purpose` est la ligne de son catalogue, écrite pour elle (ADR 0209). Ceux qu'on te partage sans
  qu'aucune case ne t'en ouvre encore se lisent dans `GET …/mcp/services` (`received`, § 8).

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
- **Comment ça part** (ADR 0207). La propriétaire d'une boîte ou d'un compte Teams règle la règle de son canal
  (`courrier:<clé>`, `teams:<clé>`) : pour chaque ligne et pour la ligne par défaut, préparer d'elle-même et comment ça
  part. Qui écrit, quand, l'ordre et le nombre des lignes restent à la console. `rules`, dans `GET …/mail/box` et
  `GET …/teams/account`, est la règle que le courrier et Teams lisent : `canal`, `set` (le compte a la sienne),
  `common` (sinon, celle de tout son canal, réglée dans la console ; ni l'une ni l'autre : sa règle de départ),
  `version` (son empreinte), `lines` et `default` (`who`, `when`, `prepare`, `reply` — `seule`, `accord`,
  `brouillon`, `non` —, `reply_words`).

| Route | Corps | Ce que ça fait |
|---|---|---|
| `POST /api/moi/account/name` | `name` | son nom (celui sous lequel elle la connaît) |
| `POST /api/moi/account/password` | `current`, `password` | son mot de passe ; toutes ses sessions se ferment, et ses jetons obtenus par connexion (ses téléphones) sont révoqués → `{"relogin": true}`. Cinq essais faux par minute au plus (comptés dès leur arrivée : des essais lancés ensemble n'en font pas plus) : 429 |
| `GET /api/moi/mail/box?box=` | — | les réglages d'une de ses boîtes : `values` (sans secret), `secrets` (`{"password": true}` : un secret est gardé), `ready`, `can_send`, `microsoft`, `signin` (une connexion Microsoft : `state`, `code`, `url`, `until`, `error`), `rules` (la règle de son canal) |
| `POST /api/moi/mail/box/save` | `box?`, `values` | sans `box` : une boîte nouvelle → `{"box": "<clé>"}` ; avec : la régler (les bornes de la console : un port, une fenêtre de relève). `values` : `label`, `address`, `enabled`, `auth` (`password` ou `microsoft`), `imap_host`, `imap_port`, `imap_ssl`, `user`, `password`, `folders`, `sync_all`, `keep_all` (tout garder en local, ADR 0249), `since_days`, `oauth_client_id`, `oauth_tenant`, `smtp_host`, `smtp_port`, `smtp_security`, `smtp_user`, `smtp_password`, `save_sent`, `voice`, `display_name`, `sender_name`, `tone`, `instructions`, `signature`, `triage_instructions` (ses consignes de tri, ADR 0243) |
| `POST /api/moi/mail/box/remove` | `box` | la retirer : plus relevée ; ce qu'elle en a appris reste |
| `POST /api/moi/mail/box/test` | `box` | essayer sa connexion (trente fois par minute au plus, avec les relèves : § 1) |
| `POST /api/moi/mail/box/microsoft` | `box` | connecter une boîte Microsoft (ADR 0166) : un code à entrer chez Microsoft (`GET …/mail/box` dit où en est la connexion) |
| `GET /api/moi/teams/account?account=` | — | les réglages d'un de ses comptes Teams : `values` (`label`, `enabled`, `display_name`, `tone`, `instructions`, `sign`, `signature`), `extension_key`, `rules` (la règle de son canal) |
| `POST /api/moi/teams/account/save` | `account?`, `values` | sans `account` : un compte nouveau ; avec : le régler |
| `POST /api/moi/teams/account/key` | `account` | une clé neuve pour son extension, rendue **cette fois seulement** (`key`) ; l'ancienne ne vaut plus |
| `POST /api/moi/teams/account/revoke` | `account` | retirer la clé : son extension est refusée jusqu'à une clé neuve |
| `POST /api/moi/teams/account/remove` | `account` | retirer le compte : sa clé part avec lui, et ce que son extension avait apporté (conversations, messages, brouillons) s'efface |
| `POST /api/moi/rules` | `canal` (`courrier:<sa boîte>` ou `teams:<son compte>`), `version`, `lines` (`[{"prepare", "reply"}]`, une par ligne), `default` (`{"prepare", "reply"}`) | comment part ce qu'elle prépare depuis un de ses comptes : enregistrée, la règle est celle du compte. Un autre canal, un autre champ, ou `brouillon` sur une ligne du courrier qui ne l'avait pas : 400 ; une ressource qu'on te partage : 403 ; ni à toi ni partagée : 404 ; une `version` qui n'est plus celle d'aujourd'hui, ou un autre nombre de lignes : 409 |

Ses téléphones et l'application se règlent par le § 5 (`/api/moi/phone/phones`, `/phone/revoke`, `/phone/apk`).

## 8. Ses services MCP

Un service qu'elle branche ici est à elle (`McpServer.owner`, ADR 0192), **distant** (une adresse https ; un service
local, qui lance une commande sur la machine, reste aux opérateurs). Il naît avec une seule ligne d'accès, la sienne
(un outil qui lit : `seule` ; qui agit : `carte`, elle lui demande ; ce qu'elle y lit : `prive`), la ligne par défaut
fermée ; ses outils arrivent coupés, à choisir un par un (ADR 0129). Ce que Mika en offre reste dans la matrice
(§ 6). Ses en-têtes secrets ne partent jamais vers un autre serveur que celui de son adresse (ADR 0236),
comme le mot de passe d'une boîte (§ 7).

| Route | Corps | Ce que ça fait |
|---|---|---|
| `GET /api/moi/mcp/services` | — | `{"plugged", "items", "received"}` — ses services (`items`) : `name`, `purpose`, `when_to_use`, `enabled`, `url`, `headers` (des en-têtes sont gardés, jamais rendus), `state` (`jamais`, `connecte`, `erreur`, `panne`, `incomplet`, `inactif`), `detail`, `tools` (`remote`, `name`, `description`, `choice` — `non`, `lecture`, `action` ; vide : jamais choisi —, `new`, `changed`), `access` (ses lignes, en codes et en mots ; `mine` : la ligne ne désigne qu'elle — la sienne, pas un partage), `default`. Ceux qu'on lui partage (`received`, § 9), en lecture : `name`, `purpose`, `enabled`, `state`, `tools` (ses outils servis : `remote`, `name`, `description`, `choice`), `level` (`lire`, `servir`), `line` (sa ligne d'accès), `owner_name` — ni `url`, ni `headers`, ni `detail` |
| `POST /api/moi/mcp/plug` | `name`, `purpose`, `url`, `headers?`, `when_to_use?` | le brancher ; un nom déjà pris : 400 ; une adresse sur la machine ou le réseau privé, pour une personne qui n'est pas opératrice : 400 ; dix services déjà à elle : 409 |
| `POST /api/moi/mcp/test` | `name` | rouvrir une session et relire ses outils → `{"ok", "message"}` (trente fois par minute au plus : § 1) |
| `POST /api/moi/mcp/tools` | `name`, `choices` (`{"<outil>": "non" \| "lecture" \| "action"}`) | choisir ses outils : un outil nouveau ou changé, tel que le service le propose maintenant ; un outil déjà choisi change de choix |
| `POST /api/moi/mcp/save` | `name`, `values` (`purpose`, `when_to_use`, `enabled`, `url`, `secret_headers`, `clear_headers`) | le régler ; des en-têtes laissés vides restent, `clear_headers: true` les retire. Une adresse qui mène ailleurs (un autre hôte, schéma ou port) redemande les en-têtes gardés (ADR 0236) : 400 sur `secret_headers` tant qu'ils ne sont ni redonnés ni retirés ; un autre chemin sur le même serveur, non |
| `POST /api/moi/mcp/remove` | `name` | le retirer : plus joint ni offert ; retiré entre-temps ailleurs : 400 |

## 9. Ses partages

Seul le propriétaire partage, et seulement avec une personne qui a un compte (ADR 0188). Un agenda partagé (ADR 0309)
apparaît dans ses agendas (`…/agenda/calendars`, `level`), à ce qu'il ouvre (§ 13). Une boîte ou un compte
Teams partagé apparaît chez la personne avec son niveau (`level` : `lire`, `preparer`, `servir`) et le nom de son
propriétaire (`owner_name`), dans `GET …/mail/boxes` et `GET …/teams/accounts` ; elle n'y fait que ce que son niveau
ouvre — `lire` : lire ; `preparer` : aussi « Préremplir avec Mika » (ses brouillons attendent l'accord du
propriétaire, quoi que dise la règle d'envoi de la ressource) ; `servir` : écrire, répondre, ranger, comme le
propriétaire. Décider de ses brouillons, régler la ressource (sa règle d'envoi comprise, § 7) et la repartager restent
au propriétaire : un partage n'y suffit pas (403). Un service partagé reçoit une ligne d'accès pour la personne :
`lire`, ses outils qui lisent ; `servir`, aussi ceux qui agissent, sur sa demande à elle (`preparer` n'a pas de sens
pour un service : 400). Elle le lit dans `GET …/mcp/services` (`received`, § 8), sans son adresse ni ses en-têtes.

Un opérateur voit tous les partages dans la console (Réglages › Droits › Partages, ADR 0210) et peut y retirer celui
d'une boîte, d'un compte Teams ou d'un agenda : la même écriture, qui disparaît de `given` et de `received` comme si son propriétaire
l'avait retiré. Il n'en donne aucun : seul le propriétaire partage.

| Route | Corps | Ce que ça fait |
|---|---|---|
| `GET /api/moi/people` | — | les personnes à qui partager : chaque compte actif sauf toi (`person`, `name`, `owner` : une de ses propriétaires, à qui ce qui est « à toi » est déjà) |
| `GET /api/moi/shares` | — | `given` (ce que tu partages : `kind`, `key`, `title`, `person`, `name`, `level`) et `received` (ce qu'on te partage : `kind`, `key`, `title`, `level`, `owner_name`) |
| `POST /api/moi/shares/set` | `kind` (`mail`, `teams`, `mcp`, `agenda` — `key` : la clé de l'agenda), `key`, `person`, `level` | partager à ce niveau, avec une personne qui a un compte actif (sinon 400) ; un `level` vide retire le partage, même fait à un compte fermé depuis. Toi-même : 400, pour partager comme pour retirer. Une ressource « à toi » à une de ses propriétaires : 400 (elle est déjà à elle). Une ressource qu'on te partage (un service aussi) : 403 ; ni à toi ni partagée : 404 |

## 10. Carte, lieux, itinéraires et voyages

Ce que l'écran Carte montre (ADR 0194, 0195, 0196, 0259), et le fond de toutes les cartes (ADR 0193, 0229). Le navigateur ne parle qu'à ce serveur ; le serveur cherche les
lieux dans son index local (`cartes/lieux.db` : rien ne sort), demande une adresse à la Géoplateforme de l'IGN (seul
le texte cherché part, jamais la position de la personne) et un itinéraire au serveur Valhalla réglé (seuls ses points
partent). Ce qui n'est pas branché répond 503, en mots. Une personne lit ce qui n'est pas prêt (« La recherche de lieux
n'est pas encore prête sur ce serveur. », de même pour les adresses et les itinéraires) : elle n'a pas la console. Une
opératrice lit ce qui manque et où le régler : « Les itinéraires ne sont pas réglés : Réglages › Carte et téléphone ›
Itinéraires. ». Un index des lieux abîmé ou effacé en cours de route se dit sans consigne d'exploitation (« L'index
des lieux est illisible. ») : c'est aussi ce que le modèle lit ; la console seule dit comment le refaire. Un service qui ne
répond pas, ou aucun chemin entre deux points : 503 aussi, son message dit lequel.

Un **lieu** : `id` (`l<n>` : l'index, qui change à chaque reconstruction — un arrêt garde son nom et ses
coordonnées ; `a:<n>` : une adresse de cette réponse), `name`, `kind` (la sorte OpenStreetMap, `camp_site` ;
`address`), `kind_fr` (« Camping »), `category` (`manger`, `dormir`… ; `adresse`), `lat`, `lon`, `town`,
`distance_m` (depuis `near`, ou jusqu'au trajet), `along_m` (le long d'un trajet : où on le croise, depuis le départ ;
sinon `null`). Et, seulement quand on les sait (ADR 0244 ; absents sinon) : `osm` (son objet d'OpenStreetMap, `n123`,
`w45`, `r6`, stable d'une reconstruction à l'autre), `open_state` (`open`, `closed`, `unknown` : des horaires qu'on ne
comprend pas) et `open_text` (« Ouvert · ferme à 22:30 », à l'instant de la réponse), `cuisine` (« Italienne,
pizza »), `tags` (ce qu'il vérifie parmi `terrasse`, `vegetarien`, `vegan`, `accessible`, `emporter`, `livraison`) ;
`rating` (sur 5), `reviews` (leur nombre), `price` (en euros, « €€ ») et `photo` (`p:<hash>`) quand le cache des avis les sait (Google Places, ADR 0256) ; avec `photo`, ce qu'il faut en citer
là où elle se montre (ADR 0269) : `photo_source` (`google`, `datatourisme`), `photo_credit` (son auteur),
`photo_credit_url` (son lien) et `photo_licence` (une photo de l'office de tourisme), eux aussi seulement quand on les
sait. Un lieu d'un regard ou d'une carte qu'elle a gardés n'a jamais `open_state` ni `open_text`, ni le crédit de sa
photo (un client n'en montre alors pas la vignette) ; son `id` y est entier (`t:<uuid>` compris : sa fiche se rouvre). Des points s'écrivent `latitude,longitude`, séparés par `;` ; une zone `ouest,sud,est,nord` (ouest
< est, sud < nord). Un paramètre hors de ses bornes est refusé (400), jamais ramené dedans : un nombre qui n'est pas
entier (`2.9`, `Infinity`) aussi. Ce qui fait sortir une demande vers le serveur d'itinéraires (un trajet, un ordre,
les lieux le long d'un trajet calculé, les tronçons d'un voyage, un GPX tracé) compte : au plus 20 par minute et par
compte (429 au-delà) — le serveur public ne répond qu'une fois par seconde, pour tout ce serveur et pour elle. Pour un
opérateur, les GPX tracés qu'il tire de la console comptent dans la même borne (ADR 0204). Une adresse cherchée a sa
propre borne, 60 par minute et par compte (la Géoplateforme en permet bien davantage).

### La carte

| Route | Ce que ça rend |
|---|---|
| `GET /api/moi/carte` | `{"places": {"ready", "count", "built"}, "addresses": {"ready"}, "routing": {"ready", "provider", "modes", "avoid"}, "categories": [{"id", "label"}], "tourism": {"ready", "places", "events", "synced"}, "features": [{"id", "label"}], "sorts": [{"id", "label"}], "themes": [{"id", "label"}]}` : ce qui est branché (`built` : quand l'index a été construit, en ms ; `provider` : qui calcule les trajets, en mots ; `modes` : `voiture`, `velo`, `pied` ; `avoid` : `peages`, `autoroutes`, `ferries` ; `tourism` : la base des données touristiques, `synced` sa dernière lecture en ms — celle d'une case ou d'un département, la plus récente ; 0 : jamais lue), les catégories dans l'ordre de l'écran, et ce qu'une liste et les événements savent filtrer : `features` (`terrasse`, `vegetarien`, `vegan`, `accessible`, `emporter`, `livraison`), `sorts` (`distance`, `rating`), `themes` (`concerts`, `spectacles`, `expositions`, `marches`, `fetes`, `sport`, `enfants`, `visites`, `conferences`), chacun avec son libellé |
| `GET /api/moi/carte/lieux?q=&cat=&near=&bbox=&limit=&open_now=&features=&cuisine=&min_rating=&sort=&here=` | `{"places": [lieu…], "reviews"?, "here"?}` : dans l'index, par le nom (`q`, 200 caractères), d'une catégorie (`cat`), près d'un point (`near` : `latitude,longitude`, ou `ici` — ta dernière position ; les plus proches d'abord), dans une zone (`bbox`) — au moins un de `q`, `near`, `bbox` ; `limit` : 1 à 50 (20). Filtres (ADR 0244, 0259) : `open_now=1` (ouvert à l'instant, d'après ses horaires), `features=terrasse,vegan` (tous ceux-là), `cuisine` (40 caractères : « italian » ou « italienne »), `min_rating` (0 à 5, « 4.5 » : écarte les lieux sans note), `sort` (`distance` ou `rating` : les mieux notés d'abord, ceux sans note à la fin). `reviews` (avec `near` ou `bbox`) : ce que le cache des avis sait de l'endroit, `{"ready", "cells", "loaded", "oldest", "note"}` (`oldest` : la lecture la plus ancienne, en ms, 0 : aucune ; `note` : ce qu'il faut en dire, en mots) — la ligne « notes Google lues le … ». `here` (avec `near=ici`) : `{"lat", "lon", "label", "at"}`. Chercher autour de toi (`near=ici`, ou `here=1` avec ta propre position) précharge les avis de ta case (§ « Les fiches… ») |
| `GET /api/moi/carte/adresses?q=&limit=` | `{"places": [lieu…]}` : une adresse (`q` : 3 à 200 caractères ; `limit` : 1 à 10, 5) |
| `GET /api/moi/carte/itineraire?points=&mode=&avoid=` | `{"distance_m", "duration_s", "legs": [{"distance_m", "duration_s", "shape", "steps": [{"text", "distance_m", "duration_s"}]}], "has_toll", "has_highway", "has_ferry", "provider"}` : de 2 à 20 points ; `shape`, le tracé d'un tronçon en polyline à six décimales ; `steps`, ses consignes en français ; `avoid` : `peages,autoroutes` |
| `GET /api/moi/carte/regards/<seq>` | ce qu'elle a cherché (`"kind": "look"`) ou montré (`"kind": "map"`) pour toi, la note d'un de ses messages (`protocole-chat.md`, § 4) : `{"kind", "title", "what", "places": [lieu…], "route", "trip", "at"}` — `what` : `lieux`, `trajet` ou `evenements` (un regard ; pour des événements, `"events": [{"id", "name", "start", "end", "when_text", "place", "lat", "lon"}]` et `places` vide ; la fiche qu'elle a lue est un regard de `lieux` d'un seul lieu, ou d'`evenements` d'un seul) ; `route` : `{"mode", "distance_m", "duration_s", "shape", "avoid"}` (le trajet résumé, et ce qu'il évitait ; une carte qui relie ses lieux sans tracé calculé : `{"mode"}` seul), sinon `null` ; `trip` : le voyage qu'elle montrait, s'il est encore là. Pour quelqu'un d'autre, oublié, ou ni un regard ni une carte : 404 |

### Les fiches, les événements et les photos

Ce que les sources disent d'un lieu ou d'un événement (ADR 0244, 0245, 0256, 0259), lu par ce serveur : l'index
d'OpenStreetMap, la base des données touristiques (un cache de DATAtourisme par cases), le cache des avis de Google
Places. Ce qui manque ou est vieux se lit en direct quand on ouvre une fiche, si le quota le permet ; sinon on montre
ce qu'on avait, et une `note` le dit en mots. Ce qui peut ainsi faire appeler un service compté est borné **par
compte** (429 au-delà, en mots) : 60 fiches ou recherches d'événements par minute (ensemble), 120 photos par minute,
10 « Actualiser » par minute ; une liste de lieux, qui ne lit que les caches, ne compte pas.

| Route | Ce que ça rend |
|---|---|
| `GET /api/moi/carte/lieu/<id>` | la fiche d'un lieu (`l<n>`, son objet d'OpenStreetMap `n123`/`w45`/`r6`, ou un lieu des données touristiques `t:<uuid>`) : `{"place": lieu, "osm", "tourism", "reviews", "events": [événement…]}` — chaque partie `null` quand sa source ne sait rien du lieu (ci-dessous). Une autre forme d'identifiant, ou un lieu qui n'est pas là : 404 |
| `POST /api/moi/carte/lieu/<id>/actualiser` | « Actualiser » : sa fiche relue tout de suite chez Google (la fiche avec ses avis et ses photos) et chez DATAtourisme, quel que soit son âge → `{"ok", "message", …la fiche}` — sauf une source relue il y a moins de dix minutes, qui ne repart pas (ADR 0269). `message`, à montrer tel quel, dit ce qui s'est passé : « Fiche relue. », « Relue il y a 4 min : elle est à jour (…) », « Rien à relire pour ce lieu : … » (on n'en lit pas les avis, et l'office de tourisme n'en a pas de fiche). Ce qui n'a pas pu se relire (le quota — celui du jour de tout le serveur compris : vingt « Actualiser » qui partent par 24 heures ; un « Actualiser » que rien ne laisse partir, le mois de Google atteint, son recul ou le quota de l'heure de DATAtourisme, n'en prend pas et dit cette cause —, la clé, le réseau, une fiche que DATAtourisme rend illisible, qui reste telle qu'on l'avait), ou rien de réglé (« Rien ne peut se relire ici : ni les avis (Google) ni les données touristiques (DATAtourisme) ne sont réglés. ») : 503, en mots — ce qui l'a pu est gardé : relis la fiche. 10 par minute et par compte, les refus compris |
| `GET /api/moi/carte/evenements?near=&bbox=&radius=&start=&end=&themes=&q=&free=&limit=` | `{"events": [événement…], "coverage", "here"?}` : les événements à venir près d'un point (`near` : `latitude,longitude` ou `ici` ; à moins de `radius` mètres, 500 à 100 000, 20 000) ou dans une zone (`bbox`), du `start` au `end` (`AAAA-MM-JJ`, à l'heure de Paris ; par défaut d'aujourd'hui à trente jours ; un an au plus — sans `start`, compté d'aujourd'hui : au-delà, ou un `end` déjà passé, 400 avec `fields.end`), d'un des `themes` (`concerts,fetes`), dont le nom ou le résumé dit `q`, gratuits seulement (`free=1`) ; `limit` : 1 à 50 (30) ; au moins un de `near`, `bbox`, `q`. Les plus tôt d'abord, puis les plus proches. `coverage` : ce que la base sait de l'endroit, au même rayon, `{"ready", "cells", "loaded", "oldest", "note"}` — une zone lue en partie (« Cette zone n'est lue qu'en partie (cases lues : 3 sur 11) : la suite se lit à la prochaine recherche, ou ce soir. »), trop grande, ou un quota atteint se disent dans `note` |
| `GET /api/moi/carte/evenement/<id>` | la fiche d'un événement (`e:<uuid>`) : `{"event": événement, "description", "dates": [{"start", "end", "text", "days"}], "more_dates", "prices", "contacts": [{"label", "value"}], "address", "town", "venue", "venue_place", "author", "updated", "url", "photos": [photo…], "merged", "attribution", "licence", "licence_url"}` — `dates` : toutes ses dates à venir, la prochaine d'abord (60 au plus, `more_dates` en plus ; `start` : sa prochaine séance, `end` : la fin de l'occurrence — pour une période, son dernier jour) ; `venue` : le lieu nommé où il se tient, s'il est rapproché (`venue_place` : son identifiant, pour `…/lieu/<id>`) ; `merged` : combien de fiches de DATAtourisme il réunit. Inconnu : 404 |
| `GET /api/moi/carte/photo/<ref>` | une photo relayée (`p:<32 chiffres hexadécimaux>`) : ses octets, `Content-Type` `image/jpeg`, `image/png`, `image/webp` ou `image/gif`, `Cache-Control: private, max-age=86400`, `X-Content-Type-Options: nosniff`. Une référence qu'aucune source ne connaît, dont les droits ont pris fin, ou qui n'a pas cette forme : 404, et rien ne part ; sa source muette, ou le cache de la carte qui ne s'écrit pas : 503, en mots ; ce qu'elle rend n'est pas une de ces images : 502. La première fois, une photo de Google coûte un appel compté : un client ne charge que celles qu'il montre |

Un **événement** (dans une liste, une fiche de lieu, un regard) a tous ses champs, toujours : `id` (`e:<uuid>`),
`name`, `start` et `end` (sa prochaine séance dans la période, en ISO 8601 : une date, ou une date et une heure à
l'heure de Paris, « 2026-11-21T10:00+01:00 » ; `end` est la fin de cette séance, le lendemain après minuit — jamais
celle d'une période, que `dates[].end` dit), `when_text` (« ven. 20 nov. · 19:00–20:30 », « du mar. au dim. ·
13:00–19:00 » dans les six jours qui viennent ; plus loin, avec leurs dates : « sam. 5 et dim. 6 déc. · 10:00–19:00 »), `place` (où, en
mots : le lieu nommé, ou l'adresse, et la commune), `lat`, `lon`, `distance_m` (depuis `near`, sinon `null`),
`themes`, `free` (`true`, `false`, `null` : on ne sait pas), `price` (ses tarifs en clair, ou vide), `photo` (`p:<hash>`,
ou vide) et ce qu'il faut en citer — `photo_source`, `photo_credit`, `photo_credit_url`, `photo_licence`, vides sans
photo (ADR 0269). Une **photo** : `ref`, `path` (le chemin de `…/photo/<ref>` sur ce serveur : jamais une adresse du dehors),
`source` (`datatourisme`, `google`), `credit` et `credit_url` (son auteur et son lien), `licence`, `caption`, `width`,
`height`.

Les parties d'une fiche de lieu :

- `osm` (OpenStreetMap) : `id`, `url` (sa page sur openstreetmap.org), `address`, `phone`, `website`, `email`, `hours`
  (le texte d'`opening_hours`), `hours_text` (la semaine en clair), `facts` (`[{"label", "value"}]` : « Cuisine »,
  « Horaires », « Téléphone », « Terrasse »…, seulement ce qui est renseigné), `wikidata`, `wikipedia`, `extract` (la
  date de l'extrait), `attribution` (« © les contributeurs d'OpenStreetMap ») et `licence_url`. Ouvert ou fermé à
  l'instant : `place.open_state` et `place.open_text`.
- `tourism` (DATAtourisme, l'office de tourisme) : `id` (`t:<uuid>`), `description` (en paragraphes), `labels`,
  `prices`, `contacts` (`[{"label", "value"}]`), `author` (qui l'a écrite), `updated` (sa mise à jour, `AAAA-MM-JJ`),
  `url`, `photos`, `attribution` (« DATAtourisme · Hello Lille, mis à jour le 5 décembre 2023 »), `licence` (« Licence
  Ouverte 2.0 ») et `licence_url`.
- `reviews` (Google Places) : `source` (`google`), `source_label` (« Google Maps »), `found` (faux : Google n'a rien de
  ce lieu, ou on n'a pas pu chercher — `note` dit lequel), `id`, `rating`, `count`, `price` (« €€ »), `price_range`
  (« 20–40 € »), `summary` (le résumé de Google), `facts` (ce que Google dit et qu'OpenStreetMap ne dit pas :
  « Terrasse » « oui (selon Google) »), `reviews` (cinq au plus : `rating`, `text` en paragraphes, `author`,
  `author_url`, `at` en ms, `relative` « il y a un mois », `language`), `photos`, `url` (sa page chez Google Maps),
  `cached` (quand ce serveur l'a lue, en ms), `note`.
- `events` : les événements à venir qui s'y tiennent ou tout près (trente jours, six au plus).

**Ce qu'un client montre avec**, toujours : « Google Maps » et le lien `reviews.url` avec la note et les avis ; l'auteur
(`author`, lien `author_url`) de chaque avis et le crédit (`credit`, lien `credit_url`) de chaque photo, à côté
d'elle, avec sa `licence` (une photo de l'office de tourisme, dans la bande d'une fiche comme dans la visionneuse) ;
l'`attribution` de l'office de tourisme (son auteur et sa date) avec ce qu'il en dit, et celle d'une fiche
d'événement ; « © les contributeurs d'OpenStreetMap » sous ce qui vient d'OpenStreetMap ; la `note` d'une partie quand
elle n'est pas vide. Dans une liste (ADR 0269) : la vignette d'un lieu ou d'un événement montre `photo_credit` (lié à
`photo_credit_url`) et `photo_licence` sur sa ligne, lisibles — jamais dans le seul texte alternatif ; sans
`photo_credit`, pas de vignette ; et « Google Maps » se lit dès qu'un lieu de la liste a une note, quelle que soit la
couverture (une zone trop grande pour la compter, une `note` qui ne nomme pas Google), dans un regard de Mika aussi.

**« Ici »** (`near=ici`) : ta dernière position, celle que ton téléphone a donnée (ADR 0119 : l'application ouverte, si
tu l'as permis), la tienne seule — jamais celle d'une autre personne. Aucune (jamais donnée, effacée, oubliée) : 409,
`fields.near`. **Le préchargement** (ADR 0250, 0256) : quand ton téléphone donne sa position, et quand tu cherches
autour de toi (`near=ici`, ou `here=1` avec ta propre position), les avis de ta case et des huit d'à côté se mettent
en file, lus en fond sur ce qui reste des quotas — seules les cases partent vers Google, jamais la position ; la
réponse n'attend pas. Au plus dix fois par compte et par dix minutes (au-delà, rien, sans le dire). Un point de la carte
qu'on regarde n'est pas toi : il ne précharge rien.

**Le fond de carte** (ADR 0193, 0229) — celui de toutes les cartes (Téléphone › Position, l'écran Carte, les miniatures
du chat), servi par ce serveur seul, à qui est connecté (il n'est à personne) ; d'où viennent ses tuiles se règle dans
la console (Réglages › Carte et téléphone › Carte de sa position). Ces routes sont les seules dont le navigateur garde
les réponses (`Cache-Control: private, max-age=86400`).

- **`GET /api/moi/carte/fond`** — `ready` (sinon `reason`, en mots, et le client garde son plan dessiné : aucune carte
  réglée, pour tout le monde ; d'une carte réglée qui ne se lit pas, une personne lit « La carte n'est pas encore
  prête sur ce serveur. », une opératrice ce qui ne va pas — un fichier absent, un serveur injoignable, une archive à
  refaire ; un serveur de carte se revérifie au plus une fois par minute), `kind` (`vecteur` : au schéma Protomaps ;
  `image`),
  `minzoom`, `maxzoom`, `bounds` (ouest, sud, est, nord ; `null` : partout), `attribution`, et les chemins de l'API
  à poser sur l'adresse du serveur : `tiles` (`…/tiles/{z}/{x}/{y}?v=<version>`), `glyphs`
  (`…/fonts/{fontstack}/{range}.pbf?v=<version>`, `null` sans polices : une carte sans noms), `sprite`
  (`…/sprites/~<version>/v4`, la planche suit : `/light`, `/dark` ; `null` sans icônes). `<version>` (douze chiffres
  hexadécimaux) change avec la source — le réglage, la date et la taille du fichier, l'en-tête et la version d'une
  archive distante — : le navigateur, qui garde un jour ce qu'il a lu, ne ressert jamais d'une carte ce qu'il gardait
  d'une autre ; les routes l'acceptent et l'ignorent.
- **`GET /api/moi/carte/fond/tiles/{z}/{x}/{y}`** — une tuile, telle que l'archive la garde (`Content-Encoding: gzip`
  pour Protomaps : le navigateur l'ouvre) ; aucune là (hors de la zone, hors des zooms) : 204, une tuile vide ;
  aucune carte réglée : 404 ; la carte ne se lit pas : 503, dit à chacun comme `reason`.
- **`GET /api/moi/carte/fond/fonts/{pile}/{plage}.pbf`** — une plage de glyphes, de la première police de la pile qui
  est là ; **`GET /api/moi/carte/fond/sprites/v4/{planche}.json|.png`** (`@2x` compris, précédé ou non de `~<version>/`) — les icônes. Rien en dehors
  de leur dossier : 404.
- L'adresse d'avant, sous le téléphone (`/api/moi/phone/map/…`), n'existe plus : 404.

### Tes voyages

Un voyage est à toi seule : celui d'une autre personne n'existe pas (404). Chaque écriture passe par une action du
plugin `trips`, en ton nom (`by` : ton adresse), et se dédoublonne par la clé d'envoi (§ 1 : une création redite rend le
même `id`) ; un voyage changé entre la lecture et l'écriture : 409 (« La situation a changé… »), renvoie. Un arrêt que
Mika a ajouté porte `"by": "mika"` (rose), un des tiens `"toi"` ; tu le retires comme un autre. Les identifiants sont
des nombres (le `seq` de leur création), en chaînes. Un opérateur peut aussi supprimer un de tes voyages depuis la
console (ta fiche, onglet Voyages, ADR 0204) : il disparaît de ta liste, et le relire répond 404.

| Route | Corps | Ce que ça fait |
|---|---|---|
| `GET /api/moi/voyages` | — | `{"trips": [{"id", "title", "start", "mode", "avoid", "days", "stops", "updated", "mika"}]}`, le plus récemment changé d'abord — `start` : `AAAA-MM-JJ`, ou vide ; `days`, `stops` : combien ; `mika` : elle l'a préparé avec toi |
| `POST /api/moi/voyages` | `title`, `start?`, `mode?`, `avoid?` | `{"ok", "message", "id"}` — un titre de 120 caractères, une date `AAAA-MM-JJ` d'une année de 1900 à 2200 (400 sinon) ; 50 voyages au plus (409 au-delà) |
| `GET /api/moi/voyages/<id>` | — | `{"id", "title", "start", "mode", "avoid", "updated", "mika", "days": [{"n", "date", "stops": [{"id", "name", "kind", "lat", "lon", "note", "by"}]}]}` — du jour 1 au dernier qui a un arrêt (un jour vide entre deux compris) ; `date` : celle du jour, si le voyage en a une |
| `POST /api/moi/voyages/<id>` | `title?`, `start?`, `mode?`, `avoid?` | le modifier : ce que le corps nomme, seulement (`start` vide : plus de date ; rien de nommé : 400) |
| `POST /api/moi/voyages/<id>/supprimer` | — | le supprimer, ses arrêts avec |
| `POST /api/moi/voyages/<id>/arrets` | `name`, `lat`, `lon`, `kind?`, `day`, `index?`, `note?` | `{"ok", "message", "id"}` — un arrêt au jour `day` (1 à 30), à la place `index` de ce jour (0 : la première ; −1, par défaut : à la fin) ; 60 arrêts au plus (409) ; `note` : 500 caractères |
| `POST /api/moi/voyages/<id>/arrets/<arrêt>` | `day` et `index?`, et/ou `note` | le déplacer, le noter (`note` vide : plus de note), ou les deux |
| `POST /api/moi/voyages/<id>/arrets/<arrêt>/retirer` | — | le retirer |
| `GET /api/moi/voyages/<id>/trajet` | — | `{"days": [{"n", "distance_m", "duration_s", "legs": [{"from", "to", "distance_m", "duration_s", "shape", "steps"}]}], "distance_m", "duration_s", "has_toll", "has_highway", "has_ferry", "provider"}` : les tronçons d'un arrêt au suivant, rangés au jour de leur arrivée (`from`, `to` : les arrêts) ; sans itinéraires : 503 |
| `POST /api/moi/voyages/<id>/ordre` | `day` | le meilleur ordre de ce jour, appliqué (son premier et son dernier arrêt restent à leur place) → `{"ok", "message", "order"}` ; moins de trois arrêts : rien à faire ; plus de 20 : refusé (400), le serveur d'itinéraires n'en range pas plus d'un coup ; un ordre illisible du serveur : 502, rien n'est appliqué |
| `GET /api/moi/voyages/<id>/sur-la-route?cat=&day=&corridor=&limit=` | — | `{"places": [lieu…], "route"}` : les lieux à moins de `corridor` mètres (200 à 50 000 ; 5 000) du trajet de tout le voyage (`day` 0, par défaut) ou d'un jour (depuis le dernier arrêt de la veille), dans l'ordre où on les croise ; `limit` : 1 à 50 (20) ; `route` faux : sans itinéraires, le long des arrêts reliés à vol d'oiseau |
| `GET /api/moi/voyages/<id>/gpx` | — | le voyage en GPX 1.1 (`application/gpx+xml`, en pièce jointe `voyage-<id>.gpx`) : ses arrêts dans l'ordre, et le tracé quand les itinéraires le calculent |

## 11. Projets

Ce que l'écran Projets montre (ADR 0282) : ses projets, ce qui l'y attend, la fiche d'un projet, son registre (tickets
et listes de suivi), ses liens, **son code** (ADR 0288 : fichiers, commits, branches, pull requests, issues, CI),
**sa documentation** (ADR 0289 : un espace à part de son dépôt, ses pages et ses images, qui s'écrit ici) ; et
ses gestes, dont **fusionner une pull request**. **Ce qu'elle y voit s'y modifie** (ADR 0290) : le projet (le
confier, le modifier, l'archiver), ses objectifs, ses jalons, un ticket, une pull request, ses décisions ; et **son
activité** s'y lit — son fil, ses exécutions, son carnet, le diagramme de ses objectifs. Régler ses lignes d'accès,
régler une liste et publier un ticket chez l'hôte du dépôt **restent à la console**.

**Ce qu'elle a d'un projet** n'est pas une règle d'ici : c'est la plus serrée de ce que les lignes d'accès du projet
lui donnent hors de toute conversation (son projet en entier ; celui d'un autre seulement par une ligne qui la désigne,
partout et toujours — la ligne par défaut n'ouvre rien) et de ce que la conversation lui en dirait par ce client (le
chat web pour un navigateur, l'app pour un jeton), au niveau de confidentialité qu'elle en entend.

- Un projet est **à elle** (`mine`) quand elle en est le propriétaire (il est fait pour elle), ou qu'il est à Mika
  (`hers`) et qu'elle s'occupe d'elle. Un opérateur n'a ici que les droits de sa personne : la console lui montre
  tout, cette API non.
- **Le voir** donne son titre et son état. **Son détail** (`detail`) demande de le piloter au moins en lecture seule
  et d'entendre son niveau ; sans lui, toute route de détail répond 403 (« Ce projet ne t'est ouvert qu'à voir… »).
- **Le piloter** (`steer`, en mots dans `steer_label`) : `non`, `lecture` (lire), `accord` (ouvrir un ticket, qui naît
  proposé, et noter), `modification` (aussi changer un statut, donner une consigne, lancer, mettre en pause,
  reprendre). **Trancher** (un ticket, un point d'arrêt) est au propriétaire du projet et à qui s'occupe d'elle ;
  **répondre à son plan**, à qui l'a demandé et à qui s'occupe d'elle ; **poser ce qu'il lit**, à son propriétaire ;
  **donner un accord**, à qui s'occupe d'elle.
- Un projet qu'on ne lui ouvre pas, archivé, ou inconnu : 404, la même réponse. Un geste que son niveau n'ouvre pas :
  403, dit en mots. Un geste qui ne vaut plus (déjà tranché, déjà en pause, un statut qu'il a déjà) : 409 ; un champ
  refusé : 400 avec `fields`.

Les codes d'étape et de statut ont leurs mots à côté (`…_label`), comme les sortes et les priorités d'un ticket, la
raison d'un geste qui ne se fait pas d'ici (`why`) et qui a écrit (`author`) : le client les affiche, il ne les traduit
pas et n'écrit pas les siens. Un texte **venu d'ailleurs** — un ticket ou une note de l'hôte du dépôt ou d'un autre projet (`outside: true`), un
commentaire de l'hôte, la fin d'un journal de CI, la sortie d'une commande, la ligne du dépôt distant (des objets
`{"text", "outside": true}`, ou `null`) — se présente comme tel : une donnée citée, jamais un mot d'elle ni du
propriétaire. Les textes sont bornés (8 000 caractères ; 400 pour une ligne).

### Lire

**`GET /api/moi/projets[?size=]`** — ses projets, ceux où quelque chose l'attend d'abord, et la première page d'« À
faire » (`size` : 25, 100 au plus) :

```json
{"projects": [{"id": 3, "title": "Outils réseau", "status": "active", "status_label": "actif", "mine": true,
               "hers": true, "owner_name": "", "steer": "modification", "steer_label": "modification",
               "detail": true, "where": "Le squelette est posé.", "last_run": 1790790000000, "plan": "planned",
               "plan_label": "validé", "waiting": 2}],
 "todo": [{"project": 3, "project_title": "Outils réseau", "kind": "ticket", "kind_label": "ticket",
           "what": "validation", "about": "#4 Journaliser les refus — son plan attend ta validation",
           "since": 1790790000000, "mine": true, "can": true, "why": "", "waits_for": "", "objective": 0,
           "number": 4, "key": "", "veiled": "", "outside": false,
           "gesture": {"route": "ticket/trancher", "args": {"item": "#4", "verdict": "validate", "plan": 812},
                       "label": "Valider ou refuser son plan", "where": "ici", "url": ""}}],
 "todo_total": 7, "create": {"can": true, "why": ""}}
```

- `create` : peut-elle lui confier un projet d'ici (`POST …/projets/nouveau/creer` : qui s'occupe d'elle), sinon
  pourquoi.
- `card` (ADR 0293, absent de l'exemple) : de quoi remplir la carte d'un projet sans lire sa fiche, pour qui lit
  son détail (`null` sinon) — `objectives` (ses ponctuels dans l'ordre du plan : `total`, `done`, `doing` — au moins
  une exécution —, `todo`, `blocked`, et `states` : `[{"id", "state", "state_label"}]`, un segment par objectif),
  `pulls_open`, `tickets_open`, `reads` et `readers` (ce dont il dépend, ce qui dépend de lui : `project`, `title`,
  `visible` — un projet qu'elle ne voit pas : `null`, `""`, `false`), `led_by` (par qui il est mené : son nom à
  elle), `last_activity` (la dernière fois que quelque chose y a bougé).
- `status` : `active`, `paused`. `hers` : un projet à Mika ; `owner_name` : pour qui il est, quand ce n'est pas elle.
  `where` (où il en est, son dernier compte rendu), `last_run`, `plan` (`""` sans plan, `to_frame`, `proposed`,
  `planned`) : vides sans le détail. `waiting` : ce qui l'attend, elle, dans ce projet.
- **Une attente** (`todo`) : `kind` — dans l'ordre où s'en occuper, celui du serveur : `approval` (un accord), `plan`,
  `need` (elle a besoin de toi), `stalled` (arrêté par ses pannes), `blocked` (un objectif bloqué), `ticket`,
  `checkpoint` (un point d'arrêt dit prêt), `review` (ses relectures l'ont refusé deux fois), `item` (un élément d'une
  liste à ta charge) ; `what` : la capacité d'un accord, ce qu'un ticket attend (`accept`, `question`, `dismissal`,
  `validation`, `merge`, `stuck`), le nom de la liste d'un élément ; `about` : de quoi il s'agit, en une ligne ;
  `mine` : c'est elle qu'on attend (« À faire » ne rend que celles-là ; la fiche les rend toutes) ; `waits_for` : qui
  elle attend — la personne nommée ; pour un accord, qui s'occupe d'elle, par son prénom ; sinon vide (le
  propriétaire du projet) ; `veiled` : un élément qu'elle ne peut pas lire (ni titre ni clé).
- **Une attente est comptée pour qui peut la régler** (`mine`, la règle du moteur : `todo.awaits`) : la personne
  nommée, sinon le propriétaire du projet — sauf un accord, qui n'attend que qui s'occupe d'elle, même dans un projet
  confié à quelqu'un d'autre (son propriétaire le voit attendre sur la fiche, `mine: false`). La console dit de même.
- **Le geste** (`gesture`) : `where` — `ici` : `POST /api/moi/projets/<project>/<route>` avec `args`, à compléter
  (une raison, un statut… ; pour fusionner une pull request — `code/pull/fusionner`, `args: {"number"}` —, le commit
  lu, `head`, que rend `GET …/code/pull` ; pour un objectif bloqué, `objectif/statut` avec `status: "open"`) ; `console` : rien ici ne le fait ; `hote` :
  chez l'hôte du dépôt (une pull request prête dont le numéro n'est pas encore connu). `url` : pour une pull request à
  fusionner, sa page chez l'hôte — composée par le serveur de l'adresse du dépôt et de son numéro, jamais prise dans
  un texte de l'hôte ; vide sinon, sans dépôt distant, ou pour un ticket qu'elle ne lit pas. `can` : elle peut le faire ici — la garde de la route, dite
  d'avance : ne pas la recalculer.
- **Pourquoi pas** (`why`) : vide quand `can` ; sinon la raison, en mots à afficher tels quels — elle ne pilote pas ce
  projet, ce geste demande l'accord de son propriétaire (il se demande dans le chat), ce n'est pas à elle de trancher
  ni de répondre à ce plan, cet accord n'est pas le sien, l'élément ne se lit pas d'ici, le projet ne lui est ouvert
  qu'à voir, le geste se fait dans la console, ce n'est pas à elle de fusionner, ou ce qui retient la pull request
  (un conflit, des vérifications en cours…). C'est, mot pour mot, le refus que la route
  rendrait (403) : elle n'y apprend rien qu'elle n'apprendrait en essayant.

**`GET /api/moi/projets/a-faire[?page=&size=]`** — « À faire » pour tous ses projets : `{"total", "page", "size",
"items"}`, les mêmes entrées.

**`GET /api/moi/projets/accords[?project=]`** — ce qui attend **son** accord (rien pour qui ne peut pas le donner), 20
au plus : `{"items": [{"id", "project", "project_title", "capability", "label", "summary", "text", "digest",
"blocked", "at"}]}` — `text` est exactement ce qui partirait, `digest` son condensé, à renvoyer pour l'accepter tel
qu'il a été lu ; `blocked` dit pourquoi il ne peut pas partir tel quel. Et ce qu'il concerne (ADR 0293) :
`concerns` — `objective` (0 : aucun), `ticket` (le ticket en une ligne — voir « Un ticket en une ligne » —, ou
`null`), `issue` et `pull` (leurs numéros chez l'hôte, 0 : aucun) — ; `where` (où cela part, en mots : chez l'hôte en
issue ou en pull request, vers son dépôt distant, sur le réseau depuis son atelier, dans ce projet) et `where_url`
(sa page chez l'hôte, composée ici ; vide sinon) ; `asked_by_kind` et `asked_by` (qui l'a demandé : elle, ou la
personne dont elle porte la demande, selon la règle des noms) ; `why` (les mots de cette personne, pour un pilotage
demandé ; vide ailleurs : la raison d'une commande réseau est dans `summary`).

**`GET /api/moi/projets/<id>`** — la fiche. Qui ne fait que le voir reçoit `project`, `rights` et `todo` (ce qui est
à sa charge), rien d'autre.

- `project` : la ligne de la liste, plus `description`.
- `rights` : ce qu'elle peut faire par les routes d'ici — `steer`, `steer_label`, `detail`, `ticket` (en ouvrir un),
  `ticket_born` (`open`, `proposed`, ou vide), `note`, `status` (changer un statut), `settle` (trancher), `plan` (y
  répondre), `pilot` (consigne, lancer, pause, reprise), `links` (poser ce qu'il lit), `approve` (donner un accord),
  `files` (lire le contenu de ses fichiers et ses diffs), `merge` (fusionner ses pull requests), `frame` (changer son
  cadre), `edit` (ses objectifs, ses jalons, ses tickets, ses décisions), `pull_write` (écrire chez l'hôte sur une
  pull request), `work` (lire son activité).
- `todo` : ce qui attend dans ce projet (60 au plus), le sien (`mine`) et celui du propriétaire.
- `missions` (ses objectifs constants) : `id`, `text`, `status`, `status_label`, `cadence_hours` (0 : la cadence par
  défaut), `cadence_label`, `on` (ce qui la déclenche : `[{"key", "label"}]`), `only_on_event`, `last_run`,
  `passes`, `each_pass` (ce que chaque passage doit faire), `need`.
- `next` (ADR 0293) — son prochain passage : `at` (0 : rien n'est daté), `state` (`due` : daté ; `running` : une
  exécution est en cours ; `paused` ; `on_demand` ; `idle` : rien de prévu) et `state_label`, `sort` (`frame` : sa
  séance de cadrage, `review` : une relecture, `run` : du travail ; vide) et `sort_label`, `objective` (`id`, `text`,
  `kind` ; `null`). Le moteur n'estime rien : sans date, `at` vaut 0.
- `rhythm` : `schedule` (son agenda en mots), `window` (sa plage en mots), `summary` (les deux, en une phrase — celle
  de `…/reglages`).
- `instructions` — ses consignes en attente, données depuis le départ de sa dernière exécution (8 au plus, les plus
  récentes d'abord) : `seq`, `at`, `text`, `veiled` (d'un niveau qu'elle n'entend pas : le texte n'est pas servi),
  `author_kind`, `author`.
- `forms` — de quoi remplir les formulaires d'un objectif et d'un jalon : `can`, `why` ; `triggers` (ce qui peut
  déclencher une mission, à envoyer tel quel dans `on` : `key`, `label`, `sort` — `project`, `app`, `item`, `wake` —,
  `sort_label`, `project` et `title` pour un projet dont il dépend) — les projets qu'il lit **et qu'elle voit**, ses
  apps, ses listes, ceux que ses missions ont déjà ; les réveils de l'instance ne sont servis qu'à qui s'occupe
  d'elle — ; `triggers_max` ; `checks` (les façons de vérifier un jalon : `code`, `label`, `help`, et `fields` — ce
  qu'il faut saisir pour elle : `name`, `label`, `help`, `required`).
- `objectives` (ses ponctuels, les ouverts d'abord, 40 au plus) : `id`, `text`, `status` (`open`, `blocked`, `done`),
  `status_label`, `done_when`, `ticket` (le ticket dont il est né), `need`, `note`, `result`, `runs`, `last_run`,
  `closed_at`, `branch`, `tickets` (ceux qui lui sont liés — celui dont il est né, ceux qu'il tient —, chacun en une
  ligne), et :
  - `milestones` : `id`, `text`, `check` (`prose`, `command`, `owner` : un point d'arrêt, `item`), `check_label`,
    `status` (`open`, `reached`, `dropped`), `status_label`, `ready` (un point d'arrêt qui attend), `ready_at`,
    `reached_at`, `refused_at`, `how`, `proof` (venu d'ailleurs), `reason`, `commit`, `started` (elle s'y est mise :
    une exécution est partie depuis que le jalon d'avant est atteint), ce qui le lie à un élément de son registre
    (`item_list`, `item` — sa clé —, `item_status` et `item_status_label` ; vides sinon), et `command` (sa commande,
    telle qu'on la taperait — **seulement avec le droit sur ses fichiers**, vide sinon) ;
  - `pull` (`null` sans pull request) : `number`, `title`, `url`, `state` (`open`, `merged`, `closed`), `state_label`,
    `words` (où elle en est, en une ligne), `changes_asked`, `conflicts`, `at`, `awaits_accord` (la proposition qui
    attend, 0 sinon), `said` (le dernier mot de l'hôte, venu d'ailleurs) ;
  - `checks` (`null` sans CI lue) : `state` (`pending`, `passed`, `failed`), `state_label`, `sha`, `at`, `said` (la
    fin du journal, venue d'ailleurs) ;
  - `review` (`null` : pas encore relu) : `ok`, `label`, `at`, `text`, `refused` (combien de fois de suite),
    `handed_over` (la main est au propriétaire), `last_refusal`.
- `plan` : `state`, `state_label`, `text`, `questions`, `at`, `version`, `asked_by`.
- `lists` : chaque liste — `name`, `title`, `tickets` (c'est la liste des tickets), `open` et `closed` (ses statuts :
  `[{"code", "label"}]` ; pour les tickets, leurs étapes), `counts` (par statut), `total`, `living` (encore ouverts),
  `actor`, `actor_label`. La liste des tickets dit aussi ce qu'il faut pour **en ouvrir un** : `kinds` (ses sortes :
  `[{"code": "bug", "label": "défaut"}, …]`) et `priorities` (`[{"code": "low", "label": "basse"}, …]`), dans l'ordre
  du moteur, avec `kind_default` et `priority_default` — ce qu'un ticket reçoit quand `POST …/ticket` n'en dit rien.
  Pour une liste de suivi : `[]` et `""`. La liste des tickets les compte aussi par étape du parcours (`journey` :
  `[{"code", "label", "count"}]`, les six étapes — voir « Le parcours d'un ticket »). Une liste de suivi dit ce
  qu'elle peut y faire (`can` : `add`, `assign`, `why`) et à qui un élément peut être (`actors` : `self`, `owner`,
  avec leurs mots).
- `links` : `reads` (ce qu'il lit : `project`, `title`, `visible`, `suspended`, `direct`, `gives` — `see`, `detail`,
  `files`, `docs` (sa documentation, ADR 0289), `ask`, `ask_label`), `plan_asks` (ce que son plan demande à lire), `readers` (qui le lit, et ce qu'il en
  reçoit), `asks` (ses demandes à d'autres projets) et `received` (celles qu'il a reçues — voir « Les demandes »), `can`
  (elle peut poser ses liens), `labels` (les mots de cette vue, qui s'appelle « Dépendances » : `title`, `reads` —
  « Il dépend de » —, `readers` — « Dépendent de lui » —, `asks` — « Ses demandes »), `candidates` (ceux qu'elle peut lui faire lire — ceux qu'il peut se mettre à lire et
  qu'elle voit : `project`, `title`, `visible`, et `gives`, ce que le lien donnerait maintenant ; `see: false` : il ne
  donnerait rien pour l'instant ; vide si elle ne pose pas ses liens). **Un projet lié ne dit son numéro et son titre
  que si elle le voit elle-même** : sinon `project: null`, `title: ""`, `visible: false` — ce que le lien donne se
  dit, quel projet, non ; un tel lien ne se retire pas d'ici (il reste tel quel).
- **Par lien** (ADR 0293), sur `reads[]` : `since` (depuis quand il est posé), `why` (le mot de son propriétaire —
  vide s'il n'en a pas, ou si elle ne voit pas le projet lu), `commit` (le commit que montre la vue de son atelier :
  `sha`, `short`, `title`, `at` — pour qui lit le détail du projet lu, quand le lien donne ses fichiers ; `null`
  sinon), `asks` (les demandes entre les deux : celles du projet, et les tickets qu'elle y a ouverts elle-même) et
  `ask_here` — **« Lui demander quelque chose »** : peut-elle ouvrir un ticket chez ce projet, avec les droits
  qu'elle a sur lui (`can`, `why`, `born` — `open`, `proposed` —, `project`, et `route` : `ticket`, c'est
  `POST /api/moi/projets/<project>/ticket`) ; un projet qu'elle ne voit pas : `can: false`, sans un mot. Sur
  `readers[]` : `since`, `why` (**pour qui lit aussi le détail du projet lecteur** : le mot est un texte de ce
  projet-là) et `asks` (ce qu'il lui a demandé).
- **Les demandes** (`links.asks`, `links.received`, et `asks` de chaque lien ; 20 au plus, les plus récentes
  d'abord) : `project`, `title`, `visible` (l'autre projet, nommé seulement si elle le voit), `direction` (`sent`,
  `received`), `from` (`project` : une demande du projet, ADR 0271 ; `you` : un ticket qu'elle a ouvert elle-même
  chez le projet lié), `number` (0 si elle ne voit pas le projet où vit le ticket), `title` (seulement si elle lit ce
  ticket là-bas ; sinon `""` et `veiled: true`), `status` et `status_label` (son étape fine), `step` et `step_label`
  (son étape du parcours), `at`, `closed_at`. Les demandes reçues sont celles que l'état du projet garde (ses
  tickets ouverts, les derniers touchés).
- `repo` : `has_remote`, `remote` (son adresse, pour un projet à elle seulement), `branch`, `flow` (`direct`, `pr`),
  `flow_label`, `auto_push`, `last_commit`, `remote_ok`, `remote_at`, `remote_line` (venue d'ailleurs), `commit` (son
  dernier commit, lu dans le dépôt de l'atelier : `sha`, `short`, `title`, `at`, `author_kind`, `author`, `outside`,
  `branch` ; `null` sans dépôt — le détail donne les titres de ses commits, comme `…/code`).

**`GET /api/moi/projets/<id>/elements[?list=&state=&status=&q=&page=&size=]`** — une page d'une liste (`list` : par
défaut `tickets`), les derniers touchés d'abord : `{"list", "total", "page", "size", "items"}`. `state` : `open`,
`closed`, ou rien ; `status` : un statut de la liste (une étape, pour les tickets) ; `q` : 120 caractères, ne compare
que ce qu'elle peut lire. Une liste inconnue : 404. Un élément :

```json
{"list": "tickets", "handle": "#4", "number": 4, "key": "plan-journal", "title": "Journaliser les refus",
 "veiled": "", "veiled_label": "", "status": "validation", "status_label": "en attente de validation",
 "open": true, "hand": "owner", "hand_label": "au propriétaire", "yours": true, "kind": "task",
 "kind_label": "tâche", "priority": "normal", "priority_label": "normale", "actor": "self", "actor_label": "elle",
 "author_kind": "person", "author": "Adrien Moreau", "outside": false, "objective": 0, "notes": 1, "at": 1790790000000,
 "updated_at": 1790790060000, "plan": 812, "issue": 0, "pull": 0, "step": "validation",
 "step_label": "Validation", "issue_state": "", "issue_state_label": ""}
```

`status` d'un ticket, son étape : `proposed`, `unread`, `analysis`, `decision`, `validation`, `working`,
`pr_pending`, `pr_ready`, `treated`, `dismissed`. `hand` : à qui est la main (`owner`, `self`) ; `yours` : à elle,
et elle peut trancher. `veiled` : pourquoi ses textes ne se lisent pas — `proposed` (proposé par un autre projet ou
venu de l'hôte : il se lit quand son propriétaire l'a accepté, et par qui peut le trancher), `level` (d'un niveau
qu'elle n'entend pas) ; alors `title` et `key` sont vides. `plan` : le numéro de son plan (0 : aucun). `issue_state`
(`open`, `closed`, ou vide) : ce que l'hôte a dit en dernier de son issue.

**Le parcours d'un ticket** (ADR 0293) a **six étapes** : `unread` (non lu), `analysis` (en analyse), `validation`,
`pull` (pull request), `merge` (fusion), `treated` (traité). Les étapes fines (`status`) restent servies comme avant :
chacune tombe dans l'une des six, dont elle est la précision — proposé : non lu ; sa question posée : en analyse ;
validé, en cours : pull request, ou traité s'il ne passe pas par une pull request ; pull request en cours : pull
request ; prête à fusionner : fusion. `step` et `step_label`, sur chaque ligne : son étape du parcours (vide : écarté,
ou pas un ticket). **Un ticket qui ne produit pas de code saute `pull` et `merge`** — un projet au flux direct, une
réponse dans son fil : le parcours le dit (`through_pull: false`, `skips`, `skips_label`).

**Un ticket en une ligne** (sur un objectif, un accord) : `number`, `handle`, `title` (vide s'il ne se lit pas),
`veiled`, `veiled_label`, `status`, `status_label`, `step`, `step_label`, `open`.

**Qui a écrit** un élément ou une note : `author_kind` — `self` (elle), `you` (la personne connectée), `person` (une
autre personne), `project` (un autre projet, qui lui adresse une demande), `host` (quelqu'un chez l'hôte du dépôt) — et
`author`, les mots à afficher : son nom à elle ; « toi » ; le nom de la personne, **seulement si elle a le droit de le
savoir**, sinon « une autre personne » ; « le projet « titre » » si elle voit ce projet, sinon « un autre projet » ;
« quelqu'un chez l'hôte du dépôt » (le compte de l'hôte n'est jamais servi). Le nom d'une autre personne se sert quand
elle s'occupe d'elle (sa voix la nomme à tous), ou quand ce qui concerne cette personne s'entend par ce client au
niveau de l'élément (la règle de sa mémoire sur autrui, comme pour le projet) ; rien n'est nommé d'un élément qu'elle
ne lit pas (`veiled`).

**`GET /api/moi/projets/<id>/element?list=&item=`** — un élément (`item` : `#n` pour un ticket, sa clé sinon) : les
champs d'une ligne, plus `body`, `link`, `thread` (son fil, les 50 dernières notes : `seq`, `at`, `author_kind`,
`author` — qui l'a écrite, comme pour un élément —, `kind` — sa sorte : `note` (une note), `change` (ce qui a été dit
d'un changement), `question` (sa question), `plan` (son plan) —, `kind_label`, `text`, `outside`), `plan_text` (le
plan à lire avant de le valider), `small`, `statuses` (ceux de sa liste, vide pour un ticket), `journey` (pour un
ticket, sinon `null` : `steps` — les six, chacune `code`, `label`, `state` (`done` : passée, `current` : en cours,
`todo` : à venir, `skipped` : sautée), `state_label` —, `current` et `current_label`, `fine` et `fine_label` (son
étape fine et ses mots, la précision de l'étape en cours), `through_pull`, `skips`, `skips_label`, `ended` — vide,
`treated`, `dismissed` — et `ended_label` ; fermé, une étape n'est passée que si un fait le dit), `linked` (ce qui lui
est lié : `objective` — `id`, `text`, `status`, `status_label` —, `pull` et `checks`, comme sur la fiche ; `null`
chacun) et `can` : `note`, `status`, `assign` (changer à qui il est : un élément d'une liste de suivi), `accept`,
`dismiss`, `dismiss_needs_reason`, `validate`, `refuse`, `modify`, `close` (le fermer comme traité), `reopen`. Un élément qu'elle ne peut pas lire rend ses faits, sans
texte ni fil.

**`GET /api/moi/projets/<id>/element/historique?item=`** — l'histoire des étapes d'un ticket (ADR 0293), rejouée de
son journal par les règles de l'état, de la plus ancienne à la plus récente : `{"item", "cut", "items"}` — `seq`,
`at`, `status` et `status_label` (l'étape où il entre), `was` et `was_label` (celle qu'il quitte ; vide : sa
naissance), `step`, `step_label`, `author_kind`, `author` (qui l'y a fait passer, selon la règle des noms),
`outside`. Des faits, aucun texte : un ticket qu'elle ne peut pas lire la rend aussi, sans un nom. `cut` : trop
d'événements (2 000) pour tout rejouer.

### Écrire

Chaque geste passe par l'action que la console déclare pour lui, au nom de la personne (auditée
`moi.projects.<action>`, dédoublonnée par la clé d'envoi, § 1), après la garde de l'outil de conversation du même
geste. `<id>` : le projet.

| Route | Corps | Qui | Ce que ça fait |
|---|---|---|---|
| `POST /api/moi/projets/<id>/plan` | `verdict` (`approve`, `revise`), `words?` | qui a demandé le projet, ou qui s'occupe d'elle | valider son plan (ce qu'il demandait à lire se pose si c'est son propriétaire), ou le lui faire reprendre avec `words` (2 000 caractères, exigés) ; plus de plan qui attend : 409 |
| `POST /api/moi/projets/<id>/ticket` | `title`, `text?`, `kind?` (`bug`, `task`, `idea`, `question`), `priority?` (`low`, `normal`, `high`, `urgent`) — servis avec leurs mots par la fiche (`lists[].kinds`, `priorities`) | qui le pilote, sur accord ou en modification | ouvrir un ticket → `{"ok", "message", "number", "proposed"}` ; sur accord il naît **proposé** (son propriétaire l'accepte ou l'écarte) ; le même titre : 400 ; 200 tickets ouverts : 409 |
| `POST /api/moi/projets/<id>/element/noter` | `list`, `item`, `text` | qui le pilote, sur accord ou en modification | une note dans son fil ; sur un ticket qui pose une question, elle y répond (il repasse en analyse). Un élément qu'elle ne peut pas lire : 403 |
| `POST /api/moi/projets/<id>/ticket/trancher` | `item`, `verdict` (`accept`, `dismiss`, `validate`, `refuse`, `done` : le fermer comme traité, `reopen` : le rouvrir), `reason?`, `plan?` | le propriétaire du projet, ou qui s'occupe d'elle | accepter un ticket proposé ; l'écarter (`reason` exigée, sauf pour confirmer qu'elle l'écarte) ; valider son plan **en nommant le plan lu** (`plan` : son numéro, exigé — un plan réécrit depuis : 409, relire) : un objectif le porte, `reason` devient sa consigne ; le refuser (`reason` exigée). Un ticket qui n'attend pas ce verdict : 409 |
| `POST /api/moi/projets/<id>/jalon` | `objective`, `milestone`, `verdict` (`validate`, `refuse`), `reason?` | le propriétaire du projet, ou qui s'occupe d'elle | un point d'arrêt dit prêt : validé, il est atteint et elle reprend ; refusé (`reason` exigée), il lui revient. Un jalon qui n'attend pas : 409 |
| `POST /api/moi/projets/<id>/element/statut` | `list`, `item`, `status`, `note?` | qui le pilote en modification | le statut d'un élément d'une liste de suivi (pas d'un ticket : 409) ; un statut qui n'est pas de la liste : 400 ; déjà ce statut : 409 |
| `POST /api/moi/projets/<id>/element/ajouter` | `list`, `title`, `key?`, `text?`, `status?`, `actor?` (`self`, `owner`), `link?` | qui le pilote en modification | un élément de plus dans une liste de suivi → `{"ok", "message", "list", "key"}` ; un ticket s'ouvre par `…/ticket` (400) ; la même clé : 400 ; une liste inconnue : 404 |
| `POST /api/moi/projets/<id>/element/confier` | `list`, `item`, `actor` (`self` : à elle, `owner` : au propriétaire du projet) | qui le pilote en modification | à qui est un élément d'une liste de suivi (la main sur un ticket se déduit de son étape : 409) ; déjà à lui : 409 |
| `POST /api/moi/projets/<id>/piloter` | `what` (`instruct`, `now`, `pause`, `resume`), `text?`, `objective?` | qui le pilote en modification | une consigne (`text`), « vas-y maintenant » (sur `objective`, s'il est nommé), la pause, la reprise. Sur accord : 403, la demande se fait dans le chat, où elle la propose |
| `POST /api/moi/projets/<id>/liens` | `add?`, `remove?`, `direct_on?`, `direct_off?` (des numéros de projets, 12 au plus chacun), `why?` et `why_for?` | le propriétaire du projet | **ce qui change** dans ce qu'il lit, lien par lien : se mettre à lire (`add`), ne plus lire (`remove`), et pour un projet qu'il lit déjà, que ses demandes y entrent directement (`direct_on`) ou plus (`direct_off`). Elle ne nomme que des projets qu'elle voit : **un lien vers un projet qu'elle ne voit pas reste tel quel** ; le nommer, comme un projet inconnu ou qu'il ne peut pas lire : 400, la même réponse. Rien à changer dans l'envoi, le même projet ajouté et retiré, `direct_on` sur un projet qu'il ne lit pas encore, ou l'ancienne forme (`reads`, `direct` : toute la liste) : 400 ; rien de changé, ou la borne (4 projets lus) : 409. **Le mot d'un lien** (ADR 0293) : `why` (300 caractères) dit pourquoi ce projet lit le projet `why_for` — un projet qu'il lit ou se met à lire, et qu'elle voit (400 sinon) ; sans `why_for`, le seul projet de `add`. Il se dit en posant le lien, ou seul, plus tard ; un lien retiré le perd |
| `POST /api/moi/projets/<id>/accord` | `proposal`, `decision` (`accept`, `refuse`), `seen`, `note?` | qui s'occupe d'elle | décider de ce qui attend un accord dans ce projet (un envoi, une commande avec le réseau, une pull request, une issue, une note à publier, un pilotage demandé…) → `{"ok", "message", "status"}` (`approved`, `rejected`). Accepter exige `seen`, le `digest` lu (400 sans) ; ce qui partirait a changé, ou ne peut pas partir tel quel : 409, rien ne part ; déjà décidé, ou pas de ce projet : 404 |

L'action de projet du chat (`POST /api/projects/pending/<id>/approve`, `protocole-chat.md` § 4) reste celle des
opératrices ; celle d'ici porte le condensé lu et suit la personne.

### Le code d'un projet

Les six vues de l'onglet Code (ADR 0288), sous `/api/moi/projets/<id>/code`. Toutes demandent **le détail** du projet
(sinon 403, « Ce projet ne t'est ouvert qu'à voir… » ; un projet qu'elle ne voit pas : 404).

- **Le détail donne les titres et les états** : ses commits, ses branches, ses pull requests, ses issues, sa CI.
  **Le contenu demande le droit sur ses fichiers** (`rights.files`) — celui de ses lignes d'accès, hors de toute
  conversation et par ce client, au niveau de ce que le projet écrit : sans lui, l'arbre, un fichier et les commits
  d'un chemin répondent 403 (« Ce projet ne t'ouvre pas ses fichiers… »), et un commit, une branche ou une pull
  request se lisent sans leurs fichiers (`files: []`, `files_readable: false`, `files_why`).
- **D'où vient chaque chose.** Les pull requests, leur CI et leur relecture : du journal. Les fichiers, les commits,
  les branches et les diffs : du dépôt de l'atelier, à une référence (`ref` : une branche, ou l'identifiant d'un
  commit — rien d'autre ne se nomme). Ce que l'hôte est seul à savoir : relu chez lui à la demande, au plus soixante
  lectures par minute et par compte (429 au-delà) ; s'il ne répond pas, `error` le dit et le reste est vide.
- **Un chemin** (`path`, 1 000 caractères) est relatif à la racine du dépôt : absolu, ou qui remonte (`..`), il est
  refusé (400, `fields.path`) ; un lien symbolique se dit, il ne se suit pas. Une référence, un commit, un chemin ou
  un numéro inconnus : 404.
- **Un fichier caché ne sort pas d'ici** (ADR 0292) — un segment qui commence par un point (`.env`, `.gitignore`,
  `.github/…`), la règle du partage d'un fichier de projet : le nommer répond 403 (`fields.path`), même à qui lit ses
  fichiers ; l'arbre ne le liste pas (`hidden` : combien il en tait) ; un diff dit son chemin et ses comptes, sans ses
  passages (`hidden: true`, `why`). `.env` et ses variantes ne s'enregistrent jamais dans le dépôt d'un atelier.
- **Tout texte de l'hôte** est un objet `{"text", "outside": true}` (ou `null`) : le titre et le texte d'une pull
  request ou d'une issue, une étiquette, le nom d'une vérification, la fin d'un journal, le compte qui a écrit là-bas
  (`account`). Un commit venu du dépôt distant porte `outside: true` : son message et son auteur ne sont pas d'elle.
  Une issue qu'aucun ticket accepté ne reflète est le texte d'un inconnu : son titre, ses étiquettes, son texte et
  ses échanges ne se servent qu'à qui peut la trancher (sinon `veiled`, `title: null`).

**Un commit** (partout où il apparaît) : `sha`, `short`, `title`, `at`, `author_kind` (`self` : elle ; `other`),
`author`, `outside`, `branch` (celle de la base, ou la branche de travail qui le porte), `base`, `merge` (une fusion),
`files`, `insertions`, `deletions`, `objective` et `ticket` (ceux qui lui sont liés ; 0 : aucun), `url` (sa page chez
l'hôte, composée ici). **Ce qui est lié** (`objective`, `ticket`, `pull`, `checks`, ou `null`) : l'objectif (`id`,
`text`, `kind`, `status`, `status_label`), son ticket (`number`, `handle`, `title`, `veiled`, `veiled_label`, `status`
— son étape —, `status_label`, `open`, `hand`, `hand_label`, `yours`), sa pull request en bref (`number`, `title`,
`state`, `state_label`, `url`, `branch`, `checks`, `review`), ses vérifications (`state`, `state_label`, `sha`, `at`).

| Route | Ce qu'elle rend |
|---|---|
| `GET …/code` | le dépôt en bref : `has_repo`, `base`, `current` (la branche où l'atelier se trouve), `remote` (`has`, `web` : sa page chez l'hôte, `branch`, `flow`, `by_pulls`, `synced_at`), `rights` (`files`, `merge`), `counts` (`commits`, `branches`, `pulls_open`, `pulls_ready`, `issues_open`, `checks_failed`), `last_commit` |
| `GET …/code/fichiers[?ref=&path=]` | **droit sur les fichiers.** Un dossier à une référence (par défaut la base), un niveau à la fois : `ref`, `path`, `parent` (`null` à la racine), `readme` (le chemin de son README, ou vide), `hidden` (les entrées cachées qu'il tait), `items` (les dossiers d'abord, 1 000 au plus : `path`, `name`, `kind` — `dir`, `file`, `link`, `module` —, `kind_label`, `size`), `last_commit` |
| `GET …/code/fichier?path=[&ref=]` | **droit sur les fichiers.** Un fichier : `ref`, `sha` (le commit lu), `path`, `name`, `kind`, `kind_label`, `size`, `text` et `lines` s'il se lit (`readable`) ; sinon `binary`, `too_big` (plus de 400 000 octets) et `why`, en mots — un lien symbolique et un sous-module se disent aussi, sans contenu. `last_commit`, `history` (les dix derniers commits qui l'ont touché), `history_total`, `url` |
| `GET …/code/commits[?ref=&path=&page=&size=]` | l'histoire d'une branche, ou de toutes sans `ref`, du plus récent : `{"ref", "total", "page", "size", "items"}` (`size` : 30, 100 au plus). `path` : ceux qui ont touché ce chemin (droit sur les fichiers) |
| `GET …/code/commit?sha=[&path=&lines=]` | un commit : `commit` (plus `body`, son message entier, et `parents`), ses fichiers et leur diff (voir plus bas), `linked` |
| `GET …/code/branches` | `{"base", "items"}`, la base d'abord : `name`, `base`, `current`, `ahead` et `behind` (son avance et son retard sur la base), `head` (son dernier commit), et ce qui lui est lié (`objective`, `ticket`, `pull`, `checks`) |
| `GET …/code/branche?name=` | `branch` (la même ligne), `commits` (ceux qu'elle a d'avance, 200 au plus), ses fichiers changés avec leurs comptes, sans leurs passages (`files`) |
| `GET …/code/pulls[?page=&size=]` | ses pull requests, les prêtes d'abord : `number`, `title`, `state` (`proposed` : elle attend un accord avant de partir ; `open` ; `ready` : prête à fusionner ; `merged` ; `closed`), `state_label`, `url`, `branch`, `base`, `at`, `checks`, `review` (`ok`, `asked`, `label`, `at`, `commit`, `refused`, `handed_over`, ou `null`), `conflicts`, `changes_asked`, `awaits_accord`, `unsent`, `objective`, `ticket`, `merge` |
| `GET …/code/pull?number=[&path=&lines=]` | une pull request (`objective=` pour celle qui n'a pas encore de numéro) : `pull` — la ligne de la liste, plus `head` (**le commit au bout de sa branche : celui à nommer pour la fusionner**), `fork` (d'où elle s'écarte de la base), `done_when`, `result`, `milestones` (les jalons de son objectif et leurs preuves, comme sur la fiche), `review` (plus `by`, `text` : ses constats, `last_refusal`), `checks` (plus `said` : la fin du journal d'un échec), `said` (le dernier mot de l'hôte) — ; `commits` ; ses fichiers et leur diff |
| `GET …/code/pull/hote?number=` | ce que l'hôte en dit maintenant : `title`, `body`, `head`, `mergeable`, `state`, `at`, `read_at`, `talk` (ses commentaires et le texte de ses relectures, du plus ancien au plus récent, 60 au plus : `id`, `at`, `account`, `text`, `outside`, `from_here` — publié d'ici, sous le compte du jeton), `checks` (comme `…/ci/commit`), `error`. Sans dépôt distant lisible : 409 |
| `GET …/code/issues[?state=&page=&size=]` | les issues du dépôt, relues chez l'hôte (les cinquante dernières touchées) et celles que ses tickets connaissent : `{"total", "page", "size", "error", "items"}` — `number`, `url`, `title`, `veiled`, `veiled_label`, `state` (`open`, `closed`, ou vide si l'hôte ne l'a pas dite), `state_label`, `dropped`, `labels`, `comments`, `at`, `from_here`, `account`, `ticket` (celui qui la reflète, et son étape). `state` : `open`, `closed` |
| `GET …/code/issue?number=` | une issue : la même ligne, plus `body` et `talk` (ses commentaires), pour qui peut la lire ; `error` |
| `GET …/code/ci` | les vérifications que le moteur suit, par commit (celui de chaque pull request), les plus récentes d'abord, 40 au plus : `sha`, `state` (`none`, `pending`, `passed`, `failed`), `state_label`, `at`, `said` (la fin du journal d'un échec), `commit`, `branch`, `objective`, `pull` |
| `GET …/code/ci/commit?sha=` | les vérifications d'un commit de ce dépôt, relues chez l'hôte : `sha`, `state`, `state_label`, `at`, `read_at`, `runs` (une à une, 30 au plus : `name`, `state`, `state_label`, `started`, `at`, `seconds`), `failed`, `log` (`name`, `tail` : la fin du journal de la première en échec, ou `null`), `error`, `commit`, `linked` |

**Un diff** (`…/code/commit`, `…/code/pull` ; ses comptes seuls pour `…/code/branche`) : `files` — pour chacun `path`,
`status` (`added`, `modified`, `deleted`), `status_label`, `insertions`, `deletions`, `binary`, `cut`, `hidden` et
`why` (un fichier caché : sans passages), et `hunks` : ses
passages (`header`, et `lines` : `kind` — `" "`, `"+"`, `"-"` —, `old` et `new`, ses numéros avant et après, 0 quand
la ligne n'y est pas, `text`, 500 caractères au plus) : de quoi l'afficher unifié ou côte à côte —, `insertions`,
`deletions`, `cut` et `cut_label`, `files_readable`, `files_why`. Borné à `lines` lignes en tout (3 000, le plus
aussi) : au-delà, le fichier où la borne tombe est coupé, les suivants gardent leurs seuls comptes (`cut: true`), et
chacun se relit seul par `path=`. Un fichier binaire n'a pas de passages.

**Peut-elle la fusionner** (`merge`, sur chaque pull request) : `can` — la garde de la route, dite d'avance —, `why`
(en mots : ce n'est pas à elle, ou ce qui retient la pull request — pas ouverte, en conflit, des changements
demandés, des vérifications en cours ou en échec, un commit pas encore envoyé, une fusion déjà demandée, **un commit
tout juste parti dont l'hôte n'a pas encore dit les vérifications** : trois minutes au plus, pendant lesquelles il se
relit chaque minute), `asked`
(une fusion est en route : demandée, ou faite et pas encore relue chez l'hôte), `asked_at`, `asked_by`, `refused`
(pourquoi la dernière demande n'a pas abouti, en mots) et `refused_at`.

**`POST /api/moi/projets/<id>/code/pull/fusionner`** — corps : `number`, `head`. **Le geste d'une personne** : le
propriétaire du projet, ou qui s'occupe d'elle (403 sinon) — Mika ne fusionne jamais, et aucun de ses outils ne le
peut. `head` nomme le commit qu'elle a lu (`pull.head`, 40 caractères ; 400 sans lui) : si la branche a bougé depuis,
dans l'atelier ou chez l'hôte, si l'hôte la dit impossible à fusionner, ou si la pull request n'est pas prête, rien ne
part (409, en mots). Sinon `{"ok", "message", "deduped", "asked": true, "number"}` : la fusion est demandée chez
l'hôte, après quoi le moteur relit la pull request et l'apprend comme toute fusion — l'objectif clos, son ticket
traité. Entre-temps `merge.asked` est vrai ; un refus de l'hôte se lit dans `merge.refused`. **Au moment de fusionner
(ADR 0292)**, l'action relit chez l'hôte les vérifications du commit de tête — en cours, en échec ou illisibles : 409
— et la base où la pull request entre — autre que la branche du projet : 409, en mots. De deux demandes parties
ensemble, une seule s'écrit (l'autre : 409). Une réponse de l'hôte perdue après l'envoi se lit dans `merge.refused`
comme « on ne sait pas si la fusion a eu lieu » — jamais « n'a pas eu lieu » — et l'hôte se relit aussitôt. L'action est celle de la
console (`projects.fusionner`), auditée `moi.projects.fusionner`. Le client demande une confirmation avant d'envoyer.

### Gérer un projet

Ce que l'écran montre s'y modifie (ADR 0290). Chaque geste passe par l'action de la console du même geste, au nom de
la personne (auditée `moi.projects.<action>`, dédoublonnée par la clé d'envoi), après la garde du moteur :

- **son cadre** — ses réglages, ses outils, son dépôt, l'archiver, le restaurer : qui le pilote en modification
  **et** en est le propriétaire, ou s'occupe d'elle (`rights.frame`). Qui ne fait que le piloter : 403 (« Seul le
  propriétaire du projet… change son cadre ») ;
- **ce qui ouvre autre chose que le projet** (ADR 0292) est réservé à **qui s'occupe d'elle**, même pour le
  propriétaire du projet : ses outils autres que sa mémoire et le web (`tool_email`, `tool_camera`, `tool_rss`,
  `tool_forge`, `tool_forge_apps`, chaque `service_…`), `approval` (l'accord de ce qui sort), `issues` (la publication
  en issues), et tout son dépôt distant (`remote`, `branch`, `auto_push`, `flow`). Les changer sans s'occuper d'elle :
  403, « Ce réglage ouvre autre chose que ce projet… », avec `fields` — le champ refusé ; rien d'autre de l'envoi
  n'est enregistré. Chaque champ le dit d'avance (`can`, `why`) ;
- **ses objectifs, ses jalons, ses tickets, ses décisions** : qui le pilote en modification (`rights.edit`) ;
- **sur l'accord du propriétaire**, rien de tout cela d'ici (403 : la demande se fait dans le chat) ; qui ne fait que
  le voir : 403 ; qui ne le voit pas : 404.

Chaque objet dit ce qu'elle peut en faire, la garde de sa route dite d'avance, et sinon pourquoi (`why`, en mots à
afficher tels quels) : sur un objectif ou une mission de la fiche, `can` — `modify`, `reopen`, `done`, `drop`,
`milestone` (lui ajouter un jalon), `why` ; sur un jalon, `can` — `modify`, `drop`, `why`.

**Le projet**

| Route | Corps | Qui | Ce que ça rend ou fait |
|---|---|---|---|
| `GET /api/moi/projets/nouveau` | — | toute personne | de quoi remplir « Nouveau projet » : `can`, `why`, `fields` (voir « Un champ ») |
| `POST /api/moi/projets/nouveau/creer` | `title`, `request?` (ce qu'elle veut, 2 000 caractères), `mode?`, `schedule?`, `schedule_rule?` | qui s'occupe d'elle | lui confier un projet : il naît **à cadrer**, pour elle, avec ses mots — elle pose ses questions puis propose un plan → `{"ok", "message", "project"}` |
| `GET /api/moi/projets/archives` | — | toute personne | les projets archivés qu'elle peut restaurer (les siens ; tous, pour qui s'occupe d'elle), sous ce qu'elle en aurait une fois restaurés — ses lignes d'accès, son niveau : `{"items": [{"id", "title", "archived_at", "owner_name"}]}` (`owner_name` : vide pour le sien, et pour qui n'a pas le droit de connaître ce nom) |
| `GET /api/moi/projets/<id>/reglages` | — | qui lit son détail | ses réglages en cinq sections : `can`, `why`, `renamable` (un projet qu'elle a ouvert d'elle-même ne se renomme pas), `archive` (`can`, `why`), `sections` — `name` (`general`, `rythme`, `accords`, `depot`, `outils`), `title`, `summary` (la section en une ligne), `can` et `why` (au moins un de ses champs se change), `fields`. L'adresse du dépôt distant n'est servie qu'à qui le projet est ; **les services branchés sur l'instance (`service_…`) ne sont servis qu'à qui peut les cocher** — les autres ne voient que ceux que le projet a |
| `POST /api/moi/projets/<id>/reglages/enregistrer` | `section`, `values` (les champs qui changent, par leur nom) | son cadre ; un champ réservé : qui s'occupe d'elle | le reste garde sa valeur. Un champ d'une autre section, ou d'une forme fausse : 400 (`fields`) ; un champ réservé à qui s'occupe d'elle : 403 (`fields`) ; rien de changé : 409. Une section que deux actions se partagent (« Accords et relecture ») s'enregistre en entier sous une seule clé d'envoi. Un projet qui n'est pour personne le reste |
| `POST /api/moi/projets/<id>/archiver` | — | son cadre | il ne travaille plus, rien n'est effacé ; il n'existe plus dans cette API, sauf dans `…/archives` |
| `POST /api/moi/projets/<id>/restaurer` | — | son cadre, tel qu'elle l'aurait une fois le projet restauré | un projet archivé revient, en pause ; celui qu'elle ne pourrait pas régler : 404 |

**Un champ** (`fields`) : `name`, `label`, `help`, `kind` (`text`, `textarea`, `select`, `bool`, `int`…), `required`,
`choices` (`[{"code", "label"}]`), `value` (sa valeur actuelle), `min`, `max`, `only` (les valeurs d'un autre champ
qui le rendent utile : `[{"field", "values"}]`), `can` (elle peut le changer : la garde de l'enregistrement, dite
d'avance) et `why` (sinon pourquoi, en mots à afficher tels quels). Ce sont les champs des actions de la console, décrits par elles :
le client n'écrit aucun libellé.

**Ses objectifs et ses jalons** — qui le pilote en modification :

| Route | Corps | Ce que ça fait |
|---|---|---|
| `POST …/objectif` | `text`, `kind?` (`once`, `constant` : une mission), `done_when?` (« fini quand »), et pour une mission `cadence_hours?`, `on?` (ce qui la déclenche, quatre au plus), `only_on_event?`, `at_once?` (premier passage tout de suite), `each_pass?` (ce que chaque passage doit faire, une ligne par chose) | ajouter un objectif → `{"ok", "message", "objective"}` ; un déclencheur refusé : 400 (`fields.on`) |
| `POST …/objectif/modifier` | `objective`, et les mêmes champs : ceux qui changent | le reste garde sa valeur ; rien de changé : 409 ; un objectif retiré : 404 |
| `POST …/objectif/statut` | `objective`, `status` (`open` : le rouvrir, `done` : le dire terminé, `dropped` : le retirer) | une mission ne se dit pas terminée (409) |
| `POST …/jalon/ajouter` | `objective`, `text`, `check?` (`prose` : sa parole, `command`, `owner` : un point d'arrêt, `item`), `command?`, `item_list?`, `item?`, `item_status?` | un jalon de plus sur un objectif ponctuel ouvert (cinq vivants au plus) |
| `POST …/jalon/modifier` | `objective`, `milestone`, ce qui change parmi `text`, `check`, `command`, `item_list`, `item`, `item_status`, et `reason?` | un jalon encore ouvert |
| `POST …/jalon/retirer` | `objective`, `milestone`, `reason?` | il reste lisible, retiré |

Un jalon atteint ou retiré ne bouge plus (409). **Un point d'arrêt, un jalon posé par une personne, fixé par un plan
validé ou refusé par le propriétaire ne se modifie ni ne se retire que par qui tranche** — le propriétaire du projet,
ou qui s'occupe d'elle (403 sinon, dit dans `can.why`).

**Un ticket** : `POST …/ticket/modifier` — `item`, et ce qui change parmi `title`, `text`, `kind`, `priority` : qui
le pilote en modification, pour un ticket qu'elle peut lire ; son étape ne change pas. Le fermer comme traité et le
rouvrir : `POST …/ticket/trancher`, `verdict: done` et `reopen` (qui tranche).

**Ses décisions techniques** — les lire demande son détail ; les changer, de le piloter en modification :

| Route | Corps | Ce que ça rend ou fait |
|---|---|---|
| `GET …/decisions[?status=]` | `status` : `active` (en vigueur, par défaut), `withdrawn`, `superseded`, `all` | `{"total", "in_force", "can", "why", "items"}`, les plus récentes d'abord : `number`, `title`, `choice`, `status`, `status_label`, `author_kind`, `author`, `at`, `replaces`, `replaced_by`, `objective`, `can` (`modify`, `replace`, `withdraw`, `restore`, `why`) |
| `GET …/decision?number=` | — | la même ligne, plus `context`, `options` (les options écartées) et `reason` |
| `POST …/decision/ajouter` | `title`, `choice`, `reason?`, `context?`, `options?`, `replaces?` (la décision en vigueur qu'elle remplace) | la consigner → `{"ok", "message", "number"}` ; l'ancienne reste lisible, remplacée |
| `POST …/decision/modifier` | `number`, et ce qui change parmi ces textes (vide : un texte facultatif est retiré) | une décision remplacée ne se modifie pas (409) |
| `POST …/decision/statut` | `number`, `status` (`withdrawn` : la retirer, `active` : la remettre en vigueur) | — |

**Une pull request : son titre, son texte, un commentaire.** Le geste d'une personne, comme la fusion : le
propriétaire du projet, ou qui s'occupe d'elle (`rights.pull_write` ; 403 sinon) — Mika n'écrit jamais ainsi.

- `POST …/code/pull/modifier` — `number`, `title?`, `body?` (un champ vide ne change pas ; les deux vides : 400) ;
- `POST …/code/pull/commenter` — `number`, `text` (4 000 caractères).

L'une et l'autre répondent `{"ok", "message", "asked": true, "number"}` : la demande est posée au journal, puis elle
part chez l'hôte. Un commentaire part du compte du jeton : son texte dit qui l'écrit, par son nom. Le résultat se lit
dans le fil d'activité (« parti chez l'hôte », ou pourquoi non) et, pour ce qui est parti, dans `…/code/pull/hote`.
Une pull request qui n'est pas ouverte chez l'hôte : 409 ; inconnue : 404.

### L'activité d'un projet

Tout se relit du journal (ADR 0290). Ces lectures demandent **son détail, au niveau de ce que le projet écrit**
(`rights.work` ; 403 sinon). **Chaque texte se compare en plus au niveau où il a été écrit** (ADR 0292) : le compte
rendu, la demande ou la note d'un objectif né d'un ticket plus confidentiel ne se sert pas à qui n'entend pas ce
niveau, même quand ce ticket n'est plus là pour le dire — la ligne porte alors `veiled: true` et, à la place du
texte, « Un texte d'un niveau que tu n'entends pas ici. ».

**`GET …/activite[?kind=&objective=&ticket=&before=&size=]`** — son fil, du plus récent au plus ancien :
`{"kinds": [{"code", "label"}], "size", "next", "items"}`. `kind` : `run` (une exécution), `commit` (le commit
qu'elle a laissé), `pull` (ce qui arrive à une pull request : l'hôte relu, ses vérifications, une fusion, ce qui est
parti), `ticket`, `gesture` (**ce qu'une personne a fait**, quel que soit l'objet : un objectif, un jalon, une
décision, une consigne, une pause, un plan validé, une fusion demandée, un commentaire). `objective` : ce qui le
concerne. `ticket` (son numéro) : ce qui arrive à ce ticket, et aux objectifs nés de lui (leurs exécutions, leurs
commits, leur pull request). `next` : le curseur à renvoyer dans `before` (0 : il n'y a plus rien). Une ligne :

```json
{"seq": 4120, "at": 1790790000000, "kind": "run", "kind_label": "exécution", "what": "report",
 "title": "Le journal des refus est écrit et testé.", "sub": "", "objective": 2, "ticket": 0, "pull": 0,
 "sha": "cdd07ae46e31…", "verdict": "continue", "verdict_label": "continuer", "run": "ep-…",
 "author_kind": "self", "author": "Mika", "outside": false}
```

`title` : pour une exécution, son compte rendu ; sinon ce qui s'est passé, en mots ; `sub` : ce qui a été écrit (une
consigne, le texte d'un objectif), ou la branche d'un commit ; `run` : l'exécution à ouvrir (`…/execution?id=`) ;
`author_kind` et `author` : comme pour un ticket (`self`, `you`, `person`, `project`, `host`) ; `outside` : ce que
dit l'hôte, ou un autre projet. Le titre d'un ticket n'est dit que si elle peut le lire. Le message d'un commit se
lit dans `…/code/commit?sha=`.

**`GET …/activite/jours`** — les trente derniers jours : `days` (du plus ancien au plus récent : `day`, puis un
compte par sorte — `run`, `commit`, `pull`, `ticket`, `gesture` — et `total`), `totals`, `total`, `kinds`, `by` (qui
a fait quoi : `[{"who": "self" | "you" | "others", "label", "count"}]`), `cut` (trop d'événements : les jours les
plus anciens sont incomplets).

**`GET …/activite/totaux[?objective=&ticket=]`** — les totaux (ADR 0293), sur toute son histoire et pour ce filtre :
`kinds` (`code`, `label`, `count`), `totals` (par sorte), `total`, `cut` (trop d'événements : le compte est
incomplet), `notes` (les notes de son carnet) et `notes_cut`, `runs` (ses exécutions).

**`GET …/executions[?before=&size=]`** — `{"total", "size", "next", "sorts", "items"}` : `id`, `at`, `sort`
(`frame` : cadrage, `run` : travail, `review` : relecture), `sort_label`, `objective` (`id`, `text`, `kind`,
`ticket`, `status`, `status_label` ; `null` pour un cadrage), `running`, `outcome`, `outcome_label`, `seconds` (sa
durée), `verdict` (`continue`, `done`, `blocked`, `wait`, ou vide), `verdict_label`, `proven`, `summary`, `commit`,
`branch`, `asked` (elle a demandé quelque chose).

**`GET …/execution?id=`** — une exécution : la même ligne, plus `report` (son compte rendu entier), `need` (ce
qu'elle a demandé), et **ce qu'elle a fait pas à pas** : `steps` (200 au plus ; `steps_cut` au-delà) — `tool`,
`label` (l'outil, en mots), `aim` (ce qu'il visait, en une ligne : un chemin, une commande, une recherche, une
adresse — jamais un texte qu'il portait), `ok`, `ran`, `ms`, `acts` (il change quelque chose), `outside` (**ce que
cet outil rend vient d'ailleurs**). Jamais ce qu'un outil a rendu. **`aim` ne se dit qu'avec le droit sur les
fichiers du projet** (`rights.files`, ADR 0292) — c'est l'arbre du dépôt par morceaux : sans lui, `aim` est vide
partout, `steps_aims` est faux et `steps_aims_why` dit pourquoi ; un pas qui vise un projet lié ne dit `aim` qu'à qui
lit aussi les fichiers de ce projet-là. `steps_kept: false` : sa trace n'est plus gardée (quatorze jours).

**`GET …/carnet[?objective=&before=&size=]`** — ses notes, les plus récentes d'abord : `seq`, `at`, `text`,
`objective` (celui qu'elle visait en l'écrivant, ou `null`), `run` ; et `total` (combien, pour ce filtre),
`total_cut`.

**`GET …/diagramme`** — de quoi dessiner ses objectifs, dans l'ordre du plan : `now`, `from` (la première date),
`cut`, `objectives` — `id`, `text`, `kind`, `status`, `status_label`, `after` (**l'objectif dont il dépend**),
`rank`, `ticket`, `added_at`, `started_at` (sa première exécution), `last_run`, `closed_at`, `runs`, `reached` et
`milestones_total`, `passes` (**les passages d'une mission**, soixante au plus), et `milestones` : `id`, `text`,
`status`, `status_label`, `check`, `check_label`, `ready`, `added_at`, `started_at` (**quand elle s'y est mise**),
`ready_at`, `reached_at`, `runs` (les exécutions qu'il a prises). **De vraies dates seulement** : 0 veut dire « pas
encore arrivé ». Quand elle s'est mise à un jalon et ce qu'il a pris se déduisent des départs de ses exécutions (la
première après le jalon d'avant) ; le moteur n'estime aucune durée.

### La documentation d'un projet

Un espace à part de son dépôt (ADR 0289), sous `/api/moi/projets/<id>/documentation` : des pages en Markdown rangées
en dossiers, et des images. **Enregistrer une page n'est pas un commit** : c'est une version de plus dans cet espace.

- **La lire** : le détail du projet, et sa documentation — ouverte d'office à qui le projet appartient ; à une autre
  personne quand une ligne d'accès qui la désigne la donne (la colonne « documentation », fermée tant qu'on ne la
  coche pas), hors de toute conversation et par ce client, au niveau de ce que le projet écrit. Sans elle, toutes ces
  routes répondent 403 (« Ce projet ne t'ouvre pas sa documentation… ») ; un projet qu'elle ne voit pas, 404.
- **L'écrire** : la lire, et piloter le projet en modification, en être le propriétaire, ou s'occuper d'elle. Sinon
  403 (« Tu lis la documentation de ce projet sans pouvoir l'écrire… »). `rights.write` et `can.write` le disent
  d'avance.
- **Un chemin** (`path`) est relatif à l'espace et finit par `.md` : des segments en minuscules, chiffres, points et
  tirets, séparés par `/`, six niveaux et 160 caractères au plus. Absolu, qui remonte (`..`), ou écrit autrement : 400
  (`fields.path`) — rien n'est corrigé. Une image a un nom simple (`schema-reseau.png`) ; une page la cite par
  `images/<nom>`.
- **Qui a écrit** une version ou ajouté une image : `author_kind` et `author` comme pour un élément (`self` : elle ;
  `you` ; `person`, nommée seulement si elle a le droit de le savoir), plus `via` — `run` (elle, pendant une
  exécution), `web` (une personne, dans le navigateur ou l'application), `mcp` (un outil, par MCP, au nom de cette
  personne), `console` —, `via_label` (ses mots) et `tool` (par MCP : le nom du jeton que l'outil présentait — servi
  à sa personne et à qui a le droit de la nommer seulement, vide sinon : ADR 0292).
- **Les bornes** (`limits`) : une page, 100 000 caractères ; 200 pages ; les 50 dernières versions de chaque page ;
  une image, 5 Mio (PNG, JPEG, GIF, WebP — pas de SVG) ; 200 images et 100 Mio par projet.

| Route | Ce qu'elle rend |
|---|---|
| `GET …/documentation` | l'espace : `project`, `rights` (`read`, `write`), `limits`, `pages` (toutes, par chemin : `path`, `name`, `folder`, `title` — son premier titre de niveau 1, sinon le nom du fichier —, `version`, `at`, `created_at`, `chars`, `images` : celles qu'elle cite, et qui l'a écrite en dernier), `folders` (ses dossiers, déduits des chemins), `images` (les plus récentes d'abord : `name`, `path`, `size`, `mime`, `at`, `used_by` : les pages qui la citent, et qui l'a ajoutée), `space_used` (octets) |
| `GET …/documentation/page?path=` | une page : la ligne de l'arbre, plus `text` (son Markdown), `forgotten` (son texte a été oublié) et `can.write`. Inconnue : 404 |
| `GET …/documentation/historique?path=` | `path`, `version` (la dernière), `kept` (50), `versions` (de la plus récente à la plus ancienne : `n`, `at`, `word` — le mot sur ce qui a changé —, `restored` — la version reprise, 0 sinon —, `chars`, `current`, et qui l'a écrite) |
| `GET …/documentation/version?path=&n=` | une version gardée : la même ligne, plus `text` et `forgotten`. Plus gardée, ou inconnue : 404 |
| `GET …/documentation/chercher?q=` | `{"q", "items"}` : les pages dont le chemin ou le texte contient ces mots (ni casse ni accents ; 120 caractères, 20 pages au plus, les dernières écrites d'abord), chacune avec `excerpt`, le passage |
| `GET …/documentation/images` | `{"items", "space_used", "limits"}` : ses images, comme dans l'espace |
| `GET …/documentation/image?name=` | les octets d'une image, servis comme une image (`nosniff`, sans rien d'actif) — **à qui peut lire la documentation seulement**. Inconnue, ou ses octets oubliés : 404 |

| Route (écrire) | Corps | Ce que ça fait |
|---|---|---|
| `POST …/documentation/page/enregistrer` | `path`, `text`, `word?` (200 caractères), `base` | **une version de plus**, avec son mot. `base` nomme la version lue (`version`) ; `0` crée la page. **Si quelqu'un l'a changée depuis** : 409, en mots (« Cette page a changé depuis ta lecture : elle en est à la version N, écrite … » — par qui, selon la règle des noms : « une autre personne » pour qui n'a pas le droit de le savoir, et jamais le nom de son jeton) — rien n'est écrasé : relire, puis reprendre. Sans `base` : 400 ; une page qui existe avec `base: 0`, le même texte, 200 pages déjà : 409. Rend `{"ok", "message", "path", "version"}`. **Un envoi redit avec la même clé d'envoi** (une coupure, puis le client réessaie) se reconnaît même si la page en est à la version qu'il a lui-même écrite : `deduped`, pas un conflit. Un corps JSON est borné à 64 Kio : **une longue page s'envoie en `multipart/form-data`** (les mêmes champs) |
| `POST …/documentation/page/revenir` | `path`, `version`, `base` | revenir à une version gardée : son texte redevient celui de la page, **dans une version de plus** (`restored`, le mot « Retour à la version N ») — rien n'est perdu. Version plus gardée : 404 ; la page a changé depuis `base` : 409 |
| `POST …/documentation/page/deplacer` | `path`, `to` | renommer ou déplacer (un autre chemin) : ses versions la suivent, les liens des autres pages ne sont pas réécrits. Un chemin pris, une page inconnue : 409 |
| `POST …/documentation/page/supprimer` | `path` | supprimer la page et ses versions |
| `POST …/documentation/image/televerser` | `multipart/form-data` : un fichier, `name?` | une image de plus → `{"ok", "message", "name", "path"}`. Son nom est celui du fichier, replié en un nom simple, à l'extension que disent ses octets ; pris, il reçoit un numéro (`schema-2.png`). Une image retirée se remet sous le même nom. Un envoi redit avec la même clé d'envoi rend la même réponse (`deduped`). Pas une image qu'on garde, plus de 5 Mio, 200 images ou 100 Mio déjà, ou une image que l'espace n'a pas gardée (un nom pris au même instant) : 409 |
| `POST …/documentation/image/retirer` | `name` | retirer une image : ses octets s'effacent ; les pages qui la citent la montrent introuvable |

Chaque geste passe par une action de la faculté (`projects.doc_ecrire`, `doc_deplacer`, `doc_supprimer`, `doc_image`,
`doc_image_retirer`), auditée `moi.projects.doc_…`. La même documentation se lit et s'écrit **par MCP**, sans rien
régler, sous les mêmes droits : `POST /mcp/moi/` avec un jeton de compte (`Authorization: Bearer mw_…` ; celui d'un
outil se crée par `mika token create <compte> --client tool`, dans la console, ou par `POST /auth/token` avec
`"client": "tool"`, et n'ouvre que ce point). Ses outils : `doc_lister` (sans `projet` : les projets dont la
documentation lui est ouverte ; avec : ses pages et ses images), `doc_lire` (`projet`, `chemin`, `version?`),
`doc_chercher` (`projet`, `mots`), `doc_ecrire` (`projet`, `chemin`, `texte`, `mot?`, `base`), `doc_image` (`projet`,
`nom`, `base64`) ; ils rendent le JSON des routes ci-dessus. **Sa porte** (ADR 0292) : 120 appels d'outil par minute
et par compte — chaque appel compte, aussi dans un lot (vingt messages au plus : au-delà, le lot entier est refusé) ;
l'appel de trop répond « Trop d'appels d'affilée… », la requête suivante 429 — et 200 écritures (une page, une image)
par projet sur vingt-quatre heures, tous comptes confondus. Un jeton d'outil se rend lui-même par
`DELETE /auth/token`, et ne s'élague pas avec les connexions d'un compte. Les décisions techniques d'un projet, que l'écran range
sous Documentation, ont leurs routes à elles.

## 12. Contacts

Ce que l'écran Contacts montre (ADR 0298) : ceux que Mika connaît **pour toi**, même sans leur avoir parlé — vus dans
tes comptes Teams et tes boîtes, sur ton téléphone, ou dont tu lui as parlé — et leurs organisations. L'annuaire a sa
base (`contacts`, le plugin du même nom) ; le code fait foi dans [`app/me/contacts.py`](../src/mika/app/me/contacts.py).

- **Tes contacts** : un contact est à qui l'a fait connaître — vu dans un compte à toi (à ton nom, ou « à toi » si tu
  es une de ses propriétaires) ou qu'on te partage (au moins en lecture), sur ton téléphone, raconté par toi, ou par
  un compte qui n'est à personne (un compte à Mika : à tout le monde). Un compte Teams ou une boîte est à qui ses
  propriétaires journalisés le disent, comme pour Mail et Teams (§ 3, § 4).
- **Ce qui s'en dit** : seulement ce que tes comptes en montrent — ses noms, son poste, ses identifiants, ses nombres
  (le même contact, vu dans la boîte d'une autre sous un autre nom, garde ici le nom que tu lui vois). Jamais de qui
  d'autre c'est le contact. La valeur d'une clé du téléphone ou d'un nom raconté ne se montre ni ne se cherche.
- **Ta propre fiche** (celle que tes comptes désignent, reliée à toi) n'est pas parmi tes contacts. Un contact d'une
  autre, ou inconnu : 404, la même réponse.

**`GET /api/moi/contacts[?q=&kind=&page=&size=]`** — tes contacts, le dernier vu d'abord : `q` cherche dans leurs noms
et leurs identifiants (un e-mail, un numéro — « 06 71 20 33 58 » se cherche comme il se range, en E.164 —, un
identifiant Teams) ; `kind` : `person` ou `org` (vide : tous ; autre chose : 400) ; `size` : 50, 100 au plus.
`counts` compte chaque sorte sans la recherche (les choix de l'écran).

```json
{"total": 7, "page": 1, "size": 50, "counts": {"all": 7, "person": 6, "org": 1},
 "items": [{"id": 12, "kind": "person", "name": "Alice Durand", "title": "Cheffe de projet", "department": "",
            "organisation": {"id": 3, "name": "Nordis"}, "linked": false, "talks": false, "members": 0,
            "last": 1790790000000,
            "sources": [{"source": "teams", "label": "Teams", "count": 64},
                        {"source": "mail", "account": "perso", "label": "Personnel", "count": 23},
                        {"source": "whatsapp", "label": "WhatsApp", "count": 4},
                        {"source": "told", "label": "Raconté", "count": 2}],
            "identifiers": [{"kind": "email", "value": "alice@nordis.fr"}],
            "photo": "/api/moi/teams/photo?account=equipe&person=8%3Aorgid%3A…&v=…"}]}
```

`sources` : d'où elle le connaît, avec combien de fois (0 : un profil seul) — Teams (tous tes comptes ensemble), chaque
boîte sous son nom (`account`), le téléphone par appli (`whatsapp`, `sms`, sinon `phone`), ce que tu lui as raconté
(`told`). `linked` : sa fiche est reliée à une personne qui a un compte ; `talks` : cette personne a déjà écrit à
Mika (« parle aussi à Mika » ; sinon « a un compte »). `members` : pour une organisation, ses personnes parmi tes
contacts — seulement celles dont tu vois la preuve qu'elles en sont (une adresse de son domaine, un profil Teams qui dit
son entreprise) ; `organisation` suit la même règle. `identifiers` : quatre au plus, jamais une clé du téléphone ni un
nom raconté. `photo` (ADR 0300) : l'adresse de sa photo de profil Teams (`GET …/teams/photo`, § 4), quand un compte
Teams où tu lis la garde ; `null` sinon (un contact sans identifiant Teams, une organisation : ses initiales).

**`GET /api/moi/contacts/fiche?id=`** — sa fiche : les champs d'une ligne (`photo` compris), plus

- `first`, `last` : la première et la dernière fois qu'elle l'a vu (ms) ;
- `identifiers` : `kind` (`teams`, `email`, `phone`, `domain`, `company`, `tenant`, `phone_app`), `label` (« E-mail »,
  « Contact WhatsApp »…), `value` (vide pour `phone_app` : sa clé ne se dit pas, `name` dit le nom que lui donne ton
  carnet), `where` (d'où elle le tient : « Teams », « son profil Teams », le nom d'une boîte, « ton téléphone »,
  « raconté par toi »), `generic` (une adresse sans personne derrière, rangée à son organisation). Un nom raconté
  n'est pas un moyen de le joindre : il n'y paraît pas ;
- `facts` : ce que Mika en sait — ce que l'annuaire tient : `title` (« Poste »), `department` (« Service »),
  `organisation` (avec son `id`), chacun avec `from` (« son profil Teams », « son adresse e-mail ») ; puis ce qu'elle a
  compris de ses derniers messages (`kind` : `note`, une personne seulement), **seulement les faits d'un compte que tu
  vois** : `id`, `value` (une phrase), `sort` (`role`, `topic`, `relation`, `expectation`, `manner` — sa façon
  d'être —, `bond` — ce qu'il y a entre elle et toi —, `other`), `confidence` (0 à 1), `from` (« ses messages dans
  Teams », « ses mails à Personnel », « ses messages sur ton téléphone »), `place` (où
  était le message qui le fonde : « en tête-à-tête », « dans le groupe « Projet » », « un mail, objet « … » »), `at`
  (sa date, ms), `forget` (il vient d'un de tes comptes : tu peux le faire oublier, ci-dessous) ;
- `places` : où vous vous croisez, le plus récent d'abord, **seulement là où tu lis** — `teams` (`conversation` : la
  clé de `GET …/teams/thread`, `account`, `title`, `kind`, `count` : ses messages, `last`), `mail` (`box`, `box_name`,
  `count`, `last`, `ref` et `subject` : son dernier mail reçu dans cette boîte, vides s'il n'y en a pas), `phone`
  (`conversation` : la clé `<appli>|<fil>` de `GET …/phone/thread`, `app`, `app_name`, `title` : un groupe, vide pour
  un tête-à-tête, `group`, `count`, `last`). Un compte à Mika se dit dans `where`, sans y mener ;
- `members`, `members_total` : une organisation, ses personnes parmi tes contacts (`id`, `name`, `title`,
  `department`, `last`, `linked`, `talks`, `photo` comme sur une ligne ; cinquante au plus) ;
- `write` (`{"address", "name"}`, ou `null`) : sa première adresse (pas une adresse générique), si une de tes boîtes
  peut envoyer ; `teams` : sa conversation Teams (le tête-à-tête, sinon la plus récente), vide sinon ; `message` : sa
  conversation de ton téléphone, vide sinon ;
- `privacy` : `mine` (tout ce qu'elle en sait vient de tes comptes : elle n'en parle qu'à toi) ou `shared` (aussi d'un
  compte qu'on te partage ou d'un compte à elle) ;
- `forget` (`{"allowed", "reason"}`) : peux-tu l'oublier d'ici (ci-dessous) — jugé, comme `privacy`, sur ce que tu en
  vois seulement : rien ne dit s'il est aussi le contact de quelqu'un d'autre.

**`POST /api/moi/contacts/forget`** `{"id"}` — l'oublier, **quand tout ce que tu en vois vient de tes comptes** (à ton
nom, « à toi », ton téléphone, ce que tu lui as raconté). S'il ne vient de rien d'autre, c'est l'oubli de la console
(`console.oublier.contact`) : la fiche et tout ce qui le désigne (ses identifiants Teams, ses adresses, ses clés du
téléphone, les noms sous lesquels on lui en a parlé), c'est-à-dire ce que Teams, le courrier, le téléphone et sa mémoire
gardaient de lui. S'il est aussi vu ailleurs, seulement ta part : ce que l'annuaire tient de tes comptes (ses vues, ce
qu'elle en a tiré) — ce qu'il est pour une autre ne change pas, et la réponse est la même. Audité `moi.oublier.contact`.
Une part qui vient d'un compte qu'on te partage ou d'un de ses comptes à elle : 403 (« Une part de ce qu'elle en sait
vient d'un compte qu'on te partage… ») ; une opératrice l'oublie depuis la console. Un contact qui n'est pas à toi :
404. Rend `{"ok", "message"}`.

**`POST /api/moi/contacts/fact/forget`** `{"id"}` — qu'elle oublie un fait qu'elle a compris de ses messages (le `id`
d'un `facts` de `kind` `note`) : il part, et ne se réapprend pas, même reformulé (seule l'empreinte de ses mots reste,
jamais son texte) — l'action de la console `contacts.oublier_fait`, auditée `moi.contacts.oublier_fait`. **Seulement
un fait d'un de tes comptes** (à ton nom, « à toi », ton téléphone) : d'un compte qu'on te partage ou d'un compte à
Mika, 403 (« Ce fait vient d'un compte qui n'est pas à toi… ») ; un fait que tu ne vois pas, ou déjà oublié : 404. Rend
`{"ok", "message", "deduped", "id"}`.

Mail › Contacts a quitté l'écran Mail (ses correspondants sont ici) ; `GET …/mail/contacts` reste, pour proposer des
destinataires quand on écrit (§ 3).

## 13. Agenda

Ce que l'écran Agenda et Paramètres › Agendas montrent (ADR 0309) : les agendas de la personne — celui du système
(« Mon agenda », sans rien régler), ceux qu'elle branche (Google Agenda, Outlook.com / Microsoft 365, CalDAV, un
abonnement iCal), ceux qu'on lui partage — et « L'agenda de Mika », sa mémoire montrée comme un agenda. Le code fait foi
dans [`app/me/agenda.py`](../src/mika/app/me/agenda.py) ; les écritures sont les actions du plugin
([`plugins/agenda/actions.py`](../src/mika/plugins/agenda/actions.py)), auditées `moi.agenda.<action>`.

- **À qui.** Un agenda est à elle quand son compte l'est : son compte du système (`moi:<sa clé>`), ou un compte
  branché à son nom, ou « à toi » si elle est une de ses propriétaires (la règle des boîtes, § 3). Un agenda qu'on lui
  partage s'y ajoute, à son niveau (`level` : `lire`, `preparer`, `servir`) — masqué par son propriétaire, ou sous un
  compte décoché, il ne lui est plus ouvert. Un agenda, un événement ou une proposition qui n'est pas à elle : 404.
- **Ce qu'un niveau ouvre à la personne.** Le sien, ou « s'en servir » : lire, créer, modifier, supprimer, dupliquer,
  répondre aux invitations (comme le courrier, un partage qui s'en sert fait comme le propriétaire) ; « lire » et
  « lire et préparer » : lire (écrire : 403 — « lire et préparer » laisse Mika y préparer un ajout, que le propriétaire
  approuve). Régler un agenda, le partager, son tableau de droits, « Mika te le rappelle » d'un événement : son
  propriétaire seulement (403 sinon).
- **Un événement privé d'une autre personne** se lit « Occupé » : son créneau seul (`masked`, sans titre, lieu,
  description, lien ni participants) ; il ne se modifie, ne se supprime ni ne se répond (409 ; `can.respond` faux,
  `respond_why` dit pourquoi), ne se cherche pas, et sa copie n'emporte que son créneau. Ce que Mika propose d'en faire,
  lu par qui n'en est ni propriétaire ni ne le décide (un partage qui prépare), se lit de même (`…/agenda/proposals`).
- **Les instants** sont en ms (UTC) avec le nom de leur fuseau (`zone`) ; une journée entière dit aussi ses jours
  (`first_day`, `last_day`, compris). Une période et ce qu'on écrit se lisent à l'heure du serveur (`zone` de
  `…/agenda/calendars`), sauf un fuseau donné ; une période est faite de jours de ce fuseau, où une journée entière se
  lit par ses dates (celle de la veille n'y est pas).

### Lire

**`GET /api/moi/agenda/calendars`** — `{"plugged", "zone", "calendars", "colors", "reminders"}` ; ses agendas, les
siens d'abord (le principal en tête), puis ses abonnements, ceux qu'on lui partage, et l'agenda de Mika en dernier
(`key` : `mika`, `kind` : `mika`, en lecture seule). Un agenda : `key` (`<compte>~<clé courte>`), `account`, `name`
(celui qu'on lui voit : le nom qu'elle lui a donné ici, sinon celui de son fournisseur) et `provider_name` (le nom chez
son fournisseur, quand elle lui en a donné un autre ; vide sinon), `kind` (`systeme`, `google`, `microsoft`, `caldav`, `ical`) et `kind_label`, `level` (`proprietaire`, ou celui du
partage) et `owner_name` (un agenda partagé), `group` (`mine`, `subscriptions`, `shared`, `mika`), `color` (celle
qu'elle a choisie, parmi `colors` ; vide : `provider_color`, celle du fournisseur), `primary`, `hidden` (masqué : Mika ne
s'en sert plus, la vue ne le montre pas), `enabled` (son compte est coché), `reminder` (« Mika te le rappelle » : `non`,
`15`, `30`, `60`, `veille`) et `reminder_set` (son choix ; vide : celui du serveur pour sa sorte), `writable`,
`read_only` (le fournisseur ne le laisse pas écrire), `can` (`write`, `respond` — y répondre aboutit : son fournisseur
transmet les réponses —, `settings`, `share`, `rights`, `remind`, `rename`), `synced_at`, `provider_reminders` (les rappels de son fournisseur : `max`, combien un événement en
garde — 5 chez Google et en CalDAV, 1 chez Microsoft, 0 pour le système, où Mika rappelle, et pour un abonnement, qui les
lit seulement — ; `email`, s'il sait en envoyer par e-mail ; `defaults`, ceux de l'agenda chez lui, les
`defaultReminders` de Google) ; pour un agenda à elle, `error` (la panne de la dernière synchronisation de son compte, en mots)
et `shares` (`person`, `name`, `level`).

**`GET /api/moi/agenda/period?start=&end=&calendars=`** — une période (`start` et `end` : `AAAA-MM-JJ`, le dernier jour
compris ; par défaut, la semaine qui commence aujourd'hui ; 100 jours au plus, 400 au-delà), sur les agendas nommés
(`calendars` : leurs clés, séparées par des virgules, `mika` pour celui de Mika ; vide : tous sauf les masqués) →
`{"start", "end", "zone", "items", "her", "proposals"}`. `items` : les occurrences, séries développées, dans l'ordre (un
événement refusé n'y est pas). Une occurrence :

```json
{"event": 42, "occurrence": "20261125T130000Z", "uid": "…", "calendar": "moi:user_1~mon-agenda",
 "title": "Point hebdo", "masked": false, "start": 1795957200000, "end": 1795959000000, "all_day": false,
 "first_day": "", "last_day": "", "zone": "Europe/Paris", "location": "", "description": "", "conference": "",
 "status": "confirme", "busy": true, "private": false, "recurring": true, "rule": "FREQ=WEEKLY",
 "organizer": {"address": "claire@lumen.fr", "name": "Claire", "person": "", "response": "", "optional": false,
               "me": false},
 "participants": [{"…": "…"}], "response": "oui", "invitation": false, "organized": false,
 "added": {"by": "elle", "conversation": "chat:user_1:812", "at": 1795900000000}, "remind": "", "forgotten": false,
 "reminders": [{"method": "notification", "minutes": 10}], "reminders_default": false,
 "can": {"edit": false, "delete": true, "respond": true, "duplicate": true, "remind": true}, "respond_why": ""}
```

`event` et `occurrence` désignent l'occurrence dans les écritures (`occurrence` vide : un événement simple, ou la
série entière). `response` : la réponse du compte de l'agenda (`attente`, `oui`, `peut`, `non` ; vide : il n'est pas
invité) ; `invitation` : elle attend sa réponse ; `organized` : faux pour une invitation, qui ne se modifie que chez qui
l'organise. `added` : ce que Mika y a mis, et la conversation où elle l'a fait (`null` sinon). `remind` : « Mika te le
rappelle » pour cet événement (vide : le choix de l'agenda). `reminders` : les rappels de son fournisseur (lot 6),
chacun `method` (`notification` ou `email`) et `minutes` avant ; `reminders_default` : il suit ceux de son agenda (Google,
`useDefault`), que `reminders` redit alors. `can.respond` : une réponse d'ici atteindrait l'organisatrice — elle peut
écrire dans cet agenda, l'invitation n'est pas le privé d'une autre, et son fournisseur transmet les réponses (un
serveur CalDAV sans planification, RFC 6638, ne les transmet pas ; tant qu'on ne l'a pas découvert, on ne le sait
pas) ; sinon `respond_why` dit pourquoi, en une ligne, qu'un écran montre à la place des boutons. `her` : les dates de l'agenda de Mika dans la période,
seulement ce qui la concerne (ce que Mika lui a promis, ce qu'elle lui a raconté elle-même ; jamais ce qu'une autre lui a
confié) — `ref` (l'élément de sa mémoire), `kind` (`promesse`, `moment`, `chaque_annee`), `title`, `start`, `end`,
`all_day`, `day`, `source` (d'où ça vient, en mots), `conversation`, `said_at`. `proposals` : ce que Mika propose
d'ajouter dans ces agendas pendant la période (ci-dessous), qu'un écran montre hachuré.

**`GET /api/moi/agenda/event?event=&occurrence=`** — une occurrence (la même forme), plus `calendar_name`, `proposals`
(ce que Mika propose sur cet événement) et `prepared` (la réponse qu'elle a préparée à cette invitation, ou `null`).
Une série demandée sans `occurrence` (la fiche qu'un écran ouvre après l'avoir créée) désigne sa première : ce qu'on en
supprime ou change demande sa portée. Une `occurrence` qui ne se lit pas : 400 (`fields.occurrence`).

**`GET /api/moi/agenda/search?q=&calendars=`** — chercher (`q` : 2 à 120 caractères, sans casse ni accents) dans les
titres, lieux, descriptions et participants, de 90 jours derrière à un an devant, les plus proches d'aujourd'hui
d'abord : `{"q", "items", "her", "more"}` (50 au plus).

**`GET /api/moi/agenda/invitations`** — `{"items"}` : les invitations qui attendent sa réponse, dans ses agendas et ceux
qu'on lui partage pour s'en servir, la plus proche d'abord (la prochaine occurrence d'une série), chacune avec
`calendar_name` et `prepared`.

**`GET /api/moi/agenda/proposals`** — `{"items"}` : ce que Mika propose d'écrire dans ses agendas et qui attend un
accord (dans un agenda à elle, ou partagé pour préparer ou s'en servir, ou dont elle décide). Une proposition : `id`,
`op` (`ajouter`, `modifier`, `supprimer`, `repondre`), `calendar`, `summary` (ce qu'elle propose, dans ses mots), `at`,
`starts` (le début du rendez-vous : passé, elle tombe), `decides` (c'est elle qui décide — sinon le propriétaire de
l'agenda, ou qui s'occupe de Mika), `conversation` (où Mika l'a proposé), `invitation` (la réponse préparée à une
invitation : sa clé), `target` (`event`, `uid`, `occurrence` ; `null` pour un ajout), `draft` (un ajout : `title`,
`start`, `end`, `all_day`, `zone`, `location`, `description`, `rule`, `invite`), `change`, `scope`, `answer` et
`comment` (une réponse), `why` (pourquoi cette réponse, à qui décide seulement), `remind`, `preview` (ce qui partirait,
à qui décide : `text`, `digest`, `blocked` ; un événement privé y est nommé à son propriétaire, « Occupé » pour un
autre). Sur un événement privé, qui n'en est ni propriétaire ni ne décide lit `summary` avec « Occupé » à la place du
titre, sans `change`, `answer` ni `comment`. Une réponse préparée à laquelle elle a répondu elle-même entre-temps n'y est
plus (elle tombe, « Répondu autrement »).

### Écrire

Chaque geste est une action du plugin, au nom de la personne (§ 1 : dédoublonnée par la clé d'envoi). Un champ texte
a sa borne (un titre 300 caractères, un lieu 300, une description 8 000, un lien 1 000, un mot 500) ; un champ refusé :
400 avec `fields`. Ce que le fournisseur refuse (un conflit, un événement disparu, une invitation qu'on n'organise pas)
ou un compte décoché, un agenda en lecture seule, une occurrence que la série ne donne plus (elle a changé depuis qu'on
l'a lue) : 409, en mots — la copie se relit. Une création rend `made` (`calendar`, `uid`, `event`). « Mika te le
rappelle » (`remind`) est à son propriétaire : d'un partage, 400 sur `remind`, avant toute écriture chez le
fournisseur.

| Route | Corps | Ce que ça fait |
|---|---|---|
| `POST /api/moi/agenda/event/create` | `calendar`, `title`, `start`, `end?`, `all_day?`, `zone?`, `location?`, `description?`, `conference?`, `rule?`, `invite?`, `free?`, `private?`, `remind?` | un événement (`agenda.creer`), parti tout de suite chez le fournisseur. `start`, `end` : `AAAA-MM-JJTHH:MM` à l'heure de `zone` (un fuseau IANA ; vide : celui de l'agenda), ou `AAAA-MM-JJ` avec `all_day` (le dernier jour compris) ; `end` vide : une heure, ou un seul jour. `rule` : une répétition RFC 5545 (`FREQ` quotidienne à annuelle, `INTERVAL`, `COUNT` ou `UNTIL`, `BYDAY`…). `invite` : des adresses — dans un agenda du système, une personne qui a un compte reçoit l'invitation dans le sien. `free` : « disponible ». `remind` : « Mika te le rappelle » (vide : le choix de l'agenda). `reminders` : les rappels de son fournisseur, `[{"method": "notification" \| "email", "minutes": n}]` (quatre semaines au plus ; absent ou `null` : ceux de l'agenda chez lui — Google, ses rappels par défaut ; Outlook, le sien ; CalDAV, aucun ; une liste vide : aucun). Google en garde cinq ; Microsoft un seul, le plus tôt, une notification (un e-mail y devient une notification) ; CalDAV les écrit en VALARM (DISPLAY ou EMAIL). L'agenda du système n'en a pas : 400 (« Mika te le rappelle » s'en charge) |
| `POST /api/moi/agenda/event/edit` | `event`, `occurrence?`, `scope?` (`un`, `suivants`, `tous`), et ce qui change parmi les champs de `create` (`invite` : toutes les adresses ; `all_day`, `free`, `private` : vrai ou faux ; `reminders` : tous ses rappels du fournisseur, une liste vide : aucun) | le modifier (`agenda.modifier`) ; changer le moment demande `start`. Une invitation ne se modifie pas (409), sauf ses rappels du fournisseur, qui sont à elle ; « Mika te le rappelle » se change par son propriétaire |
| `POST /api/moi/agenda/event/delete` | `event`, `occurrence?`, `scope?` | le supprimer (`agenda.supprimer`) ; supprimer une invitation, c'est la refuser |
| `POST /api/moi/agenda/event/duplicate` | `event`, `occurrence?`, `to?` (un agenda où elle écrit ; vide : le même) | une copie de cette occurrence (`agenda.dupliquer`) ; dans le même agenda, son titre dit « (copie) ». Un agenda qu'on lui partage en lecture se copie dans un des siens |
| `POST /api/moi/agenda/event/respond` | `event`, `occurrence?`, `answer` (`oui`, `peut`, `non`), `comment?`, `scope?` (`un`, `tous`) | répondre à une invitation (`agenda.repondre`) : la réponse repart par son fournisseur ; ce que Mika avait préparé tombe. Une invitation privée d'une autre personne : 409, comme la supprimer ; un fournisseur qui ne transmet pas les réponses : 409, en mots |
| `POST /api/moi/agenda/event/remind` | `event`, `value` (vide, `non`, `15`, `30`, `60`, `veille`) | « Mika te le rappelle » pour cet événement (`agenda.rappel`), gardé sur ce serveur seulement — son propriétaire |
| `POST /api/moi/agenda/proposal/accept` | `proposal`, `seen` | accepter ce que Mika propose tel qu'il a été lu (`seen` : le `digest` de son `preview` ; changé depuis : 409, relire) — `agenda.accepter` |
| `POST /api/moi/agenda/proposal/refuse` | `proposal`, `note?` | le refuser (`agenda.refuser`) ; elle le saura |
| `POST /api/moi/agenda/proposal/edit` | `proposal`, `calendar?`, et les champs de `create` | « Modifier » puis « Ajouter » un ajout qu'elle propose (`agenda.ajouter_modifie`) : ta version s'écrit, marquée « ajoutée par Mika » (la conversation de sa proposition) ; la proposition est retirée et Mika apprend que tu l'as ajoutée avec tes changements. Une autre sorte de proposition : 409 |

Une proposition dont elle ne décide pas : 403 (dans un agenda qu'elle voit), sinon 404 ; déjà décidée : 404.

### Ses comptes (Paramètres › Agendas)

**`GET /api/moi/agenda/accounts`** — `{"plugged", "accounts", "google", "microsoft_app", "kinds", "services", "colors",
"reminders", "max"}`. `accounts` : son compte du système d'abord (`system`), puis ceux qu'elle a branchés — `key`,
`kind`, `kind_label`, `label`, `address`, `enabled`, `url` (CalDAV : l'adresse du serveur ; un abonnement ne la rend
jamais, elle ouvre l'agenda à qui la connaît : `url_set`), `username`, `secrets` (`{"password": true}` : un mot de
passe est gardé, jamais rendu), `oauth_client_id`, `oauth_tenant` (Microsoft), `synced_at`, `tried_at`, `failures`,
`error` (la dernière panne, en mots), `signin` (Google et Microsoft : `state` — `connectee`, `en_attente`, `a_faire`
—, `code` et `url` du code d'appareil, `until`, `error`), `abilities` (`write`, `calendars` : y créer un agenda) et
`calendars` (ses agendas, comme dans `…/agenda/calendars`). `google` : `app` (l'application Google du serveur est
réglée), `direct` (elle revient seule au serveur). `services` : les aides CalDAV (`key`, `name`, `url`, `help`). `max` :
combien de comptes elle peut brancher (`null` : une opératrice).

| Route | Corps | Ce que ça fait |
|---|---|---|
| `POST /api/moi/agenda/account/save` | `account?`, `kind` (sans `account` : `google`, `microsoft`, `caldav`, `ical`), `values` (`label`, `enabled`, `url`, `username`, `password`, `address`, `oauth_client_id`, `oauth_tenant`) | brancher un compte → `{"account"}` (à elle, ou « à toi » pour une propriétaire), ou régler un des siens. Un mot de passe laissé vide reste ; le serveur CalDAV ou l'identifiant changent : le redonner (400). Pour qui n'est pas opératrice, un serveur sur Internet seulement (400 sur `url` : ni cette machine — DavMail sur `localhost` —, ni le réseau privé). Dix comptes au plus (409). Un CalDAV ou un abonnement se synchronise aussitôt ; réglé par qui n'est pas opératrice, son serveur est revérifié sur Internet à chaque connexion, joint à l'adresse vérifiée. La clé d'un compte vient de son nom affiché (sinon de sa sorte), jamais de son adresse. Audité `moi.agenda_compte` |
| `POST /api/moi/agenda/account/try` | `url`, `username`, `password` (ou `account` : un compte CalDAV à elle, son mot de passe gardé) | essayer un serveur CalDAV sans rien enregistrer → `{"ok", "message", "calendars"}` (`local`, `name`, `color`, `writable`, `primary`, `selected`) ; un refus du serveur : `ok` faux et ses mots. Trente essais par minute (§ 1) |
| `POST /api/moi/agenda/account/google/start` | `account` | commencer la connexion Google → `{"url", "until", "direct"}` : l'adresse de consentement à ouvrir. Sans application Google réglée sur le serveur : 409 (« L'application Google de ce serveur n'est pas réglée… ») |
| `POST /api/moi/agenda/account/google/finish` | `account`, `text` | la finir en collant l'adresse de la page qui n'a pas pu s'ouvrir (`http://127.0.0.1…`), ou celle de la page de retour du serveur (le retour direct, sans session), ou son code : connecté, son adresse retrouvée, il se synchronise. Une adresse qui ne vient pas d'une connexion commencée par elle, ou expirée, une case de l'agenda non cochée : 400 (`fields.text`, en mots). Audité `moi.agenda_connexion` |
| `GET /api/moi/agenda/google/retour` | — | la redirection directe de Google (une application « Web » du serveur, à son origine HTTPS) : avec une session, le parcours finit ici, pour qui l'a commencé ; une page dit ce qui s'est passé, l'écran l'apprend par le direct. Sans session (le navigateur du téléphone) : une page « Encore une étape » dit de copier son adresse et de la coller dans l'application (`…/google/finish`) — le `state` seul ne finit rien : un parcours commencé par une personne et consenti par une autre rattacherait l'agenda Google de la seconde au compte de la première |
| `POST /api/moi/agenda/account/microsoft/start` | `account` | connecter Outlook.com / Microsoft 365 : `{"code", "url", "until"}`, un code à entrer chez Microsoft ; la fin de l'attente est poussée (`agenda`), puis `…/account/sync` |
| `POST /api/moi/agenda/account/sync` | `account` | synchroniser maintenant (`agenda.synchroniser` : le compte est relu dans les secondes qui suivent, même quand elle dort) ; un compte Google ou Microsoft connecté retrouve d'abord son adresse |
| `POST /api/moi/agenda/account/disconnect` | `account` | Google ou Microsoft : la connexion retirée (chez Google aussi) et oubliée ; le compte reste, à reconnecter. Un autre : 409. Audité `moi.agenda_deconnexion` |
| `POST /api/moi/agenda/account/remove` | `account` | retirer un compte branché : ses agendas et leur copie partent (son agenda du système reste : 409). Audité `moi.agenda_compte_retire` |
| `POST /api/moi/agenda/calendar/new` | `name`, `account?` (vide : son compte du système) | un agenda de plus (`agenda.nouvel_agenda`) → `made.calendar` ; un compte qui ne le sait pas : 409 |
| `POST /api/moi/agenda/calendar/save` | `calendar`, et ce qui change parmi `name`, `color` (vide, ou une de `colors` — le rose est à Mika), `hidden` (masqué : Mika ne s'en sert plus), `reminder` (vide, `non`, `15`, `30`, `60`, `veille`), `followed` (synchronisé ; `null` : ce que le fournisseur coche) | le régler — son propriétaire. Audité `moi.agenda_reglage`. `name` (`agenda.renommer`, audité `moi.agenda.renommer`) : un agenda du système change de nom pour de bon (un nom vide : 400) ; un agenda branché prend un nom à lui, ici seulement — ni Google, ni Microsoft, ni le serveur CalDAV ne sont touchés, sa synchronisation ne le change pas, et un nom vide (ou le sien) lui rend celui de son fournisseur. Ce nom est celui que voient aussi ses outils et la console |

**Le partager** : `POST /api/moi/shares/set` avec `kind: "agenda"` et la clé de l'agenda (§ 9) — son propriétaire,
à une personne qui a un compte ; son tableau de droits reçoit la ligne de la personne (lire ; lire et préparer : Mika y
écrit sur l'accord du propriétaire ; s'en servir : elle y écrit et répond, sur l'accord de la personne). Un partage
dans Mika n'est pas un partage chez Google ou Microsoft.

**Son tableau de droits** (Outils › Droits) — son propriétaire seulement :

- `GET /api/moi/agenda/rights?calendar=` → `{"calendar", "set", "lines", "default"}` : réglé (`set`), sinon celui que
  son propriétaire et ses partages donnent. Une ligne : `who`, `canal`, `when`, `read`, `write` (`non`, `accord`,
  `seule`), `respond` (`non`, `accord`), `keep` (`rien`, `prive`, `perso`, `public`), et `words` (chacune en mots) ;
- `POST /api/moi/agenda/rights/save` `{"calendar", "lines", "default"}` (30 lignes au plus ; `words` ignoré) ou
  `{"calendar", "reset": true}` (le tableau de départ). Audité `moi.agenda_droits`. Le propriétaire et le partage
  restent la première porte : une ligne n'ouvre jamais un agenda à qui il n'est ni à elle ni partagé.

**Le direct** : tout ce qui change ses agendas — une synchronisation, une écriture (d'elle, de Mika, d'un partage),
une proposition de Mika et sa décision, une invitation, la connexion d'un compte, un réglage — part en `agenda` (§ 2
bis), avec les agendas touchés (`calendars`), à elle et à qui on les partage, à personne d'autre. L'agenda de Mika se
relit à l'ouverture de l'écran.
