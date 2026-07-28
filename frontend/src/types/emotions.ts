// Single source of truth for the 29 emotions, matching backend
// emotion/types.py::Emotion. Never re-declare EmotionName elsewhere.
export const EMOTION_NAMES = [
  "neutral",
  // Positive
  "happy",
  "excited",
  "love",
  "proud",
  "grateful",
  "playful",
  "amused",
  "hopeful",
  "relieved",
  // Negative
  "sad",
  "angry",
  "scared",
  "disgusted",
  "frustrated",
  "lonely",
  "anxious",
  "bored",
  "jealous",
  // Complex
  "surprised",
  "thinking",
  "confused",
  "embarrassed",
  "nostalgic",
  "dreamy",
  "determined",
  "mischievous",
  "curious",
  "melancholic",
] as const;

export type EmotionName = (typeof EMOTION_NAMES)[number];

const EMOTION_SET: ReadonlySet<string> = new Set(EMOTION_NAMES);

export function isEmotionName(value: unknown): value is EmotionName {
  return typeof value === "string" && EMOTION_SET.has(value);
}
