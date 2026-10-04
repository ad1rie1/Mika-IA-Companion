# Chambre de Mika — export Unity

Généré par `frontend/assets-src/blender/export_unity.py` à partir des scripts de
`frontend/assets-src/blender/` (les mêmes que le `room.glb` du client web). **Ne pas
éditer à la main** : relancer l'export.

```sh
blender -b --factory-startup --python frontend/assets-src/blender/export_unity.py -- \
    --out UnityFrontend/Mika/Assets/Mika/Art/Room
```

(`--dry-run` construit et classe sans rien écrire.) La table de regroupement
(objet logique → pièces Blender, catégorie, clé d'asset, pivots des enfants) est en
tête du script.

## Contenu

- `Models/<catégorie>/<id>.fbx` — un FBX par objet logique, ramené à l'origine.
- `room_layout.json` (`mika.room-layout/1`) — position du pivot (`pos`), lacet
  (`yaw`), boîte locale (`size`), matériaux, enfants (pivot relatif + `motion`),
  surfaces de pose (`height`, `min`, `max` relatifs au pivot), ancres de lumière.
- `materials.json` — couleur de base (linéaire + hex sRGB ; avec une texture c'est la
  teinte qui la multiplie, comme `_BaseColor` × `_BaseMap` en URP), rugosité,
  métal, émission (couleur + force), alpha, double face, textures. Pas de carte
  normale ni de rugosité dans les sources ; l'échelle des textures est cuite dans les
  UV (pas de nœud Mapping), d'où `uv_scale: null`.
- `Textures/` — les images utilisées, copiées de `frontend/assets-src/textures/`.

## Conventions

- **Espace de la pièce** = coordonnées three.js : x, z au sol, y vers le haut, en
  mètres ; `facing`/`yaw` φ : l'avant vaut (sin φ, cos φ), 0 regarde vers +z.
- **Pivot** = centre bas de la boîte englobante (axes du monde), sauf : la chaise
  (`desk_chair`, origine au sol sous l'assise, lacet `yaw` = 0,3 porté par le nœud) ;
  les battants sur leur charnière (`Door_Leaf`, `Window_Sash`, `Wardrobe_DoorL/R`) ;
  les tiroirs au milieu du dos de leur façade (contre le caisson) ; les rideaux en
  haut, côté mur ; les aiguilles au centre du cadran.
- **FBX** : `axis_forward='-Z', axis_up='Y', bake_space_transform=True,
  apply_scale_options='FBX_SCALE_UNITS'`. Les sommets du FBX sont les coordonnées de
  la pièce relatives au pivot, sans rotation sur les nœuds. L'importeur FBX de Unity
  inverse X : **unity = (-x, y, z)**, et un lacet φ devient
  `Quaternion.Euler(0, -φ en degrés, 0)`. Les sens de rotation s'inversent de même :
  une aiguille réglée en three.js par `rotation.z = -2π·h/12` se règle en Unity par
  `localEulerAngles.z = +360·h/12`.
- `motion` (enfants) est indicatif, en espace de la pièce : `hinge` (axe y,
  `opens_toward` = direction du bord libre), `slide` (`dir` = sortie du tiroir),
  `rotate`, `scale`, `toggle`. Les tiroirs n'ont que leur façade : les caissons sont
  pleins.


## Objets (84, 103080 triangles)

| id | catégorie | asset | triangles | enfants |
| --- | --- | --- | ---: | --- |
| `room_floor` | architecture | `architecture/room_floor` | 2 |  |
| `room_walls` | architecture | `architecture/room_walls` | 572 |  |
| `room_ceiling` | architecture | `architecture/room_ceiling` | 2 |  |
| `window_sky` | architecture | `architecture/window_sky` | 2 |  |
| `writing_desk` | furniture | `furniture/desk` | 1684 | `Desk_Drawer0`, `Desk_Drawer1`, `Desk_Drawer2` |
| `desk_chair` | furniture | `furniture/desk_chair` | 9544 |  |
| `bed_frame` | furniture | `furniture/bed` | 21332 |  |
| `nightstand` | furniture | `furniture/nightstand` | 1036 | `Bedside_Drawer` |
| `wardrobe` | furniture | `furniture/wardrobe` | 1244 | `Wardrobe_DoorR`, `Wardrobe_DoorL` |
| `shelves` | furniture | `furniture/bookshelf` | 920 |  |
| `dresser` | furniture | `furniture/dresser` | 2144 | `Dresser_Drawer00`, `Dresser_Drawer01`, `Dresser_Drawer10`, `Dresser_Drawer11`, `Dresser_Drawer20`, `Dresser_Drawer21` |
| `trinket_shelf` | furniture | `furniture/trinket_shelf` | 364 |  |
| `window_pane` | fixture | `fixtures/window` | 1268 | `Window_Sash` |
| `bedroom_door` | fixture | `fixtures/door` | 1036 | `Door_Leaf` |
| `light_switch` | fixture | `fixtures/light_switch` | 216 |  |
| `curtains` | fixture | `fixtures/curtains` | 7564 | `Curtain_L`, `Curtain_R` |
| `ceiling_lamp` | fixture | `fixtures/ceiling_lamp` | 1434 |  |
| `monitor` | fixture | `fixtures/monitor` | 674 | `Monitor_Screen` |
| `snake_plant` | prop | `props/snake_plant` | 1288 |  |
| `ficus` | prop | `props/ficus` | 3156 |  |
| `pothos` | prop | `props/pothos` | 3512 |  |
| `cactus_windowsill` | prop | `props/cactus_windowsill` | 388 |  |
| `succulent_windowsill` | prop | `props/succulent_windowsill` | 484 |  |
| `keyboard` | prop | `props/keyboard` | 3100 |  |
| `mouse` | prop | `props/mouse` | 288 |  |
| `desk_mat` | prop | `props/desk_mat` | 44 |  |
| `mug` | prop | `props/mug` | 684 |  |
| `notebook` | prop | `props/notebook` | 56 |  |
| `pen` | prop | `props/pen` | 40 |  |
| `pen_cup` | prop | `props/pen_cup` | 304 |  |
| `book_desk_1` | prop | `props/book_desk_1` | 56 |  |
| `book_desk_2` | prop | `props/book_desk_2` | 56 |  |
| `succulent_desk` | prop | `props/succulent_desk` | 940 |  |
| `waste_bin` | prop | `props/waste_bin` | 384 |  |
| `paper_ball` | prop | `props/paper_ball` | 80 |  |
| `desk_lamp` | prop | `props/desk_lamp` | 2322 |  |
| `plushie` | prop | `props/plushie` | 2764 |  |
| `slippers` | prop | `props/slippers` | 1544 |  |
| `bedside_lamp` | prop | `props/bedside_lamp` | 864 |  |
| `alarm_clock` | prop | `props/alarm_clock` | 568 |  |
| `book_nightstand_1` | prop | `props/book_nightstand_1` | 44 |  |
| `book_nightstand_2` | prop | `props/book_nightstand_2` | 44 |  |
| `shelf_basket_1` | prop | `props/shelf_basket_1` | 40 |  |
| `shelf_basket_2` | prop | `props/shelf_basket_2` | 40 |  |
| `vase_bookshelf` | prop | `props/vase_bookshelf` | 288 |  |
| `bunny_figurine` | prop | `props/bunny_figurine` | 736 |  |
| `moon_lamp` | prop | `props/moon_lamp` | 960 |  |
| `photo_frame_bookshelf` | prop | `props/photo_frame_bookshelf` | 110 |  |
| `cactus_bookshelf` | prop | `props/cactus_bookshelf` | 388 |  |
| `storage_box_bookshelf` | prop | `props/storage_box_bookshelf` | 216 |  |
| `star_lamp` | prop | `props/star_lamp` | 280 |  |
| `cactus_trinket_shelf` | prop | `props/cactus_trinket_shelf` | 408 |  |
| `cat_figurine` | prop | `props/cat_figurine` | 652 |  |
| `photo_frame_trinket_shelf` | prop | `props/photo_frame_trinket_shelf` | 110 |  |
| `candle` | prop | `props/candle` | 304 | `Candle_Flame` |
| `speaker` | prop | `props/speaker` | 300 |  |
| `jewelry_box` | prop | `props/jewelry_box` | 216 |  |
| `perfume_bottle` | prop | `props/perfume_bottle` | 176 |  |
| `dried_flowers` | prop | `props/dried_flowers` | 1006 |  |
| `floor_cushion` | prop | `props/floor_cushion` | 1408 |  |
| `book_stack_floor` | prop | `props/book_stack_floor` | 168 |  |
| `open_book` | prop | `props/open_book` | 56 |  |
| `laundry_basket` | prop | `props/laundry_basket` | 4608 |  |
| `tote_bag` | prop | `props/tote_bag` | 1496 |  |
| `scarf` | prop | `props/scarf` | 176 |  |
| `wardrobe_box_a` | prop | `props/wardrobe_box_a` | 108 |  |
| `wardrobe_box_b` | prop | `props/wardrobe_box_b` | 216 |  |
| `desk_cables` | decor | `decor/desk_cables` | 196 |  |
| `pinboard` | decor | `decor/pinboard` | 1072 |  |
| `print_cat` | decor | `decor/print_cat` | 434 |  |
| `print_flower` | decor | `decor/print_flower` | 434 |  |
| `poster_moon` | decor | `decor/poster_moon` | 434 |  |
| `poster_peaks` | decor | `decor/poster_peaks` | 434 |  |
| `poster_city` | decor | `decor/poster_city` | 434 |  |
| `mirror` | decor | `decor/mirror` | 1152 |  |
| `neon_sign` | decor | `decor/neon_sign` | 1180 |  |
| `wall_clock` | decor | `decor/wall_clock` | 984 | `Clock_HourHand`, `Clock_MinuteHand` |
| `wall_hooks` | decor | `decor/wall_hooks` | 756 |  |
| `rug` | decor | `decor/rug` | 1200 |  |
| `books_shelf_0` | decor | `decor/books_shelf_0` | 224 |  |
| `books_shelf_1` | decor | `decor/books_shelf_1` | 1524 |  |
| `books_shelf_2` | decor | `decor/books_shelf_2` | 1656 |  |
| `books_shelf_3` | decor | `decor/books_shelf_3` | 1508 |  |
| `books_shelf_4` | decor | `decor/books_shelf_4` | 944 |  |

## Vérifié

- La reconstruction reproduit `room.blend` : même nombre de triangles (103 080), mêmes
  boîtes pour le lit (tissus simulés compris) et la chaise ; le script refuse d'écrire
  si une pièce n'est classée nulle part ou si des triangles se perdent.
- Chaque FBX se réimporte dans Blender (importeur Python et importeur ufbx) sans
  erreur, avec ses enfants nommés et parentés, ses matériaux, sa taille `size`, son
  pivot au centre bas (sauf chaise) et les pivots d'enfants du layout.
- Orientation, sur un marqueur (sommets en (1,0,0), (0,2,0), (0,0,3) de la pièce,
  enfant en (0,5 ; 0,25 ; -0,75)) relu dans le FBX brut : les sommets et la
  translation locale de l'enfant sont écrits **tels quels** ; nœuds racines sans
  rotation ni échelle ; `GlobalSettings` : UpAxis = Y (+1), FrontAxis = Z (+1),
  CoordAxis = X (+1), UnitScaleFactor = 100 (1 unité = 1 m).
- Les boîtes des objets restent dans la pièce (à 0,2 m près), sauf `window_sky`.
- Les 10 objets de `backendv2/src/mika/faculties/world/chambre.json` ont une entrée de
  même `id`, et aucun lieu de ce monde ne tombe dans l'empreinte d'un meuble.

## À vérifier côté Unity

Constaté : Unity 6.6 importe les 84 FBX et les 18 textures sans erreur ni
avertissement (Editor.log). Pas encore vérifié dans l'éditeur :

- Que l'importeur de Unity 6.6 inverse bien X (attendu : `Desk_Drawer0` du bureau en
  `localPosition` (-0,72 ; 0,167 ; 0,32) quand le layout dit (0,72 ; 0,167 ; 0,32)),
  avec « Convert Units » actif (échelle 1) et sans rotation de -90° sur les racines.
- Le sens d'ouverture des battants et de rotation des aiguilles après le miroir X.
- Les matériaux : l'import FBX ne transporte ni la teinte qui multiplie les textures
  ni l'émission telle quelle ; `materials.json` fait foi.

## Remarques

- `snake_plant` et `ficus` ont chacun leur asset (`props/snake_plant`, `props/ficus`),
  alors que le monde par défaut (`chambre.json`) les rattache tous deux à
  l'archétype `potted_plant` → `props/potted_plant` : il faut soit une surcharge
  d'asset par objet côté monde, soit une résolution par `id` côté Unity.
- La fenêtre n'a pas de vrai vantail dans les sources : `Window_Sash` est la croisée
  (meneaux), sans vitrage ni cadre ouvrant.
- `window_sky` est la carte de ciel émissive placée derrière la fenêtre (le web la
  remplace par un shader de ciel) ; elle sort volontairement de la pièce.
- Le lacet `yaw` n'est non nul que pour `desk_chair`.
