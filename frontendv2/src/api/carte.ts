/**
 * Carte, lieux, itinéraires et voyages, par l'API par personne (`backendv2/docs/protocole-moi.md` § 10 ; le code :
 * `backendv2/src/mika/app/moi/carte.py`, ADR 0194 à 0196). Le navigateur ne parle qu'à ce serveur : il cherche les
 * lieux dans son index (rien ne sort), une adresse à la Géoplateforme (seul le texte part), un itinéraire au serveur
 * réglé (seuls ses points partent). Ce qui n'est pas branché répond 503, en mots (`ApiError.message`).
 *
 * Les lectures sont des `GET` ; les écritures, des `POST` avec le jeton CSRF et une clé d'envoi (`sendJson` : un
 * double clic ne refait rien, une création redite rend le même `id`).
 */
import { apiUrl, getJson, MOI, sendJson, type Done } from "./moi";

export type Mode = "voiture" | "velo" | "pied";
export type Avoid = "peages" | "autoroutes" | "ferries";

export const MODES: readonly Mode[] = ["voiture", "velo", "pied"];
export const AVOIDS: readonly Avoid[] = ["peages", "autoroutes", "ferries"];

/**
 * Les bornes de l'API (`app/moi/carte.py`, `contracts/trips.py`) : au-delà, elle refuse (400) — elle ne coupe jamais.
 */
export const CARTE_LIMITS = {
  query: 200,
  limit: 50,
  title: 120,
  name: 200,
  kind: 60,
  note: 500,
  days: 30,
  stops: 60,
  points: 20,
  corridorMin: 200,
  corridorMax: 50_000,
} as const;

/** Ce qui est branché sur le serveur, et les catégories dans l'ordre de l'écran. */
export interface CarteInfo {
  places: { ready: boolean; count: number; built: number };
  addresses: { ready: boolean };
  routing: { ready: boolean; provider: string; modes: string[]; avoid: string[] };
  categories: { id: string; label: string }[];
}

/** Un lieu : de l'index (`l<n>`, qui change à chaque reconstruction), une adresse (`a:<n>`), ou un point nommé (`""`). */
export interface Place {
  id: string;
  name: string;
  /** La sorte OpenStreetMap (`camp_site`), `address`, ou vide. */
  kind: string;
  /** « Camping ». */
  kind_fr: string;
  /** `manger`, `dormir`… ; `adresse`. */
  category: string;
  lat: number;
  lon: number;
  town: string;
  /** Depuis `near`, ou jusqu'au trajet ; sinon `null`. */
  distance_m: number | null;
  /** Le long d'un trajet : où on le croise, depuis le départ. */
  along_m: number | null;
}

export interface Step {
  text: string;
  distance_m: number;
  duration_s: number;
}

export interface Leg {
  distance_m: number;
  duration_s: number;
  /** Le tracé du tronçon, en polyline à six décimales (`map/polyline.ts`). */
  shape: string;
  steps: Step[];
}

export interface Route {
  distance_m: number;
  duration_s: number;
  legs: Leg[];
  has_toll: boolean;
  has_highway: boolean;
  has_ferry: boolean;
  /** Qui l'a calculé, en mots. */
  provider: string;
}

/** Ce qu'elle a cherché (`look`) ou montré (`map`) pour toi : la note d'un de ses messages. */
export interface Regard {
  kind: "look" | "map";
  title: string;
  /** `lieux` ou `trajet` (un regard) ; vide pour une carte. */
  what: string;
  places: Partial<Place>[];
  /**
   * Le trajet résumé ; une carte qui relie ses lieux sans tracé calculé : `{mode}` seul. `avoid` : ce que son trajet
   * évitait (`peages`…), quand le regard le dit (un regard d'avant ne le dit pas).
   */
  route: { mode?: string; avoid?: string[]; distance_m?: number | null; duration_s?: number | null; shape?: string | null } | null;
  /** Le voyage qu'elle montrait, s'il est encore là. */
  trip: string;
  at: number;
}

export interface TripSummary {
  id: string;
  title: string;
  /** `AAAA-MM-JJ`, ou vide. */
  start: string;
  mode: string;
  avoid: string[];
  days: number;
  stops: number;
  updated: number;
  /** Elle l'a préparé avec toi. */
  mika: boolean;
}

export interface TripStop {
  id: string;
  name: string;
  kind: string;
  lat: number | null;
  lon: number | null;
  note: string;
  /** `mika` : elle l'a ajouté (rose) ; `toi`. */
  by: string;
}

export interface TripDay {
  n: number;
  /** La date du jour, si le voyage en a une ; sinon vide. */
  date: string;
  stops: TripStop[];
}

export interface Trip {
  id: string;
  title: string;
  start: string;
  mode: string;
  avoid: string[];
  updated: number;
  mika?: boolean;
  days: TripDay[];
}

export interface TripLeg extends Leg {
  /** Les arrêts qu'il relie. */
  from: string;
  to: string;
}

export interface TripRoute {
  days: { n: number; distance_m: number; duration_s: number; legs: TripLeg[] }[];
  distance_m: number;
  duration_s: number;
  has_toll: boolean;
  has_highway: boolean;
  has_ferry: boolean;
  provider: string;
}

export interface Along {
  places: Place[];
  /** Faux : sans itinéraires, le long des points reliés à vol d'oiseau. */
  route: boolean;
}

/** `?a=1&b=…`, sans les valeurs vides. */
export function params(values: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === null || value === "") continue;
    q.set(key, String(value));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

/** Un point comme l'API le lit : `latitude,longitude`, à six décimales. */
export function pointText(lat: number, lon: number): string {
  return `${lat.toFixed(6)},${lon.toFixed(6)}`;
}

/** Des points, séparés par `;`. */
export function pointsText(points: readonly { lat: number; lon: number }[]): string {
  return points.map((p) => pointText(p.lat, p.lon)).join(";");
}

/** Une zone : `ouest,sud,est,nord`. */
export function bboxText(b: readonly [number, number, number, number]): string {
  return b.map((v) => v.toFixed(5)).join(",");
}

const C = `${MOI}/carte`;
const V = `${MOI}/voyages`;
const trip = (id: string) => `${V}/${encodeURIComponent(id)}`;
const stop = (id: string, s: string) => `${trip(id)}/arrets/${encodeURIComponent(s)}`;

export function fetchCarte(): Promise<CarteInfo> {
  return getJson(C);
}

export interface PlacesQuery {
  q?: string;
  cat?: string;
  near?: { lat: number; lon: number } | null;
  bbox?: readonly [number, number, number, number] | null;
  limit?: number;
}

/** Des lieux de l'index local : au moins un de `q`, `near`, `bbox`. */
export async function searchPlaces(query: PlacesQuery): Promise<Place[]> {
  const got = await getJson<{ places: Place[] }>(`${C}/lieux${params({
    q: query.q?.trim(),
    cat: query.cat,
    near: query.near ? pointText(query.near.lat, query.near.lon) : "",
    bbox: query.bbox ? bboxText(query.bbox) : "",
    limit: query.limit,
  })}`);
  return got.places ?? [];
}

/** Une adresse (Géoplateforme, relayée : seul ce texte part ; 3 à 200 caractères). */
export async function searchAddresses(q: string, limit = 5): Promise<Place[]> {
  const got = await getJson<{ places: Place[] }>(`${C}/adresses${params({ q: q.trim(), limit })}`);
  return got.places ?? [];
}

export function fetchRoute(points: readonly { lat: number; lon: number }[], mode: string, avoid: readonly string[] = []): Promise<Route> {
  return getJson(`${C}/itineraire${params({ points: pointsText(points), mode, avoid: avoid.join(",") })}`);
}

/** Le meilleur ordre de ces points, le départ et l'arrivée à leur place. */
export async function fetchOrder(points: readonly { lat: number; lon: number }[], mode: string): Promise<number[]> {
  const got = await getJson<{ order: number[] }>(`${C}/ordre${params({ points: pointsText(points), mode })}`);
  return got.order ?? [];
}

export function fetchAlong(points: readonly { lat: number; lon: number }[],
  opts: { cat?: string; corridor?: number; limit?: number; mode?: string; avoid?: readonly string[] } = {}): Promise<Along> {
  return getJson(`${C}/le-long${params({ points: pointsText(points), cat: opts.cat, corridor: opts.corridor,
    limit: opts.limit, mode: opts.mode, avoid: opts.avoid?.join(",") })}`);
}

/** Ce qu'elle a cherché ou montré pour toi (`ref` d'une note `look` ou `map`). */
export function fetchRegard(seq: string): Promise<Regard> {
  return getJson(`${C}/regards/${encodeURIComponent(seq)}`);
}

export async function fetchTrips(): Promise<TripSummary[]> {
  const got = await getJson<{ trips: TripSummary[] }>(V);
  return got.trips ?? [];
}

export interface TripValues {
  title?: string;
  start?: string;
  mode?: string;
  avoid?: string[];
}

export function createTrip(values: TripValues & { title: string }, nonce = ""): Promise<Done & { id: string }> {
  return sendJson(V, { ...values }, nonce);
}

export function fetchTrip(id: string): Promise<Trip> {
  return getJson(trip(id));
}

/** Ce que le corps nomme, seulement (`start` vide : plus de date). */
export function changeTrip(id: string, values: TripValues, nonce = ""): Promise<Done> {
  return sendJson(trip(id), { ...values }, nonce);
}

export function removeTrip(id: string, nonce = ""): Promise<Done> {
  return sendJson(`${trip(id)}/supprimer`, {}, nonce);
}

export interface NewStop {
  name: string;
  lat: number;
  lon: number;
  kind?: string;
  day: number;
  /** 0 : la première ; −1 (par défaut) : à la fin du jour. */
  index?: number;
  note?: string;
}

export function addStop(id: string, s: NewStop, nonce = ""): Promise<Done & { id: string }> {
  return sendJson(`${trip(id)}/arrets`, { ...s }, nonce);
}

/** Déplacer un arrêt au jour `day`, à la place `index` de ce jour (parmi les autres arrêts du jour ; −1 : à la fin). */
export function moveStop(id: string, stopId: string, day: number, index: number, nonce = ""): Promise<Done> {
  return sendJson(stop(id, stopId), { day, index }, nonce);
}

/** Sa note (vide : plus de note). */
export function noteStop(id: string, stopId: string, note: string, nonce = ""): Promise<Done> {
  return sendJson(stop(id, stopId), { note }, nonce);
}

export function removeStop(id: string, stopId: string, nonce = ""): Promise<Done> {
  return sendJson(`${stop(id, stopId)}/retirer`, {}, nonce);
}

/** Les tronçons d'un arrêt au suivant, rangés au jour de leur arrivée (503 sans itinéraires). */
export function fetchTripRoute(id: string): Promise<TripRoute> {
  return getJson(`${trip(id)}/trajet`);
}

/** Le meilleur ordre d'un jour, appliqué (son premier et son dernier arrêt restent à leur place). */
export function optimizeDay(id: string, day: number, nonce = ""): Promise<Done & { order: string[] }> {
  return sendJson(`${trip(id)}/ordre`, { day }, nonce);
}

/** Les lieux le long du trajet du voyage (`day` 0 : tout le voyage). */
export function fetchOnRoute(id: string, opts: { cat?: string; day?: number; corridor?: number; limit?: number } = {}): Promise<Along> {
  return getJson(`${trip(id)}/sur-la-route${params({ cat: opts.cat, day: opts.day, corridor: opts.corridor, limit: opts.limit })}`);
}

/** Le voyage en GPX, à télécharger (sur le serveur, avec la session). */
export function tripGpxUrl(id: string): string {
  return apiUrl(`${trip(id)}/gpx`);
}
