# Vérifier les clips assis au bord du lit (s'asseoir, assise, se lever — les mêmes que sur la chaise de bureau) contre
# le vrai lit, sa couette faite et ce qui l'entoure (relevé Unity : frontend/Unity/ArtSource/atelier/bed_layout.json,
# repère de l'assise du lit). Contacts mesurés, planches previews/verif_lit_<clip>.png.
#
#   blender -b frontend/Unity/ArtSource/atelier/mika_rig.blend --python frontend/Web/assets-src/blender/atelier_bed_check.py -- \
#       [--only sitting_idle] [--no-previews]
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atelier_decor as dc  # noqa: E402
import atelier_lib as al  # noqa: E402
from atelier_desk_check import load_motion  # noqa: E402

BED_LAYOUT = al.WORKDIR / "bed_layout.json"
# La couette et le plaid (duvet.fbx, throw.fbx de duvet_states.py) ne se relisent pas encore à leur place dans
# Blender : le contrôle se fait contre le lit (cadre, matelas, oreiller) — la couette faite ajoute quelques
# centimètres sur le matelas, que l'enfoncement prévu pour le lit (3 cm, ChambreSceneBuilder) absorbe.
BED_OBJECTS = ("bed_frame", "nightstand", "slippers", "plushie", "bedside_lamp")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--no-previews", action="store_true")
    args = ap.parse_args(argv)
    names = [n for n in args.only.split(",") if n] or ["sitting_idle", "sit_down", "stand_up"]
    rig = al.Rig(al.mika_armature())
    al.rehearsal(True)
    layout = dc.Layout(BED_LAYOUT)
    print(f"[lit] hanches de l'assise à {layout.seat_hips:.3f} m", flush=True)
    contacts = dc.Contacts(rig)
    for name in names:
        motion = load_motion(rig, name)
        scene = dc.Scene(layout, (0.0, 0.0), objects=BED_OBJECTS)
        n = len(motion.frames)
        found = contacts.check(motion, scene, ("bed_frame", "nightstand", "slippers"), range(0, n, max(1, n // 12)))
        lines = dc.report(found)
        print(f"[lit] {name} ({n} images) : " + ("aucun contact" if not lines else ""), flush=True)
        for line in lines:
            print(f"[lit]     {line}", flush=True)
        if args.no_previews:
            continue
        picks = [round(i * (n - 1) / 3) for i in range(4)]
        views = (("cote", (1.7, 0.1, 0.1)), ("face", (-0.6, -1.7, 0.4)), ("pieds", (1.0, -0.6, -0.25)))
        dc.render_sheet(motion, scene, f"verif_lit_{name}", views, picks, focus=(0.0, -0.1, 0.45))


if __name__ == "__main__":
    main()
