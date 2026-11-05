/**
 * La carte miniature d'une de ses notes (ADR 0196), sans DOM : ce qu'elle montre (un voyage, ses lieux, un trajet), en
 * scène pour la carte ou son plan dessiné, et le balisage de la carte du chat (la forme de la maquette :
 * `frontendv2/maquette/ecrans/chat.js`, `.msg-map`). Rien n'y appelle le serveur d'itinéraires : un voyage s'y dessine
 * en reliant ses arrêts, un regard avec le tracé résumé qu'elle a gardé.
 */
import type { Regard, Trip } from "../api/carte";
import type { MapInfo } from "../api/phone";
import { h } from "../shell/dom";
import { ico } from "../shell/icons";
import { drawnScene } from "./drawn";
import { validPoint } from "./mapgeo";
import { noteRoute, regardItem, type MapNote } from "./notes";
import { safeDecode, type LatLon } from "./polyline";
import { straightLine, type Scene, type ScenePin } from "./scene";
import { duration, km, modeWords, plural } from "./words";

/** Ce qu'une miniature montre, une fois lu. */
export interface MiniData {
  title: string;
  sub: string;
  /** Ce qu'elle ouvre dans l'écran Carte. */
  href: string;
  scene: Scene;
  /** Plus là (un voyage supprimé, un regard oublié depuis). */
  gone?: boolean;
  /** Le dernier changement de ce qu'elle montre (un voyage : son `updated`, en ms) ; un regard ne change pas. */
  version?: number;
}

/** Les arrêts d'un voyage, dans l'ordre, avec leurs numéros (roses : ceux qu'elle a ajoutés). */
export function tripPins(trip: Trip): ScenePin[] {
  let n = 0;
  return trip.days.flatMap((d) =>
    d.stops.flatMap((s) => {
      n += 1;
      if (!validPoint(s.lat, s.lon)) return [];
      return [{ id: s.id, lat: s.lat as number, lon: s.lon as number, label: String(n), mika: s.by === "mika", title: s.name }];
    }),
  );
}

export function tripMini(trip: Trip): MiniData {
  const pins = tripPins(trip);
  const stops = trip.days.reduce((a, d) => a + d.stops.length, 0);
  const hers = trip.days.reduce((a, d) => a + d.stops.filter((s) => s.by === "mika").length, 0);
  const line = straightLine(pins.map((p): LatLon => [p.lat, p.lon]));
  const sub = [plural(trip.days.length, "jour"), plural(stops, "arrêt"), ...(hers ? [`${hers} de Mika`] : [])].join(" · ");
  return {
    title: `Voyage · ${trip.title || "sans titre"}`,
    sub,
    href: noteRoute({ kind: "trip", ref: trip.id }),
    scene: { pins, lines: line ? [line] : [] },
    version: trip.updated,
  };
}

/** Les lieux d'un regard (ou d'une carte), tels qu'elle les a gardés : ses épingles, roses. */
export function regardPins(regard: Regard, numbered = false): ScenePin[] {
  return regard.places.flatMap((p, i) => {
    if (!validPoint(p.lat, p.lon)) return [];
    return [{ id: p.id || `p${i}`, lat: p.lat as number, lon: p.lon as number, mika: true, title: p.name ?? "",
      ...(numbered ? { label: i === 0 ? "A" : i === regard.places.length - 1 ? "B" : String(i) } : {}) }];
  });
}

/** Le tracé d'un regard : celui qu'elle a gardé, sinon ses lieux reliés (une carte qui relie sans tracé calculé). */
export function regardLine(regard: Regard): Scene["lines"] {
  if (!regard.route) return [];
  const shape = safeDecode(regard.route.shape);
  if (shape.length >= 2) return [{ points: shape, mika: true }];
  const line = straightLine(regard.places.filter((p) => validPoint(p.lat, p.lon)).map((p): LatLon => [p.lat as number, p.lon as number]));
  return line ? [{ ...line, mika: true }] : [];
}

export function regardMini(seq: string, regard: Regard): MiniData {
  const route = regard.kind === "look" && regard.what === "trajet";
  const pins = regardPins(regard, route);
  const lines = regardLine(regard);
  const r = regard.route;
  const trip = r ? [km(r.distance_m), duration(r.duration_s)].filter(Boolean).join(" · ") : "";
  const how = r?.mode ? modeWords(r.mode) : "";
  let sub: string;
  if (route) sub = ["Mika a calculé le trajet", [trip, how].filter(Boolean).join(" ")].filter(Boolean).join(" · ");
  else if (regard.kind === "look") sub = `Mika a cherché · ${plural(pins.length, "lieu", "lieux")}`;
  else sub = ["Une carte de Mika", plural(pins.length, "lieu", "lieux"), ...(trip ? [trip] : [])].join(" · ");
  const href = regard.trip
    ? noteRoute({ kind: "trip", ref: regard.trip })
    : route ? `#carte/itineraire/${regardItem(seq)}` : `#carte/explorer/${regardItem(seq)}`;
  return { title: regard.title || "Sa carte", sub, href, scene: { pins, lines } };
}

/** Avant d'être lue : le texte de la note, et ce qu'elle est. */
export function pendingMini(note: MapNote): MiniData {
  const sub = note.kind === "trip" ? "Un voyage préparé avec Mika" : note.kind === "map" ? "Une carte de Mika" : "Ce que Mika a cherché";
  return { title: note.kind === "trip" ? `Voyage · ${note.text}` : note.text, sub, href: noteRoute(note), scene: { pins: [], lines: [] } };
}

/** Plus là : le voyage supprimé, le regard oublié. */
export function goneMini(note: MapNote): MiniData {
  return { ...pendingMini(note), sub: note.kind === "trip" ? "Ce voyage n'existe plus." : "Ce qu'elle avait vu n'est plus là.", gone: true };
}

/** La mention de la carte en texte (sans balise) : ce qu'une miniature écrit sous elle, sans lien. */
export function attributionText(info: MapInfo | null): string {
  const raw = info?.attribution || "© OpenStreetMap";
  const text = raw.replace(/<[^>]*>/g, " ").replace(/&copy;/gi, "©").replace(/&amp;/gi, "&").replace(/\s+/g, " ").trim();
  return text || "© OpenStreetMap";
}

/** La largeur et la hauteur du plan d'une miniature (celles de `.msg-map .mm-map`). */
export const MINI_SIZE = { width: 340, height: 150 } as const;

/**
 * La carte du chat : sa miniature (le plan dessiné, que la vraie carte remplace quand elle paraît), son titre, ce
 * qu'elle est ; un lien vers l'écran Carte. `key` : ce que le gestionnaire des miniatures retrouve d'un dessin à
 * l'autre (`data-mini`). La mention de la carte est du texte, jamais un lien (une carte entière est déjà un lien).
 */
export function miniCard(key: string, data: MiniData, attribution: string): string {
  return `<a class="msg-map${data.gone ? " gone" : ""}" href="${h(data.href)}" data-mini="${h(key)}">
    <span class="mm-map" data-mini-map><span class="mm-plan" data-mini-plan>${miniPlan(data)}</span><span class="mm-attrib">${h(attribution)}</span></span>
    <span class="mm-text">${ico("map")}<span><b>${h(data.title)}</b><small data-mini-sub>${h(data.sub)}</small></span>${ico("chev-right", "sm")}</span></a>`;
}

/** Le plan dessiné d'une miniature. */
export function miniPlan(data: MiniData): string {
  return drawnScene(data.scene, { ...MINI_SIZE, title: data.title });
}
