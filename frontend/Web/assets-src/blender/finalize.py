# Finalize: apply modifiers, second UV map (lightmap layout), Cycles AO bake into
# one shared 2048 atlas, glTF occlusion wiring (UV 2), export GLB + save .blend.
import math, os, time
import bpy, bmesh
import numpy as np
from mathutils import Vector
from roomlib import *

ATLAS = 2048
AO_PATH = TEXDIR + "/room_ao.png"
GLB = FRONT + "/public/models/room.glb"
BLEND = FRONT + "/assets-src/room.blend"
# Objects whose transform must survive export (the code moves them).
KEEP_TRANSFORM = {"DeskChair", "Clock_HourHand", "Clock_MinuteHand"}
SHELL_SCALE = 0.55      # walls/floor/ceiling get coarser AO texels


def room_meshes():
    return [o for o in collection().objects if o.type == "MESH"]


def is_baked(o):
    return any(s.material is not None and s.material.get("ao", False) for s in o.material_slots)


def prepare_meshes():
    objs = room_meshes()
    apply_modifiers(objs)
    for o in objs:
        if o.name not in KEEP_TRANSFORM:
            apply_transform(o, loc=False)
        me = o.data
        if "UVMap" not in me.uv_layers:
            box_uv(o, 0.5)
        # UVMap must be first (TEXCOORD_0), AO second (TEXCOORD_1)
        if me.uv_layers[0].name != "UVMap":
            raise RuntimeError(f"{o.name}: first UV layer is {me.uv_layers[0].name}")
        for extra in [l for l in me.uv_layers if l.name not in ("UVMap", "AO")]:
            me.uv_layers.remove(extra)
        me.uv_layers.active_index = 0
        me.uv_layers["UVMap"].active_render = True
    return objs


def _area3d(o):
    M = o.matrix_basis
    return sum((M.to_3x3() @ (o.data.vertices[p.vertices[1]].co - o.data.vertices[p.vertices[0]].co)).length * 0 + p.area for p in o.data.polygons)


def unwrap_ao(objs):
    ctx = bpy.context
    for o in objs:
        me = o.data
        if "AO" not in me.uv_layers:
            me.uv_layers.new(name="AO")
        me.uv_layers.active = me.uv_layers["AO"]
    for o in ctx.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    ctx.view_layer.objects.active = objs[0]
    area = next((a for a in ctx.screen.areas if a.type == "VIEW_3D"), None)
    region = next((r for r in area.regions if r.type == "WINDOW"), None) if area else None
    ov = dict(area=area, region=region, active_object=objs[0], selected_objects=objs, selected_editable_objects=objs,
              objects_in_edit_mode=objs)
    with ctx.temp_override(**ov):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.0, area_weight=0.0,
                                 correct_aspect=True, scale_to_bounds=False)
        bpy.ops.uv.select_all(action="SELECT")
        bpy.ops.uv.average_islands_scale()
        bpy.ops.object.mode_set(mode="OBJECT")
    # coarser texels for the big shell surfaces
    for o in objs:
        if o.name.startswith("Shell_"):
            uvl = o.data.uv_layers["AO"]
            for d in uvl.data:
                d.uv = d.uv * SHELL_SCALE
    with ctx.temp_override(**ov):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.select_all(action="SELECT")
        kw = dict(rotate=True, scale=True, margin=0.0025)
        props = bpy.ops.uv.pack_islands.get_rna_type().properties
        if "margin_method" in props:
            kw["margin_method"] = enum_ok_op(props["margin_method"], "FRACTION")
        if "shape_method" in props:
            kw["shape_method"] = enum_ok_op(props["shape_method"], "CONCAVE")
        bpy.ops.uv.pack_islands(**kw)
        bpy.ops.object.mode_set(mode="OBJECT")


def enum_ok_op(prop, value):
    """Validate against RNA when it lists the items (some operator enums are
    dynamic and report none; then the operator itself validates)."""
    items = [i.identifier for i in prop.enum_items]
    if not items or value in items:
        return value
    return items[0]


def bake_ao(objs, samples=192, distance=0.55, name="RoomAO", fill=(1.0, 1.0, 1.0, 1.0)):
    """One bake call for all `objs` into image `name`, pre-filled with `fill`
    (a second bake call into the same generated image does not preserve it)."""
    sc = bpy.context.scene
    img = bpy.data.images.get(name)
    if img is None:
        img = bpy.data.images.new(name, ATLAS, ATLAS, alpha=True)
    img.colorspace_settings.name = "Non-Color"
    img.pixels.foreach_set(np.tile(np.array(fill, np.float32), ATLAS * ATLAS))
    clear = False
    mats = {s.material for o in objs for s in o.material_slots if s.material}
    for m in mats:
        nt = m.node_tree
        n = next((x for x in nt.nodes if x.type == "TEX_IMAGE" and x.image == img), None)
        if n is None:
            n = nt.nodes.new("ShaderNodeTexImage")
            n.image = img
            n.location = (-650, -650)
            n.name = "AO_Bake"
        nt.nodes.active = n
        n.select = True
    for o in objs:
        o.data.uv_layers.active = o.data.uv_layers["AO"]
    try:
        sc.render.engine = "CYCLES"
    except TypeError:
        pass
    cy = sc.cycles
    cy.samples = samples
    # CPU on purpose: the CUDA bake on this machine silently writes black.
    cy.device = "CPU"
    if sc.world is None:
        sc.world = bpy.data.worlds.new("World")
    sc.world.light_settings.distance = distance
    bk = sc.render.bake
    bk.margin = 8
    bk.use_clear = clear
    bk.target = enum_ok(bk, "target", "IMAGE_TEXTURES")
    ctx = bpy.context
    for o in ctx.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    ctx.view_layer.objects.active = objs[0]
    t = time.time()
    with ctx.temp_override(active_object=objs[0], selected_objects=objs, selected_editable_objects=objs):
        bpy.ops.object.bake(type="AO", margin=8, use_clear=clear)
    print("bake", round(time.time() - t, 1), "s on", cy.device)
    for o in objs:
        o.data.uv_layers.active_index = 0
    return img


def bake_all(objs, samples=192):
    """Two passes: the movable chair must not leave its contact shadow baked
    into the floor (it slides back when she sits), but it gets its own AO."""
    sc = bpy.context.scene
    hidden = []
    for o in bpy.data.objects:
        if o.name.startswith("Preview_") and not o.hide_render:
            o.hide_render = True
            hidden.append(o)
    chair = bpy.data.objects.get("DeskChair")
    static = [o for o in objs if o is not chair]
    if chair:
        chair.hide_render = True
    img = bake_ao(static, samples)
    if chair:
        chair.hide_render = False
        # chair pass into its own image (red = untouched), composited below
        cimg = bake_ao([chair], samples, name="RoomAO_Chair", fill=(1.0, 0.0, 0.0, 1.0))
        A = np.empty(ATLAS * ATLAS * 4, np.float32)
        B = np.empty(ATLAS * ATLAS * 4, np.float32)
        img.pixels.foreach_get(A)
        cimg.pixels.foreach_get(B)
        A = A.reshape(-1, 4)
        B = B.reshape(-1, 4)
        mask = np.abs(B[:, 0] - B[:, 1]) < 0.5
        A[mask] = B[mask]
        img.pixels.foreach_set(A.ravel())
        print("chair texels", int(mask.sum()))
        for m in {s.material for s in chair.material_slots if s.material}:
            for n in list(m.node_tree.nodes):
                if n.type == "TEX_IMAGE" and n.image == cimg:
                    m.node_tree.nodes.remove(n)
        bpy.data.images.remove(cimg)
    for o in hidden:
        o.hide_render = False
    return img


def postprocess_ao(img):
    """Gentle denoise + remap: the baked AO only darkens indirect light in
    three.js, so keep contact shadows but never crush to black."""
    a = np.array(img.pixels[:], dtype=np.float32).reshape(ATLAS, ATLAS, 4)
    g = a[..., 0]
    # 3x3 box blur restricted to baked texels (margin pixels are baked too)
    pad = np.pad(g, 1, mode="edge")
    blur = sum(pad[1 + dy:1 + dy + ATLAS, 1 + dx:1 + dx + ATLAS] for dy in (-1, 0, 1) for dx in (-1, 0, 1)) / 9.0
    g = 0.5 * g + 0.5 * blur
    g = np.clip(0.12 + 0.88 * g ** 0.9, 0, 1)
    a[..., 0] = a[..., 1] = a[..., 2] = g
    a[..., 3] = 1.0
    img.pixels.foreach_set(a.ravel())
    img.filepath_raw = AO_PATH
    img.file_format = "PNG"
    img.save()
    return img


def gltf_group():
    g = bpy.data.node_groups.get("glTF Material Output")
    if g is None:
        try:
            from io_scene_gltf2.blender.com.material_helpers import create_settings_group
            g = create_settings_group("glTF Material Output")
        except Exception:
            g = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
            g.interface.new_socket("Occlusion", socket_type="NodeSocketFloat")
            g.nodes.new("NodeGroupInput")
            g.nodes.new("NodeGroupOutput")
    return g


def wire_occlusion(objs, img):
    grp = gltf_group()
    mats = {s.material for o in objs for s in o.material_slots if s.material}
    for m in mats:
        nt = m.node_tree
        bake_node = next((x for x in nt.nodes if x.type == "TEX_IMAGE" and x.image == img), None)
        for n in list(nt.nodes):
            if n.name in ("AO_UV", "AO_Sep", "AO_glTF"):
                nt.nodes.remove(n)
        if not m.get("ao", False):
            if bake_node:
                nt.nodes.remove(bake_node)
            continue
        if bake_node is None:
            bake_node = nt.nodes.new("ShaderNodeTexImage")
            bake_node.image = img
            bake_node.name = "AO_Bake"
            bake_node.location = (-650, -650)
        uv = nt.nodes.new("ShaderNodeUVMap")
        uv.name = "AO_UV"
        uv.uv_map = "AO"
        uv.location = (-900, -650)
        nt.links.new(uv.outputs["UV"], bake_node.inputs["Vector"])
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        sep.name = "AO_Sep"
        sep.location = (-350, -650)
        nt.links.new(bake_node.outputs["Color"], sep.inputs[0])
        gn = nt.nodes.new("ShaderNodeGroup")
        gn.name = "AO_glTF"
        gn.node_tree = grp
        gn.location = (-100, -650)
        nt.links.new(sep.outputs[0], gn.inputs["Occlusion"])
        # keep the base colour texture as the active node (viewport/exporter defaults)
        nt.nodes.active = principled(m)


def export(objs_extra=()):
    ctx = bpy.context
    room = list(collection().objects)
    for o in ctx.view_layer.objects:
        o.select_set(False)
    for o in room:
        o.select_set(True)
    ctx.view_layer.objects.active = room[0]
    props = bpy.ops.export_scene.gltf.get_rna_type().properties
    kw = dict(filepath=GLB, use_selection=True, export_apply=True, export_yup=True,
              export_texcoords=True, export_normals=True, export_lights=False, export_cameras=False,
              export_extras=False, export_animations=False, export_jpeg_quality=82)
    kw["export_format"] = enum_ok_op(props["export_format"], "GLB")
    kw["export_image_format"] = enum_ok_op(props["export_image_format"], "JPEG")
    if "export_materials" in props:
        kw["export_materials"] = enum_ok_op(props["export_materials"], "EXPORT")
    if "export_tangents" in props:
        kw["export_tangents"] = False
    with ctx.temp_override(selected_objects=room, active_object=room[0]):
        bpy.ops.export_scene.gltf(**kw)
    return os.path.getsize(GLB)


def save_blend():
    os.makedirs(os.path.dirname(BLEND), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, relative_remap=True, compress=True, copy=True)
