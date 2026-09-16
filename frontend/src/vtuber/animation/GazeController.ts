import * as THREE from "three";
import { VRM } from "@pixiv/three-vrm";
import type { EmotionName, SleepPhase } from "../../types";
import { forwardSign } from "../vrmVersion";
import type { GazeIntent } from "./attention";
import {
  directionToGaze,
  eyesLocalOrigin,
  gazeToQuaternion,
  localDirectionTo,
  type GazeAngles,
} from "./gazeMath";

/**
 * Drives the eye bones: where Mika is looking, on top of what the head
 * already does.
 *
 * Mixamo rigs have no eye bones, so these absolute writes never conflict
 * with the clip mixer. Composition, in semantic angles (pitch > 0 down,
 * yaw > 0 her left — see gazeMath):
 *
 *   contact · (viewer direction, measured in the FINAL head frame)
 *   + emotion bias · intensity
 *   + attention offset (aversion / thinking / inner murmur)
 *   + saccade jitter
 *
 * The viewer term is measured after every head overlay ran, so it is the
 * residual the head did not cover — that is the vestibulo-ocular reflex:
 * the clip turns the head, the eyes counter-rotate, contact holds. It is
 * applied unfiltered (the reflex is ~10 ms in humans); everything else is
 * a step decided by the AttentionDirector, followed with a ~30 ms ease
 * that reads as a saccade, never as a slide.
 *
 * Eye range is deliberately conservative — a VRM eye bone rotated past
 * ~17° shows white on most models. Past it the eyes stop at the corner
 * and the head overlay carries the rest.
 */

export const EYE_MAX_YAW = 0.3;
export const EYE_MAX_PITCH = 0.22;
/** ~2 frames: the eye lands, it does not glide. */
export const EYE_TAU = 0.03;
/** Asleep: lids closed, eyes rest slightly downward like a real sleeper's. */
export const EYE_SLEEP_PITCH = 0.06;

/** Emotion → steady gaze bias (baseline the saccades wiggle around). */
export const EMOTION_GAZE_BIAS: Partial<Record<EmotionName, GazeAngles>> = {
  embarrassed: { pitch: 0.08, yaw: -0.08 }, // down, away: averts
  scared: { pitch: 0.1, yaw: 0.06 }, // down-side, tense
  jealous: { pitch: 0.05, yaw: -0.1 }, // side-glance
  anxious: { pitch: 0.06, yaw: 0.04 }, // down, unsteady
  lonely: { pitch: 0.06, yaw: 0.0 }, // down, centre
  sad: { pitch: 0.08, yaw: 0.0 },
  melancholic: { pitch: 0.07, yaw: -0.02 },
  bored: { pitch: 0.0, yaw: 0.1 }, // looks elsewhere
  thinking: { pitch: -0.06, yaw: 0.08 }, // up and to the side
  curious: { pitch: -0.04, yaw: 0.06 }, // slightly up
  confused: { pitch: -0.02, yaw: -0.05 },
  dreamy: { pitch: -0.05, yaw: 0.0 }, // gaze up, vacant
  love: { pitch: 0.0, yaw: 0.0 }, // direct eye contact
  grateful: { pitch: 0.0, yaw: 0.0 },
  proud: { pitch: -0.02, yaw: 0.0 }, // chin up slightly
  determined: { pitch: 0.0, yaw: 0.0 },
  // Emotions without an entry keep a plain contact / saccade behaviour.
};

const ZERO: GazeAngles = { pitch: 0, yaw: 0 };

export class GazeController {
  private vrm: VRM | null = null;
  private sign: 1 | -1 = 1;
  private camera: THREE.Object3D | null = null;
  private emotion: EmotionName = "neutral";
  private intensity = 0.5;
  private sleepPhase: SleepPhase = "awake";

  /** Applied angles, eased toward the target. */
  private readonly current: GazeAngles = { pitch: 0, yaw: 0 };
  private readonly target: GazeAngles = { pitch: 0, yaw: 0 };
  private readonly _v = new THREE.Vector3();
  private readonly _eye = new THREE.Vector3();
  private readonly _viewer: GazeAngles = { pitch: 0, yaw: 0 };
  private readonly _q = new THREE.Quaternion();

  setVRM(vrm: VRM): void {
    this.vrm = vrm;
    this.sign = forwardSign(vrm);
  }

  setCamera(camera: THREE.Object3D | null): void {
    this.camera = camera;
  }

  setEmotion(emotion: EmotionName, intensity: number): void {
    this.emotion = emotion;
    this.intensity = intensity;
  }

  setSleepPhase(phase: SleepPhase): void {
    this.sleepPhase = phase;
  }

  /** Semantic angles currently applied — for tests and the debug panel. */
  get applied(): Readonly<GazeAngles> {
    return this.current;
  }

  update(delta: number, intent: GazeIntent | null = null): void {
    const humanoid = this.vrm?.humanoid;
    if (!humanoid) return;
    const leftEye = humanoid.getNormalizedBoneNode("leftEye");
    const rightEye = humanoid.getNormalizedBoneNode("rightEye");
    if (!leftEye && !rightEye) return;

    const t = this.target;
    if (this.sleepPhase !== "awake") {
      t.pitch = EYE_SLEEP_PITCH;
      t.yaw = 0;
    } else {
      const bias = EMOTION_GAZE_BIAS[this.emotion] ?? ZERO;
      // A mild "thinking" barely moves the gaze, a strong one clearly looks away.
      const biasScale = 0.3 + this.intensity * 0.7;
      t.pitch = bias.pitch * biasScale;
      t.yaw = bias.yaw * biasScale;

      if (intent) {
        if (intent.contact > 0 && this.camera) {
          const head = humanoid.getNormalizedBoneNode("head");
          if (head) {
            head.updateWorldMatrix(true, false);
            this.camera.getWorldPosition(this._v);
            eyesLocalOrigin(humanoid, this._eye);
            localDirectionTo(head, this._eye, this._v, this._v);
            directionToGaze(this._v, this.sign, this._viewer);
            // Only what the eyes can physically reach: a viewer past the
            // corner of the eye is looked at as far as the eye goes.
            t.pitch +=
              intent.contact *
              Math.max(-EYE_MAX_PITCH, Math.min(EYE_MAX_PITCH, this._viewer.pitch));
            t.yaw +=
              intent.contact *
              Math.max(-EYE_MAX_YAW, Math.min(EYE_MAX_YAW, this._viewer.yaw));
          }
        }
        t.pitch += intent.offset.pitch + intent.saccade.pitch;
        t.yaw += intent.offset.yaw + intent.saccade.yaw;
      }
      t.pitch = Math.max(-EYE_MAX_PITCH, Math.min(EYE_MAX_PITCH, t.pitch));
      t.yaw = Math.max(-EYE_MAX_YAW, Math.min(EYE_MAX_YAW, t.yaw));
    }

    const k = 1 - Math.exp(-Math.max(0, delta) / EYE_TAU);
    this.current.pitch += (t.pitch - this.current.pitch) * k;
    this.current.yaw += (t.yaw - this.current.yaw) * k;

    gazeToQuaternion(this.current, this.sign, this._q);
    if (leftEye) leftEye.quaternion.copy(this._q);
    if (rightEye) rightEye.quaternion.copy(this._q);
  }
}
