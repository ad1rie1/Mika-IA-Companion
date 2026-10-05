# 0062 — L'application mobile : une messagerie, une présence, des fichiers

**Contexte.** L'ADR 0060 a retiré Telegram : on écrit à Mika par une application dédiée, avec un compte. Elle
laissait un reste : « sans robot, elle ne peut plus écrire d'elle-même à quelqu'un qui n'est devant aucun écran ;
quand l'application dédiée saura recevoir hors ligne (une notification), son canal pourra se déclarer messagerie dans
`vocab.privacy` et redonner vie à `identity.REACHABLE` ». Le 2026-10-04, la propriétaire a demandé cette application
(`frontend/Android/`) : parler à Mika, lui envoyer des fichiers, **en recevoir**, voir un peu ce qu'elle fait — avec
une connexion obligatoire par identifiant et mot de passe, une session qui dure jusqu'à la déconnexion, des
notifications quand l'application est fermée, et le droit pour Mika d'écrire la première.

Quatre choses manquaient au serveur. Un client natif s'authentifiait déjà par un jeton porteur sans `Origin`
(ADR 0051), mais un jeton ne s'obtenait qu'en ligne de commande. `/ws` écrivait le canal `web` en dur. Une connexion
**était** une présence : une application qui garde sa connexion en arrière-plan pour recevoir aurait fait croire à
Mika que la personne la regardait jour et nuit (salutations, « resté là sans répondre », murmures à voix haute). Et
rien ne lui permettait d'envoyer un fichier : ni outil, ni octets gardés, ni champ dans la parole, ni route de
téléchargement pour un compte qui n'est pas opérateur.

**Décision.**

1. *Un jeton contre un mot de passe.* `POST /auth/token {username, password, label, client}` rend un jeton de client
   natif (`mw_…`, montré une fois, gardé en empreinte), avec les champs de `/auth/whoami`, `Cache-Control: no-store`
   et aucun cookie. Refusé en 403 à une requête qui porte une `Origin` (un navigateur a sa session ; ce refus ne
   compte pas comme un échec) ; les échecs comptent avec ceux de `/auth/login` (mêmes étranglements, mêmes clés).
   `DELETE /auth/token` rend le jeton : il ne vaut plus rien, ses connexions se ferment en 4401. `/auth/whoami`, et
   toute route qui lit un compte (`account_of`), reconnaissent le jeton **sans** `Origin` ; celles qui écrivent
   exigent toujours le jeton CSRF, qu'un client natif n'a pas : rien n'est élargi. Un jeton dit désormais **ce qu'il
   ouvre** (`client_tokens.client` : `screen`, un écran ou un moteur ; `mobile`, l'application du téléphone) et
   **d'où il vient** (`source` : `cli`, `console`, `login`), colonnes ajoutées à l'ouverture d'une table ancienne
   (ses jetons restent des écrans donnés en ligne de commande). Un jeton obtenu par mot de passe suit ce mot de
   passe : le changer, ou désactiver le compte, le révoque dans la même transaction ; ceux qu'un opérateur a donnés
   (un moteur de jeu configuré à la main) restent. Au-delà de dix jetons vivants obtenus par connexion, le moins
   récemment utilisé part. Console › Comptes montre, sur la page d'un compte, ses applications connectées (nom,
   sorte, origine, création, dernier usage, état — jamais le secret) et les révoque (action auditée,
   `console.comptes.revoquer_jeton`). `mika token create --client mobile|screen` ; `token list` montre les deux
   colonnes.

2. *Le téléphone est une messagerie.* `vocab.privacy` déclare `MOBILE` (« mobile ») : `is_messaging` vrai (on y lit
   quand on y pense ; elle peut y écrire à quelqu'un d'absent). La confiance ne change pas : authentifié, c'est un
   compte comme un autre ; sans session, un transport que rien ne décrit reste public (`mobile` n'entre pas dans les
   canaux de compte). La sorte d'application est **une colonne du jeton**, pas un en-tête de la connexion : la
   joignabilité doit être connue quand aucune connexion n'est ouverte (elle écrit à quelqu'un dont l'application est
   tuée), un jeton est une installation, Unity garde `screen` sans rien changer, et ça se révoque.
   `identity.registered` gagne `messaging` (`"mobile"` : le compte a une application qui reçoit hors ligne ; `""` :
   il n'en a plus ; `None`, le défaut : rien n'est dit — un journal d'avant). `register_accounts` le calcule (un jeton
   `mobile` non révoqué, compte actif) et n'écrit qu'au changement ; la création ou la révocation d'un jeton
   `mobile` le relance. Le réducteur pose ou retire `push` et le canal de l'adresse. Corollaire voulu : **une adresse
   authentifiée n'est plus rendue joignable par ce qu'elle a dit** (`_seen` ne pose `push` que sans session) — la
   joignabilité d'un compte ne vient que de `registered`, et se retire quand l'application part ; aucun journal
   existant n'avait de compte authentifié sur une messagerie. Ce que ça rallume, sans une ligne de plus dans les
   facultés : les rappels échus, les prises de nouvelles, les reprises de contact, les promesses et les nouvelles
   de projets vont à l'adresse présente d'abord, sinon à l'adresse joignable ; l'attention et les délais appris
   prennent la classe « messagerie ». Les retenues ne changent pas (`agency`, ADR 0033 : budget, période
   réfractaire, après un au revoir, la journée) : elles valaient déjà « présente ou non ». `/ws` porte le canal de la
   session (`Connected`, `PerceptionReceived`) : `mobile` pour un jeton `mobile`, `web` sinon.

3. *Une connexion n'est pas une présence.* Un client natif peut ouvrir sa connexion avec
   `X-Mika-Presence: away` : elle ne s'annonce pas (pas de `presence.connected`), ne reçoit rien qu'elle n'ait demandé
   (ni fil initial — elle envoie `sync`, même à zéro —, ni visage, ni panneau : la batterie), et reçoit ce qui lui est
   adressé (la parole, sans voix : `speak` faux ; les accusés ; les rattrapages). La trame client
   `{"type": "presence", "here": bool}` bascule : revenir vaut tout de suite (présence, visage et panneau frais) ;
   partir vaut après `AWAY_GRACE_S` (20 s : prendre une photo et revenir n'écrit rien). Les écritures au journal sont
   bornées par connexion (`PRESENCE_RATE`, 6 par minute) ; au-delà, l'état voulu s'applique quand la fenêtre le
   permet — jamais perdu, jamais une rafale. Un message envoyé d'une connexion absente (une réponse depuis la
   notification) est perçu sans faire croire qu'on est revenu. Le concentrateur distingue `Conn.here` : la voix se
   choisit parmi les écrans regardés ; **une pensée à voix haute ne part jamais vers un écran que personne ne
   regarde** (ce serait une notification de ce qu'elle pense) ; visage et panneau ne vont qu'aux écrans regardés.
   Une connexion à cookie, ou un jeton sans l'en-tête, se comporte comme avant.

4. *Un tour posé d'un autre appareil.* Quand on écrit du navigateur, le téléphone reçoit la réponse — mais jamais la
   question : son curseur la dépassait avec la réponse, et un `sync` ne la renvoyait plus. Juste avant la trame
   `speech`, les connexions **autres que celle qui a demandé** reçoivent la ligne de la question dans le `history`
   (`catchup`) qui rattache déjà les messages d'une rafale (ADR 0045 §7) ; celle qui a demandé garde le
   comportement d'avant.

5. *Elle envoie des fichiers.* Une faculté `shares` (« Fichiers envoyés ») : elle écrit un fichier texte en
   parlant (une liste, une note, du code, un tableau — extensions de texte seulement, 512 Kio au plus) ou joint un
   fichier de l'atelier d'un projet que la personne a le droit de voir (la propriétaire, ou celle qui l'a confié, et
   un sujet qu'elle peut entendre). Les **octets restent hors du journal** (`data/partages/`, port `ShareStore`,
   précédent : les brouillons du courrier, ADR 0027), le journal ne garde que leur fiche (`shares.shared` : nom et
   chemin en `Content`, taille, empreinte, origine, destinataire) ; un fichier se rattache à sa parole par une
   référence opaque (`ToolResult.attach` → `Utterance.attachments` → `Delivery.attachments` : le runtime et
   l'expression ne nomment aucune faculté). La parole (`speech`) et les lignes de Mika du fil (`history`) portent
   `attachments: [{id, name, kind, mime, size, url, available}]` ; `GET /files/{id}` les télécharge, pour le seul
   compte dont le fil contient ce message (même réponse 404 pour inconnu et interdit ; 410 retiré ; en pièce jointe,
   `nosniff`, `no-store`, CSP `sandbox`, jamais rendu comme une page). Oublier une personne efface ses fichiers
   (ADR 0024) ; une rétention les retire au bout d'un an ou au-delà d'un volume par personne ; la sauvegarde
   emporte `partages/`. Les fichiers que la personne lui envoie restent ce qu'ils étaient : lus, jamais gardés.

   Le détail. Trois outils, un ensemble proposé à la demande, seulement en privé à une personne authentifiée, en
   réponse comme en initiative : `share_text` (un nom nettoyé, une liste fermée d'extensions de texte, sans
   extension `.txt`), `project_files` (ce qu'elle peut envoyer de ses projets : il lui faut un moyen de nommer un
   fichier, les numéros de projet ne paraissant jamais en conversation) et `share_project_file` (projet vivant ; la
   personne parle en propriétaire, ou c'est elle qui l'a confié ; un sujet qu'elle peut entendre ; ni chemin caché —
   `.git`, `.env` —, ni fichier vide, ni hors de l'atelier). Trois fichiers au plus par épisode, tous outils
   confondus. L'identifiant d'un fichier se tire de l'épisode, de l'appel et du destinataire : une réponse recomposée
   retrouve le même fichier. Cinq paramètres (`Knob`) : `per_day` 10, `text_max_chars` 200 000, `project_max_mb` 10,
   `keep_days` 365, `per_person_mb` 200 (au moins 10, pour qu'un fichier de taille maximale tienne toujours), et
   500 fichiers gardés par personne au plus (`KEPT_PER_PERSON`). La rétention se programme à son échéance (le plus
   vieux fichier + `keep_days`, ou tout de suite au-delà du volume) ; un effet efface les octets **après** que
   `shares.expired` est écrit. Un fichier dont la parole n'est pas partie (une réponse abstenue ou remplacée) reste
   « pas parti » : la personne ne peut pas le télécharger, la rétention l'emporte. La section de prompt « CE QUE TU
   LUI AS DÉJÀ ENVOYÉ » (les trois derniers, sur trente jours) évite qu'elle renvoie le même fichier et lui permet de
   dire « je te l'ai envoyé hier ». Console : un onglet « Fichiers » sur la fiche d'une personne, une page par fichier
   (sujet `partage`, téléchargement opérateur `/inspecteur/telecharger/partage/<id>`). `mika forget` efface aussi les
   octets (serveur arrêté) ; le simulateur garde ses fichiers en mémoire d'un redémarrage à l'autre.

**Conséquences.** Contrats : `Registered.messaging` (défaut `None`), `vocab.privacy.MOBILE`, `ClientToken.client` et
`.source`, `Accounts.create_token(client=, source=)`, `token_client`, `has_mobile`, `prune_login_tokens` ;
`Conn.here`, `Conn.channel`, `Hub.watching` ; `protocol.PRESENCE_RATE`, `AWAY_GRACE_S`, `PRESENCE_HEADER` ;
`ToolResult.attach`, `Utterance.attachments`, `Delivery.attachments`, `MindPort.shared`, `MindPort.shared_file`,
`ProjectView.written`, la faculté `shares` et son port (`ShareStore` : `DiskShares` dans `data/partages/`, 0700/0600,
sauvegardé et restauré ; `MemoryShares` pour les essais). Aucun événement existant ne change de forme ; un journal ancien se rejoue à
l'identique (`messaging` absent ne dit rien). Un client ancien ignore la trame `presence` qu'il n'envoie pas et les
`attachments` de Mika qu'il ne lit pas. Le protocole complet, pour qui écrit un client : `docs/protocole-chat.md`.
Tests : `tests/protocol/test_mobile_auth.py`, `tests/unit/test_client_tokens.py`, `tests/unit/test_mobile_channel.py`,
`tests/protocol/test_mobile_presence.py`, `tests/protocol/test_mobile_files.py`, `tests/unit/test_shares.py`,
`tests/contract/test_shares_store.py`, et la page Comptes dans `tests/protocol/test_inspector_pages.py`.

**Reste.** Une application en arrière-plan sous Doze perd sa connexion jusqu'à la fenêtre de maintenance suivante :
le rattrapage par `sync` la rend juste, pas instantanée (une notification poussée — UnifiedPush — le serait).
L'application web envoie désormais `presence` sur `visibilitychange`, et `here: false` à l'ouverture d'un onglet
caché (issue #456) : un onglet que personne ne regarde n'est plus une présence. La voix n'est pas sur le téléphone (la synthèse
reste dans le navigateur, ADR 0050).
