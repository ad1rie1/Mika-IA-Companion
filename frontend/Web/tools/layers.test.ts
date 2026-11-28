import { readdirSync, readFileSync } from "node:fs";
import { posix } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

/**
 * Deux règles de couches, tests compris :
 * - ce que les écrans partagent ne dépend d'aucun écran : `shared/`, `api/`, `live/`, `shell/`, `map/`, `mika/`,
 *   `login/`, `network/`, `types/` et `ui/` n'importent rien de `screens/`. Une aide dont deux écrans ont besoin vit
 *   dans `shared/`, pas dans le dossier de l'un d'eux ;
 * - Paramètres est un cadre qui montre les pages de réglages des écrans de domaine (`screens/parametres/index.ts` les
 *   importe) : aucun fichier de `screens/<x>/`, pour `x` autre que `parametres`, n'importe rien de
 *   `screens/parametres/`. Ce qu'un écran de domaine y prendrait vit dans `shared/`.
 *
 * Les imports sont lus par TypeScript lui-même (`preProcessFile` : `import`, `import type`, `export … from`,
 * `import()`), jamais par un motif : un commentaire ou une chaîne qui nomme `../screens/…` ne compte pas.
 */
const SRC = new URL("../src/", import.meta.url);

/** Les dossiers communs de `src/`, ceux que les écrans se partagent. */
const COMMON = ["shared", "api", "live", "shell", "map", "mika", "login", "network", "types", "ui"];

/** Le cadre de Paramètres, qu'aucun écran de domaine n'importe. */
const PARAMETRES = "screens/parametres";

/** Les chemins qu'importe une source, tels qu'écrits. */
function specifiers(text: string): string[] {
  return ts.preProcessFile(text, true, true).importedFiles.map((f) => f.fileName);
}

/** Le module de `src/` que désigne un import relatif d'une source (`shared/kit.ts`, `../screens/chat/markup` →
 *  `screens/chat/markup`) ; rien pour un paquet ou un module de Node. */
function target(file: string, spec: string): string | null {
  if (!spec.startsWith(".")) return null;
  return posix.normalize(posix.join(posix.dirname(file), spec));
}

/** Les imports de `file` qui mènent dans le dossier `folder` de `src/` (`screens`, `screens/parametres`), ou sur lui. */
function importsInto(file: string, text: string, folder: string): string[] {
  return specifiers(text).filter((spec) => {
    const to = target(file, spec);
    return to !== null && (to === folder || to.startsWith(`${folder}/`));
  });
}

/** Chaque source de `src/`, son chemin depuis `src/`. */
function sources(): string[] {
  return readdirSync(SRC, { recursive: true, encoding: "utf8" })
    .map((f) => f.split("\\").join("/"))
    .filter((f) => f.endsWith(".ts"));
}

/** Chaque source des dossiers communs. */
function commonSources(): string[] {
  return sources().filter((f) => COMMON.includes(f.split("/")[0]));
}

/** Chaque source d'un écran de domaine : `screens/<x>/…`, `x` autre que `parametres`. */
function domainSources(): string[] {
  return sources().filter((f) => {
    const [top, screen, ...rest] = f.split("/");
    return top === "screens" && rest.length > 0 && screen !== "parametres";
  });
}

/** Ce que la garde trouve : `fichier : import`, pour chaque import de ces sources qui mène dans `folder`. */
function found(files: readonly string[], folder: string): string[] {
  return files.flatMap((file) =>
    importsInto(file, readFileSync(new URL(file, SRC), "utf8"), folder).map((spec) => `${file} : ${spec}`),
  );
}

describe("ce qui est commun n'importe aucun écran", () => {
  it("la lecture voit les imports, et seulement eux", () => {
    const text = `
      // import { clock } from "../screens/chat/markup"; dans un commentaire ne compte pas
      /* export { x } from "../screens/mail/format"; non plus */
      import { a } from "../screens/chat/markup";
      import type { B } from "../screens/mail/format";
      export { c } from "../screens/teams/format";
      const lazy = () => import("../screens/carte/view");
      const said = "../screens/agenda/model";
      import { d } from "./dates";
      import { e } from "../api/mail";
      import { f } from "../ui/approvals";`;
    expect(importsInto("shared/x.ts", text, "screens")).toEqual([
      "../screens/chat/markup",
      "../screens/mail/format",
      "../screens/teams/format",
      "../screens/carte/view",
    ]);
    // un chemin relatif se lit depuis le dossier de la source
    expect(importsInto("map/x.ts", 'import { g } from "./screens/y";', "screens")).toEqual([]);
    expect(importsInto("shell/deep/x.ts", 'import { g } from "../../screens/y";', "screens")).toEqual(["../../screens/y"]);
  });

  it("elle lit bien les dossiers communs (sans eux, la garde passerait sur une liste vide)", () => {
    const common = commonSources();
    for (const folder of COMMON) expect(common.some((f) => f.startsWith(`${folder}/`)), folder).toBe(true);
    expect(common).toContain("shared/kit.ts");
  });

  it("aucun de leurs fichiers n'importe un module de screens/", () => {
    expect(found(commonSources(), "screens")).toEqual([]);
  });
});

describe("aucun écran de domaine n'importe Paramètres", () => {
  it("la lecture voit les imports qui mènent dans screens/parametres/, et seulement eux", () => {
    const text = `
      // import { openOf } from "../parametres/shares"; dans un commentaire ne compte pas
      import { a } from "../parametres/shares";
      import type { B } from "../parametres";
      export { c } from "../../screens/parametres/index";
      const lazy = () => import("../parametres/account");
      const said = "../parametres/shares";
      import { d } from "../teams/settings";
      import { e } from "../../shared/settings";
      import { f } from "./parametres";
      import { g } from "../parametres-bis/x";`;
    expect(importsInto("screens/outils/x.ts", text, PARAMETRES)).toEqual([
      "../parametres/shares",
      "../parametres",
      "../../screens/parametres/index",
      "../parametres/account",
    ]);
    // un chemin relatif se lit depuis le dossier de la source : plus bas dans l'écran, un cran de plus
    expect(importsInto("screens/projets/views/x.ts", 'import { h } from "../../parametres/shares";', PARAMETRES)).toEqual([
      "../../parametres/shares",
    ]);
    expect(importsInto("screens/projets/views/x.ts", 'import { h } from "../parametres/shares";', PARAMETRES)).toEqual([]);
  });

  it("elle lit les écrans de domaine, tests compris, et pas Paramètres", () => {
    const domain = domainSources();
    for (const screen of ["chat", "mail", "teams", "outils", "agenda"]) {
      expect(domain.some((f) => f.startsWith(`screens/${screen}/`)), screen).toBe(true);
    }
    expect(domain).toContain("screens/outils/settings.test.ts");
    expect(domain).toContain("screens/projets/views/sheet.ts");
    expect(domain.filter((f) => f.startsWith(`${PARAMETRES}/`))).toEqual([]);
  });

  it("aucun de leurs fichiers n'importe un module de screens/parametres/", () => {
    expect(found(domainSources(), PARAMETRES)).toEqual([]);
  });
});
