import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { OverlayContext } from "../overlays/Overlay";
import {
  HEAD_MAX_YAW,
  HeadAttentionOverlay,
  viewerReachable,
} from "../overlays/HeadAttentionOverlay";
import type { GazeIntent } from "../attention";
import { makeRig, worldDirectionTo, worldForward } from "./rigFixtures";

const contact: GazeIntent = {
  state: "contact",
  contact: 1,
  offset: { pitch: 0, yaw: 0 },
  saccade: { pitch: 0, yaw: 0 },
  shift: 0,
};

/** Angle (rad) between the head's forward and the direction to the camera. */
function headError(rig: ReturnType<typeof makeRig>, camera: THREE.Object3D): number {
  const head = rig.nodes.get("head")!;
  const f = worldForward(head, rig.sign);
  const d = worldDirectionTo(head, camera.position);
  return Math.acos(Math.max(-1, Math.min(1, f.dot(d))));
}

function run(
  rig: ReturnType<typeof makeRig>,
  ctx: OverlayContext,
  overlay: HeadAttentionOverlay,
  seconds: number,
  poseClip: () => void = () => {}
) {
  const frames = Math.round(seconds * 60);
  for (let i = 0; i < frames; i++) {
    // The mixer rewrites every bone each frame; the overlay adds on top.
    rig.vrm.humanoid!.resetNormalizedPose();
    poseClip();
    overlay.update(1 / 60, ctx);
  }
}

describe.each([["0"], ["1"]] as const)("HeadAttentionOverlay on a VRM %s rig", (version) => {
  it("turns the head most of the way toward a viewer 30° to the side", () => {
    const rig = makeRig(version);
    const ctx = new OverlayContext(rig.vrm);
    const camera = new THREE.Object3D();
    camera.position.set(rig.sign * Math.sin(0.52) * 2, 1.66, rig.sign * Math.cos(0.52) * 2);
    ctx.camera = camera;
    ctx.attention = contact;
    const overlay = new HeadAttentionOverlay();

    const before = headError(rig, camera);
    run(rig, ctx, overlay, 2);
    const after = headError(rig, camera);

    expect(before).toBeGreaterThan(0.45);
    // HEAD_FOLLOW 0.7 past the dead zone: the residual stays for the eyes.
    expect(after).toBeLessThan(before * 0.45);
    expect(after).toBeGreaterThan(0.05);
    expect(ctx.viewerMeasured).toBe(true);
  });

  it("a viewer straight ahead within the dead zone leaves the head alone", () => {
    const rig = makeRig(version);
    const ctx = new OverlayContext(rig.vrm);
    const camera = new THREE.Object3D();
    camera.position.set(rig.sign * 0.05, 1.66, rig.sign * 2);
    ctx.camera = camera;
    ctx.attention = contact;
    const overlay = new HeadAttentionOverlay();
    run(rig, ctx, overlay, 2);
    expect(rig.nodes.get("head")!.quaternion.angleTo(new THREE.Quaternion())).toBeLessThan(0.01);
  });

  it("a viewer behind her is out of reach: no twist, forward gaze", () => {
    const rig = makeRig(version);
    const ctx = new OverlayContext(rig.vrm);
    const camera = new THREE.Object3D();
    camera.position.set(0.3, 1.66, -rig.sign * 2);
    ctx.camera = camera;
    ctx.attention = contact;
    const overlay = new HeadAttentionOverlay();
    run(rig, ctx, overlay, 2);
    expect(ctx.viewerMeasured).toBe(true);
    expect(viewerReachable(ctx.viewerYaw, ctx.viewerPitch)).toBe(false);
    expect(rig.nodes.get("head")!.quaternion.angleTo(new THREE.Quaternion())).toBeLessThan(0.01);
  });

  it("the turn is bounded by HEAD_MAX_YAW even for a viewer at 75°", () => {
    const rig = makeRig(version);
    const ctx = new OverlayContext(rig.vrm);
    const camera = new THREE.Object3D();
    camera.position.set(rig.sign * Math.sin(1.3) * 2, 1.66, rig.sign * Math.cos(1.3) * 2);
    ctx.camera = camera;
    ctx.attention = contact;
    const overlay = new HeadAttentionOverlay();
    run(rig, ctx, overlay, 3);
    const neck = rig.nodes.get("neck")!;
    const head = rig.nodes.get("head")!;
    const total = neck.quaternion.angleTo(new THREE.Quaternion()) + head.quaternion.angleTo(new THREE.Quaternion());
    expect(total).toBeLessThanOrEqual(HEAD_MAX_YAW + 0.02);
    expect(total).toBeGreaterThan(0.3);
  });

  it("measures the viewer in the CLIP pose, not in its own closed loop (no runaway)", () => {
    const rig = makeRig(version);
    const ctx = new OverlayContext(rig.vrm);
    const camera = new THREE.Object3D();
    camera.position.set(rig.sign * Math.sin(0.4) * 2, 1.66, rig.sign * Math.cos(0.4) * 2);
    ctx.camera = camera;
    ctx.attention = contact;
    const overlay = new HeadAttentionOverlay();
    run(rig, ctx, overlay, 2);
    const settled = headError(rig, camera);
    run(rig, ctx, overlay, 4);
    // Four more seconds change nothing: the target is a fraction of the
    // clip-frame angle, and that angle does not include the overlay's turn.
    expect(Math.abs(headError(rig, camera) - settled)).toBeLessThan(0.005);
  });

  it("asleep the head is left to the sleep overlay", () => {
    const rig = makeRig(version);
    const ctx = new OverlayContext(rig.vrm);
    const camera = new THREE.Object3D();
    camera.position.set(rig.sign * 1, 1.66, rig.sign * 2);
    ctx.camera = camera;
    ctx.attention = contact;
    ctx.sleepPhase = "rem";
    const overlay = new HeadAttentionOverlay();
    run(rig, ctx, overlay, 2);
    expect(ctx.viewerMeasured).toBe(false);
    expect(rig.nodes.get("head")!.quaternion.angleTo(new THREE.Quaternion())).toBeLessThan(0.01);
  });

  it("an aversion offset turns the head partly even when the viewer is out of reach", () => {
    const rig = makeRig(version);
    const ctx = new OverlayContext(rig.vrm);
    const camera = new THREE.Object3D();
    camera.position.set(0, 1.66, -rig.sign * 2); // behind
    ctx.camera = camera;
    ctx.attention = { ...contact, contact: 0, offset: { pitch: -0.2, yaw: 0 } };
    const overlay = new HeadAttentionOverlay();
    run(rig, ctx, overlay, 2);
    // Semantic pitch −0.2 = up, on both rigs.
    expect(worldForward(rig.nodes.get("head")!, rig.sign).y).toBeGreaterThan(0.05);
  });
});
