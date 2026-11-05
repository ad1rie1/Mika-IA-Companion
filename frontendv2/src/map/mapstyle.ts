/**
 * Le style d'une carte (ADR 0193, 0194), sans MapLibre : les tuiles, les polices et les icônes de ce serveur seulement,
 * claires ou sombres (les couleurs de Protomaps, ses noms en français).
 */
import { layers, namedFlavor } from "@protomaps/basemaps";
import type { LayerSpecification, StyleSpecification } from "maplibre-gl";
import type { MapInfo } from "../api/phone";

export const SOURCE = "carte";

/**
 * Le style : la carte de ce serveur (`base` + les chemins de l'API), claire ou sombre. `base` est l'adresse absolue
 * du serveur (`mapBase()`) : MapLibre lit ses tuiles dans un travailleur né d'une adresse `blob:`, où un chemin seul ne
 * se résout pas. Les chemins sont collés tels quels, jamais passés par `URL` : `{z}`, `{fontstack}` y resteraient
 * encodés, et MapLibre ne les remplacerait plus. Sans polices, ses noms s'effacent ; sans icônes, ses symboles aussi —
 * jamais une police ou une planche venue d'ailleurs.
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
  const kept = (layers(SOURCE, namedFlavor(flavor), { lang: "fr" }) as LayerSpecification[]).flatMap((layer) => {
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
