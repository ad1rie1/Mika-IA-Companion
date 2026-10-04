# Cherche, sur le vrai bureau, une place pour la tasse et le carnet qui convienne à ses gestes : la tasse à portée de sa
# main gauche quand elle tape (P_type), le carnet devant elle quand la chaise a pivoté de 45° vers sa gauche (P_write),
# le stylo couché sur le carnet, rien qui se touche ni ne déborde du plateau. Empreintes au sol des vrais modèles
# (enveloppes convexes), déplacées sans recharger la scène. Imprime les meilleures solutions.
#
#   blender -b frontend/Unity/ArtSource/atelier/mika_rig.blend --python frontend/Web/assets-src/blender/atelier_desk_search.py
import math
import sys
from pathlib import Path

from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atelier_decor as dc  # noqa: E402
import atelier_desk_plan as plan  # noqa: E402

SHOULDER_L = Vector((0.089, 0.036))      # épaule gauche, repère du clip (x : sa gauche, y : derrière), assise
REACH = 0.47                              # le trou de l'anse au plus à cette distance de l'épaule (bras + penché)
GAP = 0.015


def hull_local(oid, layout):
    """L'empreinte du modèle dans le repère du siège, relative à son origine (x, z), et son origine."""
    sc = dc.Scene(layout, (0.0, 0.0))
    sc.apply(0)
    pts = [o.matrix_world @ v.co for o in dc.meshes(dc.load(oid)) for v in o.data.vertices]
    seat = [dc.to_seat(p, (0.0, 0.0)) for p in pts]
    (ox, _, oz), _ = layout.home[oid]
    poly = plan.footprint_pts([(x - ox, z - oz) for x, _, z in seat])
    return poly


def place(poly, at, rot_deg):
    a = math.radians(rot_deg)
    c, s = math.cos(a), math.sin(a)
    return [(at[0] + x * c + z * s, at[1] - x * s + z * c) for x, z in poly]


def main():
    layout = dc.Layout()
    ty, tr = layout.typing()
    wy, wr = ty - 45.0, tr
    e0, e1, n = layout.desk_edge()
    fixed = {}
    for oid in ("keyboard", "mouse", "desk_lamp", "monitor", "pen_cup", "desk_mat"):
        (ox, _, oz), _ = layout.home[oid]
        fixed[oid] = place(hull_local(oid, layout), (ox, oz), 0.0)
    mug0 = hull_local("mug", layout)
    nb0 = hull_local("notebook", layout)
    pen0 = hull_local("pen", layout)
    (mx0, _, mz0), _ = layout.home["mug"]
    (nx0, _, nz0), _ = layout.home["notebook"]
    (px0, _, pz0), _ = layout.home["pen"]
    feat = dc.features(layout, (0.0, 0.0))
    # La tasse : son anse, relative à son origine (repère du siège).
    hole_seat = dc.to_seat(feat["mug"]["hole"], (0.0, 0.0))
    hole_rel = (hole_seat[0] - mx0, hole_seat[2] - mz0)

    def on_desk(poly):
        return min((Vector(p) - e0).dot(n) for p in poly)

    best = []
    why = {}
    for nx in [i * 0.01 for i in range(-4, 13)]:          # carnet : décalage latéral (repère de P_write)
        for nf in [0.38 + i * 0.01 for i in range(0, 10)]:  # … et distance
            for nrot in (-20.0, -10.0, 0.0, 10.0, 20.0):     # … et rotation de plus que la chaise
                nc = layout.work_point(wy, wr, (nx, nf))
                nb = place(nb0, nc, nrot)                    # nb0 a déjà la rotation actuelle du carnet (wy)
                if on_desk(nb) < GAP:
                    why["carnet déborde"] = why.get("carnet déborde", 0) + 1
                    continue
                if any(plan.poly_gap(nb, fixed[k]) < GAP for k in ("keyboard", "desk_lamp", "monitor")):
                    why["carnet touche"] = why.get("carnet touche", 0) + 1
                    continue
                for mx in [-0.50 + i * 0.02 for i in range(0, 14)]:     # tasse : repère de P_type
                    for mz in [0.24 + i * 0.02 for i in range(0, 10)]:
                        for mrot in range(0, 360, 15):
                            mc = layout.work_point(ty, tr, (mx, mz))
                            mug = place(mug0, mc, mrot)
                            if on_desk(mug) < GAP or plan.poly_gap(mug, nb) < GAP:
                                why["tasse déborde/carnet"] = why.get("tasse déborde/carnet", 0) + 1
                                continue
                            if any(plan.poly_gap(mug, fixed[k]) < GAP for k in ("keyboard", "desk_lamp", "mouse")):
                                why["tasse touche"] = why.get("tasse touche", 0) + 1
                                continue
                            a = math.radians(mrot)
                            hx = mc[0] + hole_rel[0] * math.cos(a) + hole_rel[1] * math.sin(a)
                            hz = mc[1] - hole_rel[0] * math.sin(a) + hole_rel[1] * math.cos(a)
                            hole = dc.to_clip((hx, 0.79, hz), (ty, tr))
                            centre = dc.to_clip((mc[0], 0.76, mc[1]), (ty, tr))
                            reach = (hole.xy - SHOULDER_L).length
                            if reach > REACH:
                                why["trop loin"] = why.get("trop loin", 0) + 1
                                continue
                            # L'anse vers l'extérieur (sa gauche, +x du clip) : la main la prend à côté.
                            out = (hole.xy - centre.xy).normalized()
                            if out.x < 0.75:
                                why["anse"] = why.get("anse", 0) + 1
                                continue
                            score = reach + abs(nx - 0.04) * 0.5 + abs(nf - 0.42) * 0.8
                            best.append((score, nx, nf, nrot, mx, mz, mrot, reach, tuple(round(v, 2) for v in out)))
    best.sort()
    for b in best[:12]:
        print("SEARCH", [round(v, 3) if isinstance(v, float) else v for v in b])
    print("SEARCH total", len(best), why)


if __name__ == "__main__":
    main()
