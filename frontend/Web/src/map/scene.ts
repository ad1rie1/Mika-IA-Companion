/**
 * Ce qu'une carte montre par-dessus le fond, sans MapLibre ni DOM : des épingles (numérotées, lettrées, roses pour ce
 * que Mika a fait ; secondaires, plus petites et sans numéro, pour les lieux d'à côté comme ceux de « Sur la route »),
 * des tracés (un itinéraire calculé, ou des points reliés à vol d'oiseau), la position de la personne et, quand on la
 * connaît, sa précision (un rayon : un cercle autour) ; la zone qui les tient tous, cercle compris, et comment une vue
 * la cadre (serrée sur l'écran Carte, un quartier autour sur une miniature, quelques fois son rayon autour d'une
 * position seule). La même scène sert la vraie carte et le plan dessiné de repli.
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
  /**
   * Une épingle secondaire (un lieu d'à côté, pas une étape : ceux de « Sur la route ») : plus petite, sans numéro même
   * si `label` en donne un, sous les autres.
   */
  minor?: boolean;
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

/** La position de la personne (son téléphone). */
export interface SceneHere {
  lat: number;
  lon: number;
  /** Sa précision, en mètres : un cercle autour du point, que la zone de la scène tient. Sans : le point seul. */
  accuracy_m?: number;
}

export interface Scene {
  pins: ScenePin[];
  lines: SceneLine[];
  /** La position de la personne, s'il faut la montrer. */
  here?: SceneHere | null;
}

export const EMPTY_SCENE: Scene = { pins: [], lines: [] };

/** Un degré de latitude, en mètres (le rayon moyen de la Terre de `mapgeo.ts`). */
const M_PER_DEG = 111_195;

/** Le plus petit plan autour d'une position seule, en mètres : sa rue et ses voisines. */
const HERE_SPAN_M = 300;

/** Le rayon de la précision d'une position, en mètres : un nombre fini et positif, sinon 0 (aucun cercle). */
export function hereRadius(here: Scene["here"]): number {
  const r = here?.accuracy_m;
  return typeof r === "number" && Number.isFinite(r) && r > 0 ? r : 0;
}

/** Le même rayon en degrés de latitude (0 : aucun cercle), pour le poser sur un dessin. */
export function hereRadiusDeg(here: Scene["here"]): number {
  return hereRadius(here) / M_PER_DEG;
}

/** Une position valide ; son rayon reste s'il est un nombre fini et positif, sinon le point seul. */
function cleanHere(here: Scene["here"]): SceneHere | null {
  if (!here || !validPoint(here.lat, here.lon)) return null;
  return here.accuracy_m === undefined || hereRadius(here) ? here : { lat: here.lat, lon: here.lon };
}

/** Ses épingles et ses tracés valides seulement (des coordonnées hors de la Terre ne se posent pas). */
export function cleanScene(scene: Scene): Scene {
  return {
    pins: scene.pins.filter((p) => validPoint(p.lat, p.lon)),
    lines: scene.lines
      .map((l) => ({ ...l, points: l.points.filter(([la, lo]) => validPoint(la, lo)) }))
      .filter((l) => l.points.length >= 2),
    here: cleanHere(scene.here),
  };
}

/** La position et, si elle a un rayon, les quatre bords de son cercle (nord, sud, est, ouest). */
function herePoints(here: SceneHere): LatLon[] {
  const dLat = hereRadiusDeg(here);
  if (!dLat) return [[here.lat, here.lon]];
  const dLon = dLat / Math.max(0.01, Math.cos((here.lat * Math.PI) / 180));
  return [[here.lat + dLat, here.lon], [here.lat - dLat, here.lon], [here.lat, here.lon + dLon], [here.lat, here.lon - dLon]];
}

/**
 * La zone qui tient toute la scène, le cercle de la position compris (élargie à `minDeg` degrés au moins autour d'un
 * point seul) ; rien à montrer : `null`.
 */
export function sceneBounds(scene: Scene, minDeg?: number): Bounds | null {
  const points: LatLon[] = [
    ...scene.pins.map((p): LatLon => [p.lat, p.lon]),
    ...scene.lines.flatMap((l) => l.points),
    ...(scene.here ? herePoints(scene.here) : []),
  ];
  const b = boundsOf(points);
  return b ? widened(b, minDeg) : null;
}

/**
 * L'élargissement (en degrés) d'une scène qui n'a que la position et sa précision : quelques fois son rayon, ~300 m au
 * moins — pas le quartier de ~2 km d'une scène à épingles, où un cercle de 12 m ne serait qu'un point. Une scène qui
 * a des épingles ou des tracés, ou une position sans rayon : `undefined` (l'élargissement de la vue, inchangé).
 */
export function hereSpan(scene: Scene): number | undefined {
  const r = hereRadius(scene.here);
  if (!r || scene.pins.length || scene.lines.length) return undefined;
  return Math.max(HERE_SPAN_M, 5 * r) / M_PER_DEG;
}

/** Comment une vue cadre ce qu'elle montre : l'élargissement d'une zone trop petite (degrés), ses marges (px), son zoom le plus serré. */
export interface Framing {
  minDeg: number;
  padding: number;
  maxZoom: number;
}

/**
 * L'écran Carte : des lieux à quelques mètres les uns des autres se départagent (une rue, ~200 m au moins, jusqu'au
 * zoom 17). Une miniature du chat garde un quartier autour (~2 km, jusqu'au zoom 12,5), pour qu'on reconnaisse où c'est.
 */
export function framingFor(interactive: boolean): Framing {
  return interactive ? { minDeg: 0.002, padding: 56, maxZoom: 17 } : { minDeg: 0.02, padding: 18, maxZoom: 12.5 };
}

/** Le cadrage d'une scène dans une vue : sa zone, élargie à la mesure de cette vue, ses marges, son plafond ; rien à montrer : `null`. */
export function sceneFraming(scene: Scene, interactive: boolean): (Framing & { bounds: Bounds }) | null {
  const f = framingFor(interactive);
  const bounds = sceneBounds(scene, f.minDeg);
  return bounds ? { ...f, bounds } : null;
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
