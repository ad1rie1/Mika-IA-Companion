# Audit des mouvements de Mika : chaque clip source (attentes, paroles et gestes Mixamo du client web, prises CMU),
# transféré sur son squelette, est mesuré — pieds (glissement, enfoncement, appui qui monte), raccord de boucle,
# sauts d'un os d'une image à l'autre, posture (buste, cou), genoux en hyperextension, avant-bras et mains dans le
# corps (sur son maillage). « --clean » mesure aussi le mouvement après le traitement de l'atelier.
#
#   blender -b UnityFrontend/ArtSource/atelier/mika_rig.blend --python frontend/assets-src/blender/atelier_audit.py -- \
#       [--only idle_happy,talk_main] [--clean] [--no-mesh] [--json chemin]
import argparse
import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atelier_lib as al  # noqa: E402

WEB = al.REPO / "frontend/public/animations"
MOCAP = al.REPO / "UnityFrontend/ArtSource/mocap"


def sources():
    """Les clips qu'Unity joue : nom → (fichier, boucle, voyage)."""
    out = {}
    loops_web = {"idle": True, "talk": True, "gesture": False}
    manifest = json.loads((WEB / "manifest.json").read_text())["clips"]
    for cat, loop in loops_web.items():
        for p in sorted((WEB / cat).glob("*.fbx")):
            out[p.stem] = (p, manifest.get(p.stem, {}).get("loop", loop), False)
    clips = json.loads((MOCAP / "clips.json").read_text())["clips"]
    for c in clips:
        name = c["name"]
        if name in ("walking", "walking_slow", "sit_down", "stand_up", "sitting_idle", "waiting"):
            out[name] = (MOCAP / f"{name}.fbx", bool(c.get("loop")), name in ("walking", "walking_slow", "sit_down", "stand_up"))
    return out


def measure(motion, soles, clearance):
    r = {"images": len(motion.frames)}
    r.update(al.loop_report(motion))
    r.update(al.jumps(motion))
    r.update(al.posture(motion))
    r.update(al.knees(motion))
    r["pieds"] = al.feet_report(motion, soles)
    if clearance is not None:
        r["mains"] = clearance.measure(motion)
    return r


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--no-mesh", action="store_true")
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)
    only = [n for n in args.only.split(",") if n]
    rig = al.Rig(al.mika_armature())
    soles = al.Soles(rig)
    clearance = None if args.no_mesh else al.Clearance(rig)
    report = {}
    rest = al.Motion(rig, "repos", [{"hips": rig.rest_pos["hips"].copy(), "d": {h: al.Quaternion() for h in rig.hmap}}])
    report["_repos"] = al.posture(rest)
    print(f"[audit] pose de repos : {report['_repos']}", flush=True)
    for name, (path, loop, travel) in sources().items():
        if only and name not in only:
            continue
        src = al.import_fbx(path)
        motion = al.retarget(src, rig, name, loop=loop, travel=travel)
        bpy.data.objects.remove(src, do_unlink=True)
        al.ground(motion, soles)
        report[name] = {"brut": measure(motion, soles, clearance)}
        print(f"[audit] {name} brut : {json.dumps(report[name]['brut'], ensure_ascii=False)}", flush=True)
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
