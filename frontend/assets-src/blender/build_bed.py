# Bed along the left wall around (-3.35, 1.3), head toward the front wall next to
# the bedside table (-3.6, 2.75). bed_lie anchor: mattress top y = 0.42.
import math, random
import bmesh, bpy
from mathutils import Vector, Matrix
from roomlib import *

BX, BZ = -3.35, 1.3
MATTRESS_TOP = 0.42


def pillow_data(w, d, t, nu=22, nv=16, pinch=0.07, seed=0, wrinkle=0.004):
    """Stuffed pillow: two puffy faces meeting on a thin seam, pinched sides."""
    rnd = random.Random(seed)
    ph = [rnd.uniform(0, 6.28) for _ in range(4)]

    def f(u, v):
        return max(0.0, (1 - abs(u) ** 2.6)) ** 0.55 * max(0.0, (1 - abs(v) ** 2.6)) ** 0.55

    verts, faces = [], []
    idx = {}
    for side in (1, -1):
        for j in range(nv + 1):
            for i in range(nu + 1):
                u = -1 + 2 * i / nu
                v = -1 + 2 * j / nv
                boundary = i in (0, nu) or j in (0, nv)
                key = (i, j) if boundary else (i, j, side)
                if key in idx:
                    continue
                x = u * w / 2 * (1 - pinch * (1 - v * v))
                y = v * d / 2 * (1 - pinch * (1 - u * u))
                z = side * t / 2 * f(u, v)
                z += wrinkle * f(u, v) * (math.sin(u * 7 + ph[0]) * math.sin(v * 5 + ph[1]) +
                                          0.5 * math.sin(u * 13 + v * 9 + ph[2]))
                idx[key] = len(verts)
                verts.append((x, y, z))
    W = nu + 1

    def vid(i, j, side):
        b = i in (0, nu) or j in (0, nv)
        return idx[(i, j) if b else (i, j, side)]

    for side in (1, -1):
        for j in range(nv):
            for i in range(nu):
                q = [vid(i, j, side), vid(i + 1, j, side), vid(i + 1, j + 1, side), vid(i, j + 1, side)]
                faces.append(q if side == 1 else list(reversed(q)))
    return verts, faces


def pillow(name, w, d, t, X, Y, Z, m, rx=0.0, ry=0.0, rz=0.0, seed=0, uv_tile=0.3):
    v, f = pillow_data(w, d, t, seed=seed)
    o = mesh_obj(name, v, f, m, smooth=True)
    planar_uv(o, 0, 1, uv_tile, uv_tile)
    place(o, X, Y, Z, rx=rx, ry=ry, rz=rz)
    return o


def plushie(M, X, Y, Z, ry):
    """A small cream bunny sitting on the bed."""
    pl = M["plush"]
    pink = M["plush_pink"]
    p = []
    p.append(sphere("Plush_Body", 0.085, 0.095, 0.075, 0, 0.09, 0, pl, 18, 12))
    p.append(sphere("Plush_Head", 0.078, 0.07, 0.07, 0, 0.215, 0.005, pl, 18, 12))
    for s in (-1, 1):
        e = sphere("Plush_Ear", 0.022, 0.08, 0.013, s * 0.034, 0.315, -0.005, pl, 12, 8)
        place(e, s * 0.034 + s * 0.01, 0.31, -0.01, rz=-s * 0.28, rx=-0.15 if s > 0 else 0.25)
        p.append(e)
        ie = sphere("Plush_InnerEar", 0.012, 0.055, 0.004, 0, 0, 0, pink, 10, 6)
        place(ie, s * 0.034 + s * 0.012, 0.312, 0.002, rz=-s * 0.28, rx=-0.15 if s > 0 else 0.25)
        p.append(ie)
        a = sphere("Plush_Arm", 0.024, 0.05, 0.024, 0, 0, 0, pl, 10, 8)
        place(a, s * 0.072, 0.1, 0.035, rz=s * 0.5, rx=-0.4)
        p.append(a)
        ft = sphere("Plush_Foot", 0.036, 0.024, 0.05, s * 0.045, 0.02, 0.055, pl, 12, 8)
        p.append(ft)
        p.append(sphere("Plush_Pad", 0.022, 0.006, 0.03, s * 0.045, 0.022, 0.1, pink, 10, 6))
        p.append(sphere("Plush_Eye", 0.009, 0.01, 0.006, s * 0.027, 0.222, 0.069, M["black"], 10, 6))
        p.append(sphere("Plush_Cheek", 0.014, 0.008, 0.004, s * 0.045, 0.2, 0.064, M["blush"], 10, 6))
    p.append(sphere("Plush_Nose", 0.008, 0.006, 0.005, 0, 0.205, 0.074, pink, 8, 6))
    p.append(sphere("Plush_Tail", 0.026, 0.026, 0.026, 0, 0.05, -0.075, pl, 10, 8))
    o = join(p, "Bed_Plushie")
    place(o, X, Y, Z, ry=ry)
    apply_transform(o, loc=True)
    return o


def build(M):
    for p in ("Bed", "Bedside", "BedLamp", "LightAnchor_Bed", "Plush", "Wall_Print", "Slipper"):
        remove_prefix(p)
    pr = []
    # frame: floating platform on a recessed plinth + padded headboard
    pr.append(box("Bed_Plinth", 1.08, 0.07, 2.0, BX, 0.035, BZ, M["wood_dark"], 0.004, 2))
    pr.append(box("Bed_Frame", 1.2, 0.17, 2.15, BX, 0.07 + 0.085, BZ, M["wood_mid"], 0.014, 3))
    pr.append(box("Bed_Head", 1.24, 0.8, 0.05, BX, 0.46, BZ + 1.075 + 0.025, M["wood_mid"], 0.018, 3))
    pr.append(box("Bed_HeadPad", 1.1, 0.4, 0.07, BX, 0.64, BZ + 1.075 - 0.035, M["cushion"], 0.032, 5))
    for s in (-1, 1):
        pr.append(box("Bed_HeadButton", 0.012, 0.012, 0.006, BX + s * 0.25, 0.67, BZ + 1.075 - 0.071, M["cushion"], 0.004, 1))
    join(pr, "Bed_Frame")
    mt = box("Bed_Mattress", 1.1, 0.18, 2.02, BX, 0.24 + 0.09, BZ + 0.01, M["mattress"], 0.05, 5)
    box_uv(mt, 0.3)

    # pillows (head end = +Z)
    pillow("Bed_Pillow", 0.72, 0.44, 0.17, BX + 0.03, MATTRESS_TOP + 0.075, BZ + 0.83, M["pillow"], rx=-0.22, ry=0.04, seed=1)
    pillow("Bed_Cushion", 0.4, 0.4, 0.13, BX + 0.24, MATTRESS_TOP + 0.2, BZ + 0.95, M["pillow_pink"], rx=-1.05, ry=-0.25, rz=0.08, seed=2)
    plushie(M, BX - 0.22, MATTRESS_TOP - 0.004, BZ + 0.62, ry=0.5)

    # ------------------------------------------------------------ bedside table
    tx, tz = -3.6, 2.75
    t = []
    for sx in (-1, 1):
        for sz in (-1, 1):
            lg = cyl("Bedside_Leg", 0.016, 0.115, tx + sx * 0.16, 0, tz + sz * 0.15, M["wood_dark"], 10, r2=0.012)
            t.append(lg)
    t.append(box("Bedside_Top", 0.44, 0.025, 0.42, tx, 0.48 - 0.0125, tz, M["wood_dark"], 0.008, 3))
    t.append(box("Bedside_Bottom", 0.42, 0.02, 0.38, tx, 0.115 + 0.01, tz, M["wood_dark"], 0.004, 2))
    for sz in (-1, 1):
        t.append(box("Bedside_Side", 0.42, 0.34, 0.02, tx, 0.115 + 0.17, tz + sz * 0.19, M["wood_dark"], 0.004, 2))
    t.append(box("Bedside_Back", 0.02, 0.34, 0.38, tx - 0.2, 0.115 + 0.17, tz, M["wood_dark"], 0.003, 1))
    t.append(box("Bedside_Shelf", 0.4, 0.018, 0.36, tx, 0.29, tz, M["wood_dark"], 0.003, 1))
    t.append(box("Bedside_Drawer", 0.018, 0.155, 0.37, tx + 0.205, 0.38, tz, M["wood_mid"], 0.004, 2))
    t.append(sphere("Bedside_Knob", 0.014, 0.014, 0.014, tx + 0.222, 0.38, tz, M["brass"], 12, 8))
    # two books in the open niche
    t.append(box("Bedside_Book1", 0.2, 0.03, 0.26, tx + 0.01, 0.135 + 0.015, tz - 0.03, M["book4"], 0.003, 1, ry=0.05))
    t.append(box("Bedside_Book2", 0.18, 0.025, 0.23, tx + 0.02, 0.165 + 0.0125, tz - 0.02, M["book9"], 0.003, 1, ry=-0.1))
    join(t, "Bedside_Table")
    # lamp: ceramic gourd base + linen drum shade (emissive)
    ly = 0.48
    lamp = []
    base_prof = [(0, 0), (0.05, 0), (0.07, 0.04), (0.075, 0.075), (0.06, 0.12), (0.03, 0.15), (0.018, 0.16),
                 (0.018, 0.17), (0, 0.17)]
    lamp.append(lathe("BedLamp_Base", base_prof, 28, tx - 0.06, ly, tz - 0.06, M["ceramic_pink"], sharp=70))
    lamp.append(cyl("BedLamp_Stem", 0.006, 0.2, tx - 0.06, ly + 0.17, tz - 0.06, M["brass"], 10))
    lamp.append(cyl("BedLamp_Socket", 0.016, 0.03, tx - 0.06, ly + 0.33, tz - 0.06, M["brass"], 12))
    join(lamp, "BedLamp")
    shade_prof = [(0.125, 0.0), (0.126, 0.004), (0.1, 0.15), (0.098, 0.154)]
    lathe("BedLamp_Shade", shade_prof, 36, tx - 0.06, ly + 0.27, tz - 0.06, M["bed_lamp_shade"],
          cap_bottom=False, cap_top=False, sharp=80)
    sphere("BedLamp_Bulb", 0.028, 0.034, 0.028, tx - 0.06, ly + 0.38, tz - 0.06, M["bed_bulb"], 12, 8)
    a = bpy.data.objects.new("LightAnchor_BedLamp", None)
    link(a)
    a.location = V(tx - 0.03, ly + 0.36, tz - 0.08)
    # alarm clock + glasses-free book stack on the table top
    ck = []
    ck.append(cyl("Bedside_Clock", 0.042, 0.035, tx + 0.13, ly + 0.042, tz + 0.1, M["plastic_white"], 24, rz=math.pi / 2, bev=0.01))
    ck.append(cyl("Bedside_ClockFace", 0.034, 0.002, tx + 0.13 + 0.0, ly + 0.042, tz + 0.1, M["paper"], 24, rz=-math.pi / 2))
    for k, (ang, ln) in enumerate(((0.6, 0.022), (2.2, 0.03))):
        hand = box("Bedside_ClockHand", 0.002, ln, 0.003, tx + 0.132, ly + 0.042 + ln / 2 * math.cos(ang),
                   tz + 0.1 + ln / 2 * math.sin(ang), M["black"], 0, rx=ang)
        ck.append(hand)
    for s in (-1, 1):
        ck.append(sphere("Bedside_ClockFoot", 0.008, 0.006, 0.008, tx + 0.13 - 0.01, ly + 0.004, tz + 0.1 + s * 0.025, M["plastic_white"], 8, 6))
    join(ck, "Bedside_Clock")

    # ------------------------------------------------------------ prints above the bed
    def framed(name, w, h, X, Y, Z, art, frame_m):
        parts = []
        fw, fd = 0.02, 0.022
        wall = -4.0
        for (bw, bh, ox, oy) in ((w + 2 * fw, fw, 0, h / 2 + fw / 2), (w + 2 * fw, fw, 0, -h / 2 - fw / 2),
                                 (fw, h, -w / 2 - fw / 2, 0), (fw, h, w / 2 + fw / 2, 0)):
            parts.append(box(name + "_F", fd, bh, bw, wall + fd / 2, Y + oy, Z + ox, frame_m, 0.004, 2))
        art_o = mesh_obj(name + "_Art", [V(wall + 0.006, Y - h / 2, Z + w / 2), V(wall + 0.006, Y - h / 2, Z - w / 2),
                                         V(wall + 0.006, Y + h / 2, Z - w / 2), V(wall + 0.006, Y + h / 2, Z + w / 2)],
                         [(0, 1, 2, 3)], art)
        if art_o.data.polygons[0].normal.x < 0:
            art_o.data.flip_normals()
        uvl = art_o.data.uv_layers.new(name="UVMap")
        for li, loop in enumerate(art_o.data.loops):
            uvl.data[li].uv = [(0, 0), (1, 0), (1, 1), (0, 1)][loop.vertex_index]
        parts.append(art_o)
        join(parts, name)

    framed("Wall_PrintCat", 0.3, 0.37, -4.0, 1.42, 0.85, M["print_cat"], M["frame_white"])
    framed("Wall_PrintFlower", 0.26, 0.32, -4.0, 1.52, 1.45, M["print_flower"], M["frame_white"])
    # wait, the art quad's UV orientation depends on the face winding; fixed below in check

    # ------------------------------------------------------------ slippers
    sl = []
    for k, (x, z, yaw) in enumerate(((-2.58, 2.62, 0.25), (-2.4, 2.78, -0.1))):
        s = []
        s.append(box("Slipper_Sole", 0.1, 0.022, 0.26, 0, 0.011, 0, M["plastic_white"], 0.009, 3))
        s.append(box("Slipper_Bed", 0.094, 0.016, 0.25, 0, 0.027, 0, M["slipper"], 0.008, 3))
        up = sphere("Slipper_Upper", 0.054, 0.06, 0.085, 0, 0.018, 0.055, M["slipper"], 18, 12)
        s.append(up)
        o = join(s, f"Slipper{k}")
        place(o, x, 0, z, ry=yaw)
        apply_transform(o, loc=True)
        sl.append(o)
    join(sl, "Bed_Slippers")
    return True
