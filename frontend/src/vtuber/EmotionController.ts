import { VRM } from "@pixiv/three-vrm";

export type EmotionName =
  | "neutral"
  | "happy"
  | "sad"
  | "angry"
  | "surprised"
  | "thinking"
  | "love";

interface BlendShapeTarget {
  [presetName: string]: number;
}

// Map emotions to VRM expression blend shapes
const EMOTION_MAP: Record<EmotionName, BlendShapeTarget> = {
  neutral: {},
  happy: { happy: 1.0 },
  sad: { sad: 1.0 },
  angry: { angry: 1.0 },
  surprised: { surprised: 1.0 },
  thinking: { neutral: 0.5 },
  love: { happy: 0.8, relaxed: 0.5 },
};

export class EmotionController {
  private vrm: VRM | null = null;
  private currentEmotion: EmotionName = "neutral";
  private targetWeights: BlendShapeTarget = {};
  private currentWeights: Map<string, number> = new Map();
  private transitionSpeed = 3.0; // lerp speed

  setVRM(vrm: VRM) {
    this.vrm = vrm;
  }

  setEmotion(emotion: EmotionName) {
    if (emotion === this.currentEmotion) return;
    this.currentEmotion = emotion;
    this.targetWeights = EMOTION_MAP[emotion] || {};
    console.log(`Emotion changed to: ${emotion}`);
  }

  update(delta: number) {
    if (!this.vrm?.expressionManager) return;

    const allExpressions = [
      "happy",
      "angry",
      "sad",
      "relaxed",
      "surprised",
      "neutral",
    ];
    const lerpFactor = Math.min(1, delta * this.transitionSpeed);

    for (const name of allExpressions) {
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
}
