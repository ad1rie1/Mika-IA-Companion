# Mika pour Android

Une messagerie, avec une seule conversation : celle avec Mika. On lui écrit, on lui envoie des photos et des
fichiers, elle répond — et, comme dans une vraie messagerie, elle peut écrire la première quand l'application est
fermée (un rappel qui échoit, une prise de nouvelles). On voit aussi un peu ce qu'elle fait : sa ligne d'état sous
son nom, et l'écran « Ce qu'elle fait ».

Le serveur est `backendv2/` (`python -m mika serve`). Le protocole est décrit dans
[`backendv2/docs/protocole-chat.md`](../../backendv2/docs/protocole-chat.md) et les décisions dans l'ADR 0062.

## Ce que fait l'application

- **Connexion** avec le compte que tu utilises sur la page web de Mika (nom d'utilisateur et mot de passe). Le
  mot de passe sert une fois : le serveur rend un jeton propre à ce téléphone, gardé chiffré par le Keystore
  Android. La session dure jusqu'à ce que tu te déconnectes, ou qu'un opérateur révoque le téléphone.
- **La conversation** : bulles, heures, séparateurs de date, état de chaque message (en attente, envoyé, lu,
  refusé + « Réessayer »), gras et code mis en forme, « Mika écrit… ». Un message tapé hors ligne part tout seul
  au retour du réseau, même si l'application a été tuée entre-temps. Sous une réponse qui n'est pas venue
  (`no_reply`, `too_late`), « Le lui redemander » renvoie le même texte et les mêmes fichiers comme un nouveau
  message ; la bulle d'origine reste.
- **Le mode pro** (ADR 0116), pour une opératrice : la pastille « Pro » dans le champ (retenue sur le téléphone)
  envoie le message en mode pro (`chat.mode`). Pendant qu'elle travaille, une carte montre ses outils en direct
  (trames `tool` : en cours, ✓ ou ✗, durée ; dépliables en texte brut), jamais gardée en base ; elle se replie au-dessus
  de la réponse, une seule bulle en Markdown (tableaux compris) que sa voix ne lit pas. L'historique montre la ligne
  de ses outils. Pastille allumée, le travail prend tout l'écran : Mika quitte le fond (sa 3D ne tourne plus, son
  visage reste dans la barre), le fil n'a plus de bande sous son visage, ses réponses et ses cartes prennent toute la
  largeur, en texte plus serré. Une réponse depuis une notification part toujours en message ordinaire.
- **Les fils de travail** (ADR 0164) : pastille allumée, la conversation devient un client à plusieurs fils, chacun son
  contexte — Mika n'y relit que les messages du fil, sous son titre et sa petite description. Le fil avec elle est
  caché ; pastille éteinte, il revient seul (aucun message d'un fil de travail). Une barre au-dessus du fil dit le fil
  ouvert (toucher son nom le règle : titre, description, archivé) ; « Fils » ouvre la liste (titre, sinon le début du
  premier message ; archivés repliés à part), « Nouveau » un fil neuf. Le fil ouvert est retenu sur le téléphone. Dans
  le champ : `/clear` (ou `/nouveau`) ouvre un fil neuf sans rien effacer, `/renommer <titre>`, `/description <texte>`,
  `/archiver`, `/desarchiver`, `/aide` ; `//` en tête envoie le message avec un seul `/`. Chaque message garde son fil
  (`chat.strand`, base version 5) ; un fil ouvert ici dont le serveur a plus de messages les demande
  (`strand_history`). Code : `data/chat/Strands.kt` (pur), `ui/chat/StrandParts.kt`.
- **Les cartes d'accord** (ADR 0064) : quand Mika veut appeler un service extérieur et que c'est à toi d'en
  décider, une carte apparaît au-dessus de la barre de saisie — ce qu'elle veut faire, **exactement ce qui partira**
  (en texte brut, à chasse fixe, jamais interprété), le compte à rebours (« expire dans 4 min ») et deux boutons,
  « Accepter » et « Refuser ». Seul le bouton décide : un « oui » tapé dans la conversation ne vaut jamais accord.
  « Accepter » s'éteint quand la carte est bloquée (la raison est dite), expirée, incomplète, hors ligne, ou quand
  une décision est déjà partie ; hors ligne, rien n'est mis en file. Le sort de la décision s'affiche un instant
  (« Refusé : rien ne partira. »). Trames : `approvals` (la liste entière, qui remplace la précédente ; chaque
  connexion repart d'une liste vide, le serveur n'envoie la liste à l'ouverture que si elle n'est pas vide),
  `approval_result` (le sort), et côté app `approval` (`id`, `decision`, l'empreinte `digest` de la carte montrée).
- **Envoyer des fichiers** : Photos, Appareil photo, Fichier (images, audio, texte, CSV, Markdown, JSON, PDF),
  jusqu'à 5 fichiers de 5 Mo par message (11 Mo au total). Les photos trop lourdes sont réduites en JPEG (côté
  long ≤ 2 048 px), ce qui retire aussi l'EXIF et la position GPS. Le brouillon (texte et fichiers) survit à la
  fermeture de l'application.
- **« Partager vers Mika »** depuis la galerie, le navigateur ou n'importe quelle application : le texte et les
  fichiers arrivent dans la barre de saisie. Partagé sans être connectée, tout attend la connexion.
- **Ses fichiers à elle** : vignette pour une image (touchée, elle s'agrandit), puce avec nom et taille sinon ;
  « Enregistrer » (dans Téléchargements/Mika) ou « Ouvrir avec… ».
- **« Ce qu'elle fait »** : humeur, corps (sommeil, énergie, où elle est, moment de la journée), estime de soi,
  ce à quoi elle repense, le rêve de la nuit, son dernier journal, qui elle est devenue, ce qu'elle sait de toi
  (sous quel nom elle te reconnaît et, si ta fiche t'est ouverte, où vous en êtes, son ton, tes intérêts, ce à
  quoi elle fait attention), ce qu'elle t'a promis, ses besoins, et ses projets en cours si tu es propriétaire.
  Une carte sans données n'apparaît pas.
- **Mika en fond** : derrière la conversation, Mika en 3D native, dans une lumière qui suit son humeur. Elle vit
  (souffle, gestes, regard, clignements, cheveux), te salue à la mesure de ton absence (un hochement après un
  moment, un coucou après sa nuit, jamais joyeux si elle est fâchée) et s'endort la nuit (lumière
  bleue, étoiles en thème sombre). Désactivable (Paramètres › Apparence). Voir
  [Mika en fond](#mika-en-fond-3d-native).
- **« Lui dire où je suis »** (ADR 0119, coupé par défaut) : application ouverte, la position du téléphone part à
  Mika — les coordonnées exactes et le nom du lieu trouvé par le téléphone (`Geocoder`). Voir
  [Sa position](#sa-position).
- **« Lui montrer mes messages »** (ADR 0120, coupé par défaut) : les messages WhatsApp et SMS que le téléphone affiche
  partent à Mika, qui s'en souvient ; elle peut proposer une réponse, qu'une notification te demande d'autoriser. Voir
  [Ses messages](#ses-messages).
- **Paramètres** : compte et déconnexion, notifications (et si elles arrivent application fermée), « Lui dire quand
  j'ai lu », « Lui dire où je suis », « Lui montrer mes messages », thème (système / clair / sombre, couleurs
  dynamiques), « Effacer les messages de ce téléphone ».

Hors périmètre : la voix (ni messages vocaux, ni lecture à voix haute) et le monde 3D (la chambre, les déplacements :
c'est le client Unity).

## Construire

Outils attendus sur cette machine : le JDK 25 (`/usr/lib/jvm/java-25-openjdk`) et le SDK Android dans
`~/Android/Sdk` (le fichier `local.properties`, non commité, pointe dessus).

```bash
cd frontend/Android
export JAVA_HOME=/usr/lib/jvm/java-25-openjdk
export ANDROID_HOME=~/Android/Sdk
./gradlew assembleDebug
```

Pour les notifications application fermée, pose d'abord le `google-services.json` du projet Firebase dans `app/`
(jamais versionné ; voir [Les notifications et la batterie](#les-notifications-et-la-batterie)). Sans lui, l'app se
construit et marche, sans notifications application fermée — la construction le dit.

L'APK de débogage est dans `app/build/outputs/apk/debug/app-debug.apk` ; il s'installe à côté d'une version
« release » (identifiant `fr.qwartz.mika.debug`, nom « Mika (dev) »). `./gradlew assembleRelease` produit une
version minifiée, signée avec la clé de débogage (rien n'est publié sur un magasin).

> La machine est partagée : une construction complète prend ~2 Gio de mémoire. Lance-la seule, sans démon
> (`--no-daemon`), et de préférence à travers `~/recup-audit-v2-2026-10-01/outils/borne.sh`.

## Mika en fond (3D native)

Derrière la conversation, Mika est rendue **en 3D native avec Filament** (le moteur 3D de Google), dans la lumière
de son humeur. Elle respire et bouge, joue les mouvements de l'atelier, fait des gestes quand elle répond, cligne des
yeux, te regarde, pose son regard sur toi quand tu écris et regarde ailleurs quand elle compose sa réponse. Ses
cheveux et ses vêtements suivent ses mouvements, et elle bâille quand elle est fatiguée, puis s'endort la nuit.
Le comportement est celui du client web, porté en Kotlin pur et testé sur la JVM (`avatar3d/`). Décision : ADR 0067.

Elle vit la conversation (ADR 0067, point 6) :
- les derniers messages tiennent dans une bande en bas et s'effacent avant son visage ;
- remonter dans l'historique la met en retrait ;
- chaque bulle de sa réponse arrive entière, comme un SMS, quand sa bouche commence à la dire ; la suivante attend
  qu'elle l'ait dite, ses trois points à sa place, sur une seule horloge (`avatar3d/Utterance`), et toucher la bulle
  la fait taire ;
- un message qu'on envoie, elle le lit, puis hoche la tête.

Ces signaux viennent de `ui/chat/ConversationCues.kt` (`ConversationCues`, `SpeechTrack`).

- **Le modèle** n'est pas versionné : il est sous licence de l'acheteur. On le prépare pour le téléphone depuis le
  VRM du client web, sans perte de qualité : textures en pleine résolution, morphoses inutilisées retirées (Filament
  en accepte 256 au plus), maillage du visage découpé par matériau pour un chargement rapide. Il fait ~30 Mo :

  ```bash
  python3 frontend/Android/tools/vrm_mobile.py   # → app/src/main/assets/avatar3d/mika.glb (ignoré par git)
  ```

- **Les animations** sont les mouvements de l'atelier (`frontend/Unity/ArtSource/atelier/motions`, ceux qu'Unity
  importe) et le manifeste du client web (`frontend/Web/public/animations/manifest.json`). Ils sont copiés dans
  l'APK à chaque construction : il n'y a qu'une seule source.
- **Repli.** Sans le modèle préparé, l'app montre les portraits pré-rendus de l'ADR 0065
  (`frontend/Web/assets-src/blender/portraits.py`, ignorés par git eux aussi). Sans portraits non plus, pas d'avatar,
  et l'interrupteur « Mika en fond » (Paramètres › Apparence) n'apparaît pas.
- **Batterie.** Elle n'est dessinée que quand l'écran est visible, à 60 images/s au plus, même sur un écran à 120 Hz.

En version de débogage, **le studio 3D** montre Mika sans serveur ni compte. On y règle chaque émotion « dite »
(geste permis) ou « en dérive » (posture seulement), le sommeil et la fatigue :

```bash
adb shell am start -n fr.qwartz.mika.debug/fr.qwartz.mika.studio.Avatar3DStudioActivity [--ez dark true]
```

## Installer

Téléphone en mode développeur avec le débogage USB activé (ou émulateur démarré) :

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## Se connecter au serveur

L'adresse du serveur se saisit à l'écran de connexion (`http://` est ajouté si tu l'omets).

| Situation | Côté serveur | Adresse dans l'app |
|---|---|---|
| Émulateur sur cette machine | `python -m mika serve` | `http://10.0.2.2:8001` |
| Téléphone en USB | `python -m mika serve` puis `adb reverse tcp:8001 tcp:8001` | `http://localhost:8001` |
| Téléphone sur le Wi-Fi de la maison | `python -m mika serve --host 0.0.0.0` | `http://192.168.x.y:8001` |
| Tailscale | `--host 0.0.0.0` (ou l'adresse Tailscale) | `http://machine.xxx.ts.net:8001` |
| Hors de chez toi | un mandataire TLS devant (voir `backendv2/deploy/README.md`) | `https://mika.example.org` |

En `http://` hors de Tailscale, l'écran de connexion prévient : le mot de passe et les messages passent en clair
sur le réseau. Préfère `https://` dès que tu sors de chez toi. Derrière un mandataire, il doit laisser passer les
en-têtes `Authorization` et `X-Mika-Presence` à la mise à niveau WebSocket et ne pas couper une connexion
silencieuse avant 120 s.

Si le serveur répond « ce serveur ne propose pas encore la connexion par jeton », il est trop ancien pour l'app :
mets Mika à jour. En version de débogage, le lien « Utiliser un jeton (dev) » accepte un jeton créé à la main
(serveur arrêté) : `python -m mika token create <compte> --client mobile --label android`.

## Les notifications et la batterie

- **L'application ne se connecte qu'ouverte** (ADR 0077). Fermée, elle ne garde aucune connexion : ni service en
  arrière-plan, ni démarrage avec le téléphone. C'est ce qui ménage la batterie — une connexion gardée ouverte se
  réveillait toutes les 10 à 20 s, et réessayait sans fin quand le serveur de la maison était hors de portée (en 4G).
  Au premier plan, l'app annonce ta présence (`presence here`) ; quand tu la quittes, ton absence (le serveur
  attend 20 s : prendre une photo et revenir ne compte pas), et la connexion se ferme 30 s plus tard.
- **Application fermée, ses messages arrivent par Firebase** (Firebase Cloud Messaging), **chiffrés pour ce
  téléphone seul** : l'app tire une clé AES à la connexion, gardée par le Keystore, et la donne au serveur avec son
  jeton Firebase (`POST /auth/push`) ; le serveur scelle chaque message avec elle, Google ne transporte qu'un chiffré.
  L'app le déchiffre et l'affiche dans la notification de conversation habituelle. Il faut, une fois : un projet
  Firebase où l'application est déclarée, son `google-services.json` dans `app/` à la construction, et la clé d'un
  compte de service **côté serveur** — `firebase-service-account.json` dans son dossier de données, ou collée dans
  sa console ; jamais dans l'app (pas à pas : `backendv2/deploy/README.md`, « Notifications du téléphone »). L'app le redit au serveur à chaque ouverture chez toi (au plus tous les quarts d'heure). Paramètres ›
  Notifications › « Application fermée » dit où elle en est (active, en attente, serveur sans clé, version sans
  Firebase) avec « Réessayer ».
- **Hors de chez toi**, la notification arrive (elle passe par Google) mais l'app ne joint pas le serveur : le
  message n'entre dans le fil qu'à la prochaine connexion. D'ici là, la notification le garde, même app ouverte.
  Une réponse écrite dans la notification attend dans la file d'envoi et part à la prochaine ouverture chez toi.
- **Notifications** : l'autorisation est demandée une fois, à la première ouverture de la conversation, avec une
  explication. Une notification par conversation, avec « Répondre » (directement depuis la notification) et
  « Marquer comme lu ». Un rattrapage après une coupure donne une seule notification groupée. Rien n'est notifié
  quand l'application est à l'écran, ni pour ses pensées à voix haute, ni pour les réponses à une question posée
  depuis un autre appareil, ni pour l'historique reçu à la toute première connexion. Ouvrir la conversation
  efface la notification.
- **« Lui dire quand j'ai lu »** (Notifications, activé par défaut) : l'app dit au serveur jusqu'à quel message
  tu as lu (la conversation à l'écran, ou « Marquer comme lu »), trame `read` — une seule valeur, ni l'heure où tu
  es en ligne, ni le temps passé à l'écran. Mika sait alors si ce qu'elle t'a écrit a été vu : un téléphone qui
  dort ne la fait pas se sentir ignorée. Coupé, rien ne part.
- Une réponse depuis une notification démarre un service le temps de son envoi (60 s au plus, notification « Envoi
  de ta réponse à Mika »). Sans Firebase, l'app ne reçoit rien une fois fermée : ce que Mika a dit t'attend à la
  prochaine ouverture.

## Sa position

« Lui dire où je suis » : décision dans l'ADR 0119. Le réglage est dans Paramètres › Position, **coupé par défaut**.

- **L'autorisation** de localisation est demandée en l'activant : précise ou approximative (Android 12 et plus laisse
  choisir), l'une ou l'autre suffit. Refusée, le réglage reste coupé et le dit, avec un lien vers les réglages du
  téléphone. Retirée plus tard dans les réglages du téléphone, rien ne part (le réglage le dit) et la position s'efface
  chez Mika ; le rallumer redemande l'autorisation.
- **Seulement application au premier plan** (ADR 0077) : l'app écoute la localisation tant qu'elle est à l'écran (une
  mesure par minute au plus, pas moins de 30 s ni de 50 m entre deux), et plus du tout dès qu'elle passe en
  arrière-plan — même si la connexion reste ouverte 30 s, ou s'ouvre le temps d'une réponse depuis une notification.
  Ni `ACCESS_BACKGROUND_LOCATION`, ni service, ni notification permanente.
- **Ce qui part** : la trame `where` (`lat`, `lon`, la précision en mètres, le nom du lieu, l'âge de la mesure), redite
  à chaque ouverture de la connexion — l'âge est compté au moment où elle part. Le serveur ignore une mesure de plus de
  24 h et ne réécrit pas une position qui n'a pas bougé.
- **Couper le réglage** envoie `where` `off` : sa dernière position s'efface chez Mika. **Se déconnecter** l'efface
  aussi, et remet le réglage à zéro : un autre compte n'en hérite jamais.
- **Elle ne la regarde que quand vous vous parlez**, en tête-à-tête, par un outil — jamais d'elle-même, jamais en
  salon. Chaque fois, une **petite bulle** le montre juste avant sa réponse : « 📍 Mika a regardé où tu es · Rue de la
  République, Lyon · position de 14:10 » (l'heure seulement si la position avait plus de 2 min, le jour si elle date
  d'un autre jour ; sans lieu une fois la position oubliée). Elle vient du champ `notes` de sa réponse (`speech`,
  `history`), gardé en base avec elle.

## Ses messages

« Lui montrer mes messages » : décision dans l'ADR 0120. Le réglage est dans Paramètres › Ses messages, **coupé par
défaut**.

- **L'accès aux notifications** s'accorde dans les réglages d'Android (« Accès aux notifications ») : le bouton y mène,
  et l'interrupteur s'allume au retour s'il a été accordé. Retiré plus tard, rien ne part (le réglage le dit).
- **Ce qui est lu** : seulement les applis cochées — WhatsApp (et WhatsApp Business), Messages (Google et Samsung) —,
  jamais une liste d'exclusions : ni la banque, ni les codes. Les groupes seulement si « Les groupes aussi » est coché.
  Le lecteur (`service/PhoneListenerService`) lit le `MessagingStyle` de chaque notification : la conversation, qui
  écrit, le texte, l'heure, et si c'est toi qui as écrit. Le tri est pur et testé (`data/phone/PhoneReading`).
- **Ce qui part** : `POST /api/phone/inbox`, par lots de 200, sous le jeton de l'app. La conversation et l'expéditeur
  ne partent qu'en clés opaques (`sha256` de l'appli et de l'identifiant que donne la notification, 32 caractères) ; le
  nom affiché et le texte partent en clair.
- **En 4G**, le serveur de la maison ne répond pas : les messages attendent dans une file sur le téléphone (500 au plus,
  les plus anciens tombent), et repartent au retour du réseau, à l'ouverture de l'app, ou au message suivant — pas
  avant 10 min après un échec. Aucune connexion ne reste ouverte (ADR 0077). Paramètres › Ses messages dit combien
  attendent, ou si le serveur refuse (seule sa propriétaire peut lui montrer ses messages).
- **Ses réponses proposées** arrivent par Firebase, scellées comme ses paroles (`{"t": "phone_draft", …}`) : une
  notification « Répondre à Léa (WhatsApp) ? », le texte entier, avec **Envoyer**, **Écrire autre chose** et
  **Ignorer** (balayer la notification compte comme « Ignorer »). Le geste vaut accord, et marche aussi en 4G.
  « Envoyer » passe par l'action « Répondre » de la notification de WhatsApp ou de Messages, gardée en mémoire
  seulement ; si elle n'existe plus (notification balayée, appli redémarrée), le texte est copié et la notification
  ouvre l'appli pour le coller. Le sort repart au serveur (`POST /api/phone/settled`) par la même file. Sans geste, la
  proposition expire (2 h) et la notification disparaît.
- **Couper** le réglage vide la file et oublie les actions gardées ; Android cesse alors d'appeler le lecteur.
  **Se déconnecter** fait de même et remet le réglage à zéro : un autre compte n'en hérite jamais.

## Se déconnecter, révoquer un téléphone

- **Se déconnecter** (Paramètres) rend le jeton au serveur et efface du téléphone les messages, les fichiers, les
  vignettes et les notifications. L'adresse et le nom d'utilisateur restent pré-remplis.
- **Révoquer un téléphone perdu** : dans la console, **Comptes**, révoque son jeton (il porte le nom
  « Android · fabricant modèle »), ou `python -m mika token revoke <id>`. Le téléphone est déconnecté à sa
  prochaine connexion (« Ta session a expiré ou a été révoquée — reconnecte-toi. ») et efface ce qu'il gardait.
  Changer le mot de passe du compte révoque aussi les jetons obtenus avec l'ancien.

## Tests

```bash
./gradlew testDebugUnitTest          # le cœur, sur la JVM (protocole, fil, socket, notifications, fichiers…)
./gradlew lintDebug
./gradlew assembleDebugAndroidTest   # compile les tests instrumentés
./gradlew connectedDebugAndroidTest  # les exécute sur un émulateur ou un téléphone branché
```

Les tests JVM n'ont besoin d'aucun émulateur : le moteur (protocole, fusion du fil, socket, décisions de
notification, réduction des images, partage, navigation, cartes de « Ce qu'elle fait », choix du portrait, cartes
d'accord, ce qui part de sa position et sa petite bulle, ouverture d'un message Firebase — `PushPayloadTest` en ouvre un scellé par le serveur —, inscription aux
notifications, tri des notifications de WhatsApp et de Messages, leurs clés opaques, leur file et son envoi, les
réponses proposées) est du Kotlin pur. Les
tests instrumentés (`app/src/androidTest`) éprouvent Room en mémoire (`ChatStoreTest`) et les écrans Compose
(`ChatScreenTest`, `LoginScreenTest`, `MindScreenTest`).

## Organisation du code

| Paquet | Contenu |
|---|---|
| `core` | `AppGraph` (le graphe de l'app, à la main), horloges, premier plan, réseau, localisation |
| `data/net` | protocole, trames, `MikaSocket` (reconnexion, battement, file d'envoi), adresse du serveur |
| `data/db` | Room : messages, file d'envoi, petites valeurs |
| `data/chat` | `ChatSync` (fusion du fil, portage du client web), `ChatEngine`, `ChatRepository` |
| `data/mind` | l'état de Mika, ses libellés, la ligne d'état |
| `data/approvals` | les cartes d'accord : leurs règles (`Approvals`, testées) et la liste en cours |
| `avatar3d` | Mika en 3D native : VRM, squelette, mouvements, machine à états, couches du corps, visage, ressorts, rendu Filament |
| `data/avatar` | ses portraits (repli) : le manifeste, le choix du portrait, le rythme des clignements |
| `data/auth` | jeton chiffré (Keystore), connexion, erreurs en français |
| `data/files` | pièces jointes (préparation, réduction), brouillon, partages reçus, fichiers de Mika |
| `data/location` | « Lui dire où je suis » : ce qui part (`WhereShare`, selon le réglage et le premier plan), le nom du lieu (`PlaceLabel`) ; la localisation elle-même est dans `core/LocationMonitor` |
| `service` | connexion voulue, notifications, réponse depuis une notification (et son service de 60 s) ; le lecteur des notifications du téléphone (`PhoneListenerService`) et les réponses proposées (`PhoneDraftNotifier`) |
| `data/phone` | « Lui montrer mes messages » (ADR 0120) : les applis lues, le tri des notifications (`PhoneReading`), les clés opaques, la file et son envoi (`PhoneOutbox`), les réponses proposées (`PhoneDrafts`), les actions « Répondre » gardées en mémoire |
| `data/push` | les notifications par Firebase : ouvrir un message scellé (`PushPayload`), dire au serveur où notifier (`PushRegistrar`) |
| `push` | Firebase lui-même : le jeton (`FirebasePush`) et la réception (`MikaMessagingService`) |
| `share` | « Partager vers Mika », raccourci de conversation |
| `ui` | écrans Compose : connexion, conversation, « Ce qu'elle fait », paramètres, visionneuse |
| `ui/avatar` | Mika en fond : chargement des portraits, l'aura, le souffle, les clignements, le sommeil, son visage dans la barre |
