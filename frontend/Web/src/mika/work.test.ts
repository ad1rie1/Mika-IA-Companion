import { describe, expect, it } from "vitest";
import { elapsed, workLine, workText, type Work } from "./work";

const AT = 1_790_000_000_000;

describe("où elle en est (ADR 0306)", () => {
  it("l'étape en mots : elle s'y met, elle réfléchit, tel outil tourne", () => {
    const w = (step: Work["step"], label = ""): Work => ({ step, label, since: AT, started: AT });
    expect(workText(w("waiting"))).toBe("Elle s'y met…");
    expect(workText(w("thinking"))).toBe("Réflexion en cours…");
    expect(workText(w("tool", "Relire une de tes conversations Teams"))).toBe("Relire une de tes conversations Teams…");
    expect(workText(w("tool", "Chercher…"))).toBe("Chercher…"); // jamais deux points de suspension
    expect(workText(w("tool"))).toBe("Un de ses outils…");
  });
  it("un chrono qui court : secondes, minutes, heures — jamais négatif", () => {
    expect(elapsed(7_400)).toBe("0:07");
    expect(elapsed(90_000)).toBe("1:30");
    expect(elapsed(3_725_000)).toBe("1:02:05");
    expect(elapsed(-2_000)).toBe("0:00");
  });
  it("une ligne : l'étape, échappée, et le chrono depuis le début de l'étape, que le minuteur fait courir", () => {
    const html = workLine({ step: "tool", label: "Lire <b>", since: AT, started: AT - 60_000 }, AT + 32_000, "tm-asked");
    expect(html).toContain("Lire &lt;b&gt;…");
    expect(html).toContain(`data-work-since="${AT}"`);
    expect(html).toContain(">0:32<");
    expect(html).toContain('aria-hidden="true"'); // le chrono n'est pas lu à chaque seconde
  });
});
