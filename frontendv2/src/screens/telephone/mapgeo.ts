/**
 * La carte de sa position (ADR 0193), en calculs seulement (aucune dépendance) : ce qu'elle couvre, le cercle de sa
 * précision, le zoom qui le montre.
 */
import type { MapInfo } from "../../api/phone";

/** Le rayon moyen de la Terre, en mètres. */
const EARTH_M = 6_371_008.8;

/** La carte montre-t-elle ce point ? Une archive dit sa zone ; un serveur `{z}/{x}/{y}`, partout. */
export function covers(info: MapInfo | null, lat: number, lon: number): boolean {
  if (!info?.ready || !info.tiles) return false;
  const b = info.bounds;
  return !b || (lon >= b[0] && lon <= b[2] && lat >= b[1] && lat <= b[3]);
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
