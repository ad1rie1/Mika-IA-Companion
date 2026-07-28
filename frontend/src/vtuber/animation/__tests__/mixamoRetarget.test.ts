import * as THREE from "three";
import { describe, expect, it } from "vitest";
import type { VRM } from "@pixiv/three-vrm";
import { detectMixamoPrefix, retargetMixamoClip } from "../mixamoRetarget";

/** Minimal fake VRM: just what the retarget path reads. */
function fakeVrm(metaVersion: "0" | "1" = "0"): VRM {
  const nodes = new Map<string, THREE.Object3D>();
  const getNormalizedBoneNode = (bone: string) => {
    let node = nodes.get(bone);
    if (!node) {
      node = new THREE.Object3D();
      node.name = `Normalized_${bone}`;
      nodes.set(bone, node);
    }
    return node;
  };
  return {
    meta: { metaVersion },
    humanoid: {
      getNormalizedBoneNode,
      normalizedRestPose: { hips: { position: [0, 0.75, 0] } },
    },
  } as unknown as VRM;
}

/** Synthetic Mixamo-style rig: root → prefix+Hips (y=100) → prefix+Spine,
 * with a "mixamo.com" clip animating hips (quat+pos) and spine (quat). */
function fakeMixamoAsset(prefix = "mixamorig"): THREE.Group {
  const root = new THREE.Group();
  const hips = new THREE.Object3D();
  hips.name = `${prefix}Hips`;
  hips.position.set(0, 100, 0);
  const spine = new THREE.Object3D();
  spine.name = `${prefix}Spine`;
  spine.position.set(0, 10, 0);
  hips.add(spine);
  root.add(hips);

  const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.3, 0, 0));
  const tracks = [
    new THREE.QuaternionKeyframeTrack(`${prefix}Hips.quaternion`, [0, 1], [
      q.x, q.y, q.z, q.w,
      q.x, q.y, q.z, q.w,
    ]),
    new THREE.VectorKeyframeTrack(`${prefix}Hips.position`, [0, 1], [
      5, 100, -3,
      5, 100, -3,
    ]),
    new THREE.QuaternionKeyframeTrack(`${prefix}Spine.quaternion`, [0, 1], [
      0, 0, 0, 1,
      0, 0, 0, 1,
    ]),
    // Finger track — must be stripped.
    new THREE.QuaternionKeyframeTrack(`${prefix}LeftHandIndex1.quaternion`, [0], [0, 0, 0, 1]),
    // Unknown end-site — must be dropped.
    new THREE.QuaternionKeyframeTrack(`${prefix}LeftToe_End.quaternion`, [0], [0, 0, 0, 1]),
  ];
  root.animations = [new THREE.AnimationClip("mixamo.com", 1, tracks)];
  return root;
}

describe("detectMixamoPrefix", () => {
  it.each([["mixamorig"], ["mixamorig:"], ["mixamorig1"]])(
    "detects prefix %s",
    (prefix) => {
      expect(detectMixamoPrefix(fakeMixamoAsset(prefix))).toBe(prefix);
    }
  );

  it("accepts a bare Hips rig (empty prefix)", () => {
    expect(detectMixamoPrefix(fakeMixamoAsset(""))).toBe("");
  });

  it("returns null when no hips exists", () => {
    expect(detectMixamoPrefix(new THREE.Group())).toBeNull();
  });
});

describe("retargetMixamoClip", () => {
  it("maps tracks to normalized bone names and strips fingers", () => {
    const { clip, report } = retargetMixamoClip(fakeMixamoAsset(), fakeVrm(), "test");
    const names = clip.tracks.map((t) => t.name).sort();
    expect(names).toEqual([
      "Normalized_hips.position",
      "Normalized_hips.quaternion",
      "Normalized_spine.quaternion",
    ]);
    expect(report.strippedFingerTracks).toBe(1);
    expect(report.droppedTracks).toContain("mixamorigLeftToe_End.quaternion");
    expect(clip.duration).toBe(1);
  });

  it("scales the hips position by vrmHips/mixamoHips and flips X/Z for VRM0", () => {
    const { clip, report } = retargetMixamoClip(fakeMixamoAsset(), fakeVrm("0"), "test");
    expect(report.hipsPositionScale).toBeCloseTo(0.0075, 6);
    expect(report.hipsScaleSuspicious).toBe(false);
    const pos = clip.tracks.find((t) => t.name === "Normalized_hips.position")!;
    // source (5, 100, -3) × 0.0075, then x/z negated
    expect(pos.values[0]).toBeCloseTo(-0.0375, 6);
    expect(pos.values[1]).toBeCloseTo(0.75, 6);
    expect(pos.values[2]).toBeCloseTo(0.0225, 6);
  });

  it("conjugates quaternions by Ry(π) for VRM0 (negate x and z)", () => {
    // Rig at identity rest → q' = q before the flip.
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.3, 0, 0));
    const { clip } = retargetMixamoClip(fakeMixamoAsset(), fakeVrm("0"), "test");
    const track = clip.tracks.find((t) => t.name === "Normalized_hips.quaternion")!;
    expect(track.values[0]).toBeCloseTo(-q.x, 6);
    expect(track.values[1]).toBeCloseTo(q.y, 6);
    expect(track.values[2]).toBeCloseTo(-q.z, 6);
    expect(track.values[3]).toBeCloseTo(q.w, 6);
  });

  it("applies no flip for VRM1", () => {
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.3, 0, 0));
    const { clip } = retargetMixamoClip(fakeMixamoAsset(), fakeVrm("1"), "test");
    const track = clip.tracks.find((t) => t.name === "Normalized_hips.quaternion")!;
    expect(track.values[0]).toBeCloseTo(q.x, 6);
    const pos = clip.tracks.find((t) => t.name === "Normalized_hips.position")!;
    expect(pos.values[0]).toBeCloseTo(0.0375, 6);
  });

  it("stripRootXZ zeroes hips X/Z but keeps the vertical bob", () => {
    const { clip } = retargetMixamoClip(fakeMixamoAsset(), fakeVrm(), "test", {
      stripRootXZ: true,
    });
    const pos = clip.tracks.find((t) => t.name === "Normalized_hips.position")!;
    expect(pos.values[0]).toBe(0);
    expect(pos.values[1]).toBeCloseTo(0.75, 6);
    expect(pos.values[2]).toBe(0);
  });

  it("throws on an asset with no animation", () => {
    const empty = fakeMixamoAsset();
    empty.animations = [];
    expect(() => retargetMixamoClip(empty, fakeVrm(), "test")).toThrow(/no animation/);
  });

  it("drops degenerate FBXLoader stub tracks instead of emitting NaN", () => {
    const asset = fakeMixamoAsset();
    // three's FBXLoader emits `(name, [0], [0])` when a bone's rotation
    // curves are incomplete — length 1 instead of times.length * 4.
    asset.animations[0].tracks.push(
      new THREE.QuaternionKeyframeTrack("mixamorigNeck.quaternion", [0], [0])
    );
    const neck = new THREE.Object3D();
    neck.name = "mixamorigNeck";
    asset.getObjectByName("mixamorigSpine")!.add(neck);

    const { clip, report } = retargetMixamoClip(asset, fakeVrm(), "test");
    expect(report.droppedTracks).toContain("mixamorigNeck.quaternion");
    for (const track of clip.tracks) {
      for (const v of track.values) expect(Number.isFinite(v)).toBe(true);
    }
  });

  it("maps a bone animated AT its (non-identity) rest rotation to the identity quaternion", () => {
    // The normalized rig's rest is identity by spec, so retargeting the
    // FBX rest pose itself must land exactly on identity — a property
    // that breaks if the premultiply/multiply conjugation order is
    // swapped or the rest rotations are read after playback.
    const asset = fakeMixamoAsset();
    const hips = asset.getObjectByName("mixamorigHips")!;
    const spine = asset.getObjectByName("mixamorigSpine")!;
    hips.quaternion.setFromEuler(new THREE.Euler(0.1, -0.2, 0.05));
    spine.quaternion.setFromEuler(new THREE.Euler(0.2, 0.4, 0.1));
    const q = spine.quaternion;
    asset.animations[0].tracks = [
      new THREE.QuaternionKeyframeTrack("mixamorigSpine.quaternion", [0, 1], [
        q.x, q.y, q.z, q.w,
        q.x, q.y, q.z, q.w,
      ]),
    ];

    const { clip } = retargetMixamoClip(asset, fakeVrm("0"), "test");
    const track = clip.tracks.find((t) => t.name === "Normalized_spine.quaternion")!;
    // identity is flip-invariant: (−0, 0, −0, 1) ≡ (0, 0, 0, 1)
    expect(Math.abs(track.values[0])).toBeLessThan(1e-6);
    expect(Math.abs(track.values[1])).toBeLessThan(1e-6);
    expect(Math.abs(track.values[2])).toBeLessThan(1e-6);
    expect(Math.abs(track.values[3])).toBeCloseTo(1, 6);
  });

  it("ignores a unit-conversion scale on the FBX root when measuring hips height", () => {
    // Mixamo FBX files are cm with a 0.01 scale on the root: the position
    // track values stay in cm-LOCAL space, so the ratio must use the
    // local hips position (100), never getWorldPosition (1 m).
    const asset = fakeMixamoAsset();
    asset.scale.setScalar(0.01);
    const { report } = retargetMixamoClip(asset, fakeVrm(), "test");
    expect(report.hipsPositionScale).toBeCloseTo(0.0075, 6);
  });
});
