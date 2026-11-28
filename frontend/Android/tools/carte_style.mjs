#!/usr/bin/env node
/**
 * Le style de la carte de l'app (ADR 0193, 0194, 0235), tiré du code du web — jamais écrit à la main : les calques de
 * Protomaps (`@protomaps/basemaps`, ses couleurs et ses noms en français), clairs et sombres, sans les points d'intérêt
 * qui n'apprennent rien (`QUIET_POIS`), tels que les compose `frontend/Web/src/map/mapstyle.ts`. Ce script importe ce
 * fichier même (Node 24 lit le TypeScript : ses types s'effacent) et `@protomaps/basemaps` depuis
 * `frontend/Web/node_modules`, et écrit les calques dans les assets de l'app :
 *
 *     node frontend/Android/tools/carte_style.mjs           # écrit les styles et leurs références
 *     node frontend/Android/tools/carte_style.mjs --check   # échoue si l'un d'eux a vieilli
 *
 * L'app y pose, au moment de charger, ce qui vient du serveur (`data/moi/carte/CarteStyle.kt`) : les adresses des
 * tuiles, des polices et des icônes, ses zooms, sa zone, sa mention — et retire les noms sans polices, les icônes sans
 * planche, comme le web. Une carte `image` n'a pas besoin de ces calques (un style raster).
 *
 * Cette moitié-là est réécrite à la main en Kotlin : le script écrit aussi le style **complet** que le web compose pour
 * quelques cartes servies types (`REFERENCES` : avec tout, sans polices, sans planche, sans les deux, en images ; sous
 * un préfixe), dans `app/src/test/resources/carte/styles-web.json`, et `CarteStyleTest` vérifie que l'app compose le
 * même pour les mêmes entrées (la source, `sprite` et `glyphs`, le style raster, la règle qui retire texte et icônes,
 * toute clé racine).
 *
 * Après `npm install` dans `frontend/Web/` (une autre version de `@protomaps/basemaps`) ou une retouche de `mapstyle.ts`,
 * relancer le script : `--check` le dit. Puis les tests JVM : ce que le web a changé, l'app le suit-elle ?
 */
import { readFile, writeFile, mkdir, readdir, unlink } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const WEB_STYLE = join(ROOT, "frontend", "Web", "src", "map", "mapstyle.ts");
const BASEMAPS = join(ROOT, "frontend", "Web", "node_modules", "@protomaps", "basemaps", "package.json");
const OUT = join(HERE, "..", "app", "src", "main", "assets", "carte");
const TEST_OUT = join(HERE, "..", "app", "src", "test", "resources", "carte");
const REFERENCES_FILE = "styles-web.json";

/** Les deux planches de Protomaps, et le nom de leur fichier dans l'app. */
const FLAVORS = [
  { dark: false, flavor: "light", file: "style-clair.json" },
  { dark: true, flavor: "dark", file: "style-sombre.json" },
];

/**
 * Une carte servie qui a tout (des polices, des icônes) : le web garde alors chaque calque tel quel ; l'app retire
 * ce qui manque à la carte du moment. Les adresses ne servent pas ici : l'app pose celles du serveur.
 */
const FULL = {
  ready: true,
  reason: "",
  kind: "vecteur",
  minzoom: 0,
  maxzoom: 15,
  bounds: null,
  attribution: "",
  tiles: "/tiles",
  glyphs: "/glyphs",
  sprite: "/sprite",
};

/** Un fichier par planche : l'en-tête, puis un calque par ligne (une retouche se lit dans un diff). */
function render(header, layers) {
  const head = JSON.stringify(header).slice(0, -1);
  return `${head},"layers":[\n${layers.map((l) => JSON.stringify(l)).join(",\n")}\n]}\n`;
}

/** Une carte servie comme `GET /api/moi/carte/fond` la rend (les chemins de l'API, sa version). */
const SERVED = {
  ready: true,
  reason: "",
  kind: "vecteur",
  minzoom: 0,
  maxzoom: 15,
  bounds: [-5.2, 41.3, 9.6, 51.1],
  attribution: "© OpenStreetMap",
  tiles: "/api/moi/carte/fond/tiles/{z}/{x}/{y}?v=1a2b3c4d5e6f",
  glyphs: "/api/moi/carte/fond/fonts/{fontstack}/{range}.pbf?v=1a2b3c4d5e6f",
  sprite: "/api/moi/carte/fond/sprites/~1a2b3c4d5e6f/v4",
};

/**
 * Les cartes servies types dont le style complet du web sert de référence à l'app : les mêmes entrées (`info`, le thème,
 * l'adresse du serveur), le même style attendu.
 */
const REFERENCES = [
  { name: "vecteur, clair, avec tout", dark: false, base: "http://192.168.1.22:8001", info: SERVED },
  {
    name: "vecteur, sombre, sans polices, sous un préfixe, partout",
    dark: true,
    base: "https://mika.example.ts.net/mika",
    info: { ...SERVED, glyphs: null, bounds: null, minzoom: 2, maxzoom: 14 },
  },
  { name: "vecteur, clair, sans planche", dark: false, base: "http://192.168.1.22:8001", info: { ...SERVED, sprite: null } },
  {
    name: "vecteur, sombre, ni polices ni planche, sans mention",
    dark: true,
    base: "http://192.168.1.22:8001",
    info: { ...SERVED, glyphs: null, sprite: null, attribution: "" },
  },
  {
    name: "en images",
    dark: false,
    base: "http://192.168.1.22:8001",
    info: { ...SERVED, kind: "image", tiles: "/api/moi/carte/fond/tiles/{z}/{x}/{y}.png?v=9f8e7d", glyphs: null, sprite: null, maxzoom: 18 },
  },
];

/** Les références : l'en-tête, puis chaque cas — ses entrées, le style hors calques, un calque par ligne. */
function renderReferences(header, cases) {
  const parts = cases.map(({ name, dark, base, info, style }) => {
    const { layers, ...rest } = style;
    const head = JSON.stringify({ name, dark, base, info, style: rest });
    return `${head.slice(0, -2)},"layers":[\n${layers.map((l) => JSON.stringify(l)).join(",\n")}\n]}}`;
  });
  return `${JSON.stringify(header).slice(0, -1)},"cases":[\n${parts.join(",\n")}\n]}\n`;
}

async function expected() {
  const { mapStyle, SOURCE } = await import(pathToFileURL(WEB_STYLE).href);
  const version = JSON.parse(await readFile(BASEMAPS, "utf8")).version;
  const out = new Map();
  for (const { dark, flavor, file } of FLAVORS) {
    const style = mapStyle(FULL, dark, "");
    const header = {
      genere_par: "frontend/Android/tools/carte_style.mjs, depuis frontend/Web/src/map/mapstyle.ts",
      basemaps: version,
      source: SOURCE,
      flavor,
    };
    out.set(file, render(header, style.layers));
  }
  const cases = REFERENCES.map((c) => ({ ...c, style: mapStyle(c.info, c.dark, c.base) }));
  const header = {
    genere_par: "frontend/Android/tools/carte_style.mjs, depuis frontend/Web/src/map/mapstyle.ts",
    basemaps: version,
  };
  out.set(REFERENCES_FILE, renderReferences(header, cases));
  return out;
}

/** Où va un fichier : les styles dans les assets, les références dans les ressources des tests. */
function placeOf(name) {
  return join(name === REFERENCES_FILE ? TEST_OUT : OUT, name);
}

async function main(argv) {
  const check = argv.includes("--check");
  const wanted = await expected();
  let present = [];
  try {
    present = (await readdir(OUT)).filter((n) => n.startsWith("style-") && n.endsWith(".json"));
  } catch {
    present = [];
  }
  const stale = [];
  for (const [name, text] of wanted) {
    let now = null;
    try {
      now = await readFile(placeOf(name), "utf8");
    } catch {
      now = null;
    }
    if (now !== text) stale.push(name);
  }
  const orphans = present.filter((n) => !wanted.has(n));
  if (check) {
    if (stale.length || orphans.length) {
      console.error(`Styles de la carte (ou leurs références) à régénérer : ${[...stale, ...orphans].join(", ")}`);
      return 1;
    }
    console.log(`${wanted.size - 1} styles de la carte et leurs références à jour.`);
    return 0;
  }
  await mkdir(OUT, { recursive: true });
  await mkdir(TEST_OUT, { recursive: true });
  for (const name of stale) await writeFile(placeOf(name), wanted.get(name), "utf8");
  for (const name of orphans) await unlink(join(OUT, name));
  console.log(`${wanted.size - 1} styles de la carte et leurs références (${stale.length} écrits, ${orphans.length} retirés).`);
  return 0;
}

process.exitCode = await main(process.argv.slice(2));
