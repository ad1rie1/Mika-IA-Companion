import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { GazeController, EYE_MAX_YAW } from "../GazeController";
import { OverlayContext } from "../overlays/Overlay";
import { SleepOverlay } from "../overlays/SleepOverlay";
import { HeadEmotionOverlay } from "../overlays/HeadEmotionOverlay";
import { directionToGaze, gazeToQuaternion } from "../gazeMath";
import type { GazeIntent } from "../attention";
import { makeRig, worldDirectionTo, worldForward } from "./rigFixtures";

/**
 * Every assertion here is GEOMETRIC — "the eye's forward vector points at
 * the camera", "the head's forward vector tips down" — never a check on
 * a sign constant. The rig convention (a VRM 0.x faces −Z, a 1.0 faces +Z)
 * is the one thing that must not be trusted from a comment: the previous
 * overlays wrote +Z-convention pitches onto the user's −Z model, so `sad`
 * raised the chin and the sleep doze tilted the head back.
 */

const contact: GazeIntent = {
  state: "contact",
  contact: 1,
  offset: { pitch: 0, yaw: 0 },
  saccade: { pitch: 0, yaw: 0 },
  shift: 0,
};

function settle(gaze: GazeController, intent: GazeIntent | null, frames = 30) {
  for (let i = 0; i < frames; i++) gaze.update(1 / 60, intent);
}

describe.each([["0"], ["1"]] as const)("gaze geometry on a VRM %s rig", (version) => {
  it("directionToGaze ↔ gazeToQuaternion round-trip on the rig's forward axis", () => {
    const sign = version === "0" ? -1 : 1;
    const targets = [
      new THREE.Vector3(0.3, 0.2, sign * 1),
      new THREE.Vector3(-0.4, -0.3, sign * 1),
      new THREE.Vector3(0.1, 0.5, sign * 0.8),
    ];
    for (const target of targets) {
      const g = directionToGaze(target, sign, { pitch: 0, yaw: 0 });
      const q = gazeToQuaternion(g, sign, new THREE.Quaternion());
      const forward = new THREE.Vector3(0, 0, sign).applyQuaternion(q);
      expect(forward.dot(target.clone().normalize())).toBeGreaterThan(0.9999);
      // Semantic meaning is convention-free: below = pitch > 0.
      expect(Math.sign(g.pitch)).toBe(-Math.sign(target.y));
    }
  });

  it("eyes land ON the camera when it sits within the eye range", () => {
    const rig = makeRig(version);
    const gaze = new GazeController();
    gaze.setVRM(rig.vrm);
    // 8° up and 8° to her left, 2 m away — inside EYE_MAX on both axes.
    const eye = rig.nodes.get("leftEye")!;
    eye.updateWorldMatrix(true, false);
    const origin = new THREE.Vector3();
    eye.getWorldPosition(origin);
    const dir = new THREE.Vector3(
      Math.sin(0.14) * rig.sign,
      Math.sin(0.14),
      rig.sign * Math.cos(0.14)
    ).normalize();
    const camera = new THREE.Object3D();
    camera.position.copy(origin).addScaledVector(dir, 2);
    gaze.setCamera(camera);

    settle(gaze, contact);
    const forward = worldForward(eye, rig.sign);
    const toCamera = worldDirectionTo(eye, camera.position);
    expect(forward.dot(toCamera)).toBeGreaterThan(0.995);
  });

  it("a camera above makes the eyes look up, one below makes them look down", () => {
    const rig = makeRig(version);
    const gaze = new GazeController();
    gaze.setVRM(rig.vrm);
    const eye = rig.nodes.get("rightEye")!;
    const camera = new THREE.Object3D();
    gaze.setCamera(camera);

    camera.position.set(0, 3.0, rig.sign * 1.5);
    settle(gaze, contact);
    expect(worldForward(eye, rig.sign).y).toBeGreaterThan(0.1);

    camera.position.set(0, 0.2, rig.sign * 1.5);
    settle(gaze, contact);
    expect(worldForward(eye, rig.sign).y).toBeLessThan(-0.1);
  });

  it("a camera far to the side stops at the corner of the eye, never past EYE_MAX", () => {
    const rig = makeRig(version);
    const gaze = new GazeController();
    gaze.setVRM(rig.vrm);
    const camera = new THREE.Object3D();
    // 70° to the side: well past what an eye bone may show.
    camera.position.set(rig.sign * 2.7, 1.66, rig.sign * 1);
    gaze.setCamera(camera);
    settle(gaze, contact);
    expect(Math.abs(gaze.applied.yaw)).toBeLessThanOrEqual(EYE_MAX_YAW + 1e-6);
    expect(Math.abs(gaze.applied.yaw)).toBeGreaterThan(EYE_MAX_YAW - 0.01);
  });

  it("the eyes compensate a head turn: contact holds when the clip swings the head (VOR)", () => {
    const rig = makeRig(version);
    const gaze = new GazeController();
    gaze.setVRM(rig.vrm);
    const camera = new THREE.Object3D();
    const eye = rig.nodes.get("leftEye")!;
    camera.position.set(0, 1.66, rig.sign * 2);
    gaze.setCamera(camera);
    settle(gaze, contact);
    const before = worldForward(eye, rig.sign).dot(worldDirectionTo(eye, camera.position));

    // The clip turns the head 12° — the eyes must counter-rotate.
    rig.nodes.get("head")!.quaternion.setFromEuler(new THREE.Euler(0, 0.21, 0));
    settle(gaze, contact);
    const after = worldForward(eye, rig.sign).dot(worldDirectionTo(eye, camera.position));
    expect(before).toBeGreaterThan(0.999);
    expect(after).toBeGreaterThan(0.999);
    // And the eye really did rotate relative to the head.
    expect(Math.abs(gaze.applied.yaw)).toBeGreaterThan(0.15);
  });

  it("with no viewer (contact 0) an aversion offset still reads as its direction", () => {
    const rig = makeRig(version);
    const gaze = new GazeController();
    gaze.setVRM(rig.vrm);
    const eye = rig.nodes.get("leftEye")!;
    const down: GazeIntent = { ...contact, contact: 0, offset: { pitch: 0.15, yaw: 0 } };
    settle(gaze, down);
    expect(worldForward(eye, rig.sign).y).toBeLessThan(-0.1);
  });

  it("asleep the eyes rest slightly downward, on both rigs", () => {
    const rig = makeRig(version);
    const gaze = new GazeController();
    gaze.setVRM(rig.vrm);
    gaze.setSleepPhase("deep_sleep");
    settle(gaze, contact);
    expect(worldForward(rig.nodes.get("leftEye")!, rig.sign).y).toBeLessThan(-0.03);
  });
});

describe.each([["0"], ["1"]] as const)("overlay pitch semantics on a VRM %s rig", (version) => {
  it("addRotation(head, +x) pitches the head DOWN", () => {
    const rig = makeRig(version);
    const ctx = new OverlayContext(rig.vrm);
    ctx.addRotation("head", 0.2, 0, 0);
    expect(worldForward(rig.nodes.get("head")!, rig.sign).y).toBeLessThan(-0.15);
  });

  it("the sleep doze tilts the head forward, never back", () => {
    const rig = makeRig(version);
    const ctx = new OverlayContext(rig.vrm);
    ctx.sleepPhase = "deep_sleep";
    const overlay = new SleepOverlay();
    for (let i = 0; i < 240; i++) {
      rig.vrm.humanoid!.resetNormalizedPose();
      overlay.update(1 / 60, ctx);
    }
    expect(worldForward(rig.nodes.get("head")!, rig.sign).y).toBeLessThan(-0.15);
  });

  it("sad lowers the head, proud raises the chin", () => {
    const rig = makeRig(version);
    const ctx = new OverlayContext(rig.vrm);
    const overlay = new HeadEmotionOverlay();
    const run = () => {
      for (let i = 0; i < 240; i++) {
        rig.vrm.humanoid!.resetNormalizedPose();
        overlay.update(1 / 60, ctx);
      }
      return worldForward(rig.nodes.get("head")!, rig.sign).y;
    };
    ctx.emotion = "sad";
    ctx.intensity = 1;
    expect(run()).toBeLessThan(-0.03);
    ctx.emotion = "proud";
    expect(run()).toBeGreaterThan(0.02);
  });
});
