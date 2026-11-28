import { describe, expect, it } from "vitest";
import { phonesPage, phonesView, pushWords } from "./settings";

const NOW = new Date(2026, 10, 4, 15, 0).getTime();

describe("Téléphones et Compte : un bouton par geste, des mots sans code (F4-15, F4-08)", () => {
  it("« Télécharger l'APK » une seule fois, sur la carte ; ni ADR, ni « notifié fermé »", () => {
    const html = phonesView(true, [{ id: 1, label: "Pixel", push: true, revoked: false, created_at: 0, last_used: 0 }] as never, NOW);
    expect(html.split("Télécharger l'APK").length - 1).toBe(1);
    expect(phonesPage.actions).toBeUndefined();
    expect(html).not.toMatch(/ADR|notifié fermé/);
    expect(pushWords(true)).toBe("même application fermée");
    expect(pushWords(false)).toBe("sans notifications");
  });
});
