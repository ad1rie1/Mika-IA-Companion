import * as THREE from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";
import { forwardSign } from "../vrmVersion";

/**
 * Body clips built in code on the normalized rig: a walk cycle, a seated
 * pose and a lying pose. There is no Mixamo walk on disk (and a sitting
 * clip would have to match each seat's height); these are the defaults,
 * and a manifest `locomotion` clip, when one is downloaded, replaces the
 * walk.
 *
 * Everything is authored in the VRM 1.0 convention — the rig faces +Z,
 * its left side is +X; +X rotation bends a segment's far end toward −Z
 * (backward for a leg, so a forward leg swing is a NEGATIVE X rotation,
 * and a knee bends with a positive one) — then conjugated by Ry(π) for a
 * VRM 0.x rig: quaternion (x, y, z, w) → (−x, y, −z, w), position
 * (x, y, z) → (−x, y, −z). The same rule as every overlay.
 */

export const WALK_CLIP_NAME = "__walk__";
export const SIT_CLIP_NAME = "__sit__";
export const LIE_CLIP_NAME = "__lie__";

/** One walk cycle (two steps), seconds, at playback speed 1. */
export const WALK_PERIOD = 1.05;
/** Ground covered per cycle at playback speed 1 (m) — what the root must
 * travel for the feet not to slide. Sized for her ~0.68 m legs. */
export const WALK_STRIDE = 0.74;
export const WALK_SPEED = WALK_STRIDE / WALK_PERIOD;

/** How far below the standing hips the seated hips sit above the seat. */
export const SEAT_HIPS_ABOVE = 0.06;

const SAMPLES = 24;

const _e = new THREE.Euler();

/** A-pose arm drop (same values as ClipLibrary.REST_ARM_POSE). */
const ARM_DROP = 1.15;

type Pose = Partial<Record<VRMHumanBoneName, THREE.Quaternion>>;

function euler(x: number, y: number, z: number): THREE.Quaternion {
  return new THREE.Quaternion().setFromEuler(_e.set(x, y, z, "XYZ"));
}

/** Arm in the A-pose, then swung about the parent's X (forward = −). */
function arm(side: 1 | -1, swing: number, abduct = 0): THREE.Quaternion {
  // side +1 = left (+X), its drop is a negative Z.
  const drop = euler(0, 0, -side * (ARM_DROP - abduct));
  return euler(swing, 0, 0).multiply(drop);
}

/** Elbow: the rest bend plus a forward flex (about the upper arm's Y). */
function forearm(side: 1 | -1, flex: number): THREE.Quaternion {
  return euler(0, 0, -side * 0.1).multiply(euler(0, -side * flex, 0));
}

function conjugate(q: THREE.Quaternion, sign: 1 | -1): THREE.Quaternion {
  return sign === 1 ? q : new THREE.Quaternion(-q.x, q.y, -q.z, q.w);
}

function restHipsY(vrm: VRM): number {
  const humanoid = vrm.humanoid;
  const rest = (humanoid as unknown as { normalizedRestPose?: Record<string, { position?: number[] }> })
    ?.normalizedRestPose?.hips?.position;
  if (rest && Number.isFinite(rest[1])) return rest[1];
  return humanoid?.getNormalizedBoneNode("hips")?.position.y ?? 0.75;
}

function restHips(vrm: VRM): THREE.Vector3 {
  const humanoid = vrm.humanoid;
  const rest = (humanoid as unknown as { normalizedRestPose?: Record<string, { position?: number[] }> })
    ?.normalizedRestPose?.hips?.position;
  if (rest && rest.every(Number.isFinite)) return new THREE.Vector3(rest[0], rest[1], rest[2]);
  const node = humanoid?.getNormalizedBoneNode("hips");
  return node ? node.position.clone() : new THREE.Vector3(0, restHipsY(vrm), 0);
}

/** Standing hips height of the rig (m) — what a seat lowers the root by. */
export function standingHipsHeight(vrm: VRM): number {
  return restHipsY(vrm);
}

/** Amplitude (rad) of the sway given to a track the sample left constant —
 * far below anything visible, far above float rounding. */
const STILL_SWAY = 1e-4;

/**
 * A constant quaternion track gets an imperceptible sway about the bone's
 * own X: the mixer only writes a bone whose value changed since the last
 * frame, and AnimationSystem resets the pose before every mixer pass, so a
 * still track would be written once and then left at rest (see the
 * postures below). One full sway per loop, so the seam stays continuous;
 * `k` staggers the tracks.
 */
function keepWritten(values: number[], times: number[], duration: number, k: number): number[] {
  const first = values.slice(0, 4);
  if (duration <= 0 || values.some((v, i) => v !== first[i % 4])) return values;
  const q = new THREE.Quaternion(first[0], first[1], first[2], first[3]);
  const out: number[] = [];
  for (const t of times) {
    const s = q.clone().multiply(euler(STILL_SWAY * Math.sin((2 * Math.PI * t) / duration + k), 0, 0));
    out.push(s.x, s.y, s.z, s.w);
  }
  return out;
}

/** `hips` in a sample is an OFFSET from the rig's rest hips, authored in
 * the 1.0 convention; the rest position itself is the rig's own and is
 * never conjugated. */
function buildClip(
  vrm: VRM,
  name: string,
  duration: number,
  times: number[],
  sample: (phase: number) => { pose: Pose; hips?: THREE.Vector3 }
): THREE.AnimationClip {
  const humanoid = vrm.humanoid;
  const sign = forwardSign(vrm);
  const rest = restHips(vrm);
  const rot = new Map<VRMHumanBoneName, number[]>();
  const pos: number[] = [];
  for (const t of times) {
    const { pose, hips } = sample(duration > 0 ? t / duration : 0);
    for (const [bone, q] of Object.entries(pose) as [VRMHumanBoneName, THREE.Quaternion][]) {
      const c = conjugate(q, sign);
      let arr = rot.get(bone);
      if (!arr) rot.set(bone, (arr = []));
      arr.push(c.x, c.y, c.z, c.w);
    }
    if (hips) pos.push(rest.x + sign * hips.x, rest.y + hips.y, rest.z + sign * hips.z);
  }
  const tracks: THREE.KeyframeTrack[] = [];
  for (const [bone, values] of rot) {
    const node = humanoid?.getNormalizedBoneNode(bone);
    if (!node || values.length !== times.length * 4) continue;
    const kept = keepWritten(values, times, duration, tracks.length);
    tracks.push(new THREE.QuaternionKeyframeTrack(`${node.name}.quaternion`, times, kept));
  }
  const hipsNode = humanoid?.getNormalizedBoneNode("hips");
  if (hipsNode && pos.length === times.length * 3) {
    tracks.push(new THREE.VectorKeyframeTrack(`${hipsNode.name}.position`, times, pos));
  }
  return new THREE.AnimationClip(name, duration, tracks);
}

/**
 * The walk cycle. Phase 0 = left heel strike. The thigh swings ±0.3 rad
 * (her step is ~0.37 m), the knee folds in swing and gives a little at
 * loading, the planted foot stays flat (the ankle cancels hip + knee) and
 * the swinging toes lift; the hips dip at double support and ride over the
 * stance leg, the pelvis turns with the swinging leg and the chest turns
 * against it; the arms swing opposite to the legs with a soft elbow.
 */
export function buildWalkClip(vrm: VRM): THREE.AnimationClip {
  const times = Array.from({ length: SAMPLES + 1 }, (_, i) => (i / SAMPLES) * WALK_PERIOD);
  return buildClip(vrm, WALK_CLIP_NAME, WALK_PERIOD, times, (p) => {
    const w = 2 * Math.PI * p;
    const pose: Pose = {};
    for (const side of [1, -1] as const) {
      // Left leads at phase 0, right half a cycle later.
      const ph = side === 1 ? w : w + Math.PI;
      const thigh = 0.3 * Math.cos(ph); // + = forward
      const swing = Math.max(0, Math.sin(ph - Math.PI)); // swing phase bump
      const load = Math.max(0, Math.sin(ph * 2)) * (Math.cos(ph) > 0 ? 1 : 0);
      const knee = 0.06 + 0.62 * swing + 0.1 * load;
      const ankle = 0.85 * (thigh - knee) * (1 - swing) - 0.12 * swing;
      const leg = side === 1 ? "left" : "right";
      pose[`${leg}UpperLeg` as VRMHumanBoneName] = euler(-thigh, 0, 0);
      pose[`${leg}LowerLeg` as VRMHumanBoneName] = euler(knee, 0, 0);
      pose[`${leg}Foot` as VRMHumanBoneName] = euler(-ankle, 0, 0);
      // Arms swing opposite to the same-side leg.
      const armSwing = 0.22 * Math.cos(ph + Math.PI);
      const armSide = side;
      pose[`${leg}UpperArm` as VRMHumanBoneName] = arm(armSide, -armSwing, 0.05);
      pose[`${leg}LowerArm` as VRMHumanBoneName] = forearm(armSide, 0.25 + 0.15 * Math.max(0, armSwing / 0.22));
    }
    const pelvisYaw = -0.07 * Math.cos(w);
    pose.hips = euler(0, pelvisYaw, 0.025 * Math.sin(w));
    pose.spine = euler(0.05, -pelvisYaw * 0.6, -0.02 * Math.sin(w));
    pose.chest = euler(0.02, -pelvisYaw * 0.9, 0);
    pose.neck = euler(-0.03, pelvisYaw * 0.5, 0);
    const bob = 0.03 * Math.cos(2 * w) * 0.5 + 0.015; // dip at double support
    const hips = new THREE.Vector3(0.016 * Math.sin(w), -0.012 - bob, 0);
    return { pose, hips };
  });
}

/**
 * Postures are LOOPS, never single frames, and that is load-bearing: the
 * mixer's PropertyMixer only writes a bone when its value changed since the
 * previous frame, while AnimationSystem resets the normalized pose before
 * every mixer pass — a perfectly still clip is written once, wiped by the
 * next reset, and never written again (she stood straight inside the
 * chair). A slow, small motion keeps every bone written, and is what a
 * body at rest does anyway; a bone the pose below holds still (hips,
 * forearms, a resting leg) gets the imperceptible sway of `keepWritten`.
 */
const SIT_PERIOD = 4.6;
const LIE_PERIOD = 6.2;

/**
 * Seated, on a seat whose top is SEAT_HIPS_ABOVE below the hips. The root
 * is lowered by the locomotion controller (one clip for every seat height):
 * the hips keep their rest height in the clip. She is small and most seats
 * leave her feet off the floor: they swing a little, out of step.
 */
export function buildSitClip(vrm: VRM): THREE.AnimationClip {
  const times = Array.from({ length: SAMPLES + 1 }, (_, i) => (i / SAMPLES) * SIT_PERIOD);
  return buildClip(vrm, SIT_CLIP_NAME, SIT_PERIOD, times, (p) => {
    const w = 2 * Math.PI * p;
    const pose: Pose = {
      hips: euler(-0.08, 0, 0),
      spine: euler(0.1 + 0.008 * Math.sin(w), 0.01 * Math.sin(w + 1), 0),
      chest: euler(0.04, 0, 0),
      neck: euler(-0.04, 0, 0),
      leftUpperLeg: euler(-1.48 + 0.015 * Math.sin(w + 0.5), 0, 0.06),
      rightUpperLeg: euler(-1.48 + 0.015 * Math.sin(w + 2.4), 0, -0.06),
      leftLowerLeg: euler(1.36 + 0.07 * Math.sin(w), 0, 0),
      rightLowerLeg: euler(1.36 + 0.07 * Math.sin(w + 2.2), 0, 0),
      leftFoot: euler(0.1 + 0.05 * Math.sin(w - 0.6), 0, 0),
      rightFoot: euler(0.1 + 0.05 * Math.sin(w + 1.6), 0, 0),
      // Hands resting on the thighs.
      leftUpperArm: arm(1, -0.42 + 0.01 * Math.sin(w + 0.3), 0.12),
      rightUpperArm: arm(-1, -0.42 + 0.01 * Math.sin(w + 1.9), 0.12),
      leftLowerArm: forearm(1, 0.85),
      rightLowerArm: forearm(-1, 0.85),
    };
    return { pose, hips: new THREE.Vector3() };
  });
}

/** Lying on her back, legs nearly straight, arms along the body, head
 * turned a little toward the room. The root carries the 90° rotation. */
export function buildLieClip(vrm: VRM): THREE.AnimationClip {
  const times = Array.from({ length: SAMPLES + 1 }, (_, i) => (i / SAMPLES) * LIE_PERIOD);
  return buildClip(vrm, LIE_CLIP_NAME, LIE_PERIOD, times, (p) => {
    const w = 2 * Math.PI * p;
    const pose: Pose = {
      spine: euler(-0.04 + 0.006 * Math.sin(w), 0, 0),
      neck: euler(0.08, 0.15, 0),
      head: euler(0.06, 0.2 + 0.01 * Math.sin(w + 1), 0.04),
      leftUpperLeg: euler(-0.12, 0, 0.04),
      rightUpperLeg: euler(-0.08 + 0.01 * Math.sin(w + 2), 0, -0.06),
      leftLowerLeg: euler(0.2, 0, 0),
      rightLowerLeg: euler(0.12 + 0.015 * Math.sin(w + 2), 0, 0),
      leftFoot: euler(0.35, 0, 0),
      rightFoot: euler(0.35, 0, 0),
      // Arms along the body (abduct < 0 brings them in from the A-pose).
      leftUpperArm: arm(1, -0.05, -0.32),
      rightUpperArm: arm(-1, -0.12 + 0.01 * Math.sin(w), -0.3),
      leftLowerArm: forearm(1, 0.3),
      rightLowerArm: forearm(-1, 0.45),
    };
    return { pose, hips: new THREE.Vector3() };
  });
}
