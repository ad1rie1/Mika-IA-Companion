# Assets : l'art de Mika

Les sources graphiques des clients, réunies ici par l'ADR 0319 : son modèle, ses mouvements, les scripts Blender
qui en tirent ses portraits, et les sources de la chambre en 3D d'avant. Rien ici n'est servi tel quel : chaque
client prend ce qu'il lui faut, à l'endroit que dit le tableau.

## Ce qu'il contient, et qui le lit

| Dossier | Contenu | Lu par |
|---|---|---|
| `models/` | `default.vrm` (la VRM achetée, non versionnée), `mika-libre.vrm` (le modèle libre, ADR 0252), `room.glb` | le client web en développement (`/ext/models/`, `frontend/Web/tools/extAssets.ts`), le mandataire en service (`backend/deploy/README.md`), `frontend/Android/tools/vrm_mobile.py` |
| `atelier/` | l'atelier d'animation : `mika_rig.blend` (non versionné), `motions/*.json.gz` (versionnés), les relevés `*_layout.json` et `desk_plan.json`, `held/`, `previews/` (non versionné) | `blender/atelier_*.py`, `blender/portraits.py`, `blender/portrait_loops.py` |
| `animations/` | les clips sources (Mixamo), `manifest.json`, et `atelier/`, un lien vers `../atelier/motions/` | `blender/atelier_mika.py`, `blender/atelier_audit.py` |
| `mocap/` | des clips de la base CMU, en FBX (provenance et licence dans son `README.md`) | `blender/atelier_mika.py`, `blender/atelier_audit.py` |
| `objects/`, `textures/`, `room.blend` | la chambre : un `.blend` par objet, ses textures, la scène entière | `blender/build_*.py`, `blender/run_final.py` |
| `blender/` | les scripts (Blender 5.x, module VRM « blender_org.vrm ») | |

## Les portraits

`blender/portraits.py` rend une image par émotion, que l'app Android et le client web affichent (dans
`frontend/Android/app/src/main/assets/avatar/`, non versionné ; le client web les lit par `/ext/avatar/`). Le corps
vient d'un mouvement de `atelier/motions/`, figé sur l'image choisie :

```bash
blender -b frontend/Assets/atelier/mika_rig.blend --python frontend/Assets/blender/portraits.py -- \
    [--only happy,sad] [--scale 50] [--out dossier] [--sheet idle_sad,gesture_think]
```

`blender/portrait_loops.py` fait les clips du labo de l'avatar (`frontend/Android/avatar-lab/out/`).

## La licence du modèle

`default.vrm` et tout ce qui le contient (`atelier/*.blend`, `atelier/previews/`, les portraits rendus, la VRM
préparée pour Android) sont sous la licence de l'acheteur : jamais versionnés (`.gitignore` à la racine et
`atelier/.gitignore`). Seuls les mouvements exportés (les os, sans maillage) le sont.

## Ce qui n'a plus de destination

Depuis l'ADR 0319, il n'y a plus de client Unity ni de client web en 3D. Ces scripts restent, mais n'ont plus de
lecteur :

- `blender/export_unity.py` et `blender/duvet_states.py` écrivent la chambre et la couette en FBX pour Unity ;
  `blender/atelier_decor.py` lit encore la couette et le plaid de cet export (`FBX_OBJECTS`), qui ne sont plus dans
  l'arbre ;
- `blender/run_final.py` reconstruit `models/room.glb`, que plus aucun client ne charge.

Le dernier état des deux clients est au tag git `avant-menage`.

## Reconstruire la chambre

Toute la chambre est écrite par les scripts de `blender/` (Blender 5.2, console Python) : une retouche est une
modification de script, puis une exécution.

```python
BLENDER_SCRIPTS_DIR = "/chemin/vers/frontend/Assets/blender"
SAMPLES = 128                      # échantillons du calcul d'occlusion
exec(open(BLENDER_SCRIPTS_DIR + "/run_final.py").read())
```

`run_final.py` reconstruit chaque objet (`build_all.py`), applique les modificateurs, fait la seconde carte UV,
calcule l'occlusion ambiante avec Cycles **sur le processeur** (le calcul CUDA écrit une image noire sur cette
machine) dans `textures/room_ao.png`, exporte `models/room.glb` et enregistre `room.blend`. `gen_textures.py`
régénère les textures (il attend les téléchargements Poly Haven listés plus bas, dans
`blender/ph/<nom>_diff_1k.jpg`). Les coordonnées des scripts sont celles de three.js (`V(X, Y, Z)` → Blender
`(X, -Z, Y)`).

## Licences des textures

Tout le matériel tiers est **CC0** (domaine public), de [Poly Haven](https://polyhaven.com) :

| Texture | Source Poly Haven | Usage |
| --- | --- | --- |
| `floor_wood.jpg` | [wood_floor](https://polyhaven.com/a/wood_floor) | le parquet |
| `wood_grain.jpg` | [oak_veneer_01](https://polyhaven.com/a/oak_veneer_01) | tout le bois des meubles (teinté par pièce) |
| `fabric_linen.jpg` | [rough_linen](https://polyhaven.com/a/rough_linen) | draps, oreillers, chaise, paniers (désaturé) |
| `fabric_fleece.jpg` | [knitted_fleece](https://polyhaven.com/a/knitted_fleece) | sweat, peluche, chaussons, trame de la couette (désaturé) |
| `fabric_velvet.jpg` | [velour_velvet](https://polyhaven.com/a/velour_velvet) | rideaux, coussins (désaturé) |
| `fabric_plaid.jpg` | [wool_boucle](https://polyhaven.com/a/wool_boucle) | le plaid |

Le reste (plâtre des murs, liège, tapis, motif de la couette, affiches, tirages, photos, écran, carnet) est dessiné
par `gen_textures.py` ; la géométrie est modelée par les scripts. Aucun autre élément extérieur n'est utilisé.
