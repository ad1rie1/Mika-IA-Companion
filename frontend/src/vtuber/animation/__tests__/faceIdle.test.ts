import { describe, expect, it } from "vitest";
import { EMOTION_NAMES } from "../../../types";
import { EMOTION_ACCENT, MICRO_CHANNELS } from "../FaceIdleController";

/**
 * The face layers compose ADDITIVELY on shared morph targets (VRM binds
 * use `+=`), so the guard that matters is that micro-drift + accent can
 * never sum into an over-deformed face.
 */
describe("FaceIdleController tables", () => {
  it("micro channels stay subtle (bias + amp * talkBoost <= 0.2)", () => {
    for (const c of MICRO_CHANNELS) {
      const peak = c.bias + c.amp * (c.talkBoost ?? 1);
      expect(peak, `${c.name} peaks at ${peak}`).toBeLessThanOrEqual(0.2);
      expect(c.amp).toBeGreaterThan(0);
      expect(c.rate).toBeGreaterThan(0);
    }
  });

  it("left/right pairs use different noise rates (no symmetric face)", () => {
    const byBase = new Map<string, number[]>();
    for (const c of MICRO_CHANNELS) {
      const base = c.name.replace(/(Left|Right)$/, "");
      if (base === c.name) continue;
      byBase.set(base, [...(byBase.get(base) ?? []), c.rate]);
    }
    expect(byBase.size).toBeGreaterThan(0);
    for (const [base, rates] of byBase) {
      expect(new Set(rates).size, `${base} L/R share a rate`).toBe(rates.length);
    }
  });

  it("accents only reference known emotions and stay <= 0.45", () => {
    const valid = new Set<string>(EMOTION_NAMES);
    for (const [emotion, shapes] of Object.entries(EMOTION_ACCENT)) {
      expect(valid.has(emotion), `unknown emotion "${emotion}"`).toBe(true);
      for (const [shape, weight] of Object.entries(shapes)) {
        expect(weight, `${emotion}.${shape}`).toBeGreaterThan(0);
        expect(weight, `${emotion}.${shape}`).toBeLessThanOrEqual(0.45);
      }
    }
  });

  it("combined micro peak + accent peak cannot exceed 1.0 on any shape", () => {
    const microPeak = new Map<string, number>();
    for (const c of MICRO_CHANNELS) {
      microPeak.set(c.name, c.bias + c.amp * (c.talkBoost ?? 1));
    }
    for (const [emotion, shapes] of Object.entries(EMOTION_ACCENT)) {
      for (const [shape, weight] of Object.entries(shapes)) {
        const total = weight + (microPeak.get(shape) ?? 0);
        expect(total, `${emotion}.${shape} sums to ${total}`).toBeLessThanOrEqual(1);
      }
    }
  });

  it("covers a broad emotional range (most emotions get facial shading)", () => {
    const covered = Object.keys(EMOTION_ACCENT).length;
    expect(covered).toBeGreaterThanOrEqual(EMOTION_NAMES.length - 3);
  });
});
