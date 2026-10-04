# Export de la chambre de Mika pour Unity : un FBX par objet logique + une
# description (room_layout.json, materials.json, Textures/, README.md).
#
#   blender -b --factory-startup --python frontend/Web/assets-src/blender/export_unity.py -- \
#       --out frontend/Unity/Mika/Assets/Mika/Art/Room
#
# Options après « -- » : --out <dossier> (défaut : le chemin ci-dessus, depuis la
# racine du dépôt), --dry-run (construit et classe, n'écrit rien), --blend-dir
# <dossier> (écrit aussi un .blend par objet logique, <catégorie>/<id>.blend — la
# source Blender de chaque objet, que l'atelier d'animation ouvre pour vérifier une
# animation contre le vrai meuble ; défaut des .blend : frontend/Web/assets-src/objects),
# --no-unity (n'écrit ni FBX ni JSON : seulement les .blend).
#
# Le pipeline web (room.blend, room.glb, run_final.py) n'est pas touché : ce script
# reconstruit la chambre en mémoire avec les scripts existants, dans l'ordre de
# build_all.py (sans preview.setup), en remplaçant pendant la construction
# `roomlib.join` par une version qui PARTITIONNE les pièces d'après la table
# OBJECTS ci-dessous. Une fusion dont toutes les pièces vont au même objet logique
# se comporte exactement comme l'originale (même nom, même résultat — la
# simulation de tissu retrouve ses collisionneurs par nom). Sinon chaque groupe
# devient un objet à part (« U_<id> » ou « U_<id>__<enfant> ») et les pièces non
# classées gardent le nom d'origine. Rien n'est sauvegardé : room.blend n'est
# jamais écrit. Ni AO, ni second UV : Unity fera SSAO / lightmaps.
#
# Coordonnées : la table et les JSON parlent l'espace de la pièce = coordonnées
# three.js (x, z au sol, y vers le haut, mètres). Blender = (X, -Z, Y).
import argparse
import importlib
import json
import os
import re
import shutil
import sys
import time
import traceback
from collections import namedtuple

import bpy
import numpy as np
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

DEFAULT_OUT = os.path.join(REPO, "frontend", "Unity", "Mika", "Assets", "Mika", "Art", "Room")
DEFAULT_BLEND_DIR = os.path.join(REPO, "frontend", "Web", "assets-src", "objects")
SOURCE = "frontend/Web/assets-src"

P = namedtuple("P", "x y z")   # point de l'espace de la pièce (centre d'une pièce Blender)


# =====================================================================================
# Table de regroupement
# =====================================================================================
# id logique (snake_case) -> catégorie, clé d'asset, pièces, options.
#
# Pièces : noms des objets créés par les scripts (sans suffixe « .001 »). « Nom* » =
# préfixe, sinon nom exact. Le motif le plus long gagne ; à égalité, le premier de
# la table. `where` (fonction d'un P = centre de la pièce) départage les pièces
# homonymes (portes d'armoire, tiroirs de la commode, livres par étagère).
#
# Options :
#   children     sous-objets animables, exportés comme enfants nommés du même FBX
#   pivot        pivot d'un enfant : "origin" (origine de l'objet Blender) ou
#                ref(pièce, x=, y=, z=) avec "min" | "mid" | "max" de la boîte de la
#                pièce ; défaut = centre bas de la boîte de l'enfant
#   motion       indication pour Unity (axes en espace de la pièce)
#   surfaces     pièces dont le dessus reçoit des objets (plateaux, étagères)
#   node_transform  garder la transformation du nœud (chaise : origine au sol sous
#                l'assise, lacet porté par le nœud)
#   anchors      LightAnchor_* rattachés à cet objet
#   outside_ok   l'objet sort volontairement de la pièce (fond de ciel)

def O(category, asset, parts, **kw):
    return dict(category=category, asset=asset, parts=list(parts), **kw)


def C(parts, pivot=None, where=None, motion=None):
    return dict(parts=list(parts), pivot=pivot, where=where, motion=motion)


def ref(piece, x="mid", y="mid", z="mid"):
    return dict(ref=piece, x=x, y=y, z=z)


def slide(x=0.0, z=0.0):
    return {"type": "slide", "dir": {"x": x, "y": 0.0, "z": z}}


def hinge(x=0.0, z=0.0):
    # le bord libre part dans la direction (x, z) quand on ouvre
    return {"type": "hinge", "axis": "y", "opens_toward": {"x": x, "y": 0.0, "z": z}}


TOGGLE = {"type": "toggle"}

# repères tirés des scripts (build_misc : armoire, build_shelves : commode et bibliothèque)
WARDROBE_MID_Z = (-4.48 + -3.28) / 2                 # entre les deux portes
DRESSER_ROW_Y = (0.3325, 0.5225)                     # limites des 3 rangées de tiroirs
DRESSER_MID_Z = (0.05 + 1.15) / 2                    # entre les 2 colonnes
SHELF_TOPS = (0.082, 0.472, 0.862, 1.252, 1.632)     # dessus des 5 planches


def _dresser_cell(c):
    row = sum(1 for y in DRESSER_ROW_Y if c.y >= y)
    return row, (0 if c.z < DRESSER_MID_Z else 1)


def _shelf_level(c):
    lv = [i for i, t in enumerate(SHELF_TOPS) if c.y >= t - 0.01]
    return lv[-1] if lv else -1


BOOKS = ["Bookshelf_Book*", "Bookshelf_Mag*", "Bookshelf_Stack*"]

OBJECTS = {
    # ------------------------------------------------------------ architecture
    "room_floor": O("architecture", "architecture/room_floor", ["Shell_Floor"]),
    "room_walls": O("architecture", "architecture/room_walls", ["Shell_Walls", "Shell_Skirt*"]),
    "room_ceiling": O("architecture", "architecture/room_ceiling", ["Shell_Ceiling"]),
    # carte de ciel 0,6 m derrière la fenêtre (le web y met un shader de ciel)
    "window_sky": O("architecture", "architecture/window_sky", ["Window_Sky"], outside_ok=True),

    # ------------------------------------------------------------ furniture
    "writing_desk": O(
        "furniture", "furniture/desk",
        ["Desk", "Desk_Top", "Desk_Unit", "Desk_UnitKick", "Desk_Leg", "Desk_Stretcher", "Desk_Apron"],
        surfaces=["Desk_Top"],
        children={f"Desk_Drawer{k}": C([f"Desk_Drawer{k}", f"Desk_Pull{k}", f"Desk_PullPost{k}"],
                                       pivot=ref(f"Desk_Drawer{k}", z="min"), motion=slide(z=1.0))
                  for k in range(3)}),
    "desk_chair": O("furniture", "furniture/desk_chair", ["DeskChair", "Chair_*", "Desk_Hoodie*"],
                    node_transform=True),
    "bed_frame": O("furniture", "furniture/bed",
                   ["Bed_Frame", "Bed_Plinth", "Bed_Head*", "Bed_Mattress", "Bed_Pillow", "Bed_Cushion",
                    "Bed_Duvet", "Bed_Throw"]),
    "nightstand": O(
        "furniture", "furniture/nightstand",
        ["Bedside_Table", "Bedside_Leg", "Bedside_Top", "Bedside_Bottom", "Bedside_Side", "Bedside_Back",
         "Bedside_Shelf"],
        surfaces=["Bedside_Top", "Bedside_Bottom"],
        children={"Bedside_Drawer": C(["Bedside_Drawer", "Bedside_Knob"], pivot=ref("Bedside_Drawer", x="min"),
                                      motion=slide(x=1.0))}),
    "wardrobe": O(
        "furniture", "furniture/wardrobe", ["Wardrobe", "Wardrobe_Body", "Wardrobe_Kick", "Wardrobe_Crown"],
        children={
            # « droite / gauche » vues depuis la pièce, face à l'armoire (regard vers -x)
            "Wardrobe_DoorR": C(["Wardrobe_Door", "Wardrobe_Inset", "Wardrobe_Handle*"],
                                where=lambda c: c.z < WARDROBE_MID_Z,
                                pivot=ref("Wardrobe_Door", x="max", y="min", z="min"), motion=hinge(x=1.0)),
            "Wardrobe_DoorL": C(["Wardrobe_Door", "Wardrobe_Inset", "Wardrobe_Handle*"],
                                where=lambda c: c.z >= WARDROBE_MID_Z,
                                pivot=ref("Wardrobe_Door", x="max", y="min", z="max"), motion=hinge(x=1.0)),
        }),
    "shelves": O("furniture", "furniture/bookshelf",
                 ["Bookshelf", "Bookshelf_Side", "Bookshelf_Top", "Bookshelf_Back", "Bookshelf_Kick",
                  "Bookshelf_Board"],
                 surfaces=["Bookshelf_Board", "Bookshelf_Top"]),
    "dresser": O(
        "furniture", "furniture/dresser", ["Dresser", "Dresser_Body", "Dresser_Top", "Dresser_Leg"],
        surfaces=["Dresser_Top"],
        # Dresser_Drawer<rangée><colonne> : rangée 0 = en bas, colonne 0 = côté z-
        children={f"Dresser_Drawer{r}{c}": C(["Dresser_Drawer", "Dresser_Knob"],
                                             where=(lambda p, r=r, c=c: _dresser_cell(p) == (r, c)),
                                             pivot=ref("Dresser_Drawer", x="max"), motion=slide(x=-1.0))
                  for r in range(3) for c in range(2)}),
    "trinket_shelf": O("furniture", "furniture/trinket_shelf", ["Trinket_Shelf", "Trinket_Bracket*"],
                       surfaces=["Trinket_Shelf"]),

    # ------------------------------------------------------------ fixtures
    "window_pane": O(
        "fixture", "fixtures/window", ["Window_Frame*", "Window_Sill", "Window_Apron", "Window_Casing*"],
        anchors=["LightAnchor_Window"],
        # pas de vrai battant dans les scripts : la croisée (meneaux) sert de vantail
        children={"Window_Sash": C(["Window_Mullion*"], pivot=ref("Window_Mullion*", x="max", y="min", z="min"),
                                   motion=hinge(x=1.0))}),
    "bedroom_door": O(
        "fixture", "fixtures/door", ["Door", "Door_Casing*"],
        children={"Door_Leaf": C(["Door_Slab", "Door_Panel", "Door_Rose", "Door_Lever*"],
                                 pivot=ref("Door_Slab", x="max", y="min", z="min"), motion=hinge(z=-1.0))}),
    "light_switch": O("fixture", "fixtures/light_switch", ["Door_Switch*"]),
    "curtains": O(
        "fixture", "fixtures/curtains", ["Curtain_Rod", "Curtain_Finial", "Curtain_Bracket"],
        # pivot en haut, sur le bord côté mur : une échelle sur z les replie vers le coin
        children={"Curtain_L": C(["Curtain_L", "Curtain_L_Ring*"], pivot=ref("Curtain_L", y="max", z="min"),
                                 motion={"type": "scale", "axis": "z"}),
                  "Curtain_R": C(["Curtain_R", "Curtain_R_Ring*"], pivot=ref("Curtain_R", y="max", z="max"),
                                 motion={"type": "scale", "axis": "z"})}),
    "ceiling_lamp": O("fixture", "fixtures/ceiling_lamp", ["CeilingLamp*"], anchors=["LightAnchor_Ceiling"]),
    "monitor": O("fixture", "fixtures/monitor", ["Desk_Monitor", "Desk_Mon*"], anchors=["LightAnchor_Monitor"],
                 children={"Monitor_Screen": C(["Monitor_Screen"], motion=TOGGLE)}),

    # ------------------------------------------------------------ props
    "snake_plant": O("prop", "props/snake_plant", ["Plant_Snake*"]),
    "ficus": O("prop", "props/ficus", ["Plant_Fig*"]),
    "pothos": O("prop", "props/pothos", ["Plant_Pothos*"]),
    "cactus_windowsill": O("prop", "props/cactus_windowsill", ["Plant_SillPot1", "Plant_SillCactus*"]),
    "succulent_windowsill": O("prop", "props/succulent_windowsill", ["Plant_SillBowl", "Plant_SillSucculent"]),
    "keyboard": O("prop", "props/keyboard", ["Desk_Keyboard", "Desk_Kb*", "Desk_Key"]),
    "mouse": O("prop", "props/mouse", ["Desk_Mouse"]),
    "desk_mat": O("prop", "props/desk_mat", ["Desk_Mat"]),
    "mug": O("prop", "props/mug", ["Desk_Mug*", "Desk_Coffee"]),
    "notebook": O("prop", "props/notebook", ["Desk_Notebook*"]),
    "pen": O("prop", "props/pen", ["Desk_Pen"]),
    "pen_cup": O("prop", "props/pen_cup", ["Desk_PenCup", "Desk_CupPen"]),
    "book_desk_1": O("prop", "props/book_desk_1", ["Desk_BookA*"]),       # dessous de la pile
    "book_desk_2": O("prop", "props/book_desk_2", ["Desk_BookB*"]),       # dessus (porte la succulente)
    "succulent_desk": O("prop", "props/succulent_desk", ["Desk_Succ*"]),
    "waste_bin": O("prop", "props/waste_bin", ["Desk_Bin", "Desk_Paper1", "Desk_Paper2"]),
    "paper_ball": O("prop", "props/paper_ball", ["Desk_Paper3"]),         # celle tombée par terre
    "desk_lamp": O("prop", "props/desk_lamp", ["DeskLamp*"], anchors=["LightAnchor_DeskLamp"]),
    "plushie": O("prop", "props/plushie", ["Bed_Plushie", "Plush_*"]),
    "slippers": O("prop", "props/slippers", ["Bed_Slippers", "Slipper*"]),
    "bedside_lamp": O("prop", "props/bedside_lamp", ["BedLamp*"], anchors=["LightAnchor_BedLamp"]),
    "alarm_clock": O("prop", "props/alarm_clock", ["Bedside_Clock*"]),
    "book_nightstand_1": O("prop", "props/book_nightstand_1", ["Bedside_Book1"]),
    "book_nightstand_2": O("prop", "props/book_nightstand_2", ["Bedside_Book2"]),
    "shelf_basket_1": O("prop", "props/shelf_basket_1", ["Bookshelf_Basket"], where=lambda c: c.z < -2.5),
    "shelf_basket_2": O("prop", "props/shelf_basket_2", ["Bookshelf_Basket"], where=lambda c: c.z >= -2.5),
    "vase_bookshelf": O("prop", "props/vase_bookshelf", ["Bookshelf_Vase"]),
    "bunny_figurine": O("prop", "props/bunny_figurine", ["Bookshelf_Fig*"]),
    "moon_lamp": O("prop", "props/moon_lamp", ["MoonLamp*"]),
    "photo_frame_bookshelf": O("prop", "props/photo_frame_bookshelf", ["Bookshelf_Frame", "Bookshelf_Photo"]),
    "cactus_bookshelf": O("prop", "props/cactus_bookshelf", ["Bookshelf_Cactus*"]),
    "storage_box_bookshelf": O("prop", "props/storage_box_bookshelf", ["Bookshelf_Box*"]),
    "star_lamp": O("prop", "props/star_lamp", ["Trinket_Star*"]),
    "cactus_trinket_shelf": O("prop", "props/cactus_trinket_shelf", ["Trinket_Pot", "Trinket_Cactus*"]),
    "cat_figurine": O("prop", "props/cat_figurine", ["Trinket_Cat*"]),
    "photo_frame_trinket_shelf": O("prop", "props/photo_frame_trinket_shelf", ["Trinket_Frame", "Trinket_Photo"]),
    "candle": O("prop", "props/candle", ["Candle_Jar", "Candle_Wax"],
                children={"Candle_Flame": C(["Candle_Flame"], motion=TOGGLE)}),
    "speaker": O("prop", "props/speaker", ["Dresser_Speaker"]),
    "jewelry_box": O("prop", "props/jewelry_box", ["Dresser_Jewel*"]),
    "perfume_bottle": O("prop", "props/perfume_bottle", ["Dresser_Perfume*"]),
    "dried_flowers": O("prop", "props/dried_flowers", ["Dresser_Vase", "Dresser_Stem", "Dresser_Bud"]),
    "floor_cushion": O("prop", "props/floor_cushion", ["Floor_Cushion"]),
    "book_stack_floor": O("prop", "props/book_stack_floor", ["Floor_Books*"]),
    "open_book": O("prop", "props/open_book", ["Floor_OpenBook*"]),
    "laundry_basket": O("prop", "props/laundry_basket", ["Laundry*"]),
    "tote_bag": O("prop", "props/tote_bag", ["Tote", "Tote_Body", "Tote_Strap"]),
    "scarf": O("prop", "props/scarf", ["Tote_Scarf"]),
    "wardrobe_box_a": O("prop", "props/wardrobe_box_a", ["Wardrobe_BoxA"]),
    "wardrobe_box_b": O("prop", "props/wardrobe_box_b", ["Wardrobe_BoxB*"]),

    # ------------------------------------------------------------ decor
    "desk_cables": O("decor", "decor/desk_cables", ["Desk_Cable*"]),
    "pinboard": O("decor", "decor/pinboard", ["Pinboard*"]),
    "print_cat": O("decor", "decor/print_cat", ["Wall_PrintCat*"]),
    "print_flower": O("decor", "decor/print_flower", ["Wall_PrintFlower*"]),
    "poster_moon": O("decor", "decor/poster_moon", ["Poster_Moon*"]),
    "poster_peaks": O("decor", "decor/poster_peaks", ["Poster_Peaks*"]),
    "poster_city": O("decor", "decor/poster_city", ["Poster_City*"]),
    "mirror": O("decor", "decor/mirror", ["Mirror", "Mirror_Frame"]),
    "neon_sign": O("decor", "decor/neon_sign", ["Neon_*"]),
    "wall_clock": O("decor", "decor/wall_clock", ["Clock*"],
                    children={"Clock_HourHand": C(["Clock_HourHand"], pivot="origin",
                                                  motion={"type": "rotate", "axis": "z"}),
                              "Clock_MinuteHand": C(["Clock_MinuteHand"], pivot="origin",
                                                    motion={"type": "rotate", "axis": "z"})}),
    "wall_hooks": O("decor", "decor/wall_hooks", ["Hooks*"]),
    "rug": O("decor", "decor/rug", ["Rug"]),
    # livres de la bibliothèque groupés par étagère (0 = en bas : magazines couchés)
    **{f"books_shelf_{i}": O("decor", f"decor/books_shelf_{i}", BOOKS,
                             where=(lambda c, i=i: _shelf_level(c) == i)) for i in range(5)},
}

FBX_OPTIONS = dict(
    use_selection=True, object_types={"MESH", "EMPTY"},
    axis_forward="-Z", axis_up="Y", bake_space_transform=True,
    apply_scale_options="FBX_SCALE_UNITS", add_leaf_bones=False,
    use_mesh_modifiers=True, mesh_smooth_type="FACE",
    path_mode="STRIP", embed_textures=False, bake_anim=False, use_custom_props=False,
)


# =====================================================================================
# Résolution pièce -> (id, enfant)
# =====================================================================================

class Rule:
    __slots__ = ("text", "prefix", "key", "where")

    def __init__(self, pattern, key, where):
        self.prefix = pattern.endswith("*")
        self.text = pattern[:-1] if self.prefix else pattern
        self.key = key
        self.where = where

    def matches(self, name):
        return name.startswith(self.text) if self.prefix else name == self.text

    @property
    def score(self):
        return (len(self.text), 0 if self.prefix else 1)


def _compile_rules():
    rules = []
    for oid, spec in OBJECTS.items():
        for p in spec["parts"]:
            rules.append(Rule(p, (oid, ""), spec.get("where")))
        for cname, cs in spec.get("children", {}).items():
            for p in cs["parts"]:
                rules.append(Rule(p, (oid, cname), cs.get("where") or spec.get("where")))
    seen = {}
    for r in rules:
        if r.where is None:
            k = (r.text, r.prefix)
            if k in seen and seen[k] != r.key:
                raise ValueError(f"motif {r.text!r} déclaré pour {seen[k]} et {r.key}")
            seen[k] = r.key
    return rules


RULES = _compile_rules()
_SUFFIX = re.compile(r"\.\d{3,}$")


def base_name(name):
    return _SUFFIX.sub("", name)


def pattern_matches(pattern, name):
    return name.startswith(pattern[:-1]) if pattern.endswith("*") else name == pattern


def resolve(name, center):
    """(id, enfant) de la pièce `name` ; `center` est appelé seulement si une règle
    candidate a un `where`."""
    best, c = None, None
    for r in RULES:
        if not r.matches(name):
            continue
        if r.where is not None:
            if c is None:
                c = center()
            if not r.where(c):
                continue
        if best is None or r.score > best.score:
            best = r
    return best.key if best else None


# =====================================================================================
# Géométrie (espace de la pièce)
# =====================================================================================

def to_room(b):
    return (float(b[0]), float(b[2]), -float(b[1]))


def to_blender(r):
    return Vector((r[0], -r[2], r[1]))


def room_coords(o, matrix=None):
    """Sommets de `o` en espace de la pièce (matrix_basis : pas de parents ici, et
    matrix_world n'est à jour qu'après une évaluation du depsgraph)."""
    me = o.data
    n = len(me.vertices)
    co = np.empty(n * 3, np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    M = np.array(o.matrix_basis if matrix is None else matrix, dtype=np.float64)
    w = co @ M[:3, :3].T + M[:3, 3]
    return np.stack([w[:, 0], w[:, 2], -w[:, 1]], axis=1)


def bbox(objs, matrix=None):
    pts = [room_coords(o, matrix) for o in objs if o.type == "MESH" and len(o.data.vertices)]
    if not pts:
        return None
    a = np.concatenate(pts)
    return tuple(a.min(axis=0)), tuple(a.max(axis=0))


def center_of(o):
    lo, hi = bbox([o])
    return P(*((lo[i] + hi[i]) / 2 for i in range(3)))


def tris(objs):
    return sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in objs if o.type == "MESH")


def pick(lo, hi, axis, how):
    return {"min": lo[axis], "max": hi[axis], "mid": (lo[axis] + hi[axis]) / 2}[how]


def r4(v):
    return round(float(v), 4) + 0.0      # + 0.0 : pas de « -0.0 » dans le JSON


def xyz(v):
    return {"x": r4(v[0]), "y": r4(v[1]), "z": r4(v[2])}


def uniq(seq):
    out, seen = [], set()
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


# =====================================================================================
# Fusion partitionnante (remplace roomlib.join pendant la construction)
# =====================================================================================

REGISTRY = []      # pièces vues : {"key", "name", "min", "max"} (espace pièce, au moment vu)
_ORIG_JOIN = None
_roomlib = None


def _key_str(k):
    return f"{k[0]}|{k[1]}"


def key_of(o):
    s = o.get("unity_key")
    if s:
        a, b = s.split("|", 1)
        return (a, b)
    return resolve(base_name(o.name), lambda: center_of(o))


def parts_of(o):
    s = o.get("unity_parts")
    return json.loads(s) if s else [base_name(o.name)]


def _tag(o, key, parts):
    if key is not None:
        o["unity_key"] = _key_str(key)
    o["unity_parts"] = json.dumps(uniq(parts))


def _register(o, key):
    bb = bbox([o]) if o.type == "MESH" else None
    if bb:
        REGISTRY.append({"key": key, "name": base_name(o.name), "min": bb[0], "max": bb[1]})


def _join_group(objs, name, bake):
    if len(objs) == 1:          # bpy.ops.object.join refuse un objet seul
        o = objs[0]
        _roomlib.apply_modifiers([o])
        o.name = name
        o.data.name = name
        if bake:
            _roomlib.apply_transform(o, loc=True)
        return o
    return _ORIG_JOIN(objs, name, bake)


def partition_join(objs, name, bake=True):
    objs = [o for o in objs if o is not None]
    if not objs:
        return None
    groups = {}
    for o in objs:
        k = key_of(o)
        _register(o, k)
        groups.setdefault(k, []).append(o)
    if len(groups) == 1:                       # comportement d'origine, à l'identique
        k = next(iter(groups))
        parts = [n for o in objs for n in parts_of(o)]
        res = _ORIG_JOIN(objs, name, bake)
        _tag(res, k, parts)
        return res
    rest, first = None, None
    for k, members in groups.items():
        parts = [n for o in members for n in parts_of(o)]
        label = name if k is None else "U_" + k[0] + (("__" + k[1]) if k[1] else "")
        res = _join_group(members, label, bake)
        _tag(res, k, parts)
        if k is None:
            rest = res
        elif first is None:
            first = res
    return rest or first


# =====================================================================================
# Construction
# =====================================================================================

def build_room():
    """La séquence de build_all.py, sans preview.setup, avec la fusion partitionnante."""
    global _ORIG_JOIN, _roomlib
    import roomlib, materials, build_shell, build_desk, build_bed, build_shelves, build_plants, build_misc, cloth
    mods = (roomlib, materials, build_shell, build_desk, build_bed, build_shelves, build_plants, build_misc, cloth)
    for m in mods:                     # même ordre que build_all.py ; le patch vient APRÈS
        importlib.reload(m)
    _roomlib = roomlib
    _ORIG_JOIN = roomlib.join
    patched = [m for m in mods if getattr(m, "join", None) is _ORIG_JOIN]
    for m in patched:
        m.join = partition_join
    try:
        roomlib.clear_scene()
        M = materials.make_all()
        build_shell.build(M)
        build_desk.build(M)
        build_desk.build_chair(M)
        build_bed.build(M)
        build_shelves.build(M)
        build_plants.build(M)
        build_misc.build(M)
        cloth.build_bed_cloth(M)
        cloth.build_hoodie(M)
    finally:
        for m in patched:
            m.join = _ORIG_JOIN
    return roomlib, build_shell


# =====================================================================================
# Matériaux
# =====================================================================================

def lin_to_srgb(c):
    c = min(max(float(c), 0.0), 1.0)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def color_entry(rgba):
    rgba = [float(v) for v in rgba]
    return {"linear": [round(v, 6) for v in rgba],
            "srgb_hex": "#" + "".join(f"{round(lin_to_srgb(v) * 255):02x}" for v in rgba[:3])}


def _src(sock):
    return sock.links[0].from_node if sock.is_linked else None


def material_info(m, used_images):
    bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    inp = bsdf.inputs

    def tex_path(node):
        if node is None or node.type != "TEX_IMAGE" or node.image is None:
            return None
        img = node.image
        used_images[img.name] = bpy.path.abspath(img.filepath)
        return "Textures/" + os.path.basename(bpy.path.abspath(img.filepath))

    base_tex, base = None, list(inp["Base Color"].default_value)
    src = _src(inp["Base Color"])
    if src is not None and src.type == "TEX_IMAGE":
        base_tex, base = tex_path(src), [1.0, 1.0, 1.0, 1.0]
    elif src is not None and src.type == "MIX":           # texture × teinte (roomlib.mat)
        a = next(s for s in src.inputs if s.identifier == "A_Color")
        b = next(s for s in src.inputs if s.identifier == "B_Color")
        base_tex = tex_path(_src(a))
        base = list(b.default_value) if not b.is_linked else [1.0, 1.0, 1.0, 1.0]
    emit_tex = tex_path(_src(inp["Emission Color"]))
    emit_col = [1.0, 1.0, 1.0, 1.0] if emit_tex else list(inp["Emission Color"].default_value)
    strength = float(inp["Emission Strength"].default_value)
    mapping = [n for n in m.node_tree.nodes if n.type == "MAPPING"]
    uv_scale = None
    if mapping:
        s = mapping[0].inputs["Scale"].default_value
        uv_scale = [r4(s[0]), r4(s[1])]
    alpha = float(inp["Alpha"].default_value)
    return {
        "base_color": color_entry(base),
        "roughness": r4(inp["Roughness"].default_value),
        "metallic": r4(inp["Metallic"].default_value),
        "specular": r4(inp["Specular IOR Level"].default_value) if "Specular IOR Level" in inp else None,
        "emission": {"color": color_entry(emit_col), "strength": r4(strength)},
        "alpha": r4(alpha),
        "blend": "transparent" if alpha < 1.0 else "opaque",
        "double_sided": not m.use_backface_culling,
        "textures": {"base": base_tex, "normal": None, "roughness": None, "emission": emit_tex},
        "uv_scale": uv_scale,
        "flat_color": color_entry(m.diffuse_color),
    }


def is_emissive(info):
    e = info["emission"]
    return e["strength"] > 0 and (any(v > 0 for v in e["color"]["linear"][:3]) or info["textures"]["emission"])


# =====================================================================================
# Assemblage et export
# =====================================================================================

def merge(objs, name):
    """Applique les transformations complètes et fusionne en un objet `name`."""
    for o in objs:
        o.data.transform(o.matrix_basis)
        o.matrix_basis = Matrix.Identity(4)
        o.data.update()
    o = objs[0] if len(objs) == 1 else _ORIG_JOIN(objs, name, True)
    o.name = name
    o.data.name = name
    if o.name != name:
        raise RuntimeError(f"nom déjà pris : {name!r} -> {o.name!r}")
    return o


def ref_bbox(key, pattern):
    ents = [e for e in REGISTRY if e["key"] == key and pattern_matches(pattern, e["name"])]
    if not ents:
        raise RuntimeError(f"pivot : aucune pièce {pattern!r} pour {key}")
    lo = tuple(min(e["min"][i] for e in ents) for i in range(3))
    hi = tuple(max(e["max"][i] for e in ents) for i in range(3))
    return lo, hi


def export_fbx(root, children, path):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in [root] + children:
        o.select_set(True)
    bpy.context.view_layer.objects.active = root
    os.makedirs(os.path.dirname(path), exist_ok=True)
    res = bpy.ops.export_scene.fbx(filepath=path, **FBX_OPTIONS)
    if "FINISHED" not in res:
        raise RuntimeError(f"export FBX échoué : {path} ({res})")


def write_blends(blend_dir, exports, entries):
    """
    Un .blend par objet logique (<catégorie>/<id>.blend) : l'objet ramené à son pivot comme dans le FBX, ses
    enfants animables, ses matériaux (textures en chemins relatifs), dans une collection du nom de l'objet. Sa
    place dans la pièce est gardée en propriétés (`room_pos`, `room_yaw`, espace de la pièce) : l'atelier
    d'animation l'y remet, ou le pose là où Unity le met (chaise pivotée, objets glissés).
    """
    by_id = {e["id"]: e for e in entries}
    for oid, root, child_objs, rel in exports:
        e = by_id[oid]
        coll = bpy.data.collections.new(oid)
        for o in [root] + child_objs:
            coll.objects.link(o)
        root["room_pos"] = [e["pos"]["x"], e["pos"]["y"], e["pos"]["z"]]
        root["room_yaw"] = e["yaw"]
        root["category"] = e["category"]
        root["source"] = "frontend/Web/assets-src/blender/export_unity.py"
        path = os.path.join(blend_dir, e["category"], f"{oid}.blend")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        bpy.data.libraries.write(path, {coll}, path_remap="RELATIVE_ALL", fake_user=True, compress=True)
        print(f"[export_unity] .blend {os.path.relpath(path, REPO)}")


def main(argv):
    ap = argparse.ArgumentParser(prog="export_unity.py")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--blend-dir", nargs="?", const=DEFAULT_BLEND_DIR, default=None)
    ap.add_argument("--no-unity", action="store_true")
    args = ap.parse_args(argv)
    out = os.path.abspath(args.out)
    t0 = time.time()

    roomlib, build_shell = build_room()
    print(f"[export_unity] chambre construite en {time.time() - t0:.1f} s")

    room = list(roomlib.collection().objects)
    anchors = [o for o in room if o.type == "EMPTY" and o.name.startswith("LightAnchor_")]
    meshes = [o for o in room if o.type == "MESH"]
    strays = [o.name for o in room if o not in anchors and o not in meshes]
    if strays:
        raise RuntimeError(f"objets inattendus : {strays}")
    roomlib.apply_modifiers(meshes)
    tris_build = tris(meshes)

    # ---------------------------------------------------------------- classement
    by_key, unassigned = {}, []
    for o in meshes:
        k = key_of(o)
        _register(o, k)
        if k is None:
            unassigned.append(o.name)
        else:
            by_key.setdefault(k, []).append(o)
    if unassigned:
        raise RuntimeError(f"pièces sans objet logique : {sorted(unassigned)}")
    missing = [f"{oid}" for oid in OBJECTS if (oid, "") not in by_key]
    missing += [f"{oid}/{c}" for oid, s in OBJECTS.items() for c in s.get("children", {}) if (oid, c) not in by_key]
    if missing:
        raise RuntimeError(f"entrées de la table sans pièce : {missing}")

    for o in meshes:                       # même repli que finalize.prepare_meshes
        me = o.data
        if "UVMap" not in me.uv_layers:
            roomlib.box_uv(o, 0.5)
        for extra in [l for l in me.uv_layers if l.name != "UVMap"]:
            me.uv_layers.remove(extra)

    # ---------------------------------------------------------------- objets logiques
    room_lo = (build_shell.ROOM["minX"], 0.0, build_shell.ROOM["minZ"])
    room_hi = (build_shell.ROOM["maxX"], build_shell.ROOM["H"], build_shell.ROOM["maxZ"])
    entries, exports, used_images, warnings = [], [], {}, []
    owner = {a: oid for oid, s in OBJECTS.items() for a in s.get("anchors", [])}
    pivots = {}
    for oid, spec in OBJECTS.items():
        body = by_key[(oid, "")]
        kids = {c: by_key[(oid, c)] for c in spec.get("children", {})}
        everything = body + [o for v in kids.values() for o in v]
        parts = uniq([n for o in everything for n in parts_of(o)])
        n_tris = tris(everything)
        mats = uniq([m.name for o in everything for m in o.data.materials if m is not None])
        wlo, whi = bbox(everything)
        if not spec.get("outside_ok"):
            for i, ax in enumerate("xyz"):
                if wlo[i] < room_lo[i] - 0.2 or whi[i] > room_hi[i] + 0.2:
                    warnings.append(f"{oid}: sort de la pièce sur {ax} ({wlo[i]:.2f}..{whi[i]:.2f})")

        if spec.get("node_transform"):
            if len(body) != 1 or kids:
                raise RuntimeError(f"{oid}: node_transform attend un seul objet sans enfant")
            root = body[0]
            loc, rot, sca = root.matrix_basis.decompose()
            eul = rot.to_euler()
            if abs(eul.x) > 1e-5 or abs(eul.y) > 1e-5 or (sca - Vector((1, 1, 1))).length > 1e-5:
                raise RuntimeError(f"{oid}: transformation de nœud autre qu'un lacet")
            pivot, yaw = to_room(loc), eul.z           # Blender Rz(a) == three Ry(a)
            root.matrix_basis = Matrix.Identity(4)
            root.name = oid
            root.data.name = oid
            lo, hi = bbox([root])
        else:
            pivot, yaw = ((wlo[0] + whi[0]) / 2, wlo[1], (wlo[2] + whi[2]) / 2), 0.0
            lo, hi = wlo, whi
        pivots[oid] = pivot

        # pivots des enfants, calculés avant de toucher aux transformations
        child_pivots = {}
        for cname, cs in spec.get("children", {}).items():
            objs = kids[cname]
            pv = cs.get("pivot")
            if pv == "origin":
                if len(objs) != 1:
                    raise RuntimeError(f"{oid}/{cname}: pivot 'origin' sur plusieurs objets")
                child_pivots[cname] = to_room(objs[0].matrix_basis.translation)
            elif pv is None:
                clo, chi = bbox(objs)
                child_pivots[cname] = ((clo[0] + chi[0]) / 2, clo[1], (clo[2] + chi[2]) / 2)
            else:
                rlo, rhi = ref_bbox((oid, cname), pv["ref"])
                child_pivots[cname] = tuple(pick(rlo, rhi, i, pv[ax]) for i, ax in enumerate("xyz"))

        surfaces = []
        for pat in spec.get("surfaces", []):
            seen = set()
            for e in REGISTRY:
                if e["key"] != (oid, "") or not pattern_matches(pat, e["name"]):
                    continue
                sig = (e["min"], e["max"])
                if sig in seen:
                    continue
                seen.add(sig)
                surfaces.append({"piece": e["name"], "height": r4(e["max"][1] - pivot[1]),
                                 "min": {"x": r4(e["min"][0] - pivot[0]), "z": r4(e["min"][2] - pivot[2])},
                                 "max": {"x": r4(e["max"][0] - pivot[0]), "z": r4(e["max"][2] - pivot[2])}})
        surfaces.sort(key=lambda s: s["height"])
        child_parts = {c: uniq([n for o in v for n in parts_of(o)]) for c, v in kids.items()}

        if args.dry_run:
            root, child_objs = None, []
        else:
            if not spec.get("node_transform"):
                root = merge(body, oid)
                root.data.transform(Matrix.Translation(-to_blender(pivot)))
                root.data.update()
            child_objs = []
            for cname in spec.get("children", {}):
                cp = child_pivots[cname]
                co = merge(kids[cname], cname)
                co.data.transform(Matrix.Translation(-to_blender(cp)))
                co.data.update()
                co.parent = root
                co.matrix_parent_inverse = Matrix.Identity(4)
                co.matrix_basis = Matrix.Translation(to_blender(cp) - to_blender(pivot))
                child_objs.append(co)

        children = []
        for cname, cs in spec.get("children", {}).items():
            cp = child_pivots[cname]
            ch = {"name": cname, "pivot": xyz([cp[i] - pivot[i] for i in range(3)]),
                  "parts": child_parts[cname]}
            if cs.get("motion"):
                ch["motion"] = cs["motion"]
            children.append(ch)

        fbx_rel = f"Models/{spec['category']}/{oid}.fbx"
        entries.append({
            "id": oid, "category": spec["category"], "asset": spec["asset"], "fbx": fbx_rel,
            "parts": parts, "pos": xyz(pivot), "yaw": r4(yaw),
            "size": xyz([hi[i] - lo[i] for i in range(3)]),
            "materials": mats, "emissive": False, "children": children, "surfaces": surfaces,
            "triangles": n_tris,
        })
        exports.append((oid, root, child_objs, fbx_rel))

    # ---------------------------------------------------------------- matériaux
    mat_infos = {}
    for e in entries:
        for name in e["materials"]:
            if name not in mat_infos:
                mat_infos[name] = material_info(bpy.data.materials[name], used_images)
        e["emissive"] = any(is_emissive(mat_infos[n]) for n in e["materials"])

    light_anchors = []
    for a in sorted(anchors, key=lambda o: o.name):
        p = to_room(a.matrix_basis.translation)
        ent = {"name": a.name, "pos": xyz(p)}
        if a.name in owner:
            oid = owner[a.name]
            ent["object"] = oid
            ent["local"] = xyz([p[i] - pivots[oid][i] for i in range(3)])
        light_anchors.append(ent)

    tris_export = sum(e["triangles"] for e in entries)
    print(f"[export_unity] {len(entries)} objets, {tris_export} triangles (scène : {tris_build})")
    for w in warnings:
        print("[export_unity] ATTENTION", w)
    for e in entries:
        kids = ",".join(c["name"] for c in e["children"])
        print(f"[export_unity] {e['id']:28s} {e['category']:12s} {e['asset']:34s} {e['triangles']:6d}"
              f"{'  [' + kids + ']' if kids else ''}")
    if tris_export != tris_build:
        raise RuntimeError(f"triangles perdus : {tris_export} exportés pour {tris_build} construits")
    if args.dry_run:
        return

    if args.blend_dir:
        write_blends(os.path.abspath(args.blend_dir), exports, entries)
    if args.no_unity:
        print(f"[export_unity] .blend écrits en {time.time() - t0:.1f} s (rien pour Unity)")
        return

    # ---------------------------------------------------------------- écriture
    os.makedirs(out, exist_ok=True)
    # Les FBX qu'un export précédent a écrits (ceux de son room_layout.json) : les seuls qu'on peut retirer s'ils
    # n'existent plus. D'autres scripts écrivent dans Models/ (duvet_states.py : duvet.fbx, throw.fbx).
    ours = set()
    old_layout = os.path.join(out, "room_layout.json")
    if os.path.exists(old_layout):
        with open(old_layout, encoding="utf-8") as f:
            ours = {os.path.normpath(os.path.join(out, e["fbx"])) for e in json.load(f).get("objects", [])}
    written = set()
    for oid, root, child_objs, rel in exports:
        path = os.path.join(out, rel)
        export_fbx(root, child_objs, path)
        written.add(os.path.normpath(path))
    tex_dir = os.path.join(out, "Textures")
    os.makedirs(tex_dir, exist_ok=True)
    for src in sorted(set(used_images.values())):
        dst = os.path.join(tex_dir, os.path.basename(src))
        shutil.copyfile(src, dst)
        written.add(os.path.normpath(dst))
    # fichiers d'un export précédent qui n'existent plus (les .meta suivent)
    for sub, exts in (("Models", (".fbx",)), ("Textures", (".jpg", ".jpeg", ".png"))):
        for dirpath, _, files in os.walk(os.path.join(out, sub)):
            for f in files:
                p = os.path.normpath(os.path.join(dirpath, f))
                if f.lower().endswith(exts) and p not in written and (sub != "Models" or p in ours):
                    os.remove(p)
                    if os.path.exists(p + ".meta"):
                        os.remove(p + ".meta")
                    print("[export_unity] supprimé (obsolète) :", os.path.relpath(p, out))

    layout = {
        "format": "mika.room-layout/1", "source": SOURCE, "units": "m",
        "space": "room (three.js: y up, facing = (sin φ, cos φ))",
        "room": {"min": xyz(room_lo), "max": xyz(room_hi)},
        "objects": entries, "light_anchors": light_anchors, "materials_file": "materials.json",
    }
    with open(os.path.join(out, "room_layout.json"), "w", encoding="utf-8") as f:
        json.dump(layout, f, ensure_ascii=False, indent=1)
        f.write("\n")
    with open(os.path.join(out, "materials.json"), "w", encoding="utf-8") as f:
        json.dump({"format": "mika.room-materials/1", "source": SOURCE,
                   "color_note": "linear = valeurs du shader Blender ; srgb_hex = même couleur encodée sRGB",
                   "materials": dict(sorted(mat_infos.items()))}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    with open(os.path.join(out, "README.md"), "w", encoding="utf-8") as f:
        f.write(readme(entries, tris_export))
    print(f"[export_unity] écrit dans {out} en {time.time() - t0:.1f} s")


# =====================================================================================
# README généré (la table suit la table OBJECTS)
# =====================================================================================

README_HEAD = """# Chambre de Mika — export Unity

Généré par `frontend/Web/assets-src/blender/export_unity.py` à partir des scripts de
`frontend/Web/assets-src/blender/` (les mêmes que le `room.glb` du client web). **Ne pas
éditer à la main** : relancer l'export.

```sh
blender -b --factory-startup --python frontend/Web/assets-src/blender/export_unity.py -- \\
    --out frontend/Unity/Mika/Assets/Mika/Art/Room
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
- `Textures/` — les images utilisées, copiées de `frontend/Web/assets-src/textures/`.

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

"""


def readme(entries, total):
    lines = [README_HEAD, f"## Objets ({len(entries)}, {total} triangles)\n",
             "| id | catégorie | asset | triangles | enfants |", "| --- | --- | --- | ---: | --- |"]
    for e in entries:
        kids = ", ".join(f"`{c['name']}`" for c in e["children"])
        lines.append(f"| `{e['id']}` | {e['category']} | `{e['asset']}` | {e['triangles']} | {kids} |")
    lines.append("")
    lines.append(README_NOTES.replace("UNITY_CHECK\n", README_UNITY))
    return "\n".join(lines)


README_UNITY = """## À vérifier côté Unity

Constaté : Unity 6.6 importe les 84 FBX et les 18 textures sans erreur ni
avertissement (Editor.log). Pas encore vérifié dans l'éditeur :

- Que l'importeur de Unity 6.6 inverse bien X (attendu : `Desk_Drawer0` du bureau en
  `localPosition` (-0,72 ; 0,167 ; 0,32) quand le layout dit (0,72 ; 0,167 ; 0,32)),
  avec « Convert Units » actif (échelle 1) et sans rotation de -90° sur les racines.
- Le sens d'ouverture des battants et de rotation des aiguilles après le miroir X.
- Les matériaux : l'import FBX ne transporte ni la teinte qui multiplie les textures
  ni l'émission telle quelle ; `materials.json` fait foi.

"""



README_NOTES = """## Vérifié

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

UNITY_CHECK
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
"""


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    try:
        main(argv)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
