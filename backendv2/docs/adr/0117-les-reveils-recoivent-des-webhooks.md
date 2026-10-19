# 0117 — Les réveils reçoivent des webhooks

**Contexte.** Les réveils par API (ADR 0068) font agir Mika quand un système extérieur l'appelle, mais seulement si
cet appelant se plie à leur forme : un corps `{"text": "…"}` et un en-tête `Authorization: Bearer <clé>`. Un vrai
service de webhooks n'en fait rien. GitHub, Gitea, Forgejo ou Home Assistant envoient leur propre JSON, sans `text`
(400). GitHub et Forgejo ne posent pas d'en-tête `Authorization` : ils signent le corps avec un secret
(`X-Hub-Signature-256`). Il fallait donc un script relais entre eux et elle. Par ailleurs, un réveil ne pouvait que
travailler sur-le-champ. Il ne pouvait ni planter un rappel ni ouvrir quelque chose qu'elle reprendrait ensuite :
`goal_remind` ne sert qu'en conversation, et le lot `goals` n'était pas permis à un réveil. Le 2026-10-19, la
propriétaire a demandé des webhooks qui la réveillent, lui donnent un contexte et des informations, et lui font lancer
une action ou une tâche.

**Décision.**

1. **Le texte d'un appel** (`app/wakeups.call_text`) :
   - `{"text": "…"}` reste ce qu'il était. Le texte est strict : vide ou plus long que la borne du réveil, il est
     refusé (400), parce que l'appelant l'a écrit et peut le raccourcir. Un `context` peut l'accompagner (un objet,
     une liste, une phrase). Il suit le texte, mis en lignes `chemin: valeur` et coupé à la place qui reste.
   - Tout autre objet ou liste est le JSON d'un service, pris tel quel. Il est mis en lignes `chemin: valeur` dans
     l'ordre où il est écrit, sans les valeurs vides et jusqu'à seize niveaux de profondeur. L'évènement que le
     service annonce vient en tête (`event: push`). Le tout est **coupé** à la longueur admise (« … ») au lieu d'être
     refusé : un service ne choisit pas la taille de son corps.
   - L'opérateur peut déclarer des **champs gardés** (`fields`, un chemin par ligne : `issue.title`,
     `commits.*.message`, `commits.0.id`). Le corps se réduit alors à ce qu'ils désignent. Un chemin absent ne donne
     rien. Rien à lire : 400.
   - Le corps d'un appel peut atteindre 512 Kio (64 Kio avant), assez pour un `push` de GitHub. Ce que l'appel apporte
     reste **cité** et jamais obéi. Les consignes du réveil priment, comme avant.
2. **La signature** (`signed`, « Signé (GitHub, Gitea, Forgejo) ») :
   - Un réveil signé admet le corps signé par sa clé : HMAC-SHA256 du corps tel qu'il est arrivé, en hexadécimal,
     avec ou sans `sha256=` devant. La signature se lit dans le premier en-tête présent parmi `X-Hub-Signature-256`,
     `X-Gitea-Signature`, `X-Forgejo-Signature` et `X-Signature-256`. La clé `mwk_…` est le « secret » qu'on donne au
     webhook. La clé présentée en Bearer passe toujours.
   - Pour vérifier une signature, il faut relire la clé. Celle d'un réveil signé est donc **aussi gardée chiffrée**
     (Fernet, `secret.key`, champ `sealed` des `wakeup_keys`). C'est la seule entorse à « seule son empreinte est
     gardée » (ADR 0068). Elle ne vaut que pour un réveil signé : décoché, la copie chiffrée part à l'enregistrement.
     Une clé générée avant que le réveil signe ne sait rien vérifier, et la fiche dit d'en générer une neuve.
   - La porte calcule toujours les deux vérifications, avec le même coût. Quand il n'y a pas de clé chiffrée à ouvrir,
     elle ouvre un jeton factice. Rien ne dit si un nom existe, ni s'il signe. Une signature fausse reçoit le même 401
     qu'une mauvaise clé.
   - Une copie qui ne s'ouvre plus (`secret.key` ou `MIKA_SECRET_KEY` changée) ne vérifie rien : seule une clé
     `mwk_…` déchiffrée signe, jamais une clé vide ni le jeton factice.
   - GitLab recopie son « secret token » tel quel (`X-Gitlab-Token`) : c'est une clé présentée.
3. **Les livraisons.**
   - Un `ping` (`X-GitHub-Event: ping`, quand GitHub vérifie un webhook neuf) reçoit 200 `{ok, call: null}` après la
     clé et l'état du réveil, et rien n'est journalisé. Avant, il lui aurait fait traiter un appel vide de sens.
   - L'identifiant d'une livraison (`X-GitHub-Delivery`, `X-Gitea-Delivery`, `X-Forgejo-Delivery`) sert de clé
     d'idempotence quand il n'y a pas d'`Idempotency-Key`.
   - Un appel admis par sa signature a pour clé d'idempotence l'**empreinte de son corps**. Seul le corps est signé :
     ni l'en-tête de la livraison ni l'heure ne le sont. Un corps signé capté puis rejoué, même sous un autre
     identifiant, rend donc le même appel.
4. **Ses buts dans un réveil.** Le lot `goals` est permis à un réveil **sans projet**. Il est refusé sur un réveil qui
   a un projet, dès la validation du réglage. Il entre dans `WAKE_TOOLS`. Deux outils de la faculté `goals` ne servent
   que là :
   - `goal_plan_reminder` (`WAKE`, `WAKE_JOB`, trois par épisode) :
     - un rappel à l'heure dite, pour la personne à qui le réveil rend compte (sa propriétaire, ou la personne d'un
       compte) ;
     - un réveil qui ne rend compte à personne n'en plante pas : l'outil le refuse ;
     - le candidat du réveil porte son destinataire (`contracts.wakeup.NOTIFY_ARG`), si bien que la faculté n'a pas
       à lire l'état du plugin ;
     - c'est un rappel demandé (`authority=user`), de source `wakeup:<seq>` ;
     - il se dit à l'heure dite, là où la personne est alors, comme un rappel promis en conversation.
   - `goal_plan_exploration` (`WAKE` seulement, une par appel, dédoublonnée sur l'appel) :
     - une exploration née d'un signal, avec un titre à elle. Ce que l'appel apportait est gardé à part et cité au
       travail (`titled`) ;
     - elle est à elle (`authority=self`) : elle peut la laisser ;
     - son destinataire est celui du réveil ;
     - elle a **les seuls outils du réveil**, moins `wakeup` et plus `goals` : jamais plus que ce que l'opérateur lui
       a donné ;
     - elle dure autant de séances qu'une exploration ordinaire.

     En impersonnel, l'outil n'est pas offert : une exploration se vit dans son mode à elle.
5. **La console et la CLI.**
   - La fiche d'un réveil dit s'il signe et ce qu'il garde, et comment brancher un webhook (adresse, type de contenu,
     secret).
   - Elle avertit quand le réveil a ses buts : ce qu'un appel apporte agit alors plus tard, hors de lui.
   - Elle avertit aussi quand le réveil signe sans clé qui le puisse.
   - `mika wakeup list` montre `signed` et `fields`, et `mika wakeup key` dit comment signer.

**Conséquences.**

- *Sans réglage nouveau, rien ne change* : `{"text": "…"}` et le Bearer marchent comme avant, et un réveil ne signe ni
  ne garde de champs par défaut.
- *Réserves.*
  - La clé d'un réveil signé se retrouve avec `mind.db` et `secret.key` réunis, comme ses autres secrets.
  - Les en-têtes d'évènement et de livraison ne sont pas signés. L'évènement ne fait qu'étiqueter le texte et
    reconnaître un `ping`. Un `ping` forgé sur un corps signé ne fait rien.
  - Une livraison d'essai de Gitea qui renvoie le même corps rend le même appel (202 « Déjà reçu »).
  - Une exploration née d'un réveil garde les outils du réveil plusieurs séances après l'appel. Sa mémoire jointe à un
    outil qui fait sortir des données (`risks`) vaut donc au-delà de l'appel.
  - Un rappel planté pour un compte qui n'est pas propriétaire est écrit par elle et trié par sa discrétion, comme le
    compte rendu (ADR 0068).

Épreuves, dans `tests/unit/test_wakeup_webhooks.py` :

- *Le texte* :
  - le `text` comme avant, et un `context` en lignes ;
  - le JSON d'un service, avec l'évènement en tête et ses champs gardés (`*`, un index, un chemin absent) ;
  - un gros corps coupé, pas refusé ;
  - un corps trop profond, laissé ;
  - rien à lire, refusé ;
  - des champs illisibles, refusés ;
  - `goals` sur un réveil qui a un projet, refusé.
- *La porte, par le vrai serveur* :
  - une livraison de GitHub signée passe ;
  - rejouée sous le même identifiant ou sous un autre, elle rend le même appel ;
  - une signature fausse, un autre corps ou une signature illisible reçoivent 401 ;
  - le Bearer et `X-Gitlab-Token` passent ;
  - un `ping` reçoit 200, sans rien journaliser ;
  - la clé n'est nulle part en clair ;
  - décoché, le réveil perd sa copie chiffrée et refuse les signatures ;
  - recoché, il attend une clé neuve, et sa fiche le dit ;
  - une copie qui ne s'ouvre plus ne laisse passer aucune signature, même par une clé vide.
- *Ses buts* :
  - le réveil offre ses outils, et pas ceux d'une conversation ni d'un pas ;
  - le rappel est pour la propriétaire et dit à l'heure dite ;
  - l'exploration a les outils du réveil sans `wakeup`, son titre et ce qu'elle cite ;
  - sans personne à qui rendre compte, l'outil refuse le rappel ;
  - en impersonnel, pas d'exploration.
- `tests/protocol/test_wakeup_web.py` borne le corps à la nouvelle taille.

Quatre mutations les font échouer :

- une signature acceptée sans être comparée ;
- une signature vérifiée par une copie qui ne s'ouvre plus ;
- un `ping` qui n'est plus reconnu ;
- une exploration qui garde le lot `wakeup`.
