# Full pipeline: build -> second UV -> AO bake (Cycles, CPU) -> glTF wiring ->
# export public/models/room.glb -> save assets-src/room.blend.
# In Blender's Python console:
#   BLENDER_SCRIPTS_DIR = "/path/to/frontend/assets-src/blender"
#   exec(open(BLENDER_SCRIPTS_DIR + "/run_final.py").read())
import os
_dir = BLENDER_SCRIPTS_DIR if "BLENDER_SCRIPTS_DIR" in globals() else os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(_dir, "build_all.py")).read())
import finalize
importlib.reload(finalize)
SAMPLES = globals().get("SAMPLES", 128)
t = time.time()
objs = finalize.prepare_meshes()
baked = [o for o in objs if finalize.is_baked(o)]
finalize.unwrap_ao(baked)
img = finalize.bake_all(baked, samples=SAMPLES)
finalize.postprocess_ao(img)
finalize.wire_occlusion(baked, img)
size = finalize.export()
finalize.save_blend()
tris = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in objs)
print("final: tris", tris, "glb bytes", size, "time", round(time.time() - t, 1))
