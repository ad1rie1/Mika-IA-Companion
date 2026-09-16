import type { VRM } from "@pixiv/three-vrm";

/**
 * Is this a VRM 0.x model?
 *
 * ONE definition, because two layers depend on it and a disagreement
 * between them is silent: the AvatarRoot's Y-π turn (`VTuberModel`) and
 * the X/Z conjugation of retargeted Mixamo clips (`mixamoRetarget`). A
 * VRM 0.x rest faces −Z, a VRM 1.0 rest faces +Z; the camera looks
 * toward −Z, so applying the flip to a VRM 1.0 leaves the avatar
 * animating correctly with its back to the viewer — a symptom nobody
 * imputes to the loader.
 *
 * Same predicate as the library's own `VRMUtils.rotateVRM0`.
 */
export function isVRM0(vrm: VRM): boolean {
  return vrm.meta?.metaVersion === "0";
}

/**
 * Sign of the model's forward axis in its normalized-rig frame: +1 for a
 * VRM 1.0 (faces +Z), −1 for a VRM 0.x (faces −Z — three-vrm's own words:
 * "VRM 0.0 models are facing Z- instead of Z+").
 *
 * Every hand-written rotation of the animation layer — a head tilt, an eye
 * pitch, the A-pose arm drop, a finger curl — is authored ONCE in the
 * VRM 1.0 convention and conjugated by Ry(π) for a 0.x model. That
 * conjugation flips the X and Z components and leaves Y alone, exactly what
 * `mixamoRetarget` does to every clip quaternion, so "look down", "tilt
 * right" and "curl the fingers" keep their meaning on both rigs. Before this
 * existed the overlays wrote +Z-convention pitches onto a −Z-facing model:
 * `sad` raised the chin and the sleep doze tilted the head *back*.
 */
export function forwardSign(vrm: VRM): 1 | -1 {
  return isVRM0(vrm) ? -1 : 1;
}
