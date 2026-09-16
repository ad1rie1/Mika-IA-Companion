import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { applyRestPose, buildRestClip } from "../ClipLibrary";
import { HandAnimator } from "../HandAnimator";
import { forwardSign } from "../../vrmVersion";
import { makeRig } from "./rigFixtures";

/**
 * The rest pose and the finger curls were hand-tuned on a VRM 0.x rig.
 * Authoring them in the 1.0 convention and conjugating by forwardSign
 * must reproduce those tuned values byte-for-byte on a 0.x — and mirror
 * them on a 1.0, where the raw values raised both arms into a V.
 */
describe("rest pose across rig conventions", () => {
  it("reproduces the historical VRM 0.x values exactly", () => {
    const rig = makeRig("0");
    expect(forwardSign(rig.vrm)).toBe(-1);
    applyRestPose(rig.vrm);
    const expected = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, 1.15));
    expect(rig.nodes.get("leftUpperArm")!.quaternion.angleTo(expected)).toBeLessThan(1e-6);
    const expectedRight = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, -1.15));
    expect(rig.nodes.get("rightUpperArm")!.quaternion.angleTo(expectedRight)).toBeLessThan(1e-6);
  });

  it.each([["0"], ["1"]] as const)("drops the arms DOWN on a VRM %s rig", (version) => {
    const rig = makeRig(version);
    applyRestPose(rig.vrm);
    // The left arm runs along her left (+X on a 1.0, −X on a 0.x): after
    // the rest pose its direction must point downward on either rig.
    const leftAlong = new THREE.Vector3(rig.sign, 0, 0);
    const posed = leftAlong.clone().applyQuaternion(rig.nodes.get("leftUpperArm")!.quaternion);
    expect(posed.y).toBeLessThan(-0.8);
    const rightAlong = new THREE.Vector3(-rig.sign, 0, 0);
    const posedRight = rightAlong.clone().applyQuaternion(rig.nodes.get("rightUpperArm")!.quaternion);
    expect(posedRight.y).toBeLessThan(-0.8);
  });

  it("the synthetic rest clip carries the same pose as applyRestPose", () => {
    for (const version of ["0", "1"] as const) {
      const rig = makeRig(version);
      const clip = buildRestClip(rig.vrm);
      applyRestPose(rig.vrm);
      const track = clip.tracks.find((t) => t.name === "Normalized_leftUpperArm.quaternion")!;
      const q = new THREE.Quaternion().fromArray(Array.from(track.values), 0);
      expect(q.angleTo(rig.nodes.get("leftUpperArm")!.quaternion)).toBeLessThan(1e-6);
    }
  });
});

describe("finger curl across rig conventions", () => {
  function fingerRig(version: "0" | "1") {
    const nodes = new Map<string, THREE.Object3D>();
    const vrm = {
      meta: { metaVersion: version },
      humanoid: {
        getNormalizedBoneNode: (name: string) => {
          let n = nodes.get(name);
          if (!n) {
            n = new THREE.Object3D();
            n.name = name;
            nodes.set(name, n);
          }
          return n;
        },
      },
    } as never;
    return { vrm, nodes };
  }

  it("keeps the verified VRM 0.x signs: left curl +Z, right curl −Z", () => {
    const { vrm, nodes } = fingerRig("0");
    const hands = new HandAnimator();
    hands.setVRM(vrm);
    for (let i = 0; i < 60; i++) hands.update(1 / 60);
    expect(nodes.get("leftIndexProximal")!.rotation.z).toBeGreaterThan(0.05);
    expect(nodes.get("rightIndexProximal")!.rotation.z).toBeLessThan(-0.05);
    // The thumb rotates about Y and does not flip with the convention.
    expect(nodes.get("leftThumbMetacarpal")!.rotation.y).toBeGreaterThan(0);
    expect(nodes.get("rightThumbMetacarpal")!.rotation.y).toBeLessThan(0);
  });

  it("mirrors the curl on a VRM 1.0, and only the curl", () => {
    const { vrm, nodes } = fingerRig("1");
    const hands = new HandAnimator();
    hands.setVRM(vrm);
    for (let i = 0; i < 60; i++) hands.update(1 / 60);
    expect(nodes.get("leftIndexProximal")!.rotation.z).toBeLessThan(-0.05);
    expect(nodes.get("rightIndexProximal")!.rotation.z).toBeGreaterThan(0.05);
    expect(nodes.get("leftThumbMetacarpal")!.rotation.y).toBeGreaterThan(0);
    expect(nodes.get("rightThumbMetacarpal")!.rotation.y).toBeLessThan(0);
    // Spread (about Y) keeps its side sign too.
    const v0 = fingerRig("0");
    const h0 = new HandAnimator();
    h0.setVRM(v0.vrm);
    for (let i = 0; i < 60; i++) h0.update(1 / 60);
    expect(Math.sign(nodes.get("leftIndexProximal")!.rotation.y)).toBe(
      Math.sign(v0.nodes.get("leftIndexProximal")!.rotation.y)
    );
  });
});
