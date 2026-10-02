import * as THREE from "three";
import { VRMHumanBoneList, type VRM, type VRMHumanBoneName } from "@pixiv/three-vrm";

/**
 * Left/right mirrored copies of retargeted clips.
 *
 * Every Mixamo idle stands on the same leg, every talk clip gestures with
 * the same hand, every gesture leans to the same side — on a loop, that
 * asymmetry is the first thing the eye learns, and once learned the clip
 * reads as a recording. A mirrored twin doubles each pool for free and
 * lets the same motion come back from the other side.
 *
 * The math is exact on the NORMALIZED rig: its bones have identity rest
 * rotations in a frame whose lateral axis is X (for a VRM 1.0 facing +Z
 * as for a 0.x facing −Z — the Ry(π) between them is diagonal and commutes
 * with the reflection). Reflecting across the X = 0 plane maps a rotation
 * quaternion (x, y, z, w) to (x, −y, −z, w) and a position (x, y, z) to
 * (−x, y, z); each track is then moved onto the opposite bone.
 */

export const MIRROR_SUFFIX = "~m";

export function isMirrorName(name: string): boolean {
  return name.endsWith(MIRROR_SUFFIX);
}

/** The manifest name a clip (or its mirrored twin) was loaded from. */
export function baseClipName(name: string): string {
  return isMirrorName(name) ? name.slice(0, -MIRROR_SUFFIX.length) : name;
}

export function mirrorBoneName(bone: VRMHumanBoneName): VRMHumanBoneName {
  if (bone.startsWith("left")) return ("right" + bone.slice(4)) as VRMHumanBoneName;
  if (bone.startsWith("right")) return ("left" + bone.slice(5)) as VRMHumanBoneName;
  return bone;
}

/** Normalized node name → the node name of its mirror bone. Centre bones
 * (hips, spine, head…) map to themselves. */
export function buildMirrorNodeMap(vrm: VRM): Map<string, string> {
  const map = new Map<string, string>();
  const humanoid = vrm.humanoid;
  if (!humanoid) return map;
  for (const bone of VRMHumanBoneList) {
    const node = humanoid.getNormalizedBoneNode(bone);
    const twin = humanoid.getNormalizedBoneNode(mirrorBoneName(bone));
    if (node && twin) map.set(node.name, twin.name);
  }
  return map;
}

export function mirrorClip(
  clip: THREE.AnimationClip,
  nodeMap: Map<string, string>,
  name = clip.name + MIRROR_SUFFIX
): THREE.AnimationClip {
  const tracks: THREE.KeyframeTrack[] = [];
  for (const track of clip.tracks) {
    const dot = track.name.lastIndexOf(".");
    const nodeName = track.name.slice(0, dot);
    const property = track.name.slice(dot + 1);
    const target = `${nodeMap.get(nodeName) ?? nodeName}.${property}`;
    const values = Float32Array.from(track.values as ArrayLike<number>);
    if (property === "quaternion") {
      for (let i = 0; i < values.length; i += 4) {
        values[i + 1] = -values[i + 1];
        values[i + 2] = -values[i + 2];
      }
      tracks.push(new THREE.QuaternionKeyframeTrack(target, Array.from(track.times), Array.from(values)));
    } else if (property === "position") {
      for (let i = 0; i < values.length; i += 3) values[i] = -values[i];
      tracks.push(new THREE.VectorKeyframeTrack(target, Array.from(track.times), Array.from(values)));
    }
  }
  return new THREE.AnimationClip(name, clip.duration, tracks);
}
