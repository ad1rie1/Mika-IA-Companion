/**
 * Une carte de l'écran Carte, de la Position du Téléphone, ou une miniature du chat (ADR 0194, 0196) : le fond du
 * serveur (`base.ts`), et par-dessus une scène (`scene.ts`) — des épingles numérotées (roses pour ce que Mika a fait),
 * des secondaires plus petites, des tracés, la position de la personne et le cercle de sa précision — que la vue cadre
 * (`fitBounds`, comme le dit `sceneFraming` : serrée sur l'écran Carte, un quartier autour sur une miniature). Une scène
 * qui n'a que la position et sa précision s'ouvre centrée sur elle, au zoom qui montre son cercle (`hereFocus`), et se
 * recentre quand on le lui demande, au zoom où on l'a laissée. Un cadrage demandé se fait même sur une scène inchangée ;
 * une scène vide garde la vue, sauf quand l'écran demande le fond de carte (un regard en échec). Le thème et une autre
 * carte du serveur se reposent sans la refaire. Son cycle de vie dans un écran (la monter, la reposer, ses échecs) :
 * `live.ts`.
 */
import type { FeatureCollection } from "geojson";
import type { GeoJSONSource, LngLatBoundsLike, Map as MapLibre, Marker } from "maplibre-gl";
import type { MapInfo } from "../api/carte";
import { createBaseMap, type BaseMap, type MapLib } from "./base";
import { circle, zoomFor, type Bounds } from "./mapgeo";
import { cleanScene, EMPTY_SCENE, framingFor, hereRadius, hereSpan, linesGeoJson, sceneFraming, sceneKey, type Scene, type ScenePin } from "./scene";

const LINES = "lignes";
/** La source du cercle de la précision de la position. */
const HERE = "ici";

export interface MapViewOptions {
  dark: boolean;
  /** Faux : une miniature (ni geste, ni commande, ni clic sur ses épingles). */
  interactive: boolean;
  /** Un clic sur une épingle (son `id`). */
  onPin?: (id: string) => void;
  /** Ses tuiles échouent de suite : la vue ne se dessinera pas. */
  onFail?: () => void;
  /** La carte a fini de bouger (la personne l'a déplacée). */
  onMove?: () => void;
}

/** Une couleur du thème (`base.css`), lue au moment de la poser. */
function token(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/** Les tracés d'une scène sur une carte dont le style est là : leur source se met à jour (sinon : rien encore). */
function setLines(map: MapLibre, scene: Scene): boolean {
  const source = map.getSource(LINES) as GeoJSONSource | undefined;
  if (!source) return false;
  source.setData(linesGeoJson(scene));
  return true;
}

function addLines(map: MapLibre, scene: Scene): void {
  if (setLines(map, scene)) return;
  const data = linesGeoJson(scene);
  map.addSource(LINES, { type: "geojson", data });
  const color = ["case", ["get", "mika"], token("--mika", "#db3f76"), token("--accent", "#4f46e5")];
  const routed = ["!", ["get", "straight"]];
  map.addLayer({ id: "lignes-bord", type: "line", source: LINES, filter: routed as never,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": token("--raised", "#ffffff"), "line-width": 7, "line-opacity": 0.9 } });
  map.addLayer({ id: "lignes-trait", type: "line", source: LINES, filter: routed as never,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": color as never, "line-width": 4 } });
  map.addLayer({ id: "lignes-droites", type: "line", source: LINES, filter: ["get", "straight"] as never,
    layout: { "line-cap": "round" },
    paint: { "line-color": color as never, "line-width": 2.5, "line-opacity": 0.75, "line-dasharray": [1.4, 2] } });
}

/** Le cercle de la précision de la position, en GeoJSON (lon, lat) ; sans position ou sans rayon : vide. */
export function hereGeoJson(scene: Scene): FeatureCollection {
  const here = scene.here;
  const r = hereRadius(here);
  return {
    type: "FeatureCollection",
    features: here && r ? [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [circle(here.lat, here.lon, r)] } }] : [],
  };
}

/** Le cercle d'une scène sur une carte dont le style est là : sa source se met à jour (sinon : rien encore). */
function setHere(map: MapLibre, scene: Scene): boolean {
  const source = map.getSource(HERE) as GeoJSONSource | undefined;
  if (!source) return false;
  source.setData(hereGeoJson(scene));
  return true;
}

/** Le cercle de la précision : rempli et bordé, aux couleurs du thème (lues à chaque style), sous les tracés. */
function addHere(map: MapLibre, scene: Scene): void {
  if (setHere(map, scene)) return;
  map.addSource(HERE, { type: "geojson", data: hereGeoJson(scene) });
  const accent = token("--accent", "#4f46e5");
  map.addLayer({ id: "ici-zone", type: "fill", source: HERE, paint: { "fill-color": accent, "fill-opacity": 0.14 } });
  map.addLayer({ id: "ici-bord", type: "line", source: HERE, paint: { "line-color": accent, "line-opacity": 0.5, "line-width": 1.5 } });
}

/**
 * Une scène qui n'a que la position et sa précision (la Position du Téléphone) : son centre et le zoom qui montre son
 * cercle en entier (`zoomFor`), comme elle s'est toujours ouverte, et non par `fitBounds`. Toute autre scène : `null`.
 */
export function hereFocus(scene: Scene): { center: [number, number]; zoom: number } | null {
  const here = scene.here;
  if (!here || hereSpan(scene) === undefined) return null;
  return { center: [here.lon, here.lat], zoom: zoomFor(hereRadius(here)) };
}

/**
 * Les classes d'une épingle (`carte.css`) : numérotée, rose pour ce que Mika a fait, choisie ; un point sans numéro ;
 * secondaire (`minor`, un lieu de « Sur la route ») : plus petite, sans numéro, d'un autre style que les arrêts.
 */
export function pinClass(pin: ScenePin): string {
  if (pin.minor) return `cm-pin-el minor${pin.selected ? " sel" : ""}`;
  return `cm-pin-el${pin.mika ? " mika" : ""}${pin.selected ? " sel" : ""}${pin.label ? "" : " dot"}`;
}

/** Ce qui se pose au-dessus de quoi : les secondaires dessous, puis les autres, les siennes, et la choisie en haut. */
export function pinRank(pin: ScenePin): number {
  return pin.selected ? 3 : pin.minor ? 0 : pin.mika ? 2 : 1;
}

/** L'élément d'une épingle : un bouton sur une carte qu'on touche, une pastille sur une miniature. */
function pinElement(pin: ScenePin, interactive: boolean): HTMLElement {
  const el = document.createElement(interactive ? "button" : "span");
  el.className = pinClass(pin);
  if (pin.label && !pin.minor) el.textContent = pin.label;
  if (pin.title) {
    el.title = pin.title;
    el.setAttribute("aria-label", pin.title);
  }
  if (interactive) {
    (el as HTMLButtonElement).type = "button";
    el.dataset.pin = pin.id;
  } else {
    el.setAttribute("aria-hidden", "true");
  }
  return el;
}

function hereElement(): HTMLElement {
  const el = document.createElement("span");
  el.className = "cm-here-el";
  el.title = "Ta position";
  el.setAttribute("aria-label", "Ta position");
  return el;
}

export class MapView {
  private readonly base: BaseMap;
  private readonly lib: MapLib;
  private markers: Marker[] = [];
  private scene: Scene = EMPTY_SCENE;
  private key = "";

  constructor(
    lib: MapLib,
    readonly host: HTMLElement,
    info: MapInfo,
    scene: Scene,
    private readonly opts: MapViewOptions,
  ) {
    this.lib = lib;
    this.scene = cleanScene(scene);
    const focus = hereFocus(this.scene);
    const framed = focus ? null : sceneFraming(this.scene, opts.interactive);
    const { padding, maxZoom } = framingFor(opts.interactive);
    this.base = createBaseMap(lib, host, info, {
      dark: opts.dark,
      interactive: opts.interactive,
      attribution: opts.interactive,
      ...(focus ?? (framed ? { bounds: framed.bounds } : boundsFromInfo(info))),
      padding,
      fitMaxZoom: maxZoom,
      // le cercle d'abord : les tracés passent par-dessus
      overlay: (map) => {
        addHere(map, this.scene);
        addLines(map, this.scene);
      },
      onFail: opts.onFail,
    });
    this.key = sceneKey(this.scene);
    this.placeMarkers();
    if (opts.onPin) {
      const onPin = opts.onPin;
      host.addEventListener("click", (e) => {
        const b = (e.target as Element | null)?.closest?.("[data-pin]") as HTMLElement | null;
        if (b && host.contains(b)) {
          e.stopPropagation();
          onPin(b.dataset.pin ?? "");
        }
      });
    }
    if (opts.onMove) {
      const onMove = opts.onMove;
      this.base.map.on("moveend", (e: { originalEvent?: unknown }) => {
        if (e.originalEvent) onMove(); // la personne l'a bougée, pas un cadrage de l'écran
      });
    }
  }

  get info(): MapInfo {
    return this.base.info;
  }

  /**
   * Une autre scène : ses épingles et ses tracés, reposés (rien de changé : rien à reposer). `fit` : cadrée sur elle,
   * même inchangée, car un cadrage demandé (une recherche relancée qui rend les mêmes lieux) ne se perd pas ; vide, la
   * vue reste, sauf `orBase` : le fond de carte.
   */
  show(scene: Scene, fit = true, orBase = false): void {
    const next = cleanScene(scene);
    const key = sceneKey(next);
    if (key !== this.key) {
      this.key = key;
      this.scene = next;
      // jamais par `isStyleLoaded()`, faux tant que des tuiles arrivent : la source, si elle est là ; sinon
      // « style.load » posera la scène d'aujourd'hui
      setHere(this.base.map, next);
      setLines(this.base.map, next);
      this.placeMarkers();
    }
    if (fit) this.fit(true, orBase);
  }

  /**
   * Cadrer la scène. Une position seule et sa précision : recentrée, au zoom où on l'a laissée. Rien à montrer : la vue
   * reste (un regard qui se lit encore attend ses lieux), sauf `orBase` (un regard en échec) : la zone de la carte du
   * serveur, sinon la France.
   */
  fit(animate = true, orBase = false): void {
    const duration = animate && this.opts.interactive ? 600 : 0;
    const focus = hereFocus(this.scene);
    if (focus) {
      this.base.map.easeTo({ center: focus.center, duration });
      return;
    }
    const framed = sceneFraming(this.scene, this.opts.interactive);
    if (framed) {
      this.base.map.fitBounds(framed.bounds as LngLatBoundsLike, { padding: framed.padding, maxZoom: framed.maxZoom, duration });
      return;
    }
    if (!orBase) return;
    const home = boundsFromInfo(this.base.info);
    if ("bounds" in home) this.base.map.fitBounds(home.bounds as LngLatBoundsLike, { padding: framingFor(this.opts.interactive).padding, duration });
    else this.base.map.easeTo({ center: home.center, zoom: home.zoom, duration });
  }

  /** Ce que la carte montre en ce moment (ouest, sud, est, nord), dans les bornes de la Terre. */
  frame(): Bounds {
    const b = this.base.map.getBounds();
    return [Math.max(-180, b.getWest()), Math.max(-90, b.getSouth()), Math.min(180, b.getEast()), Math.min(90, b.getNorth())];
  }

  theme(dark: boolean): void {
    this.base.theme(dark);
  }

  restyle(info: MapInfo): void {
    this.base.restyle(info);
  }

  resize(): void {
    this.base.resize();
  }

  remove(): void {
    for (const m of this.markers) m.remove();
    this.markers = [];
    this.base.remove();
  }

  private placeMarkers(): void {
    for (const m of this.markers) m.remove();
    const map = this.base.map;
    const interactive = this.opts.interactive;
    this.markers = [];
    // sa position d'abord, sous les épingles (posées après, elles passent par-dessus) ; puis les secondaires sous les
    // arrêts, les siennes au-dessus des autres, et l'épingle choisie au-dessus de tout
    const here = this.scene.here;
    if (here) this.markers.push(new this.lib.Marker({ element: hereElement(), anchor: "center" }).setLngLat([here.lon, here.lat]).addTo(map));
    const pins = [...this.scene.pins].sort((a, b) => pinRank(a) - pinRank(b));
    for (const p of pins) {
      this.markers.push(new this.lib.Marker({ element: pinElement(p, interactive), anchor: "center" }).setLngLat([p.lon, p.lat]).addTo(map));
    }
  }
}

/** Sans rien à montrer : la zone de la carte du serveur, sinon la France. */
function boundsFromInfo(info: MapInfo): { bounds: Bounds } | { center: [number, number]; zoom: number } {
  return info.bounds ? { bounds: info.bounds } : { center: [2.35, 46.6], zoom: 5 };
}
