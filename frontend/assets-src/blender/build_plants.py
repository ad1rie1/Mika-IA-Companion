# Plants with real leaves: fiddle-leaf fig (back-right corner), snake plant (near
# the bedside table), pothos trailing off the bookcase, sill succulents.
import math, random
from mathutils import Vector, Matrix
from roomlib import *


def shape_w(shape, t):
    if shape == "fig":
        return max(0.0, math.sin(math.pi * t ** 0.85)) ** 0.6 * (0.6 + 0.55 * t) / 1.02
    if shape == "heart":
        return max(0.0, math.sin(math.pi * t)) ** 0.65 * (1.3 - t) / 0.98
    if shape == "blade":
        return max(0.0, 1 - t ** 2.2) ** 0.55
    return math.sin(math.pi * t)


def leaf_data(length, width, shape, droop, fold, nu=8, nv=2, wave=0.0, seed=0):
    rnd = random.Random(seed)
    ph = rnd.uniform(0, 6.28)
    verts, faces = [], []
    for i in range(nu + 1):
        t = i / nu
        w = width / 2 * shape_w(shape, t)
        if shape == "heart" and i == 0:
            w = width * 0.18
        for j in range(-nv, nv + 1):
            s = j / nv
            x = s * w
            z = fold * abs(s) * w - droop * t * t * length + wave * math.sin(t * 9 + ph) * abs(s) * w
            y = t * length * (1 - 0.25 * droop * t)
            verts.append((x, y, z))
    W = 2 * nv + 1
    for i in range(nu):
        for j in range(2 * nv):
            a = i * W + j
            faces.append((a, a + 1, a + 1 + W, a + W))
    return verts, faces


def frame_for(D, roll=0.0):
    D = Vector(D).normalized()
    up = Vector((0, 0, 1))
    X = D.cross(up)
    if X.length < 1e-4:
        X = Vector((1, 0, 0))
    X.normalize()
    Z = X.cross(D).normalized()
    R = Matrix((X, D, Z)).transposed()
    return R @ Matrix.Rotation(roll, 3, "Y")


def add_leaf(acc, base_b, D_b, roll, length, width, shape, droop, fold, mat_index, seed, nu=8, wave=0.0):
    v, f = leaf_data(length, width, shape, droop, fold, nu=nu, wave=wave, seed=seed)
    R = frame_for(D_b, roll)
    off = len(acc["v"])
    for p in v:
        acc["v"].append(tuple(Vector(base_b) + R @ Vector(p)))
    for q in f:
        acc["f"].append(tuple(i + off for i in q))
        acc["m"].append(mat_index)


def finish(acc, name, mats):
    o = mesh_obj(name, acc["v"], acc["f"], list(mats), smooth=True)
    for poly, mi in zip(o.data.polygons, acc["m"]):
        poly.material_index = mi
    return o


def pot(name, X, Z, r, h, m, M, rim=True):
    prof = [(0, 0), (r * 0.78, 0), (r * 0.82, 0.01), (r, h * 0.9)]
    if rim:
        prof += [(r * 1.06, h * 0.92), (r * 1.06, h), (r * 0.94, h)]
    else:
        prof += [(r * 0.93, h)]
    prof += [(r * 0.9, h * 0.6), (0, h * 0.6)]
    o = lathe(name, prof, 28, X, 0, Z, m, sharp=55)
    s = cyl(name + "Soil", r * 0.92, 0.004, X, h * 0.86, Z, M["soil"], 24)
    return [o, s]


def build(M):
    for p in ("Plant_",):
        remove_prefix(p)
    rnd = random.Random(31)
    # ------------------------------------------------------------ fiddle-leaf fig
    fx, fz = 3.42, -3.95
    parts = pot("Plant_FigPot", fx, fz, 0.17, 0.36, M["ceramic_white"], M)
    parts.append(cyl("Plant_FigFoot", 0.12, 0.02, fx, 0, fz, M["wood_dark"], 20, bev=0.005))
    trunk_pts = []
    for k in range(9):
        t = k / 8
        trunk_pts.append(V(fx + 0.04 * math.sin(t * 2.4), 0.3 + 1.15 * t, fz + 0.03 * math.sin(t * 3.1 + 1)))
    parts.append(tube("Plant_FigTrunk", trunk_pts, 0.016, M["trunk"], 8,
                      radii=[0.018 - 0.01 * (k / 8) for k in range(9)]))
    acc = {"v": [], "f": [], "m": []}
    stems = []
    n = 26
    for k in range(n):
        t = k / (n - 1)
        y = 0.72 + 0.72 * t
        idx = min(8, int((y - 0.3) / 1.15 * 8))
        tp = Vector(trunk_pts[idx]) + (Vector(trunk_pts[min(8, idx + 1)]) - Vector(trunk_pts[idx])) * 0.5
        phi = k * 2.399 + rnd.uniform(-0.2, 0.2)
        elev = math.radians(18 + 42 * t + rnd.uniform(-8, 8))
        D3 = (math.cos(phi) * math.cos(elev), math.sin(elev), math.sin(phi) * math.cos(elev))
        D = Vector(V(*D3))
        # keep leaves out of the walls (back wall z=-4.5, right wall x=4)
        base = tp + D * 0.05
        stems.append(tube("Plant_FigStem", [tp, base], 0.004, M["stem"], 5))
        L = rnd.uniform(0.24, 0.32) * (0.85 + 0.25 * (1 - t))
        add_leaf(acc, base, D, rnd.uniform(-0.5, 0.5), L, L * rnd.uniform(0.58, 0.68), "fig",
                 rnd.uniform(0.15, 0.32), 0.18, k % 3 == 0, k, nu=9, wave=0.06)
    leaves = finish(acc, "Plant_FigLeaves", (M["leaf"], M["leaf_light"]))
    join(parts + stems, "Plant_Fig")

    # ------------------------------------------------------------ snake plant
    sx, sz = -3.56, 3.2
    parts = pot("Plant_SnakePot", sx, sz, 0.12, 0.24, M["terracotta"], M)
    join(parts, "Plant_SnakePotJ")
    acc = {"v": [], "f": [], "m": []}
    for k in range(10):
        phi = k * 2.399
        tilt = math.radians(rnd.uniform(3, 16))
        D3 = (math.cos(phi) * math.sin(tilt), math.cos(tilt), math.sin(phi) * math.sin(tilt))
        r0 = rnd.uniform(0.0, 0.05)
        base = V(sx + r0 * math.cos(phi), 0.2, sz + r0 * math.sin(phi))
        L = rnd.uniform(0.42, 0.78)
        add_leaf(acc, base, V(*D3), phi + rnd.uniform(-0.6, 0.6), L, rnd.uniform(0.06, 0.085), "blade",
                 rnd.uniform(-0.02, 0.08), 0.35, 0, 100 + k, nu=10, wave=0.05)
    finish(acc, "Plant_SnakeLeaves", (M["leaf_snake"],))

    # ------------------------------------------------------------ pothos trailing off the bookcase
    px, py, pz = 3.82, 2.0, -2.5
    parts = pot("Plant_PothosPot", px, pz, 0.075, 0.11, M["ceramic_sage"], M)
    for o in parts:
        o.location.z += py
    acc = {"v": [], "f": [], "m": []}
    vines = []
    for k in range(6):
        zoff = -0.16 + 0.065 * k + rnd.uniform(-0.02, 0.02)
        drop = rnd.uniform(0.25, 0.65)
        pts3 = [(px - 0.03, py + 0.1, pz + zoff * 0.3), (px - 0.12, py + 0.06, pz + zoff * 0.7),
                (3.635, py + 0.02, pz + zoff), (3.6, py - 0.04, pz + zoff + 0.01)]
        steps = 6
        for s in range(1, steps + 1):
            yy = py - 0.04 - drop * s / steps
            pts3.append((3.6 - 0.01 * math.sin(s * 1.3 + k), yy, pz + zoff + 0.02 * math.sin(s * 0.9 + k * 2)))
        pts = [V(*p) for p in pts3]
        vines.append(tube("Plant_PothosVine", pts, 0.0025, M["stem"], 4, cap=False))
        # leaves along the vine
        for s in range(2, len(pts) - 1):
            p = Vector(pts[s])
            side = 1 if s % 2 else -1
            D3 = (-0.75, -0.25 if s > 3 else 0.35, side * 0.6)
            L = rnd.uniform(0.045, 0.07) * (1.0 if s < len(pts) - 2 else 0.7)
            add_leaf(acc, p, V(*D3), rnd.uniform(-0.6, 0.6), L, L * 0.85, "heart", 0.1, 0.25,
                     s % 2, 200 + k * 20 + s, nu=6)
    for k in range(12):
        phi = k * 2.399
        D3 = (math.cos(phi) * 0.7, 0.6, math.sin(phi) * 0.7)
        base = V(px + 0.03 * math.cos(phi), py + 0.1, pz + 0.03 * math.sin(phi))
        L = rnd.uniform(0.05, 0.075)
        add_leaf(acc, base, V(*D3), rnd.uniform(-0.5, 0.5), L, L * 0.85, "heart", 0.15, 0.25, k % 2, 400 + k, nu=6)
    finish(acc, "Plant_PothosLeaves", (M["leaf"], M["leaf_light"]))
    join(parts + vines, "Plant_Pothos")

    # ------------------------------------------------------------ window sill succulents
    sill_y = 1.204
    sp = []
    sp.append(lathe("Plant_SillPot1", [(0, 0), (0.035, 0), (0.042, 0.07), (0.038, 0.07), (0, 0.062)], 20,
                    -3.98, sill_y, -1.72, M["terracotta"], sharp=60))
    sp.append(sphere("Plant_SillCactus", 0.03, 0.07, 0.03, -3.98, sill_y + 0.12, -1.72, M["succulent"], 12, 8))
    sp.append(sphere("Plant_SillCactusArm", 0.015, 0.03, 0.015, -3.98, sill_y + 0.13, -1.69, M["succulent"], 10, 6))
    sp.append(lathe("Plant_SillBowl", [(0, 0), (0.04, 0), (0.06, 0.045), (0.056, 0.048), (0, 0.04)], 22,
                    -3.97, sill_y, -0.75, M["ceramic_white"], sharp=60))
    acc = {"v": [], "f": [], "m": []}
    for k in range(11):
        phi = k * 2.399
        D3 = (math.cos(phi) * 0.75, 0.66, math.sin(phi) * 0.75)
        base = V(-3.97 + 0.01 * math.cos(phi), sill_y + 0.045, -0.75 + 0.01 * math.sin(phi))
        add_leaf(acc, base, V(*D3), 0, 0.04, 0.025, "blade", 0.05, 0.5, 0, 500 + k, nu=4)
    finish(acc, "Plant_SillSucculent", (M["succulent"],))
    join(sp, "Plant_Sill")
    return True
