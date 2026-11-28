import { describe, expect, it } from "vitest";
import { TABBAR_ORDER, TABBAR_PLUS } from "./shell";

describe("la barre du bas d'un téléphone", () => {
  it("Projets après le chat, l'Agenda après Téléphone, Contacts avant Carte, comme la maquette", () => {
    expect(TABBAR_ORDER).toEqual(["chat", "projets", "mail", "teams", "telephone", "agenda", "contacts", "carte", "outils", "parametres"]);
  });

  it("garde huit entrées : Carte, Outils et Réglages passent sous « Plus » (ADR 0309)", () => {
    expect(TABBAR_PLUS).toEqual(["carte", "outils", "parametres"]);
    expect(TABBAR_ORDER.filter((id) => !TABBAR_PLUS.includes(id)).length + 1).toBe(8);
  });
});
