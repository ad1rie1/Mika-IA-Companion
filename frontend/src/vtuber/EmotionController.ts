import { VRM } from "@pixiv/three-vrm";

// All 29 emotions matching backend ai/emotion_types.py
export type EmotionName =
  | "neutral"
  // Positive
  | "happy"
  | "excited"
  | "love"
  | "proud"
  | "grateful"
  | "playful"
  | "amused"
  | "hopeful"
  | "relieved"
  // Negative
  | "sad"
  | "angry"
  | "scared"
  | "disgusted"
  | "frustrated"
  | "lonely"
  | "anxious"
  | "bored"
  | "jealous"
  // Complex
  | "surprised"
  | "thinking"
  | "confused"
  | "embarrassed"
  | "nostalgic"
  | "dreamy"
  | "determined"
  | "mischievous"
  | "curious"
  | "melancholic";

interface BlendShapeTarget {
  [presetName: string]: number;
}

// Map all 29 emotions to VRM blend shape combinations (weights at intensity 1.0)
const EMOTION_MAP: Record<EmotionName, BlendShapeTarget> = {
  // Neutral
  neutral: {},

  // --- Positive ---
  happy: { happy: 1.0 },
  excited: { happy: 0.8, surprised: 0.4 },
  love: { happy: 0.7, relaxed: 0.6 },
  proud: { happy: 0.6, relaxed: 0.3 },
  grateful: { happy: 0.7, relaxed: 0.4 },
  playful: { happy: 0.7, surprised: 0.2 },
  amused: { happy: 0.8, surprised: 0.15 },
  hopeful: { happy: 0.4, relaxed: 0.3 },
  relieved: { relaxed: 0.8, happy: 0.3 },

  // --- Negative ---
  sad: { sad: 1.0 },
  angry: { angry: 1.0 },
  scared: { surprised: 0.6, sad: 0.4 },
  disgusted: { angry: 0.6, sad: 0.3 },
  frustrated: { angry: 0.7, sad: 0.3 },
  lonely: { sad: 0.7, relaxed: 0.2 },
  anxious: { sad: 0.4, surprised: 0.3 },
  bored: { relaxed: 0.3, neutral: 0.4 },
  jealous: { angry: 0.5, sad: 0.4 },

  // --- Complex ---
  surprised: { surprised: 1.0 },
  thinking: { neutral: 0.3, relaxed: 0.2 },
  confused: { surprised: 0.4, sad: 0.25 },
  embarrassed: { happy: 0.3, sad: 0.3, surprised: 0.2 },
  nostalgic: { sad: 0.4, happy: 0.3, relaxed: 0.2 },
  dreamy: { relaxed: 0.7, happy: 0.3 },
  determined: { angry: 0.3, neutral: 0.3 },
  mischievous: { happy: 0.6, surprised: 0.2 },
  curious: { surprised: 0.4, happy: 0.2 },
  melancholic: { sad: 0.6, relaxed: 0.3 },
};

const ALL_EXPRESSIONS = [
  "happy",
  "angry",
  "sad",
  "relaxed",
  "surprised",
  "neutral",
];

// Per-emotion head pose offsets (radians). Applied to the `head` bone on
// top of whatever the sleep layer does to the neck. Positive pitch = look
// down, negative = look up. Positive roll = tilt right (left ear down).
// Positive yaw = turn right.
interface HeadPose {
  pitch: number;
  roll: number;
  yaw: number;
}

const ZERO_POSE: HeadPose = { pitch: 0, roll: 0, yaw: 0 };

const EMOTION_HEAD_POSE: Partial<Record<EmotionName, HeadPose>> = {
  // Curiosity + thinking → classic head-tilt to one side
  curious:     { pitch: -0.04, roll:  0.10, yaw: 0 },
  thinking:    { pitch: -0.02, roll:  0.08, yaw: 0.03 },
  confused:    { pitch:  0.0,  roll: -0.10, yaw: 0 },
  // Embarrassment → head turns down-away
  embarrassed: { pitch:  0.08, roll: -0.05, yaw: -0.05 },
  // Proud → chin up slightly
  proud:       { pitch: -0.06, roll:  0.0,  yaw: 0 },
  determined:  { pitch: -0.03, roll:  0.0,  yaw: 0 },
  // Sad family → head down
  sad:         { pitch:  0.08, roll:  0.0,  yaw: 0 },
  lonely:      { pitch:  0.06, roll:  0.0,  yaw: 0 },
  melancholic: { pitch:  0.06, roll:  0.03, yaw: 0 },
  // Surprised → head back a touch
  surprised:   { pitch: -0.05, roll:  0.0,  yaw: 0 },
  scared:      { pitch: -0.03, roll:  0.04, yaw: 0 },
  // Dreamy / love → soft tilt
  dreamy:      { pitch: -0.02, roll:  0.05, yaw: 0 },
  love:        { pitch:  0.0,  roll:  0.04, yaw: 0 },
  // Mischievous → slight lean + side glance complement
  mischievous: { pitch: -0.02, roll:  0.06, yaw: 0.05 },
  // Everything else stays at rest
};

export class EmotionController {
  private vrm: VRM | null = null;
  private currentEmotion: EmotionName = "neutral";
  private intensity: number = 0.5;
  private targetWeights: BlendShapeTarget = {};
  private currentWeights: Map<string, number> = new Map();
  private transitionSpeed = 3.0;

  // Head pose state (eased toward target per-frame so changes are smooth).
  private currentHeadPose: HeadPose = { pitch: 0, roll: 0, yaw: 0 };
  private targetHeadPose: HeadPose = { pitch: 0, roll: 0, yaw: 0 };
  // Emotions where head pose is suppressed (avoid stacking with sleep).
  // Set to true when entering sleep phase; main.ts pushes this.
  private suppressHeadPose = false;

  setVRM(vrm: VRM) {
    this.vrm = vrm;
  }

  setEmotion(emotion: EmotionName, intensity: number = 0.7) {
    const clampedIntensity = Math.max(0.0, Math.min(1.0, intensity));
    if (emotion === this.currentEmotion && clampedIntensity === this.intensity)
      return;

    this.currentEmotion = emotion;
    this.intensity = clampedIntensity;

    // Scale blend shape targets by intensity
    const baseTargets = EMOTION_MAP[emotion] || {};
    this.targetWeights = {};
    for (const [key, value] of Object.entries(baseTargets)) {
      this.targetWeights[key] = value * clampedIntensity;
    }

    // Update target head pose — scaled by intensity so low-intensity
    // emotions barely tilt the head.
    const pose = EMOTION_HEAD_POSE[emotion] || ZERO_POSE;
    const scale = 0.3 + clampedIntensity * 0.7;
    this.targetHeadPose = {
      pitch: pose.pitch * scale,
      roll: pose.roll * scale,
      yaw: pose.yaw * scale,
    };

    console.log(
      `Emotion: ${emotion} (intensity: ${clampedIntensity.toFixed(2)})`
    );
  }

  /** Called by main.ts when sleep phase changes. Sleep owns the neck;
   * we freeze the head pose during sleep to avoid layered conflicts. */
  setSuppressHeadPose(suppressed: boolean): void {
    this.suppressHeadPose = suppressed;
    if (suppressed) {
      this.targetHeadPose = { pitch: 0, roll: 0, yaw: 0 };
    }
  }

  update(delta: number) {
    if (!this.vrm?.expressionManager) return;

    const lerpFactor = Math.min(1, delta * this.transitionSpeed);

    for (const name of ALL_EXPRESSIONS) {
      const target = this.targetWeights[name] ?? 0;
      const current = this.currentWeights.get(name) ?? 0;
      const newValue = current + (target - current) * lerpFactor;

      this.currentWeights.set(name, newValue);
      this.vrm.expressionManager.setValue(name, newValue);
    }

    this.updateHeadPose(delta);
  }

  private updateHeadPose(delta: number): void {
    if (!this.vrm?.humanoid) return;
    // While suppressed the target is (0,0,0) and we keep easing toward it:
    // bailing out here froze the head at whatever tilt the last emotion left,
    // which then stacked on top of the sleep neck tilt all night — exactly
    // the layered conflict the suppression exists to prevent.

    const ease = Math.min(1, delta * 2.0); // slower than expressions — natural
    this.currentHeadPose = {
      pitch:
        this.currentHeadPose.pitch +
        (this.targetHeadPose.pitch - this.currentHeadPose.pitch) * ease,
      roll:
        this.currentHeadPose.roll +
        (this.targetHeadPose.roll - this.currentHeadPose.roll) * ease,
      yaw:
        this.currentHeadPose.yaw +
        (this.targetHeadPose.yaw - this.currentHeadPose.yaw) * ease,
    };

    const head = this.vrm.humanoid.getNormalizedBoneNode("head");
    if (head) {
      head.rotation.x = this.currentHeadPose.pitch;
      head.rotation.y = this.currentHeadPose.yaw;
      head.rotation.z = this.currentHeadPose.roll;
    }
  }

  getCurrentEmotion(): EmotionName {
    return this.currentEmotion;
  }

  getIntensity(): number {
    return this.intensity;
  }
}
