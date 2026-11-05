/**
 * La vraie carte de sa position (ADR 0193), dessinée par MapLibre sur la carte du serveur (`map/base.ts` : ses tuiles,
 * ses polices et ses icônes avec la session, les commandes en français, le thème, une autre carte du serveur qui se
 * repose, des tuiles en échec de suite qui font revenir le plan). La position et sa précision s'y posent par-dessus,
 * aux couleurs du thème. MapLibre arrive chargé (`map/load.ts`) : ce module ne l'importe pas.
 */
import type { FeatureCollection } from "geojson";
import type { GeoJSONSource, Map as MapLibre } from "maplibre-gl";
import type { MapInfo } from "../../api/phone";
import { createBaseMap, type MapLib } from "../../map/base";
import { circle, zoomFor } from "../../map/mapgeo";

export interface At {
  lat: number;
  lon: number;
  /** Sa précision, en mètres. */
  accuracy: number;
}

export interface LiveMap {
  /** Le cadre où elle est dessinée : il se repose tel quel quand l'écran se redessine. */
  readonly host: HTMLElement;
  /** Une autre position, ou un autre thème : la carte suit, sans se refaire. */
  show(at: At, dark: boolean): void;
  /** Une autre carte du serveur (relue toutes les cinq minutes). */
  restyle(info: MapInfo): void;
  resize(): void;
  remove(): void;
}

const HERE = "ici";

function features(at: At): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: [
      { type: "Feature", properties: { kind: "zone" }, geometry: { type: "Polygon", coordinates: [circle(at.lat, at.lon, at.accuracy)] } },
      { type: "Feature", properties: { kind: "point" }, geometry: { type: "Point", coordinates: [at.lon, at.lat] } },
    ],
  };
}

/** Une couleur du thème (`base.css`), lue au moment de la poser. */
function token(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function addHere(map: MapLibre, at: At): void {
  const source = map.getSource(HERE) as GeoJSONSource | undefined;
  if (source) {
    source.setData(features(at));
    return;
  }
  map.addSource(HERE, { type: "geojson", data: features(at) });
  const accent = token("--accent", "#4f46e5");
  map.addLayer({ id: "ici-zone", type: "fill", source: HERE, filter: ["==", ["get", "kind"], "zone"],
    paint: { "fill-color": accent, "fill-opacity": 0.14 } });
  map.addLayer({ id: "ici-bord", type: "line", source: HERE, filter: ["==", ["get", "kind"], "zone"],
    paint: { "line-color": accent, "line-opacity": 0.5, "line-width": 1.5 } });
  map.addLayer({ id: "ici-point", type: "circle", source: HERE, filter: ["==", ["get", "kind"], "point"],
    paint: { "circle-radius": 7, "circle-color": token("--accent-fill", accent),
      "circle-stroke-color": token("--raised", "#ffffff"), "circle-stroke-width": 3 } });
}

/**
 * La carte dans `host`, centrée sur `first`. Lève si le navigateur ne dessine pas (pas de WebGL) : le plan reste.
 * `onFail` : ses tuiles échouent de suite (un serveur de carte injoignable) — l'écran reprend son plan dessiné.
 */
export function mountMap(lib: MapLib, host: HTMLElement, info: MapInfo, first: At, dark: boolean, onFail?: () => void): LiveMap {
  let at = first;
  let shownDark = dark;
  const base = createBaseMap(lib, host, info, {
    dark,
    center: [at.lon, at.lat],
    zoom: zoomFor(at.accuracy),
    overlay: (map) => addHere(map, at),
    onFail,
  });
  const map = base.map;
  return {
    host,
    show(next, nextDark) {
      const moved = next.lat !== at.lat || next.lon !== at.lon;
      at = next;
      if (nextDark !== shownDark) {
        shownDark = nextDark;
        base.theme(nextDark); // « style.load » repose la position
      } else {
        (map.getSource(HERE) as GeoJSONSource | undefined)?.setData(features(at));
      }
      if (moved) map.easeTo({ center: [at.lon, at.lat] });
    },
    restyle(next) {
      base.restyle(next);
    },
    resize() {
      base.resize();
    },
    remove() {
      base.remove();
    },
  };
}
