/**
 * Le style d'une carte (ADR 0193, 0194), sans MapLibre : les tuiles, les polices et les icônes de ce serveur seulement,
 * claires ou sombres (les couleurs de Protomaps, ses noms en français), sans les points d'intérêt qui n'apprennent rien
 * (`QUIET_POIS`).
 */
import { layers, namedFlavor } from "@protomaps/basemaps";
import type { ExpressionSpecification, FilterSpecification, LayerSpecification, StyleSpecification } from "maplibre-gl";
import type { MapInfo } from "../api/carte";

export const SOURCE = "carte";

/** Le calque des points d'intérêt de Protomaps : le seul que le style filtre. */
export const POIS_LAYER = "pois";

/**
 * Les noms qui ne disent que la sorte d'un bâtiment, en minuscules. Le fond de Protomaps range des bâtiments ainsi
 * nommés dans la sorte `attraction` (son étoile rose, dès le zoom 16) : sur les tuiles servies, plus d'une centaine
 * d'étoiles « Immeubles », « Maison », « Immeuble », « Maisons », « Hôtel particulier » dans le seul centre de Lille, qui
 * couvraient le plan au zoom d'une rue. La liste reste courte : un nom propre (« Maison Meert », « Hôtel de
 * Lamissart ») n'y est jamais.
 */
export const GENERIC_POI_NAMES: readonly string[] = [
  "immeuble",
  "immeubles",
  "maison",
  "maisons",
  "hôtel particulier",
  "hôtels particuliers",
  "ancien hôtel",
];

/** Le nom qu'un point montre, en minuscules ; "" s'il n'en a pas. */
const POI_NAME: ExpressionSpecification = ["downcase", ["to-string", ["coalesce", ["get", "name:fr"], ["get", "name"], ""]]];

/**
 * Les points qui encombrent sans rien apprendre : une `attraction` sans nom (une étoile seule) ou d'un nom générique.
 * Seule cette sorte : un restaurant qui s'appelle « Maison » garde son nom. Relever le zoom de toute la sorte aurait
 * aussi caché les vraies (« Beffroi de la Bourse », « Pont Napoléon » paraissent au zoom 16, comme les autres).
 */
export const QUIET_POIS: ExpressionSpecification = [
  "all",
  ["==", ["get", "kind"], "attraction"],
  ["in", POI_NAME, ["literal", ["", ...GENERIC_POI_NAMES]]],
];

/** Le calque des points d'intérêt, sans ce qui n'apprend rien ; tout autre calque, tel quel. */
function quieted(layer: LayerSpecification): LayerSpecification {
  if (layer.id !== POIS_LAYER || layer.type !== "symbol") return layer;
  const keep: ExpressionSpecification = ["!", QUIET_POIS];
  const filter = (layer.filter ? ["all", layer.filter, keep] : keep) as FilterSpecification;
  return { ...layer, filter };
}

/**
 * Le style : la carte de ce serveur (`base` + les chemins de l'API), claire ou sombre. `base` est l'adresse absolue
 * du serveur (`mapBase()`) : MapLibre lit ses tuiles dans un travailleur né d'une adresse `blob:`, où un chemin seul ne
 * se résout pas. Les chemins sont collés tels quels, jamais passés par `URL` : `{z}`, `{fontstack}` y resteraient
 * encodés, et MapLibre ne les remplacerait plus. Sans polices, ses noms s'effacent ; sans icônes, ses symboles aussi —
 * jamais une police ou une planche venue d'ailleurs. Les points d'intérêt perdent ce qui n'apprend rien (`QUIET_POIS`).
 */
export function mapStyle(info: MapInfo, dark: boolean, base: string): StyleSpecification {
  const at = (path: string) => `${base}${path}`;
  const zooms = { minzoom: info.minzoom ?? 0, maxzoom: info.maxzoom ?? 15 };
  const bounds = info.bounds ? { bounds: info.bounds } : {};
  const attribution = info.attribution || "© OpenStreetMap";
  const tiles = [at(info.tiles ?? "")];
  if (info.kind === "image") {
    return {
      version: 8,
      sources: { [SOURCE]: { type: "raster", tiles, tileSize: 256, attribution, ...zooms, ...bounds } },
      layers: [{ id: SOURCE, type: "raster", source: SOURCE }],
    };
  }
  const flavor = dark ? "dark" : "light";
  const kept = (layers(SOURCE, namedFlavor(flavor), { lang: "fr" }) as LayerSpecification[]).map(quieted).flatMap((layer) => {
    if (layer.type !== "symbol") return [layer];
    const layout: Record<string, unknown> = { ...(layer.layout ?? {}) };
    if (!info.glyphs) delete layout["text-field"];
    if (!info.sprite) delete layout["icon-image"];
    if (!layout["text-field"] && !layout["icon-image"]) return [];
    return [{ ...layer, layout } as LayerSpecification];
  });
  return {
    version: 8,
    ...(info.glyphs ? { glyphs: at(info.glyphs) } : {}),
    ...(info.sprite ? { sprite: `${at(info.sprite)}/${flavor}` } : {}),
    sources: { [SOURCE]: { type: "vector", tiles, attribution, ...zooms, ...bounds } },
    layers: kept,
  };
}
