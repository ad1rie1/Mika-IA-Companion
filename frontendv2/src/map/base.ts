/**
 * Ce que toute carte dessinée par MapLibre partage (ADR 0193, 0194) : l'adresse absolue du serveur, ses tuiles, polices
 * et icônes demandées avec la session (et rien d'autre), les commandes en français, le nord toujours en haut (ni
 * rotation ni inclinaison), le thème qui suit, une autre carte du serveur qui se repose sans se refaire, et des tuiles
 * qui échouent de suite qui font revenir le plan dessiné.
 *
 * MapLibre n'est pas importé ici (seulement ses types) : il se charge à part (`load.ts`), et chaque carte le reçoit —
 * ce qui laisse aussi les tests lui en donner un faux.
 */
import { API_BASE } from "@web/network/api";
import type { Map as MapLibre, MapOptions, RequestParameters } from "maplibre-gl";
import type { MapInfo } from "../api/phone";
import { infoKey } from "./info";
import type { Bounds } from "./mapgeo";
import { mapStyle, SOURCE } from "./mapstyle";

/** Le module MapLibre, tel que `load.ts` le donne. */
export type MapLib = typeof import("maplibre-gl");

/**
 * L'adresse absolue du serveur, pour MapLibre. Un client construit pour la même origine que le serveur
 * (`VITE_BACKEND_ORIGIN` vide : Caddy sert tout, comme sur le portable) a une base vide ; ses chemins se posent alors
 * sur l'adresse de la page.
 */
export function absoluteBase(api: string, page: string): string {
  const base = api.trim().replace(/\/+$/, "");
  if (/^https?:\/\//i.test(base)) return base;
  const origin = page.trim().replace(/\/+$/, "");
  return base ? `${origin}${base.startsWith("/") ? "" : "/"}${base}` : origin;
}

/** L'adresse absolue de ce serveur, depuis la page. */
export function mapBase(): string {
  return absoluteBase(API_BASE, location.origin);
}

/** Ce que MapLibre demande : vers ce serveur, avec la session (le client de développement est d'une autre origine). */
export function transformFor(base: string): (url: string) => RequestParameters {
  return (url) => (url.startsWith(`${base}/`) ? { url, credentials: "include" } : { url });
}

/** Les commandes et les noms de MapLibre, en français (ses défauts sont anglais). */
export const FR_LOCALE: Record<string, string> = {
  "AttributionControl.ToggleAttribution": "Afficher ou masquer les mentions",
  "AttributionControl.MapFeedback": "Signaler une erreur de la carte",
  "FullscreenControl.Enter": "Plein écran",
  "FullscreenControl.Exit": "Quitter le plein écran",
  "GeolocateControl.FindMyLocation": "Trouver ma position",
  "GeolocateControl.LocationNotAvailable": "Position indisponible",
  "LogoControl.Title": "Logo de MapLibre",
  "Map.Title": "Carte",
  "Marker.Title": "Repère",
  "NavigationControl.ResetBearing": "Glisser pour tourner la carte, cliquer pour remettre le nord en haut",
  "NavigationControl.ZoomIn": "Zoomer",
  "NavigationControl.ZoomOut": "Dézoomer",
  "Popup.Close": "Fermer",
  "ScaleControl.Feet": "pi",
  "ScaleControl.Meters": "m",
  "ScaleControl.Kilometers": "km",
  "ScaleControl.Miles": "mi",
  "ScaleControl.NauticalMiles": "nmi",
  "GlobeControl.Enable": "Afficher le globe",
  "GlobeControl.Disable": "Afficher la carte à plat",
  "TerrainControl.Enable": "Afficher le relief",
  "TerrainControl.Disable": "Masquer le relief",
  "CooperativeGesturesHandler.WindowsHelpText": "Ctrl + molette pour zoomer",
  "CooperativeGesturesHandler.MacHelpText": "⌘ + molette pour zoomer",
  "CooperativeGesturesHandler.MobileHelpText": "Deux doigts pour déplacer la carte",
};

/** Au-delà de tant de tuiles en échec d'affilée (aucune lue entre deux), la carte ne se dessine pas : le plan revient. */
export const TILE_FAILURES = 4;

/**
 * Le compte des tuiles en échec d'affilée : une tuile lue le remet à zéro ; `failed` ne devient vrai qu'une fois.
 * Une tuile absente (204, ou 404 que MapLibre tait) n'est pas un échec.
 */
export class TileWatch {
  private streak = 0;
  failed = false;

  constructor(private readonly limit = TILE_FAILURES) {}

  /** Une tuile en échec : vrai la seule fois où la série atteint la borne. */
  error(): boolean {
    if (this.failed) return false;
    this.streak += 1;
    if (this.streak < this.limit) return false;
    this.failed = true;
    return true;
  }

  ok(): void {
    if (!this.failed) this.streak = 0;
  }

  reset(): void {
    this.streak = 0;
    this.failed = false;
  }
}

export interface BaseMapOptions {
  dark: boolean;
  /** Où regarder d'abord : un centre (lon, lat) et un zoom, ou une zone. */
  center?: [number, number];
  zoom?: number;
  bounds?: Bounds;
  /** Le cadrage d'une zone : ses marges (px) et son zoom le plus serré. */
  padding?: number;
  fitMaxZoom?: number;
  /** Faux : une miniature (ni geste, ni commande). */
  interactive?: boolean;
  /** Les boutons de zoom (par défaut : si elle est interactive). */
  controls?: boolean;
  /** La mention de la carte, dessinée par MapLibre (une miniature l'écrit elle-même, sans lien). */
  attribution?: boolean;
  maxZoom?: number;
  /** Ce qui se pose par-dessus la carte, reposé après chaque style (un autre thème, une autre carte du serveur). */
  overlay?: (map: MapLibre) => void;
  /** Les tuiles échouent de suite (un serveur de carte injoignable) : la carte ne se dessinera pas. */
  onFail?: () => void;
  /** L'adresse absolue du serveur (par défaut, `mapBase()`). */
  base?: string;
}

export interface BaseMap {
  readonly map: MapLibre;
  /** La carte servie qu'elle dessine en ce moment. */
  readonly info: MapInfo;
  /** Un autre thème : son style, reposé (ce qui est par-dessus avec). */
  theme(dark: boolean): void;
  /** Une autre carte du serveur (relue toutes les cinq minutes : polices ajoutées, autre source, autre zone). */
  restyle(info: MapInfo): void;
  resize(): void;
  remove(): void;
}

/** Les options de MapLibre pour cette carte : pures, pour qu'un test les lise. */
export function mapOptions(host: HTMLElement, info: MapInfo, opts: BaseMapOptions, base: string): MapOptions {
  const interactive = opts.interactive !== false;
  const view = opts.bounds
    ? { bounds: opts.bounds as [number, number, number, number], fitBoundsOptions: { padding: opts.padding ?? 32, maxZoom: opts.fitMaxZoom ?? 15 } }
    : { center: opts.center ?? [2.35, 46.6], zoom: opts.zoom ?? 5 };
  return {
    container: host,
    style: mapStyle(info, opts.dark, base),
    ...view,
    maxZoom: opts.maxZoom ?? 19,
    interactive,
    // le nord reste en haut : ni rotation ni inclinaison, aucune boussole n'est là pour y revenir
    dragRotate: false,
    pitchWithRotate: false,
    touchPitch: false,
    attributionControl: opts.attribution === false ? false : { compact: false },
    locale: FR_LOCALE,
    transformRequest: transformFor(base),
  };
}

/**
 * Une carte MapLibre dans `host`. Lève si le navigateur ne dessine pas (pas de WebGL) : l'appelant garde son plan.
 * `onFail` dit, une fois, que ses tuiles échouent de suite ; une autre carte du serveur (`restyle`) recommence le compte.
 */
export function createBaseMap(lib: MapLib, host: HTMLElement, info: MapInfo, opts: BaseMapOptions): BaseMap {
  const base = opts.base ?? mapBase();
  let current = info;
  let dark = opts.dark;
  const watch = new TileWatch();
  const map = new lib.Map(mapOptions(host, info, opts, base));
  // deux doigts zooment sans tourner ; Maj et les flèches ne tournent ni n'inclinent (elles déplacent encore)
  map.touchZoomRotate.disableRotation();
  map.keyboard.disableRotation();
  if (opts.controls ?? opts.interactive !== false) {
    map.addControl(new lib.NavigationControl({ showCompass: false }), "top-right");
  }
  if (opts.overlay) {
    const overlay = opts.overlay;
    map.on("style.load", () => overlay(map));
  }
  map.on("error", (e: { sourceId?: string; tile?: unknown }) => {
    if (e.sourceId !== SOURCE || !e.tile) return; // une police, une planche d'icônes : la carte reste
    if (watch.error()) opts.onFail?.();
  });
  map.on("sourcedata", (e: { sourceId?: string; tile?: unknown }) => {
    if (e.sourceId === SOURCE && e.tile) watch.ok();
  });
  const apply = () => map.setStyle(mapStyle(current, dark, base), { diff: false }); // « style.load » repose le dessus
  return {
    map,
    get info() {
      return current;
    },
    theme(next) {
      if (next === dark) return;
      dark = next;
      apply();
    },
    restyle(next) {
      if (infoKey(next) === infoKey(current)) return;
      current = next;
      watch.reset();
      apply();
    },
    resize() {
      map.resize();
    },
    remove() {
      map.remove();
    },
  };
}
