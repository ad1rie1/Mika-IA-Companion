/**
 * Carte : ce qui se calcule sans DOM ni réseau — l'ordre des arrêts d'un voyage et où un geste les met (un geste qui ne
 * change rien, ce qu'en dit un lecteur d'écran), une note changée, ce dont son trajet dépend, le jour et la place d'un
 * lieu croisé le long du trajet, ce que la fenêtre d'un voyage envoie, tes choix d'itinéraire face à ceux d'un trajet
 * de Mika, jusqu'où une recherche est allée, un itinéraire en GPX, les phrases qu'on prépare pour Mika, le contrôle qui
 * garde la main d'un dessin à l'autre, les icônes des catégories.
 */
import { AVOIDS, MODES, type Place, type Route, type Trip, type TripRoute, type TripStop, type TripValues } from "../../api/carte";
import { meters, validPoint } from "../../map/mapgeo";
import { safeDecode, type LatLon } from "../../map/polyline";
import type { IconName } from "../../shell/icons";
import { duration, km, modeWords } from "../../map/words";

// ── Les arrêts d'un voyage ───────────────────────────────────────────

/** Ses arrêts dans l'ordre du voyage, avec leur jour et leur numéro (1, 2, 3… d'un bout à l'autre). */
export function orderedStops(trip: Trip): { stop: TripStop; day: number; n: number }[] {
  let n = 0;
  return trip.days.flatMap((d) => d.stops.map((stop) => ({ stop, day: d.n, n: ++n })));
}

/**
 * Où un arrêt déplacé atterrit : le jour `day`, posé avant l'arrêt `before` (ou à la fin du jour si `before` est vide)
 * — en `index`, sa place parmi les **autres** arrêts du jour, comme l'API la lit (`plugins/trips::place`).
 */
export function dropIndex(trip: Trip, moving: string, day: number, before: string | null): number {
  const others = (trip.days.find((d) => d.n === day)?.stops ?? []).filter((s) => s.id !== moving);
  if (!before) return -1;
  const at = others.findIndex((s) => s.id === before);
  return at < 0 ? -1 : at;
}

/** Le voyage tel qu'il sera une fois l'arrêt déplacé (pour le montrer avant que le serveur le dise). */
export function movedTrip(trip: Trip, moving: string, day: number, index: number): Trip {
  const stop = trip.days.flatMap((d) => d.stops).find((s) => s.id === moving);
  if (!stop) return trip;
  const lastDay = Math.max(day, ...trip.days.map((d) => d.n));
  const days = Array.from({ length: lastDay }, (_, i) => {
    const n = i + 1;
    const found = trip.days.find((d) => d.n === n);
    return { n, date: found?.date ?? "", stops: (found?.stops ?? []).filter((s) => s.id !== moving) };
  });
  const row = days[day - 1].stops;
  row.splice(index < 0 || index > row.length ? row.length : index, 0, stop);
  // un voyage va du jour 1 au dernier qui a un arrêt
  while (days.length > 1 && !days[days.length - 1].stops.length) days.pop();
  return { ...trip, days };
}

/** Les arrêts de chaque jour, dans l'ordre, sans les jours vides du bout : deux voyages rangés pareil se confondent. */
function arrangement(trip: Trip): string {
  const days = trip.days.map((d) => d.stops.map((s) => s.id).join(","));
  while (days.length && !days[days.length - 1]) days.pop();
  return days.join("|");
}

/** Le voyage sans cet arrêt (pour le montrer retiré avant que le serveur le dise). */
export function removedTrip(trip: Trip, stopId: string): Trip {
  const days = trip.days.map((d) => ({ ...d, stops: d.stops.filter((s) => s.id !== stopId) }));
  while (days.length > 1 && !days[days.length - 1].stops.length) days.pop();
  return { ...trip, days };
}

/** Le voyage avec cette note sur cet arrêt (vide : sans note), pour la montrer avant que le serveur le dise. */
export function notedTrip(trip: Trip, stopId: string, note: string): Trip {
  return { ...trip, days: trip.days.map((d) => ({ ...d, stops: d.stops.map((s) => (s.id === stopId ? { ...s, note } : s)) })) };
}

/** Un geste qui ne change rien (une poignée lâchée où elle était, un tremblement) : rien à envoyer. */
export function noopMove(trip: Trip, moving: string, day: number, index: number): boolean {
  return arrangement(movedTrip(trip, moving, day, index)) === arrangement(trip);
}

/** Ce qu'un lecteur d'écran dit d'un arrêt déplacé au clavier : « Reims : jour 1, arrêt 2 sur 3. » */
export function movedWords(trip: Trip, stopId: string): string {
  const day = trip.days.find((d) => d.stops.some((s) => s.id === stopId));
  if (!day) return "";
  const at = day.stops.findIndex((s) => s.id === stopId);
  return `${day.stops[at].name || "L'arrêt"} : jour ${day.n}, arrêt ${at + 1} sur ${day.stops.length}.`;
}

/** Combien de ses arrêts ont des coordonnées : sous deux, un voyage n'a pas de trajet. */
export function routableStops(trip: Trip): number {
  return trip.days.reduce((a, d) => a + d.stops.filter((s) => validPoint(s.lat, s.lon)).length, 0);
}

/**
 * Ce dont le trajet d'un voyage dépend (`GET …/trajet`) : ses arrêts dans l'ordre, avec leur jour et leurs
 * coordonnées, son mode, ce qu'il évite. La même clé : le trajet calculé vaut encore ; une autre : il se recalcule. Une
 * note, un titre, une date n'y sont pas.
 */
export function tripRouteKey(trip: Trip): string {
  return JSON.stringify([trip.id, trip.mode, [...trip.avoid].sort(), trip.days.flatMap((d) => d.stops.map((s) => [s.id, d.n, s.lat, s.lon]))]);
}

/** Monter ou descendre un arrêt d'une place (au clavier), d'un jour à l'autre au besoin : `[jour, index]`, ou `null`. */
export function stepMove(trip: Trip, moving: string, delta: -1 | 1): [number, number] | null {
  const day = trip.days.find((d) => d.stops.some((s) => s.id === moving));
  if (!day) return null;
  const at = day.stops.findIndex((s) => s.id === moving);
  const next = at + delta;
  if (next >= 0 && next < day.stops.length) return [day.n, next];
  // au bord du jour : au bout du jour voisin
  const neighbour = day.n + delta;
  if (neighbour < 1 || (delta > 0 && neighbour > trip.days.length && day.stops.length === 1)) return null;
  if (delta < 0) return [neighbour, -1];
  return [neighbour, 0];
}

/** Ses arrêts qu'elle a ajoutés. */
export function hersCount(trip: Trip): number {
  return trip.days.reduce((a, d) => a + d.stops.filter((s) => s.by === "mika").length, 0);
}

/** Le titre d'un jour : « Lille → Dijon », un seul arrêt : son nom ; aucun : vide. */
export function dayTitle(stops: readonly TripStop[]): string {
  if (!stops.length) return "";
  const first = stops[0].name;
  const last = stops[stops.length - 1].name;
  return stops.length === 1 || first === last ? first : `${first} → ${last}`;
}

/** Le tronçon qui arrive à chaque arrêt (« 2 h 15 · 207 km »), par l'identifiant de l'arrêt. */
export function legsByStop(route: TripRoute | null): Map<string, { distance_m: number; duration_s: number }> {
  const out = new Map<string, { distance_m: number; duration_s: number }>();
  for (const d of route?.days ?? []) for (const leg of d.legs) out.set(leg.to, { distance_m: leg.distance_m, duration_s: leg.duration_s });
  return out;
}

/** Le tracé d'un voyage, tronçon par tronçon (ce que le serveur d'itinéraires a calculé), en points. */
export function tripLines(route: TripRoute | null): LatLon[][] {
  return (route?.days ?? []).flatMap((d) => d.legs.map((l) => safeDecode(l.shape))).filter((p) => p.length >= 2);
}

/**
 * Où ajouter un lieu croisé le long du trajet (`along_m` : sa distance depuis le départ) : avant l'arrêt qu'on atteint
 * juste après lui, dans le jour de cet arrêt. Les distances d'un arrêt au suivant viennent des tronçons calculés, sinon
 * du vol d'oiseau (le long d'une ligne droite, comme le serveur sans itinéraires). Rend `[jour, index]` (−1 : à la fin).
 */
export function alongPlace(trip: Trip, route: TripRoute | null, along: number | null): [number, number] {
  const order = orderedStops(trip).filter((o) => validPoint(o.stop.lat, o.stop.lon));
  const lastDay = trip.days.length ? trip.days[trip.days.length - 1].n : 1;
  if (order.length < 2 || typeof along !== "number") return [lastDay, -1];
  const legs = legsByStop(route);
  let walked = 0;
  for (let i = 1; i < order.length; i++) {
    const prev = order[i - 1].stop;
    const cur = order[i].stop;
    walked += legs.get(cur.id)?.distance_m ?? meters([prev.lat as number, prev.lon as number], [cur.lat as number, cur.lon as number]);
    if (along <= walked) {
      const day = trip.days.find((d) => d.n === order[i].day)!;
      return [order[i].day, day.stops.findIndex((s) => s.id === cur.id)];
    }
  }
  return [lastDay, -1];
}

// ── Les choix d'un itinéraire ────────────────────────────────────────

/** Le mode d'un itinéraire et ce qu'il évite (en voiture seulement). */
export interface RouteChoices {
  mode: string;
  avoid: string[];
}

/** Un geste de la personne : un mode, ou une case cochée ou décochée. */
export type RouteChoice = { mode: string } | { avoid: string; on: boolean };

/**
 * Le mode et ce qu'évite le trajet montré : ceux du trajet de Mika qu'on ouvre (`regard`, tel qu'elle l'a gardé), sinon
 * les tiens (`own`). Ce qu'un regard ne dit pas (un regard d'avant ne dit pas ce qu'il évitait), ce sont les tiens. Rien
 * n'écrit `own` ici : son trajet se montre sans devenir ton choix (un trajet que tu commences reprend `own`).
 */
export function routeChoices(own: RouteChoices, regard: { mode?: string | null; avoid?: readonly string[] | null } | null): RouteChoices {
  const mode = regard?.mode && (MODES as readonly string[]).includes(regard.mode) ? regard.mode : own.mode;
  const said = regard?.avoid;
  const avoid = Array.isArray(said) ? AVOIDS.filter((a) => said.includes(a)) : [...own.avoid];
  return { mode, avoid };
}

/**
 * Des choix après un geste (un mode, une case) : seul ce que le geste touche change. Il s'applique au trajet montré
 * comme à tes choix — un clic sur une case du trajet de Mika ne fait pas tiennes les autres cases qu'il avait cochées.
 */
export function withChoice(choices: RouteChoices, choice: RouteChoice): RouteChoices {
  if ("mode" in choice) {
    return (MODES as readonly string[]).includes(choice.mode) ? { mode: choice.mode, avoid: [...choices.avoid] } : choices;
  }
  if (!(AVOIDS as readonly string[]).includes(choice.avoid)) return choices;
  return { mode: choices.mode, avoid: AVOIDS.filter((a) => (a === choice.avoid ? choice.on : choices.avoid.includes(a))) };
}

// ── Ce que la fenêtre d'un voyage envoie ─────────────────────────────

/** Ce que disent les fenêtres « Nouveau voyage » et « Le voyage » (`avoid` : les cases cochées, cachées ou non). */
export interface TripForm {
  title: string;
  start: string;
  mode: string;
  avoid: readonly string[];
}

/** Ce qu'un trajet évite pour ce mode : en voiture, les cases cochées (dans l'ordre de l'API) ; à vélo, à pied, rien. */
function avoidFor(mode: string, avoid: readonly string[]): string[] {
  return mode === "voiture" ? AVOIDS.filter((a) => avoid.includes(a)) : [];
}

/** « Nouveau voyage » : son titre, sa date, son mode, et ce qu'il évite s'il se fait en voiture (sinon rien). */
export function newTripValues(form: TripForm): TripValues & { title: string } {
  return { title: form.title.trim(), start: form.start, mode: form.mode, ...(form.mode === "voiture" ? { avoid: avoidFor(form.mode, form.avoid) } : {}) };
}

/**
 * « Le voyage » : ce qui a changé, seulement (un corps vide : rien à envoyer). Ce qu'il évite ne part qu'en voiture
 * — les cases, cachées hors voiture, ne disent rien d'un voyage qui la quitte —, et seulement s'il a changé.
 */
export function tripChanges(trip: Pick<Trip, "title" | "start" | "mode" | "avoid">, form: TripForm): TripValues {
  const values: TripValues = {};
  const title = form.title.trim();
  if (title !== trip.title) values.title = title;
  if (form.start !== trip.start) values.start = form.start;
  if (form.mode !== trip.mode) values.mode = form.mode;
  if (form.mode === "voiture") {
    const avoid = avoidFor(form.mode, form.avoid);
    if (avoid.join(",") !== AVOIDS.filter((a) => trip.avoid.includes(a)).join(",")) values.avoid = avoid;
  }
  return values;
}

// ── Jusqu'où une recherche est allée ─────────────────────────────────

/**
 * Le rayon (en mètres) jusqu'où une recherche autour de toi se dit « autour de ta position » : le deuxième cercle où
 * l'index cherche un texte (`TEXT_RADII_KM`, `backendv2/src/mika/adapters/maps/places.py`). Au-delà, il s'est élargi.
 */
export const NEARBY_M = 20_000;

/**
 * Ce que la légende dit de la portée d'une recherche, depuis ses lieux reçus (`distance_m`). Autour de toi, l'index
 * élargit ses cercles jusqu'à trouver, puis cherche partout : tant que le plus loin est à `NEARBY_M` au plus, c'est
 * « autour de ta position » ; sinon, ce sont les plus proches qu'il connaisse, jusqu'où ils vont. Le classement mêle
 * pertinence et distance : la phrase ne promet pas un ordre par distance. Une zone ne s'élargit pas : « dans cette
 * zone ». `near` : la recherche est partie de ta position (inconnue, elle cherche dans la zone de la carte).
 */
export function searchReach(near: boolean, places: readonly Pick<Place, "distance_m">[]): string {
  if (!near) return "dans cette zone";
  const far = Math.max(0, ...places.map((p) => (typeof p.distance_m === "number" && Number.isFinite(p.distance_m) ? p.distance_m : 0)));
  return far <= NEARBY_M ? "autour de ta position" : `les plus proches que l'index connaisse · jusqu'à ${km(far)}`;
}

// ── La main d'un dessin à l'autre ────────────────────────────────────

/** Les attributs qui désignent un contrôle de l'écran d'un dessin à l'autre, du plus sûr au moins sûr. */
const FOCUS_KEYS = ["q", "pt", "cat", "where", "lieu", "mode", "avoid", "itiAdd", "itiSwap", "itiRemove", "itiCompute", "itiTrip",
  "itiGpx", "itiAsk", "pick", "goRoute", "addTrip", "askPlace", "grip", "noteInput", "noteSave", "noteCancel", "noteStop", "retirer",
  "addStop", "onroute", "addAlong", "editTrip", "newTrip", "retry"] as const;

/**
 * Le sélecteur qui retrouve, après un dessin, le contrôle qui avait la main (ses `data-*`, tels que `dataset` les
 * donne) : `[data-cat="dormir"]`, `[data-iti-swap]` ; aucun de ceux-là : `null`.
 */
export function focusSelector(data: Readonly<Record<string, string | undefined>>): string | null {
  for (const key of FOCUS_KEYS) {
    const value = data[key];
    if (value === undefined) continue;
    const attr = `data-${key.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`;
    return value ? `[${attr}="${value.replace(/["\\]/g, "\\$&")}"]` : `[${attr}]`;
  }
  return null;
}

// ── Les catégories ───────────────────────────────────────────────────

const CATEGORY_ICONS: Record<string, IconName> = {
  manger: "smile", dormir: "moon", voir: "eye", nature: "sun", route: "bolt", courses: "tag", sante: "heart",
  sortir: "star", services: "info", villes: "pin", adresse: "pin",
};

export function categoryIcon(category: string): IconName {
  return CATEGORY_ICONS[category] ?? "pin";
}

// ── Pour Mika ────────────────────────────────────────────────────────

/** « En parler à Mika » : la phrase qu'on lui prépare, qu'on complète avant de l'envoyer. */
export function askAboutPlace(p: Pick<Place, "name" | "kind_fr" | "town">): string {
  const what = [p.kind_fr, p.town].filter(Boolean).join(", ");
  return `Tu connais « ${p.name} »${what ? ` (${what})` : ""} ? `;
}

/** « Demander à Mika », d'un voyage. */
export function askAboutTrip(t: Pick<Trip, "title">): string {
  return `Tu peux m'aider à préparer notre voyage « ${t.title} » ? `;
}

/** « Envoyer à Mika », d'un itinéraire. */
export function askAboutRoute(names: readonly string[], route: Pick<Route, "distance_m" | "duration_s"> | null, mode: string): string {
  const facts = route ? ` (${[duration(route.duration_s), km(route.distance_m)].filter(Boolean).join(", ")} ${modeWords(mode)})` : "";
  return `Regarde ce trajet : ${names.join(" → ")}${facts}. `;
}

// ── Le GPX d'un itinéraire ───────────────────────────────────────────

/** L'espace de noms de GPX 1.1 : un nom que le format exige, jamais une adresse que le navigateur joindrait. */
const GPX_NS = "http://www.topografix.com/GPX/1/1";

function xml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" })[c] ?? c);
}

/**
 * Un itinéraire en GPX 1.1, fait dans le navigateur (un itinéraire n'est pas encore un voyage : le serveur ne garde que
 * le GPX d'un voyage) : ses points nommés en route (`<rte>`), son tracé en trace (`<trk>`), tout texte échappé.
 */
export function routeGpx(name: string, points: readonly { name: string; lat: number; lon: number }[], track: readonly LatLon[]): string {
  const rte = points.map((p) => `    <rtept lat="${p.lat.toFixed(6)}" lon="${p.lon.toFixed(6)}"><name>${xml(p.name)}</name></rtept>`).join("\n");
  const trk = track.map(([la, lo]) => `      <trkpt lat="${la.toFixed(6)}" lon="${lo.toFixed(6)}"/>`).join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Mika" xmlns="${GPX_NS}">
  <metadata><name>${xml(name)}</name></metadata>
  <rte>
    <name>${xml(name)}</name>
${rte}
  </rte>${track.length ? `
  <trk>
    <name>${xml(name)}</name>
    <trkseg>
${trk}
    </trkseg>
  </trk>` : ""}
</gpx>
`;
}

/** Le nom d'un fichier : sans ce qu'un système refuse. */
export function fileName(title: string, ext: string): string {
  const base = title.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^\w.-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);
  return `${base || "itineraire"}.${ext}`;
}
