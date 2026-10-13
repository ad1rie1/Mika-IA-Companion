import { describe, expect, it } from "vitest";
import { components, corner, openingSign, union } from "../meshParts";

/** Une boîte en triangles, ses faces sans sommet partagé (comme l'exporteur glTF les dédouble aux arêtes vives). */
function box(x0: number, y0: number, z0: number, x1: number, y1: number, z1: number): number[] {
  const p = (x: number, y: number, z: number) => [x, y, z];
  const quads = [
    [p(x0, y0, z0), p(x1, y0, z0), p(x1, y1, z0), p(x0, y1, z0)],
    [p(x0, y0, z1), p(x1, y0, z1), p(x1, y1, z1), p(x0, y1, z1)],
    [p(x0, y0, z0), p(x0, y1, z0), p(x0, y1, z1), p(x0, y0, z1)],
    [p(x1, y0, z0), p(x1, y1, z0), p(x1, y1, z1), p(x1, y0, z1)],
    [p(x0, y0, z0), p(x1, y0, z0), p(x1, y0, z1), p(x0, y0, z1)],
    [p(x0, y1, z0), p(x1, y1, z0), p(x1, y1, z1), p(x0, y1, z1)],
  ];
  return quads.flatMap(([a, b, c, d]) => [...a, ...b, ...c, ...a, ...c, ...d]);
}

describe("les morceaux d'un maillage joint", () => {
  it("deux boîtes jointes redeviennent deux morceaux, même aux sommets dédoublés", () => {
    const positions = [...box(0, 0, 0, 1, 1, 1), ...box(2, 0, 0, 2.5, 2, 0.1)];
    const parts = components(positions, null);
    expect(parts).toHaveLength(2);
    expect(parts.map((c) => c.triangles.length)).toEqual([12, 12]);
    const thin = parts.find((c) => c.box.min[0] === 2)!;
    expect(thin.box.max).toEqual([2.5, 2, 0.1]);
  });

  it("deux boîtes qui se touchent n'en font qu'une", () => {
    const parts = components([...box(0, 0, 0, 1, 1, 1), ...box(1, 0, 0, 2, 1, 1)], null);
    expect(parts).toHaveLength(1);
  });

  it("un maillage indexé se lit par son index", () => {
    const positions = [0, 0, 0, 1, 0, 0, 0, 1, 0, 5, 5, 5, 6, 5, 5, 5, 6, 5];
    const parts = components(positions, [0, 1, 2, 3, 4, 5]);
    expect(parts.map((c) => c.triangles)).toEqual([[0], [1]]);
  });

  it("la charnière est un coin de la boîte, l'ouverture va vers la pièce", () => {
    const b = union([
      { min: [1.37, 0, 3.56], max: [2.23, 2.05, 3.6] },
      { min: [1.45, 0.99, 3.5], max: [1.57, 1.01, 3.51] },
    ])!;
    expect(b.min).toEqual([1.37, 0, 3.5]);
    expect(corner(b, { x: "max", y: "min", z: "min" })).toEqual([2.23, 0, 3.5]);
    // la porte (bord libre vers −x) s'ouvre vers −z : une rotation négative autour de +Y
    expect(openingSign({ x: -0.43, z: 0.02 }, { x: 0, z: -1 })).toBe(-1);
    // la croisée (bord libre vers +z) s'ouvre vers +x : positive
    expect(openingSign({ x: -0.02, z: 0.65 }, { x: 1, z: 0 })).toBe(1);
  });
});
