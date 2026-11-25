import { readdirSync, readFileSync } from "node:fs";
import { posix } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

/**
 * Ce que les écrans partagent ne dépend d'aucun écran : `shared/`, `api/`, `live/`, `shell/`, `map/`, `mika/` et
 * `login/` n'importent rien de `screens/` (tests compris). Une aide dont deux écrans ont besoin vit dans `shared/`, pas
 * dans le dossier de l'un d'eux. Les imports sont lus par TypeScript lui-même (`preProcessFile` : `import`,
 * `import type`, `export … from`, `import()`), jamais par un motif : un commentaire ou une chaîne qui nomme
 * `../screens/…` ne compte pas.
 */
const SRC = new URL("../src/", import.meta.url);

/** Les dossiers communs de `src/`, ceux que les écrans se partagent. */
const COMMON = ["shared", "api", "live", "shell", "map", "mika", "login"];

/** Les chemins qu'importe une source, tels qu'écrits. */
function specifiers(text: string): string[] {
  return ts.preProcessFile(text, true, true).importedFiles.map((f) => f.fileName);
}

/** Le module de `src/` que désigne un import relatif d'une source (`shared/kit.ts`, `../screens/chat/markup` →
 *  `screens/chat/markup`) ; rien pour un paquet, l'alias `@web/` ou un module de Node. */
function target(file: string, spec: string): string | null {
  if (!spec.startsWith(".")) return null;
  return posix.normalize(posix.join(posix.dirname(file), spec));
}

/** Les imports de `file` qui mènent dans `screens/`. */
function screensImported(file: string, text: string): string[] {
  return specifiers(text).filter((spec) => {
    const to = target(file, spec);
    return to !== null && (to === "screens" || to.startsWith("screens/"));
  });
}

/** Chaque source des dossiers communs, son chemin depuis `src/`. */
function commonSources(): string[] {
  return readdirSync(SRC, { recursive: true, encoding: "utf8" })
    .map((f) => f.split("\\").join("/"))
    .filter((f) => f.endsWith(".ts") && COMMON.includes(f.split("/")[0]));
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
      import { f } from "@web/ui/approvals";`;
    expect(screensImported("shared/x.ts", text)).toEqual([
      "../screens/chat/markup",
      "../screens/mail/format",
      "../screens/teams/format",
      "../screens/carte/view",
    ]);
    // un chemin relatif se lit depuis le dossier de la source
    expect(screensImported("map/x.ts", 'import { g } from "./screens/y";')).toEqual([]);
    expect(screensImported("shell/deep/x.ts", 'import { g } from "../../screens/y";')).toEqual(["../../screens/y"]);
  });

  it("elle lit bien les dossiers communs (sans eux, la garde passerait sur une liste vide)", () => {
    const sources = commonSources();
    for (const folder of COMMON) expect(sources.some((f) => f.startsWith(`${folder}/`)), folder).toBe(true);
    expect(sources).toContain("shared/kit.ts");
  });

  it("aucun de leurs fichiers n'importe un module de screens/", () => {
    const found = commonSources().flatMap((file) =>
      screensImported(file, readFileSync(new URL(file, SRC), "utf8")).map((spec) => `${file} : ${spec}`),
    );
    expect(found).toEqual([]);
  });
});
