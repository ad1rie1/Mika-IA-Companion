# Les états de la couette (et du plaid) du lit de Mika, simulés en tissu et livrés en FBX à formes (shape keys).
#
#   blender -b --factory-startup --python frontend/assets-src/blender/duvet_states.py -- \
#       [--poses UnityFrontend/Mika/Temp/lab/poses] [--out UnityFrontend/Mika/Assets/Mika/Art/Room/Models/furniture]
#
# La couette du lit est une simulation (cloth.build_bed_cloth) : un drap de 48 × 72 carreaux, retombé sur le
# matelas, puis épaissi. On rejoue la même simulation depuis d'autres départs — même grille, même épaisseur, donc
# exactement les mêmes sommets dans le même ordre — et chaque résultat devient une forme de la couette faite :
#
#   Faite (base)        le lit fait, comme dans la chambre exportée ;
#   Ouverte             repliée vers le pied du lit (on va se coucher, on vient de se lever) ;
#   Couverte_Dos        retombée sur Mika allongée sur le dos, jusqu'aux épaules, bord retourné ;
#   Couverte_Gauche     … sur le côté gauche ;
#   Couverte_Droite     … sur le côté droit.
#
# Le corps de Mika vient d'Unity (AnimLab.ExportPose : OBJ déjà en coordonnées Blender de la chambre, une pose par
# position couchée). Le plaid, posé sur la couette au pied du lit, est resimulé sur chaque forme.
#
# Sortie : duvet.fbx et throw.fbx (origine = origine de la chambre, mêmes options FBX que export_unity.py) ; Unity
# retire la couette et le plaid du maillage du lit et pose ces deux-là à la place (Mika › Art › Couette).
import argparse
import math
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)

import roomlib  # noqa: E402
import materials  # noqa: E402
import build_bed  # noqa: E402
import cloth  # noqa: E402
from roomlib import V  # noqa: E402

FBX_OPTIONS = dict(
    use_selection=True, object_types={"MESH"},
    axis_forward="-Z", axis_up="Y", bake_space_transform=True,
    apply_scale_options="FBX_SCALE_UNITS", add_leaf_bones=False,
    use_mesh_modifiers=False, mesh_smooth_type="FACE",
    path_mode="STRIP", embed_textures=False, bake_anim=False, use_custom_props=False,
)

# La même géométrie que cloth.build_bed_cloth : ne pas la modifier sans elle.
BX, BZ = -3.35, 1.3
Y0 = 0.47
R = 0.028
L_MAIN, L_FOLD = 1.6, 0.34
Z_START = 0.12
L_TOT = L_MAIN + math.pi * R + L_FOLD
W = 1.45
XC = BX + 0.1
NU, NV = 48, 72

# La tête et le cou au-dessus des épaules, pour Mika (1,45 m) : le bord de la couette s'arrête là.
HEAD_AND_NECK = 0.36


def folded(z_start, y0, l_main, fold=L_FOLD, height=None):
    """
    Un drap posé de z_start à z_start + l_main, puis retourné sur lui-même vers le pied. <height>(x, z), si
    donnée, soulève le drap au-dessus de ce qu'il recouvre (le corps) : il part de sa forme et n'a qu'à retomber.
    """
    rest = L_TOT - l_main - math.pi * R

    def lift(x, z):
        return max(y0, height(x, z)) if height is not None else y0

    def fn(u, v):
        x = XC - W / 2 + W * u
        s = v * L_TOT
        if s <= l_main:
            z = z_start + s
            y = lift(x, z)
        elif s <= l_main + math.pi * R:
            th = (s - l_main) / R
            z = z_start + l_main + R * math.sin(th)
            y = lift(x, z_start + l_main) + R * (1 - math.cos(th))
        else:
            z = z_start + l_main - (s - l_main - math.pi * R)
            y = lift(x, z) + 2 * R
        return V(x, y, z)

    return fn, rest


def height_field(body, margin=0.045, cell=0.02, grow=4, blur=3):
    """
    La silhouette du corps vue de dessus : pour chaque case de 2 cm, la hauteur la plus haute du corps, élargie
    et adoucie (un drap ne suit pas chaque doigt), plus une marge. Coordonnées de la chambre (glTF : y en haut).
    """
    import numpy as np
    x0, x1 = XC - W / 2 - 0.1, XC + W / 2 + 0.1
    z0, z1 = -0.2, 2.7
    nx, nz = int((x1 - x0) / cell) + 1, int((z1 - z0) / cell) + 1
    h = np.full((nz, nx), -1.0)
    mw = body.matrix_world
    for v in body.data.vertices:
        w = mw @ v.co
        gx, gy, gz = w.x, w.z, -w.y          # Blender → glTF (V inverse)
        ix, iz = int((gx - x0) / cell), int((gz - z0) / cell)
        if 0 <= ix < nx and 0 <= iz < nz and gy > h[iz, ix]:
            h[iz, ix] = gy
    for _ in range(grow):                    # élargir : le drap déborde du corps
        h = np.maximum.reduce([h, np.roll(h, 1, 0), np.roll(h, -1, 0), np.roll(h, 1, 1), np.roll(h, -1, 1)])
    for _ in range(blur):                    # adoucir
        h = (h + np.roll(h, 1, 0) + np.roll(h, -1, 0) + np.roll(h, 1, 1) + np.roll(h, -1, 1)) / 5.0

    def height(x, z):
        ix = min(max(int((x - x0) / cell), 0), nx - 1)
        iz = min(max(int((z - z0) / cell), 0), nz - 1)
        return h[iz, ix] + margin if h[iz, ix] > 0 else -1.0

    return height


def tmp_planes():
    wall = roomlib.mesh_obj("Tmp_Wall", [V(-4.0, 0, -1), V(-4.0, 0, 3.4), V(-4.0, 1.2, 3.4), V(-4.0, 1.2, -1)], [(0, 1, 2, 3)])
    if wall.data.polygons[0].normal.x < 0:
        wall.data.flip_normals()
    floor = roomlib.mesh_obj("Tmp_Floor", [V(-5, 0, -1), V(-1, 0, -1), V(-1, 0, 4), V(-5, 0, 4)], [(0, 1, 2, 3)])
    if floor.data.polygons[0].normal.z < 0:
        floor.data.flip_normals()
    return [wall, floor]


def import_pose(path, name):
    """Le corps posé (OBJ en coordonnées Blender), allégé pour servir de collision."""
    before = set(bpy.data.objects)
    bpy.ops.wm.obj_import(filepath=path, forward_axis="Y", up_axis="Z")
    parts = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in parts:
        o.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    if len(parts) > 1:
        bpy.ops.object.join()
    body = bpy.context.view_layer.objects.active
    body.name = name
    # Une enveloppe lisse et fermée : remaillée en voxels de 2,5 cm (les mèches fines, les rubans, les doigts
    # disparaissent — un drap ne s'y accroche pas), lissée, allégée.
    rem = body.modifiers.new("Enveloppe", "REMESH")
    rem.mode = "VOXEL"
    rem.voxel_size = 0.025
    smo = body.modifiers.new("Lisse", "SMOOTH")
    smo.factor = 0.6
    smo.iterations = 6
    roomlib.apply_modifiers([body])
    dec = body.modifiers.new("Decimate", "DECIMATE")
    dec.ratio = 0.35
    roomlib.apply_modifiers([body])
    # Un peu d'épaisseur : la couette ne colle pas à la peau, elle repose sur les vêtements et le volume du corps.
    disp = body.modifiers.new("Gonfle", "DISPLACE")
    disp.strength = 0.012
    roomlib.apply_modifiers([body])
    print(f"[couette] corps {name} : {len(body.data.polygons)} faces")
    return body


def fix_spikes(o, limit=0.07, passes=4):
    """
    Une simulation de tissu laisse parfois partir quelques sommets (coincés contre une mèche de cheveux, une
    main) : ils deviennent des pointes de plusieurs mètres. Tout sommet trop loin de la moyenne de ses voisins y
    est ramené ; la grille est régulière (≈3 cm), un vrai pli n'en est jamais à 7 cm.
    """
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(o.data)
    fixed = 0
    for _ in range(passes):
        moved = 0
        for v in bm.verts:
            ns = [e.other_vert(v).co for e in v.link_edges]
            if not ns:
                continue
            mean = sum(ns, v.co * 0) / len(ns)
            if (v.co - mean).length > limit:
                v.co = mean
                moved += 1
        fixed += moved
        if moved == 0:
            break
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    if fixed:
        print(f"[couette] {o.name} : {fixed} sommets aberrants ramenés")


def sim_duvet(name, fn, colliders, frames, M, bending=6.0):
    o = cloth.grid_obj(name, NU, NV, fn, M["duvet"], W / 0.4, L_TOT / 0.4)
    cloth.simulate(o, colliders, frames, mass=0.45, tension=18, bending=bending, self_col=True, quality=7,
                   col_dist=0.008, friction=40)
    fix_spikes(o)
    cloth.solidify(o, 0.03, 0.0)
    roomlib.apply_modifiers([o])
    # L'épaisseur « uniforme » projette au loin les sommets d'un pli très serré : on les ramène aussi.
    fix_spikes(o, limit=0.08, passes=6)
    o.data.shade_smooth()
    return o


def sim_throw(name, colliders, M):
    tw, tl = 1.35, 0.55

    def fn2(u, v):
        return V(-3.1 - tw / 2 + tw * u, 0.72, 0.22 + tl * v)

    o = cloth.grid_obj(name, 40, 16, fn2, M["throw"], tw / 0.3, tl / 0.3)
    cloth.simulate(o, colliders, 50, mass=0.25, tension=12, bending=0.6, quality=6, col_dist=0.006, friction=40)
    fix_spikes(o)
    cloth.solidify(o, 0.008, 0.0)
    roomlib.apply_modifiers([o])
    fix_spikes(o, limit=0.06, passes=6)
    return o


def add_key(base, name, source):
    if len(base.data.vertices) != len(source.data.vertices):
        raise RuntimeError(f"{name} : {len(source.data.vertices)} sommets au lieu de {len(base.data.vertices)}")
    if base.data.shape_keys is None:
        base.shape_key_add(name="Faite", from_mix=False)
    key = base.shape_key_add(name=name, from_mix=False)
    for i, v in enumerate(source.data.vertices):
        key.data[i].co = v.co
    return key


def preview(folder, name, objs):
    """Un aperçu (Workbench) de la forme avec le corps : vue de côté depuis la chambre et vue de dessus."""
    os.makedirs(folder, exist_ok=True)
    sc = bpy.context.scene
    try:
        sc.render.engine = "BLENDER_WORKBENCH"
    except TypeError:
        pass
    sc.render.resolution_x, sc.render.resolution_y = 800, 500
    sc.display.shading.light = "STUDIO"
    sc.display.shading.color_type = "OBJECT"
    for o in objs:
        if o is not None and o.name.startswith("Tmp_Corps"):
            o.color = (0.95, 0.75, 0.7, 1)
    keep = {o.name for o in objs if o is not None}
    hidden = []
    for o in bpy.context.view_layer.objects:
        if o.type == "MESH" and o.name not in keep and not o.hide_render:
            o.hide_render = True
            hidden.append(o)
    cam_data = bpy.data.cameras.new("Tmp_Cam")
    cam = bpy.data.objects.new("Tmp_Cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    sc.camera = cam
    target = V(BX, 0.5, BZ + 0.3)
    for label, eye in (("cote", V(BX + 1.9, 1.3, BZ + 0.3)), ("dessus", V(BX, 2.6, BZ + 0.3001))):
        cam.location = eye
        d = target - eye
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = os.path.join(folder, f"{name}_{label}.png")
        bpy.ops.render.render(write_still=True)
    for o in hidden:
        o.hide_render = False
    bpy.data.objects.remove(cam, do_unlink=True)


def export(obj, path):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    os.makedirs(os.path.dirname(path), exist_ok=True)
    res = bpy.ops.export_scene.fbx(filepath=path, **FBX_OPTIONS)
    if "FINISHED" not in res:
        raise RuntimeError(f"export FBX échoué : {path}")
    print(f"[couette] écrit {path}")


def main(argv):
    ap = argparse.ArgumentParser(prog="duvet_states.py")
    ap.add_argument("--poses", default=os.path.join(REPO, "UnityFrontend", "Mika", "Temp", "lab", "poses"))
    ap.add_argument("--out", default=os.path.join(REPO, "UnityFrontend", "Mika", "Assets", "Mika", "Art", "Room", "Models", "furniture"))
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--preview", default=None, help="dossier où rendre un aperçu de chaque forme")
    args = ap.parse_args(argv)
    t0 = time.time()

    roomlib.clear_scene()
    M = materials.make_all()
    build_bed.build(M)
    duvet, throw = cloth.build_bed_cloth(M)          # la couette faite et son plaid : les bases
    print(f"[couette] lit et couette faite en {time.time() - t0:.0f} s ({len(duvet.data.vertices)} sommets)")

    bed = [bpy.data.objects.get(n) for n in ("Bed_Mattress", "Bed_Frame", "Bed_Pillow", "Bed_Cushion")]
    plush = [o for o in bpy.data.objects if o.name.startswith("Plush") or o.name == "Bed_Plushie"]

    # Ouverte : repliée en deux vers le pied du lit, le pli au milieu du lit et rien qui dépasse au pied (sinon
    # le poids qui pend entraîne tout par terre) : les jambes ont la place de se glisser dessous.
    fn, _ = folded(BZ + 0.01 - 1.0, Y0, 1.02)
    walls = tmp_planes()
    open_ = sim_duvet("Tmp_Ouverte", fn, bed + plush + walls, args.frames, M)
    if args.preview:
        preview(args.preview, "Ouverte", [open_] + bed)
    add_key(duvet, "Ouverte", open_)
    t_open = sim_throw("Tmp_Plaid_Ouverte", bed + walls + [open_], M)
    add_key(throw, "Ouverte", t_open)
    print(f"[couette] ouverte ({time.time() - t0:.0f} s)")

    for side, name in ((0, "Couverte_Dos"), (1, "Couverte_Gauche"), (2, "Couverte_Droite")):
        path = os.path.join(args.poses, f"lie{side}.obj")
        if not os.path.exists(path):
            print(f"[couette] pas de pose {path} : {name} sautée")
            continue
        body = import_pose(path, f"Tmp_Corps_{side}")
        # Le bord retourné arrive aux épaules — mesurées sur le corps : le sommet de la tête (le point le plus
        # avancé vers la tête du lit, −Y en Blender) moins la tête et le cou. On lâche le drap de plus haut pour
        # qu'il retombe sur elle.
        head_top = max(-(body.matrix_world @ v.co).y for v in body.data.vertices)
        shoulders = head_top - HEAD_AND_NECK
        print(f"[couette] {name} : tête à z={head_top:.2f}, bord à z={shoulders:.2f}")
        fn, _ = folded(shoulders - L_MAIN, Y0 + 0.03, L_MAIN, height=height_field(body))
        # Sur un corps, le tissu a besoin de plus de temps et d'un peu plus de souplesse pour se poser (sinon il
        # reste « en tente » le long des flancs).
        cov = sim_duvet(f"Tmp_{name}", fn, bed + walls + [body], args.frames + 40, M, bending=3.5)
        if args.preview:
            preview(args.preview, name, [cov, body] + bed)
        add_key(duvet, name, cov)
        t_cov = sim_throw(f"Tmp_Plaid_{name}", bed + walls + [cov], M)
        add_key(throw, name, t_cov)
        print(f"[couette] {name} ({time.time() - t0:.0f} s)")

    duvet.name, throw.name = "Couette", "Plaid"
    export(duvet, os.path.join(args.out, "duvet.fbx"))
    export(throw, os.path.join(args.out, "throw.fbx"))
    print(f"[couette] terminé en {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
