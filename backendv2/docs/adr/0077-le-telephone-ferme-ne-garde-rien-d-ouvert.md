# 0077 — Le téléphone fermé ne garde rien d'ouvert : Firebase le notifie

**Contexte.** L'ADR 0062 faisait de l'application Android une messagerie en gardant sa connexion ouverte quand elle
était fermée : un service au premier plan (`remoteMessaging`), activé par défaut, relancé au démarrage du téléphone
et après chaque mise à jour, qui tenait le WebSocket en se déclarant absent. Le 2026-10-09, la propriétaire a
constaté que l'application vidait la batterie « à grande vitesse » sans avoir été ouverte. Trois causes, toutes
dans ce choix :

- deux battements de 20 s non synchronisés — le `ping` applicatif du client (`HEARTBEAT_INTERVAL_MS`) et le ping
  WebSocket d'uvicorn (`ws_ping_interval`, 20 s par défaut) : jusqu'à ~360 réveils par heure, jour et nuit ;
- hors de la maison, le serveur (le portable dédié, sur le Wi-Fi de la box) est injoignable en 4G : l'application
  réessayait **sans fin**, toutes les 30 s, chaque essai attendant 15 s une réponse qui ne viendrait pas — le modem
  ne redescendait presque jamais en veille, et chaque changement de réseau remettait l'attente à 1 s ;
- rien ne disait que le service tournait sinon une notification discrète : il démarrait seul après une mise à jour.

Ce que l'ADR 0062 notait déjà en « reste » : « une notification poussée le serait ». La propriétaire a choisi un
système de notification tiers, Firebase Cloud Messaging, et que l'application ne se connecte **que** quand on
l'ouvre ; le message lui-même doit arriver dans la notification, chiffré, pour être lisible hors de la maison.

**Décision.**

1. *L'application ne se connecte qu'ouverte.* Plus de connexion en arrière-plan ni de démarrage avec le téléphone :
   le réglage, le récepteur de démarrage, la demande d'exemption de batterie et leurs permissions sont retirés. La
   connexion vit tant que l'écran la tient (plus 30 s après l'avoir quitté, comme avant) ou le temps d'envoyer une
   réponse écrite dans une notification (un service au premier plan de 60 s au plus, comme avant pour qui coupait
   l'arrière-plan). Hors de portée, cette réponse reste dans la file d'envoi et part à la prochaine ouverture. La
   joignabilité ne change pas : elle vient d'un jeton `mobile` vivant (ADR 0062, `identity.registered`), pas d'une
   connexion ouverte — Mika écrit toujours la première à quelqu'un dont l'application est fermée.

2. *Le téléphone dit où le notifier.* `POST /auth/push {token, key}` sous le jeton de l'application (jamais à côté
   d'une `Origin`, jamais sous un jeton `screen`) : son jeton Firebase et une clé AES de 256 bits tirée par le
   téléphone, gardée chiffrée par son Keystore. Rangés sur la ligne du jeton (`client_tokens.push_token`, `push_key`,
   `push_at`, colonnes ajoutées à l'ouverture) : un jeton rendu ou révoqué les perd, un même jeton Firebase ne sert
   qu'un jeton de l'application (une réinstallation sans déconnexion ne notifie pas deux fois). La réponse dit
   `available` : le serveur a-t-il une clé Firebase. `DELETE /auth/push` retire l'inscription. L'application
   s'inscrit à chaque ouverture (jamais fermée : en 4G, un serveur de la maison ne répond pas — un jeton Firebase
   changé app fermée attend l'ouverture suivante), au plus tous les quarts d'heure tant que rien ne change, tout de
   suite quand le jeton, la clé ou le serveur changent ou que le serveur n'avait pas de clé : un serveur qui a oublié
   le téléphone (une base restaurée) le réapprend vite. Le jeton Firebase naît avec une session et meurt avec elle
   (initialisation automatique coupée au manifeste, `deleteToken` à la déconnexion, sans la retenir plus de 5 s).

3. *Ce qui part, et à qui.* À la livraison d'une parole (`Hub.deliver`), `adapters/web/push.py` applique la règle
   que l'application appliquait à ce qu'elle recevait en arrière-plan : une parole de Mika à une personne, dans le
   fil, avec du texte — jamais une pensée à voix haute, jamais le sort d'une question ; pas la réponse à une question
   posée d'un navigateur (on la lit là où on l'a posée), mais bien celle posée du téléphone (une réponse depuis la
   notification, connexion refermée depuis : `Hub._asked_from` garde la session qui a posé, au-delà de la connexion) ;
   à chaque téléphone du compte qui **ne la regarde pas par une connexion vivante** — application à l'écran
   (`Conn.here`) et une trame reçue depuis moins de 45 s (`push.LIVE_S` ; les clients pinguent toutes les 20 s). Une
   connexion « absente » (l'application quittée depuis peu) ne retient pas la notification, une connexion muette non
   plus : un téléphone sorti du Wi-Fi n'envoie pas de fermeture, et le serveur ne la constate qu'au bout de
   `WS_PING_TIMEOUT_S` (~5 min) — il aurait cru ce téléphone servi. L'application ne montre pas deux fois le même
   message (par identifiant). L'envoi part dans une tâche à part, jamais devant la livraison, et un téléphone en
   échec n'empêche pas les suivants ; un jeton Firebase mort (`UNREGISTERED`, 404) est oublié — ce jeton-là
   seulement, pas un jeton neuf donné entre-temps ; `SENDER_ID_MISMATCH` (la clé du serveur n'est pas celle du
   projet de l'application) est un échec de configuration, qui n'oublie aucun téléphone ; un échec se dit au journal
   et dans la console, et n'est pas réessayé (le message est dans le fil). À l'arrêt, ce qui part encore a 5 s, et
   rien de neuf ne part.

4. *Scellé pour le seul téléphone.* `adapters/push/seal.py` : le clair `{"t": "speech", "id", "text", "ts", "files"}`
   (jetons prosodiques retirés, texte coupé à 2 400 octets sur un caractère entier, et le clair sérialisé sous
   2 600 octets, échappements JSON compris), chiffré en AES-GCM avec la clé du
   téléphone, nonce de 96 bits à chaque envoi, données associées `fr.qwartz.mika/push/v1` ; les données du message
   Firebase sont `{"v": "1", "n", "c"}` (base64). Google ne transporte qu'un chiffré. Un message **de données** de
   priorité haute, pas un message « notification » : l'application le reçoit fermée, l'ouvre (`PushPayload`) et
   l'affiche dans la notification de conversation habituelle (`MessageNotifier.onPushed` : « Répondre », « Marquer
   comme lu »). Un message illisible n'est jamais montré.

5. *Firebase côté serveur.* `adapters/push/fcm.py` : l'API HTTP v1, un jeton d'accès OAuth 2 tiré d'une assertion
   JWT signée RS256 avec la clé d'un compte de service (`cryptography`, `httpx` : rien de neuf à installer), gardé
   jusqu'à une minute de sa fin, redemandé une fois sur un 401/403. La clé se pose dans le dossier de données, à
   côté de `secret.key` (`firebase-service-account.json`, droits 600 — un fichier lisible par d'autres est signalé
   au journal ; la sauvegarde l'emporte, la restauration lui rend ses droits), ou se colle dans la console
   (Réglages › Canaux › Notifications du téléphone), refusée en français si elle ne se lit pas, scellée comme les
   autres secrets, jamais réaffichée — collée, elle passe devant le fichier. Elle est relue à chaque envoi : ni
   l'une ni l'autre ne demande de redémarrer. La page dit d'où vient la clé, le projet, les téléphones notifiables,
   ce qui est parti et le dernier échec. Sans clé, rien ne part et rien n'est appelé.

6. *Firebase côté application.* `google-services.json` (non versionné, dans `app/`) est lu par la construction, qui
   en tire les ressources de chaque variante (`fr.qwartz.mika`, `fr.qwartz.mika.debug`) — ce que fait le greffon
   `com.google.gms.google-services`, sans lui. Sans le fichier, l'application se construit et marche : elle ne reçoit
   que ce qu'elle trouve en s'ouvrant, et ses paramètres le disent.

7. *Hors de la maison.* Une parole venue par Firebase n'est pas dans le fil tant que la connexion n'est pas revenue
   (l'application n'y insère rien : son curseur dépasserait des messages jamais reçus). La notification la garde donc
   jusqu'à ce que le fil l'ait, même application ouverte (`NotificationPolicy.unseen`) ; application ouverte sans
   connexion, une parole arrivée par Firebase est notifiée. « Marquer comme lu » va jusqu'à ce que la notification
   montrait, dit au serveur à la prochaine connexion. Firebase ne garantit pas l'ordre : une parole se reconnaît
   déjà montrée par son identifiant (les cent dernières), pas par un « dernier notifié ».

**Ce qui n'est pas fait.** Les paroles reçues par Firebase hors de la maison ne s'affichent pas dans le fil de
l'application (seulement dans le volet) : il faudrait des bulles provisoires que la fusion du fil (`ChatSync`,
portage du client web) remplacerait. Le serveur reste joignable seulement à la maison : répondre hors de la maison
demande de l'exposer (Tailscale, ou un mandataire TLS, `deploy/README.md`). Les cartes d'accord (ADR 0064) ne sont
pas notifiées, comme avant. Le ping WebSocket d'uvicorn reste à 20 s : il ne coûte plus rien au téléphone fermé.

**Conséquences.** Contrats : `adapters/push` (`FcmSender`, `seal`), `adapters/web/push.py` (`MobilePush`, `wanted`,
`recipients`, `LIVE_S`), `Hub.push`, `Hub._asked_from`, `Conn.seen_at`, `PushRegistration`, `Accounts.set_push` / `clear_push` /
`push_registrations` / `push_count`, `ClientToken.push`, `account_of_handle`, `create_app(push_ready=)`,
`Settings.push` / `save_push`, `settings.PUSH_KEY_FILE` / `push_key_file`, la section de réglages
`notifications`. Aucun événement ne change ; un client ancien
ne s'inscrit pas et n'est pas notifié (il recevait par sa connexion d'arrière-plan, qui marche toujours côté
serveur). Le protocole : `docs/protocole-chat.md` ; la mise en place : `deploy/README.md` et
`frontend/Android/README.md`. Tests : `tests/unit/test_push.py`, `tests/protocol/test_mobile_push.py`, la page de
réglages dans `tests/protocol/test_console_settings.py` ; côté application `PushPayloadTest` (un vecteur scellé par
le serveur), `PushRegistrarTest`, `NotificationPolicyTest`.
