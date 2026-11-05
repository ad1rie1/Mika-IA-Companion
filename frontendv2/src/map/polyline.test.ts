import { describe, expect, it } from "vitest";
import { decodePolyline6, encodePolyline6, safeDecode } from "./polyline";

// Les mêmes points que `backendv2/tests/unit/test_maps_routing.py`, encodés par `mika.ports.maps.encode_polyline6`.
const SHAPE: [number, number][] = [[45.899543, 6.128952], [45.8, 6.05], [45.564275, 5.91769]];
const SHAPE6 = "mpnpvAorauJllaEneyCxkkMjlaG";
// Des longitudes et latitudes à leurs bornes : rien ne déborde sur 32 bits.
const FAR: [number, number][] = [[-33.868, 151.21], [51.5074, -0.1278], [0, 0], [89.999999, -179.999999]];
const FAR6 = "~lcr_A_`cl_Hoy{yaDns|s_HnkwfaBorxF}fdtjD|niivI";

describe("le tracé d'un itinéraire (polyline à six décimales)", () => {
  it("se lit comme le serveur l'écrit", () => {
    expect(decodePolyline6(SHAPE6)).toEqual(SHAPE);
    expect(decodePolyline6(FAR6)).toEqual(FAR);
    // l'exemple de l'algorithme (cinq décimales), lu à six : les mêmes chiffres, une décimale plus loin
    expect(decodePolyline6("_p~iF~ps|U_ulLnnqC_mqNvxq`@")).toEqual([[3.85, -12.02], [4.07, -12.095], [4.3252, -12.6453]]);
    expect(decodePolyline6("")).toEqual([]);
  });

  it("s'écrit comme le serveur", () => {
    expect(encodePolyline6(SHAPE)).toBe(SHAPE6);
    expect(encodePolyline6(FAR)).toBe(FAR6);
    expect(decodePolyline6(encodePolyline6(SHAPE))).toEqual(SHAPE);
  });

  it("refuse un tracé tronqué ou illisible ; `safeDecode` rend alors rien", () => {
    expect(() => decodePolyline6("_p~iF~ps|U_")).toThrow("un tracé tronqué");
    expect(() => decodePolyline6("_p~iF~ps|U\u007f")).toThrow("un tracé illisible");
    expect(safeDecode("_p~iF~ps|U_")).toEqual([]);
    expect(safeDecode(null)).toEqual([]);
    expect(safeDecode(SHAPE6)).toEqual(SHAPE);
  });
});
