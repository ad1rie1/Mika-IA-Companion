/**
 * Une carte de l'écran Carte, ou une miniature du chat (ADR 0194, 0196) : le fond du serveur (`base.ts`), et par-dessus
 * une scène (`scene.ts`) — des épingles numérotées (roses pour ce que Mika a fait), des tracés, la position de la
 * personne — que la vue cadre (`fitBounds`). Le thème et une autre carte du serveur se reposent sans la refaire.
 */
import type { GeoJSONSource, LngLatBoundsLike, Map as MapLibre, Marker } from "maplibre-gl";
import type { MapInfo } from "../api/phone";
import { createBaseMap, type BaseMap, type MapLib } from "./base";
import type { Bounds } from "./mapgeo";
import { cleanScene, EMPTY_SCENE, linesGeoJson, sceneBounds, sceneKey, type Scene } from "./scene";

const LINES = "lignes";

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

/** L'élément d'une épingle : un bouton sur une carte qu'on touche, une pastille sur une miniature. */
function pinElement(pin: Scene["pins"][number], interactive: boolean): HTMLElement {
  const el = document.createElement(interactive ? "button" : "span");
  el.className = `cm-pin-el${pin.mika ? " mika" : ""}${pin.selected ? " sel" : ""}${pin.label ? "" : " dot"}`;
  if (pin.label) el.textContent = pin.label;
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
    const bounds = sceneBounds(this.scene);
    this.base = createBaseMap(lib, host, info, {
      dark: opts.dark,
      interactive: opts.interactive,
      attribution: opts.interactive,
      ...(bounds ? { bounds } : boundsFromInfo(info)),
      ...this.framing(),
      overlay: (map) => addLines(map, this.scene),
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

  /** Une autre scène : ses épingles et ses tracés, reposés ; `fit` : cadrée sur elle. Rien de changé : rien. */
  show(scene: Scene, fit = true): void {
    const next = cleanScene(scene);
    const key = sceneKey(next);
    if (key === this.key) return;
    this.key = key;
    this.scene = next;
    // jamais par `isStyleLoaded()`, faux tant que des tuiles arrivent : la source, si elle est là ; sinon
    // « style.load » posera la scène d'aujourd'hui
    setLines(this.base.map, next);
    this.placeMarkers();
    if (fit) this.fit();
  }

  /** Les marges et le zoom le plus serré d'un cadrage : larges sur l'écran Carte, étroites sur une miniature. */
  private framing(): { padding: number; fitMaxZoom: number } {
    return this.opts.interactive ? { padding: 56, fitMaxZoom: 14 } : { padding: 18, fitMaxZoom: 12.5 };
  }

  /** Cadrer la scène (rien à montrer : la vue reste). */
  fit(animate = true): void {
    const b = sceneBounds(this.scene);
    if (!b) return;
    const { padding, fitMaxZoom } = this.framing();
    this.base.map.fitBounds(b as LngLatBoundsLike, { padding, maxZoom: fitMaxZoom, duration: animate && this.opts.interactive ? 600 : 0 });
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
    // sa position d'abord, sous les épingles (posées après, elles passent par-dessus) ; puis les siennes au-dessus
    // des autres, et l'épingle choisie au-dessus de tout
    const here = this.scene.here;
    if (here) this.markers.push(new this.lib.Marker({ element: hereElement(), anchor: "center" }).setLngLat([here.lon, here.lat]).addTo(map));
    const rank = (p: Scene["pins"][number]) => (p.selected ? 2 : p.mika ? 1 : 0);
    const pins = [...this.scene.pins].sort((a, b) => rank(a) - rank(b));
    for (const p of pins) {
      this.markers.push(new this.lib.Marker({ element: pinElement(p, interactive), anchor: "center" }).setLngLat([p.lon, p.lat]).addTo(map));
    }
  }
}

/** Sans rien à montrer : la zone de la carte du serveur, sinon la France. */
function boundsFromInfo(info: MapInfo): { bounds: Bounds } | { center: [number, number]; zoom: number } {
  return info.bounds ? { bounds: info.bounds } : { center: [2.35, 46.6], zoom: 5 };
}
