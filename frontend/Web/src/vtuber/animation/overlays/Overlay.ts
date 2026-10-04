import * as THREE from "three";
import { VRM } from "@pixiv/three-vrm";
import type { VRMHumanBoneName } from "@pixiv/three-vrm";
import type { EmotionName, SleepPhase, VoicePersona } from "../../../types";
import { forwardSign } from "../../vrmVersion";
import type { GazeIntent } from "../attention";
import { EMOTION_AROUSAL } from "../affect";

const _q = new THREE.Quaternion();
const _e = new THREE.Euler();

/**
 * Shared per-frame context for procedural overlays. Overlays run AFTER
 * the clip mixer and compose small deltas ON TOP of the clip pose —
 * `addRotation` post-multiplies a quaternion, it never writes absolute
 * Euler values. Absolute writes cannot coexist with an AnimationMixer;
 * that constraint killed the previous architecture.
 *
 * Deltas are authored in the VRM 1.0 convention (the rig faces +Z:
 * positive X pitches the head DOWN, positive Z tilts it toward its right)
 * and conjugated by `sign` for a VRM 0.x rig, which faces −Z. Without
 * that, the same +0.08 pitch that nods on one model raises the chin on
 * the other — and the user's model is a 0.x.
 */
export class OverlayContext {
  sleepPhase: SleepPhase = "awake";
  emotion: EmotionName = "neutral";
  intensity = 0.5;
  speaking = false;
  /** Voice of the reply being spoken; `inner` = murmuring to herself. */
  persona: VoicePersona | undefined = undefined;

  /** Whose position the attention layer looks at; null = no viewer. */
  camera: THREE.Object3D | null = null;
  /** This frame's gaze intent from the AttentionDirector (null before init). */
  attention: GazeIntent | null = null;
  /** Viewer direction in the clip-posed head frame (semantic angles),
   * published by HeadAttentionOverlay for the director's next frame. */
  viewerYaw = 0;
  viewerPitch = 0;
  viewerMeasured = false;
  /** Saccadic jump the eyes made this frame (rad), published by the
   * GazeController for the blink coupling. */
  gazeShift = 0;

  /** Character the voice is at in the reply being spoken (−1 = none),
   * fed by the lip-sync cursor — the speech beats fire on it. */
  speechCursor = -1;
  /** Brow flash of the speech beat just fired, 0…1, decaying — published
   * by SpeechBodyOverlay, read by the FaceIdleController. */
  speechEmphasis = 0;
  /** A question is being asked: brows held up, 0…1. */
  speechQuestion = 0;

  /** She is walking across the room (the locomotion controller). */
  walking = false;

  /** Tiredness 0 (fresh) … 1 (exhausted), from the backend's energy level
   * — slower breath, a stiller body, heavier blinks. */
  fatigue = 0;

  /** Breath fill, 0 (empty) … 1 (full lungs), published by the breathing
   * layer — the face and the head can ride it. */
  breath = 0;
  /** One-shot request to the breathing layer, consumed by it: a quick
   * catch-breath before a clause, or a full sigh. */
  breathRequest: "catch" | "sigh" | null = null;

  /** +1 for a rig facing +Z (VRM 1.0), −1 for −Z (VRM 0.x). */
  readonly sign: 1 | -1;

  constructor(readonly vrm: VRM) {
    this.sign = forwardSign(vrm);
  }

  /** Signed arousal of the current emotion scaled by its intensity,
   * −1 (drained) … 1 (wired) — how much the body moves. */
  get arousal(): number {
    return EMOTION_AROUSAL[this.emotion] * this.intensity;
  }

  /** Post-multiply a small Euler delta (VRM 1.0 convention) in the bone's
   * CURRENT (clip-posed) local frame. Conjugation by Ry(π) is exact for an
   * XYZ Euler: (x, y, z) → (−x, y, −z). */
  addRotation(bone: VRMHumanBoneName, x: number, y: number, z: number): void {
    const node = this.vrm.humanoid?.getNormalizedBoneNode(bone);
    if (!node) return;
    node.quaternion.multiply(
      _q.setFromEuler(_e.set(this.sign * x, y, this.sign * z, "XYZ"))
    );
  }
}

export interface ProceduralOverlay {
  update(dt: number, ctx: OverlayContext): void;
}
