# Animations de capture de mouvement (base CMU) -> un FBX par clip pour le corps de
# Mika dans Unity, avec la pose T comme pose de repos.
#
#   blender -b --factory-startup --python frontend/assets-src/blender/mocap_unity.py -- \
#       --bvh-dir <cache des BVH> [--out UnityFrontend/ArtSource/mocap] [--only walking,sit_down]
#       [--no-previews] [--no-download]
#
# Source : la conversion BVH « MotionBuilder-friendly » de cgspeed (Bruce Hahne) de la
# base Carnegie Mellon University Graphics Lab Motion Capture Database, copie
# github.com/una-dinosauria/cmu-mocap (data/<sujet sur 3 chiffres>/<prise>.bvh). 120 i/s,
# image 0 = pose T face à +Z. Les prises manquantes de --bvh-dir sont téléchargées
# (désactiver avec --no-download). Rien d'autre n'est lu ni écrit hors de --out.
#
# Pour chaque clip de la table CLIPS :
#   1. la prise est importée telle quelle (échelle 1, axes BVH -> Blender : X, -Z, Y ; le
#      personnage regarde -Y, ce qui donnera +Z dans Unity) ;
#   2. échelle : hauteur des hanches de la pose T mesurée au-dessus des pointes de pied
#      de cette même pose (hT, unités BVH) ; s = 0,95 m / hT. Chaque prise est donc
#      ramenée à 0,95 m de hanches au repos (un adulte ; Unity normalise de toute façon
#      l'humanoïde par la hauteur des hanches) ;
#   3. sol : pose de repos = pointes de pied de la pose T à 0 ; animation = pointe de
#      pied en appui (médiane, phases debout immobiles) à 0, sauf FLOOR_OVERRIDE ;
#      tête : lacet tête/buste retiré pour les prises de HEAD_RECENTER (voir plus bas) ;
#   4. une armature neuve « CMU_Rig » est construite dont la pose de REPOS est la pose T
#      de l'image 0 (pas la pose aux rotations nulles du BVH, jambes écartées de 20°) :
#      mêmes os, mêmes noms, mêmes longueurs (mises à l'échelle) ; repos centré
#      (hanches en x = y = 0), tourné face à -Y ; l'objet armature est tourné de +90° en
#      X (RIG_MATRIX) pour que le nœud racine du FBX n'ait aucune rotation ;
#   5. le mouvement est recopié os par os en espace monde (matrice de pose voulue ->
#      matrice de base locale), une image source sur 4 : 120 -> 30 i/s exactement ;
#      plage [début, fin] de la table, bornes comprises, en indices d'image du BVH
#      (0 = pose T) ; le clip ne contient jamais l'image de pose T ;
#   6. placement (« anchor ») : « self » = hanches à l'origine et regard vers -Y (avant
#      Unity) à la première image (« travel » : direction de déplacement vers -Y) ;
#      « same:<clip> » = même placement qu'un clip de la même prise (chaînes qui se
#      raccordent exactement) ; « end:<clip> » = début de ce clip posé sur la fin de
#      l'autre (position des hanches et regard) ;
#   7. boucles : l'écart résiduel entre la dernière et la première image (mesuré et
#      noté dans clips.json) est réparti linéairement sur le clip (rotations de chaque
#      os, position des hanches sauf l'avance pour la locomotion) : dernière image =
#      première image ;
#   8. export FBX de l'armature seule (réglages FBX_OPTIONS) depuis l'image -1, qui porte
#      une clé de repos : l'exporteur écrit la pose de l'image COURANTE dans les Lcl des
#      os (= pose du modèle pour Unity), et ne cuit que frame_start..frame_end (0..N-1) ;
#   9. vérification par réimport (durée, pose de repos en T, hauteur des hanches, écart
#      des articulations avec ce qui a été exporté, fermeture des boucles, nœuds FBX) et
#      planche d'images (vue de côté et de face) dans previews/<nom>.png ; clips.json et
#      README.md sont réécrits.
#
# Les plages ont été choisies par analyse du mouvement (outil numpy hors dépôt, même
# cinématique directe) : énergie de mouvement (vitesse RMS des articulations lissée sur
# 0,1 s), hauteur des hanches, inclinaison du buste (hanches -> cou), vitesse du bassin,
# frappes de talon (vitesse horizontale de la cheville) ; boucles = paire d'images
# minimisant l'écart de pose (articulations relatives aux hanches, cap retiré) + écart de
# vitesses + écart de hauteur des hanches. Détail et valeurs dans README.md.
import argparse
import json
import math
import os
import sys
import tempfile
import time
import traceback
import urllib.request
from collections import namedtuple

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DEFAULT_OUT = os.path.join(REPO, "UnityFrontend", "ArtSource", "mocap")
DEFAULT_BVH = os.environ.get("MIKA_CMU_BVH_DIR") or os.path.join(
    os.path.expanduser("~"), ".cache", "mika-mocap", "cmu")
BVH_URL = "https://raw.githubusercontent.com/una-dinosauria/cmu-mocap/master/data/{subject:03d}/{take}.bvh"
SOURCE = "frontend/assets-src/blender/mocap_unity.py"

SRC_FPS = 120
FPS = 30
STEP = SRC_FPS // FPS          # 4 : une image source sur quatre, sans interpolation
TARGET_HIPS = 0.95             # hauteur des hanches visée au repos (m)
CMU_UNIT_M = 0.0254 / 0.45     # unité CMU d'origine (« length 0.45 » de l'ASF), pour mémoire
RIG_NAME = "CMU_Rig"           # nom du nœud racine, identique dans tous les FBX
# L'exporteur FBX n'applique pas bake_space_transform aux armatures : l'objet armature
# reçoit la conversion d'axes (-90° en X) comme rotation propre. On le tourne donc de
# +90° en X (données de l'armature en espace Y-haut) : la racine sort sans rotation.
RIG_MATRIX = Matrix.Rotation(math.radians(90.0), 4, "X")
REST_FRAME = -1                # image de la clé de repos (hors plage exportée), voir export_fbx

Clip = namedtuple("Clip", "name take frames loop category anchor align description")
# frames : (début, fin) inclus, indices d'image du BVH (0 = pose T), fin - début multiple de 4.
# anchor : "self" | "same:<clip>" | "end:<clip>" ; align (pour "self") : "facing" | "travel".
CLIPS = [
    Clip("walking", "35_01", (83, 219), True, "locomotion", "self", "travel",
         "Marche normale (≈1,2 m/s), un cycle complet de l'appui du pied droit à l'appui suivant "
         "du même pied (deux pas), droite."),
    Clip("walking_slow", "142_13", (3095, 3287), True, "locomotion", "self", "travel",
         "Marche lente détendue (≈0,67 m/s), un cycle de l'appui du pied gauche au suivant (deux "
         "pas), droite."),
    Clip("sit_down", "143_18", (44, 232), False, "transition", "self", "facing",
         "Debout immobile -> assise sur une chaise (siège ≈0,47 m), mains posées sur le siège."),
    Clip("sitting_idle", "113_15", (370, 514), True, "idle", "end:sit_down", "facing",
         "Assise sur une chaise, tenue calme (mains sur les cuisses), bouclable. Posée sur la fin "
         "de sit_down."),
    Clip("stand_up", "143_18", (268, 372), False, "transition", "same:sit_down", "facing",
         "Assise -> debout (même prise et même placement que sit_down)."),
    Clip("lie_down", "113_08", (40, 708), False, "transition", "self", "facing",
         "Debout -> à genoux, assise au sol, puis allongée sur le dos."),
    Clip("lying_idle", "113_08", (708, 1064), True, "idle", "same:lie_down", "facing",
         "Allongée sur le dos, immobile (respiration), bouclable. Même prise et placement que lie_down."),
    Clip("get_up", "113_08", (1100, 1792), False, "transition", "same:lie_down", "facing",
         "Allongée sur le dos -> assise, à genoux, debout. Même prise et placement que lie_down."),
    Clip("picking_up", "26_09", (36, 476), False, "gesture", "self", "facing",
         "Se pencher en fléchissant les genoux, ramasser un objet au sol de la main droite, se relever."),
    Clip("stretch", "113_23", (36, 916), False, "gesture", "self", "facing",
         "Étirement lent : bras montés au-dessus de la tête, tenue, redescente (« stretch and yawn »)."),
    Clip("waiting", "113_21", (500, 1064), True, "idle", "self", "facing",
         "Attente debout naturelle : le poids passe d'un appui à l'autre et revient, bouclable."),
]

FBX_OPTIONS = dict(
    use_selection=True, object_types={"ARMATURE"},
    axis_forward="-Z", axis_up="Y", bake_space_transform=True,
    apply_scale_options="FBX_SCALE_UNITS", add_leaf_bones=False,
    use_armature_deform_only=False, primary_bone_axis="Y", secondary_bone_axis="X",
    armature_nodetype="NULL", use_custom_props=False,
    bake_anim=True, bake_anim_use_all_bones=True, bake_anim_use_all_actions=False,
    bake_anim_use_nla_strips=False, bake_anim_force_startend_keying=True,
    bake_anim_step=1.0, bake_anim_simplify_factor=0.0,
)

# Sujet 113 (le seul féminin de la base pour la plupart de ces gestes) : la tête reste
# tournée d'environ 50° vers sa droite par rapport au buste dans presque toutes ses
# prises, même en marchant (113_25) ; elle revient à ~0° quand elle lève les yeux vers
# ses mains (113_23) : c'est un regard réel (vers l'opérateur, probablement), pas un
# défaut de calibration, mais pour un idle c'est un tic. On retire ce lacet autour de
# l'axe vertical du buste, réparti sur Neck, Neck1, Head : « constant » = médiane sur les
# plages des clips de la prise (les chaînes restent raccordées), « smooth » = composante
# lente (gaussienne de HEAD_SMOOTH_S) quand le regard change pendant le clip.
HEAD_RECENTER = {"113_08": "constant", "113_15": "constant", "113_21": "constant", "113_23": "smooth"}
HEAD_SMOOTH_S = 0.5
HEAD_CHAIN = ("Neck", "Neck1", "Head")
# Sol imposé (unités BVH) : 113_08 se couche au sol ; caler le sol sur ses orteils debout
# (+2,6 cm) mettrait le bassin couché à 4 cm et les poignets en appui à -12 cm. On garde
# le sol brut de la capture.
FLOOR_OVERRIDE = {"113_08": 0.0}

FINGER_BONES = ("LeftFingerBase", "LeftHandIndex1", "LThumb", "RightFingerBase", "RightHandIndex1", "RThumb")

KEY_JOINTS = ["Hips", "Head", "LeftHand", "RightHand", "LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase"]
POSE_JOINTS = ["LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase", "RightUpLeg", "RightLeg", "RightFoot",
               "RightToeBase", "Spine1", "Neck1", "Head", "LeftArm", "LeftForeArm", "LeftHand",
               "RightArm", "RightForeArm", "RightHand"]


def unity(v):
    """Blender (x, y, z) -> Unity (x, y, z) après export (-Z avant, Y haut) et import Unity."""
    return [round(-v[0], 3), round(v[2], 3), round(-v[1], 3)]


def log(msg):
    print(f"[mocap_unity] {msg}", flush=True)


# =====================================================================================
# Source BVH
# =====================================================================================

def ensure_bvh(take, bvh_dir, download):
    path = os.path.join(bvh_dir, f"{take}.bvh")
    if os.path.isfile(path):
        return path
    if not download:
        raise RuntimeError(f"BVH absent : {path} (--no-download)")
    os.makedirs(bvh_dir, exist_ok=True)
    url = BVH_URL.format(subject=int(take.split("_")[0]), take=take)
    log(f"téléchargement {url}")
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read()
    if not data.startswith(b"HIERARCHY"):
        raise RuntimeError(f"réponse inattendue pour {url}")
    with open(path + ".part", "wb") as f:
        f.write(data)
    os.replace(path + ".part", path)
    return path


def hz(v):
    return Vector((v.x, v.y, 0.0))


def facing_of(m):
    """Avant horizontal (unitaire) d'une pose : perpendiculaire à l'axe gauche-droite
    (hanches + épaules). Pose T de référence : (0, -1, 0)."""
    lat = (m["LeftUpLeg"].translation - m["RightUpLeg"].translation).normalized() \
        + (m["LeftArm"].translation - m["RightArm"].translation).normalized()
    f = lat.cross(Vector((0, 0, 1)))
    f.z = 0.0
    return f.normalized()


class Take:
    """Une prise BVH importée, échantillonnée à la demande (matrices monde des os,
    tête recentrée si la prise figure dans HEAD_RECENTER)."""

    def __init__(self, take, path):
        self.take = take
        before = set(bpy.data.objects)
        res = bpy.ops.import_anim.bvh(
            filepath=path, global_scale=1.0, frame_start=1, use_fps_scale=False,
            update_scene_fps=False, update_scene_duration=False, use_cyclic=False,
            rotate_mode="NATIVE", axis_forward="-Z", axis_up="Y")
        if "FINISHED" not in res:
            raise RuntimeError(f"import BVH échoué : {path}")
        new = [o for o in bpy.data.objects if o not in before]
        if len(new) != 1 or new[0].type != "ARMATURE":
            raise RuntimeError(f"import BVH inattendu : {[o.name for o in new]}")
        self.ob = new[0]
        self.ob.name = f"src_{take}"
        act = self.ob.animation_data.action
        self.n_frames = int(round(act.frame_range[1] - act.frame_range[0])) + 1
        self.names = [b.name for b in self.ob.data.bones]
        self.parent = {b.name: (b.parent.name if b.parent else None) for b in self.ob.data.bones}
        self.length = {b.name: b.length for b in self.ob.data.bones}
        kids = {n: [] for n in self.names}
        for n, p in self.parent.items():
            if p:
                kids[p].append(n)

        def below(n):
            out = [n]
            for k in kids[n]:
                out += below(k)
            return out
        self.chain = [(j, below(j)) for j in HEAD_CHAIN]
        self._raw = {}
        self._cache = {}
        t = self.raw(0)
        toe = min(t["_tails"]["LeftToeBase"].z, t["_tails"]["RightToeBase"].z)
        self.t_toe = toe
        self.hT = t["Hips"].translation.z - toe
        self.s = TARGET_HIPS / self.hT
        self.floor_measured = self._floor()
        self.floor = FLOOR_OVERRIDE.get(take, self.floor_measured)
        self.head_twist = None          # lacet tête/buste retiré, degrés, par image du BVH
        mode = HEAD_RECENTER.get(take)
        if mode:
            self.head_twist = self._head_twist(mode)
        self._raw.clear()

    def raw(self, i):
        """Matrices monde (unités BVH) brutes de tous les os à l'image i (0 = pose T)."""
        if i not in self._raw:
            sc = bpy.context.scene
            sc.frame_set(i + 1)
            mw = self.ob.matrix_world
            d = {pb.name: (mw @ pb.matrix).copy() for pb in self.ob.pose.bones}
            d["_tails"] = {pb.name: (mw @ pb.tail).copy() for pb in self.ob.pose.bones}
            self._raw[i] = d
        return self._raw[i]

    def mats(self, i):
        """Matrices monde (unités BVH) à l'image i, tête recentrée le cas échéant."""
        if i not in self._cache:
            d = self.raw(i)
            self._raw.pop(i, None)
            if self.head_twist is not None and i > 0:
                d = self._recenter_head(d, i)
            self._cache[i] = d
        return self._cache[i]

    def tail(self, i, name):
        return self.mats(i)["_tails"][name]

    def _floor(self):
        """Hauteur (unités) des pointes de pied en appui quand la personne est debout."""
        heights, standing = [], []
        prev = None
        for i in range(1, self.n_frames, 2):
            m = self.raw(i)
            tl, tr = m["_tails"]["LeftToeBase"], m["_tails"]["RightToeBase"]
            low = tl if tl.z < tr.z else tr
            if prev is not None:
                v = (low - prev).length / (2.0 / SRC_FPS)
                if v < 3.0:
                    heights.append(low.z)
                    standing.append(m["Hips"].translation.z > 0.75 * self.hT)
            prev = low
        h = np.array(heights)
        st = np.array(standing, dtype=bool)
        if st.sum() >= 20:
            return float(np.median(h[st]))
        return float(np.median(h)) if len(h) else 0.0

    def _twist(self, m, t0):
        """Lacet (rad) de la tête par rapport au buste (Spine1), autour de l'axe vertical du
        buste, mesuré depuis la pose T (positif = vers la gauche du personnage)."""
        s0, h0 = t0["Spine1"].to_3x3().normalized(), t0["Head"].to_3x3().normalized()
        s, h = m["Spine1"].to_3x3().normalized(), m["Head"].to_3x3().normalized()
        g = ((s @ s0.inverted()).inverted() @ (h @ h0.inverted())).to_quaternion()
        return 2.0 * math.atan2(g.z, g.w)

    def _head_twist(self, mode):
        t0 = self.raw(0)
        frames = np.arange(1, self.n_frames)
        vals = np.unwrap(np.array([self._twist(self.raw(int(i)), t0) for i in frames]))
        if mode == "constant":
            spans = [range(c.frames[0], c.frames[1] + 1) for c in CLIPS if c.take == self.take]
            idx = np.unique(np.concatenate([np.array(list(r)) for r in spans])) - 1
            series = np.full(self.n_frames, float(np.median(vals[idx])))
        elif mode == "smooth":
            sigma = HEAD_SMOOTH_S * SRC_FPS
            k = np.arange(-int(3 * sigma), int(3 * sigma) + 1)
            w = np.exp(-0.5 * (k / sigma) ** 2)
            pad = np.pad(vals, len(k) // 2, mode="edge")
            series = np.concatenate([[0.0], np.convolve(pad, w / w.sum(), mode="valid")])
        else:
            raise RuntimeError(f"HEAD_RECENTER[{self.take}] : mode inconnu {mode!r}")
        series[0] = 0.0
        return np.degrees(series)

    def _recenter_head(self, d, i):
        """Tourne Neck, Neck1 puis Head (un tiers chacun) autour de l'axe vertical du buste,
        chacun autour de sa propre tête d'os, de -lacet : le cou garde ses inclinaisons."""
        t0 = self.raw(0) if 0 not in self._cache else self._cache[0]
        axis = (d["Spine1"].to_3x3().normalized() @ t0["Spine1"].to_3x3().normalized().inverted()) \
            @ Vector((0, 0, 1))
        step = Matrix.Rotation(-math.radians(self.head_twist[i]) / len(self.chain), 4, axis.normalized())
        d = {k: (v.copy() if k != "_tails" else {kk: vv.copy() for kk, vv in v.items()}) for k, v in d.items()}
        for j, sub in self.chain:
            p = d[j].translation.copy()
            c = Matrix.Translation(p) @ step @ Matrix.Translation(-p)
            for n in sub:
                d[n] = c @ d[n]
                d["_tails"][n] = c @ d["_tails"][n]
        return d


# =====================================================================================
# Placement
# =====================================================================================

class Placement:
    """p_monde(m) = Rz(theta) . s . (p_xy - p0) + q  ;  z(m) = s . (p_z - floor)."""

    def __init__(self, theta, p0, q, s, floor):
        self.theta, self.p0, self.q, self.s, self.floor = theta, Vector(p0), Vector(q), s, floor
        self.rot = Matrix.Rotation(theta, 4, "Z")
        self.rot3 = self.rot.to_3x3()

    def point(self, p):
        d = self.rot3 @ Vector((p.x - self.p0.x, p.y - self.p0.y, 0.0))
        return Vector((self.s * d.x + self.q.x, self.s * d.y + self.q.y, self.s * (p.z - self.floor)))

    def matrix(self, m):
        r = (self.rot3 @ m.to_3x3()).normalized()
        out = r.to_4x4()
        out.translation = self.point(m.translation)
        return out

    def facing(self, m):
        return (self.rot3 @ facing_of(m)).normalized()


def theta_to(src_dir, dst_dir):
    """Rotation autour de Z amenant la direction horizontale src sur dst."""
    return math.atan2(dst_dir.y, dst_dir.x) - math.atan2(src_dir.y, src_dir.x)


def mean_facing(take, i, half=6):
    acc = Vector((0, 0, 0))
    for k in range(max(1, i - half), min(take.n_frames - 1, i + half) + 1):
        acc += facing_of(take.mats(k))
    return hz(acc).normalized()


FORWARD = Vector((0, -1, 0))


def rest_placement(take):
    m = take.mats(0)
    th = theta_to(facing_of(m), FORWARD)
    return Placement(th, hz(m["Hips"].translation), (0, 0, 0), take.s, take.t_toe)


def clip_placement(clip, takes, placements, ends):
    take = takes[clip.take]
    a, b = clip.frames
    kind, _, ref = clip.anchor.partition(":")
    if kind == "self":
        p_a = take.mats(a)["Hips"].translation
        if clip.align == "travel":
            d = hz(take.mats(b)["Hips"].translation - p_a)
            th = theta_to(d.normalized(), FORWARD)
        else:
            th = theta_to(mean_facing(take, a), FORWARD)
        return Placement(th, hz(p_a), (0, 0, 0), take.s, take.floor)
    if kind == "same":
        other = placements[ref]
        if CLIP_BY_NAME[ref].take != clip.take:
            raise RuntimeError(f"{clip.name}: same:{ref} exige la même prise")
        return Placement(other.theta, other.p0, other.q, other.s, other.floor)
    if kind == "end":
        q_xy, f_dst = ends[ref]                 # position (m) et regard à la fin de ref
        th = theta_to(mean_facing(take, a), f_dst)
        p_a = take.mats(a)["Hips"].translation
        return Placement(th, hz(p_a), (q_xy.x, q_xy.y, 0), take.s, take.floor)
    raise RuntimeError(f"{clip.name}: anchor inconnu {clip.anchor!r}")


def clip_end(clip, take, pl):
    """Position (m) des hanches et regard à la dernière image du clip, une fois placé."""
    b = clip.frames[1]
    m = take.mats(b)
    return pl.point(m["Hips"].translation), hz(pl.rot3 @ mean_facing(take, b, 4)).normalized()


# =====================================================================================
# Armature cible (repos = pose T) et transfert du mouvement
# =====================================================================================

def build_rig(take):
    pl = rest_placement(take)
    m0 = take.mats(0)
    arm = bpy.data.armatures.new(RIG_NAME)
    rig = bpy.data.objects.new(RIG_NAME, arm)
    if rig.name != RIG_NAME:
        raise RuntimeError(f"nom de rig pris : {rig.name}")
    bpy.context.scene.collection.objects.link(rig)
    rig.matrix_world = RIG_MATRIX
    to_arm = RIG_MATRIX.inverted()
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for name in take.names:                      # ordre parent -> enfant (ordre du BVH)
        eb = arm.edit_bones.new(name)
        eb.head = (0, 0, 0)
        eb.tail = (0, 0.1, 0)
        eb.matrix = to_arm @ pl.matrix(m0[name])
        eb.length = max(take.length[name] * take.s, 1e-3)
        if take.parent[name]:
            eb.parent = arm.edit_bones[take.parent[name]]
        eb.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in rig.pose.bones:
        pb.rotation_mode = "QUATERNION"
    return rig


def joints_rel(world, names=POSE_JOINTS):
    h = world["Hips"].translation
    return np.array([list(world[n].translation - h) for n in names])


def bake(clip, take, rig, pl):
    """Calcule les bases locales image par image, corrige la boucle, pose les clés."""
    a, b = clip.frames
    if (b - a) % STEP:
        raise RuntimeError(f"{clip.name}: (fin - début) doit être multiple de {STEP}")
    if a < 1 or b >= take.n_frames:
        raise RuntimeError(f"{clip.name}: plage hors prise (1..{take.n_frames - 1})")
    src = list(range(a, b + 1, STEP))
    n = len(src)
    rest = {bn.name: rig.matrix_world @ bn.matrix_local for bn in rig.data.bones}   # repos, espace monde
    world = [{k: pl.matrix(v) for k, v in take.mats(i).items() if k != "_tails"} for i in src]

    stats = {}
    if clip.loop:
        w0, w1 = world[0], world[-1]
        jr = joints_rel(w0) - joints_rel(w1)
        stats["seam_pose_rms_cm"] = round(float(np.sqrt(np.mean(np.sum(jr ** 2, 1)))) * 100, 2)
        d = w0["Hips"].translation - w1["Hips"].translation
        if clip.category == "locomotion":
            stats["advance_m"] = round(d.y, 3)        # avance d'un cycle (vers +Z Unity)
            seam = Vector((d.x, 0.0, d.z))
        else:
            seam = d
        stats["seam_hips_cm"] = [round(x * 100, 2) for x in unity(seam)]
        f0, f1 = facing_of(w0), facing_of(w1)
        stats["seam_yaw_deg"] = round(math.degrees(theta_to(f1, f0)), 2)
        if clip.category == "locomotion":
            d.y = 0.0                              # l'avance (vers -Y) est le pas : on la garde
        for j, w in enumerate(world):          # tout le corps glisse, pas seulement les hanches
            t = j / (n - 1)
            for m in w.values():
                m.translation = m.translation + d * t

    # bases locales : B = R^-1 Rp Pp^-1 P (racine : R^-1 P), R et P en espace monde
    # (la transformation de l'objet armature s'y simplifie)
    quats = {nm: [] for nm in take.names}
    locs = []
    max_child_loc = 0.0
    for w in world:
        for nm in take.names:
            par = take.parent[nm]
            if par is None:
                basis = rest[nm].inverted() @ w[nm]
            else:
                basis = rest[nm].inverted() @ rest[par] @ w[par].inverted() @ w[nm]
            loc, q, _ = basis.decompose()
            if par is None:
                locs.append(loc)
            else:
                max_child_loc = max(max_child_loc, loc.length)
            seq = quats[nm]
            if seq:
                q.make_compatible(seq[-1])
            seq.append(q)
    if max_child_loc > 1e-3:
        raise RuntimeError(f"{clip.name}: translation parasite d'un os enfant ({max_child_loc:.4f} m)")

    if clip.loop:
        seams = {}
        for nm, seq in quats.items():
            c = seq[-1].inverted() @ seq[0]
            if c.w < 0:
                c.negate()
            seams[nm] = math.degrees(c.angle)
            ident = Quaternion()
            for j in range(n):
                seq[j] = seq[j] @ ident.slerp(c, j / (n - 1))
        body = {k: v for k, v in seams.items() if k not in FINGER_BONES}
        worst = max(body, key=body.get)
        stats["seam_max_bone_deg"] = {"bone": worst, "deg": round(body[worst], 2)}
        stats["seam_max_finger_deg"] = round(max(seams[k] for k in FINGER_BONES if k in seams), 2)

    sc = bpy.context.scene
    sc.render.fps, sc.render.fps_base = FPS, 1.0
    sc.frame_start, sc.frame_end = 0, n - 1
    rig.animation_data_create()
    act = bpy.data.actions.new(clip.name)
    rig.animation_data.action = act
    for nm in take.names:                     # clé de repos (pose T), hors plage exportée
        pb = rig.pose.bones[nm]
        pb.rotation_quaternion = Quaternion()
        pb.keyframe_insert("rotation_quaternion", frame=REST_FRAME, group=nm)
        if take.parent[nm] is None:
            pb.location = Vector()
            pb.keyframe_insert("location", frame=REST_FRAME, group=nm)
    for j in range(n):
        for nm in take.names:
            pb = rig.pose.bones[nm]
            pb.rotation_quaternion = quats[nm][j]
            pb.keyframe_insert("rotation_quaternion", frame=j, group=nm)
            if take.parent[nm] is None:
                pb.location = locs[j]
                pb.keyframe_insert("location", frame=j, group=nm)
    if rig.animation_data.action is not act:
        raise RuntimeError(f"{clip.name}: action remplacée pendant la pose des clés")

    # contrôle : la pose évaluée du rig reproduit la pose voulue (avant correction de boucle)
    samples = sample_frames(n, clip.loop)
    err = 0.0
    expected = {}
    raw = [{k: pl.matrix(v) for k, v in take.mats(src[j]).items() if k != "_tails"} for j in samples]
    for j, w in zip(samples, raw):
        sc.frame_set(j)
        got = {pb.name: (rig.matrix_world @ pb.matrix).translation.copy() for pb in rig.pose.bones}
        expected[j] = {k: list(got[k]) for k in KEY_JOINTS}
        if not clip.loop:
            err = max(err, max((got[k] - w[k].translation).length for k in take.names))
    stats["retarget_max_err_mm"] = None if clip.loop else round(err * 1000, 3)
    first = world[0]
    last = world[-1]
    stats["head_from_hips_end_unity_m"] = unity(last["Head"].translation - last["Hips"].translation)
    stats["_lengths"] = {bn.name: bn.length for bn in rig.data.bones}
    stats.update(
        frames_out=n, seconds=round((n - 1) / FPS, 3),
        hips_start_m=unity(first["Hips"].translation),
        hips_end_m=unity(last["Hips"].translation),
        facing_start_deg=round(math.degrees(theta_to(FORWARD, facing_of(first))), 1),
        facing_end_deg=round(math.degrees(theta_to(FORWARD, facing_of(last))), 1),
    )
    if clip.category == "locomotion":
        dist = (last["Hips"].translation - first["Hips"].translation).length
        stats["speed_m_s"] = round(dist / ((n - 1) / FPS), 3)
    return stats, expected


def preview_frames(n, loop):
    if loop:
        return sorted({0, n // 4, n // 2, (3 * n) // 4})
    return sorted({round(k * (n - 1) / 4) for k in range(5)})


def sample_frames(n, loop):
    if loop:
        return sorted({0, n // 4, n // 2, (3 * n) // 4})
    return sorted({0, (n - 1) // 3, (2 * (n - 1)) // 3, n - 1})


def export_fbx(rig, path):
    """Les propriétés Lcl des os (pose du modèle pour Unity, repos au réimport Blender)
    sont la pose de l'image COURANTE ; la cuisson couvre frame_start..frame_end puis
    l'exporteur restaure l'image courante. On exporte donc depuis l'image de repos."""
    sc = bpy.context.scene
    sc.frame_set(REST_FRAME)
    for pb in rig.pose.bones:
        mb = pb.matrix_basis
        if mb.to_quaternion().angle > 1e-5 or mb.translation.length > 1e-6:
            raise RuntimeError(f"pose de repos non atteinte à l'image {REST_FRAME} ({pb.name})")
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    os.makedirs(os.path.dirname(path), exist_ok=True)
    res = bpy.ops.export_scene.fbx(filepath=path, **FBX_OPTIONS)
    if "FINISHED" not in res:
        raise RuntimeError(f"export FBX échoué : {path} ({res})")


def delete_rig(rig):
    act = rig.animation_data.action if rig.animation_data else None
    arm = rig.data
    bpy.data.objects.remove(rig)
    bpy.data.armatures.remove(arm)
    if act:
        bpy.data.actions.remove(act)


# =====================================================================================
# Vérification par réimport + planches d'images
# =====================================================================================

def fbx_root_info(path):
    """Lit le nœud racine et les GlobalSettings du FBX (ce que Unity verra)."""
    from io_scene_fbx import parse_fbx
    root, _ver = parse_fbx.parse(path)

    def find(elem, name):
        return next((e for e in elem.elems if e.id == name), None)

    def props70(elem):
        out = {}
        p = find(elem, b"Properties70")
        if p:
            for e in p.elems:
                key = e.props[0].decode() if isinstance(e.props[0], bytes) else e.props[0]
                out[key] = e.props[4:]
        return out

    gs = props70(find(root, b"GlobalSettings"))
    info = {k: gs.get(k) for k in ("UpAxis", "UpAxisSign", "FrontAxis", "FrontAxisSign",
                                   "CoordAxis", "CoordAxisSign", "UnitScaleFactor")}
    objects = find(root, b"Objects")
    models = {}
    for e in objects.elems:
        if e.id == b"Model":
            name = e.props[1].split(b"\x00")[0].decode()
            pr = props70(e)
            models[name] = {k: [round(float(x), 4) for x in pr[k]] for k in
                            ("Lcl Translation", "Lcl Rotation", "Lcl Scaling", "PreRotation") if k in pr}
            models[name]["type"] = e.props[2].decode()
    info["root"] = models.get(RIG_NAME)
    info["hips"] = models.get("Hips")
    return info


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.fps, sc.render.fps_base = FPS, 1.0
    return sc


def import_fbx(path):
    before = set(bpy.data.objects)
    res = bpy.ops.import_scene.fbx(filepath=path)
    if "FINISHED" not in res:
        raise RuntimeError(f"réimport FBX échoué : {path}")
    arms = [o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"]
    if len(arms) != 1:
        raise RuntimeError(f"réimport : {len(arms)} armatures dans {path}")
    return arms[0]


def angle_deg(v, ref):
    return math.degrees(v.angle(ref))


def verify(clip, path, expected, stats):
    rig = import_fbx(path)
    sc = bpy.context.scene
    act = rig.animation_data.action
    f0, f1 = act.frame_range
    out = {"fbx_frames": int(round(f1 - f0)) + 1, "fbx_first_frame": round(f0, 3)}
    mw = rig.matrix_world
    # pose de repos
    bones = rig.data.bones

    def rest_head(nm):
        return mw @ bones[nm].head_local

    out["rest_hips_height_m"] = round(rest_head("Hips").z, 4)
    out["rest_ankles_z_m"] = [round(rest_head(n).z, 3) for n in ("LeftFoot", "RightFoot")]
    up, down, side = Vector((0, 0, 1)), Vector((0, 0, -1)), Vector((1, 0, 0))
    out["rest_upper_arm_from_horizontal_deg"] = [
        round(90 - angle_deg(rest_head("LeftForeArm") - rest_head("LeftArm"), up), 1),
        round(90 - angle_deg(rest_head("RightForeArm") - rest_head("RightArm"), up), 1)]
    out["rest_forearm_from_horizontal_deg"] = [
        round(90 - angle_deg(rest_head("LeftHand") - rest_head("LeftForeArm"), up), 1),
        round(90 - angle_deg(rest_head("RightHand") - rest_head("RightForeArm"), up), 1)]
    out["rest_thigh_from_vertical_deg"] = [
        round(angle_deg(rest_head("LeftLeg") - rest_head("LeftUpLeg"), down), 1),
        round(angle_deg(rest_head("RightLeg") - rest_head("RightUpLeg"), down), 1)]
    out["rest_shin_from_vertical_deg"] = [
        round(angle_deg(rest_head("LeftFoot") - rest_head("LeftLeg"), down), 1),
        round(angle_deg(rest_head("RightFoot") - rest_head("RightLeg"), down), 1)]
    out["rest_arm_span_axis"] = "X" if abs((rest_head("LeftArm") - rest_head("RightArm")).normalized().dot(side)) > 0.99 else "?"
    lat = rest_head("LeftUpLeg") - rest_head("RightUpLeg")
    out["rest_facing"] = [round(v, 3) for v in lat.cross(up).normalized()]
    # animation : écart avec ce qui a été exporté
    err = 0.0
    for j, exp in expected.items():
        sc.frame_set(int(round(f0)) + j)
        for k, v in exp.items():
            got = mw @ rig.pose.bones[k].head
            err = max(err, (got - Vector(v)).length)
    out["roundtrip_max_err_mm"] = round(err * 1000, 3)
    if clip.loop:
        sc.frame_set(int(round(f0)))
        a = {pb.name: (mw @ pb.head).copy() for pb in rig.pose.bones}
        sc.frame_set(int(round(f1)))
        b = {pb.name: (mw @ pb.head).copy() for pb in rig.pose.bones}
        ha, hb = a["Hips"], b["Hips"]
        rel = [((a[k] - ha) - (b[k] - hb)).length for k in POSE_JOINTS]
        out["loop_last_vs_first_pose_mm"] = round(max(rel) * 1000, 3)
        dh = ha - hb
        if clip.category == "locomotion":
            dh.y = 0.0
        out["loop_last_vs_first_hips_mm"] = round(dh.length * 1000, 3)
    out["fbx"] = fbx_root_info(path)
    return rig, out


# ---------------------------------------------------------------- planches

LEFT = (0.16, 0.38, 0.92, 1.0)
RIGHT = (0.92, 0.28, 0.20, 1.0)
CENTER = (0.22, 0.22, 0.24, 1.0)
MARK = (0.98, 0.78, 0.10, 1.0)


def side_of(name):
    if name.startswith("Left") or (len(name) > 1 and name[0] == "L" and name[1].isupper()):
        return "L"
    if name.startswith("Right") or (len(name) > 1 and name[0] == "R" and name[1].isupper()):
        return "R"
    return "C"


def add_prism(bm, a, b, r, segs=8):
    d = b - a
    L = d.length
    if L < 1e-4:
        return
    rot = d.normalized().to_track_quat("Z", "Y").to_matrix().to_4x4()
    mat = Matrix.Translation((a + b) / 2) @ rot
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segs,
                          radius1=r, radius2=r, depth=L, matrix=mat)


def add_sphere(bm, c, r):
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=r,
                              matrix=Matrix.Translation(c))


def material(name, color):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.diffuse_color = color
    return m


def stick_objects(rig, fwd_local, lengths):
    """(Re)construit la figure en bâtons de la pose courante (coordonnées monde). Les os
    feuilles ont une longueur devinée au réimport FBX : on prend la longueur exportée."""
    for o in [o for o in bpy.data.objects if o.name.startswith("stick_")]:
        me = o.data
        bpy.data.objects.remove(o)
        bpy.data.meshes.remove(me)
    mw = rig.matrix_world
    heads = {pb.name: mw @ pb.head for pb in rig.pose.bones}
    tails = {}
    for pb in rig.pose.bones:
        m = mw @ pb.matrix
        tails[pb.name] = heads[pb.name] + m.col[1].xyz.normalized() * lengths.get(pb.name, pb.length)
    groups = {"L": bmesh.new(), "R": bmesh.new(), "C": bmesh.new(), "M": bmesh.new()}
    for pb in rig.pose.bones:
        g = groups[side_of(pb.name)]
        if pb.parent is not None:
            add_prism(g, heads[pb.parent.name], heads[pb.name], 0.016)
        if not pb.children and pb.name != "Head":
            add_prism(g, heads[pb.name], tails[pb.name], 0.013)
        add_sphere(g, heads[pb.name], 0.022)
    hd = rig.pose.bones["Head"]
    hc = (heads["Head"] + tails["Head"]) / 2
    add_sphere(groups["C"], hc, 0.095)
    hm = (mw @ hd.matrix).to_3x3().normalized()
    add_sphere(groups["M"], hc + (hm @ fwd_local["Head"]).normalized() * 0.1, 0.03)
    sp = rig.pose.bones["Spine"]
    sm = (mw @ sp.matrix).to_3x3().normalized()
    sc = (heads["Spine"] + heads["Spine1"]) / 2
    add_sphere(groups["M"], sc + (sm @ fwd_local["Spine"]).normalized() * 0.13, 0.035)
    colors = {"L": LEFT, "R": RIGHT, "C": CENTER, "M": MARK}
    for k, bm in groups.items():
        me = bpy.data.meshes.new(f"stick_{k}")
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(f"stick_{k}", me)
        ob.color = colors[k]
        me.materials.append(material(f"mat_{k}", colors[k]))
        bpy.context.scene.collection.objects.link(ob)
    return heads


def build_stage(sc):
    sc.render.engine = "BLENDER_WORKBENCH"
    sh = sc.display.shading
    sh.light = "STUDIO"
    sh.color_type = "OBJECT"
    sh.show_shadows = True
    sh.shadow_intensity = 0.35
    sh.show_cavity = False
    w = bpy.data.worlds.new("bg")
    w.color = (0.93, 0.93, 0.9)
    sc.world = w
    try:
        sc.view_settings.view_transform = "Standard"
    except TypeError:
        pass
    sc.render.resolution_x = sc.render.resolution_y = 520
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "PNG"
    # sol : plan + grille 0,5 m + flèche avant Unity (+Z = -Y Blender)
    bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, -0.002))
    floor = bpy.context.object
    floor.color = (0.80, 0.80, 0.78, 1)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=80, y_subdivisions=80, size=40, location=(0, 0, 0))
    grid = bpy.context.object
    mod = grid.modifiers.new("w", "WIREFRAME")
    mod.thickness = 0.008
    grid.color = (0.55, 0.55, 0.53, 1)
    bm = bmesh.new()
    add_prism(bm, Vector((0, 0, 0.004)), Vector((0, -0.45, 0.004)), 0.012)
    add_sphere(bm, Vector((0, 0, 0.004)), 0.03)
    me = bpy.data.meshes.new("arrow")
    bm.to_mesh(me)
    bm.free()
    arrow = bpy.data.objects.new("arrow", me)
    arrow.color = (0.1, 0.6, 0.2, 1)
    sc.collection.objects.link(arrow)
    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 2.6
    cam = bpy.data.objects.new("cam", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam
    txt_data = bpy.data.curves.new("label", "FONT")
    txt_data.size = 0.075
    txt = bpy.data.objects.new("label", txt_data)
    txt.color = (0.05, 0.05, 0.05, 1)
    sc.collection.objects.link(txt)
    txt.parent = cam
    txt.location = (-1.25, 1.17, -1.0)
    return cam, txt


def render_sheet(clip, rig, png, lengths):
    sc = bpy.context.scene
    cam, txt = build_stage(sc)
    act = rig.animation_data.action
    f0, f1 = (int(round(v)) for v in act.frame_range)
    n = f1 - f0 + 1
    frames = preview_frames(n, clip.loop)
    # avant local (repos face à -Y) de la tête et du buste
    fwd_local = {nm: rig.data.bones[nm].matrix_local.to_3x3().inverted() @
                 (rig.matrix_world.to_3x3().inverted() @ FORWARD) for nm in ("Head", "Spine")}
    tmp = tempfile.mkdtemp(prefix="mocap_prev_")
    tiles = []
    for view in ("côté", "face"):
        row = []
        for j in frames:
            sc.frame_set(f0 + j)
            heads = stick_objects(rig, fwd_local, lengths)
            pts = list(heads.values())
            cx = (min(p.x for p in pts) + max(p.x for p in pts)) / 2
            cy = (min(p.y for p in pts) + max(p.y for p in pts)) / 2
            if view == "côté":
                cam.location = (cx + 8.0, cy, 0.95)
                cam.rotation_euler = (math.radians(90), 0, math.radians(90))
            else:
                cam.location = (cx, cy - 8.0, 0.95)
                cam.rotation_euler = (math.radians(90), 0, 0)
            txt.data.body = f"{clip.name}  {view}\nt={j / FPS:.2f}s  i={j}/{n - 1}"
            sc.render.filepath = os.path.join(tmp, f"{view}_{j}.png")
            bpy.ops.render.render(write_still=True)
            row.append(sc.render.filepath)
        tiles.append(row)
    # assemblage (numpy) : 2 rangées x 4 colonnes
    W = H = 520
    sheet = np.ones((H * len(tiles), W * len(tiles[0]), 4), dtype=np.float32)
    for r, row in enumerate(tiles):
        for c, p in enumerate(row):
            img = bpy.data.images.load(p)
            px = np.empty(W * H * 4, dtype=np.float32)
            img.pixels.foreach_get(px)
            px = px.reshape(H, W, 4)
            y0 = (len(tiles) - 1 - r) * H            # pixels Blender : de bas en haut
            sheet[y0:y0 + H, c * W:(c + 1) * W] = px
            bpy.data.images.remove(img)
            os.remove(p)
    os.rmdir(tmp)
    out = bpy.data.images.new("sheet", sheet.shape[1], sheet.shape[0], alpha=True)
    out.pixels.foreach_set(sheet.ravel())
    out.filepath_raw = png
    out.file_format = "PNG"
    os.makedirs(os.path.dirname(png), exist_ok=True)
    out.save()
    bpy.data.images.remove(out)


# =====================================================================================
# Sorties texte
# =====================================================================================

CLIP_BY_NAME = {c.name: c for c in CLIPS}


def clip_entry(clip, take_info, stats, checks):
    a, b = clip.frames
    e = {
        "name": clip.name,
        "file": f"{clip.name}.fbx",
        "source_take": clip.take,
        "frames": [a, b],
        "seconds": stats["seconds"],
        "loop": clip.loop,
        "category": clip.category,
        "description": clip.description,
        "fps": FPS,
        "frame_count": stats["frames_out"],
        "anchor": clip.anchor if clip.anchor != "self" else f"self ({clip.align})",
        "scale_m_per_bvh_unit": round(take_info["s"], 6),
        "hips_rest_height_bvh_units": round(take_info["hT"], 3),
        "floor_offset_cm": round(take_info["floor"] * take_info["s"] * 100, 2),
        "floor_measured_cm": round(take_info["floor_measured"] * take_info["s"] * 100, 2),
        "hips_start_unity_m": stats["hips_start_m"],
        "hips_end_unity_m": stats["hips_end_m"],
        "facing_start_deg": stats["facing_start_deg"],
        "facing_end_deg": stats["facing_end_deg"],
    }
    if "head" in take_info:
        e["head_yaw_recentered"] = take_info["head"]
    e["head_from_hips_end_unity_m"] = stats["head_from_hips_end_unity_m"]
    for k in ("speed_m_s", "advance_m", "seam_pose_rms_cm", "seam_hips_cm", "seam_yaw_deg",
              "seam_max_bone_deg", "seam_max_finger_deg", "retarget_max_err_mm"):
        if stats.get(k) is not None:
            e[k] = stats[k]
    if checks:
        e["checks"] = {k: v for k, v in checks.items() if k != "fbx"}
    return e


README = """# Mocap CMU — clips pour le corps de Mika

FBX produits par `{source}` (Blender 5.2, sans interface) à partir de la base de
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
{rows}

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

- Un FBX par clip, armature seule nommée `{rig}` (même hiérarchie et mêmes noms d'os
  partout), une prise (take) `{rig}|<nom>` à **30 i/s**, première image = image 0.
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
{bones}
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
blender -b --factory-startup --python {source} -- \\
    --bvh-dir ~/.cache/mika-mocap/cmu --out UnityFrontend/ArtSource/mocap
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
"""


def write_texts(out, entries, bones):
    path = os.path.join(out, "clips.json")
    old = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                old = {e["name"]: e for e in json.load(f).get("clips", [])}
        except (OSError, ValueError, KeyError):
            old = {}
    old.update({e["name"]: e for e in entries})
    ordered = [old[c.name] for c in CLIPS if c.name in old]
    doc = {
        "source": "Carnegie Mellon University Graphics Lab Motion Capture Database (mocap.cs.cmu.edu)",
        "bvh_conversion": "cgspeed / Bruce Hahne (MotionBuilder-friendly), github.com/una-dinosauria/cmu-mocap",
        "generator": SOURCE,
        "fps": FPS,
        "source_fps": SRC_FPS,
        "frames_convention": "indices d'image 0-based de la section MOTION du BVH ; 0 = pose T de cgspeed ; bornes incluses",
        "rest_pose": "pose T (image 0 du BVH), hanches à 0,95 m, face à +Z Unity",
        "rig_root": RIG_NAME,
        "bones": bones,
        "clips": ordered,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    rows = "\n".join(
        f"| `{e['file']}` | {e['source_take']} | {e['frames'][0]}–{e['frames'][1]} | {e['seconds']:.2f} s | "
        f"{'oui' if e['loop'] else 'non'} | {e['category']} |" for e in ordered)
    with open(os.path.join(out, "README.md"), "w", encoding="utf-8") as f:
        f.write(README.format(source=SOURCE, rig=RIG_NAME, rows=rows, bones=bone_tree(bones)))


def bone_tree(bones):
    lines = []
    depth = {}
    for b in bones:
        d = 0 if b["parent"] is None else depth[b["parent"]] + 1
        depth[b["name"]] = d
        lines.append("  " * d + b["name"])
    return "\n".join(lines)


# =====================================================================================
# Programme principal
# =====================================================================================

def main(argv):
    ap = argparse.ArgumentParser(prog="mocap_unity.py")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--bvh-dir", default=DEFAULT_BVH)
    ap.add_argument("--only", default="")
    ap.add_argument("--no-previews", action="store_true")
    ap.add_argument("--no-download", action="store_true")
    args = ap.parse_args(argv)
    out = os.path.abspath(args.out)
    wanted = [c for c in CLIPS if not args.only or c.name in args.only.split(",")]
    if args.only and len(wanted) != len(set(args.only.split(","))):
        raise RuntimeError(f"--only : clip inconnu dans {args.only!r}")
    # dépendances de placement
    need = []

    def add(c):
        kind, _, ref = c.anchor.partition(":")
        if kind in ("same", "end"):
            add(CLIP_BY_NAME[ref])
        if c not in need:
            need.append(c)
    for c in wanted:
        add(c)
    t0 = time.time()
    reset_scene()
    takes, placements, ends, results = {}, {}, {}, {}
    bones = None
    for c in need:
        if c.take not in takes:
            takes[c.take] = Take(c.take, ensure_bvh(c.take, args.bvh_dir, not args.no_download))
            tk = takes[c.take]
            log(f"prise {c.take} : {tk.n_frames} images, hanches pose T {tk.hT:.2f} u -> "
                f"échelle {tk.s:.5f} m/u ({tk.hT * CMU_UNIT_M:.3f} m en unités CMU), "
                f"sol {tk.floor * tk.s * 100:+.1f} cm")
        tk = takes[c.take]
        pl = clip_placement(c, takes, placements, ends)
        placements[c.name] = pl
        ends[c.name] = clip_end(c, tk, pl)
        if c not in wanted:
            continue
        rig = build_rig(tk)
        if bones is None:
            bones = [{"name": b.name, "parent": b.parent.name if b.parent else None} for b in rig.data.bones]
        stats, expected = bake(c, tk, rig, pl)
        path = os.path.join(out, f"{c.name}.fbx")
        export_fbx(rig, path)
        delete_rig(rig)
        tinfo = {"s": tk.s, "hT": tk.hT, "floor": tk.floor, "floor_measured": tk.floor_measured}
        if tk.head_twist is not None:
            seg = tk.head_twist[c.frames[0]:c.frames[1] + 1]
            tinfo["head"] = {"mode": HEAD_RECENTER[c.take],
                             "removed_yaw_deg": [round(float(-seg.max()), 1), round(float(-np.median(seg)), 1),
                                                 round(float(-seg.min()), 1)]}
        results[c.name] = (stats, expected, tinfo)
        log(f"{c.name}: {stats['frames_out']} images ({stats['seconds']:.2f} s) -> {path}")
    entries = []
    for c in wanted:
        stats, expected, tinfo = results[c.name]
        checks = None
        if not args.no_previews:
            reset_scene()
            rig, checks = verify(c, os.path.join(out, f"{c.name}.fbx"), expected, stats)
            render_sheet(c, rig, os.path.join(out, "previews", f"{c.name}.png"), stats.pop("_lengths"))
            log(f"{c.name}: vérifié {json.dumps({k: v for k, v in checks.items() if k != 'fbx'}, ensure_ascii=False)}")
            log(f"{c.name}: FBX {json.dumps(checks['fbx'], ensure_ascii=False, default=str)}")
        stats.pop("_lengths", None)
        entries.append(clip_entry(c, tinfo, stats, checks))
    if bones is None:
        bones = []
    write_texts(out, entries, bones)
    log(f"terminé en {time.time() - t0:.1f} s ({len(entries)} clips)")


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    try:
        main(argv)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
