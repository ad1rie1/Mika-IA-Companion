/**
 * Le tracé d'un itinéraire, tel que le serveur le rend (`shape`) : l'algorithme des polylines, à six décimales — le
 * même que `backendv2/src/mika/ports/maps.py` (`decode_polyline6`, `encode_polyline6`). Des nombres entiers jusqu'au
 * bout (jamais une opération sur 32 bits : une longitude de 180° y tient, ses écarts aussi), puis divisés par 10⁶.
 */

/** Un point (latitude, longitude), en degrés. */
export type LatLon = [number, number];

/** Les points (lat, lon) d'un tracé encodé. Illisible ou tronqué : une erreur, comme le serveur. */
export function decodePolyline6(text: string): LatLon[] {
  const points: LatLon[] = [];
  let index = 0;
  let lat = 0;
  let lon = 0;
  const n = text.length;
  while (index < n) {
    const deltas: number[] = [];
    for (let k = 0; k < 2; k++) {
      let result = 0;
      let factor = 1;
      for (;;) {
        if (index >= n) throw new Error("un tracé tronqué");
        const byte = text.charCodeAt(index) - 63;
        index += 1;
        if (!(byte >= 0 && byte < 64)) throw new Error("un tracé illisible");
        result += (byte & 0x1f) * factor;
        factor *= 32;
        if (byte < 0x20) break;
      }
      // le signe est dans le bit le plus bas (zigzag) : ~(r >> 1) pour un impair, r >> 1 sinon
      deltas.push(result % 2 === 1 ? -(result + 1) / 2 : result / 2);
    }
    lat += deltas[0];
    lon += deltas[1];
    points.push([lat / 1e6, lon / 1e6]);
  }
  return points;
}

/** L'inverse de `decodePolyline6` (les tests, et un tracé qu'on reposerait tel quel). */
export function encodePolyline6(points: readonly LatLon[]): string {
  let out = "";
  let lastLat = 0;
  let lastLon = 0;
  for (const [la, lo] of points) {
    const ilat = Math.round(la * 1e6);
    const ilon = Math.round(lo * 1e6);
    for (const delta of [ilat - lastLat, ilon - lastLon]) {
      let value = delta < 0 ? -2 * delta - 1 : 2 * delta;
      while (value >= 0x20) {
        out += String.fromCharCode((0x20 | (value % 32)) + 63);
        value = Math.floor(value / 32);
      }
      out += String.fromCharCode(value + 63);
    }
    lastLat = ilat;
    lastLon = ilon;
  }
  return out;
}

/** Un tracé lisible, ou rien : une forme abîmée ne fait jamais tomber l'écran (on relie alors les points). */
export function safeDecode(text: unknown): LatLon[] {
  if (typeof text !== "string" || !text) return [];
  try {
    return decodePolyline6(text).filter(([la, lo]) => Number.isFinite(la) && Number.isFinite(lo) && Math.abs(la) <= 90 && Math.abs(lo) <= 180);
  } catch {
    return [];
  }
}
