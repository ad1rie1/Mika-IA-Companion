# Mika — le client web

Vite, Three.js, VRM, TypeScript. Le client parle au moteur (`backendv2`) par le protocole du chat
(`backendv2/docs/protocole-chat.md`) et regarde son monde par `mika.world/1` (`backendv2/docs/protocole-monde.md`).

## Commandes

```bash
npm install
npm run dev        # http://localhost:3000, vise http://localhost:8001
npm run build      # passe par tsc : la vraie barrière
npm test           # vitest
```

- Une autre adresse du moteur : `VITE_BACKEND_ORIGIN` dans `.env.local` (voir `.env.example`).
- **Studio** : `npm run dev` puis `/studio.html` donne l'avatar sans backend ni connexion.

## Architecture (`src/`)

`main.ts` ne fait que câbler. Il construit les objets et branche chaque trame WebSocket et les événements de la voix
sur `ui/SpeechPresenter.ts`.

**Synchronisation de la voix et du corps** (`ui/SpeechPresenter.ts`, testé par des doublures)

- Les lectures (`EmotionDisplay`, `InnerLifePanel`) changent à la trame `speech`. L'avatar (visage, geste, regard,
  mains) change au **début réel** de l'énoncé, `tts.speak(…, { onStart })`.
- La dérive d'humeur (`emotion_update`) est retenue pendant qu'une réponse parlée est en vol : la plus récente gagne,
  avec une soupape `VOICED_HOLD_MAX_MS`.
- Au réveil, elle observe un silence de 1,3 s.

**Les clips** viennent de l'atelier d'animation d'Unity : `public/animations/atelier` est un lien vers
`frontend/Unity/ArtSource/atelier/motions/`, que `vtuber/animation/atelierClip.ts` passe sur les os normalisés du VRM
(le même squelette, la même formule que le retargeting Mixamo, qui reste possible clip par clip). La marche se joue à sa
vitesse de capture ; l'assise (`posture`) et les occupations debout (`activity` : fenêtre, bibliothèque) aussi. Le bureau
(`vtuber/animation/desk/`, port de `BodyActivity`) joue les clips `desk_*` et `chair_*` : la chaise passe de « home » à
« type » (19,45°, 25,5 cm) ou « write » par les courbes de ses gestes, pivote vers qui lui parle, et elle ne se lève qu'une
fois la chaise rentrée ; la tasse, le stylo et la souris (sortis de `Desk_Props`) suivent ses mains.

**Le corps** (`vtuber/animation/AnimationSystem.ts`) suit, à chaque image, cet ordre :

1. pose de repos ;
2. machine à états (repos, parole, geste, sommeil, marche, posture) ;
3. le mixer des clips (atelier Unity ou Mixamo, reciblés à l'exécution), et leurs jumeaux miroirs `~m` ;
4. `AttentionDirector`, pur : contact, aversion en planifiant une phrase, réflexion, écoute, voix intérieure, errance
   au bout de 25 s seule ;
5. les surcouches additives : respiration, vie, sommeil, tête émotionnelle, tête d'attention, battements de la parole ;
6. les mains ;
7. le regard (les yeux visent le résidu après la tête : réflexe vestibulo-oculaire) ;
8. les clignements ;
9. le visage idle.

Deux règles le tiennent :

- **Une seule convention de squelette.** Tout se calcule en convention VRM 1.0, conjugué par Ry(π) pour un modèle 0.x
  (`vrmVersion.ts::forwardSign`). Les tests vérifient la géométrie, jamais une constante de signe.
- **Les gestes** (`gestures.ts`) suivent la table `EMOTION_GESTURE` sur les 29 émotions et `decideGesture()`. Une
  posture tenue ne se lâche que sous le seuil moins `VARIANT_HYSTERESIS`. Une dérive change la posture, jamais un geste
  ponctuel.

**Le visage**

- Quatre écrivains sur des expressions disjointes : émotions (`EmotionController`, avec des copies `clean:` sans
  symboles manga ; l'émotion secondaire du mélange à `SECONDARY_SHARE`), visèmes (`LipSyncController`, français
  graphème → visème, recalé sur la voix par `onSpeechProgress`), clignements, micro-mouvements ARKit (`FaceIdleController`).
- La physiologie a son horloge (`FacePhysiology.ts`) : rougeur, larmes qui montent, pupilles.

**La locomotion** (`vtuber/locomotion/`)

- C'est le backend qui décide du lieu (`inner_state.place`) et de l'activité (`inner_state.activity`). Le client
  l'exécute : planificateur sur graphe de visibilité, marche de l'atelier. Un siège se prend comme dans Unity
  (`SitDown`, `StandUp`) : elle contourne la chaise à 0,48 m, se place devant le siège à la distance que recule la capture
  `sit_down` (31 cm), s'assied avec elle, et se lève par `stand_up` ; la racine suit le rythme du clip. La chaise ne bouge
  que par les gestes du bureau.
- La caméra suit sa tête.

**La pièce** : un GLB généré par script Blender (`assets-src/blender/`). La lumière du jour suit l'heure réelle, avec du
bloom. Les mêmes scripts font la chambre d'Unity (`export_unity.py`) : après une retouche, relancer aussi
`blender -b --factory-startup --python assets-src/blender/run_final.py` (cuisson de l'occlusion, `room.glb`,
`room.blend`), sinon les deux clients divergent. Les hauteurs d'assise sont celles d'Unity (`ChambreSceneBuilder.Seats`) :
hanches à 0,15 m au-dessus du siège, moins ce qu'il s'enfonce.

**Le monde** (`world/`, ADR 0050) : le client web est une spectatrice de `/ws/world` (`mika.world/1`), jumelle du client
Unity.

- `protocol.g.ts` est généré du schéma du noyau par `backendv2/.venv/bin/python frontend/Web/tools/gen_world_protocol.py`
  (`--check` échoue s'il a vieilli ; `tests/protocol/test_world_wire.py` le vérifie).
- `WorldSession` (hello, ping 5 s, reprise, accusés, débits), `WorldMirror` et `WorldIndex` (l'état dans l'ordre du
  journal), `intentTimeline`, `actionMenu` (mêmes libellés qu'Unity) : purs, testés.
- `WorldStage` montre l'état des meubles (porte, croisée de la fenêtre et portes d'armoire, sorties par `RoomHinges`
  des maillages joints de `room.glb`), une silhouette pour un objet que la pièce ne dessine pas, ce qu'elle tient dans
  sa main, les autres personnages. Le corps de Mika, lui, suit toujours `inner_state` (lieu, occupation, sommeil).
- `WorldHud` : survol et menu d'actions au clic, refus du noyau, demandes de Mika, état de la connexion. Tant que le
  noyau ne fait entrer personne dans le monde (P4), agir et faire un geste sont refusés, et le refus se lit.

**Le reste**

- `audio/TTSService.ts` : Web Speech, une soupape par énoncé, sorties `played` ou `skipped`.
- `network/WebSocketClient.ts` : reprise exponentielle, ping toutes les 20 s, reconnexion après 50 s de silence, file de
  sortie rejouée ; un 4401 est terminal.
- `ui/chatSync.ts` : fusion du fil par curseur.
- `ui/bubbles.ts` : sa réponse en plusieurs bulles (une ligne vide les sépare), « Mika écrit… » entre deux.
- `ui/verdicts.ts` : pour une opératrice, 👍/👎 sous ses réponses et ce qu'elle aurait dû dire (ADR 0113).
- Le mode pro (ADR 0116), pour une opératrice : l'interrupteur « Pro » près du champ (`ChatOverlay`), la carte de
  travail en direct (`ui/toolActivity.ts`, pur : les trames `tool` fusionnées par message), la bulle pro en Markdown
  (`ui/proMarkdown.ts` : tout le HTML échappé d'abord, liens http(s) seulement, tableaux et citations compris),
  jamais lue à voix haute. Interrupteur allumé, le chat prend tout l'écran sur un fond qui cache la pièce et la vie
  intérieure se replie ; elle revient comme elle était en sortant du mode (`main.ts`, `#app.pro-mode`).
- Les fils de travail (ADR 0164, `ui/strands.ts`, pur) : en mode pro, le chat devient un client à plusieurs fils —
  la liste à gauche (un tiroir ☰ sur un téléphone), l'en-tête du fil montré (titre et petite description, ✎), le fil
  avec Mika caché. Chaque message part avec son fil (`chat.strand`) ; les commandes du champ : `/clear` (ou
  `/nouveau`) ouvre un fil neuf sans rien effacer, `/renommer`, `/description`, `/archiver`, `/desarchiver`, `/aide` ;
  `//` en tête échappe. Le cache garde les 50 derniers messages de chaque fil (`chatSync.trimThreads`) ; un fil qu'on
  ouvre sans ses messages se relit au serveur (`strand_history`).
- Les tests vitest sont dans des dossiers `__tests__`.

Les ADR cités sont dans `backendv2/docs/decisions.md`.
