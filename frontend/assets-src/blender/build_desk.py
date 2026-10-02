# Desk zone against the back wall around x = -1.4 (desk_sit anchor -1.4, 0, -3.3).
import math, random
import bmesh, bpy
from mathutils import Vector, Matrix
from roomlib import *

TOP_Y = 0.76


def quad_uv(name, corners3, uvs, m):
    """Single textured quad from three-space corners (CCW seen from front)."""
    o = mesh_obj(name, [V(*c) for c in corners3], [(0, 1, 2, 3)], m)
    me = o.data
    uvl = me.uv_layers.new(name="UVMap")
    for li, loop in enumerate(me.loops):
        uvl.data[li].uv = uvs[loop.vertex_index]
    return o


def textured_box(name, w, h, d, X, Y, Z, m, bev=0.002, ry=0.0, rz=0.0, rx=0.0):
    """Box whose top face carries the whole texture (notebooks, books)."""
    o = box(name, w, h, d, 0, 0, 0, m, 0)
    place(o, 0, 0, 0)
    planar_uv(o, 0, 1, w, d, -w / 2, -d / 2)
    place(o, X, Y, Z, ry=ry, rz=rz, rx=rx)
    if bev:
        bevel(o, bev, 1)
    return o


def crumpled(name, r, X, Y, Z, m, seed):
    rnd = random.Random(seed)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=2, radius=r)
    for v in bm.verts:
        v.co *= 1.0 + rnd.uniform(-0.22, 0.12)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    link(o)
    me.materials.append(m)
    place(o, X, Y, Z, ry=rnd.uniform(0, 6))
    return o


def orient_axis(o, origin_b, axis_b):
    """Rotate object so its local +Z points along `axis_b` (Blender space)."""
    q = Vector((0, 0, 1)).rotation_difference(Vector(axis_b).normalized())
    o.matrix_basis = Matrix.Translation(origin_b) @ q.to_matrix().to_4x4()


def build(M):
    for p in ("Desk", "Monitor_", "DeskLamp", "Pinboard", "LightAnchor_Desk", "LightAnchor_Monitor"):
        remove_prefix(p)
    lamp_paint = mat("M_LampPaint", 0xcbb8e8, 0.35, metal=0.3, double=True)

    # ------------------------------------------------------------ desk body
    parts = []
    cx, cz = -1.4, -4.09
    parts.append(box("Desk_Top", 1.9, 0.035, 0.72, cx, TOP_Y - 0.0175, cz, M["wood_desk"], 0.008, 3))
    # drawer unit on the right
    ux, uw, ud, uh = -0.68, 0.42, 0.66, TOP_Y - 0.035
    parts.append(box("Desk_Unit", uw, uh - 0.02, ud, ux, 0.02 + (uh - 0.02) / 2, cz - 0.01, M["wood_desk"], 0.004, 2))
    parts.append(box("Desk_UnitKick", uw - 0.04, 0.03, ud - 0.06, ux, 0.015, cz - 0.03, M["wood_dark"], 0.003, 1))
    front_z = cz - 0.01 + ud / 2
    y = 0.03
    for k, hgt in enumerate((0.27, 0.2, 0.175)):
        y0 = y + 0.006
        parts.append(box(f"Desk_Drawer{k}", uw - 0.012, hgt - 0.008, 0.018, ux, y0 + (hgt - 0.008) / 2, front_z + 0.009,
                         M["wood_desk"], 0.004, 2))
        hy = y0 + hgt - 0.008 - 0.045
        parts.append(box(f"Desk_Pull{k}", 0.12, 0.012, 0.012, ux, hy, front_z + 0.03, M["brass"], 0.004, 2))
        for sx in (-0.05, 0.05):
            parts.append(box(f"Desk_PullPost{k}", 0.008, 0.008, 0.02, ux + sx, hy, front_z + 0.02, M["brass"], 0.002, 1))
        y += hgt
    # legs + rails on the left
    for lz in (cz - 0.31, cz + 0.31):
        parts.append(box("Desk_Leg", 0.045, TOP_Y - 0.035, 0.045, -2.3, (TOP_Y - 0.035) / 2, lz, M["wood_desk"], 0.006, 2))
    parts.append(box("Desk_Stretcher", 0.03, 0.03, 0.58, -2.3, 0.14, cz, M["wood_desk"], 0.005, 2))
    parts.append(box("Desk_Apron", 1.4, 0.07, 0.022, -1.6, TOP_Y - 0.035 - 0.035, cz - 0.33, M["wood_desk"], 0.004, 2))
    join(parts, "Desk")

    # ------------------------------------------------------------ monitor
    mx, my, mz = -1.38, 1.2, -4.27
    mon = []
    mon.append(box("Desk_MonBezel", 0.72, 0.425, 0.022, mx, my, mz, M["plastic_dark"], 0.006, 3, rx=-0.04))
    mon.append(box("Desk_MonBack", 0.46, 0.27, 0.034, mx, my - 0.02, mz - 0.025, M["plastic_dark"], 0.012, 3, rx=-0.04))
    mon.append(box("Desk_MonNeck", 0.05, 0.3, 0.024, mx, TOP_Y + 0.17, mz - 0.045, M["metal_dark"], 0.006, 2, rx=-0.08))
    mon.append(box("Desk_MonFoot", 0.26, 0.012, 0.19, mx, TOP_Y + 0.006, mz - 0.01, M["metal_dark"], 0.005, 3))
    join(mon, "Desk_Monitor")
    # screen: a separate named surface, slightly proud of the bezel
    sw, sh = 0.69, 0.388
    c, s = math.cos(-0.04), math.sin(-0.04)

    def tilt(px, py, pz):
        # rotate (py, pz) around X through the monitor centre by -0.04 rad
        ly, lz = py - my, pz - mz
        return (px, my + ly * c - lz * s, mz + ly * s + lz * c)
    zf = mz + 0.0115
    cy = my + 0.006
    corners = [tilt(mx - sw / 2, cy - sh / 2, zf), tilt(mx + sw / 2, cy - sh / 2, zf),
               tilt(mx + sw / 2, cy + sh / 2, zf), tilt(mx - sw / 2, cy + sh / 2, zf)]
    scr = quad_uv("Monitor_Screen", corners, [(0, 0), (1, 0), (1, 1), (0, 1)], M["monitor_screen"])
    if scr.data.polygons[0].normal.y > 0:
        scr.data.flip_normals()
    ma = bpy.data.objects.new("LightAnchor_Monitor", None)
    link(ma)
    ma.location = V(mx, my, mz + 0.35)

    # ------------------------------------------------------------ keyboard
    kx, kz = -1.38, -3.93
    kb = [box("Desk_KbBase", 0.44, 0.02, 0.145, kx, TOP_Y + 0.004 + 0.01, kz, M["plastic_white"], 0.006, 2)]
    pitch = 0.0272
    for row in range(5):
        zz = kz - 0.054 + row * pitch
        if row == 4:
            layout = [(1.25, 0), (1.25, 0), (1.25, 0), (6.0, 1), (1.25, 0), (1.25, 0), (1.25, 0), (1.5, 1)]
        else:
            layout = [(1.0, 0)] * 14 + [(1.0, 1 if row == 0 else 0)]
        total = sum(wu for wu, _ in layout)
        xx = kx - total * pitch / 2
        for wu, accent in layout:
            w = wu * pitch - 0.0045
            kb.append(box("Desk_Key", w, 0.011, pitch - 0.0045, xx + wu * pitch / 2, TOP_Y + 0.024 + 0.0055, zz,
                          M["keycap_pink"] if accent else M["keycap"], 0.002, 1))
            xx += wu * pitch
    join(kb, "Desk_Keyboard")

    # ------------------------------------------------------------ props on the desk
    pr = []
    pr.append(box("Desk_Mat", 0.86, 0.004, 0.34, -1.28, TOP_Y + 0.002, -3.92, M["mousepad"], 0.002, 1))
    pr.append(sphere("Desk_Mouse", 0.031, 0.02, 0.056, -0.96, TOP_Y + 0.007, -3.9, M["plastic_white"], 16, 10, ry_rot=0.15))
    # mug with coffee + handle
    mug_prof = [(0, 0), (0.037, 0), (0.041, 0.005), (0.043, 0.05), (0.046, 0.095), (0.0455, 0.098),
                (0.043, 0.097), (0.04, 0.05), (0.036, 0.013), (0, 0.013)]
    pr.append(lathe("Desk_Mug", mug_prof, 28, -0.82, TOP_Y, -3.86, M["ceramic_pink"], sharp=70))
    pr.append(cyl("Desk_Coffee", 0.0405, 0.002, -0.82, TOP_Y + 0.074, -3.86, M["coffee"], 24))
    hp = []
    for k in range(9):
        a = -math.pi / 2 + math.pi * k / 8
        hp.append(V(-0.82 + 0.044 + 0.026 * math.cos(a), TOP_Y + 0.052 + 0.03 * math.sin(a), -3.86))
    pr.append(tube("Desk_MugHandle", hp, 0.0065, M["ceramic_pink"], 8))
    # notebook + pen
    pr.append(textured_box("Desk_Notebook", 0.17, 0.012, 0.23, -1.98, TOP_Y + 0.006, -3.93, M["notebook"], 0.002, ry=0.35))
    pr.append(box("Desk_NotebookPages", 0.162, 0.009, 0.222, -1.98, TOP_Y + 0.0062, -3.93, M["paper"], 0.0, ry=0.35))
    pen = cyl("Desk_Pen", 0.0045, 0.14, 0, 0, 0, M["pin_blue"], 10)
    place(pen, -1.95, TOP_Y + 0.017, -3.9, ry=0.9, rz=math.pi / 2)
    pr.append(pen)
    # pen cup with pens
    cup_prof = [(0, 0), (0.034, 0), (0.035, 0.1), (0.031, 0.1), (0.03, 0.006), (0, 0.006)]
    pr.append(lathe("Desk_PenCup", cup_prof, 22, -0.92, TOP_Y, -4.32, M["ceramic_sage"], sharp=60))
    rnd = random.Random(4)
    for k, pm in enumerate((M["pin_blue"], M["pin_red"], M["book3"], M["book4"])):
        pn = cyl("Desk_CupPen", 0.004, 0.15, 0, 0, 0, pm, 8)
        place(pn, -0.92 + rnd.uniform(-0.012, 0.012), TOP_Y + 0.01, -4.32 + rnd.uniform(-0.012, 0.012),
              rx=rnd.uniform(-0.25, 0.25), rz=rnd.uniform(-0.25, 0.25))
        pr.append(pn)
    # two lying books + a succulent on top
    pr.append(box("Desk_BookA", 0.17, 0.028, 0.24, -0.62, TOP_Y + 0.014, -4.08, M["book1"], 0.003, 1, ry=0.08))
    pr.append(box("Desk_BookAPages", 0.162, 0.022, 0.235, -0.617, TOP_Y + 0.014, -4.078, M["book_pages"], 0.0, ry=0.08))
    pr.append(box("Desk_BookB", 0.15, 0.022, 0.21, -0.63, TOP_Y + 0.028 + 0.011, -4.09, M["book7"], 0.003, 1, ry=-0.12))
    pr.append(box("Desk_BookBPages", 0.142, 0.016, 0.205, -0.627, TOP_Y + 0.028 + 0.011, -4.088, M["book_pages"], 0.0, ry=-0.12))
    sy = TOP_Y + 0.05
    pr.append(lathe("Desk_SuccPot", [(0, 0), (0.032, 0), (0.038, 0.055), (0.034, 0.055), (0.0, 0.05)], 20,
                    -0.63, sy, -4.09, M["ceramic_white"], sharp=60))
    for k in range(9):
        a = k * 2.4
        leaf = sphere("Desk_SuccLeaf", 0.012, 0.03, 0.009, -0.63 + 0.012 * math.cos(a), sy + 0.06, -4.09 + 0.012 * math.sin(a),
                      M["succulent"], 8, 6)
        leaf.rotation_euler = (math.cos(a) * 0.5, -math.sin(a) * 0.5 * 0 + 0.0, 0)
        leaf.rotation_euler = (-math.sin(a) * 0.55, math.cos(a) * 0.55, 0)
        pr.append(leaf)
    pr.append(sphere("Desk_SuccCore", 0.014, 0.022, 0.014, -0.63, sy + 0.065, -4.09, M["succulent"], 10, 6))
    # waste bin + paper balls
    bin_prof = [(0, 0), (0.105, 0), (0.125, 0.3), (0.119, 0.3), (0.1, 0.008), (0, 0.008)]
    pr.append(lathe("Desk_Bin", bin_prof, 28, -0.22, 0, -4.18, M["bin"], sharp=60))
    pr.append(crumpled("Desk_Paper1", 0.035, -0.24, 0.29, -4.17, M["paper_ball"], 1))
    pr.append(crumpled("Desk_Paper2", 0.03, -0.19, 0.3, -4.2, M["paper_ball"], 2))
    pr.append(crumpled("Desk_Paper3", 0.032, -0.06, 0.03, -4.36, M["paper_ball"], 3))
    # cables: monitor down the back, lamp down to the floor
    cab = [V(-1.38, 1.06, -4.33), V(-1.37, 0.86, -4.36), V(-1.36, 0.78, -4.42), V(-1.35, 0.7, -4.465),
           V(-1.34, 0.3, -4.475), V(-1.33, 0.03, -4.48), V(-1.2, 0.006, -4.47), V(-0.9, 0.006, -4.47)]
    pr.append(tube("Desk_CableMon", cab, 0.0045, M["cable"], 6))
    cab2 = [V(-2.15, TOP_Y + 0.008, -4.36), V(-2.16, TOP_Y + 0.004, -4.44), V(-2.17, TOP_Y - 0.02, -4.47),
            V(-2.19, 0.45, -4.475), V(-2.22, 0.12, -4.47), V(-2.28, 0.02, -4.44), V(-2.45, 0.006, -4.4),
            V(-2.75, 0.006, -4.46), V(-3.0, 0.006, -4.47)]
    pr.append(tube("Desk_CableLamp", cab2, 0.004, M["cable"], 6))
    join(pr, "Desk_Props")

    # ------------------------------------------------------------ architect lamp
    base = (-2.15, TOP_Y, -4.3)
    elbow = (-2.19, 1.17, -4.38)
    head = (-1.95, 1.3, -4.14)
    aim_pt = (-1.82, TOP_Y, -3.98)
    lp = []
    lp.append(cyl("DeskLamp_Base", 0.075, 0.024, base[0], base[1], base[2], lamp_paint, 28, bev=0.008))
    lp.append(sphere("DeskLamp_Joint0", 0.018, 0.018, 0.018, base[0], base[1] + 0.035, base[2], M["metal_dark"], 12, 8))
    for off in (-0.012, 0.012):
        a = Vector(V(base[0] + off, base[1] + 0.035, base[2]))
        b = Vector(V(elbow[0] + off, elbow[1], elbow[2]))
        lp.append(tube("DeskLamp_ArmA", [a, b], 0.006, lamp_paint, 8))
        a2 = Vector(V(elbow[0] + off, elbow[1], elbow[2]))
        b2 = Vector(V(head[0] + off, head[1], head[2]))
        lp.append(tube("DeskLamp_ArmB", [a2, b2], 0.006, lamp_paint, 8))
    lp.append(cyl("DeskLamp_Elbow", 0.02, 0.04, elbow[0] - 0.02, elbow[1], elbow[2], M["metal_dark"], 14, rz=math.pi / 2))
    lp.append(sphere("DeskLamp_Joint1", 0.016, 0.016, 0.016, head[0], head[1], head[2], M["metal_dark"], 12, 8))
    # spring along the lower arm
    sp = []
    A, B = Vector(V(base[0] + 0.03, base[1] + 0.06, base[2])), Vector(V(elbow[0] + 0.03, elbow[1] - 0.12, elbow[2]))
    axis = (B - A)
    side = axis.cross(Vector((0, 0, 1))).normalized()
    up = side.cross(axis.normalized())
    for k in range(120):
        t = k / 119
        a = t * 2 * math.pi * 22
        sp.append(A + axis * t + side * 0.006 * math.cos(a) + up * 0.006 * math.sin(a))
    lp.append(tube("DeskLamp_Spring", sp, 0.0012, M["metal_light"], 4))
    join(lp, "DeskLamp")
    # shade pointing at the desk
    hb = Vector(V(*head))
    d = (Vector(V(*aim_pt)) - hb).normalized()
    shade_prof = [(0.078, 0.0), (0.075, 0.025), (0.064, 0.06), (0.045, 0.095), (0.026, 0.118), (0.018, 0.13), (0.0, 0.132)]
    sv, sf = lathe_data(shade_prof, 30, cap_bottom=False)
    shade = mesh_obj("DeskLamp_Head", sv, sf, lamp_paint, smooth=True, sharp_angle=80)
    origin = hb + d * 0.13       # rim sits 13 cm along the aim from the joint
    orient_axis(shade, origin, -d)
    bv, bf = uv_sphere_data(0.03, 0.03, 0.03, 14, 8)
    bulb = mesh_obj("DeskLamp_Bulb", bv, bf, M["desk_lamp_glow"], smooth=True)
    bulb.location = origin - d * 0.045
    anchor = bpy.data.objects.new("LightAnchor_DeskLamp", None)
    link(anchor)
    anchor.location = origin + d * 0.03

    # ------------------------------------------------------------ pinboard
    px, py, pw, ph = -1.72, 1.86, 0.9, 0.6
    wall = -4.5
    pb = []
    pb.append(textured_box("Pinboard_Cork", pw, ph, 0.012, px, py, wall + 0.006, M["cork"], 0, rx=0))
    # planar UV of the cork face (front): recompute along X/Y
    cork = pb[-1]
    planar_uv(cork, 0, 2, 0.45, 0.45)
    fw = 0.025
    for (w_, h_, x_, y_) in ((pw + 2 * fw, fw, px, py + ph / 2 + fw / 2), (pw + 2 * fw, fw, px, py - ph / 2 - fw / 2),
                             (fw, ph, px - pw / 2 - fw / 2, py), (fw, ph, px + pw / 2 + fw / 2, py)):
        pb.append(box("Pinboard_Frame", w_, h_, 0.024, x_, y_, wall + 0.012, M["wood_mid"], 0.004, 2))
    join(pb, "Pinboard")
    items = []
    zf = wall + 0.0125
    rnd = random.Random(11)
    photos = [(px - 0.3, py + 0.1, 0), (px - 0.17, py - 0.06, 1), (px + 0.2, py + 0.12, 2), (px + 0.33, py - 0.1, 3)]
    for (x_, y_, i) in photos:
        w_, h_ = 0.085, 0.1
        a = rnd.uniform(-0.18, 0.18)
        ca, sa = math.cos(a), math.sin(a)
        cs = [(-w_ / 2, -h_ / 2), (w_ / 2, -h_ / 2), (w_ / 2, h_ / 2), (-w_ / 2, h_ / 2)]
        corners = [(x_ + u * ca - v * sa, y_ + u * sa + v * ca, zf + 0.001 * (i + 1)) for (u, v) in cs]
        u0, u1 = i / 4 + 16 / 1024, i / 4 + 240 / 1024
        items.append(quad_uv("Pinboard_Photo", corners, [(u0, 0), (u1, 0), (u1, 1), (u0, 1)], M["photos"]))
        items.append(sphere("Pinboard_Pin", 0.006, 0.006, 0.006, x_ - sa * 0.04, y_ + ca * 0.04, zf + 0.008,
                            M["pin_red"] if i % 2 else M["pin_blue"], 8, 6))
    for (x_, y_, m_) in ((px + 0.02, py + 0.16, M["paper_pink"]), (px + 0.05, py - 0.15, M["paper_yellow"]),
                         (px - 0.36, py - 0.17, M["paper_blue"])):
        a = rnd.uniform(-0.2, 0.2)
        n = box("Pinboard_Note", 0.075, 0.075, 0.002, x_, y_, zf + 0.002, m_, 0, rz=a)
        items.append(n)
        items.append(sphere("Pinboard_Pin", 0.006, 0.006, 0.006, x_, y_ + 0.028, zf + 0.008, M["pin_red"], 8, 6))
    # a small calendar sheet
    items.append(box("Pinboard_Calendar", 0.15, 0.19, 0.002, px + 0.06, py + 0.0, zf + 0.0015, M["paper"], 0, rz=0.03))
    items.append(box("Pinboard_CalHead", 0.15, 0.04, 0.0025, px + 0.06 - 0.003, py + 0.075, zf + 0.0025, M["paper_pink"], 0, rz=0.03))
    join(items, "Pinboard_Items")
    return True


CHAIR_POS = (-1.4, -3.3)   # three (x, z) of the floor point under the seat centre
CHAIR_YAW = 0.3            # rotation.y; local -Z faces the desk, +Z is the backrest


def build_chair(M):
    """One object, "DeskChair": origin on the floor under the seat centre,
    yaw kept on the node so the code can slide it along its own axis."""
    remove_prefix("Chair")
    remove_prefix("DeskChair")
    remove_prefix("Desk_Chair")
    ch = []
    hub_y = 0.075
    for k in range(5):
        a = k * 2 * math.pi / 5 + 0.3
        sx, sz = math.sin(a), math.cos(a)
        ch.append(box("Chair_Spoke", 0.04, 0.035, 0.3, 0.15 * sx, hub_y, 0.15 * sz, M["metal_dark"], 0.008, 2, ry=a))
        # caster: fork + wheel
        ch.append(box("Chair_Fork", 0.025, 0.035, 0.03, 0.29 * sx, 0.05, 0.29 * sz, M["plastic_dark"], 0.006, 2, ry=a))
        ch.append(cyl("Chair_Wheel", 0.026, 0.024, 0.29 * sx - 0.012 * math.cos(a), 0.026, 0.29 * sz + 0.012 * math.sin(a),
                      M["plastic_dark"], 14, rz=math.pi / 2, bev=0.006))
    ch.append(cyl("Chair_Hub", 0.05, 0.05, 0, 0.05, 0, M["metal_dark"], 20, bev=0.01))
    ch.append(cyl("Chair_Gas", 0.022, 0.32, 0, 0.09, 0, M["metal_light"], 16))
    ch.append(cyl("Chair_GasCover", 0.032, 0.14, 0, 0.09, 0, M["plastic_dark"], 16, r2=0.028))
    ch.append(box("Chair_Plate", 0.22, 0.03, 0.22, 0, 0.41, 0, M["metal_dark"], 0.006, 2))
    ch.append(box("Chair_Seat", 0.5, 0.085, 0.48, 0, 0.465, 0.0, M["chair"], 0.038, 5))
    ch.append(box("Chair_BackBar", 0.06, 0.32, 0.03, 0, 0.56, 0.255, M["metal_dark"], 0.008, 2, rx=0.12))
    ch.append(box("Chair_Back", 0.47, 0.6, 0.075, 0, 0.88, 0.26, M["chair"], 0.034, 5, rx=0.12))
    ch.append(box("Chair_Headrest", 0.3, 0.11, 0.06, 0, 1.105, 0.25, M["chair_accent"], 0.026, 4, rx=0.12))
    ch.append(box("Chair_Lumbar", 0.34, 0.12, 0.05, 0, 0.66, 0.205, M["chair_accent"], 0.022, 4, rx=0.12))
    for s in (-1, 1):
        ch.append(box("Chair_ArmPost", 0.03, 0.2, 0.04, s * 0.27, 0.57, 0.06, M["metal_dark"], 0.008, 2))
        ch.append(box("Chair_ArmPad", 0.06, 0.026, 0.25, s * 0.27, 0.68, 0.0, M["plastic_dark"], 0.011, 3))
        ch.append(box("Chair_ArmLink", 0.03, 0.03, 0.14, s * 0.24, 0.48, 0.04, M["metal_dark"], 0.008, 2))
    o = join(ch, "DeskChair")
    place(o, CHAIR_POS[0], 0, CHAIR_POS[1], ry=CHAIR_YAW)
    return o
