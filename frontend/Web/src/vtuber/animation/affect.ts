import type { ClipManifestEntry, EmotionName } from "../../types";

/**
 * Valence (pleasure) and arousal of the 29 emotions — the P and A columns of
 * the backend's PAD anchors (`emotion/pad.py::PAD_ANCHORS`), copied rather
 * than re-invented so the body reads the same affect the mood engine
 * computes. `satisfies` makes a 30th emotion a compile error here too.
 *
 * What they drive: which base clip the pool picks (a heated talking clip
 * for an angry reply, never for a dreamy one), how fast it plays, and how
 * long it is held before rotating. None of it is load-bearing — a manifest
 * declaring no affect on its clips gets the historical uniform rotation.
 */
export const EMOTION_VALENCE = {
  neutral: 0.0,
  happy: 0.8, excited: 0.7, love: 0.9, proud: 0.7, grateful: 0.7,
  playful: 0.7, amused: 0.7, hopeful: 0.6, relieved: 0.5,
  sad: -0.7, angry: -0.6, scared: -0.7, disgusted: -0.7, frustrated: -0.5,
  lonely: -0.7, anxious: -0.5, bored: -0.3, jealous: -0.5,
  surprised: 0.1, thinking: 0.1, confused: -0.2, embarrassed: -0.3,
  nostalgic: 0.2, dreamy: 0.4, determined: 0.4, mischievous: 0.5,
  curious: 0.4, melancholic: -0.5,
} as const satisfies Record<EmotionName, number>;

export const EMOTION_AROUSAL = {
  neutral: 0.0,
  happy: 0.3, excited: 0.9, love: 0.4, proud: 0.3, grateful: 0.1,
  playful: 0.6, amused: 0.4, hopeful: 0.2, relieved: -0.3,
  sad: -0.3, angry: 0.8, scared: 0.7, disgusted: 0.3, frustrated: 0.6,
  lonely: -0.4, anxious: 0.6, bored: -0.6, jealous: 0.5,
  surprised: 0.8, thinking: 0.1, confused: 0.3, embarrassed: 0.4,
  nostalgic: -0.2, dreamy: -0.3, determined: 0.5, mischievous: 0.5,
  curious: 0.5, melancholic: -0.5,
} as const satisfies Record<EmotionName, number>;

/** Gain of the affinity term; bounds keep a mismatched clip *rare*, never
 * impossible (a pool must stay a pool), and a matched one favoured, never
 * exclusive. */
export const AFFINITY_GAIN = 1.5;
export const AFFINITY_MIN = 0.15;
export const AFFINITY_MAX = 2.5;

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/**
 * Multiplier on a base clip's pick weight, from the affect it declares
 * (`arousal` / `valence` in the manifest, −1…1) against the current emotion.
 * A clip declaring nothing keeps its weight — the affect layer is opt-in per
 * clip, and a manifest without it is byte-identical to before.
 */
export function clipAffinity(
  entry: Pick<ClipManifestEntry, "arousal" | "valence">,
  emotion: EmotionName,
  intensity: number
): number {
  const a = entry.arousal ?? 0;
  const v = entry.valence ?? 0;
  if (a === 0 && v === 0) return 1;
  const s = clamp(intensity, 0, 1);
  const match = a * EMOTION_AROUSAL[emotion] * s + v * EMOTION_VALENCE[emotion] * s;
  return clamp(1 + AFFINITY_GAIN * match, AFFINITY_MIN, AFFINITY_MAX);
}

/** Playback tempo of a base clip: agitation speeds it up a little, torpor
 * slows it down — bounded so a clip never reads as fast-forwarded. */
/**
 * How wide the mouth moves when she speaks (LipSyncController
 * `setArticulation`): an excited voice articulates big, a sad, bored or
 * tired one barely parts the lips. Arousal × intensity, minus tiredness.
 */
export function articulationFor(emotion: EmotionName, intensity: number, fatigue = 0): number {
  const a = EMOTION_AROUSAL[emotion] * Math.max(0, Math.min(1, intensity));
  return Math.max(0.6, Math.min(1.15, 1 + 0.35 * a - 0.25 * Math.max(0, Math.min(1, fatigue))));
}

export const TEMPO_GAIN = 0.12;
export const TEMPO_MIN = 0.85;
export const TEMPO_MAX = 1.15;

export function affectTimeScale(emotion: EmotionName, intensity: number): number {
  const s = clamp(intensity, 0, 1);
  return clamp(1 + TEMPO_GAIN * EMOTION_AROUSAL[emotion] * s, TEMPO_MIN, TEMPO_MAX);
}

/** Hold multiplier before a pool rotation: an agitated body changes stance
 * sooner, a low-arousal one settles longer. */
export const HOLD_GAIN = 0.35;
export const HOLD_MIN = 0.6;
export const HOLD_MAX = 1.4;

export function affectHoldScale(emotion: EmotionName, intensity: number): number {
  const s = clamp(intensity, 0, 1);
  return clamp(1 - HOLD_GAIN * EMOTION_AROUSAL[emotion] * s, HOLD_MIN, HOLD_MAX);
}
