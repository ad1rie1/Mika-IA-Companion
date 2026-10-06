import type { HandShapeName } from "../../types";
import type { AttentionFocus } from "./attention";

/**
 * What she does in her room, as the body shows it: where her eyes rest and
 * how her hands hold it. The backend decides the activity (faculty `world`,
 * `inner_state.activity`); this table only reads its name, and a name it
 * does not know shows nothing — like a place unknown to roomLayout.ts.
 *
 * No clip per activity: a gaze and a hand are enough to read "absorbed",
 * and the place already turned her toward the thing (the window, the desk,
 * the shelves — roomLayout.ts `facing`). So the gaze is relative to her
 * forward, in the semantic frame (pitch > 0 down, yaw > 0 her left); the
 * head follows part of it (HeadAttentionOverlay), the eyes the rest.
 */
export interface ActivityFocus extends AttentionFocus {
  /** Finger shapes [left, right] while she does it; absent: the clip's. */
  hands?: readonly [HandShapeName, HandShapeName];
  /** Multiplies the fingers' fidget: a drawing hand keeps moving. */
  handMotion?: number;
}

export const ACTIVITY_NAMES = ["look_outside", "draw", "work", "browse_books", "water_plant"] as const;
export type ActivityName = (typeof ACTIVITY_NAMES)[number];

export const ACTIVITY_FOCUS: Record<ActivityName, ActivityFocus> = {
  // Facing out of the window: a little up, far away.
  look_outside: { gaze: { pitch: -0.06, yaw: 0.04 }, contact: 0.05 },
  // Bent over the sheet on her desk, the pencil in her right hand.
  draw: { gaze: { pitch: 0.5, yaw: -0.06 }, contact: 0, hands: ["relaxed", "grip"], handMotion: 2.2 },
  work: { gaze: { pitch: 0.42, yaw: 0.04 }, contact: 0.05, hands: ["relaxed", "grip"], handMotion: 1.6 },
  // Before the shelves, a book open in both hands.
  browse_books: { gaze: { pitch: 0.36, yaw: 0 }, contact: 0.05, hands: ["grip", "grip"], handMotion: 1.3 },
  // Down at the plant, the watering can in her right hand.
  water_plant: { gaze: { pitch: 0.4, yaw: -0.08 }, contact: 0, hands: ["relaxed", "grip"] },
};

const ACTIVITY_SET: ReadonlySet<string> = new Set(ACTIVITY_NAMES);
export function isActivityName(value: unknown): value is ActivityName {
  return typeof value === "string" && ACTIVITY_SET.has(value);
}

/** How the body shows an activity; null for nothing or an unknown name. */
export function activityFocus(name: unknown): ActivityFocus | null {
  return isActivityName(name) ? ACTIVITY_FOCUS[name] : null;
}
