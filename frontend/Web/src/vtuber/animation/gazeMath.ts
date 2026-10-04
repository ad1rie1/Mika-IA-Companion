import * as THREE from "three";
import type { VRMHumanoid } from "@pixiv/three-vrm";

/**
 * Semantic gaze angles, in radians, independent of the rig's forward axis:
 *   pitch > 0 = look DOWN,  yaw > 0 = toward HER OWN LEFT (the viewer's
 *   right when she faces the screen).
 *
 * `sign` is `forwardSign(vrm)`: +1 for a rig facing +Z (VRM 1.0), −1 for
 * one facing −Z (VRM 0.x). Under Euler order YXZ the formulas below are
 * exact, not small-angle: for forward f = (0,0,s), R_y(yaw)·R_x(x)·f =
 * (s·cos x·sin yaw, −s·sin x, s·cos x·cos yaw), so a direction d gives
 * yaw = atan2(s·d.x, s·d.z) and x = −s·asin(d.y). The semantic pitch is
 * −asin(d.y) (positive when the target is below), hence x = s·pitch — the
 * only place the rig convention enters.
 */
export interface GazeAngles {
  pitch: number;
  yaw: number;
}

const _euler = new THREE.Euler();
const _m = new THREE.Matrix4();

export function clampGaze(g: GazeAngles, maxPitch: number, maxYaw: number): GazeAngles {
  g.pitch = Math.max(-maxPitch, Math.min(maxPitch, g.pitch));
  g.yaw = Math.max(-maxYaw, Math.min(maxYaw, g.yaw));
  return g;
}

/** Semantic angles of a direction expressed in a bone's local frame. A
 * zero-length direction reads as straight ahead rather than NaN. */
export function directionToGaze(
  d: THREE.Vector3,
  sign: 1 | -1,
  out: GazeAngles
): GazeAngles {
  const len = d.length();
  if (len < 1e-9) {
    out.pitch = 0;
    out.yaw = 0;
    return out;
  }
  const y = Math.max(-1, Math.min(1, d.y / len));
  out.pitch = -Math.asin(y);
  out.yaw = Math.atan2(sign * d.x, sign * d.z);
  return out;
}

/** Local rotation that turns a bone's forward axis toward the given
 * semantic angles (yaw first, then pitch about the yawed X axis). */
export function gazeToQuaternion(
  g: GazeAngles,
  sign: 1 | -1,
  out: THREE.Quaternion
): THREE.Quaternion {
  _euler.set(sign * g.pitch, g.yaw, 0, "YXZ");
  return out.setFromEuler(_euler);
}

/**
 * Direction from a point of `frame`'s local space toward a world position,
 * in `frame`'s local axes. `frame.matrixWorld` must be current — callers
 * `updateWorldMatrix(true, false)` first, since bones are re-posed every
 * frame before the render pass refreshes matrices.
 */
export function localDirectionTo(
  frame: THREE.Object3D,
  originLocal: THREE.Vector3,
  worldTarget: THREE.Vector3,
  out: THREE.Vector3
): THREE.Vector3 {
  out.copy(worldTarget).applyMatrix4(_m.copy(frame.matrixWorld).invert());
  return out.sub(originLocal);
}

/** Midpoint of the two eye bones in the head's local frame (their normalized
 * rest offsets — constant), or the head origin when the model has no eye
 * bones. A 7 cm eye/head offset is a 4° error at arm's length, enough to
 * make "eye contact" land on the brow. */
export function eyesLocalOrigin(
  humanoid: Pick<VRMHumanoid, "getNormalizedBoneNode">,
  out: THREE.Vector3
): THREE.Vector3 {
  const left = humanoid.getNormalizedBoneNode("leftEye");
  const right = humanoid.getNormalizedBoneNode("rightEye");
  out.set(0, 0, 0);
  if (left && right) return out.addVectors(left.position, right.position).multiplyScalar(0.5);
  if (left) return out.copy(left.position);
  if (right) return out.copy(right.position);
  return out;
}
