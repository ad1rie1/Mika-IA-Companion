# Animations Mixamo — pack de départ

Le système d'animation charge les clips listés dans [manifest.json](manifest.json)
et les retarget à la volée sur le VRM (bones humanoïdes normalisés).
**Aucun clip n'est fourni dans le repo** : Mixamo exige un compte Adobe, il
faut les télécharger à la main (5 minutes). Un clip manquant n'est jamais
bloquant — la pool se réduit, un warn console liste ce qui manque.

## Réglages d'export Mixamo (IDENTIQUES pour tous les clips)

| Réglage | Valeur |
|---|---|
| Format | **FBX Binary (.fbx)** |
| Skin | **Without Skin** (squelette seul, ~0.5–2 MB au lieu de 5–15 MB) |
| Frames per Second | **30** |
| Keyframe Reduction | **none** |
| In Place | coché **uniquement** pour les clips de locomotion (v2) |

Après téléchargement, **renomme le fichier** exactement comme dans la
colonne « Fichier » et dépose-le dans le bon sous-dossier.

## Le pack (~19 clips)

Recherche le nom de la colonne « Recherche Mixamo » ; si Mixamo propose
plusieurs variantes, prends celle qui te plaît — le manifest ne dépend
que du nom de fichier.

| # | Recherche Mixamo | Fichier | Usage |
|---|---|---|---|
| 1 | Breathing Idle | `idle/idle_breathing.fbx` | idle par défaut + sommeil (ralenti) |
| 2 | Happy Idle | `idle/idle_happy.fbx` | variation d'idle joyeuse |
| 3 | Bored | `idle/idle_bored.fbx` | posture « s'ennuie » (émotion bored) |
| 4 | Sad Idle | `idle/idle_sad.fbx` | posture triste (sad/lonely/melancholic) |
| 5 | Nervously Look Around | `idle/idle_nervous.fbx` | posture anxieuse (anxious) |
| 6 | Talking | `talk/talk_main.fbx` | gestuelle de conversation |
| 7 | Standing Arguing | `talk/talk_heated.fbx` | variante animée de conversation |
| 8 | Waving | `gesture/gesture_wave.fbx` | salut (manuel/debug, futur greeting) |
| 9 | Laughing | `gesture/gesture_laugh.fbx` | amused/playful + token [LAUGH] |
| 10 | Thinking | `gesture/gesture_think.fbx` | thinking/confused (tenu ~4 s) |
| 11 | Surprised | `gesture/gesture_surprised.fbx` | surprised |
| 12 | Bashful | `gesture/gesture_bashful.fbx` | embarrassed |
| 13 | Angry Gesture | `gesture/gesture_angry.fbx` | angry |
| 14 | Head Nod Yes | `gesture/gesture_nod.fbx` | grateful (acquiescement) |
| 15 | Shaking Head No | `gesture/gesture_headshake.fbx` | frustrated/disgusted |
| 16 | Excited | `gesture/gesture_excited.fbx` | excited/happy fort |
| 17 | Relieved Sigh | `gesture/gesture_sigh.fbx` | relieved + token [SIGH] |
| 18 | Yawn | `gesture/gesture_yawn.fbx` | transition sommeil (futur) |
| 19 | Stretching | `gesture/gesture_stretch.fbx` | réveil / pause (manuel) |

### Réservé v2 (locomotion — ne pas télécharger maintenant)

Walking, Left Turn, Right Turn (**In Place** coché), Sleeping Idle
(couchée — quand elle pourra rejoindre le lit). Dossier `locomotion/`.

## Astuce : animations ajustées à Perula

Par défaut Mixamo anime son mannequin standard et le retarget adapte les
rotations — ça marche bien. Pour des clips encore mieux ajustés à ses
proportions (moins de clipping poitrine/jupe), uploade une fois
`PerulaVRM_v1.0.6.2.zip → PerulaVRM v1.0.6.2/FBX/Perula.fbx` comme
personnage sur Mixamo, puis télécharge les clips depuis ce personnage.

## manifest.json — champs utiles

- `category`: `idle` | `talk` | `gesture` | `sleep` | `locomotion`
- `weight`: probabilité de tirage dans la rotation (**0 = jamais tiré
  spontanément** — les postures émotionnelles idle_sad/idle_bored/
  idle_nervous ne s'activent que via l'émotion)
- `hold`: [min, max] secondes avant de changer de variation
- `loop`: `true` sur un geste = tenu quelques secondes puis retour
  (ex. gesture_think) au lieu d'une lecture unique
- `hands`: formes de doigts `[gauche, droite]` (relaxed/open/tucked/loose/clasp)
- `fadeIn`/`fadeOut`: durées de crossfade du geste
- `stripRootXZ`: `true` pour forcer un clip de locomotion « in place »

## Validation (après dépôt des fichiers)

Recharge l'app puis : **Alt+M** fait défiler chaque clip sur le modèle,
**Alt+J** affiche le rapport de retarget en console, **Alt+K** affiche le
squelette, **Alt+E/G/S/T** forcent émotions/gestes/sommeil/talking,
**Alt+D** ouvre le panneau debug. Checklist : face caméra (dos = flip
VRM0 manquant), pas de miroir gauche/droite, pieds au sol sans glisse,
bras sans twist 90°, doigts/yeux toujours animés, crossfades fluides.
