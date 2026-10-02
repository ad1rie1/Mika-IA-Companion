# Bookcase on the right wall, trinket shelf + posters on the back wall, dresser.
import math, random
import bpy
from mathutils import Vector
from roomlib import *
from materials import BOOK_COLORS


def art_quad(name, w, h, center3, right3, up3, normal_b, m, uv_rect=(0, 0, 1, 1)):
    """Textured quad: centre + unit right/up vectors in three space."""
    cx, cy, cz = center3
    r = Vector(right3) * (w / 2)
    u = Vector(up3) * (h / 2)
    c = Vector((cx, cy, cz))
    pts = [c - r - u, c + r - u, c + r + u, c - r + u]
    o = mesh_obj(name, [V(*p) for p in pts], [(0, 1, 2, 3)], m)
    u0, v0, u1, v1 = uv_rect
    uvs = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
    if o.data.polygons[0].normal.dot(Vector(normal_b)) < 0:
        o.data.flip_normals()
    uvl = o.data.uv_layers.new(name="UVMap")
    for li, loop in enumerate(o.data.loops):
        uvl.data[li].uv = uvs[loop.vertex_index]
    return o


def books_row(M, rnd, y_base, z0, z1, x_front, max_h, name="Book", lean_end=True):
    """Upright books along Z (spines facing -X). Returns objects + end cursor."""
    out = []
    z = z0
    while True:
        t = rnd.uniform(0.018, 0.048)
        if z + t > z1:
            break
        h = rnd.uniform(0.17, min(0.3, max_h))
        d = rnd.uniform(0.15, 0.23)
        ci = rnd.randrange(len(BOOK_COLORS))
        x = x_front + d / 2 + rnd.uniform(0, 0.02)
        b = box(name, d, h, t, x, y_base + h / 2, z + t / 2, M[f"book{ci}"], 0.0025, 1, ry=rnd.uniform(-0.03, 0.03))
        out.append(b)
        # a lighter band on some spines (title label)
        if rnd.random() < 0.45:
            out.append(box(name + "Band", 0.004, rnd.uniform(0.02, 0.04), t * 0.82, x - d / 2 - 0.001,
                           y_base + h * rnd.uniform(0.55, 0.8), z + t / 2,
                           M["book5"] if ci not in (5,) else M["book1"], 0.0))
        z += t + rnd.uniform(0.0, 0.004)
    if lean_end and z1 - z > 0.06:
        h = rnd.uniform(0.2, min(0.28, max_h))
        t = rnd.uniform(0.022, 0.035)
        d = rnd.uniform(0.16, 0.21)
        a = rnd.uniform(0.25, 0.4)
        ci = rnd.randrange(len(BOOK_COLORS))
        zc = z + t / 2 + math.sin(a) * h / 2 + 0.004
        yc = y_base + math.cos(a) * h / 2 + math.sin(a) * t / 2
        out.append(box(name, d, h, t, x_front + d / 2, yc, zc, M[f"book{ci}"], 0.0025, 1, rx=a))
    return out


def lying_stack(M, rnd, y_base, x, z, n, name="BookStack"):
    out = []
    y = y_base
    for k in range(n):
        h = rnd.uniform(0.022, 0.045)
        w = rnd.uniform(0.17, 0.23)
        d = rnd.uniform(0.22, 0.3)
        ci = rnd.randrange(len(BOOK_COLORS))
        out.append(box(name, w, h, d, x + rnd.uniform(-0.01, 0.01), y + h / 2, z, M[f"book{ci}"], 0.003, 1,
                       ry=rnd.uniform(-0.15, 0.15) + math.pi / 2))
        out.append(box(name + "Pages", w - 0.01, h - 0.006, d - 0.008, x, y + h / 2, z, M["book_pages"], 0.0,
                       ry=out[-1].rotation_euler.z))
        y += h
    return out, y


def star_data(r_out, r_in, thick, points=5):
    verts, faces = [], []
    n = points * 2
    for side in (-1, 1):
        verts.append((0, side * thick / 2 * 1.6, 0))       # centre bulge (blender y = depth)
        for i in range(n):
            a = math.pi / 2 + math.pi * i / points
            r = r_out if i % 2 == 0 else r_in
            verts.append((r * math.cos(a), side * thick / 2, r * math.sin(a)))
    for i in range(n):
        j = (i + 1) % n
        faces.append((0, 1 + i, 1 + j))
        faces.append((n + 1, n + 2 + j, n + 2 + i))
        faces.append((1 + i, n + 2 + i, n + 2 + j, 1 + j))
    return verts, faces


def build(M):
    for p in ("Bookshelf", "Trinket", "Poster", "Dresser", "MoonLamp", "Candle", "Mirror"):
        remove_prefix(p)
    rnd = random.Random(21)
    # ------------------------------------------------------------ bookcase
    X0, X1 = 3.62, 3.995
    Z0, Z1 = -2.95, -1.45
    HT = 2.0
    dx = X1 - X0
    xc = (X0 + X1) / 2
    bc = []
    for zz in (Z0 + 0.011, Z1 - 0.011):
        bc.append(box("Bookshelf_Side", dx, HT, 0.022, xc, HT / 2, zz, M["wood_dark"], 0.004, 2))
    bc.append(box("Bookshelf_Top", dx + 0.01, 0.025, Z1 - Z0 + 0.01, xc - 0.005, HT - 0.0125, (Z0 + Z1) / 2, M["wood_dark"], 0.006, 2))
    bc.append(box("Bookshelf_Back", 0.008, HT, Z1 - Z0, X1 + 0.001, HT / 2, (Z0 + Z1) / 2, M["wood_dark"], 0.0))
    bc.append(box("Bookshelf_Kick", 0.02, 0.06, Z1 - Z0 - 0.044, X0 + 0.02, 0.03, (Z0 + Z1) / 2, M["wood_dark"], 0.003, 1))
    shelf_ys = [0.06, 0.45, 0.84, 1.23, 1.61]
    for y in shelf_ys:
        bc.append(box("Bookshelf_Board", dx - 0.012, 0.022, Z1 - Z0 - 0.044, xc - 0.004, y + 0.011, (Z0 + Z1) / 2,
                      M["wood_dark"], 0.004, 2))
    join(bc, "Bookshelf")
    tops = [y + 0.022 for y in shelf_ys]
    xf = X0 + 0.015
    items = []
    gap = 0.36
    # L0: two baskets + magazines
    for zc in (-2.72, -2.27):
        bv, bf = lathe_data([(0, 0), (0.15, 0), (0.16, 0.2), (0.155, 0.205), (0.145, 0.205), (0.14, 0.01), (0, 0.01)], 4,
                            a0=math.pi / 4)
        bo = mesh_obj("Bookshelf_Basket", bv, bf, M["basket"], smooth=False)
        bo.scale = (0.95, 1.12, 1.0)
        place(bo, xc + 0.01, tops[0], zc)
        bo.scale = (0.95, 1.12, 1.0)
        box_uv(bo, 0.25)
        items.append(bo)
    st, _ = lying_stack(M, rnd, tops[0], xc + 0.02, -1.75, 4, "Bookshelf_Mag")
    items += st
    # L1: books + small vase
    items += books_row(M, rnd, tops[1], Z0 + 0.03, -1.95, xf, gap - 0.04, "Bookshelf_Book")
    items.append(lathe("Bookshelf_Vase", [(0, 0), (0.04, 0), (0.055, 0.06), (0.045, 0.12), (0.025, 0.16), (0.028, 0.18),
                                          (0.022, 0.18), (0.0, 0.17)], 24, xc, tops[1], -1.68, M["ceramic_sage"], sharp=60))
    # L2: lying stack with a figurine on top + books
    st, ytop = lying_stack(M, rnd, tops[2], xc + 0.01, -2.8, 3, "Bookshelf_Stack")
    items += st
    fig = []
    fig.append(sphere("Bookshelf_FigBody", 0.035, 0.04, 0.03, 0, 0.04, 0, M["figurine"], 14, 10))
    fig.append(sphere("Bookshelf_FigHead", 0.032, 0.028, 0.028, 0, 0.1, 0.0, M["figurine"], 14, 10))
    for s in (-1, 1):
        e = sphere("Bookshelf_FigEar", 0.01, 0.018, 0.008, 0, 0, 0, M["figurine"], 8, 6)
        place(e, s * 0.02, 0.128, 0, rz=-s * 0.35)
        fig.append(e)
        fig.append(sphere("Bookshelf_FigEye", 0.004, 0.005, 0.003, s * 0.011, 0.105, 0.026, M["black"], 6, 4))
    f = join(fig, "Bookshelf_Fig")
    place(f, xc - 0.01, ytop, -2.8, ry=-1.2)
    apply_transform(f, loc=True)
    items.append(f)
    items += books_row(M, rnd, tops[2], -2.6, Z1 - 0.03, xf, gap - 0.04, "Bookshelf_Book")
    # L3: moon lamp + books
    items += books_row(M, rnd, tops[3], -2.55, Z1 - 0.03, xf, gap - 0.04, "Bookshelf_Book")
    items.append(cyl("MoonLamp_Stand", 0.045, 0.018, xc, tops[3], -2.78, M["wood_mid"], 20, bev=0.005))
    moon = sphere("MoonLamp", 0.075, 0.075, 0.075, xc, tops[3] + 0.018 + 0.074, -2.78, M["moon_lamp"], 24, 16)
    # crater dimples
    me = moon.data
    crng = random.Random(5)
    cr = [Vector((crng.uniform(-1, 1), crng.uniform(-1, 1), crng.uniform(-1, 1))).normalized() for _ in range(9)]
    for v in me.vertices:
        n = v.co.normalized()
        for c in cr:
            dd = (n - c).length
            if dd < 0.35:
                v.co -= n * 0.006 * (1 - dd / 0.35)
    # L4: books + photo frame + cactus
    items += books_row(M, rnd, tops[4], Z0 + 0.03, -2.25, xf, gap - 0.06, "Bookshelf_Book")
    fr = box("Bookshelf_Frame", 0.016, 0.17, 0.13, xc + 0.05, tops[4] + 0.083, -1.98, M["frame_white"], 0.004, 2, rz=-0.12)
    items.append(fr)
    items.append(art_quad("Bookshelf_Photo", 0.1, 0.13, (xc + 0.05 - 0.0095 - 0.01, tops[4] + 0.083, -1.98),
                          (0, 0, 1), (0.12, 0.993, 0), (-1, 0, 0), M["photos"], (0.25 + 16 / 1024, 0.25, 0.5 - 16 / 1024, 1.0)))
    items.append(lathe("Bookshelf_CactusPot", [(0, 0), (0.035, 0), (0.042, 0.065), (0.038, 0.065), (0, 0.06)], 20,
                       xc, tops[4], -1.66, M["terracotta"], sharp=60))
    items.append(sphere("Bookshelf_Cactus", 0.028, 0.06, 0.028, xc, tops[4] + 0.11, -1.66, M["succulent"], 12, 8))
    items.append(sphere("Bookshelf_CactusArm", 0.014, 0.028, 0.014, xc, tops[4] + 0.12, -1.63, M["succulent"], 10, 6))
    # top: storage box
    items.append(box("Bookshelf_Box", 0.3, 0.16, 0.34, xc - 0.01, HT + 0.08, -1.75, M["paper_pink"], 0.006, 2))
    items.append(box("Bookshelf_BoxLid", 0.31, 0.03, 0.35, xc - 0.01, HT + 0.16, -1.75, M["paper_pink"], 0.006, 2))
    join(items, "Bookshelf_Items")

    # ------------------------------------------------------------ trinket shelf (back wall)
    wz = -4.5
    tr = []
    ty = 1.75
    tr.append(box("Trinket_Shelf", 1.0, 0.03, 0.22, 1.9, ty - 0.015, wz + 0.11, M["wood_mid"], 0.006, 3))
    for bx in (1.52, 2.28):
        tr.append(box("Trinket_BracketV", 0.02, 0.13, 0.012, bx, ty - 0.03 - 0.065, wz + 0.006, M["metal_dark"], 0.003, 1))
        tr.append(box("Trinket_BracketH", 0.02, 0.012, 0.17, bx, ty - 0.036, wz + 0.09, M["metal_dark"], 0.003, 1))
    tr.append(cyl("Trinket_StarBase", 0.035, 0.016, 1.55, ty, wz + 0.11, M["wood_dark"], 20, bev=0.004))
    # cactus pot
    tr.append(lathe("Trinket_Pot", [(0, 0), (0.035, 0), (0.042, 0.06), (0.046, 0.065), (0.04, 0.065), (0, 0.06)], 20,
                    1.8, ty, wz + 0.11, M["terracotta"], sharp=60))
    tr.append(sphere("Trinket_Cactus", 0.026, 0.055, 0.026, 1.8, ty + 0.1, wz + 0.11, M["succulent"], 12, 8))
    tr.append(sphere("Trinket_CactusFlower", 0.012, 0.008, 0.012, 1.8, ty + 0.155, wz + 0.11, M["paper_pink"], 8, 6))
    # sitting cat figurine
    cat = []
    cat.append(sphere("Trinket_CatBody", 0.035, 0.045, 0.03, 0, 0.045, 0, M["figurine"], 14, 10))
    cat.append(sphere("Trinket_CatHead", 0.03, 0.027, 0.027, 0, 0.11, 0.008, M["figurine"], 14, 10))
    for s in (-1, 1):
        e = lathe("Trinket_CatEar", [(0, 0), (0.011, 0), (0, 0.022)], 8, 0, 0, 0, M["figurine"])
        place(e, s * 0.016, 0.128, 0.006, rz=-s * 0.3)
        cat.append(e)
        cat.append(sphere("Trinket_CatEye", 0.0045, 0.005, 0.003, s * 0.011, 0.113, 0.033, M["black"], 6, 4))
    cat.append(tube("Trinket_CatTail", [V(0.02, 0.01, -0.02), V(0.05, 0.015, 0.0), V(0.055, 0.03, 0.03)], 0.007, M["figurine"], 8))
    c = join(cat, "Trinket_Cat")
    place(c, 2.04, ty, wz + 0.1, ry=-0.3)
    apply_transform(c, loc=True)
    tr.append(c)
    # leaning photo frame
    pf = box("Trinket_Frame", 0.15, 0.19, 0.014, 2.3, ty + 0.095, wz + 0.05, M["frame_white"], 0.004, 2, rx=-0.12)
    tr.append(pf)
    tr.append(art_quad("Trinket_Photo", 0.11, 0.15, (2.3, ty + 0.095 + 0.0, wz + 0.05 + 0.008 + 0.0115),
                       (1, 0, 0), (0, math.cos(0.12), -math.sin(0.12)), (0, -1, 0), M["photos"],
                       (0.75 + 16 / 1024, 0.25, 1.0 - 16 / 1024, 1.0)))
    # candle jar
    tr.append(lathe("Candle_Jar", [(0, 0), (0.035, 0), (0.036, 0.075), (0.032, 0.075), (0.031, 0.006), (0, 0.006)], 22,
                    2.15, ty, wz + 0.14, M["glass_jar"], sharp=60))
    tr.append(cyl("Candle_Wax", 0.031, 0.045, 2.15, ty + 0.006, wz + 0.14, M["wax"], 22))
    join(tr, "Trinket_Shelf")
    # emissive star (stands on its base, faces the room)
    sv, sf = star_data(0.07, 0.03, 0.022)
    st = mesh_obj("Trinket_Star", sv, sf, M["star_glow"], smooth=True, sharp_angle=40)
    place(st, 1.55, ty + 0.016 + 0.068, wz + 0.11)
    fl = lathe("Candle_Flame", [(0, 0), (0.006, 0.006), (0.005, 0.016), (0.0, 0.028)], 10, 2.15, ty + 0.054, wz + 0.14,
               M["candle_flame"])

    # ------------------------------------------------------------ posters
    def framed_on(name, w, h, center, right, up, normal_b, art, frame_m, depth=0.022, fw=0.022):
        parts = []
        c = Vector(center)
        R, U = Vector(right), Vector(up)
        N = R.cross(U)  # three-space outward normal
        for (bw, bh, ox, oy) in ((w + 2 * fw, fw, 0, h / 2 + fw / 2), (w + 2 * fw, fw, 0, -h / 2 - fw / 2),
                                 (fw, h, -w / 2 - fw / 2, 0), (fw, h, w / 2 + fw / 2, 0)):
            p = c + R * ox + U * oy + N * (depth / 2)
            # box sized along three axes: pick extents depending on wall orientation
            if abs(R.x) > 0.5:
                b = box(name + "_F", bw, bh, depth, p.x, p.y, p.z, frame_m, 0.004, 2)
            else:
                b = box(name + "_F", depth, bh, bw, p.x, p.y, p.z, frame_m, 0.004, 2)
            parts.append(b)
        pc = c + N * 0.004
        parts.append(art_quad(name + "_Art", w, h, tuple(pc), tuple(R), tuple(U), normal_b, art))
        join(parts, name)

    framed_on("Poster_Moon", 0.62, 0.81, (0.6, 2.15, -4.5), (1, 0, 0), (0, 1, 0), (0, -1, 0), M["poster_moon"], M["frame_black"])
    # right wall, in the gap between the bookcase (z <= -1.45) and the dresser
    framed_on("Poster_Peaks", 0.58, 0.58, (4.0, 1.72, -0.7), (0, 0, 1), (0, 1, 0), (-1, 0, 0), M["poster_peaks"], M["frame_white"])
    # front wall, left of the door: city-pop sunset (landscape)
    framed_on("Poster_City", 0.8, 0.567, (-0.45, 1.72, 3.5), (-1, 0, 0), (0, 1, 0), (0, 1, 0), M["poster_city"], M["frame_black"])
    # round mirror above the dresser
    mc = (3.995, 1.48, 0.6)
    ring = [V(mc[0] - 0.02, mc[1] + 0.285 * math.sin(2 * math.pi * k / 48), mc[2] + 0.285 * math.cos(2 * math.pi * k / 48))
            for k in range(49)]
    mr = tube("Mirror_Frame", ring, 0.02, M["brass"], 10, cap=False)
    disc = cyl("Mirror", 0.28, 0.006, mc[0] - 0.012, mc[1], mc[2], M["mirror"], 48, rz=math.pi / 2)

    # ------------------------------------------------------------ dresser (right wall, under the peaks poster)
    DX0, DX1 = 3.56, 3.995
    DZ0, DZ1 = 0.05, 1.15
    DH = 0.78
    dc = (DX0 + DX1) / 2
    dz = (DZ0 + DZ1) / 2
    dr = []
    dr.append(box("Dresser_Body", DX1 - DX0, DH - 0.12, DZ1 - DZ0, dc, 0.1 + (DH - 0.12) / 2, dz, M["wood_desk"], 0.006, 2))
    dr.append(box("Dresser_Top", DX1 - DX0 + 0.015, 0.03, DZ1 - DZ0 + 0.03, dc - 0.007, DH - 0.035, dz, M["wood_desk"], 0.008, 3))
    for sx in (DX0 + 0.05, DX1 - 0.05):
        for sz in (DZ0 + 0.06, DZ1 - 0.06):
            dr.append(cyl("Dresser_Leg", 0.018, 0.1, sx, 0, sz, M["wood_dark"], 12, r2=0.014))
    rows = [(0.11, 0.33), (0.335, 0.52), (0.525, 0.715)]
    for (y0, y1) in rows:
        for (z0, z1) in ((DZ0 + 0.012, dz - 0.004), (dz + 0.004, DZ1 - 0.012)):
            dr.append(box("Dresser_Drawer", 0.018, y1 - y0 - 0.008, z1 - z0, DX0 - 0.009, (y0 + y1) / 2, (z0 + z1) / 2,
                          M["wood_desk"], 0.004, 2))
            dr.append(sphere("Dresser_Knob", 0.014, 0.014, 0.014, DX0 - 0.024, (y0 + y1) / 2, (z0 + z1) / 2, M["brass"], 12, 8))
    join(dr, "Dresser")
    di = []
    ty = DH - 0.02
    # bluetooth speaker
    di.append(box("Dresser_Speaker", 0.12, 0.17, 0.16, dc + 0.05, ty + 0.085, 0.26, M["speaker"], 0.03, 4))
    # jewelry box
    di.append(box("Dresser_JewelBox", 0.12, 0.06, 0.16, dc + 0.02, ty + 0.03, 0.55, M["paper_pink"], 0.008, 2, ry=0.2))
    di.append(box("Dresser_JewelLid", 0.125, 0.012, 0.165, dc + 0.02, ty + 0.066, 0.55, M["ceramic_pink"], 0.005, 2, ry=0.2))
    # perfume bottles
    di.append(lathe("Dresser_Perfume", [(0, 0), (0.028, 0), (0.03, 0.06), (0.012, 0.075), (0.01, 0.085), (0.0, 0.085)], 16,
                    dc - 0.05, ty, 0.72, M["glass_jar"], sharp=50))
    di.append(cyl("Dresser_PerfumeCap", 0.012, 0.025, dc - 0.05, ty + 0.085, 0.72, M["brass"], 12))
    # vase with dried stems
    di.append(lathe("Dresser_Vase", [(0, 0), (0.035, 0), (0.05, 0.08), (0.03, 0.17), (0.022, 0.2), (0.026, 0.215),
                                     (0.02, 0.215), (0, 0.2)], 22, dc + 0.02, ty, 0.95, M["ceramic_white"], sharp=60))
    vr = random.Random(9)
    for k in range(7):
        a = vr.uniform(-0.35, 0.35)
        b = vr.uniform(0, 6.28)
        top = Vector((dc + 0.02 + math.sin(a) * math.cos(b) * 0.3, ty + 0.2 + 0.32 * math.cos(a), 0.95 + math.sin(a) * math.sin(b) * 0.3))
        base = Vector((dc + 0.02, ty + 0.12, 0.95))
        mid = (base + top) / 2 + Vector((0, 0.02, 0))
        di.append(tube("Dresser_Stem", [V(*base), V(*mid), V(*top)], 0.0025, M["trunk"], 5))
        di.append(sphere("Dresser_Bud", 0.012, 0.03, 0.012, top.x, top.y, top.z, M["basket"], 8, 6))
    join(di, "Dresser_Items")
    return True
