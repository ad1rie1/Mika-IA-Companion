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

/** Les règles (sélecteur, déclarations) des blocs `@media <query>` d'une feuille. */
function mediaRules(css: string, query: string): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  let at = css.indexOf(`@media ${query}`);
  while (at >= 0) {
    const open = css.indexOf("{", at);
    let depth = 1;
    let i = open + 1;
    for (; i < css.length && depth; i++) depth += css[i] === "{" ? 1 : css[i] === "}" ? -1 : 0;
    for (const [, sel, body] of css.slice(open + 1, i - 1).matchAll(/([^{}]+)\{([^{}]*)\}/g)) out.push([sel.trim(), body]);
    at = css.indexOf(`@media ${query}`, i);
  }
  return out;
}

describe("Carte, sur un téléphone : la fiche du lieu choisi reste à l'écran (F3-17)", () => {
  it("le pied d'Explorer (la fiche, les liens d'un regard) est collé en bas de ce qui défile, par-dessus la liste", () => {
    // `explorerMarkup` (screens/carte/view.ts) pose la fiche en `.pane-foot`, enfant de l'aside `.carte-side`, après la liste
    const rules = mediaRules(sheet("ecrans/carte.css"), "(max-width: 760px)");
    const foot = rules.find(([sel]) => sel.split(",").some((s) => /^\.carte-side\s*>\s*\.pane-foot$/.test(s.trim())));
    expect(foot).toBeDefined();
    const body = foot?.[1] ?? "";
    expect(body).toMatch(/position\s*:\s*sticky/);
    expect(body).toMatch(/bottom\s*:\s*0\b/);
    expect(body).toMatch(/background\s*:/); // la liste passe dessous : elle ne se lit pas à travers
    // ce qui défile, c'est tout l'écran (la carte puis la liste) : la liste elle-même ne défile plus
    expect(rules.some(([sel, b]) => sel === ".carte-split" && /overflow-y\s*:\s*auto/.test(b))).toBe(true);
    expect(rules.some(([sel, b]) => sel === ".carte-side .pane-scroll" && /overflow\s*:\s*visible/.test(b))).toBe(true);
  });
});

/** Toutes les règles (sélecteurs, déclarations) d'une feuille, celles des `@media` comprises. */
function rules(css: string): Array<[string[], string]> {
  return Array.from(css.matchAll(/([^{}]+)\{([^{}]*)\}/g)).map(([, sel, body]): [string[], string] => [sel.split(",").map((s) => s.trim()), body]);
}

describe("Carte : la fenêtre « Le voyage » et les lieux de « Sur la route » (F3-16, F3-13)", () => {
  const carte = sheet("ecrans/carte.css");

  it("une case et son texte se règlent sur tout l'écran et dans ses fenêtres, pas seulement sous Itinéraire", () => {
    // les fenêtres se posent hors de l'écran (#modal-root) : leur formulaire porte `.trip-form` (screens/carte/view.ts)
    const check = rules(carte).filter(([sels]) => sels.some((s) => /\.check$/.test(s)));
    const sels = check.flatMap(([s]) => s);
    expect(sels).toContain('[data-screen="carte"] .check');
    expect(sels).toContain(".trip-form .check");
    const body = check.find(([s]) => s.includes(".trip-form .check"))?.[1] ?? "";
    expect(body).toMatch(/display\s*:\s*flex/);
    expect(body).toMatch(/gap\s*:\s*\d/);
  });

  it("sur un téléphone, « Supprimer le voyage » passe seul sur sa ligne : « Annuler » et « Enregistrer » restent entiers", () => {
    const mobile = mediaRules(carte, "(max-width: 760px)");
    const foot = mobile.find(([sel]) => sel === ".modal-foot:has(> .trip-delete)");
    expect(foot?.[1] ?? "").toMatch(/display\s*:\s*grid/);
    const del = mobile.find(([sel]) => sel === ".modal-foot > .trip-delete");
    expect(del?.[1] ?? "").toMatch(/grid-column\s*:\s*1\s*\/\s*-1/);
  });

  it("une épingle secondaire a son style, sur la vraie carte et sur le plan dessiné", () => {
    const sels = rules(carte).flatMap(([s]) => s);
    expect(sels).toContain(".cm-pin-el.minor");
    expect(sels).toContain(".dm-pin.minor circle");
    expect(sels).toContain(".onroute-list li.flash");
  });
});

describe("Téléphone : le plan de la position est celui de la Carte (F3-08)", () => {
  it("le cercle de sa précision a son style (un cercle SVG sans règle se remplirait de noir)", () => {
    const acc = rules(sheet("ecrans/carte.css")).find(([sels]) => sels.includes(".dm-here-acc"));
    expect(acc?.[1] ?? "").toMatch(/fill\s*:\s*color-mix/);
    expect(acc?.[1] ?? "").toMatch(/stroke\s*:/);
  });

  it("les rues, la rivière et les parcs du plan inventé n'ont plus de règle", () => {
    const tel = sheet("ecrans/telephone.css");
    const sels = rules(tel).flatMap(([s]) => s);
    expect(sels.filter((s) => /\.m-(bg|block|park|water|road|label|acc|dot|pulse)\b/.test(s))).toEqual([]);
    expect(tel).not.toMatch(/@keyframes\s+pulse\b/);
  });
});
