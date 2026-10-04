# Mika animée en 2D : des boucles et des transitions pré-rendues, pour l'application Android (et son labo dans Chrome).
#
# Un portrait fixe ne bouge pas assez : la propriétaire veut l'effet de la 3D — les mains, la tête, le corps qui vivent,
# des transitions d'un état à l'autre — avec des images. On rend donc, avec le même visage et le même cadrage que
# `portraits.py`, de courts clips d'images :
#   - une **boucle** par état (le corps d'un « idle » de l'atelier, qui respire, se balance, cligne) ;
#   - pour un geste : une **entrée** (le vrai mouvement capturé, de la position de repos à la pose), une **tenue** (la pose
#     gardée, animée par la respiration et le balancement d'un idle, ajoutés par-dessus comme le fait le web) et une
#     **sortie** (le reste du geste quand il revient au repos, sinon un fondu de pose vers le repos) ;
#   - un geste **ponctuel** (coucou, surprise) : joué une fois, puis l'état reprend.
# Le visage arrive avec l'entrée et repart avec la sortie (rampe d'intensité). Les clignements sont rendus dans les
# boucles. Le lecteur (labo web, puis l'app) enchaîne les clips et fond les images entre elles.
#
#   blender -b frontend/Unity/ArtSource/atelier/mika_rig.blend --python frontend/Web/assets-src/blender/portrait_loops.py -- \
#       [--only neutral,thinking] [--out dossier]
#
# Sortie (non versionnée, comme les portraits) : <out>/<clip>/NNN.webp + <out>/manifest.json (version 2).
import argparse
import json
import math
import sys
import time
from pathlib import Path

import bpy
from mathutils import Quaternion

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portraits as pt  # noqa: E402

al = pt.al
OUT = al.REPO / "frontend/Android/avatar-lab/out"
SIZE = (720, 960)
QUALITY = 80

# Les clips. kind : loop (un idle entier, en boucle), segment (des images d'un mouvement, de start à end), hold (la
# pose `frame` d'un geste animée par l'idle `idle`), settle (de la pose `frame` vers le repos, par interpolation).
# step : une image sur `step` du mouvement (30 i/s) ; fps : la cadence de lecture ; ramp : in, out, inout.
CLIPS = {
    "neutral.loop": dict(kind="loop", motion="idle_breathing", step=3, fps=10, face="neutral", blinks=[14, 47, 81]),
    "happy.loop": dict(kind="loop", motion="idle_happy", step=3, fps=10, face="happy", blinks=[11]),
    "sad.loop": dict(kind="loop", motion="idle_sad", step=3, fps=10, face="sad", follow=0.5, blinks=[19]),
    "thinking.enter": dict(kind="segment", motion="gesture_think", start=0, end=81, step=2, fps=15, face="thinking", ramp="in"),
    "thinking.loop": dict(kind="hold", motion="gesture_think", frame=81, idle="idle_breathing", step=3, fps=10,
                          face="thinking", blinks=[22, 70]),
    "thinking.exit": dict(kind="segment", motion="gesture_think", start=81, end=127, step=2, fps=15, face="thinking", ramp="out"),
    "angry.enter": dict(kind="segment", motion="gesture_angry", start=0, end=90, step=2, fps=15, face="angry", ramp="in"),
    "angry.loop": dict(kind="hold", motion="gesture_angry", frame=90, idle="idle_breathing", step=3, fps=10,
                       face="angry", blinks=[30, 77]),
    "angry.exit": dict(kind="settle", motion="gesture_angry", frame=90, count=14, fps=15, face="angry", ramp="out"),
    "surprised.once": dict(kind="segment", motion="gesture_surprised", start=0, end=120, step=2, fps=15, face="surprised",
                           ramp="inout"),
    "wave.once": dict(kind="segment", motion="gesture_wave", start=0, end=142, step=2, fps=15, face="happy", ramp="inout",
                      intensity=0.85),
    "sleep.loop": dict(kind="loop", motion="idle_breathing", step=3, fps=10, face="neutral", intensity=0.0, tired=0.6,
                       blink=1.0, follow=0.0, head=(0.12, 0.16, 0.0)),
}

# Les états, ce que le lecteur demande : une boucle, et pour un geste son entrée et sa sortie ; un geste ponctuel
# (once) se joue puis rend la main à l'état d'avant.
STATES = {
    "neutral": {"loop": "neutral.loop"},
    "happy": {"loop": "happy.loop"},
    "sad": {"loop": "sad.loop"},
    "thinking": {"enter": "thinking.enter", "loop": "thinking.loop", "exit": "thinking.exit"},
    "angry": {"enter": "angry.enter", "loop": "angry.loop", "exit": "angry.exit"},
    "surprised": {"once": "surprised.once"},
    "wave": {"once": "wave.once"},
    "sleep": {"loop": "sleep.loop"},
}

DRIVERS = ("head", "neck", "chest", "spine", "hips")


def smoothstep(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def ramp(kind, t):
    if kind == "in":
        return smoothstep(0.0, 0.7, t)
    if kind == "out":
        return 1.0 - smoothstep(0.3, 1.0, t)
    if kind == "inout":
        return smoothstep(0.0, 0.2, t) * (1.0 - smoothstep(0.8, 1.0, t))
    return 1.0


def driver_of(rig):
    """Chaque os humanoïde → l'os « moteur » le plus proche parmi tête, cou, poitrine, colonne, hanches."""
    arm = rig.arm
    out = {}
    for h, name in rig.hmap.items():
        bone = arm.data.bones[name]
        while bone is not None:
            hb = rig.human_of.get(bone.name)
            if hb in DRIVERS:
                out[h] = hb
                break
            bone = bone.parent
        else:
            out[h] = "hips"
    return out


def hold_frames(rig, gesture, apex, idle, step):
    """
    La pose `apex` du geste, animée par l'idle : chaque os reçoit le changement d'orientation (monde) qu'a, dans
    l'idle, son os moteur depuis la première image ; les hanches, leur déplacement. Le haut du corps respire et se
    balance d'un bloc avec la pose du geste, comme les surcouches additives du client web.
    """
    g = pt.load_motion(rig, gesture)
    i = pt.load_motion(rig, idle)
    base, first = g.frames[apex], i.frames[0]
    drv = driver_of(rig)
    frames = []
    for k in range(0, len(i.frames), step):
        fi = i.frames[k]
        frame = {"hips": base["hips"] + (fi["hips"] - first["hips"]), "d": {}}
        for h, q in base["d"].items():
            a = drv.get(h, "hips")
            if a in fi["d"] and a in first["d"]:
                frame["d"][h] = (fi["d"][a] @ first["d"][a].inverted()) @ q
            else:
                frame["d"][h] = q
        frames.append(frame)
    return frames


def settle_frames(rig, gesture, apex, count):
    """De la pose `apex` au repos (la première image de l'idle de base), os par os, avec une courbe douce."""
    g = pt.load_motion(rig, gesture)
    rest = pt.load_motion(rig, "idle_breathing").frames[0]
    a = g.frames[apex]
    frames = []
    for k in range(count):
        t = smoothstep(0.0, 1.0, (k + 1) / count)
        d = {h: q.slerp(rest["d"].get(h, q), t) for h, q in a["d"].items()}
        frames.append({"hips": a["hips"].lerp(rest["hips"], t), "d": d})
    return frames


def clip_frames(rig, spec):
    kind = spec["kind"]
    if kind == "loop":
        m = pt.load_motion(rig, spec["motion"])
        return [m.frames[k] for k in range(0, len(m.frames), spec["step"])]
    if kind == "segment":
        m = pt.load_motion(rig, spec["motion"])
        end = min(spec["end"], len(m.frames) - 1)
        return [m.frames[k] for k in range(spec["start"], end + 1, spec["step"])]
    if kind == "hold":
        return hold_frames(rig, spec["motion"], spec["frame"], spec["idle"], spec["step"])
    if kind == "settle":
        return settle_frames(rig, spec["motion"], spec["frame"], spec["count"])
    raise ValueError(kind)


def render_clip(rig, cam, groups, name, spec, out):
    arm = rig.arm
    frames = clip_frames(rig, spec)
    motion = al.Motion(rig, name, frames)
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    tmp = al.WORKDIR / "previews" / "_loop.png"
    face = spec.get("face", "neutral")
    base_head = spec.get("head", pt.HEAD.get(face, (0.0, 0.0, 0.0)))
    n = len(frames)
    blinks = set(spec.get("blinks", []))
    for k in range(n):
        r = ramp(spec.get("ramp"), k / max(1, n - 1))
        pt.pose_frame(motion, k)
        head = tuple(v * r for v in base_head) if spec.get("ramp") else base_head
        pt.look_at_camera(arm, rig, cam, head, follow=spec.get("follow", 0.6))
        pt.hang_hair(arm, rig)
        weights = pt.face_weights(groups, face, spec.get("intensity", 1.0) * r, tired=spec.get("tired", 0.0))
        blink = spec.get("blink", 1.0 if k in blinks else 0.0)
        pt.set_face(weights, blink=blink, groups=groups)
        px = pt.pixels(pt.render(tmp))
        pt.save_webp(px, folder / f"{k:03d}.webp", quality=QUALITY)
    return {"fps": spec["fps"], "frames": n}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Boucles animées de Mika")
    parser.add_argument("--only", default="", help="états à rendre (neutral,thinking…), tous par défaut")
    parser.add_argument("--out", default="", help="dossier de sortie (par défaut frontend/Android/avatar-lab/out)")
    args = parser.parse_args(argv)
    try:
        import addon_utils

        addon_utils.enable("bl_ext.blender_org.vrm", default_set=False, persistent=False)
    except Exception as exc:
        print(f"module VRM indisponible ({exc})")

    out = Path(args.out) if args.out else OUT
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    states = {k: v for k, v in STATES.items() if not only or k in only}
    pt.dress()
    cam = pt.stage()
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = SIZE
    scene.render.resolution_percentage = 100
    arm = pt.mika()
    rig = al.Rig(arm)
    groups = pt.expression_groups(arm)

    path = out / "manifest.json"
    manifest = json.loads(path.read_text()) if path.exists() and only else {"clips": {}, "states": {}}
    for state, parts in states.items():
        for role, clip in parts.items():
            t = time.time()
            manifest["clips"][clip] = render_clip(rig, cam, groups, clip, CLIPS[clip], out)
            print(f"clip {clip}: {manifest['clips'][clip]['frames']} images, {time.time() - t:.0f} s", flush=True)
        manifest["states"][state] = parts
    manifest.update({"version": 2, "width": SIZE[0], "height": SIZE[1]})
    path.write_text(json.dumps(manifest, indent=1) + "\n")
    print(path)


if __name__ == "__main__":
    main()
