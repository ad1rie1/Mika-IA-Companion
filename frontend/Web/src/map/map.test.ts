import { afterEach, describe, expect, it, vi } from "vitest";
import { layers as protomapsLayers, namedFlavor } from "@protomaps/basemaps";
// le lecteur de styles de MapLibre lui-même (sa dépendance) : il dit si un filtre est valide et ce qu'il garde
import { featureFilter, validateStyleMin } from "@maplibre/maplibre-gl-style-spec";
import type { FilterSpecification, LayerSpecification, MapOptions, StyleSpecification } from "maplibre-gl";
import { fetchMap, type MapInfo } from "../api/carte";
import { absoluteBase, blankImage, createBaseMap, FR_LOCALE, mapOptions, TileWatch, transformFor, type MapLib } from "./base";
import { infoKey } from "./info";
import { boundsOf, circle, covers, coversAll, meters, widened, zoomFor, type Bounds } from "./mapgeo";
import { attributionText } from "./cards";
import { drawnScene } from "./drawn";
import { LiveMap, liveWanted, planWhy, type LiveHooks } from "./live";
import type { loadMapView } from "./load";
import { mapStyle, POIS_LAYER, QUIET_POIS } from "./mapstyle";
import { cleanScene, EMPTY_SCENE, hereSpan, sceneBounds, sceneFraming, type Scene } from "./scene";
import { hereFocus, hereGeoJson, MapView, pinClass, pinRank } from "./view";

const ORIGIN = "http://127.0.0.1:8013";
const LILLE: MapInfo = {
  ready: true,
  reason: "",
  kind: "vecteur",
  minzoom: 0,
  maxzoom: 15,
  bounds: [-5.2, 41.3, 9.6, 51.1],
  attribution: "© OpenStreetMap",
  tiles: "/api/moi/carte/fond/tiles/{z}/{x}/{y}?v=1a2b3c4d5e6f",
  glyphs: "/api/moi/carte/fond/fonts/{fontstack}/{range}.pbf?v=1a2b3c4d5e6f",
  sprite: "/api/moi/carte/fond/sprites/~1a2b3c4d5e6f/v4",
};

/** Un faux MapLibre : ce qu'on lui demande (styles posés, commandes), et des événements qu'on déclenche. */
class FakeMap {
  static last: FakeMap;
  /** Combien de cartes ont été créées. */
  static made = 0;
  readonly handlers = new Map<string, Array<(e: unknown) => void>>();
  readonly styles: StyleSpecification[] = [];
  readonly controls: Array<[unknown, string]> = [];
  /** Les gestes qui ne tournent plus la carte. */
  readonly unrotated: string[] = [];
  readonly touchZoomRotate = { disableRotation: () => this.unrotated.push("doigts") };
  readonly keyboard = { disableRotation: () => this.unrotated.push("clavier") };
  /** Les images ajoutées au style en cours (un autre style les perd, comme dans MapLibre), et chaque ajout. */
  readonly images = new Map<string, unknown>();
  readonly added: Array<[string, unknown]> = [];
  /** Chaque cadrage demandé : une zone (`fitBounds`), un centre et un zoom (`easeTo`). */
  readonly fits: Array<[unknown, Record<string, unknown>]> = [];
  readonly eases: Array<Record<string, unknown>> = [];
  /** Les sources et les calques posés par-dessus le style en cours (un autre style les perd, comme dans MapLibre). */
  readonly sources = new Map<string, { data: unknown; setData(data: unknown): void }>();
  readonly layers: Array<Record<string, unknown>> = [];
  removed = false;

  constructor(readonly options: MapOptions) {
    FakeMap.last = this;
    FakeMap.made += 1;
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
    this.images.clear();
    this.sources.clear();
    this.layers.length = 0;
    this.fire("style.load");
    return this;
  }

  hasImage(id: string): boolean {
    return this.images.has(id);
  }

  addImage(id: string, image: unknown): this {
    this.images.set(id, image);
    this.added.push([id, image]);
    return this;
  }

  fitBounds(bounds: unknown, options: Record<string, unknown>): this {
    this.fits.push([bounds, options]);
    return this;
  }

  easeTo(options: Record<string, unknown>): this {
    this.eases.push(options);
    return this;
  }

  /** Une source de la vue : là si elle a été posée sur ce style (sinon le style se charge encore). */
  getSource(id: string): { data: unknown; setData(data: unknown): void } | undefined {
    return this.sources.get(id);
  }

  addSource(id: string, spec: { data: unknown }): this {
    this.sources.set(id, {
      data: spec.data,
      setData(data: unknown) {
        this.data = data;
      },
    });
    return this;
  }

  addLayer(layer: Record<string, unknown>): this {
    this.layers.push(layer);
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
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("se lit avec la carte, et non sous le téléphone (ADR 0229)", async () => {
    const asked: string[] = [];
    vi.stubGlobal("fetch", async (url: string) => {
      asked.push(url);
      return new Response(JSON.stringify(LILLE), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    expect(await fetchMap()).toEqual(LILLE);
    expect(asked).toHaveLength(1);
    expect(asked[0]).toMatch(/\/api\/moi\/carte\/fond$/);
  });

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
    expect(style.glyphs).toBe(`${ORIGIN}/api/moi/carte/fond/fonts/{fontstack}/{range}.pbf?v=1a2b3c4d5e6f`);
    expect(style.sprite).toBe(`${ORIGIN}/api/moi/carte/fond/sprites/~1a2b3c4d5e6f/v4/light`);
    expect(mapStyle(LILLE, true, ORIGIN).sprite).toBe(`${ORIGIN}/api/moi/carte/fond/sprites/~1a2b3c4d5e6f/v4/dark`);
    expect(style.sources.carte).toMatchObject({ type: "vector", tiles: [`${ORIGIN}/api/moi/carte/fond/tiles/{z}/{x}/{y}?v=1a2b3c4d5e6f`], maxzoom: 15 });
  });

  it("sans polices, ses noms s'effacent ; sans icônes, ses symboles aussi", () => {
    const bare = mapStyle({ ...LILLE, glyphs: null, sprite: null }, false, ORIGIN);
    expect(bare.glyphs).toBeUndefined();
    expect(bare.sprite).toBeUndefined();
    const layouts = bare.layers.map((l) => ("layout" in l ? (l.layout as Record<string, unknown> | undefined) : undefined) ?? {});
    expect(layouts.some((l) => "text-field" in l || "icon-image" in l)).toBe(false);
    expect(bare.layers.length).toBeGreaterThan(10); // l'eau, les routes, les bâtiments restent
  });

  it("au zoom d'une rue, les étoiles « Immeuble » et « Maison » s'en vont ; les vraies attractions restent", () => {
    const style = mapStyle(LILLE, true, ORIGIN);
    expect(validateStyleMin(style)).toEqual([]); // un style que MapLibre accepte
    const pois = style.layers.find((l) => l.id === POIS_LAYER) as LayerSpecification & { filter: FilterSpecification };
    const shown = featureFilter(pois.filter);
    // tels que les tuiles servies les portent, au centre de Lille (sorte, nom, zoom d'apparition)
    const at16 = (properties: Record<string, unknown>) => shown.filter({ zoom: 16 }, { type: 1, properties });
    for (const name of ["Immeuble", "Immeubles", "Maison", "Maisons", "Hôtel particulier", "Ancien hôtel"]) {
      expect(at16({ kind: "attraction", name, min_zoom: 16 })).toBe(false);
    }
    expect(at16({ kind: "attraction", name: "Maison", "name:fr": "Maison", min_zoom: 16 })).toBe(false);
    expect(at16({ kind: "attraction", min_zoom: 16 })).toBe(false); // une étoile sans nom
    expect(at16({ kind: "attraction", name: "Vieille Bourse", min_zoom: 14 })).toBe(true);
    expect(at16({ kind: "attraction", name: "Maison Meert", min_zoom: 15 })).toBe(true);
    expect(at16({ kind: "attraction", name: "Hôtel de Lamissart", min_zoom: 16 })).toBe(true);
    expect(at16({ kind: "attraction", name: "Beffroi de la Bourse", min_zoom: 16 })).toBe(true);
    expect(at16({ kind: "theatre", name: "Opéra de Lille", min_zoom: 13 })).toBe(true);
    expect(at16({ kind: "restaurant", name: "Maison", min_zoom: 16 })).toBe(true); // seule l'attraction est filtrée
    expect(at16({ kind: "artwork", min_zoom: 16 })).toBe(true);
    // le zoom d'apparition de Protomaps tient toujours
    expect(shown.filter({ zoom: 15 }, { type: 1, properties: { kind: "attraction", name: "Beffroi de la Bourse", min_zoom: 16 } })).toBe(false);
  });

  it("seul le calque des points d'intérêt change : les autres restent ceux de Protomaps", () => {
    for (const dark of [false, true]) {
      const original = protomapsLayers("carte", namedFlavor(dark ? "dark" : "light"), { lang: "fr" }) as LayerSpecification[];
      const style = mapStyle(LILLE, dark, ORIGIN);
      expect(style.layers.map((l) => l.id)).toEqual(original.map((l) => l.id));
      for (const layer of original) {
        const got = style.layers.find((l) => l.id === layer.id) as LayerSpecification & { filter?: unknown };
        if (layer.id !== POIS_LAYER) {
          expect(got).toEqual(layer);
          continue;
        }
        const { filter, ...rest } = got;
        const { filter: before, ...restBefore } = layer as LayerSpecification & { filter?: unknown };
        expect(rest).toEqual(restBefore); // ses icônes, ses noms, ses couleurs
        expect(filter).toEqual(["all", before, ["!", QUIET_POIS]]);
      }
    }
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
    expect(tiles).toBe("http://192.168.1.22/api/moi/carte/fond/tiles/{z}/{x}/{y}?v=1a2b3c4d5e6f"); // `{z}` intact
    expect(style.glyphs).toBe("http://192.168.1.22/api/moi/carte/fond/fonts/{fontstack}/{range}.pbf?v=1a2b3c4d5e6f");
    expect(String(style.sprite).startsWith("http://192.168.1.22/api/moi/")).toBe(true);
  });

  it("garde une base absolue telle quelle, et un préfixe de chemin", () => {
    expect(absoluteBase("http://localhost:8001/", "http://localhost:4173")).toBe("http://localhost:8001");
    expect(absoluteBase("/mika", "https://maison.example")).toBe("https://maison.example/mika");
  });

  it("ne demande avec la session que ce qui va à ce serveur", () => {
    const transform = transformFor("http://192.168.1.22");
    expect(transform("http://192.168.1.22/api/moi/carte/fond/tiles/3/4/2")).toEqual({ url: "http://192.168.1.22/api/moi/carte/fond/tiles/3/4/2", credentials: "include" });
    expect(transform("http://192.168.1.220/x")).toEqual({ url: "http://192.168.1.220/x" });
    const options = mapOptions(host, LILLE, { dark: false }, "http://192.168.1.22");
    const asked = options.transformRequest?.("http://192.168.1.22/api/moi/carte/fond/fonts/a/0-255.pbf", "Glyphs" as never);
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
    const wider: MapInfo = { ...LILLE, bounds: [-10, 35, 20, 60], tiles: "/api/moi/carte/fond/tiles/{z}/{x}/{y}?v=ffffffffffff" };
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
    expect(infoKey(LILLE)).not.toBe(infoKey({ ...LILLE, tiles: "/api/moi/carte/fond/tiles/{z}/{x}/{y}?v=000000000000" }));
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

describe("une icône qui manque à la planche", () => {
  it("une icône que la planche n'a pas reçoit une image vide, une fois par style ; son nom reste", () => {
    const map = createBaseMap(fakeLib, host, LILLE, { dark: false, base: ORIGIN });
    const fake = FakeMap.last;
    fake.fire("styleimagemissing", { id: "townhall" });
    fake.fire("styleimagemissing", { id: "townhall" });
    expect(fake.added.map(([id]) => id)).toEqual(["townhall"]);
    const image = fake.added[0][1] as ReturnType<typeof blankImage>;
    expect(image).toMatchObject({ width: 1, height: 1 });
    expect([...image.data]).toEqual([0, 0, 0, 0]); // transparente
    map.theme(true); // un autre style perd ses images : il la redemande, elle revient
    fake.fire("styleimagemissing", { id: "townhall" });
    expect(fake.added.map(([id]) => id)).toEqual(["townhall", "townhall"]);
  });
});

/** Le zoom où MapLibre pose une zone dans une carte de `width` × `height` px (tuiles de 512 px, Mercator), marges ôtées, plafonné. */
function fittedZoom(b: Bounds, width: number, height: number, f: { padding: number; maxZoom: number }): number {
  const x = (lon: number) => (lon + 180) / 360;
  const y = (lat: number) => (1 - Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)) / Math.PI) / 2;
  const zx = Math.log2((width - 2 * f.padding) / (512 * (x(b[2]) - x(b[0]))));
  const zy = Math.log2((height - 2 * f.padding) / (512 * (y(b[1]) - y(b[3]))));
  return Math.min(f.maxZoom, zx, zy);
}

/** Trente cafés à 20-40 m de sa position, au centre de Lille (la capture adrien-16 de l'audit). */
const HERE = { lat: 50.6365, lon: 3.0635 };
const CAFES: Scene = {
  pins: Array.from({ length: 30 }, (_, i) => {
    const r = 20 + (i % 5) * 5;
    const a = (i * 2 * Math.PI) / 30;
    return { id: `c${i}`, lat: HERE.lat + (r * Math.cos(a)) / 111_195, lon: HERE.lon + (r * Math.sin(a)) / (111_195 * Math.cos((HERE.lat * Math.PI) / 180)) };
  }),
  lines: [],
  here: HERE,
};
/** L'écran Carte à 1440 px : la carte à côté de la colonne de 380 px. */
const CARTE_W = 1060;
const CARTE_H = 760;

describe("le cadrage d'une scène (F3-18)", () => {
  it("des lieux serrés se départagent sur l'écran Carte : trente cafés dans 40 m, au-delà du zoom 16", () => {
    const framed = sceneFraming(CAFES, true);
    expect(framed).not.toBeNull();
    expect(fittedZoom(framed!.bounds, CARTE_W, CARTE_H, framed!)).toBeGreaterThan(16);
    expect(framed!.maxZoom).toBe(17);
  });

  it("une miniature garde son quartier autour : son élargissement et son plafond ne changent pas", () => {
    const framed = sceneFraming(CAFES, false);
    expect(framed).toMatchObject({ padding: 18, maxZoom: 12.5 });
    expect(framed!.bounds).toEqual(sceneBounds(CAFES)); // l'élargissement d'avant (0,02°)
    expect(framed!.bounds[2] - framed!.bounds[0]).toBeCloseTo(0.02, 6);
    expect(fittedZoom(framed!.bounds, 340, 150, framed!)).toBeLessThanOrEqual(12.5);
  });

  it("une scène étendue se cadre comme avant : sa zone telle quelle, loin du plafond", () => {
    const scene: Scene = { pins: [{ id: "lille", lat: 50.6365, lon: 3.0635 }, { id: "annecy", lat: 45.8992, lon: 6.1294 }], lines: [] };
    const framed = sceneFraming(scene, true)!;
    expect(framed.bounds).toEqual([3.0635, 45.8992, 6.1294, 50.6365]);
    expect(framed.bounds).toEqual(sceneBounds(scene));
    // ni l'ancien plafond (14) ni le nouveau (17) ne jouent
    expect(fittedZoom(framed.bounds, CARTE_W, CARTE_H, framed)).toBeLessThan(14);
    expect(sceneFraming(EMPTY_SCENE, true)).toBeNull();
  });
});

describe("la vue cadre ce qu'on lui demande (F3-18)", () => {
  /** Un tracé de 40 m dans Lille : une scène sans épingle, que la vue pose sans DOM. */
  const SHORT: Scene = { pins: [], lines: [{ points: [[50.6365, 3.0635], [50.6368, 3.0638]] }] };
  const ANNECY: Scene = { pins: [], lines: [{ points: [[45.8992, 6.1294], [45.85, 6.2]] }] };

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function view(scene: Scene, interactive = true, info: MapInfo = LILLE): { view: MapView; fake: FakeMap } {
    vi.stubGlobal("location", { origin: ORIGIN });
    const v = new MapView(fakeLib, host, info, scene, { dark: false, interactive });
    return { view: v, fake: FakeMap.last };
  }

  it("à l'ouverture : l'écran Carte serré jusqu'au zoom 17, une miniature comme avant", () => {
    const { fake } = view(SHORT);
    const opened = fake.options as MapOptions & { bounds: Bounds; fitBoundsOptions: Record<string, unknown> };
    expect(opened.fitBoundsOptions).toEqual({ padding: 56, maxZoom: 17 });
    expect(opened.bounds[2] - opened.bounds[0]).toBeCloseTo(0.002, 6);
    const mini = view(SHORT, false).fake.options as MapOptions & { bounds: Bounds; fitBoundsOptions: Record<string, unknown> };
    expect(mini.fitBoundsOptions).toEqual({ padding: 18, maxZoom: 12.5 });
    expect(mini.bounds[2] - mini.bounds[0]).toBeCloseTo(0.02, 6);
  });

  it("un cadrage demandé se fait même quand la scène n'a pas changé (une recherche relancée) ; sans demande, rien", () => {
    const { view: v, fake } = view(SHORT);
    v.show(SHORT, false);
    expect(fake.fits).toHaveLength(0);
    v.show({ ...SHORT }, true); // la même scène, un cadrage demandé
    expect(fake.fits).toHaveLength(1);
    expect(fake.fits[0][1]).toMatchObject({ padding: 56, maxZoom: 17 });
    v.show(ANNECY, false); // une autre scène, sans demande : posée, pas cadrée
    expect(fake.fits).toHaveLength(1);
  });

  it("une scène vide attend (un regard qui se lit encore) ; demandée sur le fond (un regard en échec), elle y revient", () => {
    const { view: v, fake } = view(ANNECY);
    v.show(EMPTY_SCENE, true);
    expect(fake.fits).toHaveLength(0); // le lac d'Annecy reste, le temps que le regard se lise
    v.show(EMPTY_SCENE, true, true);
    expect(fake.fits).toHaveLength(1);
    expect(fake.fits[0][0]).toEqual(LILLE.bounds); // la zone de la carte du serveur
    // une carte du serveur sans zone (un serveur {z}/{x}/{y}) : la France
    const open = view(ANNECY, true, { ...LILLE, bounds: null });
    open.view.show(EMPTY_SCENE, true, true);
    expect(open.fake.fits).toHaveLength(0);
    expect(open.fake.eases).toEqual([{ center: [2.35, 46.6], zoom: 5, duration: 600 }]);
  });
});

describe("les lieux de « Sur la route » : des épingles secondaires (F3-13)", () => {
  /** Ce qu'une épingle pose dans la page, sans DOM : ses classes, son texte, sa cible. */
  interface FakeEl {
    tag: string;
    className: string;
    textContent: string;
    title: string;
    type?: string;
    dataset: Record<string, string>;
    attrs: Record<string, string>;
    setAttribute(name: string, value: string): void;
  }

  class FakeMarker {
    static placed: FakeMarker[] = [];
    constructor(readonly options: { element: FakeEl }) {}
    setLngLat(): this {
      return this;
    }
    addTo(): this {
      FakeMarker.placed.push(this);
      return this;
    }
    remove(): void {}
  }

  const STOPS: Scene = {
    pins: [{ id: "1", lat: 50.637, lon: 3.063, label: "1", title: "Lille" }, { id: "2", lat: 49.258, lon: 4.032, label: "2", mika: true, title: "Reims" }],
    lines: [{ points: [[50.637, 3.063], [49.258, 4.032]], straight: true }],
  };
  const ALONG = { id: "along:0", lat: 50.1, lon: 3.5, minor: true, label: "9", title: "Camping de la Vallée · jour 1" };

  afterEach(() => {
    vi.unstubAllGlobals();
    FakeMarker.placed = [];
  });

  it("une épingle secondaire : plus petite, sans numéro, d'un autre style que les arrêts, sous eux", () => {
    expect(pinClass(ALONG)).toBe("cm-pin-el minor");
    expect(pinClass(STOPS.pins[0])).toBe("cm-pin-el");
    expect(pinClass(STOPS.pins[1])).toBe("cm-pin-el mika");
    expect(pinClass({ id: "x", lat: 1, lon: 1 })).toBe("cm-pin-el dot");
    expect(pinRank(ALONG)).toBeLessThan(pinRank(STOPS.pins[0]));
    expect(pinRank(STOPS.pins[0])).toBeLessThan(pinRank(STOPS.pins[1]));
  });

  it("la vraie carte les pose sous les arrêts, sans numéro, avec leur cible ; leur arrivée ne la recadre pas", () => {
    vi.stubGlobal("location", { origin: ORIGIN });
    vi.stubGlobal("document", {
      createElement: (tag: string): FakeEl => ({
        tag, className: "", textContent: "", title: "", dataset: {}, attrs: {},
        setAttribute(name: string, value: string) {
          this.attrs[name] = value;
        },
      }),
    });
    const lib = { ...fakeLib, Marker: FakeMarker } as unknown as MapLib;
    const v = new MapView(lib, host, LILLE, STOPS, { dark: false, interactive: true });
    const fake = FakeMap.last;
    FakeMarker.placed = [];
    v.show({ ...STOPS, pins: [...STOPS.pins, ALONG] }, false); // « Sur la route » vient d'arriver : `fitNext` est faux
    expect(fake.fits).toHaveLength(0);
    const els = FakeMarker.placed.map((m) => m.options.element);
    expect(els.map((e) => e.className)).toEqual(["cm-pin-el minor", "cm-pin-el", "cm-pin-el mika"]);
    expect(els[0]).toMatchObject({ tag: "button", textContent: "", title: "Camping de la Vallée · jour 1", dataset: { pin: "along:0" } });
    expect(els[1].textContent).toBe("1");
  });

  it("le plan dessiné les montre aussi, petites et sans numéro, sous les arrêts", () => {
    const svg = drawnScene({ ...STOPS, pins: [...STOPS.pins, ALONG] }, { width: 800, height: 560, title: "Le voyage" });
    expect(svg).toMatch(/<g class="dm-pin minor"><circle [^>]*r="3.5"\/><\/g>/);
    expect(svg).not.toContain(">9</text>"); // son `label` ne se dessine pas
    expect(svg.indexOf('class="dm-pin minor"')).toBeLessThan(svg.indexOf('class="dm-pin"'));
    expect(svg).toContain('<g class="dm-pin mika">');
  });
});

describe("la position et le cercle de sa précision (F3-08)", () => {
  const LAT = 50.6365;
  const LON = 3.0635;
  /** Un degré de latitude, en mètres. */
  const DEG = 111_195;
  const alone = (accuracy_m?: number): Scene => ({ pins: [], lines: [], here: { lat: LAT, lon: LON, accuracy_m } });
  const accR = (svg: string) => Number(svg.match(/<circle class="dm-here-acc" [^>]*r="([\d.]+)"\/>/)?.[1] ?? NaN);

  it("une scène garde un rayon fini et positif, et laisse tomber les autres", () => {
    expect(cleanScene(alone(30)).here).toEqual({ lat: LAT, lon: LON, accuracy_m: 30 });
    for (const bad of [0, -5, Number.NaN, Number.POSITIVE_INFINITY, "12" as unknown as number]) {
      expect(cleanScene(alone(bad)).here).toEqual({ lat: LAT, lon: LON });
    }
    const plain: Scene = { pins: [], lines: [], here: { lat: LAT, lon: LON } };
    expect(cleanScene(plain).here).toBe(plain.here); // sans rayon : la position telle quelle
  });

  it("la zone de la scène tient le cercle : la position ± son rayon", () => {
    const [w, s, e, n] = sceneBounds(alone(500), 0)!;
    expect((n - s) * DEG).toBeCloseTo(1000, 0);
    expect((n + s) / 2).toBeCloseTo(LAT, 9);
    expect((e - w) * DEG * Math.cos((LAT * Math.PI) / 180)).toBeCloseTo(1000, 0);
    // avec des épingles, le cercle compte aussi : une épingle à 100 m au nord, un cercle de 500 m
    const withPin: Scene = { ...alone(500), pins: [{ id: "a", lat: LAT + 100 / DEG, lon: LON }] };
    expect(sceneBounds(withPin, 0)).toEqual(sceneBounds(alone(500), 0));
    expect(hereSpan(withPin)).toBeUndefined(); // une scène à épingles se cadre comme avant
  });

  it("une scène sans rayon ne change pas : le point seul, le quartier autour", () => {
    const plain: Scene = { pins: [], lines: [], here: { lat: LAT, lon: LON } };
    expect(sceneBounds(plain)).toEqual(widened([LON, LAT, LON, LAT]));
    expect(hereSpan(plain)).toBeUndefined();
    const svg = drawnScene(plain, { width: 800, height: 560, title: "Ta position" });
    expect(svg).not.toContain("dm-here-acc");
    expect(svg).toContain('<circle class="dm-here-halo" cx="400.0" cy="280.0" r="10"/><circle class="dm-here" cx="400.0" cy="280.0" r="4.5"/>');
  });

  it("le plan trace le cercle à son échelle ; une position seule se montre sur quelques fois son rayon, 300 m au moins", () => {
    // 12 m : le plan couvre 300 m en hauteur (560 - 2 × 18 = 524 unités), le cercle n'est pas un point
    const small = drawnScene(alone(12), { width: 800, height: 560, title: "Plan autour de rue Nationale, Lille" });
    expect(small).toContain('aria-label="Plan autour de rue Nationale, Lille"');
    expect(accR(small)).toBeCloseTo((12 / 300) * 524, 0);
    expect(small).toMatch(/<circle class="dm-here-acc" cx="400\.0" [^>]*\/><circle class="dm-here-halo" cx="400\.0"/);
    expect(hereSpan(alone(12))! * DEG).toBeCloseTo(300, 6);
    // 200 m : le plan couvre cinq fois son rayon, le cercle (400 m de large) en prend les deux cinquièmes
    expect(accR(drawnScene(alone(200), { width: 800, height: 560, title: "" }))).toBeCloseTo((200 / 1000) * 524, 0);
    // avec des épingles, le cercle se pose à l'échelle de leur zone, sous elles
    const withPins: Scene = { ...alone(200), pins: [{ id: "a", lat: LAT + 0.01, lon: LON }, { id: "b", lat: LAT - 0.01, lon: LON }] };
    const svg = drawnScene(withPins, { width: 800, height: 560, title: "" });
    expect(accR(svg)).toBeCloseTo((200 / (0.02 * DEG)) * 524, 0);
    expect(svg.indexOf("dm-here-acc")).toBeLessThan(svg.indexOf("dm-pin"));
  });
});

/** Ce qu'une vue pose dans la page, sans DOM : un élément et ses classes. */
interface PlainEl {
  tag: string;
  className: string;
  textContent: string;
  title: string;
  dataset: Record<string, string>;
  attrs: Record<string, string>;
  setAttribute(name: string, value: string): void;
}

/** Un faux repère de MapLibre : ce qu'il porte, et où il est posé. */
class PlacedMarker {
  static placed: PlacedMarker[] = [];
  at: unknown = null;
  constructor(readonly options: { element: PlainEl }) {}
  setLngLat(at: unknown): this {
    this.at = at;
    return this;
  }
  addTo(): this {
    PlacedMarker.placed.push(this);
    return this;
  }
  remove(): void {}
}

/** La page sans DOM : le thème (clair), ses couleurs (`--accent` : `accent.value`), des éléments. */
function stubPage(accent = { value: "#4f46e5" }): void {
  vi.stubGlobal("location", { origin: ORIGIN });
  vi.stubGlobal("document", {
    documentElement: { dataset: {} },
    createElement: (tag: string): PlainEl => ({
      tag, className: "", textContent: "", title: "", dataset: {}, attrs: {},
      setAttribute(name: string, value: string) {
        this.attrs[name] = value;
      },
    }),
  });
  vi.stubGlobal("getComputedStyle", () => ({ getPropertyValue: (name: string) => (name === "--accent" ? ` ${accent.value} ` : "") }));
}

const markerLib = { ...fakeLib, Marker: PlacedMarker } as unknown as MapLib;

describe("la position sur la vraie carte : le cercle de sa précision, et une position seule centrée (F3-09)", () => {
  const LAT = 50.6365;
  const LON = 3.0635;
  const alone = (accuracy_m?: number, lat = LAT, lon = LON): Scene => ({ pins: [], lines: [], here: { lat, lon, accuracy_m } });

  afterEach(() => {
    vi.unstubAllGlobals();
    PlacedMarker.placed = [];
  });

  it("une position seule et sa précision s'ouvre centrée, au zoom de son cercle, et non par fitBounds", () => {
    stubPage();
    new MapView(markerLib, host, LILLE, alone(12), { dark: false, interactive: true });
    const opened = FakeMap.last.options as MapOptions & { bounds?: Bounds };
    expect(opened.center).toEqual([LON, LAT]);
    expect(opened.zoom).toBe(zoomFor(12));
    expect(opened.bounds).toBeUndefined();
    new MapView(markerLib, host, LILLE, alone(2000), { dark: false, interactive: true });
    expect(FakeMap.last.options.zoom).toBe(zoomFor(2000)); // une précision large : plus loin
    expect(hereFocus(alone(12))).toEqual({ center: [LON, LAT], zoom: zoomFor(12) });
  });

  it("toute autre scène se cadre comme avant : une position sans rayon (« Autour de moi »), des épingles autour d'elle", () => {
    stubPage();
    expect(hereFocus(alone())).toBeNull();
    new MapView(markerLib, host, LILLE, alone(), { dark: false, interactive: true });
    expect(FakeMap.last.options).toMatchObject({ fitBoundsOptions: { padding: 56, maxZoom: 17 } });
    const withPin: Scene = { ...alone(200), pins: [{ id: "a", lat: LAT + 0.01, lon: LON }] };
    expect(hereFocus(withPin)).toBeNull();
    new MapView(markerLib, host, LILLE, withPin, { dark: false, interactive: true });
    expect((FakeMap.last.options as MapOptions & { bounds: Bounds }).bounds).toEqual(sceneFraming(withPin, true)!.bounds);
  });

  it("une position qui bouge se recentre quand on le demande, au zoom où on l'a laissée ; sans demande, elle reste", () => {
    stubPage();
    const v = new MapView(markerLib, host, LILLE, alone(12), { dark: false, interactive: true });
    const fake = FakeMap.last;
    v.show(alone(12, LAT + 0.001), false);
    expect(fake.eases).toEqual([]);
    v.show(alone(12, LAT + 0.002), true);
    expect(fake.eases).toEqual([{ center: [LON, LAT + 0.002], duration: 600 }]); // pas de zoom : celui qu'on a laissé
    expect(fake.fits).toEqual([]);
  });

  it("le cercle se pose rempli et bordé, aux couleurs du thème, sous les tracés ; il se repose à chaque style", () => {
    const accent = { value: "#4f46e5" };
    stubPage(accent);
    const v = new MapView(markerLib, host, LILLE, alone(120), { dark: false, interactive: true });
    const fake = FakeMap.last;
    fake.fire("style.load");
    expect(fake.layers.map((l) => l.id)).toEqual(["ici-zone", "ici-bord", "lignes-bord", "lignes-trait", "lignes-droites"]);
    expect(fake.layers[0]).toMatchObject({ type: "fill", source: "ici", paint: { "fill-color": "#4f46e5" } });
    expect(fake.layers[1]).toMatchObject({ type: "line", source: "ici", paint: { "line-color": "#4f46e5" } });
    const ring = (fake.sources.get("ici")!.data as { features: Array<{ geometry: { coordinates: number[][][] } }> }).features[0].geometry.coordinates[0];
    expect(ring).toEqual(circle(LAT, LON, 120)); // le cercle de la précision, juste à tous les zooms
    // le thème sombre : un autre style, le cercle reposé à ses couleurs
    accent.value = "#a5b4fc";
    v.theme(true);
    expect(fake.layers[0]).toMatchObject({ id: "ici-zone", paint: { "fill-color": "#a5b4fc" } });
    // une autre précision : le même calque, son cercle suit
    v.show(alone(500), false);
    const wider = (fake.sources.get("ici")!.data as { features: Array<{ geometry: { coordinates: number[][][] } }> }).features[0].geometry.coordinates[0];
    expect(wider).toEqual(circle(LAT, LON, 500));
    expect(fake.layers.filter((l) => l.id === "ici-zone")).toHaveLength(1);
    // sa position : le point de la Carte, un repère
    const last = PlacedMarker.placed[PlacedMarker.placed.length - 1];
    expect(last.options.element.className).toBe("cm-here-el");
    expect(last.at).toEqual([LON, LAT]);
  });

  it("sans rayon, ni cercle ni calque vide qui gêne : sa source est vide", () => {
    expect(hereGeoJson(alone()).features).toEqual([]);
    expect(hereGeoJson(EMPTY_SCENE).features).toEqual([]);
    expect(hereGeoJson(alone(30)).features).toHaveLength(1);
  });
});

describe("une carte vivante, un seul cycle de vie pour la Carte et la Position (F3-09)", () => {
  const OTHER: MapInfo = { ...LILLE, tiles: "/api/moi/carte/fond/tiles/{z}/{x}/{y}?v=ffffffffffff" };
  const POSITION: Scene = { pins: [], lines: [], here: { lat: 50.6365, lon: 3.0635, accuracy_m: 12 } };
  const tileError = { sourceId: "carte", tile: {}, error: { status: 503 } };
  const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

  /** Un cadre de carte, dans un dessin de l'écran : ce qui s'y est reposé. */
  interface FakeSlot {
    lodged: unknown[];
    replaceWith(el: unknown): void;
  }
  const newSlot = (): FakeSlot => ({
    lodged: [],
    replaceWith(el: unknown) {
      this.lodged.push(el);
    },
  });

  /** Un écran qui montre une carte vivante : son cadre (aucun : le plan), s'il est encore là, ses redessins. */
  function screen(over: Partial<LiveHooks> = {}) {
    const state = { slot: newSlot() as FakeSlot | null, showing: true, repaints: 0, mounted: 0 };
    const kit = async () => ({ lib: markerLib, MapView });
    const live = new LiveMap({
      slot: () => state.slot as unknown as HTMLElement | null,
      showing: () => state.showing,
      repaint: () => (state.repaints += 1),
      scene: () => POSITION,
      options: { interactive: true },
      mounted: () => (state.mounted += 1),
      needsHere: true,
      load: kit as unknown as typeof loadMapView,
      ...over,
    });
    return { live, state };
  }

  afterEach(() => {
    vi.unstubAllGlobals();
    PlacedMarker.placed = [];
  });

  it("se montre quand la carte servie couvre ce que la scène montre ; une position, il faut qu'elle la couvre", () => {
    expect(liveWanted(LILLE, POSITION, false, true)).toBe(true);
    expect(liveWanted(LILLE, POSITION, true, true)).toBe(false); // refusée ici : le plan, pas une autre tentative
    expect(liveWanted(LILLE, EMPTY_SCENE, false, true)).toBe(false); // sans coordonnées : le plan vide
    expect(liveWanted(LILLE, { ...POSITION, here: { lat: 52.52, lon: 13.4 } }, false, true)).toBe(false); // hors de sa zone
    expect(liveWanted({ ready: false, reason: "aucune" }, POSITION, false, true)).toBe(false);
    expect(liveWanted(null, POSITION, false, true)).toBe(false);
    // l'écran Carte : une scène vide, le fond de carte ; des lieux, au moins un dans sa zone
    expect(liveWanted(LILLE, EMPTY_SCENE, false)).toBe(true);
    expect(liveWanted(LILLE, { pins: [{ id: "b", lat: 52.52, lon: 13.4 }], lines: [] }, false)).toBe(false);
    expect(liveWanted(LILLE, { pins: [{ id: "b", lat: 52.52, lon: 13.4 }, { id: "l", lat: 50.6, lon: 3.06 }], lines: [] }, false)).toBe(true);
  });

  it("dit en mots pourquoi un plan plutôt que la carte", () => {
    expect(planWhy(null, null, null)).toBe("la carte du serveur se lit…");
    expect(planWhy(null, new Error("x"), null)).toBe("Ça n'a pas abouti.");
    expect(planWhy({ ready: false, reason: "Aucune carte réglée." }, null, null)).toBe("Aucune carte réglée.");
    expect(planWhy({ ready: false, reason: "" }, null, "webgl")).toBe("aucune carte n'est réglée sur ce serveur.");
    expect(planWhy(LILLE, null, "tiles")).toBe("ses tuiles ne se lisent pas sur ce serveur en ce moment.");
    expect(planWhy(LILLE, null, "load")).toBe("elle n'a pas pu se charger : recharge la page.");
    expect(planWhy(LILLE, null, "webgl")).toBe("elle ne se dessine pas dans ce navigateur.");
    expect(planWhy(LILLE, null, null)).toBe("ces lieux sont hors de la zone qu'elle couvre.");
  });

  it("la vraie carte, servie par le serveur, prend la place du plan ; elle se garde d'un dessin à l'autre", async () => {
    stubPage();
    const { live, state } = screen();
    const before = FakeMap.made;
    expect(live.wanted(LILLE, POSITION)).toBe(true);
    expect(live.lodge(LILLE)).toBeNull(); // elle se monte : MapLibre se charge à part
    await flush();
    expect(FakeMap.made).toBe(before + 1);
    expect(live.view).not.toBeNull();
    expect(state.mounted).toBe(1);
    expect(FakeMap.last.options.container).toBe(state.slot); // dans le cadre du dessin
    expect(FakeMap.last.options.center).toEqual([3.0635, 50.6365]); // la Position : centrée sur elle
    // un autre dessin : la même vue, reposée dans le nouveau cadre, sans se refaire
    const first = live.view!;
    state.slot = newSlot();
    expect(live.lodge(LILLE)).toBe(first);
    expect(state.slot.lodged).toEqual([first.host]);
    expect(FakeMap.made).toBe(before + 1);
    expect(FakeMap.last.styles).toHaveLength(1);
  });

  it("une autre carte servie, relue pendant que la carte est ouverte, se repose sur elle ; la même se garde", async () => {
    stubPage();
    const { live } = screen();
    live.lodge(LILLE);
    await flush();
    const fake = FakeMap.last;
    expect(live.lodge(OTHER)).toBe(live.view);
    expect(fake.styles).toHaveLength(2);
    expect((fake.styles[1].sources.carte as { tiles: string[] }).tiles[0]).toContain("v=ffffffffffff");
    live.lodge(OTHER);
    expect(fake.styles).toHaveLength(2);
  });

  it("plus de cadre (le plan, un autre onglet) : la vue est rendue ; un montage en cours ne se pose pas", async () => {
    stubPage();
    const { live, state } = screen();
    live.lodge(LILLE);
    await flush();
    const fake = FakeMap.last;
    state.slot = null;
    expect(live.lodge(LILLE)).toBeNull();
    expect(fake.removed).toBe(true);
    expect(live.view).toBeNull();
    // un montage demandé, puis l'onglet quitté avant que MapLibre arrive : rien ne se pose
    const made = FakeMap.made;
    state.slot = newSlot();
    live.lodge(LILLE);
    live.drop();
    await flush();
    expect(FakeMap.made).toBe(made);
    // l'écran ne la montre plus quand MapLibre arrive : rien non plus
    live.lodge(LILLE);
    state.showing = false;
    await flush();
    expect(FakeMap.made).toBe(made);
  });

  it("seul le dernier montage demandé se pose", async () => {
    stubPage();
    const { live } = screen();
    const made = FakeMap.made;
    live.lodge(LILLE);
    live.lodge(OTHER); // un redessin pendant que MapLibre se charge, sur une autre carte servie (relue)
    await flush();
    // sans le jeton, le premier montage résolu (LILLE) se poserait, et le second s'arrêterait sur la vue déjà là
    expect(FakeMap.made).toBe(made + 1);
    const fake = FakeMap.last;
    expect((fake.styles[0].sources.carte as { tiles: string[] }).tiles[0]).toContain("v=ffffffffffff");
    live.lodge(OTHER); // c'est bien celle qu'elle dessine : le dessin suivant ne la repose pas
    expect(fake.styles).toHaveLength(1);
  });

  it("une carte qui n'a pas pu se dessiner ici (ses tuiles) : le plan revient avec sa note, sans réessayer ; une autre carte servie se réessaie", async () => {
    stubPage();
    const { live, state } = screen();
    live.lodge(LILLE);
    await flush();
    const fake = FakeMap.last;
    for (let i = 0; i < 4; i++) fake.fire("error", tileError);
    expect(state.repaints).toBe(1); // l'écran se redessine : le plan et sa note
    expect(fake.removed).toBe(true);
    expect(live.view).toBeNull();
    expect(live.wanted(LILLE, POSITION)).toBe(false); // chaque dessin suivant : le plan, pas une autre tentative
    expect(live.wanted(LILLE, POSITION)).toBe(false);
    expect(live.why(LILLE, null)).toBe("ses tuiles ne se lisent pas sur ce serveur en ce moment.");
    expect(live.wanted(OTHER, POSITION)).toBe(true); // une autre carte servie (relue) se réessaie
  });

  it("ses tuiles en échec après une autre carte servie : c'est celle-là qui est refusée", async () => {
    stubPage();
    const { live } = screen();
    live.lodge(LILLE);
    await flush();
    live.lodge(OTHER); // reposée sur une autre carte servie
    const fake = FakeMap.last;
    for (let i = 0; i < 4; i++) fake.fire("error", tileError);
    expect(live.wanted(OTHER, POSITION)).toBe(false);
  });

  it("MapLibre qui ne vient pas (un nouveau déploiement) : le plan, et ce qu'il faut faire", async () => {
    stubPage();
    const { live, state } = screen({ load: (() => Promise.reject(new Error("chunk"))) as unknown as typeof loadMapView });
    live.lodge(LILLE);
    await flush();
    expect(state.repaints).toBe(1);
    expect(live.wanted(LILLE, POSITION)).toBe(false);
    expect(live.why(LILLE, null)).toBe("elle n'a pas pu se charger : recharge la page.");
  });

  it("pas de WebGL : le plan, ici et pour toute autre carte, sans réessayer", async () => {
    stubPage();
    vi.resetModules(); // ce navigateur se retient pour toute la page (`load.ts`) : un module neuf pour ce test
    const fresh = await import("./live");
    const broken = { ...markerLib, Map: class { constructor() { throw new Error("WebGL"); } } } as unknown as MapLib;
    let repaints = 0;
    const live = new fresh.LiveMap({
      slot: () => newSlot() as unknown as HTMLElement,
      showing: () => true,
      repaint: () => (repaints += 1),
      scene: () => POSITION,
      options: { interactive: true },
      needsHere: true,
      load: (async () => ({ lib: broken, MapView })) as unknown as typeof loadMapView,
    });
    live.lodge(LILLE);
    await flush();
    expect(repaints).toBe(1);
    expect(live.wanted(LILLE, POSITION)).toBe(false);
    expect(live.wanted(OTHER, POSITION)).toBe(false); // ni une autre carte servie
    expect(live.why(OTHER, null)).toBe("elle ne se dessine pas dans ce navigateur.");
  });
});
