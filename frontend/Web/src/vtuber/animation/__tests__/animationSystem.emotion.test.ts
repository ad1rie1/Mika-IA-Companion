import { beforeEach, describe, expect, it } from "vitest";
import type { EmotionBlend, EmotionName, VoicePersona } from "../../../types";
import { AnimationSystem } from "../AnimationSystem";
import type { LoadedClip } from "../ClipLibrary";
import { GESTURE_COOLDOWN_S } from "../gestures";

/**
 * La couture que S7 a cassée : une réponse arrive par la frame `speech` et
 * doit pouvoir déclencher un one-shot, une dérive arrive par `emotion_update`
 * et ne doit jamais en déclencher. Les deux passent par le MÊME
 * `setEmotion` ; la seule différence est l'option `ambient`. Ce fichier pince
 * ce report d'option jusqu'à `decideGesture`, c'est-à-dire le seul endroit du
 * frontend où la régression pourrait revenir.
 */

interface MachineStub {
  idleVariantName: string | null;
  setIdleVariant(name: string | null): void;
  requestGesture(loaded: LoadedClip): boolean;
  setAffect(emotion: EmotionName, intensity: number): void;
}

function harness() {
  const gestures: string[] = [];
  const variants: (string | null)[] = [];
  const machine: MachineStub = {
    idleVariantName: null,
    setIdleVariant(name) {
      machine.idleVariantName = name;
      variants.push(name);
    },
    requestGesture(loaded) {
      gestures.push(loaded.name);
      return true;
    },
    setAffect() {},
  };

  const system = new AnimationSystem();
  (system as unknown as { machine: MachineStub }).machine = machine;
  // Tout clip nommé est réputé chargé : ce test porte sur la décision, pas
  // sur le streaming du manifeste.
  (
    system.library as unknown as { get: (name: string) => LoadedClip }
  ).get = (name) => ({ name } as unknown as LoadedClip);

  return { system, machine, gestures, variants };
}

/** Forme exacte de main.ts::handleSpeech → applyEmotion (4 arguments). */
function speechFrame(
  system: AnimationSystem,
  emotion: EmotionName,
  intensity: number,
  blend: EmotionBlend,
  persona: VoicePersona | undefined = "speaking"
) {
  system.setEmotion(emotion, intensity, blend, persona);
}

/** Forme exacte du handler `emotion_update` : persona absente, ambient posé. */
function driftFrame(
  system: AnimationSystem,
  emotion: EmotionName,
  intensity: number,
  blend: EmotionBlend
) {
  system.setEmotion(emotion, intensity, blend, undefined, { ambient: true });
}

describe("AnimationSystem.setEmotion — frame speech vs dérive", () => {
  let h: ReturnType<typeof harness>;

  beforeEach(() => {
    h = harness();
  });

  it("une frame speech portant angry 0.8 demande le geste", () => {
    speechFrame(h.system, "angry", 0.8, [{ emotion: "angry", weight: 0.72 }]);
    expect(h.gestures).toEqual(["gesture_angry"]);
  });

  it("la même émotion arrivée par dérive n'en demande aucun", () => {
    driftFrame(h.system, "angry", 0.8, [{ emotion: "angry", weight: 0.72 }]);
    expect(h.gestures).toEqual([]);
  });

  it("la dérive change quand même la posture", () => {
    driftFrame(h.system, "sad", 0.8, [{ emotion: "sad", weight: 0.8 }]);
    expect(h.machine.idleVariantName).toBe("idle_sad");
    expect(h.gestures).toEqual([]);
  });

  it("un one-shot joué arme le cooldown des suivants", () => {
    const blend: EmotionBlend = [{ emotion: "angry", weight: 0.72 }];
    speechFrame(h.system, "angry", 0.8, blend);
    speechFrame(h.system, "angry", 0.8, blend);
    expect(h.gestures).toEqual(["gesture_angry"]);
    expect(GESTURE_COOLDOWN_S).toBeGreaterThan(0);
  });

  it("un murmure intérieur reste face seule", () => {
    speechFrame(h.system, "angry", 0.8, [{ emotion: "angry", weight: 0.72 }], "inner");
    expect(h.gestures).toEqual([]);
  });
});
