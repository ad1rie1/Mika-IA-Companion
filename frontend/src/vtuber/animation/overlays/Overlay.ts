import * as THREE from "three";
import { VRM } from "@pixiv/three-vrm";
import type { VRMHumanBoneName } from "@pixiv/three-vrm";
import type { EmotionName, SleepPhase } from "../../../types";

const _q = new THREE.Quaternion();
const _e = new THREE.Euler();

/**
 * Shared per-frame context for procedural overlays. Overlays run AFTER
 * the clip mixer and compose small deltas ON TOP of the clip pose —
 * `addRotation` post-multiplies a quaternion, it never writes absolute
 * Euler values. Absolute writes cannot coexist with an AnimationMixer;
 * that constraint killed the previous architecture.
 */
export class OverlayContext {
  sleepPhase: SleepPhase = "awake";
  emotion: EmotionName = "neutral";
  intensity = 0.5;
  speaking = false;

  constructor(readonly vrm: VRM) {}

  /** Post-multiply a small Euler delta in the bone's CURRENT
   * (clip-posed) local frame. */
  addRotation(bone: VRMHumanBoneName, x: number, y: number, z: number): void {
    const node = this.vrm.humanoid?.getNormalizedBoneNode(bone);
    if (!node) return;
    node.quaternion.multiply(_q.setFromEuler(_e.set(x, y, z, "XYZ")));
  }
}

export interface ProceduralOverlay {
  update(dt: number, ctx: OverlayContext): void;
}
