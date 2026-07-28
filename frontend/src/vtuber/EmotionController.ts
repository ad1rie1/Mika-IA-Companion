import { VRM } from "@pixiv/three-vrm";
import { EMOTION_NAMES, type EmotionName } from "../types";

/**
 * FACE-ONLY emotion rendering: maps the 29 emotions to VRM expression
 * weights with intensity scaling and per-frame easing.
 *
 * The emotional head pose that used to live here moved to
 * vtuber/animation/overlays/HeadEmotionOverlay.ts — it now composes an
 * additive delta ON TOP of the clip-driven head, instead of absolute
 * Euler writes that would erase clip motion.
 */

interface BlendShapeTarget {
  [presetName: string]: number;
}

// Fallback map for models that only expose the standard VRM presets
// (weights at intensity 1.0). Note: on VRM 0.x models three-vrm exposes
// joy/sorrow/fun as happy/sad/relaxed, and "surprised" may not exist.
const STANDARD_EMOTION_MAP: Record<EmotionName, BlendShapeTarget> = {
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

// Map for the Perula model (PerfectSync build), whose custom expressions
// are far richer than the standard presets — its standard `angry` preset
// is even empty (0 binds), so anger MUST go through the custom shapes.
// Names are case-sensitive and match blendShapeGroups in the .vrm.
const PERULA_EMOTION_MAP: Record<EmotionName, BlendShapeTarget> = {
  neutral: {},

  // --- Positive ---
  happy: { Smile1: 1.0 },
  excited: { Joy2: 0.9, InWonder: 0.2 },
  love: { Love1: 0.9 },
  proud: { Prond: 0.9 }, // sic — the model's author spelled "proud" this way
  grateful: { Smile2: 0.8, Relaxy: 0.2 },
  playful: { Smile4: 0.7, Wink1: 0.3 },
  amused: { LMAO: 0.85 },
  hopeful: { Smile3: 0.5, InWonder: 0.4 },
  relieved: { Relaxy: 0.9 },

  // --- Negative ---
  sad: { Sad1: 0.9 },
  angry: { Angry1: 0.9 },
  scared: { Shocked2: 0.7, Pain: 0.25 },
  disgusted: { Disgust: 0.9 },
  frustrated: { Angry2: 0.7, GiveUp: 0.25 },
  lonely: { Sad3: 0.8 },
  anxious: { Pain: 0.5, Sad1: 0.3 },
  bored: { Boring: 0.85 },
  jealous: { BadSmile2: 0.5, Angry2: 0.4 },

  // --- Complex ---
  surprised: { Shocked: 0.9 },
  thinking: { Interesting: 0.55, Numbly: 0.15 },
  confused: { Hau: 0.7 },
  embarrassed: { Shy: 0.85 },
  nostalgic: { Sad2: 0.35, Smile2: 0.35, Relaxy: 0.2 },
  dreamy: { InWonder: 0.6, Relaxy: 0.3 },
  determined: { Healthy: 0.6, Angry4: 0.2 },
  mischievous: { BadSmile1: 0.7, Taunt1: 0.2 },
  curious: { Interesting: 0.8 },
  melancholic: { Sad2: 0.6, Relaxy: 0.2 },
};

export class EmotionController {
  private vrm: VRM | null = null;
  private currentEmotion: EmotionName = "neutral";
  private intensity: number = 0.5;
  private targetWeights: BlendShapeTarget = {};
  private currentWeights: Map<string, number> = new Map();
  private transitionSpeed = 3.0;
  private activeMap: Record<EmotionName, BlendShapeTarget> =
    STANDARD_EMOTION_MAP;

  setVRM(vrm: VRM) {
    this.vrm = vrm;
    this.activeMap = this.resolveEmotionMap(vrm);
    // Re-apply the current emotion so the new map takes effect immediately
    const emotion = this.currentEmotion;
    this.currentEmotion = "neutral";
    this.setEmotion(emotion, this.intensity);
  }

  /** Per emotion, prefer the rich (Perula) entry when the model exposes
   * every expression it needs; otherwise fall back to the standard-preset
   * entry. Models are mixed freely: a partial match degrades per-emotion,
   * not globally. */
  private resolveEmotionMap(vrm: VRM): Record<EmotionName, BlendShapeTarget> {
    const manager = vrm.expressionManager;
    if (!manager) return STANDARD_EMOTION_MAP;

    const has = (name: string) => manager.getExpression(name) != null;
    const resolved = {} as Record<EmotionName, BlendShapeTarget>;
    let richCount = 0;

    for (const emotion of Object.keys(PERULA_EMOTION_MAP) as EmotionName[]) {
      const rich = PERULA_EMOTION_MAP[emotion];
      const richKeys = Object.keys(rich);
      if (richKeys.length > 0 && richKeys.every(has)) {
        resolved[emotion] = rich;
        richCount++;
      } else {
        resolved[emotion] = STANDARD_EMOTION_MAP[emotion];
      }
    }

    console.log(
      `EmotionController: ${richCount}/${EMOTION_NAMES.length} emotions using rich model expressions`
    );
    return resolved;
  }

  setEmotion(emotion: EmotionName, intensity: number = 0.7) {
    const clampedIntensity = Math.max(0.0, Math.min(1.0, intensity));
    if (emotion === this.currentEmotion && clampedIntensity === this.intensity)
      return;

    this.currentEmotion = emotion;
    this.intensity = clampedIntensity;

    // Scale blend shape targets by intensity
    const baseTargets = this.activeMap[emotion] || {};
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

    // Ease every expression touched by the current OR a previous emotion,
    // so switching emotions fades the old shapes out instead of snapping.
    const names = new Set<string>([
      ...Object.keys(this.targetWeights),
      ...this.currentWeights.keys(),
    ]);

    for (const name of names) {
      const target = this.targetWeights[name] ?? 0;
      const current = this.currentWeights.get(name) ?? 0;
      const newValue = current + (target - current) * lerpFactor;

      if (target === 0 && newValue < 0.001) {
        // Fully faded out — write the final 0 and stop tracking.
        this.currentWeights.delete(name);
        this.vrm.expressionManager.setValue(name, 0);
        continue;
      }

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
