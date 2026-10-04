# Mocap CMU — clips pour le corps de Mika

FBX produits par `frontend/Web/assets-src/blender/mocap_unity.py` (Blender 5.2, sans interface) à partir de la base de
capture de mouvement de Carnegie Mellon. Dossier hors de `Assets/` exprès : on importe
dans Unity ce dont on a besoin.

## Provenance et licence

- **Carnegie Mellon University Graphics Lab Motion Capture Database**,
  http://mocap.cs.cmu.edu — « The data used in this project was obtained from
  mocap.cs.cmu.edu. The database was created with funding from NSF EIA-0196217. »
  Libre d'usage, y compris commercial ; on ne revend pas la base telle quelle.
- Conversion BVH « MotionBuilder-friendly » : **cgspeed / Bruce Hahne**
  (cgspeed.com), copie `github.com/una-dinosauria/cmu-mocap`.
- À créditer : « Carnegie Mellon University Graphics Lab Motion Capture Database » et
  « BVH conversion by cgspeed / Bruce Hahne ».

## Clips

| Fichier | Prise | Images BVH (120 i/s) | Durée | Boucle | Catégorie |
|---|---|---|---|---|---|
| `walking.fbx` | 35_01 | 83–219 | 1.13 s | oui | locomotion |
| `walking_slow.fbx` | 142_13 | 3095–3287 | 1.60 s | oui | locomotion |
| `sit_down.fbx` | 143_18 | 44–232 | 1.57 s | non | transition |
| `sitting_idle.fbx` | 113_15 | 370–514 | 1.20 s | oui | idle |
| `stand_up.fbx` | 143_18 | 268–372 | 0.87 s | non | transition |
| `lie_down.fbx` | 113_08 | 40–708 | 5.57 s | non | transition |
| `lying_idle.fbx` | 113_08 | 708–1064 | 2.97 s | oui | idle |
| `get_up.fbx` | 113_08 | 1100–1792 | 5.77 s | non | transition |
| `picking_up.fbx` | 26_09 | 36–476 | 3.67 s | non | gesture |
| `stretch.fbx` | 113_23 | 36–916 | 7.33 s | non | gesture |
| `waiting.fbx` | 113_21 | 500–1064 | 4.70 s | oui | idle |

Détail (échelle, sol, placement, écarts de boucle avant fermeture, contrôles après
réimport) : `clips.json`.

## Choix des prises

Plages trouvées par analyse du mouvement (cinématique directe en numpy) : énergie de
mouvement (vitesse RMS des articulations lissée sur 0,1 s) pour les débuts et fins de
transition (debout immobile -> ... -> posture stable), hauteur des hanches, inclinaison
du buste, vitesse du bassin, frappes de talon ; boucles = paire d'images minimisant
l'écart de pose (articulations relatives aux hanches, cap retiré) + écart de vitesses +
écart de hauteur des hanches.

- `walking` — 35_01 (sujet 35, la série de marche la plus propre : sol plat, ligne
  droite) : cycle appui droit -> appui droit de 1,13 s, 1,18 m/s. Écarté : 07_01 et
  08_01 (sol de capture incliné : les hanches montent de 1 à 2 cm par cycle),
  113_25 (sujet féminin, 1,05 m/s, mais boucle moins bonne et même tic de tête que
  ci-dessous).
- `walking_slow` — 142_13 « Relaxed » (marche détendue, longues lignes droites, sol
  plat) : cycle appui gauche -> appui gauche de 1,60 s, 0,67 m/s (choisi parmi une
  trentaine de cycles de la prise : plus petit écart de pose et de rotations locales). Écarté : 07_04,
  08_04 (≈1 m/s, trop proches de la marche normale, sol incliné), 91_10 (0,55 m/s,
  cycle de 1,8 s, marche volontairement ralentie ; 105_10 en est un doublon), 37_01
  (bonne boucle mais 0,97 m/s).
- `sit_down` / `stand_up` — 143_18 « Sit Down And Get Up » : vraie chaise (assise,
  hanches à ≈0,51 m), départ et arrivée debout immobile. Écarté : 75_17 / 75_19
  (siège bas ≈0,27 m, buste penché à 70°, descente en 0,8 s), 13_xx et 141_17
  (tabouret haut), 86_09 (assise sur un plan haut), 113_15 pour l'assise (elle y
  arrive en marchant et en pivotant, sans temps debout immobile).
- `sitting_idle` — 113_15 (sujet féminin, chaise) : la seule tenue assise vraiment
  calme de la base (mains sur les cuisses) ; 1,2 s seulement. La tenue de 143_18 dure
  moins de 1 s et les mains s'y agitent ; 114_05 (longue, jambes croisées) bouge trop.
- `lie_down` / `lying_idle` / `get_up` — 113_08 « Lay down and get up » (sujet
  féminin) : chaîne complète dans une seule prise (debout -> à genoux -> assise au sol
  -> sur le dos, 4 s immobile, puis assise -> à genoux -> debout). Écarté : 77_18 (la
  prise commence déjà au sol, sur le côté, et se relève à quatre pattes ; pas de
  « s'allonger »), 77_16/17 (idem), 114_11 et 111_12 (sujets enceintes).
- `picking_up` — 26_09 « bend, pick up » : debout immobile, flexion des genoux et du
  buste, main droite à ≈15 cm du sol, retour debout. Écarté : 80_08 (penché jambes
  tendues, mains à mi-hauteur), 69_68 (commence en marchant), 115_06 (caisse à deux
  mains, 1,2 s), 111_17 (sujet enceinte, jambes tendues).
- `stretch` — 113_23 « Stretch and yawn » : bras montés lentement au-dessus de la
  tête, ouverts, redescendus. Écarté : 143_30 (court, mains à hauteur de tête), 141_13
  (sur la pointe des pieds en se déplaçant), 77_21 / 83_22 / 42_01 (échauffements
  sportifs enchaînés).
- `waiting` — 113_21 « Standing Still » : pieds fixes, le poids passe d'une jambe à
  l'autre (période ≈4,5 s) ; boucle de 4,7 s gauche -> droite -> gauche, choisie pour
  le plus petit écart de pose et de rotations locales entre ses bords. Écarté : 40_10 « wait
  for bus » (elle marche, se retourne, regarde sa montre), 141_20 (piétine, croise les
  jambes), 77_02.

## Corrections appliquées aux données

- **Tête du sujet 113** (sitting_idle, lie_down, lying_idle, get_up, stretch,
  waiting) : dans toutes ses prises, même en marchant, la tête reste tournée de 50 à
  70° vers sa droite par rapport au buste (elle regarde quelqu'un sur le côté ; elle
  revient dans l'axe quand elle lève les yeux vers ses mains). Ce lacet est retiré
  autour de l'axe vertical du buste, réparti sur Neck, Neck1 et Head ; inclinaisons et
  petits mouvements conservés. Constante par prise (médiane sur les plages des clips :
  les chaînes restent raccordées) sauf `stretch` (composante lente, gaussienne de
  0,5 s). Valeurs retirées : `head_yaw_recentered` dans `clips.json`.
- **Sol de 113_08** : sol brut de la capture (recaler sur les orteils debout,
  +2,6 cm, enfoncerait le bassin couché à 4 cm).

## Réserves

- `sitting_idle` vient d'un autre sujet que `sit_down` / `stand_up` : même position
  (posée sur la fin de `sit_down`), mais mains sur les cuisses au lieu de posées sur
  le siège ; un fondu enchaîné de 0,3 s s'impose. Boucle courte (1,2 s), presque
  immobile.
- Chaîne couchée : c'est un coucher **au sol** (à genoux, assise de côté, puis sur le
  dos), pas sur un lit ; le corps finit perpendiculaire à la direction de départ, tête
  vers +X Unity (la droite du personnage au départ), bassin ≈0,55 m à droite (voir
  `head_from_hips_end_unity_m`). Le poignet droit, en appui au sol, passe 5 à 10 cm
  sous le sol pendant quelques dixièmes de seconde (artefact de capture) dans
  `lie_down` et `get_up`.
- La pose T de cgspeed a les bras 8° sous l'horizontale (même valeur pour tous les
  sujets) ; « Enforce T-Pose » de Unity la redresse si besoin.
- Doigts : la base n'a qu'un os d'index et un pouce, bruités ; les écarts de boucle sur
  ces os (`seam_max_finger_deg`) sont grands et sans importance.
Planches : `previews/<nom>.png` (rangée du haut vue de côté, du bas vue de face ;
bleu = gauche, rouge = droite, jaune = avant de la tête et du buste, flèche verte =
avant Unity +Z).

## Conventions

- Un FBX par clip, armature seule nommée `CMU_Rig` (même hiérarchie et mêmes noms d'os
  partout), une prise (take) `CMU_Rig|<nom>` à **30 i/s**, première image = image 0.
- **Pose de repos = pose T** (image 0 du BVH de cgspeed), hanches à **0,95 m**, pointes
  de pied à 0, face à l'avant Unity (+Z). C'est elle que l'importeur humanoïde prend
  comme référence. Échelle par prise : 0,95 m / hauteur des hanches de la pose T.
- Réglages FBX : `axis_forward='-Z', axis_up='Y', bake_space_transform=True,
  apply_scale_options='FBX_SCALE_UNITS', add_leaf_bones=False, bake_anim=True`,
  sans simplification des courbes.
- Placement : chaque clip commence hanches à l'origine (x = z = 0) en regardant +Z,
  sauf les chaînes : `stand_up` reprend le placement de `sit_down` (même prise, même
  chaise), `sitting_idle` est posé sur la fin de `sit_down`, `lying_idle` et `get_up`
  reprennent le placement de `lie_down` (même prise) : ces enchaînements se raccordent
  en position absolue. Les marches avancent vers +Z (mouvement racine conservé).
- Sol : pointe des pieds en appui à y = 0 (estimée sur les phases debout de la prise).
- Boucles (`loop: true`) : dernière image = première image (écart d'origine réparti
  linéairement sur le clip, valeurs avant correction dans `clips.json`), avance de la
  marche conservée.

## Os de l'armature (noms CMU)

```
Hips
  LHipJoint
    LeftUpLeg
      LeftLeg
        LeftFoot
          LeftToeBase
  RHipJoint
    RightUpLeg
      RightLeg
        RightFoot
          RightToeBase
  LowerBack
    Spine
      Spine1
        Neck
          Neck1
            Head
        LeftShoulder
          LeftArm
            LeftForeArm
              LeftHand
                LeftFingerBase
                  LeftHandIndex1
                LThumb
        RightShoulder
          RightArm
            RightForeArm
              RightHand
                RightFingerBase
                  RightHandIndex1
                RThumb
```

Correspondance humanoïde Unity suggérée (tient compte des articulations à décalage nul
du BVH : LowerBack est au même point que Hips, Neck, LeftShoulder et RightShoulder au
même point que Spine1, LHipJoint/RHipJoint partent de Hips) :

| Unity | Os CMU |
|---|---|
| Hips | Hips |
| Left/Right Upper Leg | LeftUpLeg / RightUpLeg |
| Left/Right Lower Leg | LeftLeg / RightLeg |
| Left/Right Foot | LeftFoot / RightFoot |
| Left/Right Toes | LeftToeBase / RightToeBase |
| Spine | Spine |
| Chest | Spine1 |
| Upper Chest | — |
| Neck | Neck1 |
| Head | Head |
| Left/Right Shoulder | LeftShoulder / RightShoulder (facultatif : il part du même point que Chest) |
| Left/Right Upper Arm | LeftArm / RightArm |
| Left/Right Lower Arm | LeftForeArm / RightForeArm |
| Left/Right Hand | LeftHand / RightHand |

Non mappés : LHipJoint, RHipJoint, LowerBack, Neck (os intermédiaires) ; LeftFingerBase,
LeftHandIndex1, LThumb et leurs symétriques (doigts sommaires et bruités de la base).

## Relancer

```
blender -b --factory-startup --python frontend/Web/assets-src/blender/mocap_unity.py -- \
    --bvh-dir ~/.cache/mika-mocap/cmu --out frontend/Unity/ArtSource/mocap
```

`--only walking,sit_down` limite aux clips nommés (les clips dont ils dépendent pour le
placement sont relus sans être exportés) ; `--no-previews` saute réimport et planches ;
les BVH manquants sont téléchargés dans `--bvh-dir` (sinon `--no-download`). La table
`CLIPS` en tête du script fixe prise, plage, boucle, placement et description.

## Import dans Unity (conseils)

Rig → Animation Type **Humanoid**, Avatar Definition **Create From This Model** (la
pose de repos est déjà la pose T). Animation → Loop Time pour les clips `loop: true`
(la pose de bouclage est déjà fermée) ; pour les marches, Root Transform Rotation /
Position Y « Bake Into Pose », Position XZ selon que le contrôleur pilote le
déplacement ou non.
