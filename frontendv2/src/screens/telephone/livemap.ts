/**
 * La vraie carte de sa position (ADR 0193), dessinée par MapLibre. Ce module se charge à part (import dynamique,
 * avec MapLibre et sa feuille) : il ne retarde aucun écran. Ses tuiles, ses polices et ses icônes viennent du serveur
 * de Mika, avec la session ; la position et sa précision s'y posent par-dessus, aux couleurs du thème.
 */
import maplibregl, { type GeoJSONSource, type Map as MapLibre } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FeatureCollection } from "geojson";
import { API_BASE } from "@web/network/api";
import type { MapInfo } from "../../api/phone";
import { circle, zoomFor } from "./mapgeo";
import { mapStyle } from "./mapstyle";

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

/** La carte dans `host`, centrée sur `first`. Lève si le navigateur ne dessine pas (pas de WebGL) : le plan reste. */
export function mountMap(host: HTMLElement, info: MapInfo, first: At, dark: boolean): LiveMap {
  let at = first;
  let shownDark = dark;
  const map = new maplibregl.Map({
    container: host,
    style: mapStyle(info, dark, API_BASE),
    center: [at.lon, at.lat],
    zoom: zoomFor(at.accuracy),
    maxZoom: 19,
    attributionControl: { compact: false },
    // ses tuiles, polices et icônes : du serveur de Mika, avec la session (en dev, le client est d'une autre origine)
    transformRequest: (url) => (url.startsWith(API_BASE) ? { url, credentials: "include" } : { url }),
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  map.on("style.load", () => addHere(map, at));
  return {
    host,
    show(next, nextDark) {
      const moved = next.lat !== at.lat || next.lon !== at.lon;
      at = next;
      if (nextDark !== shownDark) {
        shownDark = nextDark;
        map.setStyle(mapStyle(info, nextDark, API_BASE), { diff: false }); // « style.load » repose la position
      } else {
        (map.getSource(HERE) as GeoJSONSource | undefined)?.setData(features(at));
      }
      if (moved) map.easeTo({ center: [at.lon, at.lat] });
    },
    resize() {
      map.resize();
    },
    remove() {
      map.remove();
    },
  };
}
