# Atelier d'animation de Mika : les mouvements adaptés à son squelette, posés au sol, appuis bloqués, exportés pour
# Unity (UnityFrontend/ArtSource/atelier/motions/*.json.gz → menu « Mika › Animation › Importer les mouvements de
# l'atelier Blender »).
#
#   blender -b UnityFrontend/ArtSource/atelier/mika_rig.blend --python frontend/assets-src/blender/atelier_mika.py -- \
#       [--only walking,idle_breathing] [--no-previews]
#
# mika_rig.blend (non versionnée : elle contient le modèle de l'acheteur) se fait une fois depuis une session Blender
# graphique — l'importeur glTF du module VRM veut une fenêtre :
#   import atelier_lib as al; al.import_mika(); al.rehearsal(True); bpy.ops.wm.save_as_mainfile(filepath=..., copy=True)
#
# Les clips : toutes les attentes, paroles et gestes du client web (Mixamo), l'attente et les deux marches de la
# capture CMU. Pour chacun :
#   1. transfert sur son squelette (atelier_lib.retarget : changement d'orientation de chaque os par rapport à la pose T,
#      hanches à l'échelle de ses jambes) ;
#   2. sauts lissés : un os qui tourne de plus de 25° (doigts) ou 30° d'une image à la suivante ;
#   3. marche (« walk ») : cycle symétrique bâti sur la moitié propre de la prise et son miroir (la marche CMU boitait :
#      pas de 86 puis 35 cm, un pied glissant sur la pointe) ;
#   4. posture : redressements éventuels (le cou de l'acteur CMU avançait de 16°, elle semblait voûtée ; l'acteur de
#      la marche lente penche le buste en arrière et la tête en avant) ;
#   5. sur place : recentrée — pieds (debout) ou hanches (assise) sous la racine, bassin face à l'avant ; puis sol : la
#      semelle la plus basse des appuis à 0 (semelles mesurées sur ses chaussures) ;
#   6. debout (« stand ») : les genoux moins pliés — les acteurs Mixamo se tiennent jambe d'appui fléchie de 18 à 32°,
#      sur elle une silhouette accroupie ; on n'en garde qu'un tiers en montant les hanches ;
#   7. appuis : chaque pied posé tenu à sa place (IK cuite), entrée et sortie fondues ;
#   8. debout : avant-bras et mains hors du corps — son bassin et ses cuisses sont plus larges que ceux de l'acteur, les
#      mains y rentraient (jusqu'à 10 cm) ; le bras s'écarte juste assez, en douceur ;
#   9. une boucle est refermée (sa dernière image répète la première) et l'écart du raccord est rapporté ;
#  10. export du mouvement, rendus de contrôle en tenue de répétition (previews/<clip>.png, non versionnés).
import argparse
import json
import os
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atelier_lib as al  # noqa: E402

MOCAP = al.REPO / "UnityFrontend/ArtSource/mocap"
WEB = al.REPO / "frontend/public/animations"

# Ce qui s'écarte du traitement par défaut, clip par clip.
OVERRIDES = {
    "walking": dict(straighten={"neck": -8.0}, note="CMU 35_01"),
    # Les têtes CMU ont un décalage constant propre à l'acteur (142 : levée de 27° ; 113 : penchée de 39° de côté) :
    # cou et tête ramenés droits sur le buste en moyenne (recenter_head), leurs mouvements gardés.
    "walking_slow": dict(straighten={"spine": 3.5, "chest": 3.5}, head="recenter", note="CMU 142_13"),
    "waiting": dict(head="recenter", note="CMU 113_21"),
    # La surprise se fait en se baissant d'un coup : les genoux pliés sont le geste.
    "gesture_surprised": dict(taller=False),
    # S'asseoir et se lever (143_18) : l'acteur plonge la tête presque à hauteur de bureau (buste +21°, cou +42° en
    # moyenne au-delà de son repos à elle) ; on n'en garde que la moitié, et cou et tête sont ramenés sur le buste.
    "sit_down": dict(lean_keep=0.5, head="recenter", note="CMU 143_18"),
    "stand_up": dict(lean_keep=0.5, head="recenter", note="CMU 143_18"),
    # Adossée, la tête suivait le buste et regardait 10° vers le haut : un peu vers le bureau.
    "sitting_idle": dict(head="recenter", straighten={"head": 12.0}, note="CMU 113_15"),
}

# Hauteur des hanches assises (m au-dessus du sol du clip, 2 cm sous le vrai), mesurée dans l'atelier avec les vrais
# meubles (atelier_desk_check.py) : assise, le dessous de ses fesses est 15 cm sous l'os du bassin. Sa chaise (vérin
# réglé pour elle, build_desk.CHAIR_DROP) a son coussin à 0,447 m, qui s'enfonce d'un peu plus d'un centimètre ; le
# matelas, à 0,47 m, de trois → bassin à 0,585 / 0,59 m réels, un seul clip pour les deux. La scène pose les ancres
# des sièges à cette hauteur (ChambreSceneBuilder). Pieds à plat, ses cuisses traverseraient encore le bord du coussin :
# elle lève un peu les talons (SEAT_HEELS).
SEAT_HIPS = 0.565
SEAT_HEELS = 0.04
# Les pieds un peu en avant de ceux de la prise : debout devant le siège pour s'asseoir (et en se relevant), ses
# mollets entraient de 3 cm dans le bord du coussin ; assise, ils s'écartent aussi du piètement.
SEAT_FEET_AHEAD = 0.04


def catalog():
    """Les clips de l'atelier : nom → réglages (source, genre, boucle, voyage)."""
    clips = {
        "walking": dict(src=MOCAP / "walking.fbx", kind="walk", loop=True, travel=True),
        "walking_slow": dict(src=MOCAP / "walking_slow.fbx", kind="walk", loop=True, travel=True),
        "waiting": dict(src=MOCAP / "waiting.fbx", kind="stand", loop=True),
        "sit_down": dict(src=MOCAP / "sit_down.fbx", kind="sit", loop=False, travel=True),
        "sitting_idle": dict(src=MOCAP / "sitting_idle.fbx", kind="sit", loop=True),
        "stand_up": dict(src=MOCAP / "stand_up.fbx", kind="sit", loop=False, travel=True),
    }
    manifest = json.loads((WEB / "manifest.json").read_text())["clips"]
    for category, loop in (("idle", True), ("talk", True), ("gesture", False)):
        for p in sorted((WEB / category).glob("*.fbx")):
            clips[p.stem] = dict(src=p, kind="stand", loop=manifest.get(p.stem, {}).get("loop", loop), note="Mixamo")
    for name, extra in OVERRIDES.items():
        if name in clips:
            clips[name].update(extra)
    return clips


def clear_desk_edge(motion, scene, margin=0.006, passes=8):
    """
    Les mains et les avant-bras sortis du plateau du bureau, mesurés sur la peau (le maillage déformé, comme le
    contrôle) : une main qui s'appuie sur le bureau pour se lever y entrait de quelques centimètres sous la ligne des
    os, et une main juste devant la tranche du plateau échappait aux rayons vers le bas. Le poignet est soulevé d'autant
    qu'il faut (IK du bras), lissé dans le temps ; on recommence tant qu'il reste un contact. Rend la plus grande
    remontée (cm).
    """
    import atelier_decor as dc
    import atelier_desk as ad
    from mathutils import Vector
    rig = motion.rig
    contacts = dc.Contacts(rig)
    desk = ad.Desk(rig)
    n = len(motion.frames)
    scene.apply(0)
    top = max((o.matrix_world @ Vector(c)).z for o in dc.meshes(dc.load("writing_desk")) for c in o.bound_box)
    worst = 0.0
    for _ in range(passes):
        needs = {"left": [0.0] * n, "right": [0.0] * n}
        for i in range(n):
            found = contacts.check(motion, scene, ("writing_desk",), [i], tolerance=0.002)
            for (part, _oid), (depth, f, bone, at) in found.items():
                if part not in ("mains", "bras"):
                    continue
                side = "left" if bone.startswith("left") else "right"
                # Au-dessus du plateau : la distance à la face la plus proche sous-estime une main enfoncée dans son
                # épaisseur (elle est plus près de la tranche que du dessus).
                needs[side][i] = max(needs[side][i], depth / 100.0, top - at[2]) + margin
        if os.environ.get("MIKA_DEBUG"):
            print("[debug] besoins", {k: [round(x * 100, 1) for x in v if x > 0] for k, v in needs.items()},
                  {k: [i for i, x in enumerate(v) if x > 0] for k, v in needs.items()}, flush=True)
        if not any(max(v) > 0.0 for v in needs.values()):
            break
        for side, values in needs.items():
            if max(values) <= 0.0:
                continue
            held = [max(values[min(n - 1, max(0, i + k))] for k in range(-3, 4)) for i in range(n)]
            smooth = [max(held[i], sum(held[min(n - 1, max(0, i + k))] for k in range(-2, 3)) / 5) for i in range(n)]
            for i, lift in enumerate(smooth):
                if lift <= 1e-4:
                    continue
                frame = motion.frames[i]
                j = rig.joints(frame, (f"{side}UpperArm", f"{side}LowerArm", f"{side}Hand"))
                # Le coude dans le plan où il plie, ou, bras tendu (elle s'appuie sur le bureau), en arrière et en dehors :
                # soulever un poignet le long d'un bras droit ne le déplaçait pas.
                sx = 1.0 if side == "left" else -1.0
                hint = j[f"{side}LowerArm"] + Vector((sx * 0.08, 0.10, 0.0))
                ad.arm_ik(desk, frame, side, j[f"{side}Hand"] + Vector((0.0, 0.0, lift)), hint, None, None,
                          hand_rot=frame["d"][f"{side}Hand"].copy())
                worst = max(worst, lift)
    return round(worst * 100, 1)


def build(name, spec, rig, soles, clearance, previews):
    src = al.import_fbx(spec["src"])
    motion = al.retarget(src, rig, name, loop=spec.get("loop", False), travel=spec.get("travel", False))
    bpy.data.objects.remove(src, do_unlink=True)
    report = [f"rapport de jambes {motion.ratio:.3f}"]
    fixed = al.despike(motion)
    if fixed:
        report.append(f"{fixed} saut(s) lissé(s)")
    if spec["kind"] == "walk":
        side, start = al.symmetric_cycle(motion, soles)
        report.append(f"cycle symétrique sur l'appui {side} (image {start})")
    if motion.loop and spec["kind"] != "walk":
        # Le raccord de la prise : sa dernière image doit répéter la première (Unity étale un écart sur tout le cycle).
        gap, bone = al.loop_gap(motion)
        report.append(f"raccord source {gap:.1f}° ({bone or '-'})")
        if gap > 3.0:
            print(f"[atelier] ATTENTION {name} : la prise ne se referme pas ({gap:.1f}° sur {bone}).")
    if spec.get("head") == "recenter":
        removed = al.recenter_head(motion)
        report.append("tête recentrée " + ", ".join(f"{b} {a:.0f}°" for b, a in removed.items()))
    if spec.get("lean_keep") is not None:
        worst = al.lean_less(motion, keep=spec["lean_keep"])
        report.append(f"buste moins plongé (au plus {worst:.0f}° → {worst * spec['lean_keep']:.0f}°)")
    if spec.get("straighten"):
        al.straighten(motion, spec["straighten"])
        report.append(f"redressé {spec['straighten']}")
    if spec["kind"] == "stand":
        angle, shift = al.center_stance(motion, on="feet")
        report.append(f"recentrée ({angle:.0f}°, {shift:.1f} cm)")
    elif spec["kind"] == "sit":
        # L'assise sous la racine (le jeu pose la racine sur le siège), face à l'avant ; pour s'asseoir et se
        # lever, c'est la partie assise qui fait référence (fin de l'un, début de l'autre).
        n = len(motion.frames)
        ref = {"sit_down": range(n - 5, n), "stand_up": range(0, 5)}.get(name)
        angle, shift = al.center_stance(motion, on="hips", frames=ref)
        if spec.get("travel"):
            report.append(f"tournée de {angle:.0f}°")
        else:
            report.append(f"recentrée ({angle:.0f}°, {shift:.1f} cm)")
    floor = al.ground(motion, soles)
    report.append(f"sol {floor:+.3f}")
    flags = {s: al.contacts(motion, soles, s, height=0.03)[0] for s in ("left", "right")}
    if spec["kind"] == "sit":
        # S'asseoir, rester assise, se lever : les pieds ne quittent pas le sol (l'acteur les traîne un peu).
        flags = {s: [True] * len(motion.frames) for s in flags}
    if spec["kind"] == "stand" and spec.get("taller", True):
        lift = al.stand_taller(motion, flags)
        report.append(f"grandie de {lift:.1f} cm")
    if spec["kind"] == "sit":
        lo, delta = al.seat_height(motion, SEAT_HIPS)
        report.append(f"assise {lo:.2f} → {SEAT_HIPS:.2f} m")
    al.lock_feet(motion, soles, flags)
    report.append("appuis " + " ".join(f"{s}:{sum(f)}" for s, f in flags.items()))
    if spec["kind"] == "sit":
        # Les talons se lèvent une fois le poids sur le siège (fin de la descente) et se reposent avant qu'elle se
        # relève (début de la montée) : le poids du bas de course des hanches.
        zs = [f["hips"].z for f in motion.frames]
        lo = min(zs)
        weights = [max(0.0, min(1.0, 1.0 - (z - lo) / 0.06)) for z in zs]
        weights = [w * w * (3 - 2 * w) for w in weights]
        al.raise_heels(motion, rig, SEAT_HEELS, weights)
        report.append(f"talons levés de {SEAT_HEELS * 100:.0f} cm assise")
        # Debout → assise : la part de la descente faite (les hanches qui reculent vers le siège).
        span = max(zs) - lo
        seated = [1.0 if span < 0.05 else min(1.0, max(0.0, (max(zs) - z) / span)) for z in zs]
        al.feet_ahead(motion, rig, SEAT_FEET_AHEAD, seated)
        report.append(f"pieds {SEAT_FEET_AHEAD * 100:.0f} cm plus en avant")
    if spec["kind"] in ("stand", "sit"):
        rest = al.clear_arms(motion, clearance)
        report.append("bras dégagés" + (f" (reste {rest} cm)" if rest else ""))
    if name in ("sit_down", "stand_up"):
        # Au bureau, elle s'assoit et se lève la chaise à sa place (rien ne la recule) : la main qui accompagne le mouvement
        # passe près du bord du plateau — posée dessus, pas dedans (vérifié avec le vrai bureau, atelier_desk_check.py).
        import atelier_decor as dc
        import atelier_desk as ad
        layout = dc.Layout()
        scene = dc.Scene(layout, layout.chair_pose("home"))
        motion.explicit()
        lift = ad.settle_hands(motion, scene, reach=0.05)
        swivel = ad.clear_desk(motion, scene)
        # En dernier : mesuré sur la peau, après tout ce qui fait bouger le bras.
        edge = clear_desk_edge(motion, scene)
        if lift or swivel or edge:
            report.append(f"mains au-dessus du bureau (posées {lift} cm, sorties du plateau {edge} cm, coudes {swivel}°)")
        left = dc.Contacts(rig).check(motion, scene, ("writing_desk",), range(len(motion.frames)), tolerance=0.002)
        print(f"[atelier] {name} : reste contre le bureau {dc.report(left) or 'rien'}", flush=True)
    if motion.loop:
        # Le raccord après traitement : de la dernière image unique à la première, pas plus qu'un pas ordinaire.
        seam, usual = al.seam_step(motion)
        al.close_loop(motion)
        report.append(f"raccord {seam:.1f}° (pas moyen {usual:.1f}°)")
        if seam > max(3.0, 3 * usual):
            print(f"[atelier] ATTENTION {name} : à-coup au raccord ({seam:.1f}° contre {usual:.1f}° d'habitude).")
    # Contrôle final : pieds (glissement, enfoncement, appui qui décolle), plus grand saut d'un os.
    feet = al.feet_report(motion, soles)
    jump = al.jumps(motion)
    qa = (f"contrôle : glisse {feet['left']['glisse_cm']}/{feet['right']['glisse_cm']} cm, "
          f"enfonce {feet['left']['enfonce_cm']}/{feet['right']['enfonce_cm']} cm, "
          f"appui qui bouge {feet['left']['hauteur_appui_cm']}/{feet['right']['hauteur_appui_cm']} cm, "
          f"en l'air {feet['en_l_air']}, saut {jump['saut']}° ({jump['os']} image {jump['image']})")
    print(f"[atelier] {name} {qa}", flush=True)
    path = motion.export(note=f"{spec.get('note', '')} — " + ", ".join(report))
    if previews:
        motion.to_action()
        al.render_sheet(motion, name)
    print(f"[atelier] {name} : {len(motion.frames)} images, " + ", ".join(report) + f" → {path}", flush=True)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--no-previews", action="store_true")
    args = parser.parse_args(argv)
    only = [n for n in args.only.split(",") if n]
    rig = al.Rig(al.mika_armature())
    soles = al.Soles(rig)
    clearance = al.Clearance(rig)
    al.rehearsal(True)
    for name, spec in catalog().items():
        if only and name not in only:
            continue
        build(name, spec, rig, soles, clearance, not args.no_previews)


if __name__ == "__main__":
    main()
