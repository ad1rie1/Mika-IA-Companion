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

/**
 * Ambient = the backend's emotion_update, i.e. the mood drifting on its own
 * between two replies. Without this gate a sustained emotion above threshold
 * fires a body clip every cooldown for as long as it lasts, at nothing.
 */
describe("ambient drift", () => {
  it("blocks a oneshot that would otherwise fire", () => {
    const speaking = decideGesture(base({ emotion: "excited", intensity: 0.9 }));
    expect(speaking.action).toBe("oneshot");

    const drifting = decideGesture(
      base({ emotion: "excited", intensity: 0.9, ambient: true })
    );
    expect(drifting).toEqual({ action: "none", reason: "ambient_drift" });
  });

  it("still allows a posture — a mood that settles into sadness slumps", () => {
    const d = decideGesture(
      base({ emotion: "sad", intensity: 0.8, ambient: true })
    );
    expect(d).toEqual({ action: "idleVariant", clip: "idle_sad" });
  });

  it("never overrides the sleep gate", () => {
    const d = decideGesture(
      base({ emotion: "sad", intensity: 0.8, ambient: true, sleepPhase: "rem" })
    );
    expect(d).toEqual({ action: "none", reason: "asleep" });
  });
});

/**
 * La frame `speech` porte désormais l'émotion de la balise [EMOTION:] —
 * la vérité du tour — et non plus la lecture de l'oscillateur d'avant
 * l'impulsion, qui passait structurellement sous tous les seuils. Ces cas
 * pincent que la valeur qui arrive maintenant traverse bien les portes, et
 * que la dérive, elle, ne les traverse toujours pas.
 *
 * Les blends utilisés sont ceux que le backend produit réellement
 * (`EmotionEngine._build_turn_view`) : dominante = la balise, secondaire =
 * ce que la position projetée laisse d'inexpliqué.
 */
describe("frame speech vs dérive (S7)", () => {
  const speech = (over: Partial<GestureDecisionInput> = {}) =>
    base({ persona: "speaking", ...over });
  const drift = (over: Partial<GestureDecisionInput> = {}) =>
    base({ persona: undefined, ambient: true, ...over });

  it("une frame speech portant angry 0.8 déclenche un one-shot", () => {
    const d = decideGesture(
      speech({
        emotion: "angry",
        intensity: 0.8,
        blend: [
          { emotion: "angry", weight: 0.8 },
          { emotion: "determined", weight: 0.46 },
        ],
      })
    );
    expect(d).toEqual({ action: "oneshot", clip: "gesture_angry" });
  });

  it("la même émotion arrivée par dérive n'en déclenche pas", () => {
    const d = decideGesture(
      drift({
        emotion: "angry",
        intensity: 0.8,
        blend: [{ emotion: "angry", weight: 0.8 }],
      })
    );
    expect(d).toEqual({ action: "none", reason: "ambient_drift" });
  });

  it("un blend mono-entrée ne se lit jamais comme de l'ambivalence", () => {
    const d = decideGesture(
      speech({
        emotion: "angry",
        intensity: 0.8,
        blend: [{ emotion: "angry", weight: 0.38 }],
      })
    );
    expect(d).toEqual({ action: "oneshot", clip: "gesture_angry" });
  });

  it("un blend vide non plus", () => {
    const d = decideGesture(
      speech({ emotion: "angry", intensity: 0.8, blend: [] })
    );
    expect(d).toEqual({ action: "oneshot", clip: "gesture_angry" });
  });

  it("l'ancienne lecture pré-impulsion serait restée sous le seuil", () => {
    // Ce que la frame portait avant le correctif backend : la position de
    // l'oscillateur telle quelle, que l'impulsion n'avait pas encore bougée.
    const d = decideGesture(speech({ emotion: "angry", intensity: 0.36 }));
    expect(d).toEqual({ action: "none", reason: "below_threshold" });
  });
});
