import * as THREE from "three";
import type { VRM } from "@pixiv/three-vrm";
import type { VRMHumanBoneName } from "@pixiv/three-vrm";

/**
 * Runtime retargeting of a Mixamo FBX AnimationClip onto the VRM's
 * NORMALIZED humanoid bones (three-vrm 3.x API).
 *
 * Algorithm (same as the official three-vrm `loadMixamoAnimation`
 * example): for every quaternion keyframe q (Mixamo bone local rotation)
 *
 *     q' = parentRestWorldRotation · q · restWorldRotation⁻¹
 *
 * where both rest rotations are read from the FBX rig at bind pose.
 * This converts the bone's local delta into a WORLD-frame delta from
 * rest — and since three-vrm normalized bones have identity rest world
 * rotation, that world delta IS the correct local quaternion for the
 * normalized bone. Both rigs are T-pose at rest (Mixamo bind pose and
 * the VRM normalized rig by spec), which is the precondition making
 * this valid. The runtime A-pose never enters this math.
 *
 * VRM 0.x flip: Mixamo's frame has the character facing +Z, a VRM0
 * model's internal rest faces −Z. Re-expressing in the Y-π-rotated
 * frame is quaternion conjugation by (0,1,0,0), i.e. (x,y,z,w) →
 * (−x,y,−z,w), and positions (x,y,z) → (−x,y,−z). The manual
 * `scene.rotation.y = Math.PI` on the avatar root is ABOVE the animated
 * subtree and never interacts with these local track values.
 */

// Mixamo bone-name suffix → VRM humanoid bone. The prefix ("mixamorig",
// "mixamorig:", "mixamorig1"…) varies across exports and is detected at
// load time; the map is keyed by suffix.
export const MIXAMO_SUFFIX_TO_VRM: Record<string, VRMHumanBoneName> = {
  Hips: "hips",
  Spine: "spine",
  Spine1: "chest",
  Spine2: "upperChest",
  Neck: "neck",
  Head: "head",
  LeftShoulder: "leftShoulder",
  LeftArm: "leftUpperArm",
  LeftForeArm: "leftLowerArm",
  LeftHand: "leftHand",
  LeftHandThumb1: "leftThumbMetacarpal",
  LeftHandThumb2: "leftThumbProximal",
  LeftHandThumb3: "leftThumbDistal",
  LeftHandIndex1: "leftIndexProximal",
  LeftHandIndex2: "leftIndexIntermediate",
  LeftHandIndex3: "leftIndexDistal",
  LeftHandMiddle1: "leftMiddleProximal",
  LeftHandMiddle2: "leftMiddleIntermediate",
  LeftHandMiddle3: "leftMiddleDistal",
  LeftHandRing1: "leftRingProximal",
  LeftHandRing2: "leftRingIntermediate",
  LeftHandRing3: "leftRingDistal",
  LeftHandPinky1: "leftLittleProximal",
  LeftHandPinky2: "leftLittleIntermediate",
  LeftHandPinky3: "leftLittleDistal",
  RightShoulder: "rightShoulder",
  RightArm: "rightUpperArm",
  RightForeArm: "rightLowerArm",
  RightHand: "rightHand",
  RightHandThumb1: "rightThumbMetacarpal",
  RightHandThumb2: "rightThumbProximal",
  RightHandThumb3: "rightThumbDistal",
  RightHandIndex1: "rightIndexProximal",
  RightHandIndex2: "rightIndexIntermediate",
  RightHandIndex3: "rightIndexDistal",
  RightHandMiddle1: "rightMiddleProximal",
  RightHandMiddle2: "rightMiddleIntermediate",
  RightHandMiddle3: "rightMiddleDistal",
  RightHandRing1: "rightRingProximal",
  RightHandRing2: "rightRingIntermediate",
  RightHandRing3: "rightRingDistal",
  RightHandPinky1: "rightLittleProximal",
  RightHandPinky2: "rightLittleIntermediate",
  RightHandPinky3: "rightLittleDistal",
  LeftUpLeg: "leftUpperLeg",
  LeftLeg: "leftLowerLeg",
  LeftFoot: "leftFoot",
  LeftToeBase: "leftToes",
  RightUpLeg: "rightUpperLeg",
  RightLeg: "rightLowerLeg",
  RightFoot: "rightFoot",
  RightToeBase: "rightToes",
};

// Finger bones stay procedural: the HandAnimator owns them (emotion-
// reactive curl, ripples, sleep shapes). Deleting a bone from this set
// hands its ownership back to Mixamo clips — one-line reversal.
export const STRIPPED_VRM_BONES: ReadonlySet<VRMHumanBoneName> = new Set<VRMHumanBoneName>([
  "leftThumbMetacarpal", "leftThumbProximal", "leftThumbDistal",
  "leftIndexProximal", "leftIndexIntermediate", "leftIndexDistal",
  "leftMiddleProximal", "leftMiddleIntermediate", "leftMiddleDistal",
  "leftRingProximal", "leftRingIntermediate", "leftRingDistal",
  "leftLittleProximal", "leftLittleIntermediate", "leftLittleDistal",
  "rightThumbMetacarpal", "rightThumbProximal", "rightThumbDistal",
  "rightIndexProximal", "rightIndexIntermediate", "rightIndexDistal",
  "rightMiddleProximal", "rightMiddleIntermediate", "rightMiddleDistal",
  "rightRingProximal", "rightRingIntermediate", "rightRingDistal",
  "rightLittleProximal", "rightLittleIntermediate", "rightLittleDistal",
]);

// Sanity bounds for hipsPositionScale (VRM meters / Mixamo cm ≈ 0.0075).
// Outside this range the height measurement is almost certainly wrong.
export const HIPS_SCALE_MIN = 0.004;
export const HIPS_SCALE_MAX = 0.02;

export interface RetargetOptions {
  /** Drop finger tracks so the procedural HandAnimator keeps ownership. */
  stripFingers?: boolean;
  /** Zero the hips X/Z position (in-place enforcement for locomotion). */
  stripRootXZ?: boolean;
}

export interface RetargetReport {
  clipName: string;
  sourceClipName: string;
  duration: number;
  mappedTracks: number;
  strippedFingerTracks: number;
  droppedTracks: string[];
  hipsPositionScale: number | null;
  hipsScaleSuspicious: boolean;
}

/** Find the Mixamo bone-name prefix by locating the hips node.
 * Handles "mixamorigHips", "mixamorig:Hips", "mixamorig1Hips", bare
 * "Hips"… Returns null when no hips-like node exists. */
export function detectMixamoPrefix(asset: THREE.Object3D): string | null {
  let prefix: string | null = null;
  asset.traverse((node) => {
    if (prefix !== null) return;
    if (node.name === "Hips") {
      prefix = "";
    } else if (node.name.endsWith("Hips") && node.name.length > 4) {
      prefix = node.name.slice(0, -4);
    }
  });
  return prefix;
}

const _restRotationInverse = new THREE.Quaternion();
const _parentRestWorldRotation = new THREE.Quaternion();
const _quat = new THREE.Quaternion();

/**
 * Convert a loaded Mixamo FBX into an AnimationClip whose tracks target
 * the VRM's normalized humanoid bone nodes. Throws when the asset has
 * no animation or no recognizable Mixamo rig.
 */
export function retargetMixamoClip(
  asset: THREE.Group,
  vrm: VRM,
  clipName: string,
  opts: RetargetOptions = {}
): { clip: THREE.AnimationClip; report: RetargetReport } {
  const stripFingers = opts.stripFingers !== false;

  const source =
    THREE.AnimationClip.findByName(asset.animations, "mixamo.com") ??
    asset.animations[0];
  if (!source) {
    throw new Error(`${clipName}: FBX contains no animation`);
  }

  const prefix = detectMixamoPrefix(asset);
  if (prefix === null) {
    throw new Error(`${clipName}: no Mixamo hips node found in FBX`);
  }

  const humanoid = vrm.humanoid;
  if (!humanoid) {
    throw new Error(`${clipName}: VRM has no humanoid`);
  }

  // Bind-pose world matrices must be current before reading rest
  // rotations (FBXLoader leaves nodes at their rest transforms).
  asset.updateMatrixWorld(true);

  // Hips height ratio for the position track. Mixamo FBX files are in
  // centimeters with a unit-conversion scale on the root, so the LOCAL
  // hips position must be used — it lives in the same space as the
  // position track values. getWorldPosition would mix meters into a
  // cm-space ratio (100× error → hips in orbit).
  const hipsNode = asset.getObjectByName(prefix + "Hips");
  const motionHipsHeight = hipsNode ? hipsNode.position.y : 0;
  const restHips = humanoid.normalizedRestPose.hips?.position;
  const vrmHipsHeight = restHips ? Math.abs(restHips[1]) : null;
  const hipsPositionScale =
    motionHipsHeight > 1e-6 && vrmHipsHeight
      ? vrmHipsHeight / motionHipsHeight
      : null;

  // VRM 0.x internal rest faces −Z (vs Mixamo's +Z): conjugate by Ry(π).
  const flip = vrm.meta?.metaVersion === "0";

  const tracks: THREE.KeyframeTrack[] = [];
  const dropped: string[] = [];
  let strippedFingerTracks = 0;

  for (const track of source.tracks) {
    const dot = track.name.lastIndexOf(".");
    if (dot <= 0) {
      dropped.push(track.name);
      continue;
    }
    const rigName = track.name.slice(0, dot);
    const property = track.name.slice(dot + 1);

    if (!rigName.startsWith(prefix)) {
      dropped.push(track.name);
      continue;
    }
    const vrmBone = MIXAMO_SUFFIX_TO_VRM[rigName.slice(prefix.length)];
    if (!vrmBone) {
      dropped.push(track.name);
      continue;
    }
    if (stripFingers && STRIPPED_VRM_BONES.has(vrmBone)) {
      strippedFingerTracks++;
      continue;
    }
    const node = humanoid.getNormalizedBoneNode(vrmBone);
    const rigNode = asset.getObjectByName(rigName);
    if (!node || !rigNode) {
      // e.g. Spine2 on a model without upperChest — expected, not an error.
      dropped.push(track.name);
      continue;
    }

    if (property === "quaternion" && track instanceof THREE.QuaternionKeyframeTrack) {
      // FBXLoader emits degenerate stub tracks (e.g. `(name, [0], [0])`)
      // for bones whose rotation curves are incomplete — retargeting one
      // would push NaN quaternions into the mixer without ever throwing.
      if (track.values.length !== track.times.length * 4) {
        dropped.push(track.name);
        continue;
      }
      rigNode.getWorldQuaternion(_restRotationInverse).invert();
      _parentRestWorldRotation.identity();
      rigNode.parent?.getWorldQuaternion(_parentRestWorldRotation);

      const values = new Float32Array(track.values.length);
      let finite = true;
      for (let i = 0; i < track.values.length; i += 4) {
        _quat
          .fromArray(track.values as unknown as number[], i)
          .premultiply(_parentRestWorldRotation)
          .multiply(_restRotationInverse);
        if (!Number.isFinite(_quat.x + _quat.y + _quat.z + _quat.w)) {
          finite = false;
          break;
        }
        values[i] = flip ? -_quat.x : _quat.x;
        values[i + 1] = _quat.y;
        values[i + 2] = flip ? -_quat.z : _quat.z;
        values[i + 3] = _quat.w;
      }
      if (!finite) {
        dropped.push(track.name);
        continue;
      }
      tracks.push(
        new THREE.QuaternionKeyframeTrack(
          `${node.name}.quaternion`,
          Array.from(track.times),
          Array.from(values)
        )
      );
    } else if (
      property === "position" &&
      vrmBone === "hips" &&
      track instanceof THREE.VectorKeyframeTrack
    ) {
      if (
        hipsPositionScale === null ||
        track.values.length !== track.times.length * 3
      ) {
        dropped.push(track.name);
        continue;
      }
      const values = new Float32Array(track.values.length);
      for (let i = 0; i < track.values.length; i += 3) {
        let x = track.values[i] * hipsPositionScale;
        const y = track.values[i + 1] * hipsPositionScale;
        let z = track.values[i + 2] * hipsPositionScale;
        if (flip) {
          x = -x;
          z = -z;
        }
        if (opts.stripRootXZ) {
          x = 0;
          z = 0;
        }
        values[i] = x;
        values[i + 1] = y;
        values[i + 2] = z;
      }
      tracks.push(
        new THREE.VectorKeyframeTrack(
          `${node.name}.position`,
          Array.from(track.times),
          Array.from(values)
        )
      );
    }
    // Non-hips position tracks and all scale tracks: dropped silently —
    // VRMHumanoidRig.update only transfers quaternions + hips position.
  }

  if (tracks.length === 0) {
    throw new Error(`${clipName}: no retargetable tracks (wrong rig?)`);
  }

  const report: RetargetReport = {
    clipName,
    sourceClipName: source.name,
    duration: source.duration,
    mappedTracks: tracks.length,
    strippedFingerTracks,
    droppedTracks: dropped,
    hipsPositionScale,
    hipsScaleSuspicious:
      hipsPositionScale !== null &&
      (hipsPositionScale < HIPS_SCALE_MIN || hipsPositionScale > HIPS_SCALE_MAX),
  };

  return { clip: new THREE.AnimationClip(clipName, source.duration, tracks), report };
}
