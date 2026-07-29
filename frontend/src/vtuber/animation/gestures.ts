import type {
  EmotionBlend,
  EmotionName,
  GestureMapping,
  SleepPhase,
  VoicePersona,
} from "../../types";

/**
 * How each of the 29 emotions lands in the BODY. The face (expressions),
 * gaze bias and hand mood always react — a body gesture is a bonus on
 * top, never load-bearing. `satisfies` makes a missing 30th emotion a
 * compile error, not a silent gap.
 *
 * - oneshot:     a gesture clip plays once, then crossfades back
 * - idleVariant: the base idle pool is swapped for a posture clip
 *                (sad slump, nervous look-around…) until the next reply
 *                selects something else
 * - none:        face/gaze/head-tilt carry it alone — deliberate
 */
export const EMOTION_GESTURE = {
  neutral: { kind: "none" },
  // Positive
  happy: { kind: "oneshot", clip: "gesture_excited", minIntensity: 0.85 },
  excited: { kind: "oneshot", clip: "gesture_excited", minIntensity: 0.55 },
  love: { kind: "none" },
  proud: { kind: "none" }, // chin-up head pose carries it
  grateful: { kind: "oneshot", clip: "gesture_nod", minIntensity: 0.7 },
  playful: { kind: "oneshot", clip: "gesture_laugh", minIntensity: 0.75 },
  amused: { kind: "oneshot", clip: "gesture_laugh", minIntensity: 0.65 },
  hopeful: { kind: "none" },
  relieved: { kind: "oneshot", clip: "gesture_sigh", minIntensity: 0.7 },
  // Negative
  sad: { kind: "idleVariant", clip: "idle_sad", minIntensity: 0.6 },
  angry: { kind: "oneshot", clip: "gesture_angry", minIntensity: 0.65 },
  scared: { kind: "none" }, // gaze + face carry it
  disgusted: { kind: "oneshot", clip: "gesture_headshake", minIntensity: 0.7 },
  frustrated: { kind: "oneshot", clip: "gesture_headshake", minIntensity: 0.65 },
  lonely: { kind: "idleVariant", clip: "idle_sad", minIntensity: 0.6 },
  anxious: { kind: "idleVariant", clip: "idle_nervous", minIntensity: 0.55 },
  bored: { kind: "idleVariant", clip: "idle_bored", minIntensity: 0.5 },
  jealous: { kind: "none" }, // side-glance carries it
  // Complex
  surprised: { kind: "oneshot", clip: "gesture_surprised", minIntensity: 0.55 },
  thinking: { kind: "oneshot", clip: "gesture_think", minIntensity: 0.6 },
  confused: { kind: "oneshot", clip: "gesture_think", minIntensity: 0.7 },
  embarrassed: { kind: "oneshot", clip: "gesture_bashful", minIntensity: 0.6 },
  nostalgic: { kind: "none" },
  dreamy: { kind: "none" },
  determined: { kind: "none" },
  mischievous: { kind: "none" },
  curious: { kind: "none" }, // head tilt carries it
  melancholic: { kind: "idleVariant", clip: "idle_sad", minIntensity: 0.6 },
} as const satisfies Record<EmotionName, GestureMapping>;

/** Prosodic cue → gesture clip (bypasses the emote cooldown — the LLM
 * authored these as beats — but respects the sleep gate). */
export const CUE_GESTURE: Record<string, string | null> = {
  sigh: "gesture_sigh",
  laugh: "gesture_laugh",
  breath: null, // 350ms is too short for a body beat — deliberate no-op
};

export const GESTURE_COOLDOWN_S = 8;
export const DEFAULT_MIN_INTENSITY = 0.6;
/** blend[1] within this ratio of blend[0] = strong ambivalence → the
 * body stays still (stillness reads ambivalent; a clip picks a side). */
export const AMBIVALENCE_RATIO = 0.85;

export interface GestureDecisionInput {
  emotion: EmotionName;
  intensity: number;
  blend?: EmotionBlend;
  persona?: VoicePersona;
  sleepPhase: SleepPhase;
  nowMs: number;
  lastOneshotAtMs: number | null;
  /**
   * The emotion drifted on its own (backend emotion_update) rather than
   * being what Mika just said. Postures still follow — a mood that settles
   * into sadness should slump — but one-shots do not: a gesture is a
   * reaction, and a sustained emotion above threshold would otherwise fire
   * one every cooldown, forever, at nothing.
   */
  ambient?: boolean;
}

export type GestureDecision =
  | { action: "none"; reason: string }
  | { action: "oneshot"; clip: string }
  | { action: "idleVariant"; clip: string };

/** Pure gating logic — the order of the gates is the contract:
 * sleep → persona → ambivalence → mapping → ambient → threshold → cooldown. */
export function decideGesture(input: GestureDecisionInput): GestureDecision {
  if (input.sleepPhase !== "awake") {
    return { action: "none", reason: "asleep" };
  }
  // Murmured inner monologue with big gestures reads wrong: face only.
  if (input.persona === "inner") {
    return { action: "none", reason: "inner_persona" };
  }
  const blend = input.blend;
  if (
    blend &&
    blend.length >= 2 &&
    blend[0].weight > 0 &&
    blend[1].weight >= blend[0].weight * AMBIVALENCE_RATIO
  ) {
    return { action: "none", reason: "ambivalent" };
  }
  const mapping: GestureMapping = EMOTION_GESTURE[input.emotion];
  if (mapping.kind === "none" || !mapping.clip) {
    return { action: "none", reason: "unmapped" };
  }
  // Drift changes how she holds herself, never what she does.
  if (input.ambient && mapping.kind === "oneshot") {
    return { action: "none", reason: "ambient_drift" };
  }
  if (input.intensity < (mapping.minIntensity ?? DEFAULT_MIN_INTENSITY)) {
    return { action: "none", reason: "below_threshold" };
  }
  if (
    mapping.kind === "oneshot" &&
    input.lastOneshotAtMs !== null &&
    input.nowMs - input.lastOneshotAtMs < GESTURE_COOLDOWN_S * 1000
  ) {
    return { action: "none", reason: "cooldown" };
  }
  return { action: mapping.kind, clip: mapping.clip };
}
