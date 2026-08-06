import type { EmotionName } from "./emotions";
import type { SleepPhase } from "./sleep";

// ── Animation state machine ─────────────────────────────────────────

// "walking" and "interacting" are reserved for the v2 locomotion /
// environment-interaction work; the state machine declares them but
// refuses to enter them until LOCOMOTION_ENABLED is flipped.
export type AnimationStateName =
  | "idle"
  | "talking"
  | "gesture"
  | "sleeping"
  | "walking"
  | "interacting";

// Non-verbal audio beats parsed from [SIGH]/[LAUGH]/[BREATH] tokens by
// the TTS — mirrored into body animation cues.
export type ProsodicCue = "sigh" | "laugh" | "breath";

// Découpage de la restitution tel que le TTS va réellement la jouer
// (TTSService.lipSyncPlan) : ce qui est prononcé, et le temps que les
// tokens de prosodie réservent sans qu'un mot soit dit. Le lip-sync en a
// besoin pour articuler la bonne chaîne et se taire pendant les silences.
export type SpeechPlanSegment =
  | { type: "speech"; text: string }
  | { type: "silence"; ms: number };

// ── Emotion → body gesture mapping ──────────────────────────────────

export type GestureKind = "oneshot" | "idleVariant" | "none";

export interface GestureMapping {
  kind: GestureKind;
  /** Manifest clip name; required unless kind === "none". */
  clip?: string;
  /** Emotion intensity below which the body stays still (face only). */
  minIntensity?: number;
}

// ── Hands ───────────────────────────────────────────────────────────

/** Named finger shapes owned by the procedural HandAnimator. */
export type HandShapeName = "relaxed" | "open" | "tucked" | "loose" | "clasp";

// ── Clip manifest (public/animations/manifest.json) ─────────────────

export type ClipCategory = "idle" | "talk" | "gesture" | "sleep" | "locomotion";

export interface ClipManifestEntry {
  /** URL relative to the site root, e.g. "/animations/idle/idle_breathing.fbx". */
  url: string;
  category: ClipCategory;
  /** Loop the clip (default true for idle/talk/sleep, false for gesture). */
  loop?: boolean;
  /** Relative pick probability within its category pool (default 1). */
  weight?: number;
  /** [min, max] seconds to hold before rotating to another pool clip. */
  hold?: [number, number];
  fadeIn?: number;
  fadeOut?: number;
  timeScale?: number;
  /** Finger shapes [left, right] forwarded to the HandAnimator. */
  hands?: [HandShapeName, HandShapeName];
  /** Zero the hips X/Z position track (in-place enforcement, locomotion). */
  stripRootXZ?: boolean;
}

export interface AnimationManifest {
  version: number;
  clips: Record<string, ClipManifestEntry>;
  /** Which clip plays per sleep phase (defaults to the first idle clip). */
  sleep?: Partial<
    Record<Exclude<SleepPhase, "awake">, { clip: string; timeScale?: number }>
  >;
}

// ── v2 seams: environment anchors (design-only, unused in v1) ───────

export type AnchorId = "bed_lie" | "desk_sit" | "window_stand";

export interface EnvironmentAnchor {
  id: AnchorId;
  /** Room-space settle position. */
  position: [number, number, number];
  /** Yaw (radians) once settled. */
  facing: number;
  /** Walk-to point reached before playing enterClip. */
  approach?: [number, number, number];
  enterClip?: string;
  exitClip?: string;
  pose: "stand" | "sit" | "lie";
}

// ── v2 seams: backend-synced body state (design-only, unused in v1) ─

/**
 * Serializable body-state snapshot. In v2 the backend becomes the
 * authority and broadcasts these as `avatar_state` frames so every
 * connected client renders the same pose; today it is only produced
 * locally by AnimationSystem.getSnapshot() for debugging.
 */
export interface AvatarStateSnapshot {
  /** Monotonic sequence number (backend-assigned in v2; 0 locally). */
  seq: number;
  /** Epoch ms at capture. */
  t: number;
  position: [number, number, number];
  /** Yaw radians of the avatar root. */
  facing: number;
  behaviorState: AnimationStateName;
  clipName?: string | null;
  /** Seconds into the current clip at time t. */
  clipTime?: number;
  sleepPhase: SleepPhase;
  emotion: EmotionName;
  emotionIntensity: number;
  anchorId?: AnchorId | null;
}
