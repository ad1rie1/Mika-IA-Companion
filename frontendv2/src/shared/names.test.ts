import { describe, expect, it } from "vitest";
import { ofName } from "./names";

describe("« de Léa », « d'Adrien » : un seul `ofName`", () => {
  it("élide devant une voyelle ou un h, accents ignorés", () => {
    expect(ofName("Léa")).toBe("de Léa");
    expect(ofName("Adrien")).toBe("d'Adrien");
    expect(ofName("Adrien Moreau")).toBe("d'Adrien Moreau");
    expect(ofName("Hélène")).toBe("d'Hélène");
    expect(ofName("Élodie")).toBe("d'Élodie");
  });

  it("élide devant les ligatures « œ » et « æ », majuscules comprises", () => {
    expect(ofName("Œdipe")).toBe("d'Œdipe");
    expect(ofName("Æsa")).toBe("d'Æsa");
    expect(ofName("œdipe")).toBe("d'œdipe");
    expect(ofName("æsa")).toBe("d'æsa");
  });

  it("rogne le nom ; un nom vide ne dit rien", () => {
    expect(ofName("  Léa  ")).toBe("de Léa");
    expect(ofName(" Adrien ")).toBe("d'Adrien");
    expect(ofName("")).toBe("");
    expect(ofName("   ")).toBe("");
  });
});
