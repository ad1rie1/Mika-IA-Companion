import { describe, expect, it } from "vitest";
import type { MapInfo } from "../../api/phone";
import { circle, covers, zoomFor } from "./mapgeo";
import { mapStyle } from "./mapstyle";

const ORIGIN = "http://127.0.0.1:8013";
const LILLE: MapInfo = {
  ready: true,
  reason: "",
  kind: "vecteur",
  minzoom: 0,
  maxzoom: 15,
  bounds: [-5.2, 41.3, 9.6, 51.1],
  attribution: "© OpenStreetMap",
  tiles: "/api/moi/phone/map/tiles/{z}/{x}/{y}",
  glyphs: "/api/moi/phone/map/fonts/{fontstack}/{range}.pbf",
  sprite: "/api/moi/phone/map/sprites/v4",
};

describe("la carte de sa position (ADR 0193)", () => {
  it("ne montre que ce qu'elle couvre", () => {
    expect(covers(LILLE, 50.6365, 3.0635)).toBe(true);
    expect(covers(LILLE, 52.52, 13.4)).toBe(false); // Berlin : hors de la France extraite, le plan dessiné
    expect(covers({ ...LILLE, bounds: null }, 52.52, 13.4)).toBe(true); // un serveur {z}/{x}/{y} : partout
    expect(covers({ ready: false, reason: "aucune" }, 50.6, 3.06)).toBe(false);
    expect(covers(null, 50.6, 3.06)).toBe(false);
  });

  it("pose sa précision en cercle, et un zoom qui la montre", () => {
    const ring = circle(50.6365, 3.0635, 120);
    expect(ring).toHaveLength(65);
    expect(ring[0]).toEqual(ring[64]); // fermé
    const north = ring[0]; // vers le nord : 120 m ≈ 0,00108°
    expect(north[1] - 50.6365).toBeCloseTo(120 / 111_195, 5);
    expect(zoomFor(12)).toBe(16); // quelques mètres : le quartier autour
    expect(zoomFor(5000)).toBeGreaterThanOrEqual(11);
    expect(zoomFor(5000)).toBeLessThan(zoomFor(100));
  });

  it("ne charge rien d'ailleurs : ses tuiles, ses polices et ses icônes viennent du serveur de Mika", () => {
    const style = mapStyle(LILLE, false, ORIGIN);
    const urls = JSON.stringify(style).match(/https?:\/\/[^"\s]+/g) ?? [];
    expect(urls.length).toBeGreaterThan(0);
    expect(urls.every((u) => u.startsWith(ORIGIN))).toBe(true);
    expect(style.glyphs).toBe(`${ORIGIN}/api/moi/phone/map/fonts/{fontstack}/{range}.pbf`);
    expect(style.sprite).toBe(`${ORIGIN}/api/moi/phone/map/sprites/v4/light`);
    expect(mapStyle(LILLE, true, ORIGIN).sprite).toBe(`${ORIGIN}/api/moi/phone/map/sprites/v4/dark`);
    expect(style.sources.carte).toMatchObject({ type: "vector", tiles: [`${ORIGIN}/api/moi/phone/map/tiles/{z}/{x}/{y}`], maxzoom: 15 });
  });

  it("sans polices, ses noms s'effacent ; sans icônes, ses symboles aussi", () => {
    const bare = mapStyle({ ...LILLE, glyphs: null, sprite: null }, false, ORIGIN);
    expect(bare.glyphs).toBeUndefined();
    expect(bare.sprite).toBeUndefined();
    const layouts = bare.layers.map((l) => ("layout" in l ? (l.layout as Record<string, unknown> | undefined) : undefined) ?? {});
    expect(layouts.some((l) => "text-field" in l || "icon-image" in l)).toBe(false);
    expect(bare.layers.length).toBeGreaterThan(10); // l'eau, les routes, les bâtiments restent
  });

  it("des images : une seule couche, ses tuiles telles quelles", () => {
    const style = mapStyle({ ...LILLE, kind: "image", glyphs: null, sprite: null }, false, ORIGIN);
    expect(style.layers).toEqual([{ id: "carte", type: "raster", source: "carte" }]);
    expect(style.sources.carte).toMatchObject({ type: "raster", tileSize: 256 });
  });
});
