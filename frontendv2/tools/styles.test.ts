import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/**
 * Les feuilles de style, lues sur le disque : vitest rend vide une feuille importée (même en `?raw`), et ses tests
 * n'appliquent pas les media queries. Ce qui se vérifie ici, ce sont les règles mêmes.
 */
function sheet(name: string): string {
  return readFileSync(new URL(`../src/styles/${name}`, import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
}

/** Les sélecteurs des règles qui cachent un libellé `.lbl` (`display: none`). */
function hiding(css: string): string[] {
  return Array.from(css.matchAll(/([^{}]+)\{([^{}]*)\}/g))
    .filter(([, sel, body]) => /\.lbl\b/.test(sel) && /display\s*:\s*none/.test(body))
    .flatMap(([, sel]) => sel.split(",").map((s) => s.trim()));
}

describe("sur un téléphone, seule la barre de titre réduit ses boutons à leur icône (F4-14)", () => {
  it("la tête d'une section de Paramètres et celle d'une fenêtre gardent leurs libellés", () => {
    const rules = hiding(sheet("base.css")).filter((sel) => /\.ph-actions/.test(sel));
    expect(rules.length).toBeGreaterThan(0);
    // la barre de titre seule : `nameTitleButtons` y pose le nom de chaque bouton réduit (shell/shell.ts)
    for (const sel of rules) expect(sel).toMatch(/^\.page-head \.ph-actions\b/);
  });
});
