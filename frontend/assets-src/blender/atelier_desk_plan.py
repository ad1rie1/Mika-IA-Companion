# Le plan du bureau : où poser la souris, le carnet, le stylo et la tasse pour qu'elle s'en serve sans que rien ne
# glisse tout seul. Chaque objet est posé, une fois pour toutes, là où le geste qui l'utilise l'attend :
#   - la souris à sa place de travail quand elle tape (chaise tournée et avancée vers le clavier : P_type) ;
#   - le carnet devant elle, un peu à droite, quand la chaise a pivoté de 45° vers sa gauche depuis P_type (P_write) ;
#   - le stylo sur le carnet, le long de son bord droit ;
#   - la tasse devant à gauche (le seul endroit à portée de ses petits bras que ni le clavier, ni la souris, ni le
#     carnet n'occupent), son anse vers l'extérieur : la main gauche la prend à côté, les doigts dedans.
# Le script mesure les recouvrements (empreintes au sol des vrais modèles) et la marge au bord du plateau, rend une vue
# de dessus (previews/plan_bureau.png) et écrit les places (repère du siège, Unity) et leur équivalent dans la pièce
# (coordonnées three.js de build_desk.py) dans ArtSource/atelier/desk_plan.json.
#
#   blender -b UnityFrontend/ArtSource/atelier/mika_rig.blend --python frontend/assets-src/blender/atelier_desk_plan.py
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atelier_decor as dc  # noqa: E402
import atelier_lib as al  # noqa: E402

# Le repère du siège (chaise d'origine) → la pièce (three.js) : la chaise est en CHAIR_POS, tournée de CHAIR_YAW (rad).
CHAIR_POS = (-1.4, -3.3)
CHAIR_YAW = 0.3
C, S = math.cos(CHAIR_YAW), math.sin(CHAIR_YAW)

TURN_WRITE = -45.0          # écrire : la chaise pivote de 45° vers sa gauche depuis P_type (un pas des pieds)
WRITE_FORWARD = 0.42        # le carnet devant elle (repère de P_write) …
WRITE_LATERAL = 0.05        # … un peu à sa droite : elle écrit de la main droite, et la tasse tient à gauche
NOTEBOOK_TURN = 20.0        # le carnet tourné de 20° de plus que sa chaise (vers sa droite) : comme on tourne un cahier pour écrire
MUG = (-0.40, 0.24)         # la tasse, repère de travail de P_type (à droite, devant) : devant à gauche, à portée de sa main gauche
MUG_HANDLE_CLIP = (0.79, 0.61)  # son anse, vue d'elle à P_type (repère du clip : sa gauche, vers elle) — la main la prend à côté
# (atelier_desk_search.py : la meilleure place libre à portée de ses petits bras)
MARGIN = 0.015              # au bord du plateau


def to_room(x, z):
    """Un point du repère du siège (x à droite, z devant) → la pièce (three.js x, z)."""
    return CHAIR_POS[0] + C * x - S * z, CHAIR_POS[1] - S * x - C * z


def handle_local():
    """La direction de l'anse de la tasse dans son modèle (Blender, à plat) : le sommet le plus loin de son axe."""
    obj = dc.load("mug")
    pts = [v.co for o in dc.meshes(obj) for v in o.data.vertices]
    cx = sum(p.x for p in pts) / len(pts)
    cy = sum(p.y for p in pts) / len(pts)
    # L'axe : le centre du corps de la tasse (la moyenne est tirée vers l'anse ; on prend le milieu de l'étendue opposée).
    far = max(pts, key=lambda p: math.hypot(p.x - cx, p.y - cy))
    d = Vector((far.x - cx, far.y - cy))
    return math.atan2(d.y, d.x)


def footprint(oid):
    """L'enveloppe convexe (au sol, monde) des sommets du modèle posé."""
    pts = []
    for o in dc.meshes(dc.load(oid)):
        mw = o.matrix_world
        pts += [(mw @ v.co).xy.to_tuple() for v in o.data.vertices]
    return footprint_pts(pts)


def footprint_pts(pts):
    """L'enveloppe convexe d'une liste de points (x, y)."""
    pts = sorted(set((round(x, 4), round(y, 4)) for x, y in pts))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def poly_gap(a, b):
    """La distance entre deux polygones convexes (0 s'ils se touchent ou se recouvrent)."""
    def inside(p, poly):
        sign = None
        for i in range(len(poly)):
            q, r = poly[i], poly[(i + 1) % len(poly)]
            c = (r[0] - q[0]) * (p[1] - q[1]) - (r[1] - q[1]) * (p[0] - q[0])
            if abs(c) < 1e-12:
                continue
            s = c > 0
            if sign is None:
                sign = s
            elif s != sign:
                return False
        return True

    def seg_dist(p, q, r):
        qr = (r[0] - q[0], r[1] - q[1])
        L = qr[0] ** 2 + qr[1] ** 2
        t = 0 if L == 0 else max(0, min(1, ((p[0] - q[0]) * qr[0] + (p[1] - q[1]) * qr[1]) / L))
        return math.hypot(p[0] - q[0] - t * qr[0], p[1] - q[1] - t * qr[1])
    if any(inside(p, b) for p in a) or any(inside(p, a) for p in b):
        return 0.0
    return min(min(seg_dist(p, b[i], b[(i + 1) % len(b)]) for p in a for i in range(len(b))),
               min(seg_dist(p, a[i], a[(i + 1) % len(a)]) for p in b for i in range(len(a))))


def main():
    al.rehearsal(True)
    layout = dc.Layout()
    ty, tr = layout.typing()
    wy, wr = ty + TURN_WRITE, tr
    # Le carnet : droit devant elle (P_write), repoussé sur le plateau s'il déborde ; tourné comme sa chaise.
    ahead_w = (math.sin(math.radians(wy)), math.cos(math.radians(wy)))
    want = layout.work_point(wy, wr, (WRITE_LATERAL, WRITE_FORWARD))
    nb = layout.onto_desk(want, ahead_w, 0.135 + MARGIN)
    nb_yaw = wy + NOTEBOOK_TURN
    # Où il est dans le repère d'écriture (le clip d'écriture le veut là).
    ox, oz = 0.0, wr
    a = math.radians(wy)
    rel = (nb[0] - ox, nb[1] - oz)
    nb_local = (rel[0] * math.cos(a) - rel[1] * math.sin(a), rel[0] * math.sin(a) + rel[1] * math.cos(a))
    # La souris : sa place de travail (P_type), le grand axe dans le sens de la main.
    ms = layout.work_spot(ty, tr, dc.MOUSE_SPOT, 0.07)
    ms_yaw = ty - 6.0
    # Le stylo : sur le carnet, le long de son bord droit (repère du carnet : x à droite, z vers le haut de la page).
    pen_local = (0.06, 0.0)
    na = math.radians(nb_yaw)
    pen = (nb[0] + pen_local[0] * math.cos(na) + pen_local[1] * math.sin(na),
           nb[1] - pen_local[0] * math.sin(na) + pen_local[1] * math.cos(na))
    moved = {
        "notebook": ((nb[0], 0.76, nb[1]), nb_yaw),
        "pen": ((pen[0], 0.76 + 0.012 + 0.0045, pen[1]), nb_yaw),
        "mouse": ((ms[0], 0.747, ms[1]), ms_yaw),
        "mug": ((0.0, 0.76, 0.0), 0.0),
    }
    # La tasse : sa place et la direction de son anse, données dans le repère de travail de P_type, ramenées au siège.
    mx, mz = layout.work_point(ty, tr, MUG)
    want = math.atan2(MUG_HANDLE_CLIP[1], MUG_HANDLE_CLIP[0])
    # Le modèle posé avec le lacet Unity y (vu d'elle : y − ty) est tourné de −(y − ty) autour de Z (Blender).
    yaw_her = math.degrees(handle_local() - want)
    moved["mug"] = ((mx, 0.76, mz), yaw_her + ty)
    report = {}
    for name, (cy, cr) in (("P_type", (ty, tr)), ("P_write", (wy, wr))):
        scene = dc.Scene(layout, (cy, cr), moved=moved)
        scene.apply(0)
        objs = ("keyboard", "mouse", "mug", "notebook", "pen", "desk_lamp", "monitor", "pen_cup", "book_desk_1",
                "succulent_desk", "desk_mat")
        prints = {o: footprint(o) for o in objs if o in layout.home}
        if name == "P_type":
            for i, o1 in enumerate(["mouse", "mug", "notebook", "pen"]):
                for o2 in prints:
                    if o2 == o1 or o2 == "desk_mat" or (o1, o2) in (("pen", "notebook"),) or (o2, o1) in (("pen", "notebook"),):
                        continue
                    g = poly_gap(prints[o1], prints[o2])
                    if g < 0.04:
                        report.setdefault("proches", []).append(f"{o1} ↔ {o2} : {g * 100:.1f} cm")
        cam = bpy.data.objects.get("PlanCam") or bpy.data.objects.new("PlanCam", bpy.data.cameras.new("PlanCam"))
        if cam.name not in bpy.context.scene.collection.objects:
            bpy.context.scene.collection.objects.link(cam)
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = 1.6
        cam.location = Vector((0.0, -0.55, 2.5))
        cam.rotation_euler = (0.0, 0.0, 0.0)
        sc = bpy.context.scene
        sc.camera = cam
        sc.render.engine = "BLENDER_WORKBENCH"
        sc.display.shading.color_type = "MATERIAL"
        sc.render.resolution_x, sc.render.resolution_y = 640, 640
        sc.render.filepath = str(al.PREVIEWS / f"plan_bureau_{name}.png")
        motion = __import__("atelier_desk_check").load_motion(al.Rig(al.mika_armature()), "desk_rest")
        motion.pose(0)
        bpy.ops.render.render(write_still=True)
    out = {
        "note": "places des objets du bureau (repère du siège, Unity : x à droite, z devant ; lacet en degrés) et dans la pièce (three.js)",
        "P_type": [round(ty, 3), round(tr, 4)],
        "P_write": [round(wy, 3), round(wr, 4)],
        "notebook_in_write_frame": [round(nb_local[0], 4), round(nb_local[1], 4)],
        "objects": {},
    }
    for oid, ((x, y, z), yaw) in moved.items():
        rx, rz = to_room(x, z)
        out["objects"][oid] = {"seat": [round(x, 4), round(y, 4), round(z, 4)], "yaw": round(yaw, 3),
                               "room": [round(rx, 4), round(rz, 4)], "room_ry": round(math.radians(-yaw) - math.radians(162.8113), 4)}
    out["report"] = report
    (al.WORKDIR / "desk_plan.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print("PLAN", json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
