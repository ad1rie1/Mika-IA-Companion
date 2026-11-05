import { describe, expect, it } from "vitest";
import type { MapOptions, StyleSpecification } from "maplibre-gl";
import type { MapInfo } from "../api/phone";
import { absoluteBase, createBaseMap, FR_LOCALE, mapOptions, TileWatch, transformFor, type MapLib } from "./base";
import { infoKey } from "./info";
import { boundsOf, circle, covers, coversAll, meters, widened, zoomFor } from "./mapgeo";
import { attributionText } from "./cards";
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
  tiles: "/api/moi/phone/map/tiles/{z}/{x}/{y}?v=1a2b3c4d5e6f",
  glyphs: "/api/moi/phone/map/fonts/{fontstack}/{range}.pbf?v=1a2b3c4d5e6f",
  sprite: "/api/moi/phone/map/sprites/~1a2b3c4d5e6f/v4",
};

/** Un faux MapLibre : ce qu'on lui demande (styles posés, commandes), et des événements qu'on déclenche. */
class FakeMap {
  static last: FakeMap;
  readonly handlers = new Map<string, Array<(e: unknown) => void>>();
  readonly styles: StyleSpecification[] = [];
  readonly controls: Array<[unknown, string]> = [];
  /** Les gestes qui ne tournent plus la carte. */
  readonly unrotated: string[] = [];
  readonly touchZoomRotate = { disableRotation: () => this.unrotated.push("doigts") };
  readonly keyboard = { disableRotation: () => this.unrotated.push("clavier") };
  removed = false;

  constructor(readonly options: MapOptions) {
    FakeMap.last = this;
    this.styles.push(options.style as StyleSpecification);
  }

  on(type: string, fn: (e: unknown) => void): this {
    const list = this.handlers.get(type) ?? [];
    list.push(fn);
    this.handlers.set(type, list);
    return this;
  }

  fire(type: string, e: unknown = {}): void {
    for (const fn of this.handlers.get(type) ?? []) fn(e);
  }

  addControl(control: unknown, where: string): this {
    this.controls.push([control, where]);
    return this;
  }

  setStyle(style: StyleSpecification): this {
    this.styles.push(style);
    this.fire("style.load");
    return this;
  }

  resize(): void {}

  remove(): void {
    this.removed = true;
  }
}

const fakeLib = { Map: FakeMap, NavigationControl: class { constructor(readonly options: unknown) {} } } as unknown as MapLib;
const host = {} as HTMLElement;

describe("la carte du serveur (ADR 0193)", () => {
  it("ne montre que ce qu'elle couvre", () => {
    expect(covers(LILLE, 50.6365, 3.0635)).toBe(true);
    expect(covers(LILLE, 52.52, 13.4)).toBe(false); // Berlin : hors de la France extraite, le plan dessiné
    expect(covers({ ...LILLE, bounds: null }, 52.52, 13.4)).toBe(true); // un serveur {z}/{x}/{y} : partout
    expect(covers({ ready: false, reason: "aucune" }, 50.6, 3.06)).toBe(false);
    expect(covers(null, 50.6, 3.06)).toBe(false);
    expect(coversAll(LILLE, [[50.6, 3.06], [45.9, 6.13]])).toBe(true);
    expect(coversAll(LILLE, [[50.6, 3.06], [52.52, 13.4]])).toBe(false);
    expect(coversAll(LILLE, [])).toBe(false);
  });

  it("pose une précision en cercle, et un zoom qui la montre", () => {
    const ring = circle(50.6365, 3.0635, 120);
    expect(ring).toHaveLength(65);
    expect(ring[0]).toEqual(ring[64]); // fermé
    const north = ring[0]; // vers le nord : 120 m ≈ 0,00108°
    expect(north[1] - 50.6365).toBeCloseTo(120 / 111_195, 5);
    expect(zoomFor(12)).toBe(16); // quelques mètres : le quartier autour
    expect(zoomFor(5000)).toBeGreaterThanOrEqual(11);
    expect(zoomFor(5000)).toBeLessThan(zoomFor(100));
  });

  it("la zone qui tient des points, élargie autour d'un seul ; une distance à vol d'oiseau", () => {
    expect(boundsOf([[45.9, 6.1], [43.7, 7.26]])).toEqual([6.1, 43.7, 7.26, 45.9]);
    expect(boundsOf([])).toBeNull();
    const [w, s, e, n] = widened([6.1, 45.9, 6.1, 45.9]);
    expect(e - w).toBeCloseTo(0.02, 6);
    expect(n - s).toBeCloseTo(0.02, 6);
    expect(meters([50.6365, 3.0635], [45.8992, 6.1294]) / 1000).toBeCloseTo(573.4, 1); // Lille → Annecy
  });

  it("ne charge rien d'ailleurs : ses tuiles, ses polices et ses icônes viennent du serveur de Mika", () => {
    const style = mapStyle(LILLE, false, ORIGIN);
    const urls = JSON.stringify(style).match(/https?:\/\/[^"\s]+/g) ?? [];
    expect(urls.length).toBeGreaterThan(0);
    expect(urls.every((u) => u.startsWith(ORIGIN))).toBe(true);
    expect(style.glyphs).toBe(`${ORIGIN}/api/moi/phone/map/fonts/{fontstack}/{range}.pbf?v=1a2b3c4d5e6f`);
    expect(style.sprite).toBe(`${ORIGIN}/api/moi/phone/map/sprites/~1a2b3c4d5e6f/v4/light`);
    expect(mapStyle(LILLE, true, ORIGIN).sprite).toBe(`${ORIGIN}/api/moi/phone/map/sprites/~1a2b3c4d5e6f/v4/dark`);
    expect(style.sources.carte).toMatchObject({ type: "vector", tiles: [`${ORIGIN}/api/moi/phone/map/tiles/{z}/{x}/{y}?v=1a2b3c4d5e6f`], maxzoom: 15 });
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

  it("la mention de la carte, en texte pour une miniature (aucun lien)", () => {
    expect(attributionText({ ...LILLE, attribution: '<a href="https://www.openstreetmap.org/copyright">&copy; OpenStreetMap</a>' })).toBe("© OpenStreetMap");
    expect(attributionText(null)).toBe("© OpenStreetMap");
  });
});

describe("une carte sur la même origine que le serveur (client construit sans VITE_BACKEND_ORIGIN)", () => {
  it("pose ses chemins sur l'adresse de la page : MapLibre ne lit pas une adresse relative", () => {
    // Caddy sert le client et le serveur à la même adresse : la base de l'API est vide
    const base = absoluteBase("", "http://192.168.1.22");
    expect(base).toBe("http://192.168.1.22");
    const style = mapStyle(LILLE, false, base);
    const tiles = (style.sources.carte as { tiles: string[] }).tiles[0];
    expect(tiles).toBe("http://192.168.1.22/api/moi/phone/map/tiles/{z}/{x}/{y}?v=1a2b3c4d5e6f"); // `{z}` intact
    expect(style.glyphs).toBe("http://192.168.1.22/api/moi/phone/map/fonts/{fontstack}/{range}.pbf?v=1a2b3c4d5e6f");
    expect(String(style.sprite).startsWith("http://192.168.1.22/api/moi/")).toBe(true);
  });

  it("garde une base absolue telle quelle, et un préfixe de chemin", () => {
    expect(absoluteBase("http://localhost:8001/", "http://localhost:4173")).toBe("http://localhost:8001");
    expect(absoluteBase("/mika", "https://maison.example")).toBe("https://maison.example/mika");
  });

  it("ne demande avec la session que ce qui va à ce serveur", () => {
    const transform = transformFor("http://192.168.1.22");
    expect(transform("http://192.168.1.22/api/moi/phone/map/tiles/3/4/2")).toEqual({ url: "http://192.168.1.22/api/moi/phone/map/tiles/3/4/2", credentials: "include" });
    expect(transform("http://192.168.1.220/x")).toEqual({ url: "http://192.168.1.220/x" });
    const options = mapOptions(host, LILLE, { dark: false }, "http://192.168.1.22");
    const asked = options.transformRequest?.("http://192.168.1.22/api/moi/phone/map/fonts/a/0-255.pbf", "Glyphs" as never);
    expect(asked).toMatchObject({ credentials: "include" });
  });
});

describe("ses commandes, en français", () => {
  it("MapLibre reçoit sa langue : zoomer, dézoomer, la carte", () => {
    const options = mapOptions(host, LILLE, { dark: false }, ORIGIN);
    expect(options.locale?.["NavigationControl.ZoomIn"]).toBe("Zoomer");
    expect(options.locale?.["NavigationControl.ZoomOut"]).toBe("Dézoomer");
    expect(options.locale?.["Map.Title"]).toBe("Carte");
    expect(Object.values(FR_LOCALE).some((v) => /zoom in|zoom out|\bmap\b/i.test(v))).toBe(false);
  });

  it("le nord reste en haut : ni rotation ni inclinaison (aucune boussole pour y revenir)", () => {
    const options = mapOptions(host, LILLE, { dark: false }, ORIGIN);
    expect(options).toMatchObject({ dragRotate: false, pitchWithRotate: false, touchPitch: false });
    createBaseMap(fakeLib, host, LILLE, { dark: false, base: ORIGIN });
    expect(FakeMap.last.unrotated).toEqual(["doigts", "clavier"]);
  });

  it("une miniature : sans geste, sans commande, sans mention dessinée", () => {
    const options = mapOptions(host, LILLE, { dark: false, interactive: false, attribution: false, bounds: [6, 45, 7, 46] }, ORIGIN);
    expect(options.interactive).toBe(false);
    expect(options.attributionControl).toBe(false);
    expect(options.bounds).toEqual([6, 45, 7, 46]);
    createBaseMap(fakeLib, host, LILLE, { dark: false, interactive: false, base: ORIGIN });
    expect(FakeMap.last.controls).toEqual([]);
  });
});

describe("une carte ouverte suit la carte du serveur", () => {
  it("une autre carte relue se repose sur elle, et le thème suivant la garde", () => {
    const map = createBaseMap(fakeLib, host, LILLE, { dark: false, base: ORIGIN });
    const fake = FakeMap.last;
    expect(fake.controls).toHaveLength(1); // les boutons de zoom
    const wider: MapInfo = { ...LILLE, bounds: [-10, 35, 20, 60], tiles: "/api/moi/phone/map/tiles/{z}/{x}/{y}?v=ffffffffffff" };
    map.restyle(wider);
    expect(fake.styles).toHaveLength(2);
    expect((fake.styles[1].sources.carte as { bounds: number[] }).bounds).toEqual([-10, 35, 20, 60]);
    map.theme(true);
    expect(fake.styles).toHaveLength(3);
    expect((fake.styles[2].sources.carte as { tiles: string[] }).tiles[0]).toContain("v=ffffffffffff"); // la nouvelle, en sombre
    expect(String(fake.styles[2].sprite)).toMatch(/\/dark$/);
    expect(map.info).toBe(wider);
    map.restyle({ ...wider }); // la même : rien à reposer
    expect(fake.styles).toHaveLength(3);
  });

  it("des polices ajoutées (mika carte polices) : ses noms paraissent", () => {
    const map = createBaseMap(fakeLib, host, { ...LILLE, glyphs: null, sprite: null }, { dark: false, base: ORIGIN });
    const fake = FakeMap.last;
    expect(fake.styles[0].glyphs).toBeUndefined();
    map.restyle(LILLE);
    expect(fake.styles[1].glyphs).toContain("/fonts/");
  });

  it("ce qui est par-dessus se repose à chaque style", () => {
    let laid = 0;
    const map = createBaseMap(fakeLib, host, LILLE, { dark: false, base: ORIGIN, overlay: () => (laid += 1) });
    FakeMap.last.fire("style.load");
    map.theme(true);
    expect(laid).toBe(2);
  });

  it("la clé d'une carte servie change avec ses adresses (sa version)", () => {
    expect(infoKey(LILLE)).toBe(infoKey({ ...LILLE }));
    expect(infoKey(LILLE)).not.toBe(infoKey({ ...LILLE, tiles: "/api/moi/phone/map/tiles/{z}/{x}/{y}?v=000000000000" }));
  });
});

describe("des tuiles qui échouent de suite font revenir le plan dessiné", () => {
  it("une série d'échecs, sans tuile lue entre deux : la carte le dit, une fois", () => {
    let failed = 0;
    createBaseMap(fakeLib, host, LILLE, { dark: false, base: ORIGIN, onFail: () => (failed += 1) });
    const fake = FakeMap.last;
    const tileError = { sourceId: "carte", tile: {}, error: { status: 503 } };
    fake.fire("error", tileError);
    fake.fire("error", tileError);
    fake.fire("sourcedata", { sourceId: "carte", tile: {} }); // une tuile lue : la série repart de zéro
    fake.fire("error", tileError);
    fake.fire("error", tileError);
    fake.fire("error", tileError);
    expect(failed).toBe(0);
    fake.fire("error", tileError);
    expect(failed).toBe(1);
    fake.fire("error", tileError);
    expect(failed).toBe(1);
  });

  it("une police ou une planche d'icônes qui manque ne compte pas", () => {
    let failed = 0;
    createBaseMap(fakeLib, host, LILLE, { dark: false, base: ORIGIN, onFail: () => (failed += 1) });
    const fake = FakeMap.last;
    for (let i = 0; i < 10; i++) fake.fire("error", { error: new Error("glyphs") });
    for (let i = 0; i < 10; i++) fake.fire("error", { sourceId: "lignes", tile: {} });
    expect(failed).toBe(0);
  });

  it("une autre carte servie recommence le compte", () => {
    const watch = new TileWatch(2);
    expect(watch.error()).toBe(false);
    expect(watch.error()).toBe(true);
    expect(watch.error()).toBe(false);
    watch.reset();
    expect(watch.error()).toBe(false);
    expect(watch.error()).toBe(true);
  });
});
