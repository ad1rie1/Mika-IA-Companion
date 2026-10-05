# 0051 — L'adaptateur du monde : `/ws/world`, les jetons, le bail

> Réalise la P2 de l'ADR 0050. La spécification du fil reste [`docs/protocole-monde.md`](../protocole-monde.md) ;
> ce document dit ce que l'adaptateur garantit, et pourquoi.

**Contexte.** Le contrat du monde (`contracts/world.py`), ses trames (`adapters/world/protocol.py`) et la
faculté qui le tient (`faculties/world/`, avec `commands.handle`, qui rend un verdict sans rien écrire)
existaient ; aucun client ne pouvait s'y brancher. Un moteur de jeu (Unity) a trois besoins que le navigateur
n'a pas : s'authentifier **sans cookie ni `Origin`** ; savoir, après une coupure, ce qu'il a manqué ; tenir seul
le rôle d'hôte sans qu'un hôte figé bloque le monde. Et deux pièges attendaient : les `seq` du journal ne sont
pas contigus (le journal porte toute sa vie), alors que la spécification disait « un trou → `sync` » ; et
certains changements du monde ne viennent d'aucun événement `world.*` (le coucher naît de `body.fell_asleep`, le
réveil de `body.woke`).

**Décision.**

1. *Le port d'entrée gagne trois méthodes* (`contracts/entry.py`, `app/mindport.py`) : `world_view()` (la
   définition et l'état, lus sur la même racine) ; `world_command(command, *, actor, handle, operator, session)`
   — **un seul** `frame` pour décider (`faculties.world.commands.handle`) et pour écrire (`basis` + la garde du
   verdict ; une garde devancée rend `refused`/`stale`, rien d'écrit ; un brouillon sans clé reçoit
   `<session>:<cmd>:<i>`, celui qui en a une la garde — une fin d'action et son échéance ne terminent pas deux
   fois) ; `world_events(after, *, limit)` — ce qui a changé les écrans après `after`, jusqu'à la tête publiée :
   les types que la faculté `world` **réduit** (lus dans la composition, pas recopiés : un réflexe de plus s'y
   ajoute seul) et ceux qu'elle diffuse sans les réduire, jamais `world.noticed` ni `world.described`.
2. *L'adaptateur fait le bord, rien que le bord* (`adapters/world/server.py`) : authentification, rôles, bail,
   débits (`protocol.RATES`), dédoublonnage par connexion et `cmd`, traduction du journal en trames
   (`translate`). Il ne valide **rien** du monde ; `expect` passe tel quel dans la commande.
3. *Le journal, traduit.* Chaque trame porte le `seq` de son événement. Un événement d'une autre faculté que le
   monde réduit n'a pas de trame à lui : s'il a fait naître un réflexe, c'est l'`intent` du réflexe qui part,
   **avec le `seq` de l'endormissement** ; s'il a changé l'état autrement (le réveil), un `snapshot` suit ; s'il
   ne l'a pas changé (`state.seq` plus ancien que lui), rien. Une édition donne son `definition_delta` puis un
   `snapshot` (ce qu'elle a réconcilié ne se rejoue pas). En direct, la diffusion est l'écouteur du `Mind`
   (`app/server.py` : `mind.subscribe` → `KernelPort.world_update` → `WorldHub.publish`), synchrone : elle ne
   fait que mettre en file.
4. *Rien ne se perd sur une connexion ouverte.* L'accueil est d'un seul tenant (lire le monde, préparer
   `welcome`/`definition`/`snapshot` ou le rattrapage, s'inscrire aux diffusions : sans attente, donc sans commit
   intercalé). Chaque connexion a sa file d'envoi, bornée (1024) : une connexion lente est **fermée** (1013,
   `too_slow`) plutôt que de sauter une trame ou de retenir les autres, et revient par `hello.after`. Les poses,
   remplaçables, sont jetées d'abord. Donc un écart de `seq` ne dit rien, et la spécification le dit désormais.
5. *Le rattrapage est conservateur.* Plus de 500 événements du monde, un `after` inconnu du journal (plus récent
   que l'état : une sauvegarde restaurée), un changement sans action à rejouer dans l'intervalle, une révision
   différente : un `snapshot` (précédé de la définition si elle a changé).
6. *L'accusé d'abord.* Pendant qu'une commande est chez le noyau, les diffusions destinées à **sa** connexion
   attendent ; son `result` part, puis elles. Le client lit `accepted` (et le `seq`), puis la trame qui
   l'applique.
7. *Un seul hôte, par bail.* Accordé au premier opérateur qui demande `host`, pour 15 s, renouvelé par son
   `ping` ; perdu au silence (vérifié à chaque trame reçue et chaque seconde) ou à la déconnexion, et passé au
   premier opérateur qui l'attend (`host` `granted: true`) ; un hôte qui l'a perdu le reprend par son prochain
   `ping` s'il est libre. Un compte non opérateur ne l'obtient jamais (`host` `granted: false`, ses constats
   `not_host`). L'horloge du bail et des débits est injectable (`WorldHub.monotonic`).
8. *Les jetons de client natif* (`adapters/web/accounts.py`, table `client_tokens`) : par compte, préfixe
   `mw_`, 256 bits tirés au hasard, gardés en empreinte SHA-256 (un secret de cette entropie n'a pas besoin d'un
   hachage lent), montrés une seule fois, révocables un par un (`mika token create|list|revoke`). Un jeton parle
   sous l'adresse du compte (`user_<pk>`) : l'identité reste authentifiée. Révoqué, il prévient
   `on_token_revoke` et ses connexions se ferment (4401, sur `/ws/world` comme sur `/ws`) ; révoqué par la ligne
   de commande (un autre processus), la revérification périodique (10 s) et celle de chaque commande s'en
   chargent ; un compte désactivé, ou dont les droits changent, ferme aussi ses connexions. **Seulement sans
   `Origin`** : un navigateur ne peut pas poser d'en-tête sur un WebSocket, il garde sa session ; un jeton
   présenté avec une `Origin` est refusé sur `/ws/world`, ignoré sur `/ws`.
9. *Les erreurs se disent.* Une trame illisible reçoit `error` `bad_frame` (non fatale), dont la phrase nomme le
   champ et le `cmd` (un client qui attend cet accusé sait lequel est perdu) ; ce qui n'est pas un objet JSON en
   texte ferme (1003). Le dernier `loaded` de chaque hôte est gardé (`WorldHub.overview()`).

**Conséquences.**

- La spécification change sur un point : les `seq` sont croissants, pas contigus ; un client ne détecte pas une
  perte par un écart, il n'en subit pas sur une connexion ouverte, et rattrape par `hello.after` en revenant.
- Un `snapshot` peut arriver sans qu'on l'ait demandé (le réveil, une édition) : un client le pose comme à
  l'accueil.
- Ce que le noyau ne sait pas encore faire répond `unsupported` (les actes des personnes, la prose et ce
  qu'un premier éditeur ne change pas encore — pièces, lieux, personnages : P4, P5 ; ADR 0050 §11),
  et la `presence` à l'entrée attend P4 (aucun `world.joined` n'est écrit ici : sans corps dans l'état, une
  présence annoncerait quelqu'un que le monde ne contient pas).
- La console montre les clients du monde, qui tient le bail d'hôte et ce qui manque au moteur (Système › Le
  monde, côté écrans), lus à chaque rendu dans `WorldHub.overview()` : aucun événement, aucune faculté nommée.
- Un seul hôte pour tout le monde (ADR 0050) : plusieurs hôtes, un par pièce, seraient une révision.

Tests : `tests/unit/test_world_server.py` (chaque événement donne sa trame et son `seq` ; ce qui ne regarde
qu'elle n'en a pas ; le coucher porte le `seq` de l'endormissement ; le réveil demande un instantané, un
non-changement rien ; une édition dit sa révision ; une trame illisible nomme son champ et son `cmd` ; le port :
refus, écriture, progrès sans écriture, `stale` quand le monde a bougé entre la décision et l'écriture,
rattrapage borné, l'endormissement réel traduit en `intent` du coucher) et `tests/protocol/test_world_ws.py`
(sur l'application réelle, chaque trame relue par le schéma publié : accueil complet, client à jour, diffusion
et rattrapage par `hello.after` et `sync`, l'hôte termine une action — l'accusé d'abord, puis `intent_end` —,
`duplicate`, `rate_limited`, `not_host`/`not_creator`, `unsupported`, le bail unique perdu au silence et passé
au suivant, le compte non opérateur, le jeton accepté sans `Origin` et refusé avec, l'en-tête `Authorization`,
la session d'un navigateur, l'origine étrangère, la révocation qui ferme, `/ws` avec le jeton, la pose relayée
aux autres et ni à soi ni au journal, `bad_frame` puis la fermeture 1003). Non vides par mutation : sans la
retenue des diffusions, l'accusé arrive après `intent_end` ; une pose renvoyée à soi, un bail qui n'expire
jamais, un jeton accepté avec une `Origin` font tomber leur test.
