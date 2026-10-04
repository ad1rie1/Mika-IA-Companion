# Mika.Avatar — le visage

Le visage de Mika dans le client Unity : émotions, physiologie, clignements, micro-expressions,
synchronisation labiale, sommeil, énergie et regard des yeux. C'est le portage de la couche visage du
client web (`frontend/Web/src/vtuber/`, `frontend/Web/src/audio/`) ; le `CLAUDE.md` racine (sections « Face
layers », « Humanisation pass », « Lip-sync follows the voice ») décrit le comportement visé.

- `Core/` — la logique, pure (aucune dépendance au modèle chargé), testée en mode édition
  (`Assets/Mika/Tests/EditMode/Avatar/`, assembly `Mika.Avatar.Tests`).
- `Rig/FaceRig.cs` — ce qui touche UniVRM : copies nettoyées des groupes, morphs bruts, noms → clés.
- `MikaFace.cs` — le composant, sur la racine de l'avatar à côté du `Vrm10Instance`.
- Import : menu **Mika/Avatar/Importer l'avatar du frontend** (`Assets/Mika/Editor/Avatar/AvatarImporter.cs`)
  → `Assets/Mika/Art/Avatars/Mika.prefab`.

## API de `MikaFace`

```csharp
void  ShowEmotion(string emotion, float intensity, IReadOnlyList<KeyValuePair<string, float>> blend, bool ambient);
float Speak(string text, float rate = 1f);   // durée estimée (s) ; 0 si rien à dire
void  SeekSpeech(int charIndex);              // recale sur une position de lecture (index dans `text`)
void  StopSpeaking();
event Action SpeechEnded;
bool  IsSpeaking { get; }
void  SetSleepPhase(string phase);            // awake | light_sleep | rem | deep_sleep (inconnu → awake)
void  SetEnergy(float energy01);
void  LookAt(Transform target);               // les yeux ; la tête appartient à l'IK de Mecanim
void  LookAt(Vector3? point);
event Action<string> ProsodicCue;             // "sigh" | "laugh" | "breath"
```

En plus, facultatif : `event Action<SpeechBeat> BeatReached` (accent, insistance, question… au bon mot,
pour que le corps hoche la tête), `SetReplyPending(bool)` (regard « je réfléchis »), `NoteUserTyping()`
(regard d'écoute), `InnerVoice` (murmure à elle-même), `Walking`, `ExternalVoice`, et en lecture
`Attention`, `EyeAngles`, `SpeechCursor`, `SpeechEmphasis`, `LipSyncMode`, `RichEmotionCount`,
`ExpressionNames`, `IsReady`.

Règles à connaître :

- `blend` arrive trié par poids décroissant (comme la trame du noyau). La secondaire n'est montrée que si
  son poids atteint 30 % de celui de la principale, à 45 % de ce poids.
- `ambient: true` pendant qu'elle parle : la dérive est **retenue** (la plus récente gagne) et appliquée
  quand la parole se termine — la balise `[EMOTION:]` est la vérité du tour (règle du `SpeechPresenter`
  web). Soupape : 60 s.
- Émotion inconnue : « neutral » pour une réplique, ignorée pour une dérive.
- `Speak` pendant une parole la remplace sans `SpeechEnded` intermédiaire. `SpeechEnded` est émis à la fin
  de l'estimation (ou de la voix) et par `StopSpeaking`.
- `LookAt(null)` est ambigu en C# : écrire `LookAt((Transform)null)` ou `LookAt((Vector3?)null)` (= personne,
  regard devant elle). Tant qu'aucun `LookAt` n'a été appelé, elle regarde `Camera.main` (désactivable dans
  l'inspecteur).
- Les repères `[PAUSE:ms]`, `[SIGH]`, `[LAUGH]`, `[BREATH]` ne sont pas articulés : ils deviennent des
  silences bouche fermée (pause 50–3000 ms, défaut 500 ; soupir 600, rire 900, souffle 350 ms). `[PAUSE]`
  n'émet pas de `ProsodicCue`.
- **Une vraie voix** : cocher `ExternalVoice`, appeler `SeekSpeech` à chaque position rapportée (début
  d'énoncé, frontières de mot), puis `StopSpeaking` à la fin. L'estimation court entre deux recalages ; sa
  fin ne coupe plus la parole.

Le composant **possède le visage** : il écrit chaque image les poids de toutes ses expressions dans
`Vrm10RuntimeExpression` (ordre d'exécution 10500, avant le `Vrm10Instance` à 11000 qui les applique), et
remet à zéro ce qu'aucune couche ne demande plus. Les yeux passent par `Vrm10RuntimeLookAt` en lacet/tangage
(`LookAtTargetType = YawPitchValue`) ; la courbe de l'auteur est inversée pour que l'œil tourne réellement de
l'angle voulu, et reste la borne physique du modèle.

## Ce qui est porté du web

| Couche | Source web | Ici |
|---|---|---|
| 29 émotions → groupes du modèle (Perula) ou presets, secondaire du mélange, montée par émotion, descente ×0,6, pulsation 5 % | `EmotionController.ts` | `Core/EmotionFace.cs` |
| Nettoyage des groupes : symboles manga et `eyeLook*` retirés (`clean:<Groupe>`), morphs isolés (`raw:<morph>`) | `faceRig.ts` | `Rig/FaceRig.cs`, `Core/FaceNames.cs` |
| Rougeur (1,6 s / 9 s), larmes par charge (jamais sur une tristesse légère), pupilles | `FacePhysiology.ts` | `Core/FacePhysiology.cs` |
| Clignements rapide / double / doux, cadence par émotion, fatigue, parole, clignement porté par une saccade ; yeux fermés en dormant, frémissement du paradoxal | `BlinkController.ts` | `Core/BlinkModel.cs` |
| Micro-dérive ARKit asymétrique, accents par émotion, sourcils de la parole | `FaceIdleController.ts` | `Core/FaceIdleModel.cs` |
| Graphèmes français → phonèmes → 15 visèmes (digraphes, nasales, muettes, élisions, nombres) | `frenchVisemes.ts` | `Core/FrenchVisemes.cs` |
| Coarticulation (anticipation ≤ 70 ms, attaque des fermetures, relais), plafond d'ouverture, articulation selon émotion/fatigue, visèmes `vrc.v_*` ou repli `aa ih ou ee oh` | `LipSyncController.ts`, `affect.ts` | `Core/LipSyncModel.cs` |
| Cadence selon le débit, repères prosodiques, recalage sur un index de caractère | `cadence.ts`, `TTSService.ts` | `Core/SpeechPlan.cs` |
| Temps de la phrase (accents, insistance, question) → sourcils | `speechBeats.ts`, `SpeechBodyOverlay.ts` | `Core/SpeechBeats.cs` |
| Attention conversationnelle (contact, évitements par émotion, regard de planification, réflexion, murmure, rêverie) et yeux (biais d'émotion, saccades en sauts, portée 17°/12,6°, réflexe vestibulo-oculaire) | `attention.ts`, `GazeController.ts` | `Core/Attention.cs` |
| Paupières lourdes (`Sleepy` nettoyé ≤ 0,32) sous 0,55 d'énergie | `EmotionController.setEnergy` | `EmotionFace.SetEnergy` |
| Dérive d'humeur retenue pendant la parole | `SpeechPresenter.ts` | `MikaFace.ShowEmotion` |

## Ce qui n'est pas porté, et pourquoi

- **La voix** : pas de synthèse vocale sous Linux dans Unity. La bouche suit l'estimation texte (celle du
  web entre deux recalages) ; `SeekSpeech` / `ExternalVoice` sont la prise pour une voix venue du noyau. Les
  sons synthétiques des repères (soupir, rire) ne sont pas joués : seul l'événement `ProsodicCue` part.
- **La tête et le corps** : hochements, inclinaison de question, tour de tête vers l'interlocuteur,
  respiration, gestes — c'est l'IK de Mecanim et la couche d'animation. Le visage fournit ce qu'il faut pour
  les piloter (`BeatReached`, `Attention`, `EyeAngles`, `SpeechEmphasis`). Sans tête qui tourne, les
  regards de rêverie (porte, fenêtre…) s'arrêtent au coin de l'œil.
- **Les liaisons de couleur de matériau** des groupes de l'auteur ne passent pas dans les copies nettoyées
  (le web ne recopie lui aussi que les liaisons de morphs). Un groupe qui ne rougirait que par matériau
  perdrait cette rougeur — la physiologie la redonne par le morph `FaceRed`.
- **La portée des yeux** : le web écrit les os des yeux directement (jusqu'à 17° / 12,6°). Ici ils passent par
  le LookAt d'UniVRM, et la courbe déclarée par l'auteur du modèle (90° d'entrée → 10° d'œil) borne l'œil à
  10° : les regards sont un peu plus courts que sur le web, mais restent dans ce que le modèle accepte.
- **Le délai de réveil** (1,3 s de silence avant la première réplique au sortir du sommeil) appartient à
  l'appelant qui décide quand appeler `Speak`.
