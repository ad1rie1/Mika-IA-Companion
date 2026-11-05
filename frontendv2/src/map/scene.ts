/**
 * Ce qu'une carte montre par-dessus le fond, sans MapLibre ni DOM : des épingles (numérotées, lettrées, roses pour ce
 * que Mika a fait), des tracés (un itinéraire calculé, ou des points reliés à vol d'oiseau), la position de la
 * personne ; et la zone qui les tient tous. La même scène sert la vraie carte et le plan dessiné de repli.
 */
import type { FeatureCollection } from "geojson";
import { boundsOf, validPoint, widened, type Bounds } from "./mapgeo";
import type { LatLon } from "./polyline";

export interface ScenePin {
  /** Ce que vise un clic (un lieu, un arrêt). */
  id: string;
  lat: number;
  lon: number;
  /** Dans l'épingle : un numéro, une lettre (A, B), ou rien. */
  label?: string;
  /** Ce que Mika a trouvé, proposé ou ajouté : en rose. */
  mika?: boolean;
  /** L'épingle choisie : plus grande, cerclée. */
  selected?: boolean;
  /** Son nom, au survol et pour un lecteur d'écran. */
  title?: string;
}

export interface SceneLine {
  points: LatLon[];
  /** Ce qu'elle a montré : en rose. */
  mika?: boolean;
  /** Des points reliés à vol d'oiseau (pas un trajet calculé) : en pointillés. */
  straight?: boolean;
}

export interface Scene {
  pins: ScenePin[];
  lines: SceneLine[];
  /** La position de la personne (son téléphone), s'il faut la montrer. */
  here?: { lat: number; lon: number } | null;
}

export const EMPTY_SCENE: Scene = { pins: [], lines: [] };

/** Ses épingles et ses tracés valides seulement (des coordonnées hors de la Terre ne se posent pas). */
export function cleanScene(scene: Scene): Scene {
  return {
    pins: scene.pins.filter((p) => validPoint(p.lat, p.lon)),
    lines: scene.lines
      .map((l) => ({ ...l, points: l.points.filter(([la, lo]) => validPoint(la, lo)) }))
      .filter((l) => l.points.length >= 2),
    here: scene.here && validPoint(scene.here.lat, scene.here.lon) ? scene.here : null,
  };
}

/** La zone qui tient toute la scène (élargie autour d'un point seul) ; rien à montrer : `null`. */
export function sceneBounds(scene: Scene): Bounds | null {
  const points: LatLon[] = [
    ...scene.pins.map((p): LatLon => [p.lat, p.lon]),
    ...scene.lines.flatMap((l) => l.points),
    ...(scene.here ? [[scene.here.lat, scene.here.lon] as LatLon] : []),
  ];
  const b = boundsOf(points);
  return b ? widened(b) : null;
}

/** Les tracés en GeoJSON (lon, lat), pour la couche des lignes. */
export function linesGeoJson(scene: Scene): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: scene.lines.map((l) => ({
      type: "Feature",
      properties: { mika: !!l.mika, straight: !!l.straight },
      geometry: { type: "LineString", coordinates: l.points.map(([la, lo]) => [lo, la]) },
    })),
  };
}

/** Des points reliés dans l'ordre, à vol d'oiseau : le trajet qu'on n'a pas (ou pas encore) calculé. */
export function straightLine(points: readonly LatLon[]): SceneLine | null {
  const ok = points.filter(([la, lo]) => validPoint(la, lo));
  return ok.length >= 2 ? { points: [...ok], straight: true } : null;
}

/** Une empreinte d'un tracé (ses points peuvent être des milliers) : la même ligne, la même empreinte. */
function lineSum(points: readonly LatLon[]): string {
  let a = 0;
  let b = 0;
  points.forEach(([la, lo], i) => {
    a = (a + la * (i + 1)) % 1e9;
    b = (b + lo * (i + 7)) % 1e9;
  });
  return `${points.length}:${a.toFixed(4)}:${b.toFixed(4)}`;
}

/** Ce qui change entre deux scènes : rien de changé, rien à reposer. */
export function sceneKey(scene: Scene): string {
  return JSON.stringify([scene.pins, scene.lines.map((l) => [!!l.mika, !!l.straight, lineSum(l.points)]), scene.here ?? null]);
}
