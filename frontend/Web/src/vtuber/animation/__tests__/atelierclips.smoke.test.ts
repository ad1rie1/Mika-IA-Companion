/**
 * The REAL motions of the Unity client's animation workshop
 * (frontend/Unity/ArtSource/atelier/motions/*.json.gz, served to the web
 * through the public/animations/atelier link): every one retargets onto a
 * VRM 0.x rig like hers, with finite values, and they say what they are —
 * arms down along the body at rest, a walk that moves at its own pace,
 * hips at the chair's height when seated. Node only (fs, zlib): excluded
 * from the app's typecheck like the other smoke tests.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import * as zlib from "node:zlib";
import * as THREE from "three";
import type { VRM } from "@pixiv/three-vrm";
import { describe, expect, it } from "vitest";
import { atelierDeltas, retargetAtelierClip, type AtelierMotion } from "../atelierClip";

const MOTIONS = path.resolve(__dirname, "../../../../../Unity/ArtSource/atelier/motions");
const LINK = path.resolve(__dirname, "../../../../public/animations/atelier");
const MANIFEST = path.resolve(__dirname, "../../../../public/animations/manifest.json");

function read(name: string): AtelierMotion {
  return JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(MOTIONS, `${name}.json.gz`))).toString("utf-8"));
}

const names = fs.existsSync(MOTIONS)
  ? fs.readdirSync(MOTIONS).filter((f) => f.endsWith(".json.gz")).map((f) => f.slice(0, -8))
  : [];

/** A normalized rig whose bones are found by name, parented like a VRM's (enough for the parent lookup). */
function stubVrm(): VRM {
  const root = new THREE.Object3D();
  const nodes = new Map<string, THREE.Object3D>();
  const chain: Record<string, string> = {
    spine: "hips", chest: "spine", upperChest: "chest", neck: "upperChest", head: "neck",
    leftShoulder: "upperChest", leftUpperArm: "leftShoulder", leftLowerArm: "leftUpperArm", leftHand: "leftLowerArm",
    rightShoulder: "upperChest", rightUpperArm: "rightShoulder", rightLowerArm: "rightUpperArm", rightHand: "rightLowerArm",
    leftUpperLeg: "hips", leftLowerLeg: "leftUpperLeg", leftFoot: "leftLowerLeg", leftToes: "leftFoot",
    rightUpperLeg: "hips", rightLowerLeg: "rightUpperLeg", rightFoot: "rightLowerLeg", rightToes: "rightFoot",
  };
  const node = (bone: string): THREE.Object3D => {
    let n = nodes.get(bone);
    if (n) return n;
    n = new THREE.Object3D();
    n.name = `Normalized_${bone}`;
    nodes.set(bone, n);
    (chain[bone] ? node(chain[bone]) : root).add(n);
    return n;
  };
  return {
    meta: { metaVersion: "0" },
    humanoid: {
      getNormalizedBoneNode: (bone: string) => node(bone),
      normalizedRestPose: { hips: { position: [0, 0.7829, 0.0039] } },
    },
  } as unknown as VRM;
}

describe.skipIf(names.length === 0)("the Unity workshop's motions on the web", () => {
  it("the web serves them through its link", () => {
    expect(fs.realpathSync(LINK)).toBe(fs.realpathSync(MOTIONS));
  });

  it("every workshop clip the manifest names exists", () => {
    const manifest = JSON.parse(fs.readFileSync(MANIFEST, "utf-8")) as { clips: Record<string, { url: string }> };
    for (const [name, entry] of Object.entries(manifest.clips)) {
      if (!entry.url.includes("/atelier/")) continue;
      expect(names, name).toContain(path.basename(entry.url, ".json.gz"));
    }
  });

  it.each(names)("%s retargets cleanly", (name) => {
    const { clip, report, measures } = retargetAtelierClip(read(name), stubVrm(), name);
    expect(report.mappedTracks).toBeGreaterThan(15);
    expect(report.hipsScaleSuspicious).toBe(false);
    expect(clip.duration).toBeGreaterThan(0.3);
    expect(clip.tracks.some((t) => t.name === "Normalized_hips.position")).toBe(true);
    for (const track of clip.tracks) expect(track.values.every((v) => Number.isFinite(v)), track.name).toBe(true);
    expect(measures.hipsHeight).toBeGreaterThan(0.5);
  });

  it("at rest her arms hang along her body, and her head is up", () => {
    const d = atelierDeltas(read("idle_breathing"));
    const leftArm = new THREE.Vector3(1, 0, 0).applyQuaternion(new THREE.Quaternion().fromArray(d.rotations.get("leftUpperArm")!, 0));
    const rightArm = new THREE.Vector3(-1, 0, 0).applyQuaternion(new THREE.Quaternion().fromArray(d.rotations.get("rightUpperArm")!, 0));
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(new THREE.Quaternion().fromArray(d.rotations.get("head")!, 0));
    expect(leftArm.y).toBeLessThan(-0.6);
    expect(rightArm.y).toBeLessThan(-0.6);
    expect(up.y).toBeGreaterThan(0.9);
  });

  it("the walk is played in place, at the pace it was captured", () => {
    const { measures } = retargetAtelierClip(read("walking"), stubVrm(), "walking");
    expect(measures.speed).toBeGreaterThan(0.7);
    expect(measures.speed).toBeLessThan(1.1);
  });

  it("seated, her hips are where the chair puts them (0.565–0.57 m)", () => {
    const { measures } = retargetAtelierClip(read("sitting_idle"), stubVrm(), "sitting_idle");
    expect(measures.hipsHeight).toBeGreaterThan(0.55);
    expect(measures.hipsHeight).toBeLessThan(0.59);
  });

  it("sitting down carries her hips back onto the seat, getting up carries them forward", () => {
    const sit = retargetAtelierClip(read("sit_down"), stubVrm(), "sit_down").measures.travel!;
    const stand = retargetAtelierClip(read("stand_up"), stubVrm(), "stand_up").measures.travel!;
    expect(sit.forward).toBeLessThan(-0.25);
    expect(stand.forward).toBeGreaterThan(0.25);
    expect(Math.abs(sit.right)).toBeLessThan(0.05);
  });

  it.each(names)("%s keeps her hips over the root (no body walking ahead of where she is)", (name) => {
    const { clip } = retargetAtelierClip(read(name), stubVrm(), name);
    const hips = clip.tracks.find((t) => t.name === "Normalized_hips.position")!;
    let far = 0;
    for (let i = 0; i < hips.values.length; i += 3) far = Math.max(far, Math.hypot(hips.values[i], hips.values[i + 2]));
    expect(far).toBeLessThan(0.2);
  });
});
