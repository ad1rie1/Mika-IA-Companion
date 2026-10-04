# Atelier d'animation de Mika — bibliothèque commune (Blender 5.x, module VRM « blender_org.vrm »).
#
# Les animations ne sont plus corrigées en direct dans Unity : elles sont adaptées ici, une fois, sur le squelette de
# Mika (son VRM), puis exportées os seuls pour Unity. Ce module rassemble ce que les scripts de l'atelier partagent :
#   - charger Mika (le VRM de l'acheteur, jamais versionné) et l'habiller d'une tenue de répétition — sans la veste,
#     la jupe ni le haut, le corps couvert d'une combinaison unie et mate — pour juger les articulations sur les rendus ;
#   - les correspondances humanoïdes : Mika (table du VRM), Mixamo, CMU (rig de mocap_unity.py) ;
#   - le transfert de mouvement (retarget) os par os.
#
# Transfert : les deux squelettes ont une pose T comme pose de repos. Pour chaque os humanoïde et chaque image, on
# prend le changement d'orientation de l'os source par rapport à sa pose T, en espace monde, et on l'applique à l'os
# de Mika depuis sa propre pose T : le rouli des os, leurs axes locaux et leurs longueurs n'entrent pas en compte.
# Les os qu'une seule des deux tables connaît suivent leur parent. Le déplacement des hanches est mis à l'échelle de
# ses jambes (cuisse + tibia), pas de ses hanches : c'est la longueur de jambe qui fait la longueur du pas.
#
# Utilisation : `import atelier_lib as al` (le dossier de ce fichier dans sys.path), depuis Blender.
import math
import os
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

REPO = Path(__file__).resolve().parents[4]
AVATAR = REPO / "frontend/Unity/Mika/Assets/Mika/Art/Avatars/default.vrm"
WORKDIR = REPO / "frontend/Unity/ArtSource/atelier"
RIG_BLEND = WORKDIR / "mika_rig.blend"

# Ce que la tenue de répétition retire (les vêtements amples) et la combinaison qui couvre le corps.
LOOSE_CLOTHES = ("ClothCoat", "ClothSkirt", "ClothShirt", "ClothUnder", "ClothNecklace")
SUIT_NAME = "Combinaison de répétition"
SUIT_COLOR = (0.33, 0.38, 0.46, 1.0)

FINGERS = {"Thumb": "Thumb", "Index": "Index", "Middle": "Middle", "Ring": "Ring", "Pinky": "Little"}


# --- Mika ---------------------------------------------------------------------------------------------------------
def import_mika(path=AVATAR):
    """Importe le VRM (la licence de l'acheteur est confirmée d'avance) et rend son armature."""
    os.environ["BLENDER_VRM_AUTOMATIC_LICENSE_CONFIRMATION"] = "true"
    before = set(bpy.data.objects)
    wm = bpy.context.window_manager
    # L'importeur glTF veut une fenêtre ; en session graphique on lui prête la première.
    if wm.windows:
        win = wm.windows[0]
        area = next((a for a in win.screen.areas if a.type == "VIEW_3D"), win.screen.areas[0])
        with bpy.context.temp_override(window=win, screen=win.screen, area=area):
            bpy.ops.import_scene.vrm(filepath=str(path))
    else:
        bpy.ops.import_scene.vrm(filepath=str(path))
    new = [o for o in bpy.data.objects if o not in before]
    arm = next(o for o in new if o.type == "ARMATURE")
    arm.name = "Mika"
    for o in new:
        if o.type == "EMPTY":
            o.hide_set(True)
            o.hide_render = True
    free_hips(arm)
    return arm


def free_hips(arm):
    """
    Les hanches du VRM sont « connectées » à un os racine : Blender ignore alors leur déplacement (ni avance, ni
    balancement). On les détache, sur cette copie de travail seulement — l'export écrit des positions absolues.
    """
    hips = arm.data.bones.get(vrm_map(arm)["hips"])
    if hips is None or not hips.use_connect:
        return
    view_layer = bpy.context.view_layer
    previous = view_layer.objects.active
    view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    arm.data.edit_bones[hips.name].use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    view_layer.objects.active = previous


def rehearsal(on=True):
    """La tenue de répétition : vêtements amples masqués, combinaison unie sur le corps (Body2)."""
    for name in LOOSE_CLOTHES:
        o = bpy.data.objects.get(name)
        if o:
            o.hide_set(on)
            o.hide_render = on
    suit = bpy.data.materials.get(SUIT_NAME)
    if suit is None:
        suit = bpy.data.materials.new(SUIT_NAME)
        suit.use_nodes = True
        bsdf = next(n for n in suit.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        bsdf.inputs["Base Color"].default_value = SUIT_COLOR
        bsdf.inputs["Roughness"].default_value = 0.75
        suit.diffuse_color = SUIT_COLOR
    body = bpy.data.objects.get("Body2")
    if body and on:
        for i in range(len(body.data.materials)):
            body.data.materials[i] = suit


def mika_armature():
    return bpy.data.objects.get("Mika") or next(o for o in bpy.data.objects if o.type == "ARMATURE" and hasattr(o.data, "vrm_addon_extension"))


# --- correspondances humanoïdes ---------------------------------------------------------------------------------------
def vrm_map(arm):
    """
    Os humanoïde (nom VRM 0.x, « leftUpperLeg ») → os de l'armature de Mika. Lu sur le module VRM quand il est là ;
    sinon (Blender sans interface ne le charge pas) sur la copie qu'en garde l'armature (`mika_humanoid`).
    """
    import json

    ext = getattr(arm.data, "vrm_addon_extension", None)
    if ext is not None:
        mapping = {b.bone: b.node.bone_name for b in ext.vrm0.humanoid.human_bones if b.node.bone_name}
        if mapping:
            arm.data["mika_humanoid"] = json.dumps(mapping)
            return mapping
    return json.loads(arm.data["mika_humanoid"])


def mixamo_map(prefix="mixamorig:"):
    m = {"hips": "Hips", "spine": "Spine", "chest": "Spine1", "upperChest": "Spine2", "neck": "Neck", "head": "Head"}
    for side, s in (("left", "Left"), ("right", "Right")):
        m.update({f"{side}Shoulder": f"{s}Shoulder", f"{side}UpperArm": f"{s}Arm", f"{side}LowerArm": f"{s}ForeArm",
                  f"{side}Hand": f"{s}Hand", f"{side}UpperLeg": f"{s}UpLeg", f"{side}LowerLeg": f"{s}Leg",
                  f"{side}Foot": f"{s}Foot", f"{side}Toes": f"{s}ToeBase"})
        for src, dst in FINGERS.items():
            for i, part in enumerate(("Proximal", "Intermediate", "Distal"), 1):
                m[f"{side}{dst}{part}"] = f"{s}Hand{src}{i}"
    return {k: prefix + v for k, v in m.items()}


def cmu_map():
    """Le rig de mocap_unity.py (noms du BVH de cgspeed). Les doigts CMU sont trop pauvres : ils restent au repos."""
    m = {"hips": "Hips", "spine": "LowerBack", "chest": "Spine", "upperChest": "Spine1", "neck": "Neck", "head": "Head"}
    for side, s in (("left", "Left"), ("right", "Right")):
        m.update({f"{side}Shoulder": f"{s}Shoulder", f"{side}UpperArm": f"{s}Arm", f"{side}LowerArm": f"{s}ForeArm",
                  f"{side}Hand": f"{s}Hand", f"{side}UpperLeg": f"{s}UpLeg", f"{side}LowerLeg": f"{s}Leg",
                  f"{side}Foot": f"{s}Foot", f"{side}Toes": f"{s}ToeBase"})
    return m


def source_map(arm):
    names = {b.name for b in arm.data.bones}
    if "mixamorig:Hips" in names:
        return mixamo_map()
    if "Hips" in names and "LowerBack" in names:
        return cmu_map()
    if "Hips" in names:
        return mixamo_map(prefix="")
    raise ValueError(f"squelette source inconnu : {arm.name}")


# --- outils ---------------------------------------------------------------------------------------------------------
def rot(m):
    """La rotation d'une matrice, échelle retirée (les FBX Mixamo arrivent à l'échelle 0,01)."""
    return m.to_3x3().normalized().to_quaternion()


def bfs(arm):
    out, todo = [], [b for b in arm.data.bones if b.parent is None]
    while todo:
        b = todo.pop(0)
        out.append(b)
        todo.extend(b.children)
    return out


def leg_length(arm, hmap):
    w = arm.matrix_world
    bones = arm.data.bones
    hip = w @ bones[hmap["leftUpperLeg"]].head_local
    knee = w @ bones[hmap["leftLowerLeg"]].head_local
    ankle = w @ bones[hmap["leftFoot"]].head_local
    return (knee - hip).length + (ankle - knee).length


def import_fbx(path):
    """
    Importe un FBX d'animation et rend son armature (le reste de l'import est supprimé). Les os de bout de chaîne
    sont gardés : dans les prises CMU, la tête et les orteils en sont — ignorés, la tête de Mika suivait le bas du cou
    de l'acteur (celui de 113 est tourné de 40° de côté, que le haut du cou et la tête rattrapent : elle penchait la
    tête de 37° en attendant et assise).
    """
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(path), automatic_bone_orientation=False, ignore_leaf_bones=False)
    new = [o for o in bpy.data.objects if o not in before]
    arm = next(o for o in new if o.type == "ARMATURE")
    for o in new:
        if o is not arm:
            bpy.data.objects.remove(o, do_unlink=True)
    return arm


# --- le mouvement ---------------------------------------------------------------------------------------------------
class Rig:
    """
    Le squelette de Mika tel que l'atelier le manipule : sa pose T (orientation et position de repos de chaque os, en
    espace monde) et la cinématique directe d'un mouvement exprimé en changements d'orientation.
    """

    def __init__(self, arm):
        self.arm = arm
        self.hmap = {h: n for h, n in vrm_map(arm).items() if n in arm.data.bones}
        self.human_of = {n: h for h, n in self.hmap.items()}
        self.order = bfs(arm)
        self.world = arm.matrix_world.copy()
        self.rel = {b.name: (b.parent.matrix_local.inverted() @ b.matrix_local) if b.parent else b.matrix_local.copy()
                    for b in self.order}
        self.rest = {h: rot(self.world @ arm.data.bones[n].matrix_local) for h, n in self.hmap.items()}
        self.rest_pos = {h: self.world @ arm.data.bones[n].head_local for h, n in self.hmap.items()}

    def fk(self, frame):
        """Matrices monde de tous les os pour une image {"hips": position monde, "d": {os humanoïde: Δ monde}}."""
        out = {}
        for b in self.order:
            parent = out[b.parent.name] if b.parent else self.world
            inherited = parent @ self.rel[b.name]
            h = self.human_of.get(b.name)
            if h is not None and h in frame["d"]:
                pos = frame["hips"] if h == "hips" else inherited.translation
                out[b.name] = Matrix.Translation(pos) @ (frame["d"][h] @ self.rest[h]).to_matrix().to_4x4()
            else:
                out[b.name] = inherited
        return out

    def joints(self, frame, humans):
        pose = self.fk(frame)
        return {h: pose[self.hmap[h]].translation.copy() for h in humans}


class Motion:
    """Un mouvement de Mika : une image = position monde des hanches + changement d'orientation (monde) de chaque os."""

    def __init__(self, rig, name, frames, loop=False, travel=False, fps=30, curves=None):
        self.rig, self.name, self.frames = rig, name, frames
        self.loop, self.travel, self.fps = loop, travel, fps
        # Des courbes du geste, une valeur par image, qu'Unity reçoit en paramètres de l'Animator : la chaise que le
        # geste fait pivoter et rouler (« ChairYaw », « ChairRoll », 0 → 1), les mains posées sur le bureau (« HandsOnDesk »),
        # l'objet dans la main (« Hold »). Le jeu y synchronise ce que le geste déplace : rien ne bouge tout seul.
        self.curves = curves or {}

    def copy_frames(self):
        return [{"hips": f["hips"].copy(), "d": {h: q.copy() for h, q in f["d"].items()}} for f in self.frames]

    # --- vers Blender (aperçu, rendus) et vers Unity ---------------------------------------------------------------
    def explicit(self):
        """
        Chaque os humanoïde porte son orientation monde à chaque image (comme après un export puis une relecture) : un
        os absent de l'image héritait de son parent, et une IK posée ensuite (two_bone) ne déplaçait pas ce qu'il porte.
        """
        humans = [h for h in self.rig.hmap]
        for i, frame in enumerate(self.frames):
            pose = self.rig.fk(frame)
            d = {h: rot(pose[self.rig.hmap[h]]) @ self.rig.rest[h].inverted() for h in humans}
            self.frames[i] = {"hips": pose[self.rig.hmap["hips"]].translation.copy(), "d": d}

    def to_action(self):
        """L'action de l'armature de Mika pour ce mouvement (clés sur les os humanoïdes), images 0..N-1."""
        rig, arm = self.rig, self.rig.arm
        arm.animation_data_create()
        old = bpy.data.actions.get(self.name)
        if old is not None:
            bpy.data.actions.remove(old)
        action = bpy.data.actions.new(self.name)
        arm.animation_data.action = action
        for pb in arm.pose.bones:
            pb.rotation_mode = "QUATERNION"
            pb.matrix_basis = Matrix.Identity(4)
        keyed = [b.name for b in rig.order if b.name in rig.human_of]
        hips_name = rig.hmap["hips"]
        for i, frame in enumerate(self.frames):
            pose = rig.fk(frame)
            for n in keyed:
                b = arm.data.bones[n]
                parent = pose[b.parent.name] if b.parent else rig.world
                pb = arm.pose.bones[n]
                pb.matrix_basis = rig.rel[n].inverted() @ parent.inverted() @ pose[n]
                pb.keyframe_insert("rotation_quaternion", frame=i, group=n)
                if n == hips_name:
                    pb.keyframe_insert("location", frame=i, group=n)
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 0, len(self.frames) - 1
        scene.render.fps = self.fps
        return action

    def pose(self, i):
        """Pose l'armature sur l'image i, sans clé (pour mesurer sur le maillage déformé)."""
        rig, arm = self.rig, self.rig.arm
        if arm.animation_data is not None:
            arm.animation_data.action = None
        pose = rig.fk(self.frames[i])
        for b in rig.order:
            if b.name not in rig.human_of:
                continue
            parent = pose[b.parent.name] if b.parent else rig.world
            pb = arm.pose.bones[b.name]
            pb.rotation_mode = "QUATERNION"
            pb.matrix_basis = rig.rel[b.name].inverted() @ parent.inverted() @ pose[b.name]
        bpy.context.view_layer.update()

    def export(self, note=""):
        """`motions/<nom>.json.gz` pour Unity (Editor/Animation/AtelierImporter.cs)."""
        import gzip
        import json

        rig = self.rig
        human = sorted(rig.hmap, key=lambda h: [b.name for b in rig.order].index(rig.hmap[h]))
        rest = {h: {"p": [round(v, 5) for v in rig.rest_pos[h]], "q": [round(v, 6) for v in rig.rest[h]]} for h in human}
        rows = []
        for frame in self.frames:
            pose = rig.fk(frame)
            row = [round(v, 5) for v in pose[rig.hmap["hips"]].translation]
            for h in human:
                row.extend(round(v, 6) for v in rot(pose[rig.hmap[h]]))
            rows.append(row)
        MOTIONS.mkdir(parents=True, exist_ok=True)
        data = {"name": self.name, "fps": self.fps, "loop": self.loop, "travel": self.travel, "note": note,
                "bones": human, "rest": rest, "frames": rows}
        if self.curves:
            data["curves"] = {k: [round(float(v), 4) for v in vs] for k, vs in self.curves.items()}
        path = MOTIONS / f"{self.name}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        return path


MOTIONS = WORKDIR / "motions"


# --- transfert ------------------------------------------------------------------------------------------------------
def retarget(src, rig, name, smap=None, frames=None, loop=False, travel=False):
    """
    Le mouvement de l'action de `src` (Mixamo, CMU) transféré sur Mika : pour chaque os humanoïde, le changement
    d'orientation par rapport à la pose T, en espace monde ; les hanches déplacées à l'échelle de ses jambes.
    """
    smap = smap or source_map(src)
    scene = bpy.context.scene
    act = src.animation_data.action
    f0, f1 = (int(round(act.frame_range[0])), int(round(act.frame_range[1]))) if frames is None else frames
    sw = src.matrix_world
    common = [h for h in smap if h in rig.hmap and smap[h] in src.data.bones]
    srest = {h: rot(sw @ src.data.bones[smap[h]].matrix_local) for h in common}
    ratio = leg_length(rig.arm, rig.hmap) / leg_length(src, smap)
    src_hips_rest = sw @ src.data.bones[smap["hips"]].head_local
    out = []
    for f in range(f0, f1 + 1):
        scene.frame_set(f)
        d = {h: rot(sw @ src.pose.bones[smap[h]].matrix) @ srest[h].inverted() for h in common}
        hips = rig.rest_pos["hips"] + (sw @ src.pose.bones[smap["hips"]].head - src_hips_rest) * ratio
        out.append({"hips": hips, "d": d})
    motion = Motion(rig, name, out, loop=loop, travel=travel)
    motion.ratio = ratio
    return motion


# --- semelles et appuis ---------------------------------------------------------------------------------------------
class Soles:
    """
    Les semelles de ses chaussures : les sommets du dessous de chaque chaussure, au repos, rattachés à l'os qui les
    porte (cheville ou orteils). À chaque image, le point le plus bas de chaque pied est celui qui touche le sol.
    """

    def __init__(self, rig, shoes="ClothShoes", depth=0.012):
        obj = bpy.data.objects[shoes]
        mesh = obj.data
        groups = {g.index: g.name for g in obj.vertex_groups}
        mw = obj.matrix_world
        verts = [(v, mw @ v.co) for v in mesh.vertices]
        low = min(p.z for _, p in verts)
        names = {"left": (rig.hmap["leftFoot"], rig.hmap.get("leftToes")), "right": (rig.hmap["rightFoot"], rig.hmap.get("rightToes"))}
        rest_world = {b.name: rig.world @ b.matrix_local for b in rig.arm.data.bones}
        self.points = {"left": [], "right": []}
        for v, p in verts:
            if p.z > low + depth:
                continue
            weights = {groups[g.group]: g.weight for g in v.groups if g.group in groups}
            for side, (foot, toes) in names.items():
                bone = max((n for n in (foot, toes) if n in weights), key=lambda n: weights[n], default=None)
                if bone is not None:
                    self.points[side].append((bone, rest_world[bone].inverted() @ p))
        self.rig = rig

    def lowest(self, pose, side):
        """Hauteur (z monde) du point le plus bas de la semelle de ce pied dans cette pose."""
        return min((pose[bone] @ local).z for bone, local in self.points[side])


def contacts(motion, soles, side, height=0.015, speed=0.25):
    """Images où ce pied est en appui : semelle à moins de `height` du sol et cheville presque immobile."""
    rig = motion.rig
    ankle = rig.hmap[f"{side}Foot"]
    poses = [rig.fk(f) for f in motion.frames]
    lows = [soles.lowest(p, side) for p in poses]
    pos = [p[ankle].translation for p in poses]
    n = len(poses)
    dt = 1.0 / motion.fps
    out = []
    for i in range(n):
        a, b = pos[max(0, i - 1)], pos[min(n - 1, i + 1)]
        v = ((b - a).xy.length) / (dt * (min(n - 1, i + 1) - max(0, i - 1)) or 1)
        out.append(lows[i] < height and v < speed)
    return out, lows


def ground(motion, soles, contact_sides=("left", "right")):
    """Pose le mouvement au sol : la semelle la plus basse des appuis à 0 (médiane), hanches décalées d'autant."""
    rig = motion.rig
    lows = []
    for f in motion.frames:
        pose = rig.fk(f)
        lows.append(min(soles.lowest(pose, s) for s in contact_sides))
    lows_sorted = sorted(lows)
    floor = lows_sorted[len(lows_sorted) // 10]  # le dixième le plus bas : les appuis, pas les sauts
    for f in motion.frames:
        f["hips"].z -= floor
    return floor


def intervals(flags, loop):
    """Les plages [début, fin] où `flags` est vrai (une plage qui chevauche la fin d'une boucle est recousue)."""
    n = len(flags)
    spans, start = [], None
    for i, on in enumerate(flags):
        if on and start is None:
            start = i
        if not on and start is not None:
            spans.append([start, i - 1])
            start = None
    if start is not None:
        spans.append([start, n - 1])
    if loop and len(spans) > 1 and spans[0][0] == 0 and spans[-1][1] == n - 1:
        first = spans.pop(0)
        spans[-1] = [spans[-1][0], first[1] + n]
    return spans


def two_bone(frame, rig, side, target, limb="leg"):
    """
    Amène la cheville (ou le poignet, `limb="arm"`) de ce côté sur `target` (monde) en tournant les deux segments ; le
    pied (la main) garde son orientation monde. Le genou (le coude) reste dans le plan où il plie.
    """
    up, lo, ft = (f"{side}UpperLeg", f"{side}LowerLeg", f"{side}Foot") if limb == "leg" else \
        (f"{side}UpperArm", f"{side}LowerArm", f"{side}Hand")
    j = rig.joints(frame, (up, lo, ft))
    a, b, c = j[up], j[lo], j[ft]
    lab, lcb = (b - a).length, (c - b).length
    lat = min(max((target - a).length, abs(lab - lcb) + 1e-4), lab + lcb - 1e-4)
    n = (a - b).cross(c - b)
    if n.length > 1e-6:
        n.normalize()
        cos_want = (lab * lab + lcb * lcb - lat * lat) / (2 * lab * lcb)
        want = math.acos(max(-1.0, min(1.0, cos_want)))
        now = (a - b).angle(c - b)
        bend = Quaternion(n, want - now)
        frame["d"][lo] = bend @ frame["d"][lo]
        c = b + bend @ (c - b)
    swing = (c - a).rotation_difference(target - a)
    frame["d"][up] = swing @ frame["d"][up]
    frame["d"][lo] = swing @ frame["d"][lo]


def raise_heels(motion, rig, height, weights):
    """
    Les talons levés de `height` (m) × le poids de l'image (0..1), la pointe du pied (l'articulation des orteils) restant
    où elle est : le pied pivote sur elle, les orteils restent à plat, la jambe suit (two_bone). Assise sur un siège un
    peu haut pour elle, c'est ainsi que ses cuisses reposent à plat sur le coussin au lieu d'en traverser le bord.
    """
    for frame, w in zip(motion.frames, weights):
        if w <= 0.0:
            continue
        j = rig.joints(frame, ("leftFoot", "rightFoot", "leftToes", "rightToes"))
        for side in ("left", "right"):
            ankle, ball = j[f"{side}Foot"], j[f"{side}Toes"]
            along = ball - ankle
            if along.length < 1e-4:
                continue
            axis = along.cross(Vector((0.0, 0.0, 1.0)))
            if axis.length < 1e-6:
                continue
            angle = math.asin(min(0.9, height * w / along.length))
            turn = Quaternion(axis.normalized(), -angle)
            frame["d"][f"{side}Foot"] = turn @ frame["d"][f"{side}Foot"]
            two_bone(frame, rig, side, ball + turn @ (ankle - ball))


def feet_ahead(motion, rig, ahead, seated):
    """
    Les pieds `ahead` m plus en avant (elle regarde −Y) à chaque image, sans changer leur orientation ; les hanches
    suivent là où elle est debout (poids `seated` : 0 debout → 1 assise), si bien que l'assise ne bouge pas et que,
    debout devant le siège, elle se tient d'autant plus loin de son bord.
    """
    shift = Vector((0.0, -ahead, 0.0))
    for frame, s in zip(motion.frames, seated):
        frame["hips"] += shift * (1.0 - s)
        j = rig.joints(frame, ("leftFoot", "rightFoot"))
        for side in ("left", "right"):
            two_bone(frame, rig, side, j[f"{side}Foot"] + shift * s)


def lock_feet(motion, soles, flags_by_side, blend=3, softness=0.004):
    """
    Les pieds en appui ne glissent plus : sur chaque plage d'appui, ce qui touche le sol reste où il s'est posé. Pas la
    cheville : quand le talon se lève (l'attente joyeuse sautille sur l'avant-pied), un pied tenu par la cheville
    pivotait autour d'elle — tout le pied bougeait, la pointe reculait. On tient les points de la semelle : à chaque
    image, les plus bas (talon à l'attaque, avant-pied quand le talon monte, toute la semelle à plat — un minimum
    adouci sur `softness` m) retrouvent la place qu'ils ont quand le pied est à plat au milieu de l'appui, et la
    cheville se place en conséquence ; la semelle la plus basse est posée sur le sol. Entrée et sortie fondues.
    """
    rig = motion.rig
    # Une boucle : la dernière image répète la première, avancée d'un cycle. On travaille sur la période (sans elle),
    # et une plage d'appui qui chevauche le raccord est suivie dans le cycle suivant : ses images d'après le raccord
    # sont, en monde, en avance de `travel`. Sans ce décalage, l'ancre mélangeait deux cycles et la cheville d'une
    # image était tirée d'un pas en arrière — Unity (« Loop Pose ») étalait ensuite l'écart sur tout le cycle : un
    # coup de pied en avant à chaque pas gauche.
    period = len(motion.frames) - 1 if motion.loop else len(motion.frames)
    travel = motion.frames[-1]["hips"] - motion.frames[0]["hips"] if motion.loop else Vector()
    travel = Vector((travel.x, travel.y, 0.0))
    for side, flags in flags_by_side.items():
        ankle = rig.hmap[f"{side}Foot"]
        points = soles.points[side][::3]  # un point sur trois suffit (702 par semelle)
        spans = intervals(flags[:period], motion.loop)
        poses = [rig.fk(f) for f in motion.frames[:period]]

        def sole(pose):
            return [pose[b] @ local for b, local in points]

        for s, e in spans:
            laps = list(range(s, e + 1))
            # La référence : l'image la plus à plat de la moitié centrale de l'appui.
            middle = laps[len(laps) // 4: max(len(laps) // 4 + 1, (3 * len(laps)) // 4)]
            ref = min(middle, key=lambda i: (lambda zs: max(zs) - min(zs))([p.z for p in sole(poses[i % period])]))
            anchors = [p + travel * (ref // period) for p in sole(poses[ref % period])]
            # Un pied posé toute la boucle durant ne se relâche pas aux bouts : il n'y a ni entrée ni sortie d'appui.
            whole = motion.loop and len(laps) >= period
            # Ni entrée au début d'un clip qui commence pied posé, ni sortie à la fin d'un clip qui finit pied posé.
            open_start = not motion.loop and s == 0
            open_end = not motion.loop and e >= period - 1
            for k, i in enumerate(laps):
                j = i % period
                w_in = 1.0 if open_start else (k + 1) / (blend + 1)
                w_out = 1.0 if open_end else (len(laps) - k) / (blend + 1)
                w = 1.0 if whole else min(1.0, w_in, w_out)
                pose = rig.fk(motion.frames[j])
                pts = sole(pose)
                low = min(p.z for p in pts)
                weights = [math.exp(-(p.z - low) / softness) for p in pts]
                total = sum(weights)
                shift = travel * (i // period)
                dx = sum(wt * (a.x - shift.x - p.x) for wt, a, p in zip(weights, anchors, pts)) / total
                dy = sum(wt * (a.y - shift.y - p.y) for wt, a, p in zip(weights, anchors, pts)) / total
                cur = pose[ankle].translation
                tgt = Vector((cur.x + dx, cur.y + dy, cur.z - low))
                two_bone(motion.frames[j], rig, side, cur.lerp(tgt, w))


def close_loop(motion):
    """La dernière image d'une boucle redevient la première, avancée d'un cycle (hanches) — orientations identiques."""
    first, last = motion.frames[0], motion.frames[-1]
    travel = last["hips"] - first["hips"]
    motion.frames[-1] = {"hips": first["hips"] + travel, "d": {h: q.copy() for h, q in first["d"].items()}}


def loop_gap(motion):
    """Le plus grand écart d'orientation (degrés) entre la première et la dernière image d'une boucle, et l'os."""
    first, last = motion.frames[0]["d"], motion.frames[-1]["d"]
    worst = max(((math.degrees(first[h].rotation_difference(last[h]).angle), h) for h in first if h in last),
                default=(0.0, ""))
    return worst


# --- miroir ---------------------------------------------------------------------------------------------------------
def mirror_name(h):
    return h.replace("left", "@").replace("right", "left").replace("@", "right")


def mirror_frame(frame, axis_x=0.0):
    """L'image en miroir gauche/droite (plan x = axis_x en espace monde de Blender : elle regarde -Y)."""
    d = {}
    for h, q in frame["d"].items():
        d[mirror_name(h)] = Quaternion((q.w, q.x, -q.y, -q.z))
    hips = frame["hips"].copy()
    hips.x = 2 * axis_x - hips.x
    return {"hips": hips, "d": d}


# --- posture et cycles ----------------------------------------------------------------------------------------------
def lateral_axis(frame, rig):
    """L'axe gauche-droite du bassin dans cette image (monde)."""
    q = frame["d"].get("hips", Quaternion())
    return (q @ rig.rest["hips"]) @ Vector((1, 0, 0))


def straighten(motion, bones):
    """
    Redresse des os autour de l'axe gauche-droite du bassin : `bones` = {os humanoïde: degrés} (négatif = vers
    l'arrière). Les os enfants gardent leur orientation (le regard ne change pas), seule leur position suit.
    """
    for frame in motion.frames:
        axis = lateral_axis(frame, motion.rig)
        for h, deg in bones.items():
            if h in frame["d"]:
                frame["d"][h] = Quaternion(axis, math.radians(deg)) @ frame["d"][h]


def symmetric_cycle(motion, soles, side=None):
    """
    Un cycle de marche symétrique : la moitié du cycle qui commence à la pose du pied `side` (appui de ce pied et
    balancement de l'autre), suivie de son miroir (appui de l'autre pied, balancement du premier). Une prise qui
    boite — un pas long, un pas court, un pied qui glisse — devient régulière sans rien inventer. Sans `side`, on prend
    le pied dont l'appui est le plus long et le plus immobile. La dernière image d'une boucle répète la première.
    """
    frames = motion.frames[:-1] if motion.loop else motion.frames
    n = len(frames)
    h = n // 2
    if side is None:
        best = None
        for s in ("left", "right"):
            flags, _ = contacts(motion, soles, s)
            score = sum(flags)
            if best is None or score > best[0]:
                best = (score, s)
        side = best[1]
    flags, _ = contacts(motion, soles, side)
    spans = intervals(flags[:n], True)
    start = max(spans, key=lambda sp: sp[1] - sp[0])[0] % n
    travel = motion.frames[-1]["hips"] - motion.frames[0]["hips"] if motion.loop else frames[-1]["hips"] - frames[0]["hips"]
    x0 = sum(f["hips"].x for f in frames) / n
    first = []
    for k in range(h):
        i = start + k
        f = frames[i % n]
        first.append({"hips": f["hips"] + (travel if i >= n else Vector()), "d": {kk: q.copy() for kk, q in f["d"].items()}})
    base = mirror_frame(first[0], axis_x=x0)["hips"]
    second = []
    for f in first:
        m = mirror_frame(f, axis_x=x0)
        m["hips"] = first[0]["hips"] + travel * 0.5 + (m["hips"] - base)
        second.append(m)
    cycle = first + second
    # Les deux jonctions (prise → miroir, miroir → prise au tour suivant) : un bras ne tombe pas pile au même endroit
    # dans la moitié capturée et dans son miroir (l'avant-bras sautait de 27° en une image) — on coud.
    stitch(cycle, h, travel)
    stitch(cycle, 0, travel)
    # La boucle se referme sur la première image, avancée d'un cycle.
    cycle.append({"hips": cycle[0]["hips"] + travel, "d": {kk: q.copy() for kk, q in cycle[0]["d"].items()}})
    motion.frames = cycle
    return side, start


def stitch(cycle, j, travel=None, k=5):
    """
    Coud une jonction d'un cycle (entre les images j-1 et j, circulairement) : pour chaque os, l'écart entre l'image
    j et celle que la vitesse d'avant laissait attendre est réparti à moitié sur les `k` images d'avant, à moitié sur
    les `k` d'après, en fondu. La hauteur des hanches est cousue de même. Les pieds sont replantés ensuite.
    """
    n = len(cycle)
    a1, a0, b0 = cycle[(j - 1) % n], cycle[(j - 2) % n], cycle[j % n]
    for h in b0["d"]:
        if h not in a1["d"] or h not in a0["d"]:
            continue
        expected = (a1["d"][h] @ a0["d"][h].inverted()) @ a1["d"][h]
        err = b0["d"][h] @ expected.inverted()
        if err.w < 0:
            err.negate()
        for i in range(1, k + 1):
            w = 0.5 * (1 - (i - 1) / k)
            before = cycle[(j - i) % n]["d"]
            after = cycle[(j + i - 1) % n]["d"]
            before[h] = Quaternion().slerp(err, w) @ before[h]
            after[h] = Quaternion().slerp(err.inverted(), w) @ after[h]
    za1, za0, zb0 = cycle[(j - 1) % n]["hips"].z, cycle[(j - 2) % n]["hips"].z, cycle[j % n]["hips"].z
    dz = zb0 - (2 * za1 - za0)
    for i in range(1, k + 1):
        w = 0.5 * (1 - (i - 1) / k)
        cycle[(j - i) % n]["hips"].z += dz * w
        cycle[(j + i - 1) % n]["hips"].z -= dz * w


# --- rendus de contrôle -----------------------------------------------------------------------------------------------
PREVIEWS = WORKDIR / "previews"


def render_sheet(motion, name, count=10, size=(300, 400), picks=None, views=None, focus=None):
    """
    Une planche de contrôle (previews/<nom>.png) : `count` images réparties sur le clip, de côté (rangée du haut) et
    de trois quarts avant (rangée du bas), en tenue de répétition, caméra qui suit les hanches.
    """
    import numpy as np

    scene = bpy.context.scene
    rig = motion.rig
    cam = bpy.data.objects.get("AtelierCam")
    if cam is None:
        cam = bpy.data.objects.new("AtelierCam", bpy.data.cameras.new("AtelierCam"))
        scene.collection.objects.link(cam)
    cam.data.lens = 45
    scene.camera = cam
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.render.resolution_x, scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    folder = PREVIEWS / name
    folder.mkdir(parents=True, exist_ok=True)
    n = len(motion.frames)
    picks = picks or [round(i * (n - 1) / max(1, count - 1)) for i in range(count)]
    views = views or (("cote", Vector((2.6, 0.0, 0.0))), ("face", Vector((1.3, -2.2, 0.0))))
    tiles = []
    for view, offset in views:
        row = []
        for f in picks:
            scene.frame_set(f)
            hips = rig.world @ rig.arm.pose.bones[rig.hmap["hips"]].head
            if focus is not None:
                target = Vector(focus)
                cam.location = target + offset
            else:
                cam.location = Vector((hips.x, hips.y, 0.75)) + offset
                target = Vector((hips.x, hips.y, 0.62))
            cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
            path = folder / f"{view}_{f:04d}.png"
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            img = bpy.data.images.load(str(path))
            px = np.array(img.pixels[:], dtype=np.float32).reshape(size[1], size[0], 4)
            bpy.data.images.remove(img)
            row.append(px)
        tiles.append(np.concatenate(row, axis=1))
    sheet = np.concatenate(tiles[::-1], axis=0)  # les pixels Blender partent du bas : la rangée « côté » en haut
    out = bpy.data.images.new(f"planche_{name}", sheet.shape[1], sheet.shape[0], alpha=True)
    out.pixels = sheet.ravel()
    out.filepath_raw = str(PREVIEWS / f"{name}.png")
    out.file_format = "PNG"
    out.save()
    bpy.data.images.remove(out)
    return PREVIEWS / f"{name}.png"


# --- contrôle : ce qu'un mouvement a de faux ------------------------------------------------------------------------
def facing(frame):
    """L'avant horizontal du bassin dans cette image (elle regarde −Y au repos)."""
    v = frame["d"].get("hips", Quaternion()) @ Vector((0.0, -1.0, 0.0))
    v.z = 0.0
    return v.normalized() if v.length > 1e-6 else Vector((0.0, -1.0, 0.0))


def tilt(v, fwd):
    """Inclinaison (degrés) d'un segment par rapport à la verticale : positive vers l'avant."""
    return math.degrees(math.atan2(v.dot(fwd), v.z))


def posture(motion):
    """Inclinaison moyenne et extrêmes du buste (hanches → cou) et du cou (cou → tête), en degrés, vers l'avant."""
    rig = motion.rig
    torso, neck = [], []
    for f in motion.frames:
        j = rig.joints(f, ("hips", "neck", "head"))
        fwd = facing(f)
        torso.append(tilt(j["neck"] - j["hips"], fwd))
        neck.append(tilt(j["head"] - j["neck"], fwd))
    mean = lambda xs: sum(xs) / len(xs)
    return {"buste": round(mean(torso), 1), "buste_ext": [round(min(torso), 1), round(max(torso), 1)],
            "cou": round(mean(neck), 1), "cou_ext": [round(min(neck), 1), round(max(neck), 1)]}


def jumps(motion):
    """Le plus grand changement d'orientation d'un os d'une image à la suivante (degrés), l'os et l'image."""
    worst = (0.0, "", 0)
    for i in range(1, len(motion.frames)):
        a, b = motion.frames[i - 1]["d"], motion.frames[i]["d"]
        for h, q in a.items():
            if h in b:
                ang = math.degrees(q.rotation_difference(b[h]).angle)
                ang = min(ang, 360.0 - ang)
                if ang > worst[0]:
                    worst = (ang, h, i)
    return {"saut": round(worst[0], 1), "os": worst[1], "image": worst[2]}


def loop_report(motion):
    """Raccord d'une boucle : écart d'orientation (degrés) et de position des hanches (cm, hors avance) fin → début."""
    if not motion.loop:
        return {}
    gap, bone = loop_gap(motion)
    d = motion.frames[-1]["hips"] - motion.frames[0]["hips"]
    if not motion.travel:
        hips = d.length * 100
    else:
        hips = abs(d.z) * 100
    return {"raccord": round(gap, 1), "raccord_os": bone, "raccord_hanches_cm": round(hips, 1)}


def feet_report(motion, soles, height=0.03, softness=0.004):
    """
    Les pieds : par pied, glissement maximal d'un appui (cm — ce qui touche le sol, pas la cheville : quand le talon
    monte, la cheville avance normalement de quelques cm alors que l'avant-pied ne bouge pas), enfoncement (semelle
    sous le sol, cm), écart de hauteur pendant l'appui (cm), et les images où aucun pied ne touche.
    """
    rig = motion.rig
    period = len(motion.frames) - 1 if motion.loop else len(motion.frames)
    travel = motion.frames[-1]["hips"] - motion.frames[0]["hips"] if motion.loop else Vector()
    travel = Vector((travel.x, travel.y, 0.0))
    poses = [rig.fk(f) for f in motion.frames[:period]]
    out = {}
    lows_by_side = {}
    for side in ("left", "right"):
        points = soles.points[side][::3]
        sole = [[pose[b] @ local for b, local in points] for pose in poses]
        lows = [min(p.z for p in pts) for pts in sole]
        lows_by_side[side] = [soles.lowest(p, side) for p in poses]
        flags, _ = contacts(motion, soles, side, height=height)
        flags = flags[:period]
        slide, rise = 0.0, 0.0
        for s, e in intervals(flags, motion.loop):
            laps = list(range(s, e + 1))
            if len(laps) < 3:
                continue
            ref = laps[len(laps) // 2]
            anchors = [p + travel * (ref // period) for p in sole[ref % period]]
            for i in laps:
                pts, low = sole[i % period], lows[i % period]
                ws = [math.exp(-(p.z - low) / softness) for p in pts]
                shift = travel * (i // period)
                gap = sum(w * Vector((a.x - shift.x - p.x, a.y - shift.y - p.y)).length
                          for w, a, p in zip(ws, anchors, pts)) / sum(ws)
                slide = max(slide, gap)
            hs = [lows_by_side[side][i % period] for i in laps]
            rise = max(rise, max(hs) - min(hs))
        out[side] = {"appui": sum(flags), "glisse_cm": round(slide * 100, 1),
                     "enfonce_cm": round(-min(0.0, min(lows_by_side[side])) * 100, 1),
                     "hauteur_appui_cm": round(rise * 100, 1)}
    air = sum(1 for i in range(period) if min(lows_by_side["left"][i], lows_by_side["right"][i]) > 0.02)
    out["en_l_air"] = air
    return out


def knees(motion):
    """Genoux en hyperextension : le genou passe derrière la ligne hanche-cheville (cm, vers l'arrière du bassin)."""
    rig = motion.rig
    worst = 0.0
    for f in motion.frames:
        fwd = facing(f)
        for side in ("left", "right"):
            j = rig.joints(f, (f"{side}UpperLeg", f"{side}LowerLeg", f"{side}Foot"))
            a, b, c = j[f"{side}UpperLeg"], j[f"{side}LowerLeg"], j[f"{side}Foot"]
            axis = (c - a).normalized()
            off = (b - a) - axis * (b - a).dot(axis)
            worst = min(worst, off.dot(fwd))
    return {"genou_arriere_cm": round(-worst * 100, 1)}


class Clearance:
    """
    Les avant-bras et les mains qui entrent dans le corps : sur son maillage (Body2) déformé image par image, chaque
    sommet d'avant-bras ou de main est confronté à la surface du tronc, des cuisses et de la tête (sommets dont l'os
    dominant est hanches, colonne, poitrine, cou, tête ou cuisse — une main devant la bouche n'y rentre pas).
    Profondeur maximale (cm) et nombre d'images touchées, par côté.
    """

    TRUNK = {"hips", "spine", "chest", "upperChest", "neck", "head", "leftUpperLeg", "rightUpperLeg"}

    def __init__(self, rig, body="Body2"):
        self.rig = rig
        self.obj = obj = bpy.data.objects[body]
        groups = {g.index: g.name for g in obj.vertex_groups}
        human_of_bone = {}
        for b in rig.arm.data.bones:
            p = b
            while p is not None and p.name not in rig.human_of:
                p = p.parent
            human_of_bone[b.name] = rig.human_of[p.name] if p is not None else None
        owner = []
        for v in obj.data.vertices:
            best = max(v.groups, key=lambda g: g.weight, default=None)
            owner.append(human_of_bone.get(groups.get(best.group)) if best is not None else None)
        self.owner = owner
        self.trunk_polys = [tuple(p.vertices) for p in obj.data.polygons if all(owner[i] in self.TRUNK for i in p.vertices)]
        parts = ("LowerArm", "Hand", "Thumb", "Index", "Middle", "Ring", "Little")
        self.limbs = {side: [i for i, h in enumerate(owner) if h and h.startswith(side) and any(x in h for x in parts)]
                      for side in ("left", "right")}

    def scan(self, motion, frames, tolerance=0.008):
        """
        Pour chaque image demandée et chaque côté, le sommet d'avant-bras ou de main le plus enfoncé dans le tronc :
        {image: {côté: (profondeur, point, normale de la surface, « os dans os »)}} (côtés sans contact absents).
        """
        import numpy as np
        from mathutils.bvhtree import BVHTree

        mw = np.array(self.obj.matrix_world)
        hits = {}
        for f in frames:
            motion.pose(f)
            deps = bpy.context.evaluated_depsgraph_get()
            ev = self.obj.evaluated_get(deps)
            me = ev.to_mesh()
            co = np.empty(len(me.vertices) * 3)
            me.vertices.foreach_get("co", co)
            ev.to_mesh_clear()
            co = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
            tree = BVHTree.FromPolygons([tuple(c) for c in co], self.trunk_polys)
            for side, idx in self.limbs.items():
                best = None
                for i in idx:
                    p = Vector(co[i])
                    loc, nor, poly, dist = tree.find_nearest(p, 0.12)
                    if loc is not None and (p - loc).dot(nor) < -tolerance and (best is None or dist > best[0]):
                        best = (dist, p, nor.normalized(), f"{self.owner[i]} dans {self.owner[self.trunk_polys[poly][0]]}")
                if best is not None:
                    hits.setdefault(f, {})[side] = best
        return hits

    def measure(self, motion, step=3, tolerance=0.008):
        hits = self.scan(motion, range(0, len(motion.frames), step), tolerance)
        out = {s: {"profondeur_cm": 0.0, "images": 0, "pire_image": -1, "ou": "", "point": None} for s in self.limbs}
        for f, by in sorted(hits.items()):
            for side, (depth, point, _, where) in by.items():
                r = out[side]
                r["images"] += 1
                if depth * 100 > r["profondeur_cm"]:
                    r["profondeur_cm"], r["pire_image"], r["ou"] = round(depth * 100, 1), f, where
                    r["point"] = [round(v, 3) for v in point]
        return out


# --- corrections ----------------------------------------------------------------------------------------------------
# Les os fins (doigts, orteils) et les mains : un saut au-delà de `limit` y est un défaut de la prise.
FINGER_PARTS = ("Thumb", "Index", "Middle", "Ring", "Little", "Toes", "Hand")


def _angle(a, b):
    ang = math.degrees(a.rotation_difference(b).angle)
    return min(ang, 360.0 - ang)


def despike(motion, limit=25.0, limit_body=30.0, reach=3):
    """Les sauts repris par passes successives, de plus en plus larges, jusqu'à ce qu'il n'en reste plus."""
    total = 0
    for r in (reach, reach + 2, reach + 4, reach + 7):
        fixed = _despike_pass(motion, limit, limit_body, r)
        total += fixed
        if not fixed:
            break
    return total


def _despike_pass(motion, limit, limit_body, reach):
    """
    Les sauts : un os qui tourne de plus de `limit` degrés d'une image à la suivante (doigts, orteils) ou de plus de
    `limit_body` (le reste) est repris sur ±`reach` images par une interpolation douce entre les images qui encadrent
    le saut. Les doigts Mixamo claquent parfois de 50 à 80° en une image (2 400°/s) : aucune main ne fait ça.
    """
    frames = motion.frames
    n = len(frames)
    fixed = 0
    for h in list(frames[0]["d"].keys()):
        lim = limit if any(x in h for x in FINGER_PARTS) else limit_body
        i = 1
        while i < n:
            a, b = frames[i - 1]["d"].get(h), frames[i]["d"].get(h)
            if a is None or b is None or _angle(a, b) <= lim:
                i += 1
                continue
            s, e = max(0, i - 1 - reach), min(n - 1, i + reach)
            qa, qb = frames[s]["d"][h].copy(), frames[e]["d"][h].copy()
            if qa.dot(qb) < 0:
                qb.negate()
            for k in range(s + 1, e):
                t = (k - s) / (e - s)
                frames[k]["d"][h] = qa.slerp(qb, t * t * (3 - 2 * t))
            fixed += 1
            i = e + 1
    return fixed


def _smooth_vectors(vs, loop, passes=2):
    """Moyenne glissante sur trois images (deux fois) d'une suite de vecteurs (None = nul)."""
    n = len(vs)
    cur = [v.copy() if v is not None else Vector() for v in vs]
    for _ in range(passes):
        nxt = []
        for f in range(n):
            acc = Vector()
            for k, w in ((-1, 0.25), (0, 0.5), (1, 0.25)):
                g = f + k
                if loop:
                    g %= n
                else:
                    g = min(n - 1, max(0, g))
                acc += cur[g] * w
            nxt.append(acc)
        cur = nxt
    return cur


def clear_arms(motion, clearance, margin=0.01, passes=4, spread=6, max_deg=35.0):
    """
    Les avant-bras et les mains hors du corps : à chaque image où un sommet d'avant-bras ou de main est dans le tronc
    ou une cuisse (son corps est plus large que celui de l'acteur, les bras tombaient dedans), le bras s'écarte —
    rotation du bras autour de l'épaule qui pousse le coude le long de la normale de la surface touchée, de la
    profondeur plus `margin`. L'avant-bras et la main gardent leur orientation (ils suivent le coude). La correction
    est un vecteur de rotation par image : son amplitude est étalée sur ±`spread` images (fenêtre en cosinus) pour que
    le bras s'écarte avant le contact et revienne après, sa direction est la moyenne pondérée des contacts voisins, et
    le tout est lissé — pas d'à-coup. Plusieurs passes : chacune mesure ce qui reste. Rend la profondeur restante (cm).
    """
    rig = motion.rig
    n = len(motion.frames)
    period = n - 1 if motion.loop else n
    todo = range(period)
    left = {}
    for _ in range(passes):
        hits = clearance.scan(motion, todo)
        if not hits:
            break
        touched = set()
        for side in ("left", "right"):
            upper, lower = f"{side}UpperArm", f"{side}LowerArm"
            theta, rv = [0.0] * period, [None] * period
            for f, by in hits.items():
                if side not in by:
                    continue
                depth, _, normal, _ = by[side]
                j = rig.joints(motion.frames[f], (upper, lower))
                c = (j[lower] - j[upper]).cross(normal)
                if c.length < 1e-4:
                    continue
                theta[f] = min(math.radians(max_deg), (depth + margin) / c.length)
                rv[f] = c.normalized() * theta[f]
            if not any(theta):
                continue
            corr = [None] * period
            for f in range(period):
                mag, acc = 0.0, Vector()
                for k in range(-spread, spread + 1):
                    g = f + k
                    if motion.loop:
                        g %= period
                    elif g < 0 or g >= period:
                        continue
                    if rv[g] is None:
                        continue
                    w = 0.5 * (1 + math.cos(math.pi * k / (spread + 1)))
                    mag = max(mag, theta[g] * w)
                    acc += rv[g] * w
                if mag > 0 and acc.length > 1e-9:
                    corr[f] = acc.normalized() * mag
            for f, c in enumerate(_smooth_vectors(corr, motion.loop)):
                if c.length > 1e-5:
                    d = motion.frames[f]["d"]
                    d[upper] = Quaternion(c.normalized(), c.length) @ d[upper]
                    touched.add(f)
        if motion.loop:
            close_loop(motion)
        todo = sorted(touched)
    final = clearance.scan(motion, range(period))
    for by in final.values():
        for side, h in by.items():
            left[side] = max(left.get(side, 0.0), round(h[0] * 100, 1))
    return left


def knee_flex(frame, rig, side):
    """Flexion du genou (degrés, 0 = jambe tendue)."""
    j = rig.joints(frame, (f"{side}UpperLeg", f"{side}LowerLeg", f"{side}Foot"))
    a, b, c = j[f"{side}UpperLeg"], j[f"{side}LowerLeg"], j[f"{side}Foot"]
    return 180.0 - math.degrees((a - b).angle(c - b))


def stand_taller(motion, flags_by_side, keep=0.35, floor_deg=6.0, sigma=4.0):
    """
    Debout, les genoux moins pliés : les acteurs Mixamo se tiennent jambes fléchies de 18 à 32° sur la jambe d'appui
    (sur elle, une silhouette accroupie). On ne garde que `keep` de la flexion au-delà de `floor_deg` sur la jambe
    d'appui (la plus tendue des jambes posées) en montant les hanches ; la montée est lissée dans le temps (σ en
    images) pour garder le balancement du clip. Les pieds posés sont ensuite replantés par `lock_feet` (appeler avec
    les appuis mesurés AVANT, la semelle étant montée avec les hanches). Rend la montée moyenne (cm).
    """
    rig = motion.rig
    n = len(motion.frames)
    period = n - 1 if motion.loop else n
    lifts = []
    for f in range(period):
        frame = motion.frames[f]
        best = None
        for side, flags in flags_by_side.items():
            if not flags[f]:
                continue
            flex = knee_flex(frame, rig, side)
            if best is None or flex < best[0]:
                best = (flex, side)
        if best is None or best[0] <= floor_deg:
            lifts.append(0.0)
            continue
        flex, side = best
        j = rig.joints(frame, (f"{side}UpperLeg", f"{side}LowerLeg", f"{side}Foot"))
        a, b, c = j[f"{side}UpperLeg"], j[f"{side}LowerLeg"], j[f"{side}Foot"]
        la, lb = (b - a).length, (c - b).length
        want = floor_deg + (flex - floor_deg) * keep
        d = math.sqrt(la * la + lb * lb - 2 * la * lb * math.cos(math.radians(180.0 - want)))
        v = a - c
        h2 = v.x * v.x + v.y * v.y
        lifts.append(max(0.0, math.sqrt(max(0.0, d * d - h2)) - v.z))
    # Lissage gaussien (circulaire pour une boucle).
    radius = int(3 * sigma)
    kernel = [math.exp(-0.5 * (k / sigma) ** 2) for k in range(-radius, radius + 1)]
    smooth = []
    for f in range(period):
        acc = wsum = 0.0
        for k, w in zip(range(-radius, radius + 1), kernel):
            g = f + k
            if motion.loop:
                g %= period
            elif g < 0 or g >= period:
                continue
            acc += lifts[g] * w
            wsum += w
        smooth.append(acc / wsum if wsum else 0.0)
    for f in range(period):
        motion.frames[f]["hips"].z += smooth[f]
    if motion.loop:
        motion.frames[-1]["hips"].z += smooth[0]
    return sum(smooth) / max(1, len(smooth)) * 100


def seam_step(motion):
    """Le saut au raccord d'une boucle (degrés) : de la dernière image unique à la première, comparé au saut moyen."""
    if not motion.loop or len(motion.frames) < 3:
        return 0.0, 0.0
    period = len(motion.frames) - 1
    def step(a, b):
        return max((_angle(a["d"][h], b["d"][h]) for h in a["d"] if h in b["d"]), default=0.0)
    seam = step(motion.frames[period - 1], motion.frames[0])
    usual = sum(step(motion.frames[i - 1], motion.frames[i]) for i in range(1, period)) / max(1, period - 1)
    return seam, usual


LEG_PARTS = ("UpperLeg", "LowerLeg", "Foot", "Toes")


def upper_body(motion):
    return [h for h in motion.frames[0]["d"] if h != "hips" and not any(p in h for p in LEG_PARTS)]


def lean_less(motion, keep=0.6, rest_tilt=None):
    """
    Le buste moins plongé : à chaque image, ce que le buste (hanches → cou) penche en avant au-delà de son repos est
    réduit à `keep` en redressant d'un bloc tout le haut du corps (colonne, poitrine, cou, tête, bras) autour de l'axe
    gauche-droite du bassin. S'asseoir ou se lever comme l'acteur de 143_18, c'est plonger la tête au niveau du bureau.
    """
    rig = motion.rig
    if rest_tilt is None:
        rest = Motion(rig, "repos", [{"hips": rig.rest_pos["hips"].copy(), "d": {h: Quaternion() for h in rig.hmap}}])
        j = rig.joints(rest.frames[0], ("hips", "neck"))
        rest_tilt = tilt(j["neck"] - j["hips"], facing(rest.frames[0]))
    bones = upper_body(motion)
    worst = 0.0
    for f in motion.frames:
        j = rig.joints(f, ("hips", "neck"))
        excess = tilt(j["neck"] - j["hips"], facing(f)) - rest_tilt
        if excess <= 0:
            continue
        worst = max(worst, excess)
        q = Quaternion(lateral_axis(f, rig), math.radians(-excess * (1.0 - keep)))
        for h in bones:
            f["d"][h] = q @ f["d"][h]
    return worst


def seat_height(motion, target):
    """
    Assise à la hauteur de son siège : les hanches assises (le bas de leur course) sont amenées à `target` (m
    au-dessus du sol), en proportion de la descente — debout rien ne bouge. Les pieds posés sont replantés ensuite
    par `lock_feet`. Rend (hauteur assise d'origine, décalage).
    """
    zs = [f["hips"].z for f in motion.frames]
    hi, lo = max(zs), min(zs)
    delta = target - lo
    span = hi - lo
    for f, z in zip(motion.frames, zs):
        p = 1.0 if span < 0.05 else min(1.0, max(0.0, (hi - z) / span))
        f["hips"].z += delta * p
    return lo, delta


def turn(motion, q):
    """Tourne tout le mouvement autour de l'axe vertical passant par l'origine (q : rotation autour de Z)."""
    for f in motion.frames:
        z = f["hips"].z
        p = q @ Vector((f["hips"].x, f["hips"].y, 0.0))
        f["hips"] = Vector((p.x, p.y, z))
        for h in f["d"]:
            f["d"][h] = q @ f["d"][h]


def center_stance(motion, on="feet", frames=None):
    """
    Recentre un mouvement sur place : le bassin face à l'avant en moyenne (-Y), et le milieu des pieds (« feet ») ou
    les hanches (« hips ») à l'origine — sous la racine que le jeu pose. Chaque prise Mixamo se tenait ailleurs (jusqu'à
    9 cm de côté, 24° de biais) : au fondu d'un clip à l'autre, un pied devait faire un pas pour se recaler.
    `frames` : les images qui font référence (par défaut toutes). Rend (degrés tournés, décalage en cm).
    """
    rig = motion.rig
    sel = frames if frames is not None else range(len(motion.frames))
    fw = sum((facing(motion.frames[i]) for i in sel), Vector())
    fw.z = 0.0
    q = fw.normalized().rotation_difference(Vector((0.0, -1.0, 0.0))) if fw.length > 1e-6 else Quaternion()
    turn(motion, q)
    mids = []
    for i in sel:
        f = motion.frames[i]
        if on == "feet":
            j = rig.joints(f, ("leftFoot", "rightFoot"))
            mids.append((j["leftFoot"] + j["rightFoot"]) / 2)
        else:
            mids.append(f["hips"].copy())
    mid = sum(mids, Vector()) / len(mids)
    shift = Vector((mid.x, mid.y, 0.0))
    for f in motion.frames:
        f["hips"] -= shift
    angle = math.degrees(q.angle)
    return (angle if angle <= 180 else 360 - angle), shift.length * 100


def _mean_rotation(qs):
    """Moyenne de rotations proches (somme des quaternions alignés sur le premier, normalisée)."""
    ref = qs[0]
    acc = Quaternion((0.0, 0.0, 0.0, 0.0))
    for q in qs:
        q = q.copy()
        if q.dot(ref) < 0:
            q.negate()
        acc = Quaternion((acc.w + q.w, acc.x + q.x, acc.y + q.y, acc.z + q.z))
    return acc.normalized()


def recenter_head(motion, chain=(("neck", "chest"), ("head", "neck"))):
    """
    Le cou et la tête ramenés droits sur le buste en moyenne, leurs mouvements gardés : chaque os, par rapport à son
    parent, perd sa rotation moyenne sur le clip. Les prises CMU ont un décalage de tête propre à chaque acteur (le
    bas du cou de 113 tourné de 40° de côté, la tête de 142 levée de 27° en permanence) : un défaut de calibrage, pas
    un geste. Rend, par os, l'angle retiré (degrés).
    """
    removed = {}
    for bone, parent in chain:
        frames = [f for f in motion.frames if bone in f["d"] and parent in f["d"]]
        if not frames:
            continue
        rel = [f["d"][parent].inverted() @ f["d"][bone] for f in frames]
        mean = _mean_rotation(rel)
        undo = mean.inverted()
        for f, r in zip(frames, rel):
            f["d"][bone] = f["d"][parent] @ (undo @ r)
        angle = math.degrees(mean.angle)
        removed[bone] = round(min(angle, 360 - angle), 1)
    return removed
