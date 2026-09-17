import { describe, expect, it } from "vitest";
import { parseBlocks, parseInline } from "../inlineMarkup";

describe("parseInline", () => {
  it("texte sans balise : un seul segment", () => {
    expect(parseInline("salut")).toEqual([{ kind: "text", text: "salut" }]);
  });

  it("découpe le gras", () => {
    expect(parseInline('**Côté "Ça chauffe" :** Macron')).toEqual([
      { kind: "bold", text: 'Côté "Ça chauffe" :' },
      { kind: "text", text: " Macron" },
    ]);
  });

  it("plusieurs passages en gras", () => {
    const segs = parseInline("a **b** c **d**");
    expect(segs.filter((s) => s.kind === "bold").map((s) => s.text)).toEqual(["b", "d"]);
  });

  it("un ** orphelin reste du texte", () => {
    expect(parseInline("2 ** 3")).toEqual([{ kind: "text", text: "2 ** 3" }]);
    expect(parseInline("**pas fermé")).toEqual([{ kind: "text", text: "**pas fermé" }]);
  });

  it("le code en ligne n'interprète pas le gras qu'il contient", () => {
    expect(parseInline("lance `a **b** c`")).toEqual([
      { kind: "text", text: "lance " },
      { kind: "code", text: "a **b** c" },
    ]);
  });

  it("du HTML reste du texte", () => {
    expect(parseInline("**<img src=x>**")).toEqual([{ kind: "bold", text: "<img src=x>" }]);
  });
});

describe("parseBlocks", () => {
  it("extrait un bloc de code avec son langage", () => {
    expect(parseBlocks("Voilà :\n```text\nRÉSUMÉ\n• a\n```\nEt voilà")).toEqual([
      { kind: "text", text: "Voilà :\n" },
      { kind: "code", lang: "text", text: "RÉSUMÉ\n• a" },
      { kind: "text", text: "\nEt voilà" },
    ]);
  });

  it("un bloc non fermé reste du texte", () => {
    expect(parseBlocks("```text\nsans fin")).toEqual([
      { kind: "text", text: "```text\nsans fin" },
    ]);
  });
});
