# Helpers to author Mika's room in Blender. All positions/sizes are given in
# three.js coordinates (X right, Y up, Z toward the default camera) and
# converted here: three (X, Y, Z) -> Blender (X, -Z, Y).
import bpy, bmesh, math, random
from mathutils import Vector, Matrix

import os
# assets-src/blender/ -> frontend/
FRONT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TEXDIR = FRONT + "/assets-src/textures"


def V(X, Y, Z):
    return Vector((X, -Z, Y))


def enum_ok(rna_owner, prop, value):
    """Validate an enum identifier against bl_rna instead of trusting it."""
    items = [i.identifier for i in rna_owner.bl_rna.properties[prop].enum_items]
    if value not in items:
        raise ValueError(f"{prop}: {value!r} not in {items}")
    return value


def srgb2lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def col(h):
    return (srgb2lin((h >> 16) & 255), srgb2lin((h >> 8) & 255), srgb2lin(h & 255), 1.0)


# ------------------------------------------------------------------ scene

def collection(name="Room"):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c


def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.curves, bpy.data.lights,
                 bpy.data.cameras, bpy.data.node_groups, bpy.data.images, bpy.data.textures):
        for b in list(coll):
            try:
                coll.remove(b)
            except Exception:
                pass
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)


def remove_prefix(prefix):
    for o in list(bpy.data.objects):
        if o.name.startswith(prefix):
            bpy.data.objects.remove(o, do_unlink=True)
    for m in list(bpy.data.meshes):
        if m.users == 0:
            bpy.data.meshes.remove(m)


# -------------------------------------------------------------- materials

_images = {}


def image(fname, noncolor=False):
    key = (fname, noncolor)
    if key in _images and _images[key].name in bpy.data.images:
        return _images[key]
    img = bpy.data.images.load(TEXDIR + "/" + fname, check_existing=True)
    if noncolor:
        img.colorspace_settings.name = "Non-Color"
    _images[key] = img
    return img


def principled(m):
    return next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def mat(name, color=0x888888, rough=0.6, metal=0.0, emit=None, strength=0.0,
        tex=None, tint=None, alpha=None, double=False, ao=True, emit_tex=None,
        spec=0.5):
    """Principled-only material. `tex` = base colour image (UVMap); `tint`
    multiplies it (exported as baseColorFactor). `ao` marks the material as
    receiving the baked AO atlas (all its objects get a UV2 + bake)."""
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type not in ("BSDF_PRINCIPLED", "OUTPUT_MATERIAL"):
            nt.nodes.remove(n)
    bsdf = principled(m)
    bsdf.location = (0, 0)
    bsdf.inputs["Base Color"].default_value = col(color)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = spec
    if emit is not None:
        bsdf.inputs["Emission Color"].default_value = col(emit)
        bsdf.inputs["Emission Strength"].default_value = strength
    else:
        bsdf.inputs["Emission Strength"].default_value = 0.0
    if tex:
        uv = nt.nodes.new("ShaderNodeUVMap")
        uv.uv_map = "UVMap"
        uv.location = (-900, 200)
        it = nt.nodes.new("ShaderNodeTexImage")
        it.image = image(tex)
        it.location = (-650, 200)
        nt.links.new(uv.outputs["UV"], it.inputs["Vector"])
        if tint is not None:
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = enum_ok(mix, "data_type", "RGBA")
            mix.blend_type = enum_ok(mix, "blend_type", "MULTIPLY")
            mix.inputs["Factor"].default_value = 1.0
            mix.location = (-300, 200)
            a = next(s for s in mix.inputs if s.identifier == "A_Color")
            b = next(s for s in mix.inputs if s.identifier == "B_Color")
            nt.links.new(it.outputs["Color"], a)
            b.default_value = col(tint)
            out = next(s for s in mix.outputs if s.identifier == "Result_Color")
            nt.links.new(out, bsdf.inputs["Base Color"])
        else:
            nt.links.new(it.outputs["Color"], bsdf.inputs["Base Color"])
    if emit_tex:
        uv = nt.nodes.new("ShaderNodeUVMap")
        uv.uv_map = "UVMap"
        uv.location = (-900, -300)
        it = nt.nodes.new("ShaderNodeTexImage")
        it.image = image(emit_tex)
        it.location = (-650, -300)
        nt.links.new(uv.outputs["UV"], it.inputs["Vector"])
        nt.links.new(it.outputs["Color"], bsdf.inputs["Emission Color"])
    if alpha is not None:
        bsdf.inputs["Alpha"].default_value = alpha
        try:
            m.surface_render_method = enum_ok(m, "surface_render_method", "BLENDED")
        except Exception:
            pass
    m.use_backface_culling = not double
    m.diffuse_color = col(color)
    m["ao"] = bool(ao and emit is None and alpha is None)
    return m


# ---------------------------------------------------------------- objects

def link(o):
    collection().objects.link(o)
    return o


def mesh_obj(name, verts, faces, m=None, smooth=False, sharp_angle=None, loc=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    me.validate()
    me.update()
    o = bpy.data.objects.new(name, me)
    link(o)
    if m is not None:
        if isinstance(m, (list, tuple)):
            for mm in m:
                me.materials.append(mm)
        else:
            me.materials.append(m)
    if smooth:
        me.shade_smooth()
        if sharp_angle is not None:
            me.set_sharp_from_angle(angle=math.radians(sharp_angle))
    if loc is not None:
        o.location = loc
    return o


def place(o, X, Y, Z, ry=0.0, rx=0.0, rz=0.0):
    """Set location (three coords) + rotation (three Euler XYZ, radians)."""
    o.location = V(X, Y, Z)
    # three Rx -> blender Rx, three Ry -> blender Rz, three Rz -> blender Ry(-a)
    R = Matrix.Rotation(rx, 4, "X") @ Matrix.Rotation(ry, 4, "Z") @ Matrix.Rotation(-rz, 4, "Y")
    o.rotation_euler = R.to_euler()
    return o


def bevel(o, width, seg=3, angle=35.0, harden=True, clamp=True):
    md = o.modifiers.new("Bevel", enum_ok(bpy.types.Modifier, "type", "BEVEL"))
    md.width = width
    md.segments = seg
    md.limit_method = enum_ok(md, "limit_method", "ANGLE")
    md.angle_limit = math.radians(angle)
    md.use_clamp_overlap = clamp
    if harden:
        md.harden_normals = True
        o.data.shade_smooth()
    return md


def box(name, w, h, d, X, Y, Z, m, bev=0.008, seg=3, ry=0.0, rx=0.0, rz=0.0):
    """Box sized in three.js axes (w: X, h: Y up, d: Z)."""
    bx, by, bz = w / 2, d / 2, h / 2
    verts = [(-bx, -by, -bz), (bx, -by, -bz), (bx, by, -bz), (-bx, by, -bz),
             (-bx, -by, bz), (bx, -by, bz), (bx, by, bz), (-bx, by, bz)]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    o = mesh_obj(name, verts, faces, m)
    place(o, X, Y, Z, ry, rx, rz)
    if bev and bev > 0:
        bevel(o, min(bev, 0.45 * min(w, h, d)), seg)
    return o


def lathe_data(profile, segs, a0=0.0, sweep=2 * math.pi, cap_bottom=True, cap_top=True):
    """Revolve [(r, h)] around the local up axis. Returns verts, faces."""
    verts, faces, rings = [], [], []
    full = abs(sweep - 2 * math.pi) < 1e-6
    n = segs if full else segs + 1
    for (r, h) in profile:
        if r < 1e-6:
            verts.append((0.0, 0.0, h))
            rings.append([len(verts) - 1] * n)
        else:
            idx = []
            for i in range(n):
                a = a0 + sweep * i / segs
                verts.append((r * math.cos(a), r * math.sin(a), h))
                idx.append(len(verts) - 1)
            rings.append(idx)
    for k in range(len(rings) - 1):
        A, B = rings[k], rings[k + 1]
        for i in range(segs):
            j = (i + 1) % n if full else i + 1
            f = []
            for v in (A[i], A[j], B[j], B[i]):
                if v not in f:
                    f.append(v)
            if len(f) >= 3:
                faces.append(f)
    if full:
        if cap_bottom and profile[0][0] > 1e-6:
            faces.append(list(reversed(rings[0])))
        if cap_top and profile[-1][0] > 1e-6:
            faces.append(list(rings[-1]))
    return verts, faces


def lathe(name, profile, segs, X, Y, Z, m, smooth=True, sharp=50.0, **kw):
    v, f = lathe_data(profile, segs, **kw)
    o = mesh_obj(name, v, f, m, smooth=smooth, sharp_angle=sharp)
    place(o, X, Y, Z)
    return o


def cyl(name, r, h, X, Y, Z, m, segs=24, r2=None, bev=0.0, **rot):
    """Cylinder standing on its base centre at (X, Y, Z)."""
    r2 = r if r2 is None else r2
    if bev > 0:
        b = min(bev, 0.4 * min(r, r2, h))
        prof = [(0, 0), (r - b, 0), (r - b * 0.3, b * 0.1), (r, b), (r2, h - b),
                (r2 - b * 0.3, h - b * 0.1), (r2 - b, h), (0, h)]
    else:
        prof = [(0, 0), (r, 0), (r2, h), (0, h)]
    v, f = lathe_data(prof, segs)
    o = mesh_obj(name, v, f, m, smooth=True, sharp_angle=50)
    place(o, X, Y, Z, **rot)
    return o


def tube_data(points, radius, segs=8, radii=None, cap=True):
    """Sweep a circle along a polyline of Blender-space points."""
    verts, faces = [], []
    n = len(points)
    prev_side = None
    for i, p in enumerate(points):
        p = Vector(p)
        if i == 0:
            t = (Vector(points[1]) - p).normalized()
        elif i == n - 1:
            t = (p - Vector(points[i - 1])).normalized()
        else:
            t = (Vector(points[i + 1]) - Vector(points[i - 1])).normalized()
        if prev_side is None:
            up = Vector((0, 0, 1)) if abs(t.z) < 0.9 else Vector((1, 0, 0))
            side = t.cross(up).normalized()
        else:
            side = (prev_side - t * prev_side.dot(t)).normalized()
        prev_side = side
        up2 = side.cross(t).normalized()
        r = radii[i] if radii else radius
        for k in range(segs):
            a = 2 * math.pi * k / segs
            verts.append(tuple(p + (side * math.cos(a) + up2 * math.sin(a)) * r))
    for i in range(n - 1):
        for k in range(segs):
            a = i * segs + k
            b = i * segs + (k + 1) % segs
            faces.append((a, a + segs, b + segs, b))     # outward normals
    if cap:
        faces.append(tuple(range(segs)))
        faces.append(tuple(reversed(range((n - 1) * segs, n * segs))))
    return verts, faces


def tube(name, points, radius, m, segs=8, radii=None, cap=True):
    v, f = tube_data(points, radius, segs, radii, cap)
    return mesh_obj(name, v, f, m, smooth=True, sharp_angle=70)


def uv_sphere_data(rx, ry, rz, segs=16, rings=10):
    verts, faces = [(0, 0, -rz)], []
    for j in range(1, rings):
        phi = -math.pi / 2 + math.pi * j / rings
        for i in range(segs):
            th = 2 * math.pi * i / segs
            verts.append((rx * math.cos(phi) * math.cos(th), ry * math.cos(phi) * math.sin(th), rz * math.sin(phi)))
    verts.append((0, 0, rz))
    top = len(verts) - 1
    for i in range(segs):
        faces.append((0, 1 + (i + 1) % segs, 1 + i))
    for j in range(rings - 2):
        for i in range(segs):
            a = 1 + j * segs + i
            b = 1 + j * segs + (i + 1) % segs
            faces.append((a, b, b + segs, a + segs))
    base = 1 + (rings - 2) * segs
    for i in range(segs):
        faces.append((base + i, base + (i + 1) % segs, top))
    return verts, faces


def sphere(name, rx, ry, rz, X, Y, Z, m, segs=16, rings=10, ry_rot=0.0):
    """Ellipsoid with radii in three axes (rx: X, ry: Y up, rz: Z)."""
    v, f = uv_sphere_data(rx, rz, ry, segs, rings)
    o = mesh_obj(name, v, f, m, smooth=True)
    place(o, X, Y, Z, ry=ry_rot)
    return o


def join(objs, name, bake=True):
    """Join objects (keeping materials) into one, named `name`. With bake=False
    the first object's transform is kept (the others are re-expressed in it)."""
    objs = [o for o in objs if o is not None]
    if not objs:
        return None
    apply_modifiers(objs)
    ctx = bpy.context
    for o in ctx.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    ctx.view_layer.objects.active = objs[0]
    with ctx.temp_override(active_object=objs[0], selected_editable_objects=objs, selected_objects=objs):
        bpy.ops.object.join()
    o = ctx.view_layer.objects.active
    o.name = name
    o.data.name = name
    if bake:
        apply_transform(o, loc=True)
    return o


def apply_modifiers(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        if o.type != "MESH" or not o.modifiers:
            continue
        ev = o.evaluated_get(dg)
        me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
        old = o.data
        o.modifiers.clear()
        o.data = me
        me.name = o.name
        if old.users == 0:
            bpy.data.meshes.remove(old)


def apply_transform(o, loc=False):
    """Bake rotation/scale (and optionally location) into the mesh."""
    M = o.matrix_basis.copy()
    if loc:
        o.data.transform(M)
        o.matrix_basis = Matrix.Identity(4)
    else:
        L, R, S = M.decompose()
        RS = R.to_matrix().to_4x4() @ Matrix.Diagonal(S.to_4d())
        o.data.transform(RS)
        o.matrix_basis = Matrix.Translation(L)
    o.data.update()


def box_uv(o, size=1.0, rot90=False):
    """World-scale box projection of UVMap (1 UV unit = `size` metres)."""
    me = o.data
    if "UVMap" not in me.uv_layers:
        me.uv_layers.new(name="UVMap")
    uvl = me.uv_layers["UVMap"]
    mw = o.matrix_basis  # matrix_world is stale until the depsgraph re-evaluates
    nm = mw.to_3x3().inverted().transposed()
    for poly in me.polygons:
        n = (nm @ poly.normal).normalized()
        ax = max(range(3), key=lambda i: abs(n[i]))
        for li in poly.loop_indices:
            p = mw @ me.vertices[me.loops[li].vertex_index].co
            if ax == 0:
                u, v = p.y, p.z
            elif ax == 1:
                u, v = p.x, p.z
            else:
                u, v = p.x, p.y
            if rot90:
                u, v = v, u
            uvl.data[li].uv = (u / size, v / size)


def planar_uv(o, axis_u, axis_v, size_u, size_v, off_u=0.0, off_v=0.0):
    """UVMap from two Blender world axes (0,1,2) normalised to [0,1]."""
    me = o.data
    if "UVMap" not in me.uv_layers:
        me.uv_layers.new(name="UVMap")
    uvl = me.uv_layers["UVMap"]
    mw = o.matrix_basis  # matrix_world is stale until the depsgraph re-evaluates
    for li, loop in enumerate(me.loops):
        p = mw @ me.vertices[loop.vertex_index].co
        uvl.data[li].uv = ((p[axis_u] - off_u) / size_u, (p[axis_v] - off_v) / size_v)


def grid_data(nu, nv, fn):
    """Grid surface: fn(u, v) -> (x, y, z), u,v in [0,1]. Returns verts, faces."""
    verts, faces = [], []
    for j in range(nv + 1):
        for i in range(nu + 1):
            verts.append(tuple(fn(i / nu, j / nv)))
    W = nu + 1
    for j in range(nv):
        for i in range(nu):
            a = j * W + i
            faces.append((a, a + 1, a + 1 + W, a + W))
    return verts, faces


def grid_uv(o, nu, nv, su=1.0, sv=1.0):
    """UVMap for a grid_data mesh (u, v scaled)."""
    me = o.data
    if "UVMap" not in me.uv_layers:
        me.uv_layers.new(name="UVMap")
    uvl = me.uv_layers["UVMap"]
    W = nu + 1
    for li, loop in enumerate(me.loops):
        vi = loop.vertex_index
        i, j = vi % W, vi // W
        uvl.data[li].uv = (i / nu * su, j / nv * sv)
