# Atelier d'animation de Mika — debout devant un meuble : à la fenêtre (les mains posées sur l'appui, le regard dehors)
# et devant la bibliothèque (le regard qui parcourt les rayons, la main qui effleure les tranches). Construits sur son
# attente debout (idle_breathing de l'atelier : jambes, bassin et bras au repos), devant les vrais meubles posés comme
# Unity les pose (relevés ArtSource/atelier/window_layout.json et shelf_layout.json, repère du lieu : origine au sol là
# où elle se tient, z devant elle), et vérifiés contre eux (contacts mesurés, planches previews/verif_<clip>.png).
#
#   blender -b frontend/Unity/ArtSource/atelier/mika_rig.blend --python frontend/Web/assets-src/blender/atelier_stand.py -- \
#       [--only window_lean] [--no-previews]
#
# Avant ces gestes, le regard d'une occupation debout était posé par l'IK d'Unity, le buste compris : regarder un livre
# bas pliait le buste à 57° vers les rayons, et la main partait vers une tranche tirée au hasard, paume tournée de 70°.
import argparse
import gzip
import json
import math
import sys
from pathlib import Path

from mathutils import Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atelier_decor as dc  # noqa: E402
import atelier_desk as ad  # noqa: E402
import atelier_desk_check as ck  # noqa: E402
import atelier_lib as al  # noqa: E402

FPS = 30
TAU = 2 * math.pi
Z = Vector((0.0, 0.0, 1.0))


def standing_base(rig):
    """La pose debout de départ : l'attente calme de l'atelier (idle_breathing, image 0), tout le corps."""
    data = json.load(gzip.open(al.MOTIONS / "idle_breathing.json.gz", "rt"))
    row = data["frames"][0]
    d = {h: Quaternion(row[3 + 4 * k: 7 + 4 * k]) @ rig.rest[h].inverted() for k, h in enumerate(data["bones"])}
    return {"hips": Vector(row[:3]), "d": d}


class Place:
    """Un lieu debout et ses meubles : le relevé Unity, les objets posés (le sol du clip est le vrai sol)."""

    def __init__(self, layout_file, objects):
        self.layout = dc.Layout(al.WORKDIR / layout_file)
        self.objects = tuple(o for o in objects if o in self.layout.home)

    def scene(self):
        return dc.Scene(self.layout, (0.0, 0.0), objects=self.objects)

    def points(self, oid):
        self.scene().apply(0)
        return [o.matrix_world @ v.co for o in dc.meshes(dc.load(oid)) for v in o.data.vertices]


# --- à la fenêtre --------------------------------------------------------------------------------------------------
def window_geometry(place):
    """L'appui : son bord avant (distance devant elle), son dessus, sa largeur (repère du clip : elle regarde −Y)."""
    pts = place.points("window_pane")
    # L'appui est la partie la plus avancée vers elle, à hauteur de ses coudes.
    sill = [p for p in pts if 0.7 < p.z < 1.1]
    front = max(p.y for p in sill)                 # le bord le plus proche d'elle (y le plus grand : elle regarde −Y)
    top = max(p.z for p in sill if p.y > front - 0.05)
    xs = [p.x for p in sill]
    return dict(front=front, top=top, left=max(xs), right=min(xs))


def window_lean(desk, t, period):
    """
    À la fenêtre : penchée un peu, les mains posées à plat sur l'appui, près de son bord ; le regard flâne dehors (le
    ciel, la rue, un point puis un autre) ; de temps en temps elle passe d'un pied sur l'autre et pianote sur l'appui.
    """
    g = desk.window
    f = ad.copy(desk.standing)
    breathe = math.sin(TAU * 2 * t / period)
    sway = math.sin(TAU * t / period)
    ad.lean(f, 10.0 + 0.8 * breathe, turn_deg=2.5 * sway, side_deg=1.5 * sway)
    for side, sx in (("left", 1.0), ("right", -1.0)):
        wrist = Vector((sx * 0.14 + 0.01 * sway, g["front"] - 0.075, g["top"] + 0.03))
        fingers = Vector((-sx * 0.25, -1.0, -0.12))
        palm = Vector((-sx * 0.1, 0.0, -1.0))
        ad.arm_ik(desk, f, side, wrist, Vector((sx * 0.26, 0.02, 0.85)), fingers, palm)
        tap = [ad.bump((t + 0.13 * i + (0.0 if side == "left" else 0.6)) % 3.0, 1.8, 0.16) for i in range(4)]
        ad.curl(desk, f, side, {n: (10 + 18 * d, 14 + 8 * d, 6) for n, d in zip(("Little", "Ring", "Middle", "Index"), tap)},
                thumb=(8.0, 6.0, 3.0), spread=4.0)
    # Le regard dehors : loin, au-delà de la vitre, flânant d'un point à l'autre (périodique : la boucle se referme).
    out = Vector((0.9 * ad.noise(t, period, 91), g["front"] - 6.0, 1.4 + 0.9 * ad.noise(t, period, 93)))
    ad.look(desk, f, out, neck_share=0.35)
    return f


# --- devant la bibliothèque ----------------------------------------------------------------------------------------
def shelf_geometry(place):
    """Les rangées de livres : pour chacune, sa hauteur (milieu des tranches) et la face des tranches (devant elle)."""
    rows = []
    for oid in ("books_shelf_1", "books_shelf_2", "books_shelf_3", "books_shelf_4"):
        if oid not in place.layout.home:
            continue
        pts = place.points(oid)
        rows.append(dict(id=oid, front=max(p.y for p in pts), low=min(p.z for p in pts), high=max(p.z for p in pts),
                         left=max(p.x for p in pts), right=min(p.x for p in pts)))
    return rows


def shelf_browse(desk, t, period):
    """
    Devant la bibliothèque : le regard parcourt les tranches d'un côté à l'autre (devant elle, sans se tordre), descend
    à la rangée du dessous et remonte, la tête un peu penchée pour lire ; deux fois par boucle la main droite vient
    effleurer les tranches, glisse le long de quelques livres et retombe ; la gauche reste le long du corps.
    """
    rows = desk.shelf
    eye_row = min(rows, key=lambda r: abs((r["low"] + r["high"]) / 2 - 1.15))
    low_row = min(rows, key=lambda r: abs((r["low"] + r["high"]) / 2 - 0.95))
    f = ad.copy(desk.standing)
    breathe = math.sin(TAU * 2 * t / period)
    # Le regard : d'un côté à l'autre (±22 cm devant elle), la rangée à hauteur d'yeux puis celle du dessous.
    x = 0.22 * math.sin(TAU * t / period)
    down = 0.5 - 0.5 * math.cos(TAU * t / period)            # 0 → 1 → 0 : la rangée du dessous au milieu de la boucle
    mid_eye = (eye_row["low"] + eye_row["high"]) / 2
    mid_low = (low_row["low"] + low_row["high"]) / 2
    front = max(eye_row["front"], low_row["front"])
    target = Vector((x, front, mid_eye + (mid_low - mid_eye) * down))
    # La main : deux effleurements par boucle (à 2,5 s et à 8,5 s), sur la rangée qu'elle lit.
    reach = 0.0
    slide = 0.0
    for t0 in (period * 0.18, period * 0.68):
        k = ad.ease(t, t0, t0 + 0.7) * (1.0 - ad.ease(t, t0 + 2.2, t0 + 2.9))
        if k > reach:
            reach = k
            slide = ad.ease(t, t0 + 0.7, t0 + 2.2)
    ad.lean(f, 5.0 + 4.0 * reach + 4.0 * down + 0.6 * breathe, turn_deg=-5.0 * reach, side_deg=0.0)
    if reach > 0.0:
        rest_w = desk.rig.joints(f, ("rightHand",))["rightHand"]
        rest = {k: q.copy() for k, q in f["d"].items() if k.startswith("right") and k not in ("rightUpperLeg", "rightLowerLeg", "rightFoot", "rightToes")}
        row_mid = mid_eye + (mid_low - mid_eye) * down
        touch = Vector((-0.10 - 0.10 * slide, front + 0.012, row_mid + 0.03))
        fingers = Vector((0.15, -1.0, -0.25))
        palm = Vector((0.85, 0.0, -0.3))
        wrist = touch - fingers.normalized() * 0.085
        q_touch = ad.hand_rotation(desk, "right", fingers, palm)
        ad.arm_ik(desk, f, "right", rest_w.lerp(wrist, reach), Vector((-0.25, 0.05, 0.95)), None, None,
                  hand_rot=rest["rightHand"].slerp(q_touch, reach))
        ad.curl(desk, f, "right", {"Index": (8, 10, 6), "Middle": (10, 12, 6), "Ring": (20, 25, 10), "Little": (25, 30, 12)},
                thumb=(15.0, 8.0, 4.0), spread=3.0)
        # Le bras et les doigts passent de leur repos à l'effleurement avec la main (pas d'un coup quand elle part).
        for k, q in rest.items():
            f["d"][k] = q.slerp(f["d"][k], reach)
        target = target.lerp(touch, 0.5 * reach)
    # La tête suit les tranches (cou et tête, pas le buste), penchée sur le côté pour les lire.
    ad.look(desk, f, target, neck_share=0.45)
    tilt = math.radians(-12.0 * (0.5 + 0.5 * math.sin(TAU * 2 * t / period)))
    head = f["d"]["head"]
    fwd = head @ Vector((0.0, -1.0, 0.0))
    f["d"]["head"] = Quaternion(fwd, tilt) @ head
    return f


CLIPS = {
    "window_lean": dict(build=window_lean, seconds=12.0, loop=True, place="window", note="à la fenêtre, les mains sur l'appui"),
    "shelf_browse": dict(build=shelf_browse, seconds=12.0, loop=True, place="shelf", note="devant la bibliothèque, parcourir les rayons"),
}

PLACES = {
    "window": ("window_layout.json", ("window_pane", "room_walls", "curtains", "cactus_windowsill", "succulent_windowsill")),
    "shelf": ("shelf_layout.json", ("shelves", "books_shelf_0", "books_shelf_1", "books_shelf_2", "books_shelf_3", "books_shelf_4",
                                    "vase_bookshelf", "cactus_bookshelf", "photo_frame_bookshelf", "storage_box_bookshelf",
                                    "shelf_basket_1", "shelf_basket_2", "room_walls")),
}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--no-previews", action="store_true")
    args = ap.parse_args(argv)
    only = [n for n in args.only.split(",") if n]
    # Debout, le sol du clip est le vrai sol (les attentes sont posées dessus).
    dc.FLOOR_DROP = 0.0
    rig = al.Rig(al.mika_armature())
    al.rehearsal(True)
    desk = ad.Desk(rig)
    desk.standing = standing_base(rig)
    places = {k: Place(*v) for k, v in PLACES.items()}
    desk.window = window_geometry(places["window"])
    desk.shelf = shelf_geometry(places["shelf"])
    print(f"[debout] appui de fenêtre : bord à {-desk.window['front']:.2f} m devant elle, dessus à {desk.window['top']:.2f} m", flush=True)
    print(f"[debout] rayons : " + ", ".join(f"{r['id']} {r['low']:.2f}–{r['high']:.2f} m à {-r['front']:.2f} m" for r in desk.shelf), flush=True)
    clearance = al.Clearance(rig)
    contacts = dc.Contacts(rig)
    for name, spec in CLIPS.items():
        if only and name not in only:
            continue
        place = places[spec["place"]]
        n = int(round(spec["seconds"] * FPS))
        frames = [spec["build"](desk, i / FPS, spec["seconds"]) for i in range(n)]
        frames.append(ad.copy(frames[0]))
        motion = al.Motion(rig, name, frames, loop=True)
        al.clear_arms(motion, clearance, margin=0.004)
        jump = al.jumps(motion)
        path = motion.export(note=f"atelier debout — {spec['note']} — saut max {jump['saut']}° ({jump['os']})")
        print(f"[debout] {name} : {len(frames)} images, saut max {jump['saut']}° ({jump['os']}) → {path}", flush=True)
        scene = place.scene()
        targets = tuple(o for o in place.objects if o != "room_walls") + (("room_walls",) if "room_walls" in place.objects else ())
        found = contacts.check(motion, scene, targets, range(0, len(frames), max(1, len(frames) // 24)))
        lines = dc.report(found)
        print(f"[vérif] {name} : " + ("aucun contact" if not lines else ""), flush=True)
        for line in lines:
            print(f"[vérif]     {line}", flush=True)
        if not args.no_previews:
            picks = [round(i * (len(frames) - 1) / 3) for i in range(4)]
            views = (("cote", (1.6, 0.2, 0.4)), ("face", (0.6, -0.15, 0.5)), ("dos", (0.9, 1.6, 0.6)))
            dc.render_sheet(motion, scene, f"verif_{name}", views, picks, focus=(0.0, -0.25, 1.0))


if __name__ == "__main__":
    main()
