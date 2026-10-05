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
  ce à quoi elle repense, le rêve de la nuit, son dernier journal, qui elle est devenue, ses besoins, et ses
  projets en cours si tu es propriétaire. Une carte sans données n'apparaît pas.
- **Mika en fond** : derrière la conversation, Mika en 3D native, dans une lumière qui suit son humeur. Elle vit
  (souffle, gestes, regard, clignements, cheveux), te salue à la mesure de ton absence (un hochement après un
  moment, un coucou après sa nuit, jamais joyeux si elle est fâchée) et s'endort la nuit (lumière
  bleue, étoiles en thème sombre). Désactivable (Paramètres › Apparence). Voir
  [Mika en fond](#mika-en-fond-3d-native).
- **Paramètres** : compte et déconnexion, connexion en arrière-plan, démarrage avec le téléphone, batterie,
  notifications, thème (système / clair / sombre, couleurs dynamiques), « Effacer les messages de ce téléphone ».

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
- sa réponse s'écrit dans la bulle au rythme de sa bouche, sur une seule horloge (`avatar3d/Utterance`), et toucher
  la bulle affiche tout ;
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

## La connexion en arrière-plan, les notifications et la batterie

- **« Rester connectée en arrière-plan »** (activé par défaut) : un service au premier plan garde la connexion
  ouverte quand l'application est fermée. Une notification discrète (« Connectée à Mika », « Reconnexion… »,
  « Hors ligne ») l'indique ; son bouton « Désactiver » coupe le réglage. Cette connexion se déclare **absente**
  au serveur (`X-Mika-Presence: away`) : Mika sait que tu peux recevoir ses messages, pas que tu es devant
  l'écran. Au retour de l'application au premier plan, l'app annonce ta présence (`presence here`) ; quand tu la
  quittes, ton absence (le serveur attend 20 s : prendre une photo et revenir ne compte pas).
- **Notifications** : l'autorisation est demandée une fois, à la première ouverture de la conversation, avec une
  explication. Une notification par conversation, avec « Répondre » (directement depuis la notification) et
  « Marquer comme lu ». Un rattrapage après une coupure donne une seule notification groupée. Rien n'est notifié
  quand l'application est à l'écran, ni pour ses pensées à voix haute, ni pour les réponses à une question posée
  depuis un autre appareil, ni pour l'historique reçu à la toute première connexion. Ouvrir la conversation
  efface la notification.
- **« Démarrer avec le téléphone »** : relance la connexion après un redémarrage sans ouvrir l'app.
- **Batterie** : certains fabricants endorment les services en arrière-plan. Le bouton « Ne pas restreindre
  Mika » (Paramètres › Batterie) demande l'exemption ; l'app ne la demande jamais d'elle-même.
- Sans connexion en arrière-plan, l'app ne reçoit rien une fois fermée : ce qu'elle a dit t'attend à la prochaine
  ouverture. Une réponse depuis une notification démarre quand même un service le temps de son envoi (60 s au plus).

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
d'accord) est du Kotlin pur. Les
tests instrumentés (`app/src/androidTest`) éprouvent Room en mémoire (`ChatStoreTest`) et les écrans Compose
(`ChatScreenTest`, `LoginScreenTest`, `MindScreenTest`).

## Organisation du code

| Paquet | Contenu |
|---|---|
| `core` | `AppGraph` (le graphe de l'app, à la main), horloges, premier plan, réseau |
| `data/net` | protocole, trames, `MikaSocket` (reconnexion, battement, file d'envoi), adresse du serveur |
| `data/db` | Room : messages, file d'envoi, petites valeurs |
| `data/chat` | `ChatSync` (fusion du fil, portage du client web), `ChatEngine`, `ChatRepository` |
| `data/mind` | l'état de Mika, ses libellés, la ligne d'état |
| `data/approvals` | les cartes d'accord : leurs règles (`Approvals`, testées) et la liste en cours |
| `avatar3d` | Mika en 3D native : VRM, squelette, mouvements, machine à états, couches du corps, visage, ressorts, rendu Filament |
| `data/avatar` | ses portraits (repli) : le manifeste, le choix du portrait, le rythme des clignements |
| `data/auth` | jeton chiffré (Keystore), connexion, erreurs en français |
| `data/files` | pièces jointes (préparation, réduction), brouillon, partages reçus, fichiers de Mika |
| `service` | connexion voulue, service au premier plan, notifications, réponse depuis une notification, démarrage |
| `share` | « Partager vers Mika », raccourci de conversation |
| `ui` | écrans Compose : connexion, conversation, « Ce qu'elle fait », paramètres, visionneuse |
| `ui/avatar` | Mika en fond : chargement des portraits, l'aura, le souffle, les clignements, le sommeil, son visage dans la barre |
