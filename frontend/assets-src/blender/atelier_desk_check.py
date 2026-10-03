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


def scenes(layout):
    """Le décor de chaque clip, comme BodyActivity le pose."""
    ty, tr = layout.typing()
    wy, wr = layout.writing()

    def at(oid, xz, yaw=None):
        (_, y, _), home_yaw = layout.home[oid]
        return (xz[0], y, xz[1]), (home_yaw if yaw is None else yaw)

    work = {
        "mouse": at("mouse", layout.work_spot(ty, tr, dc.MOUSE_SPOT, 0.07), ty),
        "mug": at("mug", layout.work_spot(ty, tr, dc.MUG_SPOT, 0.08)),
        "pen": at("pen", layout.work_spot(ty, tr, dc.PEN_SPOT, 0.08), ty - 25.0),
    }
    write = dict(work)
    write["mug"] = at("mug", layout.work_spot(wy, wr, dc.WRITE_MUG_SPOT, 0.08))
    write["notebook"] = at("notebook", layout.writing_spot(), -8.0)

    def turning(y0, y1, r0, r1, seconds):
        n = seconds * 30

        def chair(f):
            k = ease(f / n * seconds, 0.1, seconds - 0.25)
            return y0 + (y1 - y0) * k, r0 + (r1 - r0) * min(1.0, k * 1.6)
        return chair

    toward = -70.0   # quelqu'un à sa gauche (la démo) ; le symétrique se vérifie par les clips de droite
    out = {}
    for name in ("desk_rest", "desk_type", "desk_mouse", "desk_think", "desk_stretch", "desk_drink", "desk_take", "desk_read"):
        out[name] = dc.Scene(layout, (ty, tr), moved=work, hidden=("pen",) if name == "desk_take" else ())
    out["desk_write"] = dc.Scene(layout, (wy, wr), moved=write, hidden=("pen",))
    out["desk_lap"] = dc.Scene(layout, (toward, 0.0), moved=work)
    out["desk_lap_droite"] = dc.Scene(layout, (ty + 70.0, 0.0), moved=work)
    # Les clips de posture : assise au bureau (chaise d'origine) ; s'asseoir et se lever, chaise reculée (ActorBody :
    # PullOut) — le clip finit (ou commence) assis à l'origine, sur la chaise.
    out["sitting_idle"] = dc.Scene(layout, (0.0, 0.0))
    out["sit_down"] = dc.Scene(layout, (0.0, -0.28))
    out["stand_up"] = dc.Scene(layout, (0.0, -0.28))
    out["chair_turn_left_90"] = dc.Scene(layout, turning(ty, toward, tr, 0.0, 2.0), moved=work)
    out["chair_turn_right_90"] = dc.Scene(layout, turning(toward, ty, 0.0, tr, 2.0), moved=work)
    out["chair_turn_left_45"] = dc.Scene(layout, turning(ty, ty - 45.0, tr, tr, 1.4), moved=work)
    out["chair_turn_right_45"] = dc.Scene(layout, turning(ty, ty + 45.0, tr, tr, 1.4), moved=work)
    return out


HELD_OBJECTS = {"Tasse": "mug", "Stylo": "pen", "Objet": "pen", "Livre": "book_desk_1", "Souris": "mouse"}


def held_matrices(name, layout):
    """Les objets tenus du clip (held/<clip>.json, écrit par atelier_desk.py), ramenés aux vrais objets : du centre de
    la boîte de contrôle au pivot du modèle (le bas, au centre), l'axe long du stylo sur celui de la boîte."""
    path = al.WORKDIR / "held" / f"{name}.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    out = {}
    for box, rows in data.items():
        oid = HELD_OBJECTS.get(box)
        if oid is None:
            continue
        fix = Matrix.Identity(4)
        if oid == "mouse":
            # Elle glisse sur le bureau : seule sa place à plat vient du clip, sa hauteur et son orientation restent
            # celles qu'Unity lui donne (tournée comme la chaise, posée sur le tapis).
            (_, y, _), _ = layout.home["mouse"]
            out[oid] = [None if r is None else
                        Matrix.Translation((r[3], r[7], y - dc.FLOOR_DROP)) @ Matrix.Rotation(0.0, 4, "Z")
                        for r in rows]
            continue
        if oid == "mug":
            fix = Matrix.Translation((0.0, 0.0, -0.049))
        elif oid == "book_desk_1":
            fix = Matrix.Rotation(math.pi / 2, 4, "Z") @ Matrix.Translation((0.0, 0.0, -0.014))
        elif oid == "pen":
            axis = pen_axis()
            to = Vector((0.0, 0.0, 1.0)) if box == "Stylo" else Vector((1.0, 0.0, 0.0))
            fix = axis.rotation_difference(to).to_matrix().to_4x4()
        mats = []
        for r in rows:
            if r is None:
                mats.append(None)
                continue
            m = Matrix([r[0:4], r[4:8], r[8:12], r[12:16]])
            # Une boîte « rangée » sous le sol : l'objet n'est pas tenu à cette image, il est à sa place.
            mats.append(None if m.translation.z < -1.0 else m @ fix)
        out[oid] = mats
    return out


def pen_axis():
    """L'axe long du stylo dans son modèle (vers son sommet le plus éloigné du centre)."""
    pen = dc.load("pen")
    c = sum((Vector(b) for b in pen.bound_box), Vector()) / 8
    far = max(pen.data.vertices, key=lambda v: (v.co - c).length)
    return (far.co - c).normalized()


def grip(motion, scene, name, frames):
    """
    Ce que la main fait de l'objet de l'occupation, mesuré : la paume (entre le poignet et la base des doigts) au-dessus
    du centre de la souris ; le bout des doigts sur les touches du clavier. Les contacts ne disent que ce qui entre
    où : une paume posée à côté de la souris, sur le tapis, passait.
    """
    rig = motion.rig
    lines = []
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
        outside, high = 0, 0.0
        for f in frames:
            j = rig.joints(motion.frames[f], ("leftIndexDistal", "rightIndexDistal", "leftMiddleDistal", "rightMiddleDistal"))
            for p in j.values():
                q = inv @ p
                if not (lo.x <= q.x <= hi.x and lo.y <= q.y <= hi.y):
                    outside += 1
                high = max(high, q.z - hi.z)
        lines.append(f"bout des doigts sur le clavier : {outside} hors des touches, au plus {high * 100:.1f} cm au-dessus")
    return lines


def verify(rig, names, previews=True):
    """Les clips `names` (exportés) contre le décor réel : contacts mesurés et, si demandé, une planche chacun."""
    al.rehearsal(True)
    layout = dc.Layout()
    print(f"[vérif] taper : chaise {layout.typing()[0]:.1f}° / {layout.typing()[1]:.3f} m ; écrire : "
          f"{layout.writing()[0]:.1f}° / {layout.writing()[1]:.3f} m", flush=True)
    contacts = dc.Contacts(rig)
    targets = ("desk_chair", "writing_desk")
    all_scenes = scenes(layout)
    for name in names:
        scene = all_scenes.get(name)
        if scene is None:
            continue
        clip = "desk_lap" if name == "desk_lap_droite" else name
        motion = load_motion(rig, clip)
        held = held_matrices(clip, layout)
        if held:
            scene.held = held
            scene.hidden = scene.hidden - set(held)
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
    names = [n for n in args.only.split(",") if n] or list(scenes(layout))
    verify(rig, names, previews=not args.no_previews)


if __name__ == "__main__":
    main()
