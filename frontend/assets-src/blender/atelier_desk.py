# Atelier d'animation de Mika — au bureau : taper, la souris, écrire, lire, boire, prendre un objet, réfléchir,
# s'étirer, pivoter la chaise vers quelqu'un. Les mouvements sont construits ici (pas de capture) sur son squelette,
# assise sur sa chaise, devant son bureau tel qu'Unity le relève (UnityFrontend/ArtSource/atelier/desk_layout.json),
# puis exportés comme les autres (motions/desk_*.json.gz → « Importer les mouvements de l'atelier Blender »).
#
#   blender -b UnityFrontend/ArtSource/atelier/mika_rig.blend --python frontend/assets-src/blender/atelier_desk.py -- \
#       [--only desk_type,desk_write] [--no-previews]
#
# Le repère de travail : elle est assise, hanches à l'origine (x, y) — Blender : elle regarde −Y, sa gauche est +X —,
# la chaise tournée et avancée (par Unity) pour que l'objet de l'occupation soit droit devant elle à la distance
# prévue ici (le clavier à 43 cm des hanches, le carnet à 38 cm). Les hauteurs sont celles du clip : le sol du clip
# est 2 cm sous le vrai (Unity monte la racine de 2 cm pour poser ses hanches à 0,59 m, le siège de sa chaise).
#
# Sa taille compte : assise, ses épaules ne sont qu'à 11 cm au-dessus du bureau (76 cm, une chaise à 59 cm) — les
# avant-bras se posent sur le bureau, les coudes au bord, le buste un peu penché ; c'est ainsi qu'une personne
# menue tape à un bureau d'adulte.
#
# Les briques : IK des bras (le coude cherché sur son cercle vers un point donné, l'avant-bras partagé entre le coude
# et la main pour la torsion), orientation des mains (doigts, paume), courbure des doigts (par phalange), regard
# (cou et tête), buste (penché, tourné), souffle. Une boucle se referme d'elle-même : tout ce qui bouge est périodique.
import argparse
import math
import random
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atelier_lib as al  # noqa: E402

FPS = 30
TAU = 2 * math.pi
FINGERS = ("Index", "Middle", "Ring", "Little")

# --- le bureau, dans le repère de travail (clip) -------------------------------------------------------------------
# Relevé dans Unity (desk_layout.json, repère du siège) : clavier 20 cm à droite et 60 cm devant, écran dans son axe,
# bord du bureau à 40 cm. Pour taper, la chaise pivote de WORK_YAW vers l'écran et avance de WORK_ROLL : le clavier
# est alors à 39 cm devant elle, 8 cm à sa droite, et le bord du bureau à 15 cm de ses hanches — en biais (plus près
# à gauche). Unity calcule le même pivot et le même roulement d'après la position réelle du clavier.
WORK_YAW = 19.4          # degrés, vers sa droite
WORK_ROLL = 0.255        # m, vers le bureau
DESK_TOP = 0.74          # 0,76 réel − 2 cm
DESK_EDGE = -0.148       # le bord avant, droit devant les hanches
KEYBOARD = dict(center=Vector((-0.08, -0.39, 0.760)), size=(0.46, 0.15, 0.03))
KEY_TOP = 0.775
# La souris à droite du clavier, à 30 cm devant elle : à 36, sa paume n'arrivait pas dessus (le bras tendu au
# maximum, elle est petite).
MOUSE = dict(center=Vector((-0.36, -0.30, 0.747)), size=(0.06, 0.10, 0.04))
MONITOR = dict(center=Vector((-0.067, -0.74, 1.186)), size=(0.66, 0.03, 0.39))
# Le carnet, le stylo et la tasse : pris sur la vraie pièce (atelier_desk_gestures.Geo, atelier_decor.features).
BOOK = dict(size=(0.25, 0.19, 0.028))   # les livres du bureau (fermés : Unity les tient tels quels)


# --- outils de pose ------------------------------------------------------------------------------------------------
def basis(u, n):
    """La rotation qui envoie le repère (x = u, y = n, z = u × n) — deux directions orthogonalisées."""
    u = u.normalized()
    n = (n - u * n.dot(u)).normalized()
    w = u.cross(n)
    return Matrix((u, n, w)).transposed().to_quaternion()


def frame_map(u0, n0, u, n):
    """La rotation (monde) qui amène la paire de directions (u0, n0) sur (u, n)."""
    return basis(u, n) @ basis(u0, n0).inverted()


class Desk:
    """Ce que l'atelier sait du squelette pour le bureau : repos, longueurs, axes des doigts."""

    def __init__(self, rig):
        self.rig = rig
        arm = rig.arm
        w = rig.world

        def head(h):
            return w @ arm.data.bones[rig.hmap[h]].head_local

        def tail(h):
            return w @ arm.data.bones[rig.hmap[h]].tail_local

        self.rest_dir = {h: (tail(h) - head(h)).normalized() for h in rig.hmap}
        self.palm0 = Vector((0.0, 0.0, -1.0))   # pose T du VRM : paumes vers le bas
        self.seated = None

    def hinge0(self, side):
        """L'axe du coude au repos : bras tendu sur le côté, l'avant-bras plie vers l'avant (−Y)."""
        u = self.rest_dir[f"{side}UpperArm"]
        return u.cross(Vector((0.0, -1.0, 0.0))).normalized()


def seated_base(rig):
    """La pose assise de départ : bassin et jambes de son assise (sitting_idle de l'atelier), le reste au repos."""
    import gzip
    import json

    data = json.load(gzip.open(al.MOTIONS / "sitting_idle.json.gz", "rt"))
    row = data["frames"][0]
    d = {h: Quaternion(row[3 + 4 * k: 7 + 4 * k]) @ rig.rest[h].inverted() for k, h in enumerate(data["bones"])}
    keep = ("hips", "UpperLeg", "LowerLeg", "Foot", "Toes")
    base = {h: (q if any(k in h for k in keep) else Quaternion()) for h, q in d.items()}
    return {"hips": Vector(row[:3]), "d": base}


def copy(frame):
    return {"hips": frame["hips"].copy(), "d": {h: q.copy() for h, q in frame["d"].items()}}


def lean(frame, forward_deg, turn_deg=0.0, side_deg=0.0, bones=("spine", "chest")):
    """Le buste : penché vers l'avant, tourné (positif : vers sa gauche), incliné sur le côté (positif : vers sa
    gauche), réparti sur la colonne ; tout ce qui est au-dessus suit (cou, tête, épaules, bras)."""
    n = len(bones)
    q = (Quaternion((0.0, 0.0, 1.0), math.radians(turn_deg / n)) @
         Quaternion((0.0, 1.0, 0.0), math.radians(side_deg / n)) @
         Quaternion((1.0, 0.0, 0.0), math.radians(forward_deg / n)))
    upper = [h for h in frame["d"] if h != "hips" and not any(p in h for p in al.LEG_PARTS)]
    acc = Quaternion()
    for b in bones:
        acc = q @ acc
        # Chaque os de la colonne prend sa part ; ce qui est au-dessus du dernier prend le tout.
        frame["d"][b] = acc @ frame["d"][b]
    for h in upper:
        if h not in bones:
            frame["d"][h] = acc @ frame["d"][h]


def shrug(frame, side, up_deg):
    """L'épaule qui monte (positif) ou descend."""
    s = f"{side}Shoulder"
    axis = Vector((0.0, -1.0, 0.0)) if side == "left" else Vector((0.0, 1.0, 0.0))
    q = Quaternion(axis, math.radians(up_deg))
    for h in list(frame["d"]):
        if h == s or (h.startswith(side) and any(k in h for k in ("UpperArm", "LowerArm", "Hand", "Thumb", "Index", "Middle", "Ring", "Little"))):
            frame["d"][h] = q @ frame["d"][h]


def hand_rotation(desk, side, fingers_dir, palm):
    """L'orientation (delta monde) d'une main doigts vers `fingers_dir`, paume vers `palm`."""
    return frame_map(desk.rest_dir[f"{side}Hand"], desk.palm0, fingers_dir, palm)


def arm_ik(desk, frame, side, wrist, elbow_hint, fingers_dir, palm, twist_share=0.5, hand_rot=None):
    """
    Le bras de ce côté amène le poignet sur `wrist`, le coude au plus près de `elbow_hint` (sur le cercle que les
    longueurs permettent), la main orientée doigts vers `fingers_dir`, paume vers `palm`. Chaque os reçoit son
    orientation monde complète (direction + torsion) : le bras et l'avant-bras gardent l'axe du coude, l'avant-bras
    prend `twist_share` de la torsion de la main.
    """
    rig = desk.rig
    up, lo, hd = f"{side}UpperArm", f"{side}LowerArm", f"{side}Hand"
    j = rig.joints(frame, (up, lo, hd))
    s, e, w = j[up], j[lo], j[hd]
    l1, l2 = (e - s).length, (w - e).length
    to = wrist - s
    dist = min(max(to.length, abs(l1 - l2) + 1e-4), l1 + l2 - 1e-4)
    axis = to.normalized()
    a = (l1 * l1 - l2 * l2 + dist * dist) / (2 * dist)
    r = math.sqrt(max(0.0, l1 * l1 - a * a))
    center = s + axis * a
    h = elbow_hint - center
    h -= axis * h.dot(axis)
    if h.length < 1e-6:
        h = Vector((0.0, 0.0, -1.0)) - axis * axis.z
    h.normalize()
    elbow = center + h * r
    w_new = s + axis * dist
    u = elbow - s
    v = w_new - elbow
    # L'axe du coude : celui du plan de pliage choisi (h × axe), stable même bras presque tendu — tiré de u × v,
    # il s'inversait quand le bras se tendait vers la tasse (l'avant-bras faisait un demi-tour en une image).
    n = h.cross(axis).normalized()
    # Le repos : bras et avant-bras le long de l'axe du bras, axe du coude hinge0 ; la main : doigts le long, paume en bas.
    u0 = desk.rest_dir[up]
    n0 = desk.hinge0(side)
    frame["d"][up] = frame_map(u0, n0, u, n)
    # La main.
    f0 = desk.rest_dir[hd]
    hand = hand_rot.copy() if hand_rot is not None else frame_map(f0, desk.palm0, fingers_dir, palm)
    frame["d"][hd] = hand
    # L'avant-bras : son axe, et une torsion partagée entre le coude (n) et la paume (ramenée autour de v).
    p_hand = hand @ (n0 - f0 * n0.dot(f0))  # l'axe du coude au repos, porté par la main
    p_hand -= v.normalized() * p_hand.dot(v.normalized())
    n_proj = n - v.normalized() * n.dot(v.normalized())
    if p_hand.length > 1e-6 and n_proj.length > 1e-6:
        # La part de la torsion de la main que prend l'avant-bras, par le plus court chemin autour de son axe.
        twist = n_proj.normalized().rotation_difference(p_hand.normalized())
        n_lo = Quaternion().slerp(twist, twist_share) @ n_proj.normalized()
    else:
        n_lo = n
    frame["d"][lo] = frame_map(desk.rest_dir[lo], n0, v, n_lo)
    # Les doigts suivent la main (leur courbure est posée par curl()).
    for k in frame["d"]:
        if k.startswith(side) and any(x in k for x in FINGERS + ("Thumb",)):
            frame["d"][k] = hand.copy()
    return elbow


def curl(desk, frame, side, fingers, thumb=(10.0, 10.0, 5.0), spread=0.0):
    """
    Les doigts pliés : `fingers` = {« Index »: (proximale, intermédiaire, distale) en degrés, …} ; le pouce à part.
    À appeler après arm_ik (chaque phalange part de l'orientation de la main). `spread` écarte les doigts (degrés).
    """
    hand = frame["d"][f"{side}Hand"]
    f0 = desk.rest_dir[f"{side}Hand"]
    axis = f0.cross(desk.palm0).normalized()         # plier = tourner les doigts vers la paume
    spread_axis = desk.palm0                           # écarter = tourner dans le plan de la paume
    for i, name in enumerate(FINGERS):
        angles = fingers.get(name, (0.0, 0.0, 0.0))
        fan = (i - 1.5) / 1.5 * spread * (1 if side == "left" else -1)
        acc = Quaternion(spread_axis, math.radians(fan))
        for part, ang in zip(("Proximal", "Intermediate", "Distal"), angles):
            acc = Quaternion(axis, math.radians(ang)) @ acc
            b = f"{side}{name}{part}"
            if b in frame["d"]:
                frame["d"][b] = hand @ acc
    t0 = desk.rest_dir.get(f"{side}ThumbProximal", f0)
    t_axis = t0.cross(desk.palm0).normalized()
    acc = Quaternion()
    for part, ang in zip(("Proximal", "Intermediate", "Distal"), thumb):
        acc = Quaternion(t_axis, math.radians(ang)) @ acc
        b = f"{side}Thumb{part}"
        if b in frame["d"]:
            frame["d"][b] = hand @ acc


def look(desk, frame, target, neck_share=0.35, limit=70.0):
    """Le regard vers `target` : le cou en prend `neck_share`, la tête le reste ; la tête garde l'horizon."""
    rig = desk.rig
    j = rig.joints(frame, ("head",))
    eye = j["head"] + Vector((0.0, -0.06, 0.07))
    fwd = frame["d"]["head"] @ Vector((0.0, -1.0, 0.0))
    want = (target - eye).normalized()
    q = fwd.rotation_difference(want)
    ang = math.degrees(q.angle)
    if ang > limit:
        q = Quaternion(q.axis, math.radians(limit))
    neck = Quaternion().slerp(q, neck_share)
    frame["d"]["neck"] = neck @ frame["d"]["neck"]
    head = q @ frame["d"]["head"]
    # Pas de tête de travers : l'axe gauche-droite de la tête reste horizontal.
    right = head @ Vector((1.0, 0.0, 0.0))
    level = Vector((right.x, right.y, 0.0))
    if level.length > 1e-6:
        head = right.rotation_difference(level.normalized()) @ head
    frame["d"]["head"] = head


def noise(t, period, seed, harmonics=3):
    """Un bruit doux et périodique (somme de sinus de période period/k) — une boucle se referme d'elle-même."""
    rnd = random.Random(seed)
    v = 0.0
    for k in range(1, harmonics + 1):
        v += math.sin(TAU * k * t / period + rnd.uniform(0, TAU)) / k
    return v / 1.83


def bump(t, start, length):
    """0 → 1 → 0 en douceur sur [start, start + length] (une frappe, un clic)."""
    x = (t - start) / length
    if x <= 0 or x >= 1:
        return 0.0
    return math.sin(math.pi * x) ** 2


def ease(t, a, b):
    """0 avant a, 1 après b, en douceur entre les deux."""
    if t <= a:
        return 0.0
    if t >= b:
        return 1.0
    x = (t - a) / (b - a)
    return x * x * (3 - 2 * x)


# --- les clips -----------------------------------------------------------------------------------------------------
def desk_type(desk, t, period):
    """Taper : par rafales (deux phrases par boucle), les doigts qui frappent, un coup d'œil aux touches."""
    f = copy(desk.seated)
    breathe = math.sin(TAU * 2 * t / period)
    # Le buste penché sur le clavier, un peu tourné vers lui (8 cm à sa droite).
    lean(f, 16.0 + 0.6 * breathe, turn_deg=-6.0 + 1.5 * noise(t, period, 1))
    bursts = ((0.3, 3.4), (4.6, 7.4))
    typing = max(ease(t, a, a + 0.25) * (1 - ease(t, b - 0.25, b)) for a, b in bursts)
    kc = KEYBOARD["center"]
    for side, sx in (("left", 1.0), ("right", -1.0)):
        rnd = random.Random(7 if side == "left" else 11)
        drift = Vector((0.012 * noise(t, period, 3 + sx), 0.01 * noise(t, period, 5 + sx), 0.0))
        # Les poignets au-dessus du bord proche du clavier, les avant-bras posés sur le bureau.
        wrist = Vector((kc.x + sx * 0.085, kc.y + 0.075, 0.788)) + drift * typing
        # Entre deux rafales, les poignets reculent un peu et se posent.
        wrist += Vector((0.0, 0.015, -0.006)) * (1 - typing)
        elbow = Vector((sx * 0.13, -0.15, 0.765))
        fingers_dir = Vector((-sx * 0.22, -1.0, -0.10))
        palm = Vector((-sx * 0.35, 0.0, -1.0))
        arm_ik(desk, f, side, wrist, elbow, fingers_dir, palm)
        base = {"Index": (22.0, 32.0, 14.0), "Middle": (24.0, 34.0, 15.0), "Ring": (26.0, 34.0, 15.0), "Little": (28.0, 32.0, 14.0)}
        # Le poignet monte d'autant qu'il faut pour que, doigts au repos, leur pulpe touche le dessus des touches (le
        # poignet à 1,3 cm au-dessus du clavier enfonçait le bout des doigts de 2 cm dedans).
        curl(desk, f, side, base, thumb=(18.0, 12.0, 8.0), spread=4.0)
        low = min(p.z for p in fingertips(desk, f, side)) - FINGER_PAD - UNITY_FINGER_DROP
        if low < KEY_TOP:
            wrist = wrist + Vector((0.0, 0.0, KEY_TOP - low))
            arm_ik(desk, f, side, wrist, elbow, fingers_dir, palm)
        # Les frappes : un doigt à la fois, pour un tempo de 6 à 8 touches/s à deux mains.
        taps = []
        for a, b in bursts:
            x = a + rnd.uniform(0.05, 0.2)
            while x < b - 0.15:
                taps.append((x, rnd.choice(FINGERS)))
                x += rnd.uniform(0.18, 0.42)
        pose = {}
        for name, (p, i, d) in base.items():
            # Une frappe : la pulpe ne descend que de la course d'une touche (quelques millimètres) — plus, le doigt
            # entrait dans le clavier (ses touches ne s'enfoncent pas dans le jeu).
            press = sum(bump(t, x, 0.12) for x, fn in taps if fn == name)
            pose[name] = (p + 5.0 * press, i + 2.5 * press, d)
        thumb_press = sum(bump(t, x, 0.14) for x, fn in taps if fn == "Index") * 0.3
        curl(desk, f, side, pose, thumb=(18.0, 12.0 + 10 * thumb_press, 8.0), spread=4.0)
    # Le regard : l'écran, des lignes qui se lisent, un coup d'œil aux touches au milieu de la boucle.
    screen = MONITOR["center"] + Vector((0.12 * noise(t, period, 9), 0.0, 0.05 * noise(t, period, 13)))
    keys = kc + Vector((0.0, 0.02, 0.02))
    g = bump(t, 3.5, 1.0)
    look(desk, f, screen.lerp(keys, g))
    return f


FINGER_PAD = 0.007      # du bout de l'os de la dernière phalange à la pulpe qui touche
# Dans Unity, un doigt n'a qu'un muscle de flexion par phalange : une part de la courbure du clip se perd au passage en
# muscles et le bout des doigts arrive plus bas que dans l'atelier (mesuré sur desk_type, avatar nu : 7 mm, et le siège
# du jeu 3 mm plus bas). Une pulpe posée sur une surface l'est donc d'autant plus haut ici.
UNITY_FINGER_DROP = 0.008


def fingertips(desk, frame, side):
    """Le bout de chaque doigt (le bout de l'os de sa dernière phalange), au monde."""
    rig = desk.rig
    pose = rig.fk(frame)
    out = []
    for name in ("Index", "Middle", "Ring", "Little", "Thumb"):
        h = f"{side}{name}Distal"
        if h not in rig.hmap:
            continue
        b = rig.arm.data.bones[rig.hmap[h]]
        length = ((rig.world @ b.tail_local) - (rig.world @ b.head_local)).length
        m = pose[rig.hmap[h]]
        out.append(m.translation + m.to_3x3() @ Vector((0.0, length, 0.0)))
    return out


def hand_matrix(desk, frame, side):
    """La matrice monde de la main (os de la main) pour cette image."""
    rig = desk.rig
    return rig.fk(frame)[rig.hmap[f"{side}Hand"]].copy()


def relaxed(desk, f, side, amount=1.0):
    """Des doigts au repos, à demi pliés."""
    k = amount
    curl(desk, f, side, {"Index": (12 * k, 18 * k, 8 * k), "Middle": (15 * k, 20 * k, 9 * k), "Ring": (18 * k, 22 * k, 10 * k),
                         "Little": (22 * k, 24 * k, 10 * k)}, thumb=(10 * k, 8 * k, 4 * k), spread=3.0)


def rest_arms(desk, f, t, period, which=("left", "right")):
    """Les mains posées sur le bureau, près du bord, avant-bras sur le plateau ; le bout des doigts s'arrête avant le
    clavier (posées 8 cm plus loin, ses doigts reposaient sur son bord — dedans, une fois mesuré)."""
    for side, sx in (("left", 1.0), ("right", -1.0)):
        if side not in which:
            continue
        wrist = Vector((sx * 0.115 - 0.02, -0.175, 0.765)) + Vector((0.006 * noise(t, period, 21 + sx), 0.006 * noise(t, period, 23 + sx), 0.0))
        arm_ik(desk, f, side, wrist, Vector((sx * 0.16, -0.13, 0.75)), Vector((-sx * 0.35, -1.0, -0.05)), Vector((-sx * 0.15, 0.0, -1.0)))
        relaxed(desk, f, side)


def desk_rest(desk, t, period):
    """Au bureau, sans rien faire : les mains posées, le regard sur l'écran qui flâne, le souffle."""
    f = copy(desk.seated)
    breathe = math.sin(TAU * 2 * t / period)
    lean(f, 9.0 + 0.8 * breathe, turn_deg=-3.0 + 3.0 * noise(t, period, 31))
    rest_arms(desk, f, t, period)
    target = MONITOR["center"] + Vector((0.18 * noise(t, period, 33), 0.0, 0.08 * noise(t, period, 35)))
    # Une fois par boucle, un regard vers la pièce (à sa gauche).
    away = bump(t, 4.5, 2.2)
    target = target.lerp(Vector((1.2, -0.4, 1.05)), away * 0.8)
    look(desk, f, target)
    return f


def desk_mouse(desk, t, period):
    """La souris : la main droite dessus (petits déplacements, clics), la gauche posée au bord du clavier."""
    f = copy(desk.seated)
    breathe = math.sin(TAU * 2 * t / period)
    lean(f, 15.0 + 0.6 * breathe, turn_deg=-9.0, side_deg=-5.0)
    # La paume sur le dos de la souris, les doigts sur ses boutons : le poignet juste au-dessus de son arrière (le
    # poignet 7,5 cm derrière son centre posait la paume sur le tapis, derrière elle). La souris suit la main (Unity :
    # BodyActivity.CarryMouse).
    mc = MOUSE["center"]
    move = Vector((0.02 * noise(t, period, 41), 0.015 * noise(t, period, 43), 0.0))
    wrist = mc + Vector((0.0, 0.048, 0.045)) + move
    arm_ik(desk, f, "right", wrist, Vector((-0.22, -0.12, 0.76)), Vector((0.10, -1.0, -0.30)), Vector((0.30, 0.0, -1.0)))
    clicks = (0.8, 2.1, 2.4, 3.9, 5.2)
    press = sum(bump(t, c, 0.14) for c in clicks)
    curl(desk, f, "right", {"Index": (14 + 12 * press, 16, 8), "Middle": (18, 18, 8), "Ring": (26, 26, 10), "Little": (30, 28, 12)},
         thumb=(22.0, 10.0, 6.0), spread=2.0)
    rest_arms(desk, f, t, period, which=("left",))
    look(desk, f, MONITOR["center"] + Vector((0.2 * noise(t, period, 45), 0.0, 0.08 * noise(t, period, 47))))
    # La souris dans le sens de la main : son grand axe (la boîte de contrôle : Y) suit la direction des doigts, à plat.
    j = desk.rig.joints(f, ("rightHand", "rightMiddleProximal"))
    along = j["rightMiddleProximal"] - j["rightHand"]
    along.z = 0.0
    yaw = math.atan2(along.x, -along.y) if along.length > 1e-6 else 0.0
    return f, {"Souris": Matrix.Translation(mc + move) @ Matrix.Rotation(yaw, 4, "Z")}


def stylus(desk, f):
    """Le stylo dans la main droite : entre le pouce et l'index, la pointe vers le papier."""
    m = hand_matrix(desk, f, "right")
    rig = desk.rig
    pose = rig.fk(f)
    idx = pose[rig.hmap["rightIndexDistal"]].translation
    thb = pose[rig.hmap["rightThumbDistal"]].translation
    grip = (idx + thb) / 2
    wrist = m.translation
    axis = (grip - wrist).normalized()
    down = Vector((0.0, 0.0, -1.0))
    pen_dir = (axis * 0.4 + down * 0.6).normalized()
    rot = Vector((0.0, 0.0, 1.0)).rotation_difference(-pen_dir).to_matrix().to_4x4()
    return Matrix.Translation(grip + pen_dir * 0.02) @ rot


def desk_read(desk, t, period):
    """Lire un livre tenu à deux mains, coudes sur le bureau ; une page tournée par boucle ; les yeux suivent les lignes."""
    f = copy(desk.seated)
    breathe = math.sin(TAU * 2 * t / period)
    lean(f, 12.0 + 0.6 * breathe, turn_deg=1.0 * noise(t, period, 51))
    # Le livre un peu haut et près d'elle : ses avant-bras passent au-dessus du clavier (la chaise reste où elle tape).
    center = Vector((-0.02, -0.265, 0.875)) + Vector((0.005 * noise(t, period, 53), 0.004 * noise(t, period, 55), 0.004 * noise(t, period, 57)))
    tilt = math.radians(45.0)        # le livre incliné vers elle
    rot = Matrix.Rotation(tilt, 4, "X")
    half = BOOK["size"][0] / 2       # tenu par ses bords
    book = Matrix.Translation(center) @ rot
    page = bump(t, 6.0, 1.3)
    for side, sx in (("left", 1.0), ("right", -1.0)):
        edge = book @ Vector((sx * (half - 0.02), -0.03, -0.01))
        if side == "right" and page > 0:
            # Tourner la page : la main droite passe au milieu et revient.
            edge = edge.lerp(book @ Vector((0.0, 0.0, 0.02)), page)
        up = (book.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
        out = (book.to_3x3() @ Vector((sx, 0.0, 0.0))).normalized()
        arm_ik(desk, f, side, edge - up * 0.05 + out * 0.01, Vector((sx * 0.16, -0.14, 0.74)), up + out * 0.2, -out * 0.8 + Vector((0, 0.2, 0)))
        curl(desk, f, side, {"Index": (35, 40, 20), "Middle": (35, 40, 20), "Ring": (40, 42, 20), "Little": (45, 45, 20)},
             thumb=(5.0, 5.0, 5.0), spread=2.0)
    line = book @ Vector((0.06 * math.sin(TAU * 4 * t / period), 0.05 - 0.1 * ((t % (period / 2)) / (period / 2)), 0.01))
    look(desk, f, line, neck_share=0.45)
    return f, {"Livre": book}


def desk_think(desk, t, period):
    """Réfléchir : accoudée, le menton sur le poing gauche, les doigts de la droite qui pianotent sur le bureau."""
    f = copy(desk.seated)
    breathe = math.sin(TAU * 2 * t / period)
    lean(f, 18.0 + 0.6 * breathe, turn_deg=6.0, side_deg=8.0 + 1.5 * noise(t, period, 61))
    look(desk, f, MONITOR["center"] + Vector((0.25 * noise(t, period, 63), 0.0, -0.12 + 0.06 * noise(t, period, 65))))
    j = desk.rig.joints(f, ("leftEye", "rightEye"))
    eyes = (j["leftEye"] + j["rightEye"]) / 2
    head = f["d"]["head"]
    fwd, up = head @ Vector((0.0, -1.0, 0.0)), head @ Vector((0.0, 0.0, 1.0))
    # Le menton : 7 cm sous les yeux, un peu en avant ; le poing dessous (les phalanges contre le menton), le
    # poignet plus bas, le coude posé sur le bureau.
    chin = eyes - up * 0.072 + fwd * 0.03
    wrist = chin + fwd * 0.01 + Vector((0.0, 0.0, -0.085))
    arm_ik(desk, f, "left", wrist, Vector((0.07, -0.22, 0.76)), Vector((-0.1, -0.15, 1.0)), Vector((0.0, 1.0, 0.0)))
    curl(desk, f, "left", {"Index": (70, 70, 40), "Middle": (75, 70, 40), "Ring": (80, 70, 40), "Little": (85, 70, 40)}, thumb=(30.0, 25.0, 15.0))
    rest_arms(desk, f, t, period, which=("right",))
    drum = [bump((t * 1.0) % 1.2, 0.1 + 0.12 * i, 0.12) for i in range(4)]
    curl(desk, f, "right", {name: (12 + 20 * d, 18 + 10 * d, 8) for name, d in zip(("Little", "Ring", "Middle", "Index"), drum)},
         thumb=(10.0, 8.0, 4.0), spread=4.0)
    return f


def desk_stretch(desk, t, period):
    """S'étirer sur sa chaise : les bras montent au-dessus de la tête, le buste se cambre, puis tout revient."""
    f = copy(desk.seated)
    up = ease(t, 0.5, 1.6) * (1 - ease(t, 3.0, 4.0))
    lean(f, 9.0 - 22.0 * up, turn_deg=0.0)
    for side, sx in (("left", 1.0), ("right", -1.0)):
        rest = Vector((sx * 0.115 - 0.02, -0.255, 0.765))
        high = Vector((sx * 0.06, 0.02, 1.32))
        wrist = rest.lerp(high, up)
        arm_ik(desk, f, side, wrist, Vector((sx * 0.25, -0.05, 0.75 + 0.45 * up)), Vector((-sx * 0.35, -1.0, -0.05)).lerp(Vector((-sx * 0.3, 0.0, 1.0)), up),
               Vector((-sx * 0.15, 0.0, -1.0)).lerp(Vector((0.0, -1.0, 0.0)), up))
        relaxed(desk, f, side, 1.0 - 0.6 * up)
    look(desk, f, MONITOR["center"] + Vector((0.0, 0.0, 0.4 * up)))
    return f


def lap_hands(desk, f, t, period):
    """Les mains posées sur les cuisses, à mi-longueur, paumes en bas."""
    rig = desk.rig
    for side, sx in (("left", 1.0), ("right", -1.0)):
        j = rig.joints(f, (f"{side}UpperLeg", f"{side}LowerLeg"))
        mid = j[f"{side}UpperLeg"].lerp(j[f"{side}LowerLeg"], 0.55)
        wrist = mid + Vector((-sx * 0.01, 0.06, 0.095)) + Vector((0.004 * noise(t, period, 71 + sx), 0.004 * noise(t, period, 73 + sx), 0.0))
        arm_ik(desk, f, side, wrist, Vector((sx * 0.17, 0.0, 0.66)), Vector((-sx * 0.25, -1.0, -0.35)), Vector((-sx * 0.2, 0.0, -1.0)))
        relaxed(desk, f, side, 0.8)


def _gestures():
    import atelier_desk_gestures as g
    return g


CLIPS = {
    "desk_rest": dict(build=desk_rest, seconds=8.0, loop=True, note="au bureau, les mains posées"),
    # Taper : la pulpe d'un doigt qui frappe descend de la course d'une touche (4 mm), les touches ne bougeant pas.
    "desk_type": dict(build=desk_type, seconds=8.0, loop=True, note="taper au clavier, par rafales", tip_dip=0.004),
    "desk_mouse": dict(build=desk_mouse, seconds=6.0, loop=True, note="la souris"),
    # Écrire (la chaise pivotée de 45° vers sa gauche : le carnet devant elle, un peu à droite) : prendre le stylo couché
    # sur le carnet, écrire, le reposer exactement où il était.
    "desk_write_start": dict(grasp="right", build=lambda d, t, p: _gestures().desk_write_start(d, t, p), seconds=1.8, loop=False,
                             note="prendre le stylo sur le carnet pour écrire"),
    "desk_write": dict(build=lambda d, t, p: _gestures().desk_write(d, t, p), seconds=8.0, loop=True, note="écrire dans le carnet"),
    "desk_write_end": dict(grasp="right", build=lambda d, t, p: _gestures().desk_write_end(d, t, p), seconds=1.8, loop=False,
                           note="reposer le stylo sur le carnet"),
    "desk_read": dict(build=desk_read, seconds=10.0, loop=True, note="lire un livre tenu"),
    # Boire se joue de la main gauche (desk_drink, le miroir) : la tasse attend devant à gauche, l'anse vers l'extérieur.
    "desk_drink_droite": dict(grasp="right", build=lambda d, t, p: _gestures().desk_drink(d, t, p), seconds=5.0, loop=False,
                              note="boire à la tasse prise par l'anse (main droite)", mirror="desk_drink"),
    # Prendre se joue aussi de la main gauche (desk_take, le miroir) : son stylo, couché sur le carnet à gauche du clavier.
    "desk_take_droite": dict(grasp="right", build=lambda d, t, p: _gestures().desk_take(d, t, p), seconds=5.0, loop=False,
                             note="prendre son stylo, le regarder, le reposer (main droite)", mirror="desk_take"),
    "desk_think": dict(build=desk_think, seconds=8.0, loop=True, note="réfléchir, accoudée", clear=False),
    "desk_stretch": dict(build=desk_stretch, seconds=4.6, loop=False, note="s'étirer sur sa chaise"),
    "desk_lap": dict(build=lambda desk, t, period: lap_pose(desk, t, period), seconds=8.0, loop=True, note="assise, les mains sur les cuisses"),
    # La chaise : tirée vers le bureau ou repoussée, les mains sur son bord ; pivotée, les pieds poussant le sol.
    "chair_pull_in": dict(build=lambda d, t, p: _gestures().chair_pull_in(d, t, p), seconds=3.1, loop=False,
                          note="se tirer vers le bureau, les mains sur son bord"),
    "chair_push_out": dict(build=lambda d, t, p: _gestures().chair_push_out(d, t, p), seconds=2.9, loop=False,
                           note="repousser la chaise du bureau, les mains sur son bord"),
    "chair_turn_left_45": dict(build=lambda d, t, p: _gestures().chair_turn_left_45(d, t, p), seconds=2.6, loop=False,
                               note="pivoter la chaise d'un quart vers sa gauche, les pieds poussant le sol", mirror="chair_turn_right_45"),
    "chair_turn_left_90": dict(build=lambda d, t, p: _gestures().chair_turn_left_90(d, t, p), seconds=3.9, loop=False,
                               note="pivoter la chaise d'un demi-tour vers sa gauche, les pieds poussant le sol", mirror="chair_turn_right_90"),
}


def lap_pose(desk, t, period):
    """Assise, tournée vers quelqu'un : droite, les mains sur les cuisses, le souffle, la tête qui accompagne."""
    f = copy(desk.seated)
    breathe = math.sin(TAU * 2 * t / period)
    lean(f, 4.0 + 0.8 * breathe, turn_deg=2.0 * noise(t, period, 81))
    lap_hands(desk, f, t, period)
    look(desk, f, Vector((0.25 * noise(t, period, 83), -2.0, 1.05 + 0.08 * noise(t, period, 85))))
    return f


HAND_SURFACES = ("writing_desk", "desk_mat", "keyboard", "mouse", "notebook")
# La souris, un volume fermé et simple : on la mesure par sa face la plus proche, et seul ce qui appuie sur son dessus
# soulève la main (« sous son dessus » prenait le pouce posé sur son flanc pour un doigt enfoncé dedans).
CLOSED_SURFACES = ("mouse",)


def settle_hands(motion, scene, tolerance=0.0015, reach=0.06, tip_dip=0.0, skip=None):
    """
    Les mains posées sur ce qu'il y a dessous, sans y entrer : le bout de chaque doigt, ses phalanges et la paume
    au-dessus de la vraie surface (une touche du clavier, le dos de la souris, le carnet, le plateau — lancer de rayon
    vers le bas sur les modèles posés par `scene`, comme Unity), à l'épaisseur de la peau près. Une main qui y entre est
    remontée par son poignet (IK du bras, la main garde son orientation), d'autant qu'il faut ; les hauteurs sont
    lissées dans le temps. Une main à plus de `reach` sous une surface (sur les cuisses, sous le bureau) n'est pas
    concernée. `skip` ({côté: images}) : la main qui prend un objet posé (le stylo couché sur le carnet) doit le toucher,
    elle n'est pas soulevée pendant la prise. Rend la plus grande remontée (cm).
    """
    import atelier_decor as dc
    from mathutils.bvhtree import BVHTree  # noqa: F401  (l'arbre vient de dc.Contacts.tree)

    rig = motion.rig
    n = len(motion.frames)
    length = {}

    def tail(pose, h):
        bn = rig.hmap[h]
        if h not in length:
            b = rig.arm.data.bones[bn]
            length[h] = ((rig.world @ b.tail_local) - (rig.world @ b.head_local)).length
        m = pose[bn]
        return m.translation + m.to_3x3() @ Vector((0.0, length[h], 0.0))

    def points(frame, side):
        pose = rig.fk(frame)
        pts = []
        for fname in ("Index", "Middle", "Ring", "Little", "Thumb"):
            h = f"{side}{fname}Distal"
            if h in rig.hmap:
                pts.append((tail(pose, h), FINGER_PAD + UNITY_FINGER_DROP - tip_dip))
                pts.append((pose[rig.hmap[h]].translation, 0.008))
        hand = pose[rig.hmap[f"{side}Hand"]].translation
        mid = pose[rig.hmap[f"{side}MiddleProximal"]].translation
        pts.append((hand.lerp(mid, 0.6), 0.012))
        return pts

    static = not callable(scene.chair) and not scene.held and not scene.moves
    tree = closed = None
    lifts = {"left": [0.0] * n, "right": [0.0] * n}
    for i, frame in enumerate(motion.frames):
        if tree is None or not static:
            scene.apply(i)
            tree = dc.Contacts.tree([o for oid in HAND_SURFACES if oid not in CLOSED_SURFACES for o in dc.meshes(dc.load(oid))])
            closed = dc.Contacts.tree([o for oid in CLOSED_SURFACES for o in dc.meshes(dc.load(oid))])
        for side in ("left", "right"):
            if skip and i in skip.get(side, ()):
                continue
            need = 0.0
            for p, pad in points(frame, side):
                loc, _, _, _ = tree.ray_cast(Vector((p.x, p.y, p.z + 0.25)), Vector((0.0, 0.0, -1.0)), 0.6)
                if loc is not None and p.z >= loc.z - reach:
                    need = max(need, loc.z + pad - tolerance - p.z)
                loc, nor, _, _ = closed.find_nearest(p, 0.05)
                if loc is not None and nor.z > 0.5:
                    gap = (p - loc).dot(nor) - (pad - tolerance)
                    if gap < 0.0:
                        need = max(need, -gap / nor.z)
            lifts[side][i] = min(need, reach)
    worst = 0.0
    for side, values in lifts.items():
        if max(values) <= 0.0:
            continue
        at = (lambda k: values[k % n]) if motion.loop else (lambda k: values[min(n - 1, max(0, k))])
        held = [max(at(i + k) for k in range(-4, 5)) for i in range(n)]
        at2 = (lambda k: held[k % n]) if motion.loop else (lambda k: held[min(n - 1, max(0, k))])
        smooth = [max(held[i], sum(at2(i + k) for k in range(-3, 4)) / 7) for i in range(n)]
        for i, lift in enumerate(smooth):
            if lift <= 1e-4:
                continue
            frame = motion.frames[i]
            wrist = rig.joints(frame, (f"{side}Hand",))[f"{side}Hand"]
            al.two_bone(frame, rig, side, wrist + Vector((0.0, 0.0, lift)), limb="arm")
            worst = max(worst, lift)
    return round(worst * 100, 1)


def clear_desk(motion, scene, tolerance=0.003, reach=0.08):
    """
    Les avant-bras et les mains au-dessus du plateau du vrai bureau et de ce qui est posé dessus (posés par `scene`
    comme Unity les pose) : assise à un bureau d'adulte, ses coudes sont au bord et l'avant-bras qui le passe y entrait
    d'un centimètre ; en lisant, l'avant-bras gauche posait sur le clavier. Chaque bras qui s'enfonce tourne sur l'axe
    épaule–poignet (le coude monte sur son cercle, la main ne bouge pas) du plus petit angle qui le dégage ; les angles
    sont lissés dans le temps. Rend l'angle le plus grand (°).
    """
    import atelier_decor as dc

    rig = motion.rig
    n = len(motion.frames)

    def depth(frame, tree, side, angle=0.0):
        f = frame if angle == 0.0 else swiveled(frame, side, angle)
        j = rig.joints(f, (f"{side}LowerArm", f"{side}Hand", f"{side}MiddleProximal"))
        worst = 0.0
        for a, b, r, steps in ((j[f"{side}LowerArm"], j[f"{side}Hand"], 0.028, 8), (j[f"{side}Hand"], j[f"{side}MiddleProximal"], 0.016, 3)):
            for i in range(steps + 1):
                p = a.lerp(b, i / steps)
                loc, _, _, _ = tree.ray_cast(Vector((p.x, p.y, p.z + 0.25)), Vector((0.0, 0.0, -1.0)), 0.6)
                if loc is None or p.z < loc.z - reach:
                    continue
                worst = max(worst, loc.z + r - p.z)
        return worst

    def swiveled(frame, side, angle):
        f = {"hips": frame["hips"], "d": dict(frame["d"])}
        j = rig.joints(frame, (f"{side}UpperArm", f"{side}Hand"))
        axis = (j[f"{side}Hand"] - j[f"{side}UpperArm"]).normalized()
        q = Quaternion(axis, math.radians(angle))
        for h in (f"{side}UpperArm", f"{side}LowerArm"):
            f["d"][h] = q @ frame["d"][h]
        return f

    static = not callable(scene.chair) and not scene.held and not scene.moves
    tree = None
    best = {"left": [0.0] * n, "right": [0.0] * n}
    for i, frame in enumerate(motion.frames):
        if tree is None or not static:
            scene.apply(i)
            tree = dc.Contacts.tree([o for oid in HAND_SURFACES if oid not in CLOSED_SURFACES for o in dc.meshes(dc.load(oid))])
        for side in ("left", "right"):
            if depth(frame, tree, side) <= tolerance:
                continue
            tries = [a * s for a in [2.5 * k for k in range(1, 13)] for s in (1, -1)]
            ok = [a for a in tries if depth(frame, tree, side, a) <= tolerance]
            best[side][i] = ok[0] if ok else min(tries, key=lambda a: depth(frame, tree, side, a))
    worst = 0.0
    for side, angles in best.items():
        if not any(angles):
            continue
        # Lissés (fenêtre de 9 images, gardant le maximum local : un coude ne doit pas redescendre dans le bureau).
        smooth = []
        for i in range(n):
            window = [angles[(i + k) % n] if motion.loop else angles[min(n - 1, max(0, i + k))] for k in range(-4, 5)]
            smooth.append(max(window, key=abs))
        smooth = [sum(smooth[(i + k) % n] if motion.loop else smooth[min(n - 1, max(0, i + k))] for k in range(-3, 4)) / 7 for i in range(n)]
        for i, a in enumerate(smooth):
            if abs(a) > 1e-3:
                motion.frames[i] = swiveled(motion.frames[i], side, a)
                worst = max(worst, abs(a))
    return round(worst, 1)


HELD = al.WORKDIR / "held"


def save_held(name, held, mirror=False):
    """
    Les objets tenus d'un clip, image par image (held/<clip>.json, matrices du décor de contrôle, repère du clip) : la
    vérification (atelier_desk_check.py) y pose les vrais objets. En miroir pour un clip joué de l'autre main.
    """
    import json

    flip = Matrix.Scale(-1.0, 4, Vector((1.0, 0.0, 0.0)))
    names = sorted({k for h in held for k in h})
    out = {}
    for n in names:
        rows = []
        for h in held:
            m = h.get(n)
            if m is not None and mirror:
                m = flip @ m @ flip
            rows.append(None if m is None else [round(v, 5) for row in m for v in row])
        out[n] = rows
    HELD.mkdir(parents=True, exist_ok=True)
    (HELD / f"{name}.json").write_text(json.dumps(out, separators=(",", ":")))


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--no-previews", action="store_true")
    args = ap.parse_args(argv)
    only = [n for n in args.only.split(",") if n]
    rig = al.Rig(al.mika_armature())
    desk = Desk(rig)
    desk.seated = seated_base(rig)
    al.rehearsal(True)
    clearance = al.Clearance(rig)
    built_names = []
    import atelier_decor as dc
    import atelier_desk_check
    layout = dc.Layout()
    desk.layout = layout
    desk.geo = _gestures().Geo(layout)
    for name, spec in CLIPS.items():
        if only and name not in only and spec.get("mirror") not in only:
            continue
        n = int(round(spec["seconds"] * FPS))
        built = [spec["build"](desk, i / FPS, spec["seconds"]) for i in range(n)]
        frames = [b[0] if isinstance(b, tuple) else b for b in built]
        held = [b[1] if isinstance(b, tuple) and len(b) > 1 else {} for b in built]
        curves = {}
        for b in built:
            if isinstance(b, tuple) and len(b) > 2:
                for k, v in b[2].items():
                    curves.setdefault(k, []).append(v)
        if spec["loop"]:
            frames.append(copy(frames[0]))
            held.append(held[0])
            for k in curves:
                curves[k].append(curves[k][0])
        motion = al.Motion(rig, name, frames, loop=spec["loop"], curves=curves)
        # Les mains contre le corps (posées sur les cuisses, le poing sous le menton) : au contact, pas dedans.
        if spec.get("clear", True):
            al.clear_arms(motion, clearance, margin=0.004)
        save_held(name, held)
        _settle(motion, name, layout, held, spec, atelier_desk_check)
        frames = motion.frames
        jump = al.jumps(motion)
        hands = clearance.measure(motion, step=4)
        report = f"{len(frames)} images, saut max {jump['saut']}° ({jump['os']}), mains dans le corps " \
                 f"{hands['left']['profondeur_cm']}/{hands['right']['profondeur_cm']} cm"
        path = motion.export(note=f"atelier du bureau — {spec['note']} — {report}")
        print(f"[bureau] {name} : {report} → {path}", flush=True)
        if spec.get("mirror"):
            save_held(spec["mirror"], held, mirror=True)
            mirrored = al.Motion(rig, spec["mirror"], [al.mirror_frame(fr) for fr in frames], loop=spec["loop"], curves=motion.curves)
            # Le bureau, lui, n'est pas symétrique : le miroir (celui que le jeu joue) se vérifie contre lui.
            flip = Matrix.Scale(-1.0, 4, Vector((1.0, 0.0, 0.0)))
            mheld = [{k: (flip @ m @ flip) for k, m in h.items()} for h in held]
            _settle(mirrored, spec["mirror"], layout, mheld, spec, atelier_desk_check)
            mpath = mirrored.export(note=f"atelier du bureau — miroir de {name} — {spec['note'].replace('gauche', 'droite')}")
            print(f"[bureau] {spec['mirror']} (miroir) → {mpath}", flush=True)
        built_names.append(name)
        if spec.get("mirror"):
            built_names.append(spec["mirror"])
    # La vérification contre les vrais meubles et objets (contacts mesurés, planches previews/verif_<clip>.png).
    atelier_desk_check.verify(rig, built_names, previews=not args.no_previews)


def _settle(motion, name, layout, held, spec, check):
    """Les mains posées sur les vraies surfaces et les avant-bras au-dessus du plateau, dans le décor du clip (la chaise où
    le geste la met, image par image ; les objets là où sa main les porte)."""
    scene = check.scene_for(name, layout, motion)
    if scene is None or not spec.get("desk", True):
        return
    absolute, moves = check.split_held(held, layout)
    scene.held = absolute
    scene.moves = moves
    # La main qui prend un objet (spec « grasp » : la main du geste construit ; le miroir prend l'autre) n'est pas soulevée
    # pendant qu'elle le tient ni juste avant ou après (elle se pose dessus).
    skip = None
    hold = motion.curves.get("Hold")
    if spec.get("grasp") and hold:
        side = spec["grasp"] if name != spec.get("mirror") else ("left" if spec["grasp"] == "right" else "right")
        held_frames = [i for i, v in enumerate(hold) if v > 0.0]
        margin = 10
        skip = {side: {j for i in held_frames for j in range(i - margin, i + margin + 1)}}
    lift = settle_hands(motion, scene, tip_dip=spec.get("tip_dip", 0.0), skip=skip)
    if lift:
        print(f"[bureau] {name} : mains posées sur les surfaces (remontées d'au plus {lift} cm)", flush=True)
    swivel = clear_desk(motion, scene)
    if swivel:
        print(f"[bureau] {name} : coudes relevés au-dessus du plateau (au plus {swivel}°)", flush=True)


if __name__ == "__main__":
    main()
