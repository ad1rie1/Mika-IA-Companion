import { describe, expect, it } from "vitest";
import { EMOTION_NAMES } from "../../../types";
import {
  AMBIVALENCE_RATIO,
  EMOTION_GESTURE,
  GESTURE_COOLDOWN_S,
  decideGesture,
  type GestureDecisionInput,
} from "../gestures";

const base = (over: Partial<GestureDecisionInput> = {}): GestureDecisionInput => ({
  emotion: "excited",
  intensity: 0.9,
  blend: [],
  persona: "speaking",
  sleepPhase: "awake",
  nowMs: 100_000,
  lastOneshotAtMs: null,
  ...over,
});

describe("EMOTION_GESTURE table", () => {
  it("covers all 29 emotions", () => {
    for (const name of EMOTION_NAMES) {
      expect(EMOTION_GESTURE[name]).toBeDefined();
    }
    expect(Object.keys(EMOTION_GESTURE)).toHaveLength(EMOTION_NAMES.length);
  });

  it("every non-none mapping names a clip", () => {
    for (const name of EMOTION_NAMES) {
      const m = EMOTION_GESTURE[name];
      if (m.kind !== "none") {
        expect(m.clip, `${name} must name a clip`).toBeTruthy();
      }
    }
  });
});

describe("decideGesture gates (in contract order)", () => {
  it("sleep gate wins over everything", () => {
    const d = decideGesture(base({ sleepPhase: "deep_sleep" }));
    expect(d).toEqual({ action: "none", reason: "asleep" });
  });

  it("inner persona → face only", () => {
    const d = decideGesture(base({ persona: "inner" }));
    expect(d).toEqual({ action: "none", reason: "inner_persona" });
  });

  it("strong ambivalence → stillness", () => {
    const d = decideGesture(
      base({
        blend: [
          { emotion: "excited", weight: 0.5 },
          { emotion: "anxious", weight: 0.5 * AMBIVALENCE_RATIO },
        ],
      })
    );
    expect(d).toEqual({ action: "none", reason: "ambivalent" });
  });

  it("weak secondary emotion does NOT block", () => {
    const d = decideGesture(
      base({
        blend: [
          { emotion: "excited", weight: 0.8 },
          { emotion: "anxious", weight: 0.2 },
        ],
      })
    );
    expect(d.action).toBe("oneshot");
  });

  it("unmapped emotion (neutral) → none", () => {
    const d = decideGesture(base({ emotion: "neutral" }));
    expect(d).toEqual({ action: "none", reason: "unmapped" });
  });

  it("below per-emotion threshold → face only", () => {
    const d = decideGesture(base({ emotion: "happy", intensity: 0.7 })); // happy needs 0.85
    expect(d).toEqual({ action: "none", reason: "below_threshold" });
  });

  it("cooldown blocks a second oneshot within the window", () => {
    const now = 100_000;
    const d = decideGesture(
      base({ nowMs: now, lastOneshotAtMs: now - (GESTURE_COOLDOWN_S * 1000 - 1) })
    );
    expect(d).toEqual({ action: "none", reason: "cooldown" });
    const d2 = decideGesture(
      base({ nowMs: now, lastOneshotAtMs: now - (GESTURE_COOLDOWN_S * 1000 + 1) })
    );
    expect(d2.action).toBe("oneshot");
  });

  it("idleVariant ignores the oneshot cooldown", () => {
    const now = 100_000;
    const d = decideGesture(
      base({
        emotion: "sad",
        intensity: 0.8,
        nowMs: now,
        lastOneshotAtMs: now - 1000,
      })
    );
    expect(d).toEqual({ action: "idleVariant", clip: "idle_sad" });
  });

  it("oneshot happy path returns the mapped clip", () => {
    const d = decideGesture(base({ emotion: "excited", intensity: 0.9 }));
    expect(d).toEqual({ action: "oneshot", clip: "gesture_excited" });
  });
});
