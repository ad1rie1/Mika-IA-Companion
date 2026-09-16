import * as THREE from "three";
import type { OverlayContext, ProceduralOverlay } from "./Overlay";
import {
  directionToGaze,
  eyesLocalOrigin,
  localDirectionTo,
  type GazeAngles,
} from "../gazeMath";

/**
 * The head's share of a gaze shift — additive on neck + head, ON TOP of
 * whatever the clip does with them.
 *
 * Human head–eye coordination: for a target a few degrees off, the eyes
 * alone move; past that the head turns toward it and covers most of the
 * angle, the eyes lead and then counter-rotate as the head catches up
 * (the vestibulo-ocular reflex). Here that split falls out of the frame
 * order: this overlay measures the viewer in the head frame AS THE CLIP
 * POSED IT, eases a fraction of that angle onto the neck and head, and
 * the GazeController, which runs after it, points the eyes at whatever
 * residual remains. So when a talk clip swings the head, the eyes stay on
 * the viewer instead of sweeping past them.
 *
 * Measuring before adding its own delta keeps the loop open: each frame
 * the mixer rewrites the bones, the measurement is the clip pose alone,
 * and the eased state closes toward the target — no feedback, no drift.
 */

/** Share of the residual angle the head takes (the eyes keep the rest). */
export const HEAD_FOLLOW = 0.7;
/** Below this the head does not bother — small offsets are for the eyes. */
export const HEAD_DEAD_ZONE = 0.06;
export const HEAD_MAX_YAW = 0.6;
export const HEAD_MAX_PITCH = 0.32;
/** Share of an aversion / thinking offset the head follows. */
export const HEAD_OFFSET_SHARE = 0.55;
/** Time constant of the head's ease — slower than the eyes, on purpose. */
export const HEAD_TAU = 0.28;
/** Split of the turn between neck and head. */
export const NECK_SHARE = 0.35;
/** Past these the viewer is behind her: no twist, forward gaze. */
export const HEAD_REACH_YAW = 1.35;
export const HEAD_REACH_PITCH = 1.0;

export function viewerReachable(yaw: number, pitch: number): boolean {
  return Math.abs(yaw) <= HEAD_REACH_YAW && Math.abs(pitch) <= HEAD_REACH_PITCH;
}

function follow(angle: number): number {
  const mag = Math.abs(angle);
  if (mag < HEAD_DEAD_ZONE) return 0;
  return Math.sign(angle) * (mag - HEAD_DEAD_ZONE) * HEAD_FOLLOW;
}

export class HeadAttentionOverlay implements ProceduralOverlay {
  private yaw = 0;
  private pitch = 0;
  private readonly _v = new THREE.Vector3();
  private readonly _eye = new THREE.Vector3();
  private readonly _g: GazeAngles = { pitch: 0, yaw: 0 };

  update(dt: number, ctx: OverlayContext): void {
    let targetYaw = 0;
    let targetPitch = 0;
    const humanoid = ctx.vrm.humanoid;
    const head = humanoid?.getNormalizedBoneNode("head");
    const camera = ctx.camera;
    const intent = ctx.attention;

    ctx.viewerMeasured = false;
    if (humanoid && head && camera && ctx.sleepPhase === "awake") {
      head.updateWorldMatrix(true, false);
      camera.getWorldPosition(this._v);
      eyesLocalOrigin(humanoid, this._eye);
      localDirectionTo(head, this._eye, this._v, this._v);
      directionToGaze(this._v, ctx.sign, this._g);
      ctx.viewerYaw = this._g.yaw;
      ctx.viewerPitch = this._g.pitch;
      ctx.viewerMeasured = true;

      if (intent && viewerReachable(this._g.yaw, this._g.pitch)) {
        targetYaw =
          intent.contact * follow(this._g.yaw) + intent.offset.yaw * HEAD_OFFSET_SHARE;
        targetPitch =
          intent.contact * follow(this._g.pitch) + intent.offset.pitch * HEAD_OFFSET_SHARE;
      } else if (intent) {
        // Out of reach: a thought still turns the head a little off her
        // forward, the viewer term is gone.
        targetYaw = intent.offset.yaw * HEAD_OFFSET_SHARE;
        targetPitch = intent.offset.pitch * HEAD_OFFSET_SHARE;
      }
      targetYaw = Math.max(-HEAD_MAX_YAW, Math.min(HEAD_MAX_YAW, targetYaw));
      targetPitch = Math.max(-HEAD_MAX_PITCH, Math.min(HEAD_MAX_PITCH, targetPitch));
    }

    const k = 1 - Math.exp(-dt / HEAD_TAU);
    this.yaw += (targetYaw - this.yaw) * k;
    this.pitch += (targetPitch - this.pitch) * k;
    if (Math.abs(this.yaw) + Math.abs(this.pitch) < 1e-4) return;

    // The neck is optional in the VRM spec: without one the head carries
    // the whole turn rather than losing the neck's share.
    const neckShare = ctx.vrm.humanoid?.getNormalizedBoneNode("neck") ? NECK_SHARE : 0;
    if (neckShare > 0) {
      ctx.addRotation("neck", this.pitch * neckShare, this.yaw * neckShare, 0);
    }
    ctx.addRotation("head", this.pitch * (1 - neckShare), this.yaw * (1 - neckShare), 0);
  }
}
