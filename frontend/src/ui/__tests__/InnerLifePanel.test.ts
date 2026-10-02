import { describe, expect, it } from "vitest";
import { SLEEP_PHASES, resolveSleepPhase } from "../../types";

describe("resolveSleepPhase", () => {
  it("passes through every known sleep phase", () => {
    for (const phase of SLEEP_PHASES) {
      expect(resolveSleepPhase(phase)).toBe(phase);
    }
  });

  it("falls back to awake on a value the backend never declared", () => {
    // Le crash exact que ce garde-fou évite : un `speech` payload portant
    // une phase inconnue atteignait SLEEP_PHASE_META[resolved].icon sur
    // `undefined` et coupait tout `handleSpeech`, TTS et lip-sync compris.
    expect(resolveSleepPhase("dormant")).toBe("awake");
    expect(resolveSleepPhase(undefined)).toBe("awake");
    expect(resolveSleepPhase(null)).toBe("awake");
    expect(resolveSleepPhase(42)).toBe("awake");
  });
});

describe("DREAM_TYPE_LABEL", () => {
  it("names in French every dream type the server sends", async () => {
    // « melancholic » (contracts/self_.py) s'affichait brut, en gris.
    const { DREAM_TYPE_LABEL } = await import("../InnerLifePanel");
    const { DREAM_TYPES } = await import("../../types");
    for (const kind of DREAM_TYPES) {
      expect(DREAM_TYPE_LABEL[kind]?.label).toMatch(/^(rêve|cauchemar) /);
    }
    expect(Object.keys(DREAM_TYPE_LABEL).sort()).toEqual([...DREAM_TYPES].sort());
  });
});
