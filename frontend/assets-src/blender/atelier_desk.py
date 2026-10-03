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
# Le carnet à 40 cm devant elle (BodyActivity.WriteForward) : à 36, la chaise roulait si près que, penchée pour
# écrire, sa poitrine touchait le bord du bureau.
NOTEBOOK = dict(center=Vector((0.0, -0.40, 0.746)), size=(0.21, 0.30, 0.012))
MUG = dict(center=Vector((-0.30, -0.33, 0.789)), size=(0.08, 0.08, 0.098))
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
        # Les frappes : un doigt à la fois, pour un tempo de 6 à 8 touches/s à deux mains.
        taps = []
        for a, b in bursts:
            x = a + rnd.uniform(0.05, 0.2)
            while x < b - 0.15:
                taps.append((x, rnd.choice(FINGERS)))
                x += rnd.uniform(0.18, 0.42)
        pose = {}
        for name, (p, i, d) in base.items():
            press = sum(bump(t, x, 0.12) for x, fn in taps if fn == name)
            pose[name] = (p + 14.0 * press, i + 6.0 * press, d)
        thumb_press = sum(bump(t, x, 0.14) for x, fn in taps if fn == "Index") * 0.3
        curl(desk, f, side, pose, thumb=(18.0, 12.0 + 10 * thumb_press, 8.0), spread=4.0)
    # Le regard : l'écran, des lignes qui se lisent, un coup d'œil aux touches au milieu de la boucle.
    screen = MONITOR["center"] + Vector((0.12 * noise(t, period, 9), 0.0, 0.05 * noise(t, period, 13)))
    keys = kc + Vector((0.0, 0.02, 0.02))
    g = bump(t, 3.5, 1.0)
    look(desk, f, screen.lerp(keys, g))
    return f


def hand_matrix(desk, frame, side):
    """La matrice monde de la main (os de la main) pour cette image."""
    rig = desk.rig
    return rig.fk(frame)[rig.hmap[f"{side}Hand"]].copy()


def in_palm(desk, f, side, along, out):
    """Un objet tenu : `along` m devant le poignet le long des doigts, `out` m du côté de la paume ; son haut suit le
    pouce (une tasse tenue de côté reste droite)."""
    rig = desk.rig
    hand = f["d"][f"{side}Hand"]
    fingers = hand @ desk.rest_dir[f"{side}Hand"]
    palm = hand @ desk.palm0
    wrist = rig.joints(f, (f"{side}Hand",))[f"{side}Hand"]
    thumb_side = fingers.cross(palm) * (1 if side == "right" else -1)
    rot = basis(fingers, palm).to_matrix().to_4x4()
    up = Vector((0.0, 0.0, 1.0)).rotation_difference(thumb_side).to_matrix().to_4x4()
    return Matrix.Translation(wrist + fingers * along + palm * out) @ up


def relaxed(desk, f, side, amount=1.0):
    """Des doigts au repos, à demi pliés."""
    k = amount
    curl(desk, f, side, {"Index": (12 * k, 18 * k, 8 * k), "Middle": (15 * k, 20 * k, 9 * k), "Ring": (18 * k, 22 * k, 10 * k),
                         "Little": (22 * k, 24 * k, 10 * k)}, thumb=(10 * k, 8 * k, 4 * k), spread=3.0)


def rest_arms(desk, f, t, period, which=("left", "right")):
    """Les mains posées sur le bureau, près du bord, avant-bras sur le plateau."""
    for side, sx in (("left", 1.0), ("right", -1.0)):
        if side not in which:
            continue
        wrist = Vector((sx * 0.115 - 0.02, -0.255, 0.765)) + Vector((0.006 * noise(t, period, 21 + sx), 0.006 * noise(t, period, 23 + sx), 0.0))
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
    return f, {"Souris": Matrix.Translation(mc + move)}


def desk_write(desk, t, period):
    """Écrire : le carnet devant elle, la main gauche le tient, la droite trace des lignes ; le regard suit le stylo."""
    f = copy(desk.seated)
    breathe = math.sin(TAU * 2 * t / period)
    lean(f, 18.0 + 0.6 * breathe, turn_deg=4.0, side_deg=-2.0)
    nb = NOTEBOOK["center"]
    # Deux lignes par boucle : écrire 3,2 s de gauche à droite, revenir en 0,8 s.
    line_t = (t % (period / 2)) / (period / 2)
    k = line_t / 0.8 if line_t < 0.8 else 1.0 - (line_t - 0.8) / 0.2
    k = max(0.0, min(1.0, k))
    row = 0.0 if t < period / 2 else 0.018
    lift = 0.0 if line_t < 0.8 else math.sin(math.pi * (line_t - 0.8) / 0.2) * 0.012
    loops = Vector((math.sin(t * 15.0) * 0.004, math.cos(t * 12.0) * 0.003, max(0.0, math.sin(t * 9.0)) * 0.002))
    tip = nb + Vector((0.04 - 0.11 * k, 0.02 - row, NOTEBOOK["size"][2] / 2 + 0.002 + lift)) + loops
    fingers = Vector((0.35, -1.0, -0.55))
    palm = Vector((0.55, 0.0, -0.8))
    wrist = tip - fingers.normalized() * 0.085 + Vector((-0.02, 0.0, 0.03))
    arm_ik(desk, f, "right", wrist, Vector((-0.20, -0.12, 0.76)), fingers, palm)
    # La prise du stylo : pouce et index pincent, le majeur soutient, annulaire et auriculaire repliés.
    curl(desk, f, "right", {"Index": (28, 24, 18), "Middle": (38, 34, 20), "Ring": (55, 50, 25), "Little": (60, 52, 25)},
         thumb=(30.0, 18.0, 10.0), spread=0.0)
    # La gauche à plat sur le côté gauche du carnet.
    lw = nb + Vector((0.13, 0.03, 0.03))
    arm_ik(desk, f, "left", lw, Vector((0.18, -0.12, 0.75)), Vector((-0.6, -1.0, -0.1)), Vector((-0.1, 0.0, -1.0)))
    relaxed(desk, f, "left", 0.6)
    look(desk, f, tip + Vector((0.0, 0.0, 0.0)), neck_share=0.45)
    return f, {"Carnet": Matrix.Translation(nb), "Stylo": stylus(desk, f)}


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
    center = Vector((-0.02, -0.29, 0.845)) + Vector((0.005 * noise(t, period, 53), 0.004 * noise(t, period, 55), 0.004 * noise(t, period, 57)))
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


def reach_cycle(desk, f, t, side, start, obj, lift_to, grip_dir, palm, timing):
    """
    Aller prendre un objet et le ramener : de la main posée (start) vers l'objet (obj), puis vers lift_to, puis le
    reposer et revenir. timing = (départ, prise, levé, tenu, reposé, retour) en secondes. Rend (poignet, porté).
    """
    t0, t1, t2, t3, t4, t5 = timing
    to_obj = ease(t, t0, t1)
    up = ease(t, t1 + 0.15, t2)
    down = ease(t, t3, t4)
    back = ease(t, t4 + 0.15, t5)
    held = up * (1 - down)
    p = start.lerp(obj, to_obj)
    p = p.lerp(lift_to, held)
    p = p.lerp(start, back)
    carried = (t1 + 0.1 < t < t4 + 0.1)
    return p, carried


def desk_drink(desk, t, period):
    """Boire : prendre la tasse à droite, la porter aux lèvres, une gorgée, la reposer."""
    f = copy(desk.seated)
    breathe = math.sin(TAU * 2 * t / period)
    timing = (0.4, 1.1, 1.9, 3.3, 4.0, 4.6)
    sip = ease(t, timing[1] + 0.2, timing[2]) * (1 - ease(t, timing[3], timing[4]))
    lean(f, 9.0 + 0.6 * breathe - 4.0 * sip, turn_deg=-4.0 * (1 - sip))
    rest_arms(desk, f, t, period, which=("left",))
    mug = MUG["center"]
    start = Vector((-0.135, -0.255, 0.765))
    # Le poignet se déduit de la tasse : tenue dans la paume (in_palm : 5,5 cm le long des doigts, 4,5 cm côté paume).
    def wrist_for(mug_center, rot):
        return mug_center - (rot @ desk.rest_dir["rightHand"]) * 0.055 - (rot @ desk.palm0) * 0.045
    lips = Vector((0.0, -0.15, 0.895))     # la tasse aux lèvres : son centre 5 cm devant la bouche, 2 cm plus bas
    grip = wrist_for(mug, hand_rotation(desk, "right", Vector((0.3, -1.0, -0.05)), Vector((1.0, 0.2, -0.1))))
    mouth = wrist_for(lips, hand_rotation(desk, "right", Vector((0.55, -0.35, 0.75)), Vector((0.8, 0.4, -0.45))))
    wrist, carried = reach_cycle(desk, f, t, "right", start, grip, mouth, None, None, timing)
    # La main droite : posée (doigts vers l'intérieur, paume en bas), puis de côté contre la tasse (pouce en haut,
    # paume vers la tasse), puis la tasse qui bascule vers les lèvres.
    on_desk = hand_rotation(desk, "right", Vector((0.35, -1.0, -0.05)), Vector((0.15, 0.0, -1.0)))
    at_mug = hand_rotation(desk, "right", Vector((0.3, -1.0, -0.05)), Vector((1.0, 0.2, -0.1)))
    at_mouth = hand_rotation(desk, "right", Vector((0.55, -0.35, 0.75)), Vector((0.8, 0.4, -0.45)))
    reach = ease(t, timing[0], timing[1]) * (1 - ease(t, timing[4], timing[5]))
    rot = on_desk.slerp(at_mug, reach).slerp(at_mouth, sip)
    grab = ease(t, timing[1] - 0.15, timing[1] + 0.1) * (1 - ease(t, timing[4] - 0.05, timing[4] + 0.2))
    # Le coude bas et en avant quand elle boit : l'avant-bras monte vers la bouche (levé à hauteur d'épaule, il
    # arrivait de côté, à l'horizontale).
    elbow = Vector((-0.20, -0.08, 0.78)).lerp(Vector((-0.13, -0.17, 0.69)), sip)
    arm_ik(desk, f, "right", wrist, elbow, None, None, hand_rot=rot)
    k = grab
    curl(desk, f, "right", {"Index": (15 + 45 * k, 20 + 40 * k, 10 + 20 * k), "Middle": (18 + 45 * k, 20 + 40 * k, 10 + 20 * k),
                            "Ring": (20 + 45 * k, 22 + 40 * k, 10 + 20 * k), "Little": (22 + 45 * k, 24 + 40 * k, 10 + 20 * k)},
         thumb=(10 + 15 * k, 8 + 10 * k, 4 + 6 * k), spread=1.0)
    eye_target = mug.lerp(lips + Vector((0.0, -0.3, 0.0)), ease(t, timing[1], timing[2]) * (1 - ease(t, timing[3], timing[4])))
    look(desk, f, eye_target if t < timing[4] + 0.3 else MONITOR["center"].lerp(eye_target, 1 - ease(t, timing[4] + 0.3, timing[5])))
    if carried:
        mug_m = in_palm(desk, f, "right", 0.055, 0.045)
    else:
        mug_m = Matrix.Translation(mug)
    return f, {"Tasse": mug_m}


def desk_take(desk, t, period):
    """Prendre un objet posé devant elle (à droite), le regarder dans sa main, le reposer. Joué en miroir (main gauche)."""
    f = copy(desk.seated)
    breathe = math.sin(TAU * 2 * t / period)
    timing = (0.4, 1.2, 1.9, 3.4, 4.1, 4.7)
    look_at = ease(t, timing[1] + 0.2, timing[2]) * (1 - ease(t, timing[3], timing[4]))
    lean(f, 12.0 + 0.6 * breathe + 4.0 * (ease(t, timing[0], timing[1]) * (1 - ease(t, timing[1] + 0.1, timing[2]))), turn_deg=-6.0)
    rest_arms(desk, f, t, period, which=("left",))
    obj = Vector((-0.20, -0.42, 0.775))
    start = Vector((-0.135, -0.255, 0.765))
    view = Vector((-0.05, -0.24, 0.93))
    wrist, carried = reach_cycle(desk, f, t, "right", start, obj + Vector((0.0, 0.07, 0.03)), view, None, None, timing)
    on_desk = hand_rotation(desk, "right", Vector((0.35, -1.0, -0.05)), Vector((0.15, 0.0, -1.0)))
    grasp = hand_rotation(desk, "right", Vector((0.1, -1.0, -0.5)), Vector((0.1, 0.0, -1.0)))
    show = hand_rotation(desk, "right", Vector((0.35, -0.85, 0.3)), Vector((0.2, 0.35, 0.9)))
    reach = ease(t, timing[0], timing[1]) * (1 - ease(t, timing[4], timing[5]))
    arm_ik(desk, f, "right", wrist, Vector((-0.21, -0.10, 0.76)), None, None, hand_rot=on_desk.slerp(grasp, reach).slerp(show, look_at))
    k = ease(t, timing[1] - 0.15, timing[1] + 0.1) * (1 - ease(t, timing[4] - 0.05, timing[4] + 0.2))
    curl(desk, f, "right", {"Index": (15 + 35 * k, 20 + 30 * k, 10 + 15 * k), "Middle": (18 + 35 * k, 20 + 30 * k, 10 + 15 * k),
                            "Ring": (20 + 35 * k, 22 + 30 * k, 10 + 15 * k), "Little": (22 + 35 * k, 24 + 30 * k, 10 + 15 * k)},
         thumb=(10 + 25 * k, 8 + 12 * k, 4 + 6 * k), spread=1.0)
    target = MONITOR["center"].lerp(obj, ease(t, timing[0] - 0.3, timing[1] - 0.2)).lerp(view, look_at)
    target = target.lerp(MONITOR["center"], ease(t, timing[4], timing[5] + 0.2))
    look(desk, f, target, neck_share=0.4)
    if carried:
        om = in_palm(desk, f, "right", 0.06, 0.025)
    else:
        om = Matrix.Translation(obj)
    return f, {"Objet": om}


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


def chair_turn(desk, t, period, degrees):
    """
    Pivoter la chaise vers sa gauche de `degrees` (Unity fait tourner la chaise, et elle avec) : elle lève un peu les
    pieds, ramenés sous elle, le temps du pivot, et les repose une fois tournée ; le buste puis la tête mènent le
    mouvement, les mains sur les cuisses. Dans le jeu, tout le modèle de la chaise tourne, piètement compris : des pieds
    restés au sol voyaient ses branches passer dessous (vérifié avec la vraie chaise, atelier_desk_check.py).
    """
    f = copy(desk.seated)
    rig = desk.rig
    turn = ease(t, 0.1, period - 0.25)
    lead = math.sin(math.pi * turn)
    lean(f, 6.0, turn_deg=12.0 * lead)
    lap_hands(desk, f, t, period)
    look(desk, f, Vector((math.sin(math.radians(30.0 * lead)), -math.cos(math.radians(30.0 * lead)), 0.0)) * 2.0 + Vector((0.0, 0.0, 1.0)))
    # Levés dès le départ, reposés à la fin ; le pied qui mène (côté du pivot) un peu avant l'autre.
    up = {"left": ease(t, 0.0, 0.25) * (1 - ease(t, period - 0.4, period - 0.1)),
          "right": ease(t, 0.06, 0.31) * (1 - ease(t, period - 0.34, period - 0.04))}
    base = desk.seated
    for side in ("left", "right"):
        home = rig.joints(base, (f"{side}Foot",))[f"{side}Foot"]
        k = up[side]
        al.two_bone(f, rig, side, home + Vector((0.0, 0.012 * k, 0.045 * k)))
    return f


def chair_turn_45(desk, t, period):
    return chair_turn(desk, t, period, 45.0)


def chair_turn_90(desk, t, period):
    return chair_turn(desk, t, period, 90.0)


CLIPS = {
    "desk_rest": dict(build=desk_rest, seconds=8.0, loop=True, note="au bureau, les mains posées"),
    "desk_type": dict(build=desk_type, seconds=8.0, loop=True, note="taper au clavier, par rafales"),
    "desk_mouse": dict(build=desk_mouse, seconds=6.0, loop=True, note="la souris"),
    "desk_write": dict(build=desk_write, seconds=8.0, loop=True, note="écrire dans le carnet"),
    "desk_read": dict(build=desk_read, seconds=10.0, loop=True, note="lire un livre tenu"),
    # Boire se joue de la main gauche (desk_drink, le miroir) : la tasse attend à gauche du clavier — à droite, elle
    # était sur le chemin de la souris.
    "desk_drink_droite": dict(build=desk_drink, seconds=5.0, loop=False, note="boire à la tasse (main droite)",
                              mirror="desk_drink"),
    # Prendre se joue aussi de la main gauche (desk_take, le miroir) : l'objet (son stylo) attend à gauche du clavier,
    # la droite reste sur le bureau, près de la souris.
    "desk_take_droite": dict(build=desk_take, seconds=5.0, loop=False, note="prendre un objet, le regarder, le reposer (main droite)", mirror="desk_take"),
    "desk_think": dict(build=desk_think, seconds=8.0, loop=True, note="réfléchir, accoudée", clear=False),
    "desk_stretch": dict(build=desk_stretch, seconds=4.6, loop=False, note="s'étirer sur sa chaise"),
    "desk_lap": dict(build=lambda desk, t, period: lap_pose(desk, t, period), seconds=8.0, loop=True, note="assise, les mains sur les cuisses"),
    "chair_turn_left_45": dict(build=chair_turn_45, seconds=1.4, loop=False, note="pivoter la chaise d'un quart à gauche, les pieds levés", mirror="chair_turn_right_45"),
    "chair_turn_left_90": dict(build=chair_turn_90, seconds=2.0, loop=False, note="pivoter la chaise d'un demi-tour à gauche, les pieds levés", mirror="chair_turn_right_90"),
}


def lap_pose(desk, t, period):
    """Assise, tournée vers quelqu'un : droite, les mains sur les cuisses, le souffle, la tête qui accompagne."""
    f = copy(desk.seated)
    breathe = math.sin(TAU * 2 * t / period)
    lean(f, 4.0 + 0.8 * breathe, turn_deg=2.0 * noise(t, period, 81))
    lap_hands(desk, f, t, period)
    look(desk, f, Vector((0.25 * noise(t, period, 83), -2.0, 1.05 + 0.08 * noise(t, period, 85))))
    return f


def clear_desk(motion, scene, frames_per_scene=None, tolerance=0.003):
    """
    Les avant-bras et les mains au-dessus du plateau du vrai bureau (posé par `scene` comme Unity le pose) : assise à un
    bureau d'adulte, ses coudes sont au bord et l'avant-bras qui le passe y entrait d'un centimètre. Chaque bras qui
    s'enfonce tourne sur l'axe épaule–poignet (le coude monte sur son cercle, la main ne bouge pas) du plus petit angle
    qui le dégage ; les angles sont lissés dans le temps. Rend l'angle le plus grand (°).
    """
    import atelier_decor as dc

    rig = motion.rig
    desk = dc.load("writing_desk")
    corners = [Vector(c) for o in dc.meshes(desk) for c in (o.matrix_world @ Vector(v) for v in o.bound_box)]
    inv0 = desk.matrix_world.inverted()
    loc = [inv0 @ c for c in corners]
    lo = Vector((min(p.x for p in loc), min(p.y for p in loc), 0.0))
    hi = Vector((max(p.x for p in loc), max(p.y for p in loc), max(p.z for p in loc)))
    n = len(motion.frames)

    def depth(frame, inv, side, angle=0.0):
        f = frame if angle == 0.0 else swiveled(frame, side, angle)
        j = rig.joints(f, (f"{side}LowerArm", f"{side}Hand", f"{side}MiddleProximal"))
        worst = 0.0
        for a, b, r, steps in ((j[f"{side}LowerArm"], j[f"{side}Hand"], 0.028, 8), (j[f"{side}Hand"], j[f"{side}MiddleProximal"], 0.016, 3)):
            for i in range(steps + 1):
                p = inv @ a.lerp(b, i / steps)
                if not (lo.x <= p.x <= hi.x and lo.y <= p.y <= hi.y and hi.z - 0.15 < p.z < hi.z + r):
                    continue
                worst = max(worst, hi.z + r - p.z)
        return worst

    def swiveled(frame, side, angle):
        f = {"hips": frame["hips"], "d": dict(frame["d"])}
        j = rig.joints(frame, (f"{side}UpperArm", f"{side}Hand"))
        axis = (j[f"{side}Hand"] - j[f"{side}UpperArm"]).normalized()
        q = Quaternion(axis, math.radians(angle))
        for h in (f"{side}UpperArm", f"{side}LowerArm"):
            f["d"][h] = q @ frame["d"][h]
        return f

    best = {"left": [0.0] * n, "right": [0.0] * n}
    for i, frame in enumerate(motion.frames):
        scene.apply(i)
        inv = desk.matrix_world.inverted()
        for side in ("left", "right"):
            if depth(frame, inv, side) <= tolerance:
                continue
            tries = [a * s for a in [2.5 * k for k in range(1, 13)] for s in (1, -1)]
            ok = [a for a in tries if depth(frame, inv, side, a) <= tolerance]
            best[side][i] = ok[0] if ok else min(tries, key=lambda a: depth(frame, inv, side, a))
    worst = 0.0
    for side, angles in best.items():
        if not any(angles):
            continue
        # Lissés (fenêtre de 9 images, gardant le maximum local : un coude ne doit pas redescendre dans le bureau).
        smooth = []
        for i in range(n):
            window = [angles[(i + k) % n] if motion.loop else angles[min(n - 1, max(0, i + k))] for k in range(-4, 5)]
            big = max(window, key=abs)
            smooth.append(big)
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
    decor_scenes = atelier_desk_check.scenes(dc.Layout())
    for name, spec in CLIPS.items():
        if only and name not in only:
            continue
        n = int(round(spec["seconds"] * FPS))
        built = [spec["build"](desk, i / FPS, spec["seconds"]) for i in range(n)]
        frames = [b[0] if isinstance(b, tuple) else b for b in built]
        held = [b[1] if isinstance(b, tuple) else {} for b in built]
        if spec["loop"]:
            frames.append(copy(frames[0]))
            held.append(held[0])
        motion = al.Motion(rig, name, frames, loop=spec["loop"])
        # Les mains contre le corps (posées sur les cuisses, le poing sous le menton) : au contact, pas dedans.
        if spec.get("clear", True):
            al.clear_arms(motion, clearance, margin=0.004)
        scene = decor_scenes.get(name)
        if scene is not None and spec.get("desk", True):
            swivel = clear_desk(motion, scene)
            if swivel:
                print(f"[bureau] {name} : coudes relevés au-dessus du plateau (au plus {swivel}°)", flush=True)
        frames = motion.frames
        jump = al.jumps(motion)
        hands = clearance.measure(motion, step=4)
        report = f"{len(frames)} images, saut max {jump['saut']}° ({jump['os']}), mains dans le corps " \
                 f"{hands['left']['profondeur_cm']}/{hands['right']['profondeur_cm']} cm"
        path = motion.export(note=f"atelier du bureau — {spec['note']} — {report}")
        save_held(name, held)
        print(f"[bureau] {name} : {report} → {path}", flush=True)
        if spec.get("mirror"):
            save_held(spec["mirror"], held, mirror=True)
            mirrored = al.Motion(rig, spec["mirror"], [al.mirror_frame(fr) for fr in frames], loop=spec["loop"])
            # Le bureau, lui, n'est pas symétrique : le miroir (celui que le jeu joue) se vérifie contre lui.
            mscene = decor_scenes.get(spec["mirror"])
            if mscene is not None and spec.get("desk", True):
                swivel = clear_desk(mirrored, mscene)
                if swivel:
                    print(f"[bureau] {spec['mirror']} : coudes relevés au-dessus du plateau (au plus {swivel}°)", flush=True)
            mpath = mirrored.export(note=f"atelier du bureau — miroir de {name} — {spec['note'].replace('gauche', 'droite')}")
            print(f"[bureau] {spec['mirror']} (miroir) → {mpath}", flush=True)
        built_names.append(name)
        if spec.get("mirror"):
            built_names.append(spec["mirror"])
    # La vérification contre les vrais meubles et objets (contacts mesurés, planches previews/verif_<clip>.png).
    atelier_desk_check.verify(rig, built_names, previews=not args.no_previews)

if __name__ == "__main__":
    main()
