import { describe, expect, it } from "vitest";
import { EMOTION_NAMES } from "../../../types";
import {
  AFFINITY_MAX,
  AFFINITY_MIN,
  EMOTION_AROUSAL,
  EMOTION_VALENCE,
  HOLD_MAX,
  HOLD_MIN,
  TEMPO_MAX,
  TEMPO_MIN,
  affectHoldScale,
  affectTimeScale,
  clipAffinity,
} from "../affect";

describe("affect tables", () => {
  it("cover exactly the 29 emotions, within [−1, 1]", () => {
    for (const table of [EMOTION_AROUSAL, EMOTION_VALENCE]) {
      expect(Object.keys(table)).toHaveLength(EMOTION_NAMES.length);
      for (const name of EMOTION_NAMES) {
        const v = table[name];
        expect(v, name).toBeGreaterThanOrEqual(-1);
        expect(v, name).toBeLessThanOrEqual(1);
      }
    }
    expect(EMOTION_AROUSAL.neutral).toBe(0);
    expect(EMOTION_VALENCE.neutral).toBe(0);
  });

  it("agree with the PAD anchors on the obvious cases", () => {
    expect(EMOTION_AROUSAL.excited).toBeGreaterThan(EMOTION_AROUSAL.sad);
    expect(EMOTION_AROUSAL.bored).toBeLessThan(0);
    expect(EMOTION_VALENCE.love).toBeGreaterThan(0.5);
    expect(EMOTION_VALENCE.sad).toBeLessThan(-0.5);
  });
});

describe("clipAffinity", () => {
  it("a clip declaring no affect keeps its weight for every emotion", () => {
    for (const name of EMOTION_NAMES) {
      expect(clipAffinity({}, name, 1)).toBe(1);
    }
  });

  it("a heated clip is favoured for anger and rare for reverie", () => {
    const heated = { arousal: 0.8 };
    expect(clipAffinity(heated, "angry", 0.8)).toBeGreaterThan(1.3);
    expect(clipAffinity(heated, "dreamy", 0.8)).toBeLessThan(0.75);
    expect(clipAffinity(heated, "neutral", 0.8)).toBe(1);
  });

  it("a cheerful idle is avoided when she is sad", () => {
    const cheerful = { valence: 0.7 };
    expect(clipAffinity(cheerful, "sad", 0.8)).toBeLessThan(0.6);
    expect(clipAffinity(cheerful, "happy", 0.8)).toBeGreaterThan(1.4);
  });

  it("stays within its bounds and scales with intensity", () => {
    for (const name of EMOTION_NAMES) {
      const v = clipAffinity({ arousal: 1, valence: 1 }, name, 1);
      expect(v).toBeGreaterThanOrEqual(AFFINITY_MIN);
      expect(v).toBeLessThanOrEqual(AFFINITY_MAX);
    }
    expect(clipAffinity({ arousal: 0.8 }, "angry", 0)).toBe(1);
  });
});

describe("tempo and hold", () => {
  it("agitation plays faster and rotates sooner; torpor the reverse; both bounded", () => {
    expect(affectTimeScale("excited", 1)).toBeGreaterThan(1);
    expect(affectTimeScale("melancholic", 1)).toBeLessThan(1);
    expect(affectHoldScale("excited", 1)).toBeLessThan(1);
    expect(affectHoldScale("melancholic", 1)).toBeGreaterThan(1);
    for (const name of EMOTION_NAMES) {
      expect(affectTimeScale(name, 1)).toBeGreaterThanOrEqual(TEMPO_MIN);
      expect(affectTimeScale(name, 1)).toBeLessThanOrEqual(TEMPO_MAX);
      expect(affectHoldScale(name, 1)).toBeGreaterThanOrEqual(HOLD_MIN);
      expect(affectHoldScale(name, 1)).toBeLessThanOrEqual(HOLD_MAX);
    }
    expect(affectTimeScale("excited", 0)).toBe(1);
  });
});
