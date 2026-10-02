# Cloth simulations baked to static meshes: duvet (with a folded-back top),
# plaid throw across the foot, hoodie draped on the desk chair.
import math, bpy
from mathutils import Vector, Matrix
from roomlib import *


def _mod(o, kind):
    return o.modifiers.new(kind.title(), enum_ok(bpy.types.Modifier, "type", kind))


def simulate(obj, colliders, frames, mass=0.3, tension=15.0, bending=1.0, self_col=False,
             quality=6, col_dist=0.006, friction=5.0):
    sc = bpy.context.scene
    added = []
    for c in colliders:
        if c is None:
            continue
        m = _mod(c, "COLLISION")
        c.collision.thickness_outer = 0.008
        c.collision.cloth_friction = friction
        added.append((c, m))
    md = _mod(obj, "CLOTH")
    s = md.settings
    s.quality = quality
    s.mass = mass
    s.tension_stiffness = tension
    s.compression_stiffness = tension
    s.shear_stiffness = tension * 0.5
    s.bending_stiffness = bending
    s.air_damping = 1.0
    cs = md.collision_settings
    cs.distance_min = col_dist
    cs.use_self_collision = self_col
    if self_col:
        cs.self_distance_min = col_dist
    md.point_cache.frame_start = 1
    md.point_cache.frame_end = frames
    sc.frame_start = 1
    sc.frame_end = frames
    for f in range(1, frames + 1):
        sc.frame_set(f)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    old = obj.data
    obj.modifiers.clear()
    obj.data = me
    me.name = obj.name
    if old.users == 0:
        bpy.data.meshes.remove(old)
    for c, m in added:
        c.modifiers.remove(m)
    sc.frame_set(1)
    return obj


def solidify(o, thickness, offset=0.0):
    md = _mod(o, "SOLIDIFY")
    md.thickness = thickness
    md.offset = offset
    md.use_even_offset = True
    return md


def grid_obj(name, nu, nv, fn, m, su, sv, keep=None):
    v, f = grid_data(nu, nv, fn)
    o = mesh_obj(name, v, f, m, smooth=True)
    grid_uv(o, nu, nv, su, sv)
    if keep is not None:
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.faces.ensure_lookup_table()
        dead = [fc for fc in bm.faces if not keep(fc.calc_center_median())]
        bmesh.ops.delete(bm, geom=dead, context="FACES")
        loose = [vv for vv in bm.verts if not vv.link_faces]
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
        bm.to_mesh(o.data)
        bm.free()
    return o


def build_bed_cloth(M):
    remove_prefix("Bed_Duvet")
    remove_prefix("Bed_Throw")
    remove_prefix("Tmp_")
    BX, BZ = -3.35, 1.3
    y0 = 0.47
    r = 0.028
    L_main, L_fold = 1.6, 0.34
    z_start = 0.12
    L_tot = L_main + math.pi * r + L_fold
    W = 1.45
    XC = BX + 0.1      # start fully inside the wall (x > -4): a vertex behind the
                       # one-sided wall collider would be shot into the room

    def fn(u, v):
        x = XC - W / 2 + W * u
        s = v * L_tot
        if s <= L_main:
            z, y = z_start + s, y0
        elif s <= L_main + math.pi * r:
            th = (s - L_main) / r
            z, y = z_start + L_main + r * math.sin(th), y0 + r * (1 - math.cos(th))
        else:
            z, y = z_start + L_main - (s - L_main - math.pi * r), y0 + 2 * r
        return V(x, y, z)

    duvet = grid_obj("Bed_Duvet", 48, 72, fn, M["duvet"], W / 0.4, L_tot / 0.4)
    # Collision is one-sided (use_culling): collider normals must face the cloth,
    # or every vertex counts as "inside" and gets pushed through.
    wall = mesh_obj("Tmp_Wall", [V(-4.0, 0, -1), V(-4.0, 0, 3.4), V(-4.0, 1.2, 3.4), V(-4.0, 1.2, -1)], [(0, 1, 2, 3)])
    if wall.data.polygons[0].normal.x < 0:
        wall.data.flip_normals()
    floor = mesh_obj("Tmp_Floor", [V(-5, 0, -1), V(-1, 0, -1), V(-1, 0, 4), V(-5, 0, 4)], [(0, 1, 2, 3)])
    if floor.data.polygons[0].normal.z < 0:
        floor.data.flip_normals()
    cols = [bpy.data.objects.get(n) for n in ("Bed_Mattress", "Bed_Frame", "Bed_Pillow", "Bed_Plushie", "Bed_Cushion")]
    # high friction: the room-side overhang is heavier and would drag it off
    simulate(duvet, cols + [wall, floor], 55, mass=0.45, tension=18, bending=6.0, self_col=True, quality=7,
             col_dist=0.008, friction=40)
    solidify(duvet, 0.03, 0.0)
    apply_modifiers([duvet])
    duvet.data.shade_smooth()
    # plaid throw across the foot, hanging over the room side
    tw, tl = 1.35, 0.55

    def fn2(u, v):
        return V(-3.1 - tw / 2 + tw * u, 0.68, 0.22 + tl * v)

    throw = grid_obj("Bed_Throw", 40, 16, fn2, M["throw"], tw / 0.3, tl / 0.3)
    simulate(throw, cols + [wall, floor, duvet], 45, mass=0.25, tension=12, bending=0.6, quality=6, col_dist=0.006,
             friction=40)
    solidify(throw, 0.008, 0.0)
    apply_modifiers([throw])
    for n in ("Tmp_Wall", "Tmp_Floor"):
        o = bpy.data.objects.get(n)
        if o:
            bpy.data.objects.remove(o, do_unlink=True)
    return duvet, throw


def build_hoodie(M):
    remove_prefix("Desk_Hoodie")
    from build_desk import CHAIR_POS, CHAIR_YAW
    chair = bpy.data.objects.get("DeskChair")
    yaw = CHAIR_YAW
    cx, cz = CHAIR_POS
    W, Lz = 0.52, 0.95

    def local(x, y, z):
        c, s = math.cos(yaw), math.sin(yaw)
        return V(cx + x * c + z * s, y, cz - x * s + z * c)

    def fn(u, v):
        x = -W / 2 + W * u
        z = 0.26 - Lz * 0.45 + Lz * v
        return local(x, 1.26, z)

    h = grid_obj("Desk_Hoodie", 22, 40, fn, M["hoodie"], W / 0.25, Lz / 0.25)
    # Proxy collider: the real backrest is several overlapping boxes, whose
    # interior faces confuse one-sided cloth collision (it tunnels through).
    proxy = box("Tmp_BackProxy", 0.48, 0.68, 0.085, 0, 0.87, 0.255, None, 0.03, 3, rx=0.12)
    seat = box("Tmp_SeatProxy", 0.52, 0.1, 0.5, 0, 0.46, 0.0, None, 0.03, 3)
    for o in (proxy, seat):
        o.matrix_basis = chair.matrix_basis @ o.matrix_basis
    apply_modifiers([proxy, seat])
    simulate(h, [proxy, seat], 60, mass=0.3, tension=15, bending=1.5, quality=10, col_dist=0.01, friction=40)
    for o in (proxy, seat):
        bpy.data.objects.remove(o, do_unlink=True)
    push_out(h, chair, 0.01)
    solidify(h, 0.006, 0.0)
    apply_modifiers([h])
    # sleeves hanging beside the backrest + the hood lying on its back
    extra = []
    for s in (-1, 1):
        pts = [(s * 0.2, 1.19, 0.27), (s * 0.29, 1.12, 0.285), (s * 0.31, 0.95, 0.29), (s * 0.305, 0.78, 0.275),
               (s * 0.3, 0.68, 0.26)]
        sl = tube("Desk_HoodieSleeve", [V(*p) for p in pts], 0.04, M["hoodie"], 12,
                  radii=[0.045, 0.045, 0.042, 0.038, 0.034])
        extra.append(sl)
        extra.append(sphere("Desk_HoodieCuff", 0.034, 0.02, 0.034, s * 0.3, 0.665, 0.258, M["hoodie"], 12, 8))
    hood = sphere("Desk_HoodieHood", 0.13, 0.12, 0.055, 0, 1.0, 0.33, M["hoodie"], 20, 12)
    place(hood, 0, 1.03, 0.335, rx=0.12)
    extra.append(hood)
    for o in extra:
        o.matrix_basis = chair.matrix_basis @ o.matrix_basis
        apply_transform(o, loc=True)
    for o in extra:
        push_out(o, chair, 0.004)
    # the hoodie belongs to the chair: it moves with it when she pulls it out
    return join([chair, h] + extra, "DeskChair", bake=False)


def push_out(o, collider, margin):
    """Move vertices of `o` that ended up inside (or too close to) the
    collider back out along its nearest surface normal."""
    from mathutils.bvhtree import BVHTree
    dg = bpy.context.evaluated_depsgraph_get()
    bv = BVHTree.FromObject(collider.evaluated_get(dg), dg)
    cm = collider.matrix_basis
    inv = cm.inverted()
    om = o.matrix_basis
    oinv = om.inverted()
    nm = cm.to_3x3()
    moved = 0
    for v in o.data.vertices:
        p = inv @ (om @ v.co)
        loc, nrm, idx, dist = bv.find_nearest(p)
        if loc is None:
            continue
        d = (p - loc).dot(nrm)
        if d < margin:
            q = loc + nrm * margin
            v.co = oinv @ (cm @ q)
            moved += 1
    o.data.update()
    return moved
