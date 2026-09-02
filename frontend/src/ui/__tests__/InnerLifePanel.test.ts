import { describe, expect, it } from "vitest";
import { SLEEP_PHASES } from "../../types";
import { resolveSleepPhase } from "../InnerLifePanel";

// Ce module importe InnerLifePanel.ts, qui déclare une classe touchant le
// DOM — mais rien au chargement du module n'appelle `document`, seulement
// les méthodes d'instance (voir le constructeur), donc importer juste
// `resolveSleepPhase` ne construit rien et n'a besoin d'aucun DOM.
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
