# Portraits de Mika pour l'application Android : une image par émotion (visage + posture), plus ce que l'app superpose
# pour la faire vivre (les yeux fermés d'un clignement, découpés au plus juste).
#
# L'app n'a pas de moteur 3D : elle affiche ces images en fond de la conversation et passe de l'une à l'autre au fil de
# l'humeur que le serveur lui envoie (`speech`, `emotion_update`, `inner_state_update`). Tout ce qui fait le visage vient
# du client web, recopié ici à l'identique — un seul personnage, deux rendus :
#   - les recettes d'expressions (`EmotionController.PERULA_EMOTION_MAP`), jouées par leurs copies « propres »
#     (`faceRig.registerCleanGroups` : sans larmes, spirales, gouttes ni regard imposé) ;
#   - la physiologie au repos de l'émotion (`FacePhysiology` : rougeur, pupilles, yeux humides) ;
#   - le port de tête (`HeadEmotionOverlay.EMOTION_HEAD_POSE`).
# Le corps vient des mouvements de l'atelier (motions/*.json.gz, déjà posés au sol et nettoyés), figés sur l'image
# choisie ; la tête et les yeux sont ensuite tournés vers l'objectif, comme le fait `HeadAttentionOverlay` + `GazeController`.
#
# Le modèle est sous licence de l'acheteur : ni la scène, ni ces rendus ne sont versionnés. Ils sont écrits dans les
# assets de l'app, frontend/Android/app/src/main/assets/avatar/ (ignoré par git) ; sans eux, l'app n'affiche pas
# d'avatar. Format : `manifest.json` (taille, et par portrait son fichier, le milieu des yeux, l'incrustation du
# clignement et sa place), un WebP par portrait, un WebP sans perte par clignement.
#
#   blender -b frontend/Unity/ArtSource/atelier/mika_rig.blend --python frontend/Web/assets-src/blender/portraits.py -- \
#       [--only happy,sad] [--scale 50] [--out dossier] [--sheet idle_sad,gesture_think]
#
# `--sheet` ne rend pas les portraits : une planche par mouvement (previews/portrait_<clip>.png, 12 images en deux
# rangées, leurs numéros imprimés dans la console), pour choisir l'image à figer.
import argparse
import gzip
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atelier_lib as al  # noqa: E402

OUT = al.REPO / "frontend/Android/app/src/main/assets/avatar"
SIZE = (1080, 1440)
WEBP_QUALITY = 88

# --- le visage (client web) -----------------------------------------------------------------------------------------
# EmotionController.PERULA_EMOTION_MAP : groupes du modèle → poids à intensité 1.
FACE = {
    "neutral": {},
    "happy": {"Smile1": 1.0},
    "excited": {"Joy2": 0.9, "InWonder": 0.2},
    "love": {"Love1": 0.9},
    "proud": {"Prond": 0.9},
    "grateful": {"Smile2": 0.8, "Relaxy": 0.15},
    "playful": {"Smile4": 0.7, "Wink1": 0.25},
    "amused": {"LMAO": 0.8},
    "hopeful": {"Smile3": 0.5, "InWonder": 0.35},
    "relieved": {"Relaxy": 0.7, "Smile2": 0.2},
    "sad": {"Sad1": 0.85},
    "angry": {"Angry4": 0.7, "Angry1": 0.3},
    "scared": {"Shocked2": 0.7, "Pain": 0.25},
    "disgusted": {"Disgust": 0.85},
    "frustrated": {"Angry2": 0.6, "GiveUp": 0.25},
    "lonely": {"Sad3": 0.8},
    "anxious": {"Pain": 0.45, "Sad1": 0.25},
    "bored": {"Boring": 0.85},
    "jealous": {"BadSmile2": 0.5, "Angry2": 0.35},
    "surprised": {"Shocked": 0.9},
    "thinking": {"Numbly": 0.35, "Interesting": 0.15},
    "confused": {"Hau": 0.55},
    "embarrassed": {"Shy": 0.85},
    "nostalgic": {"Sad2": 0.3, "Smile2": 0.35, "Relaxy": 0.2},
    "dreamy": {"InWonder": 0.55, "Relaxy": 0.3},
    "determined": {"Healthy": 0.6, "Angry4": 0.2},
    "mischievous": {"BadSmile1": 0.65, "Taunt1": 0.2},
    "curious": {"Interesting": 0.75},
    "melancholic": {"Sad2": 0.55, "Relaxy": 0.2},
}
TIRED_GROUP = "Sleepy"

# faceRig.SYMBOL_MORPHS : ce que les groupes dessinent en plus d'un visage (larmes, rougeurs, sueur, yeux en spirale…).
SYMBOL_MORPHS = {
    "Tear", "Tear2", "TearFlow", "EyeWatery",
    "FaceRed", "FaceRed2", "FaceRed3",
    "FaceSweat", "FaceSweat2", "FaceShadow", "FaceShadow2", "FaceShadow3",
    "FaceSnot", "FaceSnotLong", "FaceSnotBubbles", "FaceSnotBubblesBig", "FaceSnotBubblesSmall",
    "Eye@@", "EyeStar", "EyeHeart", "EyeHeartSmall", "Eye><", "Eye0 0", "Eye0 0VSmall", "Eye0 0USmall",
    "EyeBlack", "EyeWhite", "EyeStare", "EyeHide", "EyeBlackCircles",
    "EyeIrisWhite", "EyeIrisClear", "EyeIrisSmall", "EyeIrisBig",
    "EyePupilBlackLine", "EyePupilCircle", "EyePupilSmall",
    "EyeHighlightHide", "EyeHighlightBig", "EyeHighlightDown", "EyeHighlightStar", "EyeHighlightHeart",
    "Mouth△", "Mouth^", "Mouthω", "Mouth□",
}

# FacePhysiology, à l'équilibre (l'émotion tenue) : rougeur × smoothstep(0.2, 0.9, i), pupilles × i × 0,6.
BLUSH = {
    "embarrassed": 0.95, "love": 0.75, "excited": 0.3, "amused": 0.3, "angry": 0.35, "grateful": 0.25,
    "playful": 0.2, "proud": 0.15, "jealous": 0.2, "frustrated": 0.18, "dreamy": 0.2, "happy": 0.12, "hopeful": 0.1,
}
PUPIL = {
    "love": 0.6, "scared": 0.7, "excited": 0.5, "surprised": 0.5, "curious": 0.45, "dreamy": 0.3, "hopeful": 0.25,
    "happy": 0.2, "thinking": 0.15, "angry": -0.5, "disgusted": -0.5, "frustrated": -0.3, "bored": -0.2,
}
# Les yeux brillent sans couler : une image fixe ne doit pas pleurer en permanence (le web ne fait couler une larme
# que si la tristesse dure).
WATERY = {"sad": 0.35, "lonely": 0.3, "melancholic": 0.2, "grateful": 0.15, "nostalgic": 0.15, "relieved": 0.1}

# HeadEmotionOverlay.EMOTION_HEAD_POSE (radians ; pitch > 0 baisse la tête, roll > 0 penche à droite, yaw > 0 à droite).
HEAD = {
    "curious": (-0.04, 0.10, 0.0), "thinking": (-0.02, 0.08, 0.03), "confused": (0.0, -0.10, 0.0),
    "embarrassed": (0.08, -0.05, -0.05), "proud": (-0.06, 0.0, 0.0), "determined": (-0.03, 0.0, 0.0),
    "sad": (0.08, 0.0, 0.0), "lonely": (0.06, 0.0, 0.0), "melancholic": (0.06, 0.03, 0.0),
    "surprised": (-0.05, 0.0, 0.0), "scared": (-0.03, 0.04, 0.0), "dreamy": (-0.02, 0.05, 0.0),
    "love": (0.0, 0.04, 0.0), "mischievous": (-0.02, 0.06, 0.05),
}


# --- la scène -------------------------------------------------------------------------------------------------------
def mika():
    return bpy.context.scene.objects["Mika"]


def dress():
    """Ses vrais vêtements (l'atelier la garde en tenue de répétition) et la chemise rentrée sous la veste."""
    scene = bpy.context.scene
    for name in al.LOOSE_CLOTHES:
        o = scene.objects.get(name)
        if o is not None:
            o.hide_set(False)
            o.hide_render = False
    body2 = scene.objects.get("Body2")
    if body2 is not None and bpy.data.materials.get("Body.001") is not None:
        body2.data.materials[0] = bpy.data.materials["Body.001"]
    shirt = scene.objects.get("ClothShirt")
    if shirt is not None and shirt.data.shape_keys:
        key = shirt.data.shape_keys.key_blocks.get("Cloth_Shrirt_CoatOn")
        if key is not None:
            key.value = 1.0


def stage(scale=100):
    """Caméra portrait à hauteur des yeux (objectif de 85 mm, décentrement vers le bas), lumière douce, fond transparent."""
    scene = bpy.context.scene
    cam = scene.objects.get("PortraitCam")
    if cam is None:
        cam = bpy.data.objects.new("PortraitCam", bpy.data.cameras.new("PortraitCam"))
        scene.collection.objects.link(cam)
    cam.data.lens = 85
    cam.data.sensor_fit = "AUTO"
    cam.data.sensor_width = 36
    cam.location = Vector((0.0, -2.2, 1.19))
    cam.rotation_euler = (math.radians(90), 0, 0)
    cam.data.shift_y = -0.25
    scene.camera = cam

    key = scene.objects.get("PortraitKey")
    if key is None:
        key = bpy.data.objects.new("PortraitKey", bpy.data.lights.new("PortraitKey", "SUN"))
        scene.collection.objects.link(key)
    key.data.energy = 2.0
    key.data.angle = math.radians(5)
    key.rotation_euler = (math.radians(55), 0, math.radians(-30))

    world = scene.world or bpy.data.worlds.new("PortraitWorld")
    scene.world = world
    world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs[0].default_value = (0.8, 0.8, 0.85, 1)
    bg.inputs[1].default_value = 0.6

    r = scene.render
    try:
        r.engine = "BLENDER_EEVEE"
    except TypeError:
        r.engine = "BLENDER_EEVEE_NEXT"
    r.film_transparent = True
    r.resolution_x, r.resolution_y = SIZE
    r.resolution_percentage = scale
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.eevee.taa_render_samples = 32
    return cam


# --- les expressions ------------------------------------------------------------------------------------------------
def expression_groups(arm):
    """
    Groupe du modèle → [(objet, clé de forme, poids)]. Lu sur le module VRM quand il est chargé, gardé sur l'armature
    pour Blender sans interface (même principe que `atelier_lib.vrm_map`).
    """
    ext = getattr(arm.data, "vrm_addon_extension", None)
    if ext is not None:
        groups = {
            g.name: [(b.mesh.mesh_object_name, b.index, float(b.weight)) for b in g.binds]
            for g in ext.vrm0.blend_shape_master.blend_shape_groups
        }
        if groups:
            arm.data["mika_expressions"] = json.dumps(groups)
            return groups
    return {k: [tuple(b) for b in v] for k, v in json.loads(arm.data["mika_expressions"]).items()}


def face_weights(groups, emotion, intensity, tired=0.0):
    """Clé de forme (objet, nom) → valeur : la recette de l'émotion, sans symboles ni regard, plus la physiologie."""
    weights = {}

    def add(obj, key, value):
        weights[(obj, key)] = min(1.0, weights.get((obj, key), 0.0) + value)

    recipe = dict(FACE[emotion])
    for group, w in recipe.items():
        for obj, key, bw in groups[group]:
            if key in SYMBOL_MORPHS or key.lower().startswith("eyelook"):
                continue
            add(obj, key, bw * w * intensity)
    if tired > 0:
        for obj, key, bw in groups[TIRED_GROUP]:
            if key in SYMBOL_MORPHS or key.lower().startswith("eyelook"):
                continue
            add(obj, key, bw * tired)
    t = max(0.0, min(1.0, (intensity - 0.2) / 0.7))
    add("Body", "FaceRed", BLUSH.get(emotion, 0.0) * t * t * (3 - 2 * t))
    pupil = PUPIL.get(emotion, 0.0) * intensity * 0.6
    for side in ("Left", "Right"):
        add("Body", f"EyeDilation{side}", max(0.0, pupil))
        add("Body", f"EyeConstrict{side}", max(0.0, -pupil))
    add("Body", "EyeWatery", WATERY.get(emotion, 0.0) * intensity)
    return weights


def set_face(weights, blink=0.0, groups=None):
    """Remet toutes les clés de forme du visage à zéro, puis applique `weights` (et le clignement)."""
    touched = {obj for obj, _ in weights} | {"Body"}
    if blink > 0 and groups is not None:
        weights = dict(weights)
        for obj, key, bw in groups["Blink"]:
            touched.add(obj)
            weights[(obj, key)] = min(1.0, weights.get((obj, key), 0.0) + bw * blink)
    for name in touched:
        o = bpy.context.scene.objects.get(name)
        if o is None or o.data.shape_keys is None:
            continue
        for kb in o.data.shape_keys.key_blocks[1:]:
            kb.value = 0.0
    for (obj, key), value in weights.items():
        o = bpy.context.scene.objects.get(obj)
        kb = o.data.shape_keys.key_blocks.get(key) if o is not None and o.data.shape_keys else None
        if kb is not None:
            kb.value = max(0.0, min(1.0, value))


# --- le corps -------------------------------------------------------------------------------------------------------
def load_motion(rig, name):
    """Un mouvement exporté par l'atelier, relu (même lecture que atelier_desk_check.load_motion)."""
    data = json.load(gzip.open(al.MOTIONS / f"{name}.json.gz", "rt"))
    frames = []
    for row in data["frames"]:
        d = {h: Quaternion(row[3 + 4 * k: 7 + 4 * k]) @ rig.rest[h].inverted() for k, h in enumerate(data["bones"])}
        frames.append({"hips": Vector(row[:3]), "d": d})
    return al.Motion(rig, name, frames, loop=data.get("loop", False))


def pose_frame(motion, i):
    """
    L'image i du mouvement, sur un squelette remis à zéro : `Motion.pose` ne touche qu'aux os humanoïdes, et les mèches
    tournées pour la pose précédente (`hang_hair`) garderaient sinon leur rotation, cumulée d'un rendu à l'autre.
    """
    for pb in motion.rig.arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    motion.pose(i)


def turn_bone(arm, name, q_world):
    """Tourne l'os `name` de `q_world` (rotation exprimée dans le monde), autour de sa tête."""
    pb = arm.pose.bones[name]
    m = arm.matrix_world @ pb.matrix
    loc = m.translation.copy()
    rotated = Matrix.Translation(loc) @ q_world.to_matrix().to_4x4() @ Matrix.Translation(-loc) @ m
    pb.matrix = arm.matrix_world.inverted() @ rotated
    bpy.context.view_layer.update()


def look_at_camera(arm, rig, cam, head_pose=(0.0, 0.0, 0.0), follow=0.6, eye_max=math.radians(10)):
    """
    Le port de tête de l'émotion, puis la tête qui suit l'objectif (une part, sur le cou et la tête) et les yeux qui
    font le reste — l'ordre du client web : HeadEmotionOverlay → HeadAttentionOverlay → GazeController.
    """
    head = rig.hmap["head"]
    neck = rig.hmap.get("neck")
    # Le repère de la tête : avant = -Y du monde au repos (Mika regarde -Y), tourné comme l'os.
    def head_frame():
        pb = arm.pose.bones[head]
        rest = arm.data.bones[head].matrix_local.to_quaternion()
        q = (arm.matrix_world @ pb.matrix).to_quaternion() @ rest.inverted()
        return q, (arm.matrix_world @ pb.matrix).translation

    pitch, roll, yaw = head_pose
    q, _ = head_frame()
    # Axes de Mika : droite = -X du monde au repos, avant = -Y, haut = +Z. pitch > 0 baisse le menton.
    right = q @ Vector((-1, 0, 0))
    fwd = q @ Vector((0, -1, 0))
    up = q @ Vector((0, 0, 1))
    emo = Quaternion(right, -pitch) @ Quaternion(up, -yaw) @ Quaternion(fwd, roll)
    turn_bone(arm, head, emo)

    # Vers l'objectif, une part seulement (le reste aux yeux) : 40 % de cette part au cou, le reste à la tête.
    def toward_camera():
        q, pos = head_frame()
        return (q @ Vector((0, -1, 0))).rotation_difference((cam.location - pos).normalized())

    if neck:
        turn_bone(arm, neck, Quaternion().slerp(toward_camera(), 0.4 * follow))
        turn_bone(arm, head, Quaternion().slerp(toward_camera(), 0.6 * follow / (1 - 0.4 * follow)))
    else:
        turn_bone(arm, head, Quaternion().slerp(toward_camera(), follow))

    # Les yeux, bornés comme le VRM l'annonce (10°).
    for eye in ("leftEye", "rightEye"):
        bone = rig.hmap.get(eye)
        if not bone:
            continue
        pb = arm.pose.bones[bone]
        m = arm.matrix_world @ pb.matrix
        q, _ = head_frame()
        fwd = q @ Vector((0, -1, 0))
        to_cam = (cam.location - m.translation).normalized()
        diff = fwd.rotation_difference(to_cam)
        axis, angle = diff.to_axis_angle()
        turn_bone(arm, bone, Quaternion(axis, max(-eye_max, min(eye_max, angle))))


HANGING_HAIR = ("HairTail", "HairSide")


def hair_roots(arm):
    """Racines des mèches longues (groupes de ressorts du VRM), gardées sur l'armature pour Blender sans interface."""
    ext = getattr(arm.data, "vrm_addon_extension", None)
    if ext is not None:
        roots = [b.bone_name for g in ext.vrm0.secondary_animation.bone_groups if g.comment in HANGING_HAIR
                 for b in g.bones if b.bone_name in arm.data.bones]
        if roots:
            arm.data["mika_hair_roots"] = json.dumps(roots)
            return roots
    return json.loads(arm.data["mika_hair_roots"])


def chain_end(bone):
    """Le bout de la mèche : la queue de l'os le plus loin en suivant le plus long des enfants."""
    def depth(b):
        return 1 + max((depth(c) for c in b.children), default=0)
    while bone.children:
        bone = max(bone.children, key=depth)
    return bone


def hang_hair(arm, rig, weight=0.85):
    """
    Les cheveux tombent. Le modèle livre ses ressorts sans gravité et, sur une image figée, rien ne les simule : une
    tête penchée emportait les longues mèches à l'horizontale. Chaque mèche longue reprend (à `weight` près) la
    direction qu'elle a sur le modèle debout, tournée seulement de l'orientation horizontale du buste — elle pend.
    """
    chest = rig.hmap.get("chest") or rig.hmap["spine"]
    rest_q = arm.data.bones[chest].matrix_local.to_quaternion()
    q = (arm.matrix_world @ arm.pose.bones[chest].matrix).to_quaternion() @ rest_q.inverted()
    fwd = q @ Vector((0, -1, 0))
    yaw = math.atan2(fwd.x, -fwd.y)
    turn = Quaternion(Vector((0, 0, 1)), yaw)
    for root in hair_roots(arm):
        end = chain_end(arm.data.bones[root])
        rest_vec = arm.matrix_world.to_3x3() @ (end.tail_local - arm.data.bones[root].head_local)
        head = arm.matrix_world @ arm.pose.bones[root].head
        tail = arm.matrix_world @ arm.pose.bones[end.name].tail
        diff = (tail - head).rotation_difference(turn @ rest_vec)
        turn_bone(arm, root, Quaternion().slerp(diff, weight))


# --- rendus ---------------------------------------------------------------------------------------------------------
def render(path):
    scene = bpy.context.scene
    path.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return path


def contact_sheet(rig, cam, name, count=12, scale=25):
    """Planche d'un mouvement au cadrage du portrait : `count` images réparties sur le clip (6 par rangée)."""
    import numpy as np

    scene = bpy.context.scene
    motion = load_motion(rig, name)
    n = len(motion.frames)
    picks = [round(i * (n - 1) / max(1, count - 1)) for i in range(count)]
    w = SIZE[0] * scale // 100
    h = SIZE[1] * scale // 100
    previous = scene.render.resolution_percentage
    scene.render.resolution_percentage = scale
    tiles = []
    tmp = al.WORKDIR / "previews" / "_portrait_tmp.png"
    for f in picks:
        pose_frame(motion, f)
        look_at_camera(mika(), rig, cam)
        hang_hair(mika(), rig)
        render(tmp)
        img = bpy.data.images.load(str(tmp))
        px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
        bpy.data.images.remove(img)
        # sur fond gris clair ; les numéros des images sont imprimés dans la console, dans l'ordre de la planche
        rgb = px[..., :3] * px[..., 3:4] + 0.82 * (1 - px[..., 3:4])
        tiles.append(np.concatenate([rgb, np.ones((h, w, 1), np.float32)], axis=2))
    cols = 6
    rows = [np.concatenate(tiles[i:i + cols] + [np.ones_like(tiles[0])] * (cols - len(tiles[i:i + cols])), axis=1)
            for i in range(0, len(tiles), cols)]
    sheet = np.concatenate(rows[::-1], axis=0)
    out = bpy.data.images.new(f"portrait_{name}", sheet.shape[1], sheet.shape[0], alpha=True)
    out.pixels = sheet.ravel()
    path = al.WORKDIR / "previews" / f"portrait_{name}.png"
    out.filepath_raw = str(path)
    out.file_format = "PNG"
    out.save()
    bpy.data.images.remove(out)
    scene.render.resolution_percentage = previous
    print(f"{name}: images {picks}")
    return path, picks


# --- les portraits --------------------------------------------------------------------------------------------------
# Un portrait par émotion (le nom est celui de l'émotion, ce que l'app reçoit), plus trois états qui n'en sont pas :
# « coucou » quand on la retrouve, « fatiguée » quand l'énergie est basse, « endormie ». Le corps est l'image d'un
# mouvement de l'atelier, choisie sur les planches (`--sheet`) : une posture qui se lit immobile, mains et tête comprises.
# `follow` : la part de l'angle vers l'objectif que la tête prend (0,6 par défaut, comme le web) — moins quand
# l'émotion baisse la tête ; `face` : un autre visage que celui de l'émotion ; `blink` : rendu les yeux fermés.
PORTRAITS = [
    dict(id="neutral", motion="idle_breathing", frame=0, intensity=0.0),
    dict(id="happy", motion="idle_happy", frame=16),
    dict(id="excited", motion="talk_heated", frame=454),
    dict(id="love", motion="gesture_bashful", frame=270),
    dict(id="proud", motion="talk_main", frame=0),
    dict(id="grateful", motion="gesture_excited", frame=161),
    dict(id="playful", motion="talk_heated", frame=113),
    dict(id="amused", motion="gesture_laugh", frame=107),
    dict(id="hopeful", motion="gesture_bashful", frame=60),
    dict(id="relieved", motion="gesture_sigh", frame=49),
    dict(id="sad", motion="idle_sad", frame=8, follow=0.5),
    dict(id="angry", motion="gesture_angry", frame=157),
    dict(id="scared", motion="gesture_surprised", frame=33),
    dict(id="disgusted", motion="gesture_headshake", frame=15),
    dict(id="frustrated", motion="gesture_angry", frame=470),
    dict(id="lonely", motion="idle_sad", frame=31, follow=0.5),
    dict(id="anxious", motion="idle_nervous", frame=137),
    dict(id="bored", motion="idle_bored", frame=87),
    dict(id="jealous", motion="gesture_angry", frame=105, follow=0.45),
    dict(id="surprised", motion="gesture_surprised", frame=55),
    dict(id="thinking", motion="gesture_think", frame=81),
    dict(id="confused", motion="gesture_think", frame=46),
    dict(id="embarrassed", motion="gesture_wave", frame=77, follow=0.45),
    dict(id="nostalgic", motion="gesture_bashful", frame=240),
    dict(id="dreamy", motion="idle_happy", frame=48),
    dict(id="determined", motion="gesture_excited", frame=107),
    dict(id="mischievous", motion="talk_heated", frame=284),
    dict(id="curious", motion="idle_happy", frame=24),
    dict(id="melancholic", motion="idle_sad", frame=0, follow=0.5),
    dict(id="wave", motion="gesture_wave", frame=39, face="happy", intensity=0.85),
    dict(id="tired", motion="gesture_yawn", frame=136, face="neutral", intensity=0.0, tired=1.0),
    dict(id="sleep", motion="idle_breathing", frame=0, face="neutral", intensity=0.0, tired=0.6, follow=0.0,
         head=(0.12, 0.16, 0.0), blink=1.0),
]
DEFAULT_INTENSITY = 1.0
# Différence (0-1, par canal) au-delà de laquelle un pixel appartient au clignement, marge autour, et fondu des bords
# de l'incrustation (en pixels) pour qu'elle se pose sur le portrait sans couture.
BLINK_THRESHOLD = 0.04
BLINK_PAD = 10
BLINK_FEATHER = 6


def pose_portrait(rig, cam, groups, spec, blink=0.0):
    arm = mika()
    motion = load_motion(rig, spec["motion"])
    pose_frame(motion, spec["frame"])
    emotion = spec.get("face", spec["id"])
    if emotion not in FACE:
        emotion = "neutral"
    head = spec.get("head", HEAD.get(emotion, (0.0, 0.0, 0.0)))
    look_at_camera(arm, rig, cam, head, follow=spec.get("follow", 0.6))
    hang_hair(arm, rig)
    intensity = spec.get("intensity", DEFAULT_INTENSITY)
    set_face(face_weights(groups, emotion, intensity, tired=spec.get("tired", 0.0)),
             blink=max(blink, spec.get("blink", 0.0)), groups=groups)


def pixels(path):
    """Les pixels d'une image (rangées du haut vers le bas), valeurs 0-1 telles qu'écrites dans le fichier."""
    import numpy as np

    img = bpy.data.images.load(str(path))
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[::-1]
    bpy.data.images.remove(img)
    return px


def save_webp(px, path, quality=WEBP_QUALITY):
    """Écrit des pixels (rangées du haut vers le bas) en WebP, sans conversion de couleur."""
    path.parent.mkdir(parents=True, exist_ok=True)
    h, w = px.shape[:2]
    img = bpy.data.images.new(path.stem, w, h, alpha=True, float_buffer=False)
    img.pixels = px[::-1].ravel()
    img.file_format = "WEBP"
    img.filepath_raw = str(path)
    img.save(filepath=str(path), quality=quality)
    bpy.data.images.remove(img)


def blink_patch(open_px, closed_px):
    """
    Ce que le clignement change, découpé au plus juste : la boîte des pixels qui diffèrent, plus une marge, l'alpha
    fondu vers les bords. Rien quand les yeux étaient déjà fermés.
    """
    import numpy as np

    diff = np.abs(open_px - closed_px).max(axis=2) > BLINK_THRESHOLD
    if diff.sum() < 20:
        return None
    ys, xs = np.nonzero(diff)
    h, w = diff.shape
    y0, y1 = max(0, ys.min() - BLINK_PAD), min(h, ys.max() + 1 + BLINK_PAD)
    x0, x1 = max(0, xs.min() - BLINK_PAD), min(w, xs.max() + 1 + BLINK_PAD)
    crop = closed_px[y0:y1, x0:x1].copy()
    # Masque : la zone qui change, élargie puis adoucie (flou en boîte répété), multipliée dans l'alpha.
    mask = diff[y0:y1, x0:x1].astype(np.float32)
    k = BLINK_FEATHER
    for _ in range(2):
        padded = np.pad(mask, k, mode="constant")
        csum = padded.cumsum(0).cumsum(1)
        csum = np.pad(csum, ((1, 0), (1, 0)))
        size = 2 * k + 1
        box = (csum[size:, size:] - csum[:-size, size:] - csum[size:, :-size] + csum[:-size, :-size]) / size ** 2
        mask = np.minimum(1.0, box * 3.0)
    crop[..., 3] *= mask
    return crop, (int(x0), int(y0))


def face_center(cam, arm, rig):
    """Le milieu des yeux dans l'image, en fraction de la largeur et de la hauteur (0,0 en haut à gauche)."""
    from bpy_extras.object_utils import world_to_camera_view

    scene = bpy.context.scene
    eyes = [arm.matrix_world @ arm.pose.bones[rig.hmap[e]].head for e in ("leftEye", "rightEye")]
    p = world_to_camera_view(scene, cam, (eyes[0] + eyes[1]) / 2)
    return round(p.x, 4), round(1 - p.y, 4)


def render_portraits(only=None, scale=100, out=None):
    """Rend les portraits dans `out` (OUT par défaut, en WebP) et écrit `out`/manifest.json, que l'app lit."""
    import time

    out = Path(out) if out else OUT

    dress()
    cam = stage(scale)
    arm = mika()
    rig = al.Rig(arm)
    groups = expression_groups(arm)
    tmp = al.WORKDIR / "previews" / "_portrait"
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() and only else {"portraits": {}}
    w = SIZE[0] * scale // 100
    h = SIZE[1] * scale // 100
    # Un rendu partiel complète le manifeste : à une autre taille, les positions des autres portraits mentiraient.
    if only and manifest.get("width", w) != w:
        raise SystemExit(f"{out} est rendu en {manifest['width']}x{manifest['height']} : --scale doit le suivre "
                         f"(ou rendre tous les portraits)")
    for spec in PORTRAITS:
        if only and spec["id"] not in only:
            continue
        t = time.time()
        pose_portrait(rig, cam, groups, spec)
        center = face_center(cam, arm, rig)
        open_px = pixels(render(tmp.with_suffix(".open.png")))
        save_webp(open_px, out / f"{spec['id']}.webp")
        entry = {"file": f"{spec['id']}.webp", "face": center}
        if spec.get("blink", 0.0) < 1.0:
            pose_portrait(rig, cam, groups, spec, blink=1.0)
            closed_px = pixels(render(tmp.with_suffix(".closed.png")))
            patch = blink_patch(open_px, closed_px)
            if patch is not None:
                crop, (x, y) = patch
                save_webp(crop, out / f"{spec['id']}.blink.webp", quality=100)
                entry["blink"] = {"file": f"{spec['id']}.blink.webp", "x": x, "y": y,
                                  "w": int(crop.shape[1]), "h": int(crop.shape[0])}
        manifest["portraits"][spec["id"]] = entry
        print(f"portrait {spec['id']}: {time.time() - t:.1f} s")
    manifest.update({"version": 1, "width": w, "height": h})
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    return manifest_path


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Portraits de Mika pour l'application Android")
    parser.add_argument("--only", default="", help="identifiants séparés par des virgules (happy,sad…)")
    parser.add_argument("--sheet", default="", help="planches de mouvements à rendre au lieu des portraits")
    parser.add_argument("--scale", type=int, default=100, help="taille en pourcentage de %dx%d" % SIZE)
    parser.add_argument("--out", default="", help="dossier de sortie (par défaut les assets de l'app)")
    args = parser.parse_args(argv)
    # Le module VRM donne les groupes d'expressions et les ressorts ; sans interface, Blender ne le charge pas seul.
    try:
        import addon_utils

        addon_utils.enable("bl_ext.blender_org.vrm", default_set=False, persistent=False)
    except Exception as exc:  # la copie gardée sur l'armature prend le relais
        print(f"module VRM indisponible ({exc})")
    if args.sheet:
        dress()
        cam = stage()
        rig = al.Rig(mika())
        for name in args.sheet.split(","):
            contact_sheet(rig, cam, name.strip())
        return
    only = {s.strip() for s in args.only.split(",") if s.strip()} or None
    print(render_portraits(only, args.scale, args.out or None))


if __name__ == "__main__":
    main()
