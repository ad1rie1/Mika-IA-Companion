import { VRM } from "@pixiv/three-vrm";
import { EMOTION_NAMES, isEmotionName, type EmotionBlend, type EmotionName } from "../types";
import { cleanName, registerCleanGroups } from "./faceRig";
import { FacePhysiology } from "./FacePhysiology";

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
// Names are the model's groups (case-sensitive), played through their
// `clean:` copies (faceRig.registerCleanGroups): the author's brows, lids
// and mouth, WITHOUT the manga symbols bundled in — `Shocked` drew swirl
// eyes and a sweat drop on every surprise, `Sad1`/`Sad3`/`Angry1`/`LMAO` a
// tear at any intensity, `Healthy` (determined) dark circles, `BadSmile2`
// (jealous) black eyes, `Numbly` (thinking) swirl eyes, `Hau` (confused)
// ><-eyes. Blush and tears now come from FacePhysiology, on their own
// slow clock and only when the feeling is strong enough.
const PERULA_EMOTION_MAP: Record<EmotionName, BlendShapeTarget> = {
  neutral: {},

  // --- Positive ---
  happy: { Smile1: 1.0 },
  excited: { Joy2: 0.9, InWonder: 0.2 },
  love: { Love1: 0.9 },
  proud: { Prond: 0.9 }, // sic — the model's author spelled "proud" this way
  grateful: { Smile2: 0.8, Relaxy: 0.15 },
  playful: { Smile4: 0.7, Wink1: 0.25 },
  amused: { LMAO: 0.8 },
  hopeful: { Smile3: 0.5, InWonder: 0.35 },
  relieved: { Relaxy: 0.7, Smile2: 0.2 },

  // --- Negative ---
  sad: { Sad1: 0.85 },
  angry: { Angry4: 0.7, Angry1: 0.3 },
  scared: { Shocked2: 0.7, Pain: 0.25 },
  disgusted: { Disgust: 0.85 },
  frustrated: { Angry2: 0.6, GiveUp: 0.25 },
  lonely: { Sad3: 0.8 },
  anxious: { Pain: 0.45, Sad1: 0.25 },
  bored: { Boring: 0.85 },
  jealous: { BadSmile2: 0.5, Angry2: 0.35 },

  // --- Complex ---
  surprised: { Shocked: 0.9 },
  thinking: { Numbly: 0.35, Interesting: 0.15 },
  confused: { Hau: 0.55 },
  embarrassed: { Shy: 0.85 },
  nostalgic: { Sad2: 0.3, Smile2: 0.35, Relaxy: 0.2 },
  dreamy: { InWonder: 0.55, Relaxy: 0.3 },
  determined: { Healthy: 0.6, Angry4: 0.2 },
  mischievous: { BadSmile1: 0.65, Taunt1: 0.2 },
  curious: { Interesting: 0.75 },
  melancholic: { Sad2: 0.55, Relaxy: 0.2 },
};

/**
 * Share of a secondary emotion shown on the face, relative to its weight
 * in the blend. Real faces are rarely one emotion: a smile through
 * sadness, worry under a laugh. The body stays still on strong ambivalence
 * (gestures.ts); the face shows both.
 */
export const SECONDARY_SHARE = 0.45;

/** The model's sleepy face (heavy lids, parted lips), cleaned, at most this
 * much on a tired awake face. */
const TIRED_GROUP = "Sleepy";
const TIRED_MAX = 0.32;
/** Below this weight ratio the secondary is noise, not a feeling. */
export const SECONDARY_MIN_RATIO = 0.3;

/** Slow incommensurate sines — a held expression breathes instead of
 * freezing at an exact weight. Amplitude is a few percent: the point is
 * that the face is never bit-for-bit identical across frames. */
function pulse(t: number, seed: number): number {
  return (
    (Math.sin(t * 0.43 + seed * 2.1) + Math.sin(t * 0.79 + seed * 4.3) * 0.5) /
    1.5
  );
}

const PULSE_AMPLITUDE = 0.05;

/**
 * Onset speed per emotion (1/s of the exponential ease). Real expressions
 * do not all arrive at one speed: a startle lands in ~100–200 ms, a smile
 * in ~300–500 ms, sadness and reverie settle in over most of a second. And
 * every expression LEAVES more slowly than it arrives (`OFFSET_RATIO`) —
 * a face that snaps back to neutral at the same rate it lit up is one of
 * the surest "it's a rig" tells.
 */
export const ONSET_SPEED: Partial<Record<EmotionName, number>> = {
  surprised: 9,
  scared: 8,
  excited: 6,
  angry: 5,
  amused: 5,
  playful: 5,
  disgusted: 4.5,
  frustrated: 4,
  curious: 4,
  happy: 3.5,
  sad: 1.8,
  lonely: 1.8,
  melancholic: 1.6,
  nostalgic: 1.6,
  dreamy: 1.6,
  relieved: 2.2,
  bored: 2.0,
  love: 2.2,
  grateful: 2.5,
  hopeful: 2.5,
};
export const DEFAULT_ONSET_SPEED = 3.0;
export const OFFSET_RATIO = 0.6;
/** An expression never lingers longer than ~0.8 s of time constant. */
export const MIN_OFFSET_SPEED = 1.2;

export function onsetSpeedFor(emotion: EmotionName): number {
  return ONSET_SPEED[emotion] ?? DEFAULT_ONSET_SPEED;
}

export function offsetSpeedFor(emotion: EmotionName): number {
  return Math.max(MIN_OFFSET_SPEED, onsetSpeedFor(emotion) * OFFSET_RATIO);
}

/** The strongest feeling in the blend other than the primary, with its
 * weight relative to the primary's; null when there is none worth showing. */
export function secondaryOf(
  primary: EmotionName,
  blend: EmotionBlend
): { emotion: EmotionName; ratio: number } | null {
  if (blend.length < 2) return null;
  const top = blend.find((b) => b.emotion === primary)?.weight ?? blend[0].weight;
  if (!(top > 0)) return null;
  for (const other of blend) {
    if (other.emotion === primary || other.emotion === "neutral") continue;
    if (!isEmotionName(other.emotion)) continue;
    const ratio = Math.min(1, other.weight / top);
    return ratio >= SECONDARY_MIN_RATIO ? { emotion: other.emotion, ratio } : null;
  }
  return null;
}

export class EmotionController {
  private vrm: VRM | null = null;
  private currentEmotion: EmotionName = "neutral";
  private intensity: number = 0.5;
  private targetWeights: BlendShapeTarget = {};
  private currentWeights: Map<string, number> = new Map();
  private time = 0;
  private activeMap: Record<EmotionName, BlendShapeTarget> =
    STANDARD_EMOTION_MAP;
  private blendKey = "";
  private blend: EmotionBlend = [];
  /** Heavy lids of a tired face (clean:Sleepy), 0…TIRED_MAX. */
  private tiredTarget = 0;
  private tiredName: string | null = null;
  /** Blush, tears and pupils — the face's slow, non-muscular layer. */
  readonly physiology = new FacePhysiology();

  setVRM(vrm: VRM) {
    this.vrm = vrm;
    this.physiology.setVRM(vrm);
    this.activeMap = this.resolveEmotionMap(vrm);
    // Re-apply the current emotion so the new map takes effect immediately
    const emotion = this.currentEmotion;
    this.currentEmotion = "neutral";
    this.setEmotion(emotion, this.intensity, this.blend);
  }

  /** Per emotion, prefer the rich (Perula) entry when the model exposes
   * every expression it needs; otherwise fall back to the standard-preset
   * entry. Models are mixed freely: a partial match degrades per-emotion,
   * not globally. */
  private resolveEmotionMap(vrm: VRM): Record<EmotionName, BlendShapeTarget> {
    const manager = vrm.expressionManager;
    if (!manager) return STANDARD_EMOTION_MAP;

    const groups = new Set<string>();
    for (const recipe of Object.values(PERULA_EMOTION_MAP)) {
      for (const group of Object.keys(recipe)) groups.add(group);
    }
    const clean = registerCleanGroups(vrm, [...groups, TIRED_GROUP]);
    this.tiredName = clean.has(TIRED_GROUP) ? cleanName(TIRED_GROUP) : null;
    const resolved = {} as Record<EmotionName, BlendShapeTarget>;
    let richCount = 0;

    for (const emotion of Object.keys(PERULA_EMOTION_MAP) as EmotionName[]) {
      const rich = PERULA_EMOTION_MAP[emotion];
      const richKeys = Object.keys(rich);
      if (richKeys.length > 0 && richKeys.every((g) => clean.has(g))) {
        resolved[emotion] = Object.fromEntries(
          Object.entries(rich).map(([g, w]) => [cleanName(g), w])
        );
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

  setEmotion(emotion: EmotionName, intensity: number = 0.7, blend: EmotionBlend = []) {
    const clampedIntensity = Math.max(0.0, Math.min(1.0, intensity));
    const secondary = secondaryOf(emotion, blend);
    const blendKey = secondary ? `${secondary.emotion}:${secondary.ratio.toFixed(2)}` : "";
    this.physiology.setEmotion(emotion, clampedIntensity);
    if (
      emotion === this.currentEmotion &&
      clampedIntensity === this.intensity &&
      blendKey === this.blendKey
    )
      return;

    this.currentEmotion = emotion;
    this.intensity = clampedIntensity;
    this.blendKey = blendKey;
    this.blend = blend;

    // Scale blend shape targets by intensity; a secondary feeling shows
    // through at a share of its weight, making room in the primary.
    const baseTargets = this.activeMap[emotion] || {};
    const primaryScale = secondary ? 1 - 0.25 * secondary.ratio : 1;
    this.targetWeights = {};
    for (const [key, value] of Object.entries(baseTargets)) {
      this.targetWeights[key] = value * clampedIntensity * primaryScale;
    }
    if (secondary) {
      const share = clampedIntensity * secondary.ratio * SECONDARY_SHARE;
      for (const [key, value] of Object.entries(this.activeMap[secondary.emotion] || {})) {
        this.targetWeights[key] = Math.min(1, (this.targetWeights[key] ?? 0) + value * share);
      }
    }

    console.log(
      `Emotion: ${emotion} (intensity: ${clampedIntensity.toFixed(2)})`
    );
  }

  update(delta: number) {
    if (!this.vrm?.expressionManager) return;

    this.time += delta;
    this.physiology.update(delta);
    // Onset at the emotion's own speed, offset slower — per shape, since a
    // shape leaving (the previous emotion's) and one arriving coexist.
    const onset = Math.min(1, delta * onsetSpeedFor(this.currentEmotion));
    const offset = Math.min(1, delta * offsetSpeedFor(this.currentEmotion));

    // Ease every expression touched by the current OR a previous emotion,
    // so switching emotions fades the old shapes out instead of snapping.
    const names = new Set<string>([
      ...Object.keys(this.targetWeights),
      ...this.currentWeights.keys(),
    ]);
    if (this.tiredName && this.tiredTarget > 0) names.add(this.tiredName);

    let seed = 0;
    for (const name of names) {
      seed++;
      const target =
        (this.targetWeights[name] ?? 0) + (name === this.tiredName ? this.tiredTarget : 0);
      const current = this.currentWeights.get(name) ?? 0;
      const lerpFactor = target > current ? onset : offset;
      const newValue = current + (target - current) * lerpFactor;

      if (target === 0 && newValue < 0.001) {
        // Fully faded out — write the final 0 and stop tracking.
        this.currentWeights.delete(name);
        this.vrm.expressionManager.setValue(name, 0);
        continue;
      }

      // Track the clean eased value; the pulse only shades what is
      // written, so it can't accumulate into the easing state.
      this.currentWeights.set(name, newValue);
      const shaded = newValue * (1 + pulse(this.time, seed) * PULSE_AMPLITUDE);
      this.vrm.expressionManager.setValue(
        name,
        Math.max(0, Math.min(1, shaded))
      );
    }
  }

  /** Energy 0…1: past ~0.55 of tiredness the lids get heavy and the lips
   * part a little — slowly, it is not an expression. */
  setEnergy(energy: number): void {
    const fatigue = Math.max(0, Math.min(1, (0.55 - energy) / 0.4));
    this.tiredTarget = TIRED_MAX * fatigue;
  }

  getCurrentEmotion(): EmotionName {
    return this.currentEmotion;
  }

  getIntensity(): number {
    return this.intensity;
  }
}
