/**
 * Les calculs d'une carte, sans aucune dépendance (ADR 0193, 0194) : ce que la carte du serveur couvre, le cercle d'une
 * précision et le zoom qui le montre, la zone qui tient des points, une distance à vol d'oiseau.
 */
import type { MapInfo } from "../api/phone";
import type { LatLon } from "./polyline";

/** Le rayon moyen de la Terre, en mètres. */
const EARTH_M = 6_371_008.8;

/** Ouest, sud, est, nord, en degrés. */
export type Bounds = [number, number, number, number];

/** La carte montre-t-elle ce point ? Une archive dit sa zone ; un serveur `{z}/{x}/{y}`, partout. */
export function covers(info: MapInfo | null, lat: number, lon: number): boolean {
  if (!info?.ready || !info.tiles) return false;
  const b = info.bounds;
  return !b || (lon >= b[0] && lon <= b[2] && lat >= b[1] && lat <= b[3]);
}

/** La carte couvre-t-elle tous ces points (aucun : non) ? */
export function coversAll(info: MapInfo | null, points: readonly LatLon[]): boolean {
  return points.length > 0 && points.every(([la, lo]) => covers(info, la, lo));
}

/** Un cercle de `meters` autour du point, en polygone fermé (lon, lat) : juste à tous les zooms. */
export function circle(lat: number, lon: number, meters: number, steps = 64): [number, number][] {
  const d = Math.max(1, meters) / EARTH_M;
  const la = (lat * Math.PI) / 180;
  const lo = (lon * Math.PI) / 180;
  const out: [number, number][] = [];
  for (let i = 0; i <= steps; i++) {
    const t = (2 * Math.PI * i) / steps;
    const la2 = Math.asin(Math.sin(la) * Math.cos(d) + Math.cos(la) * Math.sin(d) * Math.cos(t));
    const lo2 = lo + Math.atan2(Math.sin(t) * Math.sin(d) * Math.cos(la), Math.cos(d) - Math.sin(la) * Math.sin(la2));
    out.push([(lo2 * 180) / Math.PI, (la2 * 180) / Math.PI]);
  }
  return out;
}

/** Le zoom qui montre sa précision en entier : le quartier autour pour quelques mètres, plus large au-delà. */
export function zoomFor(meters: number): number {
  const m = Math.max(15, meters || 15);
  return Math.max(11, Math.min(16, 17 - Math.log2(m / 40)));
}

/** La distance à vol d'oiseau entre deux points, en mètres. */
export function meters(a: LatLon, b: LatLon): number {
  const p1 = (a[0] * Math.PI) / 180;
  const p2 = (b[0] * Math.PI) / 180;
  const dp = p2 - p1;
  const dl = ((b[1] - a[1]) * Math.PI) / 180;
  const x = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_M * Math.asin(Math.min(1, Math.sqrt(x)));
}

/** La zone qui tient ces points (aucun : `null`). Un seul point : une zone sans largeur, que l'écran élargit. */
export function boundsOf(points: readonly LatLon[]): Bounds | null {
  const ok = points.filter(([la, lo]) => Number.isFinite(la) && Number.isFinite(lo));
  if (!ok.length) return null;
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const [la, lo] of ok) {
    west = Math.min(west, lo);
    east = Math.max(east, lo);
    south = Math.min(south, la);
    north = Math.max(north, la);
  }
  return [west, south, east, north];
}

/** Une zone élargie d'au moins `minDeg` degrés (un point seul, deux points voisins : un quartier autour). */
export function widened(b: Bounds, minDeg = 0.02): Bounds {
  const [w, s, e, n] = b;
  const dx = Math.max(0, minDeg - (e - w)) / 2;
  const dy = Math.max(0, minDeg - (n - s)) / 2;
  return [Math.max(-180, w - dx), Math.max(-85, s - dy), Math.min(180, e + dx), Math.min(85, n + dy)];
}

/** Un point valide : deux nombres finis dans leurs bornes. */
export function validPoint(lat: unknown, lon: unknown): boolean {
  return typeof lat === "number" && typeof lon === "number" && Number.isFinite(lat) && Number.isFinite(lon)
    && Math.abs(lat) <= 90 && Math.abs(lon) <= 180;
}
