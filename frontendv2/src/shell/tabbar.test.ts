import { describe, expect, it } from "vitest";
import { TABBAR_ORDER } from "./shell";

describe("la barre du bas d'un téléphone", () => {
  it("a sept entrées, la Carte entre Téléphone et Outils, comme la maquette", () => {
    expect(TABBAR_ORDER).toEqual(["chat", "mail", "teams", "telephone", "carte", "outils", "parametres"]);
  });
});
