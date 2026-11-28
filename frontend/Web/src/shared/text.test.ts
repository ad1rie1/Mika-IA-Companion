import { describe, expect, it } from "vitest";
import { sizeLabel, thousands } from "./text";

describe("les petites formes d'un texte", () => {
  it("sizeLabel", () => {
    expect(sizeLabel(212 * 1024)).toBe("212 Ko");
    expect(sizeLabel(1.8 * 1024 * 1024)).toBe("1,8 Mo");
    expect(sizeLabel(undefined)).toBe("");
  });

  it("les milliers, séparés d'une espace fine", () => {
    expect(thousands(999)).toBe("999");
    expect(thousands(1234567)).toBe("1\u202f234\u202f567");
  });
});
