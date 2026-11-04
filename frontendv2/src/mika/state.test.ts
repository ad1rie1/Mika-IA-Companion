import { describe, expect, it } from "vitest";
import { EMPTY_MIKA, isAsleep, withInnerState, withMood, type MikaState } from "./state";

const full = {
  sleep_phase: "awake",
  energy: 0.68,
  place: "desk",
  activity: { name: "work", label: "travailler", since: 1, until: null },
  circadian: { phase: "afternoon", hour: 14, energy: 0.68, bias_emotion: "curious" },
  drives: { social: { tension: 0.7, last_satisfied: 0 }, curiosity: { tension: 0.2, last_satisfied: 0 } },
  estime: 0.6,
  ruminations: [
    { summary: "aux corneilles", intensity: 0.4, emotion: "curious" },
    { summary: "à la présentation", intensity: 0.8, emotion: "anxious" },
  ],
  pending_commitments: ["Relire ta présentation", "  ", 3],
  today_journal: { date: "2026-11-03", title: "Son journal d'hier", narrative: "Journée calme." },
  last_dream: { content: "une maison de livres", dream_type: "pleasant", vividness: 0.6, emotion: "happy", night_of: "x", recalled: true },
  projects: [{ title: "Labo de trading", status: "en pause" }],
  person_scope: true,
};

describe("withInnerState", () => {
  it("lit chaque clé, validée", () => {
    const s = withInnerState(EMPTY_MIKA, full);
    expect(s.sleepPhase).toBe("awake");
    expect(s.energy).toBe(0.68);
    expect(s.place).toBe("desk");
    expect(s.activity).toEqual({ name: "work", label: "travailler", until: null });
    expect(s.circadian).toEqual({ phase: "afternoon", hour: 14 });
    expect(s.drives).toEqual({ social: 0.7, curiosity: 0.2 });
    // les plus fortes d'abord
    expect(s.ruminations.map((r) => r.summary)).toEqual(["à la présentation", "aux corneilles"]);
    expect(s.commitments).toEqual(["Relire ta présentation"]);
    expect(s.journal).toEqual({ title: "Son journal d'hier", narrative: "Journée calme." });
    expect(s.dream).toEqual({ content: "une maison de livres", kind: "pleasant", vividness: 0.6, recalled: true });
    expect(s.projects).toEqual([{ title: "Labo de trading", status: "en pause" }]);
  });

  it("une trame qui ne parle de personne garde les sections personnelles", () => {
    const before = withInnerState(EMPTY_MIKA, full);
    const after = withInnerState(before, { sleep_phase: "rem", ruminations: [], person_scope: false });
    expect(after.sleepPhase).toBe("rem");
    expect(after.ruminations).toEqual(before.ruminations);
    expect(after.commitments).toEqual(before.commitments);
    expect(after.journal).toEqual(before.journal);
  });

  it("une section absente s'efface, une section illisible garde sa valeur", () => {
    const before = withInnerState(EMPTY_MIKA, full);
    const after = withInnerState(before, { ruminations: "pas une liste", person_scope: true });
    expect(after.ruminations).toEqual(before.ruminations);
    expect(after.commitments).toEqual([]);
    expect(after.journal).toBeNull();
    expect(after.dream).toBeNull();
    expect(after.projects).toEqual([]);
  });

  it("l'occupation : un null dit qu'elle ne fait plus rien, une trame sans la clé n'y touche pas", () => {
    const before = withInnerState(EMPTY_MIKA, full);
    expect(withInnerState(before, { energy: 0.5 }).activity).toEqual(before.activity);
    expect(withInnerState(before, { activity: null }).activity).toBeNull();
    expect(withInnerState(before, { activity: 42 }).activity).toEqual(before.activity);
  });

  it("une phase de sommeil inconnue se lit éveillée, une énergie illisible ne change rien", () => {
    const s = withInnerState(EMPTY_MIKA, { sleep_phase: "coma", energy: "beaucoup" });
    expect(s.sleepPhase).toBe("awake");
    expect(s.energy).toBeNull();
    expect(isAsleep(withInnerState(EMPTY_MIKA, { sleep_phase: "deep_sleep" }))).toBe(true);
  });

  it("ignore ce qui n'est pas un objet", () => {
    expect(withInnerState(EMPTY_MIKA, null)).toBe(EMPTY_MIKA);
    expect(withInnerState(EMPTY_MIKA, [1, 2])).toBe(EMPTY_MIKA);
  });
});

describe("withMood", () => {
  it("lit l'émotion, sa force et le mélange valide", () => {
    const s = withMood(EMPTY_MIKA, {
      emotion: "Curious",
      emotion_intensity: 0.62,
      emotion_blend: [
        { emotion: "curious", weight: 0.62 },
        { emotion: "inventée", weight: 0.9 },
        { emotion: "happy", weight: 1.7 },
        { emotion: "sad", weight: "fort" },
      ],
    });
    expect(s.mood).toEqual({
      emotion: "curious",
      intensity: 0.62,
      blend: [
        { emotion: "curious", weight: 0.62 },
        { emotion: "happy", weight: 1 },
      ],
    });
  });

  it("une émotion inconnue ou un texte de repli ne changent rien", () => {
    const before: MikaState = withMood(EMPTY_MIKA, { emotion: "happy", emotion_intensity: 0.5 });
    expect(withMood(before, { emotion: "joie" })).toBe(before);
    expect(withMood(before, { emotion: "neutral", emotion_intensity: 0, source: "error" })).toBe(before);
  });
});
