# Le décor réel de l'atelier d'animation : les objets de la pièce, chacun depuis son propre fichier
# (frontend/assets-src/objects/<catégorie>/<id>.blend, écrits par `export_unity.py --blend-dir`), posés autour de Mika
# exactement comme Unity les pose — pour qu'une animation se vérifie contre la vraie chaise, le vrai bureau, le vrai
# clavier, et pas contre des boîtes.
#
# Le repère : celui des clips (Mika assise, hanches à l'origine, elle regarde −Y, sa gauche est +X, Z en haut ; le sol
# du clip est 2 cm sous le vrai). Les places viennent du relevé Unity (UnityFrontend/ArtSource/atelier/desk_layout.json,
# repère du siège : x à droite, y en haut, z devant, chaise ni tournée ni roulée). La chaise de bureau tourne sur son
# pied et roule le long de son assise d'origine (ChairRig) : elle et la chaise bougent ensemble, c'est donc le reste
# de la pièce qui tourne et recule autour d'elle. Les calculs de place (repère de travail, objets glissés sur le
# plateau) sont ceux de BodyActivity, mot pour mot : une valeur changée ici doit l'être là-bas.
import json
import math

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

import atelier_lib as al

OBJECTS = al.REPO / "frontend/assets-src/objects"
DESK_LAYOUT = al.WORKDIR / "desk_layout.json"
FLOOR_DROP = 0.02           # hanches à 0,57 dans le clip, siège à 0,59 dans Unity

# --- BodyActivity (Unity) : les mêmes constantes ---------------------------------------------------------------------
TYPE_LATERAL, TYPE_FORWARD = 0.08, 0.39
WRITE_LATERAL, WRITE_FORWARD = 0.0, 0.40
MOUSE_SPOT = (0.36, 0.30)           # (à droite, devant), repère de travail
MUG_SPOT = (-0.30, 0.33)
WRITE_MUG_SPOT = (-0.28, 0.46)
PEN_SPOT = (-0.20, 0.42)
NOTEBOOK_LEFT = 0.17
MAX_ROLL = 0.38
# Écrire : la chaise pivote de 45° vers sa gauche depuis la position de frappe (un pas des pieds, chair_turn_left_45) ;
# le carnet est posé droit devant elle à cette position (atelier_desk_plan.py, build_desk.py).
WRITE_TURN = -45.0
# Tirer ou repousser la chaise : les mains sur le bord du bureau, de part et d'autre (dans l'axe de ses épaules quand
# la chaise présente le clavier), à cette distance du bord sur le plateau.
GRIP_LATERAL = 0.17
GRIP_INSIDE = 0.04
# Ce que le décor contient : le bureau, la chaise, et ce qui est posé dessus ou autour.
DESK_OBJECTS = ("writing_desk", "desk_chair", "desk_mat", "keyboard", "mouse", "monitor", "mug", "notebook", "pen",
                "pen_cup", "book_desk_1", "book_desk_2", "succulent_desk", "desk_lamp", "waste_bin")


# --- charger -----------------------------------------------------------------------------------------------------------
def collection():
    coll = bpy.data.collections.get("Décor")
    if coll is None:
        coll = bpy.data.collections.new("Décor")
        bpy.context.scene.collection.children.link(coll)
    return coll


def load(oid):
    """L'objet `oid` (sa racine), chargé une fois depuis son .blend ; ses enfants (tiroirs, écran) suivent."""
    obj = bpy.data.objects.get(oid)
    if obj is not None and obj.get("room_pos") is not None:
        return obj
    if oid in FBX_OBJECTS:
        return load_fbx(oid)
    path = next(OBJECTS.glob(f"*/{oid}.blend"), None)
    if path is None:
        raise FileNotFoundError(f"pas de .blend pour {oid} dans {OBJECTS} (lancer export_unity.py --blend-dir)")
    with bpy.data.libraries.load(str(path), link=False) as (_, dst):
        dst.collections = [oid]
    coll = dst.collections[0]
    collection().children.link(coll)
    root = next(o for o in coll.objects if o.parent is None)
    # Les rendus de contrôle (Workbench) montrent la couleur d'affichage : celle du shader.
    for o in coll.objects:
        if o.type != "MESH":
            continue
        for m in o.data.materials:
            if m is None or not m.use_nodes:
                continue
            bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if bsdf is not None and not bsdf.inputs["Base Color"].is_linked:
                m.diffuse_color = tuple(bsdf.inputs["Base Color"].default_value)
    bpy.context.view_layer.update()
    return root


# La couette et le plaid du lit : simulés par duvet_states.py, livrés en FBX à formes (la base = le lit fait), origine
# au centre de la pièce.
FBX_OBJECTS = {"duvet": "UnityFrontend/Mika/Assets/Mika/Art/Room/Models/furniture/duvet.fbx",
               "throw": "UnityFrontend/Mika/Assets/Mika/Art/Room/Models/furniture/throw.fbx"}


def load_fbx(oid):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(al.REPO / FBX_OBJECTS[oid]), axis_forward="-Z", axis_up="Y", bake_space_transform=True)
    new = [o for o in bpy.data.objects if o not in before]
    meshes_ = [o for o in new if o.type == "MESH"]
    root = bpy.data.objects.new(oid, None)
    root["room_pos"] = [0.0, 0.0, 0.0]
    collection().objects.link(root)
    for o in new:
        for c in o.users_collection:
            c.objects.unlink(o)
        collection().objects.link(o)
    for o in meshes_:
        mw = o.matrix_world.copy()
        o.parent = root
        o.matrix_parent_inverse = Matrix.Identity(4)
        o.matrix_world = mw
    for o in new:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.update()
    return root


def meshes(root):
    return [o for o in [root] + list(root.children_recursive) if o.type == "MESH"]


# --- placer ------------------------------------------------------------------------------------------------------------
def unity_to_atelier(p):
    """Un point du repère de Mika en unités Unity (x droite, y haut, z devant) → l'atelier (Blender)."""
    return Vector((-p[0], -p[2], p[1] - FLOOR_DROP))


def seen_from_her(pos, yaw, chair_yaw, chair_roll):
    """Une place du repère du siège (chaise d'origine) vue depuis elle, la chaise tournée de chair_yaw (°, + vers sa
    droite) et avancée de chair_roll (m, vers le bureau)."""
    x, y, z = pos[0], pos[1], pos[2] - chair_roll
    a = math.radians(-chair_yaw)
    return (x * math.cos(a) + z * math.sin(a), y, -x * math.sin(a) + z * math.cos(a)), yaw - chair_yaw


def matrix(pos_her, yaw_her):
    """La matrice atelier d'un objet posé à `pos_her` (repère de Mika, Unity) et tourné de `yaw_her` (°, Unity)."""
    return Matrix.Translation(unity_to_atelier(pos_her)) @ Matrix.Rotation(-math.radians(yaw_her), 4, "Z")


class Layout:
    """Le relevé Unity du bureau, et les calculs de place de BodyActivity (repère du siège, chaise d'origine)."""

    def __init__(self, path=DESK_LAYOUT):
        data = json.load(open(path, encoding="utf-8"))
        self.seat_hips = data["seat_hips"][1]
        # Un objet à plusieurs pièces (une table de chevet et son tiroir) : sa place est celle de son modèle.
        self.home = {}
        for o in data["objects"]:
            if o.get("part", "Modèle") == "Modèle" or o["id"] not in self.home:
                self.home[o["id"]] = (tuple(o["origin"]), o["yaw"])
        # Un livre resté tenu au moment du relevé : sa place est sous l'autre, sur la pile.
        if "book_desk_2" in self.home and abs(self.home.get("book_desk_1", ((0, 0, 0), 0))[0][1] - 0.76) > 0.02:
            (x, _, z), yaw = self.home["book_desk_2"]
            self.home["book_desk_1"] = ((x, 0.76, z), yaw)
        self._box = None

    def desk_box(self):
        """La boîte du bureau dans son propre repère, en axes Unity (x, z) : comme DeskBox."""
        if self._box is None:
            root = load("writing_desk")
            bpy.context.view_layer.update()
            inv = root.matrix_world.inverted()
            pts = [inv @ (o.matrix_world @ Vector(c)) for o in meshes(root) for c in o.bound_box]
            # Blender (X, Y, Z) local → Unity local (−X, Z, −Y)
            xs = [-p.x for p in pts]
            zs = [-p.y for p in pts]
            self._box = (min(xs), max(xs), min(zs), max(zs))
        return self._box

    def onto_desk(self, p, direction, margin):
        """OntoDesk : p (x, z, repère du siège) s'il est sur le plateau à `margin` de ses bords, sinon le premier point
        qui l'est en allant vers `direction`."""
        (dx, _, dz), dyaw = self.home["writing_desk"]
        x0, x1, z0, z1 = self.desk_box()
        a = math.radians(-dyaw)
        n = math.hypot(direction[0], direction[1]) or 1.0
        sx, sz = direction[0] / n * 0.01, direction[1] / n * 0.01
        for i in range(61):
            qx, qz = p[0] + sx * i - dx, p[1] + sz * i - dz
            lx, lz = qx * math.cos(a) + qz * math.sin(a), -qx * math.sin(a) + qz * math.cos(a)
            if x0 + margin <= lx <= x1 - margin and z0 + margin <= lz <= z1 - margin:
                return (p[0] + sx * i, p[1] + sz * i)
        return p

    @staticmethod
    def work_frame(point, lateral, forward):
        """WorkFrame : le pivot (°) et le roulement (m) qui mettent `point` (x, z) à `lateral` à droite, `forward` devant."""
        kx, kz = point
        need = lateral * lateral + forward * forward - kx * kx
        along = math.sqrt(need) if need > 0 else max(0.05, forward)
        roll = min(max(kz - along, 0.0), MAX_ROLL)
        yaw = math.degrees(math.atan2(kx, kz - roll)) - math.degrees(math.atan2(lateral, forward))
        return max(-60.0, min(60.0, yaw)), roll

    @staticmethod
    def work_point(yaw, roll, local):
        """WorkPoint : un point (à droite, devant) du repère de travail → repère du siège (x, z)."""
        a = math.radians(yaw)
        wf, wr = (math.sin(a), math.cos(a)), (math.cos(a), -math.sin(a))
        return (wr[0] * local[0] + wf[0] * local[1], roll + wr[1] * local[0] + wf[1] * local[1])

    def typing(self):
        (x, _, z), _ = self.home["keyboard"]
        return self.work_frame((x, z), TYPE_LATERAL, TYPE_FORWARD)

    def writing_spot(self):
        """WritingSpot : le carnet tiré à gauche du clavier, tout entier sur le plateau."""
        size = max(0.238, 0.273)
        return self.onto_desk((-NOTEBOOK_LEFT, 0.3), (0.0, 1.0), 0.5 * size + 0.02)

    def writing(self):
        return self.work_frame(self.writing_spot(), WRITE_LATERAL, WRITE_FORWARD)

    def work_spot(self, yaw, roll, spot, margin):
        ahead = (math.sin(math.radians(yaw)), math.cos(math.radians(yaw)))
        return self.onto_desk(self.work_point(yaw, roll, spot), ahead, margin)

    # --- les positions de la chaise que les gestes relient ----------------------------------------------------------
    def chair_pose(self, name):
        """
        (pivot °, roulement m) d'une position nommée de la chaise : « home » (là où elle s'assoit et se lève, la chaise
        à sa place), « type » (le clavier présenté), « write » (pivotée de 45° vers sa gauche depuis « type » : le
        carnet droit devant elle), « type+45 », « type-90 »… (tournée vers quelqu'un, d'un pas des pieds).
        """
        if name == "home":
            return 0.0, 0.0
        ty, tr = self.typing()
        if name == "type":
            return ty, tr
        if name == "write":
            return ty + WRITE_TURN, tr
        for base in ("type", "write", "home"):
            if name.startswith(base) and len(name) > len(base):
                y, r = self.chair_pose(base)
                return y + float(name[len(base):]), r
        raise KeyError(name)

    def desk_edge(self):
        """Le bord avant du plateau (repère du siège, chaise d'origine) : deux points (x, z) et la normale vers le fond."""
        (dx, _, dz), dyaw = self.home["writing_desk"]
        x0, x1, z0, z1 = self.desk_box()
        a = math.radians(dyaw)

        def seat(lx, lz):
            return Vector((lx * math.cos(a) + lz * math.sin(a) + dx, -lx * math.sin(a) + lz * math.cos(a) + dz))
        # Le bord le plus proche du siège.
        edges = [(seat(x0, z1), seat(x1, z1)), (seat(x0, z0), seat(x1, z0))]
        e0, e1 = min(edges, key=lambda e: ((e[0] + e[1]) / 2).length)
        t = (e1 - e0).normalized()
        n = Vector((-t.y, t.x))
        centre = seat((x0 + x1) / 2, (z0 + z1) / 2)
        if (centre - e0).dot(n) < 0:
            n = -n
        return e0, e1, n

    def grips(self):
        """
        Où ses mains se posent sur le bord du bureau pour tirer ou repousser la chaise (repère du siège, (x, z)) : de
        part et d'autre, dans l'axe de ses épaules quand la chaise présente le clavier, à GRIP_INSIDE du bord.
        """
        e0, e1, n = self.desk_edge()
        ty, tr = self.typing()
        a = math.radians(ty)
        wf, wr = Vector((math.sin(a), math.cos(a))), Vector((math.cos(a), -math.sin(a)))
        origin = Vector((0.0, tr))
        out = []
        for lx in (-GRIP_LATERAL, GRIP_LATERAL):
            p0 = origin + wr * lx
            # p0 + wf·s sur la droite du bord : (p0 + wf s − e0) · n = 0
            s = (e0 - p0).dot(n) / wf.dot(n)
            out.append(p0 + wf * s + n * GRIP_INSIDE)
        return out


# --- passer du repère du siège à celui du clip ------------------------------------------------------------------------
def to_clip(p, chair):
    """Un point du repère du siège (Unity, chaise d'origine) vu d'elle, la chaise en `chair` (pivot °, roulement m)."""
    q, _ = seen_from_her(p, 0.0, chair[0], chair[1])
    return unity_to_atelier(q)


def to_seat(v, chair):
    """L'inverse : un point du clip (Blender), la chaise en `chair`, dans le repère du siège (Unity)."""
    x, y, z = -v.x, v.z + FLOOR_DROP, -v.y
    a = math.radians(-chair[0])
    return (x * math.cos(a) - z * math.sin(a), y, x * math.sin(a) + z * math.cos(a) + chair[1])


def features(layout, chair):
    """
    Ce que les gestes prennent sur le bureau, mesuré sur les vrais modèles posés (repère du clip, la chaise en
    `chair`) : la tasse (centre du fond, hauteur, direction de l'anse), le stylo (centre, axe), le carnet (centre du
    dessus, son grand axe), le haut du plateau.
    """
    Scene(layout, chair).apply(0)

    def pts(oid):
        return [o.matrix_world @ v.co for o in meshes(load(oid)) for v in o.data.vertices]
    out = {}
    m = pts("mug")
    zmin = min(p.z for p in m)
    base = [p for p in m if p.z < zmin + 0.004]
    c = sum(base, Vector()) / len(base)
    far = max(m, key=lambda p: (p.xy - c.xy).length)
    h = (far.xy - c.xy).normalized()
    # L'anse : un demi-anneau dans le plan vertical (fond → haut), à 4,4 + 2,6 cm de l'axe, centré 5,2 cm au-dessus du fond ;
    # son trou (où passent l'index et le majeur) à mi-chemin.
    out["mug"] = dict(base=Vector((c.x, c.y, zmin)), handle=Vector((h.x, h.y, 0.0)),
                      hole=Vector((c.x, c.y, zmin + 0.052)) + Vector((h.x, h.y, 0.0)) * 0.057,
                      height=max(p.z for p in m) - zmin)
    p = pts("pen")
    pc = sum(p, Vector()) / len(p)
    far = max(p, key=lambda q: (q - pc).length)
    out["pen"] = dict(center=pc, axis=(far - pc).normalized(), half=(far - pc).length)
    nb = pts("notebook")
    top = max(q.z for q in nb)
    nc = sum(nb, Vector()) / len(nb)
    far = max(nb, key=lambda q: (q.xy - nc.xy).length)
    out["notebook"] = dict(center=Vector((nc.x, nc.y, top)), top=top)
    out["desk_top"] = max(q.z for o in meshes(load("writing_desk")) for q in [o.matrix_world @ Vector(b) for b in o.bound_box])
    return out


# --- une scène : où est la chaise, où sont les objets ---------------------------------------------------------------
class Scene:
    """
    Le décor d'un clip : la chaise (tournée, avancée — constante ou image par image), les objets déplacés (souris,
    tasse, stylo, carnet : là où BodyActivity les glisse) et les objets tenus (une matrice atelier par image).
    """

    def __init__(self, layout, chair, moved=None, held=None, hidden=(), objects=DESK_OBJECTS, moves=None):
        self.layout = layout
        self.objects = objects
        self.chair = chair            # (yaw, roll) ou fonction image → (yaw, roll)
        self.moved = moved or {}      # id → ((x, y, z), yaw), repère du siège (chaise d'origine)
        self.held = held or {}        # id → [matrice atelier ou None, …] (None : à sa place)
        # id → [déplacement rigide depuis sa place, matrice du clip, …] : un objet que la main a pris et porte
        # (atelier_desk_gestures) ; l'identité quand il est posé.
        self.moves = moves or {}
        self.hidden = set(hidden)

    def chair_at(self, f):
        return self.chair(f) if callable(self.chair) else self.chair

    def place(self, oid, f):
        """La matrice atelier de l'objet `oid` à l'image f."""
        if oid == "desk_chair":       # elle tourne avec la chaise : la chaise reste où elle est pour elle
            pos, yaw = self.layout.home[oid]
            return matrix(pos, yaw)
        held = self.held.get(oid)
        if held is not None and f < len(held) and held[f] is not None:
            return held[f]
        pos, yaw = self.moved.get(oid, self.layout.home[oid])
        cy, cr = self.chair_at(f)
        p, y = seen_from_her(pos, yaw, cy, cr)
        rest = matrix(p, y)
        moves = self.moves.get(oid)
        if moves is not None and f < len(moves) and moves[f] is not None:
            return moves[f] @ rest
        return rest

    def apply(self, f):
        for oid in self.objects:
            if oid not in self.layout.home:
                continue
            root = load(oid)
            root.matrix_world = self.place(oid, f)
            for o in meshes(root):
                o.hide_render = oid in self.hidden
        bpy.context.view_layer.update()

    def key(self, n):
        """Des clés image par image (pour les rendus : scene.frame_set pose le décor)."""
        for oid in self.objects:
            if oid not in self.layout.home:
                continue
            root = load(oid)
            root.animation_data_clear()
            root.rotation_mode = "QUATERNION"
            for f in range(n):
                loc, rot, _ = self.place(oid, f).decompose()
                root.location, root.rotation_quaternion = loc, rot
                root.keyframe_insert("location", frame=f)
                root.keyframe_insert("rotation_quaternion", frame=f)
            for o in meshes(root):
                o.hide_render = oid in self.hidden


# --- ce qui entre où ---------------------------------------------------------------------------------------------------
class Contacts:
    """
    Les parties de son corps qui entrent dans un objet du décor : sur ses maillages déformés (corps, chaussures), chaque
    sommet d'une partie est confronté à la surface de l'objet (BVH du maillage évalué, au monde). Profondeur au-delà
    d'une tolérance, par (partie, objet) : la pire image et le pire os.
    """

    PARTS = {
        "pieds": ("Foot", "Toes"),
        "jambes": ("LowerLeg",),
        "cuisses": ("UpperLeg",),
        "dos": ("hips", "spine", "chest", "upperChest"),
        "bras": ("UpperArm", "LowerArm"),
        "mains": ("Hand", "Thumb", "Index", "Middle", "Ring", "Little"),
    }

    def __init__(self, rig, bodies=("Body2", "ClothShoes")):
        self.rig = rig
        self.objs = [bpy.data.objects[n] for n in bodies if n in bpy.data.objects]
        human_of_bone = {}
        for b in rig.arm.data.bones:
            p = b
            while p is not None and p.name not in rig.human_of:
                p = p.parent
            human_of_bone[b.name] = rig.human_of[p.name] if p is not None else None
        self.owner = []
        for obj in self.objs:
            groups = {g.index: g.name for g in obj.vertex_groups}
            own = []
            for v in obj.data.vertices:
                best = max(v.groups, key=lambda g: g.weight, default=None)
                own.append(human_of_bone.get(groups.get(best.group)) if best is not None else None)
            self.owner.append(own)

    @classmethod
    def part_of(cls, human):
        if human is None:
            return None
        for part, keys in cls.PARTS.items():
            if any(human == k or human.endswith(k) for k in keys):
                return part
        return None

    @staticmethod
    def tree(obj_list):
        verts, polys = [], []
        deps = bpy.context.evaluated_depsgraph_get()
        for o in obj_list:
            ev = o.evaluated_get(deps)
            me = ev.to_mesh()
            mw = o.matrix_world
            base = len(verts)
            verts.extend(mw @ v.co for v in me.vertices)
            polys.extend(tuple(base + i for i in p.vertices) for p in me.polygons)
            ev.to_mesh_clear()
        return BVHTree.FromPolygons(verts, polys)

    # Les objets posés sur un plan (un clavier : des touches sur une plaque, des volumes imbriqués) : « dedans », c'est
    # sous leur dessus, mesuré par un rayon vers le bas. Le côté de la face la plus proche se trompe sur eux : un doigt
    # pris dans la plaque avait pour face la plus proche le dessous d'une touche, tourné vers le bas — « dehors ».
    HEIGHTFIELD = {"keyboard", "desk_mat", "notebook", "pen", "book_desk_1", "book_desk_2"}
    # Les récipients ouverts (une tasse) : la face la plus proche d'un point dehors peut être la paroi intérieure, tournée
    # vers l'axe — « dedans » à tort (une poitrine à 6 cm d'une tasse levée y entrait de 7 cm). On les mesure comme un
    # cylindre plein : rayon et hauteur du corps, l'axe du modèle (son haut).
    CYLINDERS = {"mug": (0.046, 0.098)}

    def check(self, motion, scene, targets, frames, tolerance=0.006):
        """{(partie, objet): (profondeur cm, image, os)} pour les images demandées, sur les objets `targets`."""
        import numpy as np

        out = {}
        static = not callable(scene.chair) and not scene.held and not scene.moves
        trees = {}
        boxes = {}
        for f in frames:
            motion.pose(f)
            scene.apply(f)
            if not static or not trees:
                trees = {oid: self.tree(meshes(load(oid))) for oid in targets}
                cyl_frames = {}
                for oid in targets:
                    if oid in self.CYLINDERS:
                        root = load(oid)
                        pts = [o.matrix_world @ v.co for o in meshes(root) for v in o.data.vertices]
                        axis = (root.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
                        low = min(q.dot(axis) for q in pts)
                        bottom = [q for q in pts if q.dot(axis) < low + 0.004]
                        cyl_frames[oid] = (sum(bottom, Vector()) / len(bottom), axis)
                for oid in targets:
                    if oid in self.HEIGHTFIELD:
                        pts = [o.matrix_world @ Vector(c) for o in meshes(load(oid)) for c in o.bound_box]
                        boxes[oid] = (min(q.x for q in pts), max(q.x for q in pts), min(q.y for q in pts),
                                      max(q.y for q in pts), min(q.z for q in pts), max(q.z for q in pts))
            deps = bpy.context.evaluated_depsgraph_get()
            for obj, own in zip(self.objs, self.owner):
                ev = obj.evaluated_get(deps)
                me = ev.to_mesh()
                co = np.empty(len(me.vertices) * 3)
                me.vertices.foreach_get("co", co)
                ev.to_mesh_clear()
                mw = np.array(obj.matrix_world)
                co = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
                for i in range(0, len(co), 2):
                    part = self.part_of(own[i])
                    if part is None:
                        continue
                    p = Vector(co[i])
                    for oid, tree in trees.items():
                        if oid in self.CYLINDERS:
                            r, hgt = self.CYLINDERS[oid]
                            base, axis = cyl_frames[oid]
                            v = p - base
                            along = v.dot(axis)
                            if not (0.0 <= along <= hgt):
                                continue
                            radial = (v - axis * along).length
                            if radial >= r - tolerance:
                                continue
                            dist = r - radial
                        elif oid in boxes:
                            x0, x1, y0, y1, z0, z1 = boxes[oid]
                            if not (x0 <= p.x <= x1 and y0 <= p.y <= y1 and z0 - 0.005 <= p.z <= z1):
                                continue
                            loc, _, _, _ = tree.ray_cast(Vector((p.x, p.y, z1 + 0.05)), Vector((0.0, 0.0, -1.0)), 0.3)
                            if loc is None or p.z >= loc.z - tolerance:
                                continue
                            dist = loc.z - p.z
                        else:
                            loc, nor, _, dist = tree.find_nearest(p, 0.08)
                            if loc is None or (p - loc).dot(nor) >= -tolerance:
                                continue
                        key = (part, oid)
                        if key not in out or dist * 100 > out[key][0]:
                            out[key] = (round(dist * 100, 1), f, own[i], tuple(round(v, 3) for v in p))
        return out


def report(found, ignore=()):
    """Les contacts, une ligne par (partie, objet), du plus profond au moins profond."""
    rows = sorted(((k, v) for k, v in found.items() if k not in ignore), key=lambda kv: -kv[1][0])
    return [f"{part} dans {oid} : {depth} cm (image {f}, {bone}, en {at})" for (part, oid), (depth, f, bone, at) in rows]


# --- rendus ------------------------------------------------------------------------------------------------------------
def render_sheet(motion, scene, name, views, picks, focus, size=(360, 300), lens=40):
    """Une planche (previews/<nom>.png) : une rangée par vue, une colonne par image choisie, le vrai décor posé."""
    import numpy as np

    bscene = bpy.context.scene
    cam = bpy.data.objects.get("AtelierCam")
    if cam is None:
        cam = bpy.data.objects.new("AtelierCam", bpy.data.cameras.new("AtelierCam"))
        bscene.collection.objects.link(cam)
    cam.data.lens = lens
    cam.data.clip_start = 0.02
    bscene.camera = cam
    bscene.render.engine = "BLENDER_WORKBENCH"
    bscene.display.shading.light = "STUDIO"
    bscene.display.shading.color_type = "MATERIAL"
    bscene.display.shading.show_cavity = True
    bscene.render.resolution_x, bscene.render.resolution_y = size
    bscene.render.resolution_percentage = 100
    bscene.render.image_settings.file_format = "PNG"
    folder = al.PREVIEWS / name
    folder.mkdir(parents=True, exist_ok=True)
    motion.to_action()
    scene.key(len(motion.frames))
    tiles = []
    for view, offset in views:
        row = []
        for f in picks:
            bscene.frame_set(f)
            target = Vector(focus)
            cam.location = target + Vector(offset)
            cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
            path = folder / f"{view}_{f:04d}.png"
            bscene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            img = bpy.data.images.load(str(path))
            px = np.array(img.pixels[:], dtype=np.float32).reshape(size[1], size[0], 4)
            bpy.data.images.remove(img)
            row.append(px)
        tiles.append(np.concatenate(row, axis=1))
    sheet = np.concatenate(tiles[::-1], axis=0)
    out = bpy.data.images.new(f"planche_{name}", sheet.shape[1], sheet.shape[0], alpha=True)
    out.pixels = sheet.ravel()
    out.filepath_raw = str(al.PREVIEWS / f"{name}.png")
    out.file_format = "PNG"
    out.save()
    bpy.data.images.remove(out)
    return al.PREVIEWS / f"{name}.png"
