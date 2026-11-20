/**
 * Carte, fond de carte (celui de toutes les cartes), lieux, itinéraires et voyages, par l'API par personne
 * (`backendv2/docs/protocole-moi.md` § 10 ; le code : `backendv2/src/mika/app/me/maps.py`, ADR 0194 à 0196) ; les
 * fiches des lieux, les événements et les photos (ADR 0259 : OpenStreetMap, l'office de tourisme par DATAtourisme,
 * Google Maps). Le navigateur ne parle qu'à ce serveur : il cherche les lieux dans son index (rien ne sort), une adresse
 * à la Géoplateforme (seul le texte part), un itinéraire au serveur réglé (seuls ses points partent) ; une photo ne vient
 * que de lui (`photoUrl`). Ce qui n'est pas branché répond 503, en mots (`ApiError.message`).
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
 * Les bornes de l'API (`app/me/maps.py`, `contracts/trips.py`) : au-delà, elle refuse (400) — elle ne coupe jamais.
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

/** Un choix d'une liste de l'écran (une catégorie, un filtre, un ordre, un thème), avec son libellé. */
export interface Choice {
  id: string;
  label: string;
}

/** Ce qui est branché sur le serveur, et les catégories dans l'ordre de l'écran. */
export interface CarteInfo {
  places: { ready: boolean; count: number; built: number };
  addresses: { ready: boolean };
  routing: { ready: boolean; provider: string; modes: string[]; avoid: string[] };
  categories: Choice[];
  /** La base des données touristiques (DATAtourisme) : `synced`, sa dernière lecture en ms (ADR 0259). */
  tourism?: { ready: boolean; places: number; events: number; synced: number };
  /** Ce qu'une liste sait filtrer (`terrasse`, `vegetarien`…), dans l'ordre de l'écran. */
  features?: Choice[];
  /** Les ordres d'une liste (`distance`, `rating`). */
  sorts?: Choice[];
  /** Les thèmes des événements, dans l'ordre des puces. */
  themes?: Choice[];
}

/** Ouvert ou fermé à l'instant de la réponse ; `unknown` : des horaires qu'on ne comprend pas. */
export type OpenState = "open" | "closed" | "unknown";

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
  // Seulement quand on les sait (ADR 0244, 0256 ; absents sinon) :
  /** Son objet d'OpenStreetMap (`n123`, `w45`, `r6`), stable d'une reconstruction de l'index à l'autre. */
  osm?: string;
  open_state?: OpenState;
  /** « Ouvert · ferme à 22:30 », à l'instant de la réponse. */
  open_text?: string;
  /** « Italienne, pizza ». */
  cuisine?: string;
  /** Sa note Google, sur 5. */
  rating?: number;
  /** Le nombre de ses avis Google. */
  reviews?: number;
  /** « €€ ». */
  price?: string;
  /** Sa première photo (`p:<hash>`), servie par `…/carte/photo/<ref>`. */
  photo?: string;
  /** Ce qu'il offre parmi `features` (`terrasse`, `vegetarien`…). */
  tags?: string[];
}

/** Ce qu'un cache sait d'un endroit : les notes Google d'une liste (`reviews`), les événements (`coverage`). */
export interface Coverage {
  ready: boolean;
  cells: number;
  loaded: number;
  /** Sa lecture la plus ancienne, en ms (0 : aucune). */
  oldest: number;
  /** Ce qu'il faut en dire, en mots (vide : rien). */
  note: string;
}

/** « Ici » : ta dernière position, celle que ton téléphone a donnée. */
export interface Here {
  lat: number;
  lon: number;
  label: string;
  at: number;
}

/** Une photo relayée par ce serveur (jamais une adresse du dehors), avec ce qu'il faut citer. */
export interface Photo {
  ref: string;
  /** Le chemin qui la sert ; le client le refait depuis `ref` (`photoUrl`), sans jamais suivre celui-ci. */
  path: string;
  /** `google`, `datatourisme`. */
  source: string;
  /** Son auteur, à montrer avec elle (lié à `credit_url`). */
  credit: string;
  credit_url: string;
  /** Sa licence (une photo de DATAtourisme). */
  licence: string;
  caption: string;
  width: number | null;
  height: number | null;
}

/** Un fait d'une source : « Terrasse » « oui ». */
export interface Fact {
  label: string;
  value: string;
}

/** Ce qu'OpenStreetMap dit d'un lieu (l'index de ce serveur). */
export interface OsmPart {
  id: string;
  /** Sa page sur openstreetmap.org (« Corriger sur OpenStreetMap »). */
  url: string;
  address: string;
  phone: string;
  website: string;
  email: string;
  hours: string;
  hours_text: string;
  facts: Fact[];
  wikidata: string;
  wikipedia: string;
  /** La date de l'extrait, `AAAA-MM-JJ`. */
  extract: string;
  attribution: string;
  licence_url: string;
}

/** Ce qu'en dit l'office de tourisme (DATAtourisme, Licence Ouverte). */
export interface TourismPart {
  id: string;
  description: string;
  labels: string[];
  prices: string;
  contacts: Fact[];
  author: string;
  /** Sa mise à jour, `AAAA-MM-JJ`. */
  updated: string;
  url: string;
  photos: Photo[];
  /** « DATAtourisme · Hello Lille, mis à jour le 3 juin 2025 ». */
  attribution: string;
  licence: string;
  licence_url: string;
}

/** Un avis Google : son auteur et son lien, sa date en mots, à montrer avec lui. */
export interface Review {
  rating: number;
  text: string;
  author: string;
  author_url: string;
  at: number;
  /** « il y a 2 semaines ». */
  relative: string;
  language: string;
}

/** Ce que Google Maps dit d'un lieu (le cache de ce serveur) ; `found` faux : rien, et `note` dit pourquoi. */
export interface ReviewsPart {
  source: string;
  /** « Google Maps ». */
  source_label: string;
  found: boolean;
  id: string;
  rating: number | null;
  count: number | null;
  price: string;
  /** « 20–40 € ». */
  price_range: string;
  summary: string;
  /** Ce que Google ajoute à la fiche d'OpenStreetMap. */
  facts: Fact[];
  reviews: Review[];
  photos: Photo[];
  /** Sa page chez Google Maps. */
  url: string;
  /** Quand ce serveur l'a lue, en ms. */
  cached: number;
  note: string;
}

/** Un événement (une liste, une fiche de lieu, un regard) : tous ses champs, toujours. */
export interface EventItem {
  id: string;
  name: string;
  /** Sa prochaine date dans la période, en ISO 8601 (une date, ou une date et une heure à l'heure de Paris). */
  start: string;
  end: string;
  /** « ven. 20 nov. · 19:00–20:30 ». */
  when_text: string;
  /** Où, en mots. */
  place: string;
  lat: number | null;
  lon: number | null;
  distance_m: number | null;
  themes: string[];
  /** `null` : on ne sait pas. */
  free: boolean | null;
  price: string;
  /** `p:<hash>`, ou vide. */
  photo: string;
}

/** La fiche d'un lieu : sa ligne, puis ce qu'en dit chaque source (`null` : elle n'en sait rien). */
export interface PlaceFiche {
  place: Place;
  osm: OsmPart | null;
  tourism: TourismPart | null;
  /** `null` : rien à en dire (pas de clé et rien en cache, ou une sorte dont on ne lit pas les avis). */
  reviews: ReviewsPart | null;
  events: EventItem[];
}

export interface EventDate {
  start: string;
  end: string;
  /** « du 18 nov. au 4 janv. · du mer. au lun. · 10:00–18:00 ». */
  text: string;
  days: string[];
}

/** La fiche d'un événement (DATAtourisme, Licence Ouverte). */
export interface EventFiche {
  event: EventItem;
  description: string;
  dates: EventDate[];
  more_dates: number;
  prices: string;
  contacts: Fact[];
  address: string;
  town: string;
  /** Le lieu nommé où il se tient, s'il est rapproché ; `venue_place` ouvre sa fiche. */
  venue: string;
  venue_place: string;
  author: string;
  updated: string;
  url: string;
  photos: Photo[];
  /** Combien de fiches de DATAtourisme il réunit. */
  merged: number;
  attribution: string;
  licence: string;
  licence_url: string;
}

/** Les identifiants que l'API lit, de la même forme que les siens (`ports/maps.py`). */
export const PLACE_REF = /^(?:l\d{1,15}|[nwr]\d{1,15}|t:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/;
export const EVENT_REF = /^e:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export const PHOTO_REF = /^p:[0-9a-f]{32}$/;

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
  /** Les événements qu'elle a trouvés (`what` : `evenements`) ; ses `places` sont alors vides. */
  events?: Partial<EventItem>[];
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
  /** Faux : sans itinéraires, le long des arrêts reliés à vol d'oiseau. */
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

/**
 * Le fond de carte (ADR 0193), celui de toutes les cartes, servi par le serveur seul : ses tuiles, ses polices et ses
 * icônes sont des chemins de l'API (jamais une adresse du dehors, qui dirait où tu es). `ready` faux : le plan
 * dessiné, `reason` dit pourquoi.
 */
export interface MapInfo {
  ready: boolean;
  reason: string;
  kind?: "vecteur" | "image";
  minzoom?: number;
  maxzoom?: number;
  /** Ouest, sud, est, nord ; `null` : partout. */
  bounds?: [number, number, number, number] | null;
  attribution?: string;
  /** `…/tiles/{z}/{x}/{y}` */
  tiles?: string;
  /** `…/fonts/{fontstack}/{range}.pbf` ; `null` : pas de polices (une carte sans noms). */
  glyphs?: string | null;
  /** `…/sprites/v4` (la planche suit : `/light`, `/dark`) ; `null` : pas d'icônes. */
  sprite?: string | null;
}

/** Servi avec la carte (ADR 0229), et non sous le téléphone : les autres adresses viennent de sa réponse. */
export function fetchMap(): Promise<MapInfo> {
  return getJson(`${MOI}/carte/fond`);
}

/** Ce qu'une liste de lieux sait filtrer et ranger (ADR 0244, 0259). */
export interface PlaceFilters {
  /** Ouvert à l'instant, d'après ses horaires. */
  open?: boolean;
  /** Tous ceux-là (`terrasse`, `vegan`…). */
  features?: readonly string[];
  /** « italienne » (40 caractères). */
  cuisine?: string;
  /** Une note minimale, de 0 à 5 : écarte les lieux sans note. */
  minRating?: number | null;
  /** `distance` ou `rating` (les mieux notés d'abord, ceux sans note à la fin). */
  sort?: string;
}

export interface PlacesQuery extends PlaceFilters {
  q?: string;
  cat?: string;
  /** Un point, ou « ici » : ta dernière position, que le serveur connaît (le téléphone l'a donnée). */
  near?: { lat: number; lon: number } | "ici" | null;
  bbox?: readonly [number, number, number, number] | null;
  limit?: number;
  /** Ce `near` est ta propre position (« Autour de moi » avec ses coordonnées) : le serveur précharge les avis. */
  here?: boolean;
}

/** Une liste de lieux, et ce que le cache des avis sait de l'endroit (avec `near` ou `bbox`). */
export interface PlacesResult {
  places: Place[];
  reviews: Coverage | null;
  /** Avec `near=ici` : où ton téléphone a dit que tu étais. */
  here: Here | null;
}

/** Ce qu'une recherche de lieux envoie (rien de vide, rien qui ne dise rien : une note 0 n'écarte rien). */
export function placesParams(query: PlacesQuery): string {
  const near = query.near === "ici" ? "ici" : query.near ? pointText(query.near.lat, query.near.lon) : "";
  const rating = typeof query.minRating === "number" && Number.isFinite(query.minRating) && query.minRating > 0
    ? String(Math.min(5, query.minRating)) : "";
  return params({
    q: query.q?.trim(),
    cat: query.cat,
    near,
    bbox: query.bbox ? bboxText(query.bbox) : "",
    limit: query.limit,
    open_now: query.open ? 1 : "",
    features: (query.features ?? []).join(","),
    cuisine: query.cuisine?.trim().slice(0, 40),
    min_rating: rating,
    sort: query.sort && query.sort !== "distance" ? query.sort : "",
    // « ici » est déjà ta position : `here` ne dit rien de plus
    here: query.here && near && near !== "ici" ? 1 : "",
  });
}

/** Des lieux de l'index local, avec la couverture des notes : au moins un de `q`, `near`, `bbox`. */
export async function listPlaces(query: PlacesQuery): Promise<PlacesResult> {
  const got = await getJson<{ places?: Place[]; reviews?: Coverage; here?: Here }>(`${C}/lieux${placesParams(query)}`);
  return { places: got.places ?? [], reviews: got.reviews ?? null, here: got.here ?? null };
}

/** Des lieux de l'index local : au moins un de `q`, `near`, `bbox`. */
export async function searchPlaces(query: PlacesQuery): Promise<Place[]> {
  return (await listPlaces(query)).places;
}

/** La fiche d'un lieu (`l<n>`, `n123`/`w45`/`r6`, `t:<uuid>`) : chaque source, et les événements tout près. */
export function fetchPlace(id: string): Promise<PlaceFiche> {
  return getJson(`${C}/lieu/${encodeURIComponent(id)}`);
}

/**
 * « Actualiser » : sa fiche relue tout de suite chez Google et à l'office de tourisme. Ce qui n'a pas pu se relire lève
 * un 503 en mots (ce qui l'a pu est gardé : relire la fiche).
 */
export function refreshPlace(id: string): Promise<Done & PlaceFiche> {
  return sendJson(`${C}/lieu/${encodeURIComponent(id)}/actualiser`, {});
}

/** Ce que cherche la liste des événements. */
export interface EventsQuery {
  /** Un point, ou « ici » (ta dernière position). */
  near?: { lat: number; lon: number } | "ici" | null;
  bbox?: readonly [number, number, number, number] | null;
  /** Autour de `near`, en mètres (500 à 100 000 ; le serveur prend 20 000). */
  radius?: number;
  /** `AAAA-MM-JJ`, à l'heure de Paris. */
  start?: string;
  end?: string;
  themes?: readonly string[];
  q?: string;
  /** Gratuits seulement. */
  free?: boolean;
  limit?: number;
}

export interface EventsResult {
  events: EventItem[];
  /** Ce que la base sait de l'endroit, au même rayon. */
  coverage: Coverage | null;
  here: Here | null;
}

export function eventsParams(query: EventsQuery): string {
  const near = query.near === "ici" ? "ici" : query.near ? pointText(query.near.lat, query.near.lon) : "";
  return params({
    near,
    bbox: query.bbox ? bboxText(query.bbox) : "",
    radius: near ? query.radius : undefined,
    start: query.start,
    end: query.end,
    themes: (query.themes ?? []).join(","),
    q: query.q?.trim(),
    free: query.free ? 1 : "",
    limit: query.limit,
  });
}

/** Les événements à venir (DATAtourisme) : au moins un de `near`, `bbox`, `q`. */
export async function listEvents(query: EventsQuery): Promise<EventsResult> {
  const got = await getJson<{ events?: EventItem[]; coverage?: Coverage; here?: Here }>(`${C}/evenements${eventsParams(query)}`);
  return { events: got.events ?? [], coverage: got.coverage ?? null, here: got.here ?? null };
}

/** La fiche d'un événement (`e:<uuid>`). */
export function fetchEvent(id: string): Promise<EventFiche> {
  return getJson(`${C}/evenement/${encodeURIComponent(id)}`);
}

/**
 * L'adresse d'une photo relayée, refaite depuis sa référence (`p:<32 chiffres hexadécimaux>`) : jamais le chemin ni une
 * adresse donnée par la réponse — une image ne vient que de ce serveur. Une autre forme : `null`, rien à montrer.
 */
export function photoUrl(ref: string): string | null {
  return PHOTO_REF.test(ref) ? apiUrl(`${C}/photo/${ref}`) : null;
}

/** Une adresse (Géoplateforme, relayée : seul ce texte part ; 3 à 200 caractères). */
export async function searchAddresses(q: string, limit = 5): Promise<Place[]> {
  const got = await getJson<{ places: Place[] }>(`${C}/adresses${params({ q: q.trim(), limit })}`);
  return got.places ?? [];
}

export function fetchRoute(points: readonly { lat: number; lon: number }[], mode: string, avoid: readonly string[] = []): Promise<Route> {
  return getJson(`${C}/itineraire${params({ points: pointsText(points), mode, avoid: avoid.join(",") })}`);
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
