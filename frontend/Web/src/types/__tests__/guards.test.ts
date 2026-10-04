import { describe, expect, it } from "vitest";
import {
  EMOTION_NAMES,
  SLEEP_PHASES,
  isEmotionName,
  isSleepPhase,
} from "..";

describe("type guards", () => {
  it("accepts every canonical emotion and rejects junk", () => {
    for (const name of EMOTION_NAMES) expect(isEmotionName(name)).toBe(true);
    expect(EMOTION_NAMES).toHaveLength(29);
    expect(isEmotionName("joyful")).toBe(false);
    expect(isEmotionName("")).toBe(false);
    expect(isEmotionName(undefined)).toBe(false);
    expect(isEmotionName(42)).toBe(false);
  });

  it("accepts every sleep phase and rejects junk", () => {
    for (const phase of SLEEP_PHASES) expect(isSleepPhase(phase)).toBe(true);
    expect(SLEEP_PHASES).toHaveLength(4);
    expect(isSleepPhase("asleep")).toBe(false);
    expect(isSleepPhase(null)).toBe(false);
  });
});
