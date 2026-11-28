# Preview rig (NOT exported): Mika stand-in, camera at the three.js default pose,
# Blender lights mirroring Environment.ts (glTF "compat" units: P = 4*pi*I).
import bpy, math
from mathutils import Vector
from roomlib import V, col, enum_ok, mesh_obj, uv_sphere_data, lathe_data, mat

SHOTS = "/tmp/mika-room-shots"


def pcoll():
    c = bpy.data.collections.get("Preview")
    if c is None:
        c = bpy.data.collections.new("Preview")
        bpy.context.scene.collection.children.link(c)
    return c


def _obj(name, data):
    o = bpy.data.objects.get(name)
    if o:
        bpy.data.objects.remove(o, do_unlink=True)
    o = bpy.data.objects.new(name, data)
    pcoll().objects.link(o)
    return o


def point(name, hexc, intensity, pos, radius=0.05):
    L = bpy.data.lights.new(name, enum_ok(bpy.types.Light, "type", "POINT"))
    L.energy = 4 * math.pi * intensity
    L.color = col(hexc)[:3]
    L.shadow_soft_size = radius
    o = _obj(name, L)
    o.location = V(*pos)
    return o


def sun(name, hexc, intensity, pos, target, shadow=True):
    L = bpy.data.lights.new(name, enum_ok(bpy.types.Light, "type", "SUN"))
    L.energy = intensity
    L.color = col(hexc)[:3]
    L.use_shadow = shadow
    L.angle = math.radians(3)
    o = _obj(name, L)
    p, t = V(*pos), V(*target)
    o.location = p
    o.rotation_euler = (t - p).to_track_quat("-Z", "Y").to_euler()
    return o


def setup():
    for o in list(pcoll().objects):
        bpy.data.objects.remove(o, do_unlink=True)
    sc = bpy.context.scene
    # Mika stand-in: 1.6 m capsule + head
    m = mat("M_PreviewMika", 0xf0d6e0, 0.6)
    v, f = lathe_data([(0, 0), (0.16, 0.02), (0.19, 0.6), (0.15, 1.0), (0.17, 1.3), (0.06, 1.38), (0, 1.4)], 24)
    body = _obj("Preview_Mika", bpy.data.meshes.new("Preview_Mika"))
    body.data.from_pydata(v, [], f)
    body.data.materials.append(m)
    body.location = V(0, 0, -0.5)
    hv, hf = uv_sphere_data(0.11, 0.11, 0.12, 20, 12)
    head = _obj("Preview_MikaHead", bpy.data.meshes.new("Preview_MikaHead"))
    head.data.from_pydata(hv, [], hf)
    head.data.materials.append(m)
    head.location = V(0, 1.48, -0.5)
    for o in (body, head):
        o.data.shade_smooth()
    # camera at the three.js default pose (fov 50 deg vertical)
    cd = bpy.data.cameras.new("Preview_Cam")
    cd.sensor_fit = enum_ok(cd, "sensor_fit", "VERTICAL")
    cd.angle_y = math.radians(50)
    cd.clip_start = 0.05
    cam = _obj("Preview_Cam", cd)
    sc.camera = cam
    aim(cam, (0, 1.35, 2.1), (0, 1.15, -0.5))
    # lights
    sun("Preview_Key", 0xfff1e0, 0.75, (2.4, 3.2, 2.2), (0, 1.0, -0.5), True)
    sun("Preview_Rim", 0x8a9cff, 0.3, (-2.0, 2.4, -3.0), (0, 1.2, -0.5), False)
    point("Preview_Window", 0x27336b, 0.5, (-3.4, 1.8, -1.2), 0.3)
    point("Preview_Bed", 0xffc98a, 0.7, (-3.62, 0.74, 2.72))
    point("Preview_LedB", 0x6366f1, 0.6, (0, 2.9, -4.1), 0.3)
    point("Preview_LedF", 0x6366f1, 0.6, (0, 2.9, 3.1), 0.3)
    point("Preview_Ceiling", 0xffe6c8, 0.6, (0, 2.62, -0.5), 0.1)
    point("Preview_Desk", 0xffb066, 0.8, (-1.9, 1.2, -4.0))
    point("Preview_Monitor", 0x6366f1, 0.5, (-1.4, 1.25, -3.9), 0.2)
    # world = hemisphere + ambient fill (irradiance / pi)
    w = sc.world or bpy.data.worlds.new("World")
    sc.world = w
    try:
        w.use_nodes = True
    except Exception:
        pass
    bg = next(n for n in w.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value = (0.11, 0.11, 0.17, 1)
    bg.inputs["Strength"].default_value = 1.0
    sc.render.resolution_x = 1280
    sc.render.resolution_y = 720
    vs = sc.view_settings
    for vt in ("AgX", "Filmic", "Standard"):
        try:
            vs.view_transform = vt
            break
        except TypeError:
            continue
    vs.exposure = 0.3
    return cam


def aim(cam, pos, target):
    p, t = V(*pos), V(*target)
    cam.location = p
    cam.rotation_euler = (t - p).to_track_quat("-Z", "Y").to_euler()


def orbit(cam, theta_deg, phi_deg, r, target=(0, 1.15, -0.5)):
    """three.js OrbitControls spherical: theta around Y from +Z, phi from +Y."""
    th, ph = math.radians(theta_deg), math.radians(phi_deg)
    x = target[0] + r * math.sin(ph) * math.sin(th)
    y = target[1] + r * math.cos(ph)
    z = target[2] + r * math.sin(ph) * math.cos(th)
    aim(cam, (x, y, z), target)


def render(name, hide_mika=False):
    import os
    os.makedirs(SHOTS, exist_ok=True)
    sc = bpy.context.scene
    for n in ("Preview_Mika", "Preview_MikaHead"):
        o = bpy.data.objects.get(n)
        if o:
            o.hide_render = hide_mika
    try:
        sc.render.engine = "BLENDER_EEVEE"
    except TypeError:
        pass
    sc.render.image_settings.file_format = enum_ok(sc.render.image_settings, "file_format", "JPEG")
    sc.render.filepath = f"{SHOTS}/{name}.jpg"
    bpy.ops.render.render(write_still=True)
    return sc.render.filepath
