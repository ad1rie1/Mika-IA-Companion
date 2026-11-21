import { describe, expect, it } from "vitest";
import { TABBAR_ORDER } from "./shell";

describe("la barre du bas d'un téléphone", () => {
  it("a huit entrées, Projets après le chat et la Carte entre Téléphone et Outils, comme la maquette", () => {
    expect(TABBAR_ORDER).toEqual(["chat", "projets", "mail", "teams", "telephone", "carte", "outils", "parametres"]);
  });
});
