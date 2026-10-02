# Room shell: floor, walls (window + door openings with real reveals), ceiling,
# skirting, door, window joinery, curtains, sky card and the ceiling pendant.
import math, random
import bpy
from mathutils import Vector
from roomlib import *

ROOM = dict(minX=-4.0, maxX=4.0, minZ=-4.5, maxZ=3.5, H=3.2)
WIN = dict(z0=-1.9, z1=-0.5, y0=1.2, y1=2.3)        # left wall opening
DOOR = dict(x0=1.35, x1=2.25, y1=2.06)              # front wall opening
REVEAL = 0.15


def oriented(face_pts, want):
    """Return the 4 points ordered so the face normal points along `want`."""
    a, b, c = (Vector(p) for p in face_pts[:3])
    n = (b - a).cross(c - a)
    return face_pts if n.dot(Vector(want)) > 0 else list(reversed(face_pts))


def wall_quads(to3, u_min, u_max, H, hole, normal_b):
    """Quads of a wall (u along the wall, v up) around one rectangular hole.
    to3(u, v) -> Blender point. Returns list of 4-point faces."""
    out = []

    def rect(u0, u1, v0, v1):
        if u1 - u0 < 1e-6 or v1 - v0 < 1e-6:
            return
        pts = [to3(u0, v0), to3(u1, v0), to3(u1, v1), to3(u0, v1)]
        out.append(oriented(pts, normal_b))

    if hole is None:
        rect(u_min, u_max, 0, H)
        return out
    hu0, hu1, hv0, hv1 = hole
    rect(u_min, hu0, 0, H)
    rect(hu1, u_max, 0, H)
    rect(hu0, hu1, 0, hv0)
    rect(hu0, hu1, hv1, H)
    return out


def build(M):
    remove_prefix("Shell_")
    remove_prefix("Window_")
    remove_prefix("Door_")
    remove_prefix("CeilingLamp_")
    remove_prefix("Curtain")
    remove_prefix("LightAnchor_Ceiling")
    remove_prefix("LightAnchor_Window")
    R = ROOM
    # ---------------------------------------------------------------- floor
    f = mesh_obj("Shell_Floor",
                 [V(R["minX"], 0, R["maxZ"]), V(R["maxX"], 0, R["maxZ"]),
                  V(R["maxX"], 0, R["minZ"]), V(R["minX"], 0, R["minZ"])],
                 [(0, 1, 2, 3)], M["floor"])
    planar_uv(f, 0, 1, 1.7, 1.7)

    # ---------------------------------------------------------------- walls
    faces = []
    H = R["H"]
    # back wall (Z = minZ), normal +Z three = -Y blender
    faces += wall_quads(lambda u, v: V(u, v, R["minZ"]), R["minX"], R["maxX"], H, None, (0, -1, 0))
    # right wall (X = maxX), normal -X
    faces += wall_quads(lambda u, v: V(R["maxX"], v, u), R["minZ"], R["maxZ"], H, None, (-1, 0, 0))
    # left wall with the window, normal +X
    faces += wall_quads(lambda u, v: V(R["minX"], v, u), R["minZ"], R["maxZ"], H,
                        (WIN["z0"], WIN["z1"], WIN["y0"], WIN["y1"]), (1, 0, 0))
    # front wall with the door, normal -Z three = +Y blender
    faces += wall_quads(lambda u, v: V(u, v, R["maxZ"]), R["minX"], R["maxX"], H,
                        (DOOR["x0"], DOOR["x1"], -1.0, DOOR["y1"]), (0, 1, 0))
    # window reveal (4 faces from the wall plane to the outside)
    x0, x1 = R["minX"], R["minX"] - REVEAL
    z0, z1, y0, y1 = WIN["z0"], WIN["z1"], WIN["y0"], WIN["y1"]
    faces.append(oriented([V(x0, y0, z0), V(x1, y0, z0), V(x1, y0, z1), V(x0, y0, z1)], (0, 0, 1)))   # sill (up)
    faces.append(oriented([V(x0, y1, z0), V(x1, y1, z0), V(x1, y1, z1), V(x0, y1, z1)], (0, 0, -1)))  # head
    faces.append(oriented([V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0)], (0, -1, 0)))  # jamb z0 faces +Z three
    faces.append(oriented([V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)], (0, 1, 0)))
    # door reveal
    za, zb = R["maxZ"], R["maxZ"] + REVEAL
    dx0, dx1, dy1 = DOOR["x0"], DOOR["x1"], DOOR["y1"]
    faces.append(oriented([V(dx0, dy1, za), V(dx1, dy1, za), V(dx1, dy1, zb), V(dx0, dy1, zb)], (0, 0, -1)))
    faces.append(oriented([V(dx0, 0, za), V(dx0, dy1, za), V(dx0, dy1, zb), V(dx0, 0, zb)], (1, 0, 0)))
    faces.append(oriented([V(dx1, 0, za), V(dx1, dy1, za), V(dx1, dy1, zb), V(dx1, 0, zb)], (-1, 0, 0)))
    verts, flist = [], []
    for q in faces:
        idx = []
        for p in q:
            verts.append(tuple(p))
            idx.append(len(verts) - 1)
        flist.append(idx)
    w = mesh_obj("Shell_Walls", verts, flist, M["wall"])
    box_uv(w, 1.0)

    # ---------------------------------------------------------------- ceiling
    c = mesh_obj("Shell_Ceiling",
                 [V(R["minX"], H, R["minZ"]), V(R["maxX"], H, R["minZ"]),
                  V(R["maxX"], H, R["maxZ"]), V(R["minX"], H, R["maxZ"])],
                 [(0, 1, 2, 3)], M["ceiling"])
    if c.data.polygons[0].normal.z > 0:
        c.data.flip_normals()
    planar_uv(c, 0, 1, 1.0, 1.0)

    # ---------------------------------------------------------------- skirting
    sk = []
    t, h = 0.016, 0.1
    sk.append(box("Shell_Skirt_B", 8.0, h, t, 0, h / 2, R["minZ"] + t / 2, M["skirting"], 0.004, 2))
    sk.append(box("Shell_Skirt_L", t, h, 8.0, R["minX"] + t / 2, h / 2, -0.5, M["skirting"], 0.004, 2))
    sk.append(box("Shell_Skirt_R", t, h, 8.0, R["maxX"] - t / 2, h / 2, -0.5, M["skirting"], 0.004, 2))
    l1 = 1.28 - R["minX"]
    sk.append(box("Shell_Skirt_F1", l1, h, t, R["minX"] + l1 / 2, h / 2, R["maxZ"] - t / 2, M["skirting"], 0.004, 2))
    l2 = R["maxX"] - 2.32
    sk.append(box("Shell_Skirt_F2", l2, h, t, 2.32 + l2 / 2, h / 2, R["maxZ"] - t / 2, M["skirting"], 0.004, 2))
    join(sk, "Shell_Skirting")

    # ---------------------------------------------------------------- door
    d = []
    d.append(box("Door_Slab", 0.86, 2.045, 0.04, 1.8, 0.005 + 2.045 / 2, R["maxZ"] + 0.08, M["door"], 0.006, 2))
    for (y0_, y1_) in ((0.2, 0.95), (1.1, 1.9)):
        d.append(box("Door_Panel", 0.62, y1_ - y0_, 0.01, 1.8, (y0_ + y1_) / 2, R["maxZ"] + 0.06 - 0.004,
                     M["door"], 0.004, 2))
    cw, ct = 0.07, 0.016
    d.append(box("Door_CasingL", cw, DOOR["y1"] + cw, ct, DOOR["x0"] - cw / 2, (DOOR["y1"] + cw) / 2, R["maxZ"] - ct / 2, M["trim"], 0.004, 2))
    d.append(box("Door_CasingR", cw, DOOR["y1"] + cw, ct, DOOR["x1"] + cw / 2, (DOOR["y1"] + cw) / 2, R["maxZ"] - ct / 2, M["trim"], 0.004, 2))
    d.append(box("Door_CasingT", DOOR["x1"] - DOOR["x0"] + 2 * cw, cw, ct, 1.8, DOOR["y1"] + cw / 2, R["maxZ"] - ct / 2, M["trim"], 0.004, 2))
    join(d, "Door")
    hd = []
    hd.append(cyl("Door_Rose", 0.028, 0.012, 1.46, 1.0, R["maxZ"] + 0.06, M["brass"], 20, rx=math.pi / 2, bev=0.003))
    hd.append(cyl("Door_LeverNeck", 0.009, 0.05, 1.46, 1.0, R["maxZ"] + 0.06 - 0.012, M["brass"], 10, rx=math.pi / 2))
    hd.append(box("Door_Lever", 0.12, 0.016, 0.018, 1.51, 1.0, R["maxZ"] + 0.06 - 0.055, M["brass"], 0.006, 2))
    # light switch next to the door
    hd.append(box("Door_Switch", 0.085, 0.12, 0.01, 1.08, 1.15, R["maxZ"] - 0.005, M["plastic_white"], 0.004, 2))
    hd.append(box("Door_SwitchRocker", 0.04, 0.06, 0.008, 1.08, 1.15, R["maxZ"] - 0.012, M["plastic_white"], 0.003, 2))
    join(hd, "Door_Handle")

    # ---------------------------------------------------------------- window joinery
    wx = R["minX"] - 0.09          # frame plane inside the reveal
    fw, fd = 0.055, 0.06
    wz = (WIN["z0"] + WIN["z1"]) / 2
    wy = (WIN["y0"] + WIN["y1"]) / 2
    ww = WIN["z1"] - WIN["z0"]
    wh = WIN["y1"] - WIN["y0"]
    j = []
    j.append(box("Window_FrameB", fd, fw, ww, wx, WIN["y0"] + fw / 2, wz, M["trim"], 0.005, 2))
    j.append(box("Window_FrameT", fd, fw, ww, wx, WIN["y1"] - fw / 2, wz, M["trim"], 0.005, 2))
    j.append(box("Window_FrameL", fd, wh, fw, wx, wy, WIN["z0"] + fw / 2, M["trim"], 0.005, 2))
    j.append(box("Window_FrameR", fd, wh, fw, wx, wy, WIN["z1"] - fw / 2, M["trim"], 0.005, 2))
    j.append(box("Window_MullionV", 0.04, wh - 2 * fw, 0.035, wx, wy, wz, M["trim"], 0.004, 2))
    j.append(box("Window_MullionH", 0.04, 0.035, ww - 2 * fw, wx, wy, wz, M["trim"], 0.004, 2))
    # sill board (protrudes into the room) + apron + casings on the wall
    j.append(box("Window_Sill", 0.29, 0.032, ww + 0.16, R["minX"] - 0.15 + 0.145, WIN["y0"] - 0.016 + 0.004, wz, M["trim"], 0.006, 3))
    j.append(box("Window_Apron", 0.016, 0.07, ww + 0.1, R["minX"] + 0.008, WIN["y0"] - 0.012 - 0.035, wz, M["trim"], 0.003, 2))
    cw = 0.065
    j.append(box("Window_CasingT", 0.016, cw, ww + 2 * cw, R["minX"] + 0.008, WIN["y1"] + cw / 2, wz, M["trim"], 0.004, 2))
    j.append(box("Window_CasingL", 0.016, wh, cw, R["minX"] + 0.008, wy, WIN["z0"] - cw / 2, M["trim"], 0.004, 2))
    j.append(box("Window_CasingR", 0.016, wh, cw, R["minX"] + 0.008, wy, WIN["z1"] + cw / 2, M["trim"], 0.004, 2))
    join(j, "Window_Frame")

    # sky card behind the opening (the code swaps in a sky shader)
    sx = R["minX"] - 0.6
    sky = mesh_obj("Window_Sky",
                   [V(sx, -0.6, -3.8), V(sx, -0.6, 1.4), V(sx, 3.9, 1.4), V(sx, 3.9, -3.8)],
                   [(0, 1, 2, 3)], M["window_sky"])
    if sky.data.polygons[0].normal.x < 0:
        sky.data.flip_normals()
    planar_uv(sky, 1, 2, 5.2, 4.5, -1.4, -0.6)

    # ---------------------------------------------------------------- curtain rod + curtains
    rx_ = R["minX"] + 0.085
    ry_ = 2.52
    rod = []
    pts = [V(rx_, ry_, z) for z in (-2.55, -1.2, 0.15)]
    rod.append(tube("Curtain_Rod", pts, 0.011, M["metal_dark"], 12))
    for z in (-2.55, 0.15):
        rod.append(sphere("Curtain_Finial", 0.022, 0.022, 0.022, rx_, ry_, z + (-0.02 if z < 0 else 0.02), M["metal_dark"], 12, 8))
    for z in (-2.35, -0.05):
        rod.append(box("Curtain_Bracket", 0.09, 0.012, 0.02, R["minX"] + 0.045, ry_ + 0.005, z, M["metal_dark"], 0.003, 1))
    join(rod, "Curtain_Rod")

    def curtain(name, z_wall, z_open, seed):
        """Floor-length velvet panel gathered on the rod. z_wall = edge near
        the wall corner side, z_open = edge toward the window opening."""
        rnd = random.Random(seed)
        nu, nv = 44, 34
        top, bottom = ry_ - 0.03, 0.035
        folds = 6.5
        phase = rnd.uniform(0, 6.28)
        sway = rnd.uniform(-0.03, 0.03)

        def fn(u, v):
            # v = 0 bottom, 1 top
            y = bottom + (top - bottom) * v
            flare = 1.0 + 0.10 * (1 - v) ** 2
            zc = (z_wall + z_open) / 2
            z = zc + (u - 0.5) * (z_open - z_wall) * flare + sway * (1 - v) ** 2
            amp = 0.028 + 0.03 * (1 - v)
            wav = math.sin(2 * math.pi * folds * u + phase)
            wav2 = 0.25 * math.sin(2 * math.pi * folds * 2.0 * u + 1.3 + v * 2.0)
            x = rx_ + 0.005 + amp * (0.6 + 0.5 * wav + wav2 * (0.3 + 0.7 * (1 - v)))
            # the hem curls in slightly on the floor
            x += 0.02 * max(0.0, 0.06 - (y - bottom)) / 0.06
            return V(x, y, z)

        v, f = grid_data(nu, nv, fn)
        o = mesh_obj(name, v, f, M["curtain"], smooth=True)
        # normals toward the room (+X three = +X blender): AO is baked on that side
        if sum(p.normal.x for p in o.data.polygons) < 0:
            o.data.flip_normals()
        grid_uv(o, nu, nv, (abs(z_open - z_wall) * 1.6) / 0.3, (top - bottom) / 0.3)
        # rings on the rod
        rings = []
        for k in range(8):
            u = k / 7
            z = (z_wall + z_open) / 2 + (u - 0.5) * (z_open - z_wall)
            rv, rf = lathe_data([(0.017, -0.003), (0.021, 0.0), (0.017, 0.003)], 12)
            ro = mesh_obj(name + "_Ring", rv, rf, M["metal_dark"], smooth=True)
            place(ro, rx_, ry_, z, rx=math.pi / 2)
            rings.append(ro)
        join(rings, name + "_Rings")
        return o

    curtain("Curtain_L", -2.5, -1.98, 3)
    curtain("Curtain_R", 0.1, -0.42, 5)

    # ---------------------------------------------------------------- ceiling pendant
    cz = -0.5
    pend = []
    pend.append(cyl("CeilingLamp_Canopy", 0.06, 0.025, 0, H - 0.025, cz, M["metal_dark"], 24, bev=0.006))
    pend.append(tube("CeilingLamp_Cord", [V(0, H - 0.02, cz), V(0, 2.83, cz)], 0.004, M["cable"], 6))
    pend.append(cyl("CeilingLamp_Cap", 0.035, 0.04, 0, 2.80, cz, M["metal_dark"], 20, r2=0.028, bev=0.005))
    join(pend, "CeilingLamp_Fixture")
    prof = [(0.215, 0.0), (0.212, 0.02), (0.2, 0.06), (0.178, 0.1), (0.145, 0.14), (0.1, 0.17), (0.05, 0.19), (0.032, 0.195)]
    shade = lathe("CeilingLamp_Shade", prof, 40, 0, 2.62, cz, M["ceiling_shade"], cap_bottom=False, cap_top=True, sharp=80)
    sphere("CeilingLamp_Bulb", 0.05, 0.055, 0.05, 0, 2.72, cz, M["ceiling_bulb"], 16, 10)
    for name, p in (("LightAnchor_Ceiling", (0, 2.3, cz)), ("LightAnchor_Window", (R["minX"] + 0.6, 1.8, -1.2))):
        a = bpy.data.objects.new(name, None)
        link(a)
        a.location = V(*p)
    return True
