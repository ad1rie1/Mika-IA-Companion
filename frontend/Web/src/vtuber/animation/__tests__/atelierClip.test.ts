import * as THREE from "three";
import type { VRM } from "@pixiv/three-vrm";
import { describe, expect, it } from "vitest";
import { atelierDeltas, isAtelierUrl, retargetAtelierClip, workshopFrame, type AtelierMotion } from "../atelierClip";

/** A normalized rig like three-vrm's: identity rest rotations, the humanoid hierarchy. */
function stubVrm(metaVersion: "0" | "1" = "1"): VRM {
  const parents: Record<string, string | null> = {
    hips: null,
    spine: "hips",
    chest: "spine",
    upperChest: "chest",
    neck: "upperChest",
    head: "neck",
    leftShoulder: "upperChest",
    leftUpperArm: "leftShoulder",
    leftLowerArm: "leftUpperArm",
    leftHand: "leftLowerArm",
    rightShoulder: "upperChest",
    rightUpperArm: "rightShoulder",
    rightLowerArm: "rightUpperArm",
    rightHand: "rightLowerArm",
    leftUpperLeg: "hips",
    leftLowerLeg: "leftUpperLeg",
    leftFoot: "leftLowerLeg",
    leftToes: "leftFoot",
    leftIndexProximal: "leftHand",
  };
  const nodes = new Map<string, THREE.Object3D>();
  const root = new THREE.Object3D();
  for (const [bone, parent] of Object.entries(parents)) {
    const node = new THREE.Object3D();
    node.name = `Normalized_${bone}`;
    nodes.set(bone, node);
    (parent ? nodes.get(parent)! : root).add(node);
  }
  return {
    meta: { metaVersion },
    humanoid: {
      getNormalizedBoneNode: (bone: string) => nodes.get(bone) ?? null,
      normalizedRestPose: { hips: { position: [0, 0.7829, 0] } },
    },
  } as unknown as VRM;
}

const BONES = [
  "hips", "spine", "chest", "neck", "head", "leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand",
  "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand", "leftUpperLeg", "leftLowerLeg", "leftFoot",
  "leftToes", "leftIndexProximal", "leftEye",
];

/** The workshop's T-pose in Blender space: Z up, facing −Y, her left at +X. */
const REST_P: Record<string, [number, number, number]> = {
  hips: [0, 0.004, 0.783],
  head: [0, 0.006, 1.136],
  leftHand: [0.62, 0.0, 1.3],
  rightHand: [-0.62, 0.0, 1.3],
  leftFoot: [0.063, 0.025, 0.103],
  leftToes: [0.061, -0.062, 0.042],
};

/** Blender bone rotations at rest are anything but the identity (a bone points along its Y). */
function restQ(i: number): [number, number, number, number] {
  const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.3 + i * 0.7, -0.2 + i * 0.4, 0.1 * i));
  return [q.w, q.x, q.y, q.z];
}

function motion(frames: (rotate: (bone: string, q: THREE.Quaternion) => THREE.Quaternion, hips: number[]) => number[][], travel = false): AtelierMotion {
  const rest: AtelierMotion["rest"] = {};
  BONES.forEach((b, i) => (rest[b] = { p: REST_P[b] ?? [0, 0, 1], q: restQ(i) }));
  return {
    name: "essai",
    fps: 30,
    loop: true,
    travel,
    bones: BONES,
    rest,
    frames: frames((bone, now) => now, []),
  };
}

/** One frame: hips position, then each bone's world rotation (w, x, y, z) = change · rest. */
function frame(hips: [number, number, number], change: (bone: string) => THREE.Quaternion = () => new THREE.Quaternion()): number[] {
  const row: number[] = [...hips];
  BONES.forEach((b, i) => {
    const [w, x, y, z] = restQ(i);
    const q = change(b).clone().multiply(new THREE.Quaternion(x, y, z, w));
    row.push(q.w, q.x, q.y, q.z);
  });
  return row;
}

const track = (clip: THREE.AnimationClip, name: string) => clip.tracks.find((t) => t.name === name);
const quatAt = (t: THREE.KeyframeTrack, i: number) => new THREE.Quaternion().fromArray(t.values as unknown as number[], 4 * i);

describe("les mouvements de l'atelier Unity", () => {
  it("reconnaît leurs fichiers", () => {
    expect(isAtelierUrl("/animations/atelier/walking.json.gz")).toBe(true);
    expect(isAtelierUrl("/animations/idle/idle_happy.fbx")).toBe(false);
  });

  it("passe du repère de Blender (Z en haut, regard vers −Y) à celui du VRM", () => {
    const rest = motion(() => []).rest;
    const m = workshopFrame(rest);
    const up = new THREE.Vector3(0, 0, 1).applyQuaternion(m);
    const ahead = new THREE.Vector3(0, -1, 0).applyQuaternion(m);
    const left = new THREE.Vector3(1, 0, 0).applyQuaternion(m);
    expect(up.y).toBeCloseTo(1, 2);
    expect(ahead.z).toBeCloseTo(1, 1);
    expect(left.x).toBeCloseTo(1, 1);
  });

  it("au repos, chaque os garde sa pose ; les hanches restent à leur hauteur", () => {
    const m = motion(() => [frame(REST_P.hips), frame(REST_P.hips)]);
    const { clip, measures } = retargetAtelierClip(m, stubVrm(), "essai");
    for (const t of clip.tracks.filter((x) => x.name.endsWith(".quaternion"))) {
      expect(quatAt(t, 0).angleTo(new THREE.Quaternion()), t.name).toBeLessThan(1e-4);
    }
    expect(measures.hipsHeight).toBeCloseTo(0.783, 3);
  });

  it("un bras qui descend le long du corps devient une rotation négative autour de Z (VRM 1.0)", () => {
    // Autour de +Y de Blender, de 90° : le bras gauche (+X) passe vers le bas (−Z). L'avant-bras suit.
    const down = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2);
    const arm = new Set(["leftUpperArm", "leftLowerArm", "leftHand", "leftIndexProximal"]);
    const m = motion(() => [frame(REST_P.hips), frame(REST_P.hips, (b) => (arm.has(b) ? down : new THREE.Quaternion()))]);
    const { clip } = retargetAtelierClip(m, stubVrm(), "essai");
    const upper = quatAt(track(clip, "Normalized_leftUpperArm.quaternion")!, 1);
    const expected = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), -Math.PI / 2);
    expect(upper.angleTo(expected)).toBeLessThan(1e-3);
    // l'avant-bras ne tourne pas par rapport au bras
    expect(quatAt(track(clip, "Normalized_leftLowerArm.quaternion")!, 1).angleTo(new THREE.Quaternion())).toBeLessThan(1e-3);
    // un modèle 0.x (tourné de π) reçoit la même pose, conjuguée : +Z
    const flipped = quatAt(track(retargetAtelierClip(m, stubVrm("0"), "essai").clip, "Normalized_leftUpperArm.quaternion")!, 1);
    expect(flipped.angleTo(expected.clone().invert())).toBeLessThan(1e-3);
  });

  it("les doigts et les yeux restent aux mains et au regard du client", () => {
    const { clip, report } = retargetAtelierClip(motion(() => [frame(REST_P.hips), frame(REST_P.hips)]), stubVrm(), "essai");
    expect(track(clip, "Normalized_leftIndexProximal.quaternion")).toBeUndefined();
    expect(report.strippedFingerTracks).toBe(1);
    expect(report.droppedTracks).toEqual(["leftEye"]);
  });

  it("une marche se joue sur place, et garde sa vitesse au sol", () => {
    // 1 m vers l'avant (−Y de Blender) en 30 images (1 s), en se balançant de côté
    const frames = Array.from({ length: 31 }, (_, i) =>
      frame([0.03 * Math.sin((i / 30) * 2 * Math.PI), -i / 30, 0.78])
    );
    const m = motion(() => frames, true);
    const { clip, measures } = retargetAtelierClip(m, stubVrm(), "marche");
    expect(measures.speed).toBeCloseTo(1, 3);
    const hips = track(clip, "Normalized_hips.position")!;
    const z = Array.from({ length: 31 }, (_, i) => hips.values[3 * i + 2]);
    expect(Math.max(...z.map(Math.abs))).toBeLessThan(1e-6);
    // le balancement reste
    expect(Math.max(...Array.from({ length: 31 }, (_, i) => hips.values[3 * i]))).toBeCloseTo(0.03, 2);
  });

  it("une prise qui commence loin de son origine est ramenée sur la racine", () => {
    // la marche CMU part à 0,58 m de son origine ; la boucle se joue autour de la racine
    const walk = Array.from({ length: 31 }, (_, i) => frame([0, -0.58 - i / 30, 0.78]));
    const { clip } = retargetAtelierClip(motion(() => walk, true), stubVrm(), "marche");
    const z = Array.from({ length: 31 }, (_, i) => track(clip, "Normalized_hips.position")!.values[3 * i + 2]);
    expect(Math.max(...z.map(Math.abs))).toBeLessThan(1e-6);
    // l'assise part 0,31 m devant son siège : elle commence au-dessus de la racine
    const sit = Array.from({ length: 31 }, (_, i) => frame([0, -0.31 + (0.31 * i) / 30, 0.78 - (0.21 * i) / 30]));
    const once = motion(() => sit, true);
    once.loop = false;
    const hips = track(retargetAtelierClip(once, stubVrm(), "assise").clip, "Normalized_hips.position")!;
    expect(Math.abs(hips.values[2])).toBeLessThan(1e-6);
    expect(Math.abs(hips.values[3 * 30 + 2])).toBeLessThan(1e-6);
  });

  it("les deltas du monde se calculent sans VRM", () => {
    const d = atelierDeltas(motion(() => [frame([0, -0.3, 0.6])]));
    expect([...d.hips]).toEqual([expect.closeTo(0, 6), expect.closeTo(0.6, 6), expect.closeTo(0.3, 6)]);
    expect(d.restHipsHeight).toBeCloseTo(0.783, 6);
  });
});
