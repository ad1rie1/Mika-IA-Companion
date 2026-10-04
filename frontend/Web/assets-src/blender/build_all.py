# Rebuilds the whole room from scratch. In Blender's Python console:
#   BLENDER_SCRIPTS_DIR = "/path/to/frontend/Web/assets-src/blender"
#   exec(open(BLENDER_SCRIPTS_DIR + "/build_all.py").read())
import os, sys, importlib, time
P = BLENDER_SCRIPTS_DIR if "BLENDER_SCRIPTS_DIR" in globals() else os.path.dirname(os.path.abspath(__file__))
if P not in sys.path:
    sys.path.insert(0, P)
import roomlib, materials, build_shell, build_desk, build_bed, build_shelves, build_plants, build_misc, cloth, preview
for m in (roomlib, materials, build_shell, build_desk, build_bed, build_shelves, build_plants, build_misc, cloth, preview):
    importlib.reload(m)

t0 = time.time()
roomlib.clear_scene()
M = materials.make_all()
build_shell.build(M)
build_desk.build(M)
build_desk.build_chair(M)
build_bed.build(M)
build_shelves.build(M)
build_plants.build(M)
build_misc.build(M)
cloth.build_bed_cloth(M)
cloth.build_hoodie(M)
preview.setup()
print("built in", round(time.time() - t0, 1), "s")
