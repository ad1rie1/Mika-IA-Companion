import { describe, expect, it } from "vitest";
import { TABBAR_ORDER } from "./shell";

describe("la barre du bas d'un téléphone", () => {
  it("a neuf entrées, Projets après le chat, Contacts entre Téléphone et Carte, comme la maquette", () => {
    expect(TABBAR_ORDER).toEqual(["chat", "projets", "mail", "teams", "telephone", "contacts", "carte", "outils", "parametres"]);
  });
});
