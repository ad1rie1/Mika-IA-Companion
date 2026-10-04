# Rug under Mika and the lived-in floor/wall clutter.
import math, random
from mathutils import Vector
from roomlib import *
from build_bed import pillow_data, pillow
from build_shelves import lying_stack


def build(M):
    for p in ("Rug", "Floor_", "Laundry", "Hooks", "Tote", "Wardrobe", "Neon", "Clock"):
        remove_prefix(p)
    rnd = random.Random(41)
    # ------------------------------------------------------------ round rug (thick, rounded edge)
    prof = [(0, 0), (1.49, 0), (1.498, 0.003), (1.5, 0.008), (1.496, 0.013), (1.485, 0.016), (0, 0.016)]
    rug = lathe("Rug", prof, 120, 0, 0, -0.5, M["rug"], sharp=60)
    planar_uv(rug, 0, 1, 3.0, 3.0, -1.5, 0.5 - 1.5)

    # ------------------------------------------------------------ reading corner by the bookcase
    fl = []
    fl.append(pillow("Floor_Cushion", 0.62, 0.62, 0.15, 3.0, 0.062, -0.9, M["cushion"], ry=0.3, seed=7, uv_tile=0.35))
    st, _ = lying_stack(M, rnd, 0.0, 3.74, -0.2, 3, "Floor_Books")
    fl += st
    # an open book left on the cushion (no clutter in the walking corridors)
    ob = box("Floor_OpenBook", 0.3, 0.012, 0.21, 3.02, 0.152, -0.88, M["paper"], 0.003, 1, ry=-0.4)
    fl.append(ob)
    fl.append(box("Floor_OpenBookCover", 0.31, 0.004, 0.22, 3.02, 0.145, -0.88, M["book4"], 0.0, ry=-0.4))
    join(fl, "Floor_ReadingCorner")

    # ------------------------------------------------------------ laundry basket (front-right corner)
    lb = []
    bprof = [(0, 0), (0.17, 0), (0.2, 0.36), (0.212, 0.37), (0.212, 0.385), (0.198, 0.385), (0.185, 0.02), (0, 0.02)]
    bas = lathe("Laundry_Basket", bprof, 32, 3.55, 0, 3.08, M["basket"], sharp=60)
    box_uv(bas, 0.2)
    lb.append(bas)
    for k, (m, dx, dz, ry_) in enumerate(((M["hoodie"], -0.05, 0.02, 0.3), (M["cushion"], 0.06, -0.04, 1.2),
                                          (M["pillow"], 0.0, 0.07, 2.0))):
        c = pillow("Laundry_Cloth", 0.28, 0.2, 0.09, 3.55 + dx, 0.36 + 0.02 * k, 3.08 + dz, m,
                   rx=rnd.uniform(-0.3, 0.3), ry=ry_, rz=rnd.uniform(-0.3, 0.3), seed=60 + k, uv_tile=0.25)
        lb.append(c)
    join(lb, "Laundry")

    # ------------------------------------------------------------ hooks by the door + tote bag
    wz = 3.5
    hk = []
    hk.append(box("Hooks_Rail", 0.55, 0.07, 0.018, 0.75, 1.65, wz - 0.009, M["wood_mid"], 0.005, 2))
    for hx in (0.57, 0.75, 0.93):
        hk.append(cyl("Hooks_Peg", 0.011, 0.05, hx, 1.65, wz - 0.018, M["brass"], 12, rx=-math.pi / 2))
        hk.append(sphere("Hooks_PegEnd", 0.016, 0.016, 0.012, hx, 1.65, wz - 0.07, M["brass"], 12, 8))
    join(hk, "Hooks")
    tote = []
    body = pillow("Tote_Body", 0.34, 0.38, 0.06, 0, 0, 0, M["basket"], seed=70, uv_tile=0.25)
    place(body, 0.75, 1.23, wz - 0.06, rx=math.pi / 2 + 0.06)
    tote.append(body)
    for s in (-1, 1):
        pts = [V(0.75 + s * 0.1, 1.41, wz - 0.06), V(0.75 + s * 0.06, 1.55, wz - 0.065), V(0.75 + s * 0.012, 1.64, wz - 0.07),
               V(0.75, 1.665, wz - 0.055)]
        tote.append(tube("Tote_Strap", pts, 0.006, M["basket"], 6))
    join(tote, "Tote")
    # a scarf on the third peg
    pts = [V(0.93, 1.66, wz - 0.06)] + [V(0.93 + 0.02 * math.sin(k * 0.8), 1.62 - 0.08 * k, wz - 0.045 - 0.012 * math.sin(k * 0.6))
                                        for k in range(1, 9)]
    sc = tube("Tote_Scarf", pts, 0.02, M["chair_accent"], 10, radii=[0.018 + 0.006 * (k / 8) for k in range(9)])
    from mathutils import Matrix
    c = sum((v.co for v in sc.data.vertices), Vector()) / len(sc.data.vertices)
    sc.data.transform(Matrix.Translation(c) @ Matrix.Diagonal((1.0, 0.35, 1.0, 1.0)) @ Matrix.Translation(-c))
    # ------------------------------------------------------------ wardrobe (back-left corner)
    WX0, WX1 = -4.0, -3.42
    WZ0, WZ1 = -4.48, -3.28
    WH = 2.05
    wc, wzc = (WX0 + WX1) / 2, (WZ0 + WZ1) / 2
    wd = []
    wd.append(box("Wardrobe_Body", WX1 - WX0, WH - 0.06, WZ1 - WZ0, wc, 0.06 + (WH - 0.06) / 2, wzc, M["wood_mid"], 0.008, 3))
    wd.append(box("Wardrobe_Kick", WX1 - WX0 - 0.04, 0.06, WZ1 - WZ0 - 0.04, wc - 0.01, 0.03, wzc, M["wood_dark"], 0.003, 1))
    wd.append(box("Wardrobe_Crown", WX1 - WX0 + 0.02, 0.035, WZ1 - WZ0 + 0.03, wc + 0.005, WH + 0.0175, wzc, M["wood_mid"], 0.008, 3))
    for k, (z0, z1) in enumerate(((WZ0 + 0.01, wzc - 0.003), (wzc + 0.003, WZ1 - 0.01))):
        zc_ = (z0 + z1) / 2
        wd.append(box("Wardrobe_Door", 0.02, WH - 0.12, z1 - z0, WX1 + 0.01, 0.06 + (WH - 0.06) / 2, zc_, M["wood_mid"], 0.005, 2))
        wd.append(box("Wardrobe_Inset", 0.006, WH - 0.5, z1 - z0 - 0.14, WX1 + 0.022, 0.06 + (WH - 0.06) / 2, zc_, M["wood_desk"], 0.004, 2))
        hz = wzc - 0.035 if k == 0 else wzc + 0.035
        wd.append(box("Wardrobe_Handle", 0.012, 0.22, 0.012, WX1 + 0.05, 1.05, hz, M["brass"], 0.004, 2))
        for dy in (-0.09, 0.09):
            wd.append(box("Wardrobe_HandlePost", 0.03, 0.01, 0.01, WX1 + 0.035, 1.05 + dy, hz, M["brass"], 0.002, 1))
    join(wd, "Wardrobe")
    wt = []
    wt.append(box("Wardrobe_BoxA", 0.42, 0.22, 0.5, wc, WH + 0.035 + 0.11, wzc - 0.25, M["basket"], 0.01, 2, ry=0.05))
    wt.append(box("Wardrobe_BoxB", 0.36, 0.16, 0.4, wc + 0.02, WH + 0.035 + 0.08, wzc + 0.28, M["paper_pink"], 0.008, 2, ry=-0.08))
    wt.append(box("Wardrobe_BoxBLid", 0.37, 0.025, 0.41, wc + 0.02, WH + 0.035 + 0.16, wzc + 0.28, M["paper_pink"], 0.006, 2, ry=-0.08))
    join(wt, "Wardrobe_Boxes")

    # ------------------------------------------------------------ neon crescent + star (back wall)
    nz = -4.5 + 0.035
    ncx, ncy = -0.62, 2.06
    pts = []
    for k in range(29):
        a = math.radians(55 + 250 * k / 28)
        pts.append((ncx + 0.13 * math.cos(a), ncy + 0.13 * math.sin(a)))
    for k in range(25):
        a = math.radians(285 - 210 * k / 24)
        pts.append((ncx + 0.045 + 0.1 * math.cos(a), ncy + 0.03 + 0.1 * math.sin(a)))
    pts.append(pts[0])
    neon = [tube("Neon_Moon", [V(x, y, nz) for (x, y) in pts], 0.0075, M["neon"], 8)]
    sp = []
    for k in range(11):
        a = math.pi / 2 + math.pi * k / 5
        r = 0.055 if k % 2 == 0 else 0.024
        sp.append(V(ncx + 0.17 + r * math.cos(a), ncy + 0.09 + r * math.sin(a), nz))
    neon.append(tube("Neon_Star", sp, 0.006, M["neon"], 8))
    join(neon, "Neon_Sign")
    mounts = []
    for (dx, dy) in ((-0.1, 0.08), (-0.08, -0.1), (0.17, 0.09)):
        mounts.append(cyl("Neon_Mount", 0.006, 0.03, ncx + dx, ncy + dy, -4.5, M["metal_light"], 8, rx=math.pi / 2))
    mounts.append(tube("Neon_Cable", [V(ncx - 0.06, ncy - 0.12, -4.495), V(ncx - 0.05, ncy - 0.5, -4.495),
                                      V(ncx - 0.04, 1.2, -4.495), V(ncx - 0.03, 0.02, -4.495)], 0.003, M["cable"], 5))
    join(mounts, "Neon_Mounts")

    # ------------------------------------------------------------ wall clock (hands are set by the code)
    ccx, ccy = 3.0, 2.22
    wz2 = -4.5
    ck = []
    ring = lathe("Clock_Ring", [(0.0, 0.0), (0.15, 0.0), (0.158, 0.012), (0.158, 0.035), (0.15, 0.045), (0.136, 0.045),
                                (0.134, 0.035), (0.0, 0.035)], 48, 0, 0, 0, M["wood_mid"], sharp=40)
    place(ring, ccx, ccy, wz2, rx=math.pi / 2)
    ck.append(ring)
    face = cyl("Clock_Face", 0.134, 0.002, 0, 0, 0, M["paper"], 48)
    place(face, ccx, ccy, wz2 + 0.036, rx=math.pi / 2)
    ck.append(face)
    for k in range(12):
        a = math.pi / 2 - k * math.pi / 6
        L = 0.022 if k % 3 == 0 else 0.012
        mk = box("Clock_Mark", 0.006 if k % 3 == 0 else 0.004, L, 0.002, ccx + 0.112 * math.cos(a), ccy + 0.112 * math.sin(a),
                 wz2 + 0.039, M["clock_hand"], 0, rz=a - math.pi / 2)
        ck.append(mk)
    join(ck, "Clock")
    # hands: origin at the clock centre, pointing to 12 at rest; rotate about local Z
    for name, L, w, dz in (("Clock_HourHand", 0.07, 0.008, 0.041), ("Clock_MinuteHand", 0.105, 0.005, 0.044)):
        hnd = box(name, w, L + 0.02, 0.002, 0, (L + 0.02) / 2 - 0.02, 0, M["clock_hand"], 0)
        apply_transform(hnd, loc=True)
        place(hnd, ccx, ccy, wz2 + dz)
    cap = cyl("Clock_Cap", 0.008, 0.006, 0, 0, 0, M["clock_hand"], 12)
    place(cap, ccx, ccy, wz2 + 0.045, rx=math.pi / 2)
    return True
