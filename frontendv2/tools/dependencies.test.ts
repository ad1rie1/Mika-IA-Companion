import { readdirSync, readFileSync } from "node:fs";
import ts from "typescript";
import { describe, expect, it } from "vitest";

/**
 * Chaque paquet qu'importe `src/` est déclaré dans package.json. Le `tsc` de `npm run build` compile tout `src/`, ses
 * tests compris (tsconfig.json, `include: ["src"]`) : un paquet qui ne s'y trouve que parce que npm l'a hissé depuis
 * une dépendance (`@maplibre/maplibre-gl-style-spec`, celle de maplibre-gl) casserait la compilation de production le
 * jour où npm le rangerait sous cette dépendance. Les imports sont lus par TypeScript lui-même (`preProcessFile` :
 * `import`, `import type`, `export … from`, `import()`), jamais par un motif : un commentaire qui nomme un paquet ne
 * compte pas. Les modules du client web (`@web/…`) ont leur propre package.json.
 */
const SRC = new URL("../src/", import.meta.url);

/** Le paquet d'un chemin d'import (`three/addons/…` → `three`, `@a/b/c` → `@a/b`) ; rien pour un chemin relatif,
 * l'alias `@web/` ou un module de Node. */
function packageOf(spec: string): string | null {
  if (spec.startsWith(".") || spec.startsWith("/") || spec.startsWith("@web/") || spec.startsWith("node:")) return null;
  const parts = spec.split("/");
  return spec.startsWith("@") ? parts.slice(0, 2).join("/") : parts[0];
}

/** Ce que déclare package.json : un paquet, ou ses seuls types (`@types/geojson` pour `geojson`). */
function declares(declared: Set<string>, name: string): boolean {
  const types = name.startsWith("@") ? `@types/${name.slice(1).replace("/", "__")}` : `@types/${name}`;
  return declared.has(name) || declared.has(types);
}

/** Chaque import nu de `src/`, avec le fichier qui le fait. */
function imports(): Array<{ file: string; name: string }> {
  const found: Array<{ file: string; name: string }> = [];
  for (const file of readdirSync(SRC, { recursive: true, encoding: "utf8" })) {
    if (!file.endsWith(".ts")) continue;
    const text = readFileSync(new URL(file, SRC), "utf8");
    for (const { fileName } of ts.preProcessFile(text, true, true).importedFiles) {
      const name = packageOf(fileName);
      if (name) found.push({ file, name });
    }
  }
  return found;
}

describe("les paquets que le client importe sont ceux qu'il déclare", () => {
  it("aucun import de src/ ne repose sur un paquet hissé par une dépendance", () => {
    const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
    };
    const declared = new Set([...Object.keys(pkg.dependencies ?? {}), ...Object.keys(pkg.devDependencies ?? {})]);
    const found = imports();
    // la lecture voit bien les imports (valeur, type, sous-chemin) : sans eux, le test passerait sur une liste vide
    const names = new Set(found.map((i) => i.name));
    for (const known of ["maplibre-gl", "@maplibre/maplibre-gl-style-spec", "three", "vitest", "geojson"]) {
      expect(names.has(known), known).toBe(true);
    }
    const missing = found.filter((i) => !declares(declared, i.name)).map((i) => `${i.file} : ${i.name}`);
    expect(missing).toEqual([]);
  });
});
