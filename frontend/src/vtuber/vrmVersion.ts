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
