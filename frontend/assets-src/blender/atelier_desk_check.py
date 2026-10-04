# Vérifier les clips du bureau tels qu'ils sont exportés (motions/*.json.gz, ce qu'Unity importe) contre le vrai décor :
# la chaise, le bureau et ses objets, chacun chargé depuis son .blend et posé comme Unity le pose pour cette occupation
# (chaise pivotée et avancée par le repère de travail, souris/tasse/stylo/carnet glissés à leur place). Mesure ce qui
# entre où (pieds et jambes dans la chaise ou le bureau, dos dans le dossier, bras dans les accoudoirs, mains dans le
# plateau) et rend une planche par clip (previews/verif_<clip>.png).
#
#   blender -b UnityFrontend/ArtSource/atelier/mika_rig.blend --python frontend/assets-src/blender/atelier_desk_check.py -- \
#       [--only desk_type,desk_lap] [--no-previews]
import argparse
import gzip
import json
import math
import sys
from pathlib import Path

from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atelier_decor as dc  # noqa: E402
import atelier_lib as al  # noqa: E402


def load_motion(rig, name):
    """Un mouvement exporté, relu : hanches + orientation monde de chaque os → l'image de l'atelier."""
    data = json.load(gzip.open(al.MOTIONS / f"{name}.json.gz", "rt"))
    frames = []
    for row in data["frames"]:
        d = {h: Quaternion(row[3 + 4 * k: 7 + 4 * k]) @ rig.rest[h].inverted() for k, h in enumerate(data["bones"])}
        frames.append({"hips": Vector(row[:3]), "d": d})
    return al.Motion(rig, name, frames, loop=data.get("loop", False))


def ease(t, a, b):
    if t <= a:
        return 0.0
    if t >= b:
        return 1.0
    x = (t - a) / (b - a)
    return x * x * (3 - 2 * x)


# Où est la chaise pendant chaque clip : une position nommée (atelier_decor.Layout.chair_pose), ou un trajet d'une
# position à une autre que le geste parcourt selon ses courbes « ChairYaw » (le pivot) et « ChairRoll » (le
# roulement), de 0 à 1 — exactement ce qu'Unity fera.
STATIC = {
    "desk_rest": "type", "desk_type": "type", "desk_mouse": "type", "desk_think": "type", "desk_stretch": "type",
    "desk_drink": "type", "desk_take": "type", "desk_read": "type",
    "desk_write": "write", "desk_write_start": "write", "desk_write_end": "write",
    "desk_lap": "type-90", "desk_lap_droite": "type+90",
    "sitting_idle": "home", "sit_down": "home", "stand_up": "home",
}
PATHS = {
    "chair_pull_in": ("home", "type"),
    "chair_push_out": ("type", "home"),
    "chair_turn_left_45": ("type", "type-45"),
    "chair_turn_right_45": ("type", "type+45"),
    "chair_turn_left_90": ("type", "type-90"),
    "chair_turn_right_90": ("type", "type+90"),
}
# Les pivots se jouent aussi depuis d'autres positions : vérifiés depuis chacune (« clip@départ »).
VARIANTS = {
    "chair_turn_right_45@write": ("chair_turn_right_45", "write", "type"),
    "chair_turn_left_45@home": ("chair_turn_left_45", "home", "home-45"),
    "chair_turn_right_90@home": ("chair_turn_right_90", "home", "home+90"),
}


def curves_of(name):
    """Les courbes du geste exporté (motions/<clip>.json.gz)."""
    path = al.MOTIONS / f"{name}.json.gz"
    if not path.exists():
        return {}
    return json.load(gzip.open(path, "rt")).get("curves", {})


def scene_for(name, layout, motion=None):
    """Le décor du clip `name` (ou d'une variante « clip@départ »), comme le jeu le pose ; None si le clip n'en a pas."""
    clip, path = name, None
    if name in VARIANTS:
        clip, a, b = VARIANTS[name]
        path = (a, b)
    elif name in PATHS:
        path = PATHS[name]
    if path is not None:
        curves = motion.curves if motion is not None else curves_of(clip)
        yaw, roll = curves.get("ChairYaw"), curves.get("ChairRoll")
        c0, c1 = layout.chair_pose(path[0]), layout.chair_pose(path[1])
        if not yaw and not roll:
            return dc.Scene(layout, c0)

        def at(seq, f):
            return seq[min(f, len(seq) - 1)] if seq else 0.0

        def chair(f, yaw=yaw, roll=roll, c0=c0, c1=c1):
            return c0[0] + (c1[0] - c0[0]) * at(yaw, f), c0[1] + (c1[1] - c0[1]) * at(roll, f)
        return dc.Scene(layout, chair)
    if clip in STATIC:
        return dc.Scene(layout, layout.chair_pose(STATIC[clip]))
    return None


def scenes(layout):
    """Toutes les scènes connues (clips et variantes)."""
    out = {}
    for name in list(STATIC) + list(PATHS) + list(VARIANTS):
        sc = scene_for(name, layout)
        if sc is not None:
            out[name] = sc
    return out


# Les boîtes de contrôle des anciens clips (souris, livre) : la boîte → l'objet de la pièce.
HELD_OBJECTS = {"Livre": "book_desk_1", "Souris": "mouse"}


def split_held(held, layout):
    """
    Les objets tenus d'un clip, image par image (une liste de dicts) : (absolus, déplacements). Les clés qui sont des
    objets de la pièce (« mug », « pen ») portent un déplacement rigide depuis leur place ; les autres, une boîte de
    contrôle (matrice absolue), ramenée au vrai objet.
    """
    rows = {}
    for h in held:
        for k in h:
            rows.setdefault(k, None)
    absolute, moves = {}, {}
    for k in rows:
        seq = [h.get(k) for h in held]
        if k in layout.home:
            moves[k] = seq
        elif k in HELD_OBJECTS:
            absolute.update(_absolute(k, seq, layout))
    return absolute, moves


def held_matrices(name, layout):
    """Les objets tenus du clip (held/<clip>.json, écrit par atelier_desk.py) : (absolus, déplacements)."""
    path = al.WORKDIR / "held" / f"{name}.json"
    if not path.exists():
        return {}, {}
    data = json.loads(path.read_text())
    n = max((len(v) for v in data.values()), default=0)
    held = [{} for _ in range(n)]
    for k, rows in data.items():
        for i, r in enumerate(rows):
            if r is not None:
                held[i][k] = Matrix([r[0:4], r[4:8], r[8:12], r[12:16]])
    return split_held(held, layout)


def _absolute(box, rows, layout):
    oid = HELD_OBJECTS[box]
    if oid == "mouse":
        # Elle glisse sur le bureau, dans le sens de la main : sa place à plat et son lacet viennent du clip, sa
        # hauteur reste celle du tapis ; son grand axe (le modèle est un ovale) sur celui de la boîte de contrôle.
        (_, y, _), _ = layout.home["mouse"]
        axis = long_axis("mouse")
        fix = Vector((axis.x, axis.y, 0.0)).rotation_difference(Vector((0.0, -1.0, 0.0))).to_matrix().to_4x4()
        mats = []
        for m in rows:
            if m is None:
                mats.append(None)
                continue
            yaw = m.to_euler().z
            mats.append(Matrix.Translation((m.translation.x, m.translation.y, y - dc.FLOOR_DROP)) @ Matrix.Rotation(yaw, 4, "Z") @ fix)
        return {oid: mats}
    fix = Matrix.Rotation(math.pi / 2, 4, "Z") @ Matrix.Translation((0.0, 0.0, -0.014))
    return {oid: [None if m is None or m.translation.z < -1.0 else m @ fix for m in rows]}


def long_axis(oid):
    """Le grand axe d'un objet dans son modèle (vers son sommet le plus éloigné du centre)."""
    obj = dc.load(oid)
    c = sum((Vector(b) for b in obj.bound_box), Vector()) / 8
    far = max(obj.data.vertices, key=lambda v: (v.co - c).length)
    return (far.co - c).normalized()


def pen_axis():
    """L'axe long du stylo dans son modèle."""
    return long_axis("pen")


def grip(motion, scene, name, frames):
    """
    Ce que la main fait de l'objet de l'occupation, mesuré : la paume au-dessus de la souris ; le bout des doigts sur
    les touches ; l'index et le majeur dans l'anse de la tasse ; le stylo entre le pouce et l'index ; les mains posées à
    plat sur le bureau pendant qu'elles tirent ou repoussent la chaise. Les contacts ne disent que ce qui entre où : une
    paume posée à côté de la souris, sur le tapis, passait.
    """
    import atelier_desk
    import atelier_desk_gestures as gs
    rig = motion.rig
    lines = []

    class _D:
        pass
    d = _D()
    d.rig = rig
    if name == "desk_mouse":
        worst_d, worst_h = 0.0, 0.0
        for f in frames:
            scene.apply(f)
            mouse = dc.load("mouse")
            corners = [mouse.matrix_world @ Vector(c) for c in mouse.bound_box]
            c = sum(corners, Vector()) / 8
            top = max(p.z for p in corners)
            j = rig.joints(motion.frames[f], ("rightHand", "rightMiddleProximal"))
            palm = j["rightHand"].lerp(j["rightMiddleProximal"], 0.6)
            worst_d = max(worst_d, (palm.xy - c.xy).length)
            worst_h = max(worst_h, abs(palm.z - top - 0.025))
        lines.append(f"paume au-dessus de la souris : écart au centre {worst_d * 100:.1f} cm au plus, hauteur ±{worst_h * 100:.1f} cm")
    if name == "desk_type":
        scene.apply(0)
        kb = dc.load("keyboard")
        inv = kb.matrix_world.inverted()
        lo = Vector([min(v[i] for v in kb.bound_box) for i in range(3)])
        hi = Vector([max(v[i] for v in kb.bound_box) for i in range(3)])
        outside, low, high = 0, 1.0, -1.0
        for f in frames:
            for side in ("left", "right"):
                for p in atelier_desk.fingertips(d, motion.frames[f], side)[:4]:
                    q = inv @ p
                    if not (lo.x <= q.x <= hi.x and lo.y <= q.y <= hi.y):
                        outside += 1
                        continue
                    pad = q.z - atelier_desk.FINGER_PAD - hi.z
                    low, high = min(low, pad), max(high, pad)
        drop = atelier_desk.UNITY_FINGER_DROP
        lines.append(f"pulpe des doigts sur le clavier : {outside} hors des touches, de {low * 100:.1f} à {high * 100:.1f} cm "
                     f"du dessus des touches (dans le jeu, {(low - drop) * 100:.1f} à {(high - drop) * 100:.1f} cm)")
    hold = motion.curves.get("Hold")
    if name == "desk_drink" and hold:
        side = "left"
        feat = dc.features(scene.layout, scene.chair_at(0))
        hole0 = feat["mug"]["hole"]
        worst = 0.0
        held_frames = [f for f in range(len(motion.frames)) if hold[f] >= 0.25]
        moves = scene.moves.get("mug", [])
        for f in held_frames:
            pose = rig.fk(motion.frames[f])
            g = gs.handle_grip_point(d, side)(pose)
            m = moves[f] if f < len(moves) and moves[f] is not None else Matrix.Identity(4)
            worst = max(worst, (g - m @ hole0).length)
        lines.append(f"anse de la tasse : l'index et le majeur à {worst * 100:.1f} cm au plus du trou de l'anse ({len(held_frames)} images tenues)")
    if name in ("desk_take", "desk_write_start", "desk_write_end") and hold:
        side = "left" if name == "desk_take" else "right"
        feat = dc.features(scene.layout, scene.chair_at(0))
        c0 = feat["pen"]["center"]
        moves = scene.moves.get("pen", [])
        worst = 0.0
        held_frames = [f for f in range(len(motion.frames)) if 0.25 <= hold[f] <= 0.55]
        for f in held_frames:
            pose = rig.fk(motion.frames[f])
            g = gs.pinch_point(d, side)(pose)
            m = moves[f] if f < len(moves) and moves[f] is not None else Matrix.Identity(4)
            worst = max(worst, (g - m @ c0).length)
        lines.append(f"stylo pincé : le pouce et l'index à {worst * 100:.1f} cm au plus de son milieu ({len(held_frames)} images)")
    on = motion.curves.get("HandsOnDesk")
    if on:
        worst_h, worst_slide = 0.0, 0.0
        first = {}
        top = 0.74
        for f in range(len(motion.frames)):
            if on[f] < 0.95:
                continue
            chair = scene.chair_at(f)
            for side in ("left", "right"):
                pose = rig.fk(motion.frames[f])
                hand = head(rig, pose, f"{side}Hand").lerp(head(rig, pose, f"{side}MiddleProximal"), 0.5)
                seat = dc.to_seat(hand, chair)
                first.setdefault(side, seat)
                worst_slide = max(worst_slide, math.hypot(seat[0] - first[side][0], seat[2] - first[side][2]))
                worst_h = max(worst_h, abs(hand.z - top - 0.025))
        lines.append(f"mains sur le bureau : la paume glisse de {worst_slide * 100:.1f} cm au plus sur le plateau pendant que la chaise roule, "
                     f"hauteur ±{worst_h * 100:.1f} cm")
    return lines


def head(rig, pose, h):
    return pose[rig.hmap[h]].translation


def verify(rig, names, previews=True):
    """Les clips `names` (exportés) contre le décor réel : contacts mesurés et, si demandé, une planche chacun."""
    al.rehearsal(True)
    layout = dc.Layout()
    print(f"[vérif] taper : chaise {layout.chair_pose('type')[0]:.1f}° / {layout.chair_pose('type')[1]:.3f} m ; écrire : "
          f"{layout.chair_pose('write')[0]:.1f}° / {layout.chair_pose('write')[1]:.3f} m", flush=True)
    contacts = dc.Contacts(rig)
    # Les meubles, et ce que ses mains touchent sur le bureau (une main dans le clavier ou dans la souris passait).
    targets = ("desk_chair", "writing_desk", "keyboard", "mouse", "desk_mat", "notebook", "monitor", "mug", "desk_lamp")
    wanted = list(names) + [v for v, (clip, _, _) in VARIANTS.items() if clip in names]
    for name in wanted:
        clip = VARIANTS[name][0] if name in VARIANTS else ("desk_lap" if name == "desk_lap_droite" else name)
        if not (al.MOTIONS / f"{clip}.json.gz").exists():
            continue
        motion = load_motion(rig, clip)
        motion.curves = curves_of(clip)
        scene = scene_for(name, layout, motion)
        if scene is None:
            continue
        absolute, moves = held_matrices(clip, layout)
        scene.held = absolute
        scene.moves = moves
        n = len(motion.frames)
        frames = range(0, n, max(1, n // 12))
        found = contacts.check(motion, scene, targets, frames)
        lines = dc.report(found)
        print(f"[vérif] {name} ({n} images) : " + ("aucun contact" if not lines else ""), flush=True)
        for line in lines:
            print(f"[vérif]     {line}", flush=True)
        for line in grip(motion, scene, name, list(frames)):
            print(f"[vérif]     {line}", flush=True)
        if not previews:
            continue
        picks = [round(i * (n - 1) / 3) for i in range(4)]
        views = (("pieds", (1.05, -0.55, -0.25)), ("cote", (1.7, 0.1, 0.05)), ("face", (-0.5, -1.6, 0.35)), ("dessus", (0.35, 0.6, 1.05)))
        dc.render_sheet(motion, scene, f"verif_{name}", views, picks, focus=(0.0, -0.25, 0.45))


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--no-previews", action="store_true")
    args = ap.parse_args(argv)
    rig = al.Rig(al.mika_armature())
    layout = dc.Layout()
    names = [n for n in args.only.split(",") if n] or list(STATIC) + list(PATHS)
    verify(rig, names, previews=not args.no_previews)


if __name__ == "__main__":
    main()
