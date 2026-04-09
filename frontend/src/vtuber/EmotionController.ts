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

export class EmotionController {
  private vrm: VRM | null = null;
  private currentEmotion: EmotionName = "neutral";
  private intensity: number = 0.5;
  private targetWeights: BlendShapeTarget = {};
  private currentWeights: Map<string, number> = new Map();
  private transitionSpeed = 3.0;

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

    console.log(
      `Emotion: ${emotion} (intensity: ${clampedIntensity.toFixed(2)})`
    );
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
  }

  getCurrentEmotion(): EmotionName {
    return this.currentEmotion;
  }

  getIntensity(): number {
    return this.intensity;
  }
}
