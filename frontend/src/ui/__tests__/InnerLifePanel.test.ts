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

describe("le panneau parle français (ADR 0056)", () => {
  it("names her needs with the console's words, the three the server sends", async () => {
    // « Pulsions : Lien social, Expression, Curiosité » contre « Besoins :
    // compagnie, s'exprimer, apprendre » dans la console. Un test côté serveur
    // confronte cette table à `faculties/needs/inspect.py`.
    const { DRIVE_LABELS } = await import("../InnerLifePanel");
    expect(Object.fromEntries(Object.entries(DRIVE_LABELS).map(([k, v]) => [k, v.label]))).toEqual({
      social: "Compagnie",
      expression: "S'exprimer",
      curiosity: "Apprendre",
    });
  });

  it("says the transport's trust in French", async () => {
    // « (100 % — authenticated) »
    const { TRUST_LABEL } = await import("../InnerLifePanel");
    for (const trust of ["authenticated", "account", "public", "internal"]) {
      expect(TRUST_LABEL[trust]).toBeTruthy();
      expect(TRUST_LABEL[trust]).not.toBe(trust);
    }
  });

  it("quotes a claim's evidence only when there is one", async () => {
    // v2 n'envoie pas la phrase : « — «  » » s'affichait vide.
    const { claimLine } = await import("../InnerLifePanel");
    expect(claimLine({ name: "Thomas", evidence: "" })).not.toContain("«");
    expect(claimLine({ name: "Thomas", evidence: "moi c'est Thomas" })).toContain("« moi c&#39;est Thomas »");
    expect(claimLine({ name: "<b>x</b>" })).not.toContain("<b>"); // échappé
  });

  it("titles the journal by the day it covers, never as today's", async () => {
    // Le journal montré est celui de la veille (il s'écrit la nuit) ; le
    // panneau l'intitulait « Journal d'aujourd'hui ».
    const { journalTitle } = await import("../InnerLifePanel");
    expect(journalTitle({ title: "Son journal d'hier" })).toBe("Son journal d'hier");
    expect(journalTitle({})).not.toMatch(/aujourd/);
    expect(journalTitle(undefined)).not.toMatch(/aujourd/);
  });
});

describe("le premier compte", () => {
  it("falls back to login on the status, whatever the wording", async () => {
    // Le serveur disait « existe deja » (sans accent) et le client cherchait
    // cette phrase exacte : corriger l'accent aurait cassé le repli.
    const { bootstrapClosed } = await import("../LoginOverlay");
    const { LoginRefusedError } = await import("../../network/api");
    expect(bootstrapClosed(new LoginRefusedError(409, "Un compte existe déjà : connecte-toi."))).toBe(true);
    expect(bootstrapClosed(new LoginRefusedError(409, "n'importe quoi"))).toBe(true);
    expect(bootstrapClosed(new Error("Un compte existe deja : connecte-toi."))).toBe(true);
    // contre-exemple : un mot de passe trop faible n'est pas « un compte existe »
    expect(bootstrapClosed(new LoginRefusedError(400, "Le mot de passe est trop court."))).toBe(false);
  });
});
