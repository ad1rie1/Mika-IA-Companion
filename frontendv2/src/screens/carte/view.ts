/**
 * Carte : ce qui se montre, sans DOM ni réseau — Explorer (la recherche, les catégories, « Autour de moi » / « Dans
 * cette zone », les lieux, la fiche d'un lieu), Itinéraire (ses points, son mode, ce qu'il évite, le résultat et ses
 * consignes), Voyages (les cartes de la liste, l'éditeur jour par jour — la note d'un arrêt, qu'on corrige en place —,
 * « Sur la route » et ses épingles secondaires sur la carte, les actions d'un voyage dans la barre de titre, les
 * fenêtres « Nouveau voyage » et « Le voyage »), et le cadre de la carte. Le balisage et les mots sont ceux de la
 * maquette (`frontendv2/maquette/ecrans/carte.js`) ; tout texte venu du serveur (les noms d'OpenStreetMap compris) passe
 * par `h()`.
 */
import {
  CARTE_LIMITS,
  MODES,
  tripGpxUrl,
  type CarteInfo,
  type Coverage,
  type Place,
  type Route,
  type Trip,
  type TripRoute,
  type TripStop,
  type TripSummary,
} from "../../api/carte";
import { miniPlan, type MiniData } from "../../map/cards";
import { drawnScene } from "../../map/drawn";
import { validPoint } from "../../map/mapgeo";
import { slotKey } from "../../map/minis";
import type { Scene, ScenePin } from "../../map/scene";
import { AVOID_LABELS, avoidWords, dayLabel, duration, km, MODE_LABELS, modeWords, placeWhat, plural, tripDates, tripPast } from "../../map/words";
import { h } from "../../shell/dom";
import { ico } from "../../shell/icons";
import { errorBlock } from "../../shared/kit";
import { alongPlace, categoryIcon, cuisineChoices, dayTitle, hersCount, legsByStop } from "./format";
import { coverageLine, photoImg, ratingInline } from "./sources";

// ── Le cadre de la carte ─────────────────────────────────────────────

export interface MapPaneView {
  /** La vraie carte se pose ici (`[data-carte-map]`) ; sinon le plan dessiné de la scène. */
  live: boolean;
  scene: Scene;
  /** Ce que la carte montre, pour un lecteur d'écran. */
  title: string;
  /** Pourquoi un plan plutôt qu'une carte (la raison du serveur, ou ce qui manque ici). */
  why: string;
  /** La légende, en haut à gauche (vide : aucune). */
  legend?: string;
}

export function mapPane(v: MapPaneView): string {
  const legend = v.legend ? `<div class="map-legend" data-legend>${v.legend}</div>` : "";
  if (v.live) {
    return `<section class="pane map-pane"><div class="map-live" data-carte-map role="region" aria-label="${h(v.title)}"></div>${legend}</section>`;
  }
  return `<section class="pane map-pane">${drawnScene(v.scene, { width: 800, height: 560, title: v.title, pad: 48 })}${legend}
    <p class="map-note small muted">${h(`Un plan dessiné, pas une carte : ${v.why}`)}</p></section>`;
}

/** Une légende : son icône, son titre, ce qu'elle dit de plus. */
export function legendMarkup(icon: "search" | "map" | "pin" | "sparkle", title: string, more = ""): string {
  return `${ico(icon, "sm")}<b>${h(title)}</b>${more ? `<span class="muted">${h(more)}</span>` : ""}`;
}

/** Un refus du serveur, dit tel quel (un 503 : ce qui n'est pas prêt ; où le régler, à une opératrice seulement). */
export function failedBlock(title: string, message: string): string {
  return `<div class="empty carte-failed">${ico("alert")}<b>${h(title)}</b><p>${h(message)}</p></div>`;
}

// ── Explorer ─────────────────────────────────────────────────────────

export type Where = "moi" | "zone";

/** Ce qu'une liste de lieux filtre et range (ADR 0244, 0259) : ouvert, ce qu'il offre, sa cuisine, sa note, l'ordre. */
export interface ExplorerFilters {
  open: boolean;
  /** Parmi `features` du serveur (`terrasse`, `vegetarien`…). */
  features: readonly string[];
  /** Une note minimale (4 : « 4 et plus ») ; `null` : aucune. */
  minRating: number | null;
  /** `distance` ou `rating`. */
  sort: string;
  cuisine: string;
}

export const NO_FILTERS: ExplorerFilters = { open: false, features: [], minRating: null, sort: "distance", cuisine: "" };

/** La note minimale que propose la puce « 4 et plus ». */
export const MIN_RATING = 4;

export interface ExplorerView {
  info: CarteInfo | null;
  q: string;
  cat: string;
  where: Where;
  places: Place[];
  addresses: Place[];
  /** Le refus de l'index (503 : pas construit), de la recherche d'adresses, en mots. */
  error: string;
  /** Le refus de la lecture de ce que Mika avait cherché (rien : lu, ou pas encore). */
  regardError?: unknown;
  /** Ce refus dit qu'il n'est plus là (oublié, pas à toi : 404) ; un autre (une panne, 503, 429) se réessaie. */
  regardGone?: boolean;
  addrError: string;
  loading: boolean;
  searched: boolean;
  /** Le lieu choisi (son identifiant dans la liste). */
  sel: string | null;
  /** Ce que Mika a cherché ou montré (une note du chat) : ses lieux, en rose ; où l'ouvrir aussi (son trajet, son
   *  voyage). */
  regard: { title: string; route: boolean; links: { href: string; label: string }[] } | null;
  /** Une phrase de plus, sous la recherche (sa position inconnue…). */
  hint: string;
  map: string;
  /** Les filtres de la recherche (rien : aucun). */
  filters?: ExplorerFilters;
  /** Ce que le cache des avis sait de l'endroit : la ligne « Notes Google Maps lues le … ». */
  coverage?: Coverage | null;
  /** La fiche d'un lieu ouverte, en HTML (`fiche.ts`) : elle remplace la recherche et la liste. */
  fiche?: string;
  /** Les photos déjà montrées (posées sans attendre). */
  seen?: (ref: string) => boolean;
  now?: number;
}

/** L'identifiant d'un lieu dans la liste : le sien, sinon sa place (un point nommé d'un regard n'en a pas). */
export function placeId(p: Place, i: number): string {
  return p.id || `p${i}`;
}

/**
 * La ligne d'un lieu : son nom et sa distance ; sa note Google et le nombre d'avis, son prix, sa cuisine (sinon ce
 * qu'il est) ; ouvert ou fermé (« Ouvert · ferme à 22:30 ») ; une vignette quand il a une photo.
 */
export function placeItem(p: Place, id: string, opts: { on: boolean; mika: boolean; where: Where; seen?: (ref: string) => boolean }): string {
  const dist = typeof p.distance_m === "number" ? km(p.distance_m) : "";
  const what = placeWhat(p);
  const rated = ratingInline(p.rating, p.reviews);
  const parts = rated
    ? [rated, h(p.price?.trim() ?? ""), h(p.cuisine?.trim() || p.kind_fr)]
    : [h(what), h(p.price?.trim() ?? ""), h(p.cuisine?.trim() ?? "")];
  const first = parts.filter(Boolean).join(" · ");
  const open = p.open_text?.trim()
    ? `<span class="li-snip ${p.open_state === "open" ? "ok-txt" : p.open_state === "closed" ? "ko-txt" : ""}">${h(p.open_text.trim())}</span>` : "";
  const img = p.photo && opts.seen ? photoImg(p.photo, "", opts.seen) : "";
  const lead = img ? `<span class="pl-thumb${opts.mika ? " mika" : ""}">${img}</span>`
    : `<span class="pl-dot${opts.mika ? " mika" : ""}">${ico(categoryIcon(p.category), "xs")}</span>`;
  return `<button class="li place${opts.on ? " on" : ""}${opts.mika ? " by-mika" : ""}${img ? " has-thumb" : ""}" type="button" data-lieu="${h(id)}">
    ${lead}
    <span class="li-main"><span class="li-top"><span class="li-title">${h(p.name || "—")}</span>${dist ? `<span class="pl-dist">${h(dist)}</span>` : ""}</span>
    <span class="li-snip">${first}${opts.mika ? `${first ? " · " : ""}<b class="mika-txt">Mika te l'a proposé</b>` : ""}</span>${open}</span></button>`;
}

export function placeCard(p: Place, mika: boolean, where: Where): string {
  const dist = typeof p.distance_m === "number" ? `à ${km(p.distance_m)}${where === "moi" ? " de toi" : ""}` : "";
  const sub = [placeWhat(p), dist].filter(Boolean).join(" · ");
  return `<div class="pane-foot place-card${mika ? " by-mika" : ""}" data-place-card>
    <div class="pc-head"><b>${h(p.name || "—")}</b>${sub ? `<span class="muted">${h(sub)}</span>` : ""}</div>
    <div class="row wrap"><button class="btn sm primary" type="button" data-go-route>${ico("map", "sm")}Itinéraire jusqu'ici</button>
      <button class="btn sm" type="button" data-add-trip>${ico("plus", "sm")}Ajouter au voyage</button>
      <button class="btn sm mika" type="button" data-ask-place>${ico("chat", "sm")}En parler à Mika</button></div></div>`;
}

export function categoryChips(info: CarteInfo | null, current: string, attr = "data-cat"): string {
  return (info?.categories ?? [])
    .map((c) => `<button type="button" class="cat${c.id === current ? " on" : ""}" ${attr}="${h(c.id)}" aria-pressed="${c.id === current}">${h(c.label)}</button>`)
    .join("");
}

function categoryLabel(info: CarteInfo | null, id: string): string {
  return info?.categories.find((c) => c.id === id)?.label ?? "";
}

/** Le titre de ce qu'on cherche : « Dormir · camping », « Camping », « Dormir ». */
export function searchTitle(info: CarteInfo | null, q: string, cat: string): string {
  return [categoryLabel(info, cat), q.trim()].filter(Boolean).join(" · ") || "Lieux";
}

function resultsMarkup(v: ExplorerView): string {
  const out: string[] = [];
  if (v.hint) out.push(`<p class="small muted cs-hint">${ico("info", "xs")}${h(v.hint)}</p>`);
  if (v.regardError) {
    // oublié (404) : « Introuvable. » du serveur redirait le titre, la phrase dit plutôt pourquoi ; une panne se réessaie
    return v.regardGone
      ? failedBlock("Ce que Mika avait cherché n'est plus là", "Elle l'a peut-être oublié, ou c'était pour quelqu'un d'autre.")
      : errorBlock(v.regardError, "Ce que Mika avait cherché ne se lit pas");
  }
  if (v.regard) {
    out.push(`<div class="group-label mika-label">${ico("sparkle", "xs")}Ce que Mika a ${v.regard.route ? "montré" : "cherché"} <span class="cnt">${v.places.length}</span></div>`);
    if (!v.places.length) out.push(`<div class="empty">${ico("map")}<p>Elle n'a gardé aucun lieu de ce regard.</p></div>`);
    out.push(...v.places.map((p, i) => placeItem(p, placeId(p, i), { on: v.sel === placeId(p, i), mika: true, where: v.where, seen: v.seen })));
    return out.join("");
  }
  if (v.addresses.length || v.addrError) {
    out.push(`<div class="group-label">Adresses <span class="muted">· Géoplateforme (IGN), seul le texte part</span></div>`);
    if (v.addrError) out.push(`<p class="small cs-warn">${ico("alert", "xs")}${h(v.addrError)}</p>`);
    out.push(...v.addresses.map((p, i) => placeItem(p, `a${i}`, { on: v.sel === `a${i}`, mika: false, where: v.where })));
  }
  if (v.error) {
    out.push(failedBlock("Les lieux ne se cherchent pas ici", v.error));
    return out.join("");
  }
  if (!v.searched) {
    if (!v.loading) {
      out.push(`<div class="empty">${ico("search")}<b>Cherche un lieu</b><p>Un nom, une adresse, ou une catégorie : autour de toi, ou dans la zone de la carte. Les lieux se cherchent dans l'index de ce serveur : rien ne sort.</p></div>`);
    }
    return out.join("");
  }
  out.push(`<div class="group-label">${h(searchTitle(v.info, v.q, v.cat))} <span class="cnt">${v.places.length}</span><span class="grow"></span>${sortToggle(v)}<span class="muted">index local, rien ne sort</span></div>`);
  const cover = coverageLine(v.coverage, "Notes Google Maps lues", v.now ?? Date.now());
  if (cover) out.push(`<p class="small muted cov-line">${ico("info", "xs")}<span>${h(cover)}</span></p>`);
  if (v.loading && !v.places.length) out.push(`<div class="empty">${ico("refresh")}<p>Recherche…</p></div>`);
  else if (!v.places.length) {
    const filtered = filtersOn(v.filters);
    out.push(`<div class="empty">${ico("search")}<p>${h(`Rien de tel ${v.where === "moi" ? "autour de toi" : "dans cette zone"}${filtered ? " avec ces filtres" : ""}.`)}</p></div>`);
  }
  out.push(...v.places.map((p, i) => placeItem(p, placeId(p, i), { on: v.sel === placeId(p, i), mika: false, where: v.where, seen: v.seen })));
  return out.join("");
}

/** Un filtre au moins est posé. */
export function filtersOn(f: ExplorerFilters | undefined): boolean {
  return !!f && (f.open || f.features.length > 0 || f.minRating !== null || !!f.cuisine.trim());
}

/** L'ordre de la liste : un bouton qui passe de l'un à l'autre (« Les plus proches », « Les mieux notés »). */
function sortToggle(v: ExplorerView): string {
  const sorts = v.info?.sorts ?? [];
  if (sorts.length < 2) return "";
  const now = v.filters?.sort ?? "distance";
  const label = sorts.find((s) => s.id === now)?.label ?? sorts[0].label;
  return `<button class="btn xs ghost sort-btn" type="button" data-sort title="Changer l'ordre de la liste">${ico("sort", "xs")}${h(label)}</button>`;
}

/**
 * Les filtres, sous la recherche : ouvert maintenant, ce que le serveur sait reconnaître (terrasse, végétarien, vegan,
 * accessible…), « 4 et plus » (sa note Google), et la cuisine parmi celles de la liste.
 */
export function filtersMarkup(v: Pick<ExplorerView, "info" | "places" | "filters">): string {
  const f = v.filters ?? NO_FILTERS;
  const chip = (id: string, label: string, on: boolean, icon = "") =>
    `<button type="button" class="cat flt${on ? " on" : ""}" data-flt="${h(id)}" aria-pressed="${on}">${icon}${h(label)}</button>`;
  const chips = [
    chip("open", "Ouvert maintenant", f.open, ico("clock", "xs")),
    ...(v.info?.features ?? []).map((x) => chip(`f:${x.id}`, x.label, f.features.includes(x.id))),
    chip("rating", `${MIN_RATING} et plus`, f.minRating !== null, ico("star", "xs")),
  ].join("");
  const cuisines = cuisineChoices(v.places, f.cuisine);
  const select = cuisines.length
    ? `<select class="flt-select" data-cuisine aria-label="Cuisine"><option value="">Toute cuisine</option>${cuisines
      .map((c) => `<option value="${h(c)}"${c === f.cuisine ? " selected" : ""}>${h(c)}</option>`).join("")}</select>` : "";
  return `<div class="cs-cats cs-flt" role="group" aria-label="Filtres">${chips}${select}</div>`;
}

/** Le lieu choisi de la liste (une adresse : `a<n>`), sinon `null`. */
export function selectedPlace(v: Pick<ExplorerView, "places" | "addresses" | "sel">): Place | null {
  if (!v.sel) return null;
  const a = /^a(\d+)$/.exec(v.sel);
  if (a) return v.addresses[Number(a[1])] ?? null;
  return v.places.find((p, i) => placeId(p, i) === v.sel) ?? null;
}

export function explorerMarkup(v: ExplorerView): string {
  if (v.fiche) return `<div class="split carte-split"><aside class="pane carte-side">${v.fiche}</aside>${v.map}</div>`;
  const sel = selectedPlace(v);
  const filters = !v.regard && (v.q.trim() || v.cat) ? filtersMarkup(v) : "";
  return `<div class="split carte-split">
    <aside class="pane carte-side">
      <div class="cs-search">
        <label class="search-field">${ico("search", "sm")}<input type="search" data-q value="${h(v.q)}" maxlength="200" placeholder="Un lieu, une adresse, un restaurant…" aria-label="Chercher un lieu ou une adresse"></label>
        <div class="cs-cats" role="group" aria-label="Catégories">${categoryChips(v.info, v.cat)}</div>
        <div class="seg" role="group" aria-label="Où chercher">
          <button type="button" aria-pressed="${v.where === "moi"}" data-where="moi">${ico("pin", "sm")}Autour de moi</button>
          <button type="button" aria-pressed="${v.where === "zone"}" data-where="zone">${ico("map", "sm")}Dans cette zone</button></div>
        ${filters}
      </div>
      <div class="pane-scroll" data-results>${resultsMarkup(v)}</div>
      ${sel ? placeCard(sel, !!v.regard, v.where) : v.regard?.links.length
        ? `<div class="pane-foot row wrap">${v.regard.links.map((l) => `<a class="btn sm" href="${h(l.href)}">${ico("chev-right", "sm")}${h(l.label)}</a>`).join("")}</div>` : ""}
    </aside>
    ${v.map}
  </div>`;
}

// ── Itinéraire ───────────────────────────────────────────────────────

export interface ItiPoint {
  /** Ce qu'on a tapé, ou le nom du point choisi. */
  query: string;
  name: string;
  lat: number | null;
  lon: number | null;
}

export interface ItineraryView {
  points: ItiPoint[];
  mode: string;
  avoid: readonly string[];
  route: Route | null;
  /**
   * Ce qui est montré (le trajet calculé, ou celui de Mika) n'est plus celui de ces points : un point retapé et pas
   * encore choisi, un trajet qui se recalcule. Ses consignes se taisent ; « En faire un voyage » et le GPX attendent.
   */
  stale: boolean;
  error: string;
  loading: boolean;
  /** Le point dont on montre les propositions, et elles. */
  suggestFor: number | null;
  suggestions: { label: string; sub: string; mine?: boolean }[];
  /** Ce que les propositions n'ont pas pu dire (les adresses refusées : trop demandées, pas branchées), en mots. */
  suggestNote?: string;
  /** Ce que Mika a calculé (une note du chat), quand on n'a pas recalculé : son résumé. */
  regard: { title: string; distance_m: number | null; duration_s: number | null } | null;
  now: number;
  map: string;
}

export function pointLetter(i: number, n: number): string {
  return i === 0 ? "A" : i === n - 1 ? "B" : String(i);
}

function suggestionsMarkup(v: ItineraryView, i: number): string {
  if (v.suggestFor !== i) return "";
  const list = v.suggestions.length ? `<div class="iti-sugg" role="listbox" aria-label="Propositions">${v.suggestions
    .map((s, j) => `<button class="li place" type="button" role="option" data-pick="${i}:${j}">${ico(s.mine ? "pin" : "search", "sm")}
      <span class="li-main"><span class="li-title">${h(s.label)}</span>${s.sub ? `<span class="li-snip">${h(s.sub)}</span>` : ""}</span></button>`)
    .join("")}</div>` : "";
  const note = v.suggestNote ? `<p class="small cs-warn iti-sugg-note" role="status">${ico("alert", "xs")}${h(`Adresses : ${v.suggestNote}`)}</p>` : "";
  return list + note;
}

/** Les points qu'on a choisis (avec leurs coordonnées). */
export function chosenPoints(points: readonly ItiPoint[]): { name: string; lat: number; lon: number }[] {
  return points.flatMap((p) => (typeof p.lat === "number" && typeof p.lon === "number" ? [{ name: p.name || p.query, lat: p.lat, lon: p.lon }] : []));
}

/** Un point tapé qu'on n'a pas encore choisi dans ses propositions : il n'a pas de coordonnées. */
export function typedPoint(points: readonly ItiPoint[]): boolean {
  return points.some((p) => p.query.trim() !== "" && (typeof p.lat !== "number" || typeof p.lon !== "number"));
}

/** Ce qui fait un itinéraire : ses points choisis dans l'ordre, son mode, ce qu'il évite (en voiture seulement). */
export function itiKey(points: readonly ItiPoint[], mode: string, avoid: readonly string[]): string {
  return JSON.stringify([chosenPoints(points).map((p) => [p.lat, p.lon]), mode, mode === "voiture" ? [...avoid].sort() : []]);
}

function itiActions(v: ItineraryView, more = ""): string {
  const wait = v.stale ? " disabled" : "";
  return `<div class="row wrap"><button class="btn sm primary" type="button" data-iti-trip${wait}>${ico("plus", "sm")}En faire un voyage</button>
      <button class="btn sm" type="button" data-iti-gpx${wait}>${ico("download", "sm")}GPX</button>
      <button class="btn sm mika" type="button" data-iti-ask>${ico("chat", "sm")}Envoyer à Mika</button>${more}</div>`;
}

function resultMarkup(v: ItineraryView): string {
  const chosen = chosenPoints(v.points);
  if (v.error) return `<div class="iti-res ko">${failedBlock("L'itinéraire ne se calcule pas", v.error)}</div>`;
  if (chosen.length < 2) {
    return `<p class="small muted iti-hint">${ico("info", "xs")}Choisis un départ et une arrivée : un lieu, une adresse, ta position.</p>`;
  }
  const typed = typedPoint(v.points);
  const why = v.stale && typed
    ? `<p class="small muted iti-hint">${ico("info", "xs")}Choisis chaque point dans ses propositions : l'itinéraire se recalcule alors.</p>` : "";
  if (v.loading && !v.route && !v.regard) return `<div class="iti-res"><p class="muted">${ico("refresh", "xs")} Calcul de l'itinéraire…</p></div>`;
  const r = v.route;
  if (!r && v.regard) {
    const again = `<button class="btn sm ghost" type="button" data-iti-compute title="Le trajet et ses consignes, calculés de nouveau ici"${v.loading ? " disabled" : ""}>${ico("refresh", "sm")}Recalculer</button>`;
    return `<div class="iti-res mika${v.stale || v.loading ? " stale" : ""}"><div class="iti-big"><b>${h(duration(v.regard.duration_s))}</b><span>${h(km(v.regard.distance_m))}</span></div>
      <div class="muted small">Ce que Mika a calculé : ${h(v.regard.title)}</div>
      ${itiActions(v, again)}</div>${why}`;
  }
  if (!r) return why;
  const facts = [modeWords(v.mode), ...(r.has_toll ? ["avec péages"] : v.mode === "voiture" ? ["sans péage"] : []),
    ...(r.has_ferry ? ["avec un ferry"] : [])];
  const arrive = (() => {
    if (!(r.duration_s > 0)) return "";
    const t = new Date(v.now + r.duration_s * 1000);
    return `arrivée vers ${t.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })} si tu pars maintenant`;
  })();
  return `<div class="iti-res${v.loading || v.stale ? " stale" : ""}">
    <div class="iti-big"><b>${h(duration(r.duration_s))}</b><span>${h(km(r.distance_m))}</span></div>
    <div class="muted small">${h([facts.join(", "), arrive].filter(Boolean).join(" · "))}</div>
    ${itiActions(v)}
  </div>${why}`;
}

export function itineraryMarkup(v: ItineraryView): string {
  const n = v.points.length;
  const points = v.points
    .map((p, i) => {
      const letter = pointLetter(i, n);
      const label = i === 0 ? "Départ" : i === n - 1 ? "Arrivée" : `Étape ${i}`;
      const remove = i > 0 && i < n - 1
        ? `<button class="btn icon ghost sm" type="button" data-iti-remove="${i}" title="Retirer cette étape">${ico("x", "sm")}</button>` : "";
      return `<div class="iti-pt"><span class="iti-dot${i === 0 ? " a" : i === n - 1 ? " b" : ""}">${h(letter)}</span>
        <input type="search" data-pt="${i}" value="${h(p.query)}" maxlength="200" placeholder="${label}" aria-label="${label}" autocomplete="off">${remove}</div>${suggestionsMarkup(v, i)}`;
    })
    .join("");
  const modes = Object.entries(MODE_LABELS)
    .map(([id, label]) => `<button type="button" aria-pressed="${v.mode === id}" data-mode="${id}">${h(label)}</button>`)
    .join("");
  const car = v.mode === "voiture";
  const opts = Object.entries(AVOID_LABELS)
    .map(([id, label]) => `<label class="check"><input type="checkbox" data-avoid="${id}"${v.avoid.includes(id) ? " checked" : ""}${car ? "" : " disabled"}><span>${h(`Éviter ${label}`)}</span></label>`)
    .join("");
  const steps = v.stale ? [] : (v.route?.legs ?? []).flatMap((l) => l.steps);
  return `<div class="split carte-split">
    <aside class="pane carte-side"><div class="pane-scroll iti">
      <div class="iti-points">${points}
        <div class="row"><button class="btn sm ghost" type="button" data-iti-add${n >= 20 ? " disabled" : ""}>${ico("plus", "sm")}Ajouter une étape</button>
          <button class="btn sm ghost" type="button" data-iti-swap>${ico("sort", "sm")}Inverser</button></div>
      </div>
      <div class="seg" role="group" aria-label="Comment">${modes}</div>
      <div class="iti-opts">${opts}
        ${car ? "" : `<span class="small muted">${h(v.mode === "velo" ? "À vélo, le trajet évite d'office péages et autoroutes." : "À pied, rien à éviter.")}</span>`}</div>
      ${resultMarkup(v)}
      ${steps.length ? `<h2 class="section-title">Consignes <span class="cnt">${steps.length}</span></h2>
        <ol class="iti-steps">${steps.map((s, i) => `<li><span class="st-n">${i + 1}</span><span>${h(s.text)}</span><span class="muted">${h(km(s.distance_m))}</span></li>`).join("")}</ol>` : ""}
      ${v.route ? `<p class="small muted iti-src">${ico("server", "xs")}${h(`Calculé par ${v.route.provider || "le serveur d'itinéraires"}, relayé par ce serveur : il ne voit que les points du trajet, jamais qui tu es.`)}</p>` : ""}
    </div></aside>
    ${v.map}
  </div>`;
}

// ── Voyages ──────────────────────────────────────────────────────────

/** La carte d'un voyage dans la liste : sa miniature (son plan, que la carte remplace quand elle paraît). */
export function tripCard(t: TripSummary, data: MiniData | null, now: number): string {
  const past = tripPast(t.start, t.days, now);
  const dates = tripDates(t.start, t.days, now).replace(/ · passé$/, "");
  const plan = miniPlan(data ?? { title: t.title, sub: "", href: "", scene: { pins: [], lines: [] } });
  return `<a class="trip-card${past ? " passe" : ""}" href="#carte/voyages/${encodeURIComponent(t.id)}">
    <div class="tc-map" data-mini="${h(slotKey("voyages", { kind: "trip", ref: t.id }))}"><span class="mm-map" data-mini-map><span class="mm-plan" data-mini-plan>${plan}</span></span></div>
    <div class="tc-body"><b>${h(t.title || "Sans titre")}</b><span class="muted small">${h(dates || "sans date")}</span>
      <span class="row wrap tc-tags"><span class="tag">${h(plural(t.days, "jour"))}</span><span class="tag">${h(plural(t.stops, "arrêt"))}</span>
      ${t.mika ? `<span class="tag mika">${ico("sparkle")}préparé avec Mika</span>` : ""}${past ? '<span class="tag">passé</span>' : ""}</span></div></a>`;
}

/**
 * Les actions d'un voyage, dans la barre de titre : « Optimiser l'ordre », son GPX, « Demander à Mika » — seulement une
 * fois le voyage lu (`found`) ; pendant sa lecture, ou s'il n'existe pas (404), aucune ne mènerait à rien.
 */
export function tripActions(id: string, found: boolean): string {
  if (!found) return "";
  return `<button class="btn sm" type="button" data-optimize title="Le meilleur ordre des arrêts de chaque jour ; le départ et la nuit ne bougent pas">${ico("refresh", "sm")}<span class="lbl">Optimiser l'ordre</span></button>
        <a class="btn sm" href="${h(tripGpxUrl(id))}" download title="Le tracé et les arrêts, pour un GPS ou une app de navigation">${ico("download", "sm")}<span class="lbl">GPX</span></a>
        <button class="btn sm mika" type="button" data-ask-trip>${ico("sparkle", "sm")}<span class="lbl">Demander à Mika</span></button>`;
}

/** `full` : ce qu'on sait déjà de la miniature d'un voyage (sa carte de la liste dit son dernier changement). */
export function tripsMarkup(trips: readonly TripSummary[], full: (t: TripSummary) => MiniData | null, now: number): string {
  return `<div class="trips">${trips.map((t) => tripCard(t, full(t), now)).join("")}
    <button class="trip-card new" type="button" data-new-trip>${ico("plus", "lg")}<b>Nouveau voyage</b><span class="muted small">ou demande-le à Mika dans le chat</span></button></div>`;
}

export interface TripView {
  trip: Trip;
  /** Le trajet de ces arrêts-ci (jamais celui d'avant un geste), sinon `null`. */
  route: TripRoute | null;
  /** Il se calcule (le voyage s'ouvre, ou ses arrêts ont changé) : ses arrêts sont reliés à vol d'oiseau en attendant. */
  routePending?: boolean;
  /** Le refus du trajet (503 sans itinéraires, 429), en mots. */
  routeError: string;
  /** « Sur la route » ; `sending` : le lieu qui s'ajoute (son bouton attend). */
  onRoute: { cat: string; places: Place[]; error: string; loading: boolean; routed: boolean; sending?: number | null };
  /** L'arrêt dont on écrit la note (un seul à la fois), et ce qu'on a tapé ; aucun : `null`. */
  noting?: { stop: string; draft: string } | null;
  info: CarteInfo | null;
  now: number;
  map: string;
}

function legMarkup(leg: { distance_m: number; duration_s: number } | undefined): string {
  if (!leg) return "";
  return `<li class="leg">${ico("chev-down", "xs")}${h([duration(leg.duration_s), km(leg.distance_m)].filter(Boolean).join(" · "))}</li>`;
}

/**
 * La note d'un arrêt, à part (de qui qu'il soit : « ajouté par Mika » n'est qu'une marque, la note n'est pas sa phrase
 * — la personne a pu l'écrire ou la corriger) ; l'arrêt qu'on note : son champ en place, prérempli.
 */
function stopNoteMarkup(s: TripStop, noting: TripView["noting"]): string {
  if (noting?.stop !== s.id) return s.note ? `<span class="small stop-note">${h(s.note)}</span>` : "";
  const label = `La note de ${s.name || "cet arrêt"}`;
  return `<span class="stop-note-edit" role="group" aria-label="${h(label)}">
                <input type="text" class="stop-note-input" data-note-input="${h(s.id)}" value="${h(noting.draft)}" maxlength="${CARTE_LIMITS.note}" placeholder="Réserver avant le 15, arriver avant 17 h…" aria-label="${h(label)}" autocomplete="off">
                <span class="row wrap"><button class="btn sm primary" type="button" data-note-save="${h(s.id)}">${ico("check", "sm")}Enregistrer</button>
                  <button class="btn sm ghost" type="button" data-note-cancel="${h(s.id)}">Annuler</button></span>
                <span class="small muted">Vidée, la note s'efface. Entrée enregistre, Échap annule.</span></span>`;
}

/** Les actions d'un arrêt : le noter (le crayon : un champ en place), le retirer. */
function stopActions(s: TripStop, editing: boolean): string {
  const noteTitle = s.note ? "Corriger ou effacer sa note" : "Noter cet arrêt";
  return `<span class="stop-acts"><button class="btn icon ghost sm" type="button" title="${noteTitle}" aria-label="${h(`Noter ${s.name || "cet arrêt"}`)}" aria-expanded="${editing}" data-note-stop="${h(s.id)}">${ico("pen", "sm")}</button>
                <button class="btn icon ghost sm stop-x" type="button" title="Retirer cet arrêt" data-retirer="${h(s.id)}">${ico("x", "sm")}</button></span>`;
}

// ── « Sur la route », sur la carte ───────────────────────────────────

const ALONG_PIN = /^along:(\d+)$/;

/** L'épingle d'un lieu de « Sur la route » : un identifiant à part de ceux des arrêts (`along:<sa place dans la liste>`). */
export function alongPinId(i: number): string {
  return `along:${i}`;
}

/** La place dans la liste du lieu de « Sur la route » qu'une épingle vise ; un arrêt : `null`. */
export function alongIndexOf(pinId: string): number | null {
  const m = ALONG_PIN.exec(pinId);
  return m ? Number(m[1]) : null;
}

/** La ligne d'un lieu de « Sur la route » : « jour 1 · Camping · Sévrier · à 3 km de la route » — le jour d'abord. */
export function alongFacts(trip: Trip, route: TripRoute | null, p: Place): string {
  const far = typeof p.distance_m === "number" ? (p.distance_m < 150 ? "sur la route" : `à ${km(p.distance_m)} de la route`) : "";
  return [`jour ${alongPlace(trip, route, p.along_m)[0]}`, placeWhat(p), far].filter(Boolean).join(" · ");
}

/** La liste de « Sur la route » montre ses lieux (deux arrêts au moins, une catégorie, ni en recherche ni refusée). */
function alongShown(v: Pick<TripView, "trip" | "onRoute">): boolean {
  const stops = v.trip.days.reduce((a, d) => a + d.stops.length, 0);
  const along = v.onRoute;
  return stops >= 2 && !along.error && !along.loading && !!along.cat && along.places.length > 0;
}

/**
 * Les lieux que montre « Sur la route », en épingles secondaires (plus petites, sans numéro) : sur la carte du voyage, à
 * côté de ses arrêts ; un clic sur l'une retrouve sa ligne (`alongIndexOf`). La liste cachée, aucune.
 */
export function alongPins(v: Pick<TripView, "trip" | "route" | "onRoute">): ScenePin[] {
  if (!alongShown(v)) return [];
  return v.onRoute.places.flatMap((p, i): ScenePin[] => (validPoint(p.lat, p.lon)
    ? [{ id: alongPinId(i), lat: p.lat, lon: p.lon, minor: true, title: `${p.name || "—"} · ${alongFacts(v.trip, v.route, p)}` }]
    : []));
}

export function tripEditorMarkup(v: TripView): string {
  const t = v.trip;
  const legs = legsByStop(v.route);
  const hers = hersCount(t);
  const dates = tripDates(t.start, t.days.length, v.now);
  const head = [dates || "sans date", modeWords(t.mode), avoidWords(t.avoid, t.mode)].filter(Boolean).join(" · ");
  const totals = v.route && v.route.distance_m > 0
    ? `<span class="tag">${h(km(v.route.distance_m))}</span><span class="tag">${h(`${duration(v.route.duration_s)} de route`)}</span>` : "";
  let n = 0;
  const days = t.days
    .map((d) => {
      const routeDay = v.route?.days.find((x) => x.n === d.n);
      const facts = [d.date ? dayLabel(d.date, v.now) : "", routeDay && routeDay.distance_m > 0 ? km(routeDay.distance_m) : "",
        routeDay && routeDay.duration_s > 0 ? duration(routeDay.duration_s) : ""].filter(Boolean).join(" · ");
      const title = dayTitle(d.stops);
      const stops = d.stops
        .map((s) => {
          n += 1;
          const mika = s.by === "mika";
          const what = [s.kind].filter(Boolean).join(" · ");
          const editing = v.noting?.stop === s.id;
          return `${legMarkup(legs.get(s.id))}
            <li class="stop${mika ? " by-mika" : ""}${editing ? " noting" : ""}" data-stop="${h(s.id)}" data-day="${d.n}">
              <button class="grip" type="button" data-grip="${h(s.id)}" title="Glisser pour changer l'ordre (ou les flèches du clavier)" aria-label="Déplacer ${h(s.name)}">${ico("grip", "sm")}</button>
              <span class="stop-n">${n}</span><span class="stop-main"><b>${h(s.name || "—")}</b>
              ${what ? `<span class="small muted">${h(what)}</span>` : ""}
              ${mika ? `<span class="stop-mika">${ico("sparkle", "xs")}ajouté par Mika</span>` : ""}
              ${stopNoteMarkup(s, v.noting)}</span>
              ${stopActions(s, editing)}</li>`;
        })
        .join("");
      return `<section class="trip-day" data-day-box="${d.n}">
        <div class="trip-day-head"><b>Jour ${d.n}${title ? ` · ${h(title)}` : ""}</b>${facts ? `<span class="muted small">${h(facts)}</span>` : ""}</div>
        <ol class="stops" data-day-list="${d.n}">${stops || `<li class="stop-empty small muted">Aucun arrêt ce jour-là.</li>`}</ol>
        <button class="btn sm ghost add-stop" type="button" data-add-stop="${d.n}">${ico("plus", "sm")}Ajouter un arrêt</button></section>`;
    })
    .join("");
  const nextDay = t.days.length + 1;
  const along = v.onRoute;
  const stopsCount = t.days.reduce((a, d) => a + d.stops.length, 0);
  const onRoute = stopsCount < 2 ? "" : `<section class="onroute"><h2 class="section-title">Sur la route <span class="muted small">à moins de 10 km du trajet · index local</span></h2>
      <div class="cs-cats">${categoryChips(v.info, along.cat, "data-onroute")}</div>
      ${along.error ? failedBlock("Les lieux du trajet ne se cherchent pas", along.error)
        : along.loading ? `<p class="small muted">${ico("refresh", "xs")} Recherche le long du trajet…</p>`
        : !along.cat ? `<p class="small muted">Choisis ce que tu cherches le long du trajet.</p>`
        : along.places.length ? `<ul class="onroute-list">${along.places.map((p, i) => `<li data-along-place="${i}"><span class="li-main"><b>${h(p.name || "—")}</b>
            <span class="small muted">${h(alongFacts(t, v.route, p))}</span></span>
            <button class="btn sm" type="button" data-add-along="${i}"${along.sending === i ? " disabled" : ""}>${ico("plus", "sm")}Ajouter</button></li>`).join("")}</ul>${along.routed ? "" : `<p class="small muted">Sans itinéraires : le long des arrêts reliés à vol d'oiseau.</p>`}`
        : `<p class="small muted">Rien de tel le long du trajet.</p>`}</section>`;
  return `<div class="split carte-split voyage">
    <aside class="pane carte-side"><div class="pane-scroll trip">
      <div class="trip-head"><a class="btn sm ghost" href="#carte/voyages">${ico("chev-left", "sm")}Voyages</a>
        <h2>${h(t.title || "Sans titre")} <button class="btn icon ghost sm" type="button" data-edit-trip title="Modifier le voyage">${ico("pen", "sm")}</button></h2>
        <span class="muted small">${h(head)}</span>
        <div class="row wrap">${totals}<span class="tag">${h(plural(t.days.length, "jour"))}</span>
          ${t.mika || hers ? `<span class="tag mika">${ico("sparkle")}préparé avec Mika</span>` : ""}</div>
        ${v.routeError ? `<p class="small cs-warn">${ico("alert", "xs")}${h(v.routeError)}</p>`
          : v.routePending ? `<p class="small muted" role="status">${ico("refresh", "xs")} Le trajet se calcule…</p>` : ""}</div>
      ${days}
      <button class="btn sm ghost add-day" type="button" data-add-stop="${nextDay}"${nextDay > 30 ? " disabled" : ""}>${ico("plus", "sm")}Ajouter un jour</button>
      ${onRoute}
    </div></aside>
    ${v.map}</div>`;
}

// ── Les fenêtres d'un voyage ─────────────────────────────────────────

export interface TripFormView {
  /** « Le voyage » (un voyage qu'on modifie) ; sinon « Nouveau voyage ». */
  edit: boolean;
  title: string;
  start: string;
  mode: string;
  avoid: readonly string[];
  /** « Nouveau voyage » depuis un lieu (« Ajouter au voyage ») : son premier arrêt. */
  first?: Pick<Place, "name" | "town"> | null;
}

/**
 * Ce qu'un voyage en voiture évite : les cases d'`AVOID_LABELS`, cachées hors voiture (le `select` du mode les montre
 * ou les cache : `[data-trip-mode]`, `[data-trip-avoid]`).
 */
export function tripAvoidField(mode: string, avoid: readonly string[]): string {
  const checks = Object.entries(AVOID_LABELS)
    .map(([id, label]) => `<label class="check"><input type="checkbox" name="avoid" value="${id}"${avoid.includes(id) ? " checked" : ""}><span>${h(label)}</span></label>`)
    .join("");
  return `<div class="field" role="group" aria-label="En voiture, éviter" data-trip-avoid${mode === "voiture" ? "" : " hidden"}><span>En voiture, éviter</span>${checks}</div>`;
}

/** Le corps de « Nouveau voyage » et de « Le voyage » : un titre, une date, un mode, ce qu'il évite en voiture. */
export function tripFormMarkup(v: TripFormView): string {
  const modes = MODES.map((m) => `<option value="${m}"${v.mode === m ? " selected" : ""}>${h(modeWords(m))}</option>`).join("");
  const first = v.first ? `<p class="small muted">${h(`Premier arrêt : ${v.first.name}${v.first.town ? `, ${v.first.town}` : ""}.`)}</p>` : "";
  return `<form class="stack trip-form" data-trip-form>
        <label class="field"><span>Titre</span><input name="title" maxlength="${CARTE_LIMITS.title}"${v.edit ? "" : ' required placeholder="Les Alpes en cinq jours"'} value="${h(v.title)}"></label>
        <label class="field"><span>Départ <span class="muted">${v.edit ? "(vide : sans date)" : "(facultatif)"}</span></span><input name="start" type="date" value="${h(v.start)}"></label>
        <label class="field"><span>Comment</span><select name="mode" data-trip-mode>${modes}</select></label>
        ${tripAvoidField(v.mode, v.avoid)}
        ${first}
        <p class="small cf-error" data-erreur hidden></p></form>`;
}

/**
 * Le pied de ces fenêtres. « Le voyage » : « Supprimer le voyage » à gauche, « Annuler » et « Enregistrer » à droite —
 * sur un téléphone, la suppression passe seule sur sa ligne (`.trip-delete`, carte.css) et les deux autres restent
 * entiers.
 */
export function tripFormFoot(edit: boolean): string {
  if (!edit) {
    return `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button>
        <button class="btn primary" type="button" data-ok>${ico("plus", "sm")}Créer</button>`;
  }
  return `<button class="btn danger trip-delete" type="button" data-delete>${ico("trash", "sm")}Supprimer le voyage</button><span class="grow"></span>
        <button class="btn" type="button" data-close>Annuler</button><button class="btn primary" type="button" data-ok>${ico("check", "sm")}Enregistrer</button>`;
}
