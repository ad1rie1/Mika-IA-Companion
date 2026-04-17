import { VRM } from "@pixiv/three-vrm";
import type { EmotionName } from "./EmotionController";

/**
 * Drives eye pose: where Mika is looking, and whether she's making
 * eye contact, averting, or just flickering around the scene.
 *
 * Three interacting sources of eye direction (blended in priority
 * order — the highest-priority non-zero contribution wins):
 *
 *   1. SLEEP — eyes forced forward+down; no gaze movement while asleep
 *   2. EMOTION — some emotions override gaze behavior
 *      - embarrassed / scared / jealous → avert down-side
 *      - thinking / curious → look up-side (gaze up-right/left)
 *      - love / grateful → direct eye contact, held
 *      - sad / lonely / melancholic → look down, reduced contact
 *   3. SACCADES — micro eye movements every 2-5s when idle, small
 *      deviations around eye-contact baseline. Human-like restlessness.
 *
 * Target rotations are applied to both eye bones via the VRM humanoid.
 * Values are tiny angles (± 0.15 rad max on each axis) — eye bones
 * rotate around their own origin, not the head's.
 */

export type SleepPhase = "awake" | "light_sleep" | "rem" | "deep_sleep";

interface GazeDirection {
  pitch: number; // up (-) / down (+)
  yaw: number;   // left (-) / right (+)
}

const ZERO: GazeDirection = { pitch: 0, yaw: 0 };

// Emotion → steady gaze bias (baseline around which saccades wiggle).
// pitch: positive looks down, negative looks up.
// yaw:   positive looks right, negative looks left.
const EMOTION_GAZE_BIAS: Partial<Record<EmotionName, GazeDirection>> = {
  embarrassed: { pitch: 0.08, yaw: -0.08 },  // down-left: averts
  scared:      { pitch: 0.10, yaw:  0.06 },  // down-right, tense
  jealous:     { pitch: 0.05, yaw: -0.10 },  // side-glance
  anxious:     { pitch: 0.06, yaw:  0.04 },  // down, unsteady
  lonely:      { pitch: 0.06, yaw:  0.0  },  // down, center
  sad:         { pitch: 0.08, yaw:  0.0  },
  melancholic: { pitch: 0.07, yaw: -0.02 },
  bored:       { pitch: 0.0,  yaw:  0.10 },  // looks elsewhere
  thinking:    { pitch: -0.06, yaw: 0.08 },  // up-right (classic "thinking")
  curious:     { pitch: -0.04, yaw: 0.06 },  // slightly up
  confused:    { pitch: -0.02, yaw: -0.05 },
  dreamy:      { pitch: -0.05, yaw:  0.0  },  // gaze up, vacant
  love:        { pitch: 0.0,  yaw:  0.0  },  // direct eye contact
  grateful:    { pitch: 0.0,  yaw:  0.0  },
  proud:       { pitch: -0.02, yaw: 0.0  },  // chin up slightly
  determined:  { pitch: 0.0,  yaw:  0.0  },
  // Emotions without an entry fall through to pure saccade behavior.
};

// Emotions where saccade amplitude should be reduced (focused gaze).
const FOCUSED_EMOTIONS = new Set<EmotionName>([
  "love", "grateful", "proud", "determined",
]);

// Emotions where saccades should be faster / more restless.
const RESTLESS_EMOTIONS = new Set<EmotionName>([
  "scared", "anxious", "surprised", "excited",
]);


export class GazeController {
  private vrm: VRM | null = null;
  private emotion: EmotionName = "neutral";
  private intensity: number = 0.5;
  private sleepPhase: SleepPhase = "awake";

  // Current applied rotation (eased toward target).
  private current: GazeDirection = { pitch: 0, yaw: 0 };
  // Target rotation, recomputed each frame from bias + saccade offset.
  private target: GazeDirection = { pitch: 0, yaw: 0 };

  // Saccade state machine
  private saccadeTimer = 0;
  private saccadeInterval = 2 + Math.random() * 3; // 2-5s
  private saccadeOffset: GazeDirection = { pitch: 0, yaw: 0 };

  // How fast `current` eases toward `target`. 1 / easeTime per second.
  private easeSpeed = 5.0;

  setVRM(vrm: VRM): void {
    this.vrm = vrm;
  }

  setEmotion(emotion: EmotionName, intensity: number): void {
    this.emotion = emotion;
    this.intensity = intensity;
  }

  setSleepPhase(phase: SleepPhase): void {
    this.sleepPhase = phase;
  }

  update(delta: number): void {
    if (!this.vrm?.humanoid) return;

    // Compute target gaze
    if (this.sleepPhase !== "awake") {
      // Asleep: eyes look forward+down, no saccades. The blink/closure
      // is already handled by AnimationMixer — the bone rotation just
      // keeps them pointed naturally (not rolled up).
      this.target = { pitch: 0.05, yaw: 0 };
    } else {
      this.updateSaccade(delta);
      const bias = EMOTION_GAZE_BIAS[this.emotion] || ZERO;
      // Emotion bias scales with intensity — a mild "thinking" barely
      // moves the gaze, a strong one clearly looks away.
      const biasScale = 0.3 + this.intensity * 0.7;
      this.target = {
        pitch: bias.pitch * biasScale + this.saccadeOffset.pitch,
        yaw: bias.yaw * biasScale + this.saccadeOffset.yaw,
      };
    }

    // Ease current toward target
    const ease = Math.min(1, delta * this.easeSpeed);
    this.current.pitch += (this.target.pitch - this.current.pitch) * ease;
    this.current.yaw += (this.target.yaw - this.current.yaw) * ease;

    // Apply to VRM eye bones. Not all VRM models have eye bones — fail soft.
    const leftEye = this.vrm.humanoid.getNormalizedBoneNode("leftEye");
    const rightEye = this.vrm.humanoid.getNormalizedBoneNode("rightEye");
    if (leftEye) {
      leftEye.rotation.x = this.current.pitch;
      leftEye.rotation.y = this.current.yaw;
    }
    if (rightEye) {
      rightEye.rotation.x = this.current.pitch;
      rightEye.rotation.y = this.current.yaw;
    }
  }

  private updateSaccade(delta: number): void {
    this.saccadeTimer += delta;
    if (this.saccadeTimer < this.saccadeInterval) return;

    // Fire a new saccade
    this.saccadeTimer = 0;

    // Amplitude: ~0.04-0.10 rad, smaller for focused emotions, larger for
    // restless ones.
    let amplitude = 0.04 + Math.random() * 0.06;
    if (FOCUSED_EMOTIONS.has(this.emotion)) amplitude *= 0.4;
    if (RESTLESS_EMOTIONS.has(this.emotion)) amplitude *= 1.4;

    // Random direction in 2D (a saccade in any direction)
    const angle = Math.random() * Math.PI * 2;
    this.saccadeOffset = {
      pitch: Math.sin(angle) * amplitude,
      yaw: Math.cos(angle) * amplitude,
    };

    // Next interval: faster for restless emotions
    let baseInterval = 2 + Math.random() * 3;
    if (FOCUSED_EMOTIONS.has(this.emotion)) baseInterval *= 1.3;
    if (RESTLESS_EMOTIONS.has(this.emotion)) baseInterval *= 0.55;
    this.saccadeInterval = baseInterval;
  }
}
