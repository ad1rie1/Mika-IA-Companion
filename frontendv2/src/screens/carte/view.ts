/**
 * Carte : ce qui se montre, sans DOM ni réseau — Explorer (la recherche, les catégories, « Autour de moi » / « Dans
 * cette zone », les lieux, la fiche d'un lieu), Itinéraire (ses points, son mode, ce qu'il évite, le résultat et ses
 * consignes), Voyages (les cartes de la liste, l'éditeur jour par jour, « Sur la route »), et le cadre de la carte. Le
 * balisage et les mots sont ceux de la maquette (`frontendv2/maquette/ecrans/carte.js`) ; tout texte venu du serveur
 * (les noms d'OpenStreetMap compris) passe par `h()`.
 */
import type { CarteInfo, Place, Route, Trip, TripRoute, TripSummary } from "../../api/carte";
import { miniPlan, type MiniData } from "../../map/cards";
import { drawnScene } from "../../map/drawn";
import { slotKey } from "../../map/minis";
import type { Scene } from "../../map/scene";
import { avoidWords, dayLabel, duration, km, MODE_LABELS, modeWords, placeWhat, plural, tripDates, tripPast } from "../../map/words";
import { h } from "../../shell/dom";
import { ico } from "../../shell/icons";
import { alongPlace, categoryIcon, dayTitle, hersCount, legsByStop } from "./format";

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

export interface ExplorerView {
  info: CarteInfo | null;
  q: string;
  cat: string;
  where: Where;
  places: Place[];
  addresses: Place[];
  /** Le refus de l'index (503 : pas construit), de la recherche d'adresses, en mots. */
  error: string;
  /** Ce que Mika avait cherché ne se lit plus (oublié, pas à toi : 404), en mots. */
  regardError?: string;
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
}

/** L'identifiant d'un lieu dans la liste : le sien, sinon sa place (un point nommé d'un regard n'en a pas). */
export function placeId(p: Place, i: number): string {
  return p.id || `p${i}`;
}

export function placeItem(p: Place, id: string, opts: { on: boolean; mika: boolean; where: Where }): string {
  const dist = typeof p.distance_m === "number" ? km(p.distance_m) : "";
  const what = placeWhat(p);
  return `<button class="li place${opts.on ? " on" : ""}${opts.mika ? " by-mika" : ""}" type="button" data-lieu="${h(id)}">
    <span class="pl-dot${opts.mika ? " mika" : ""}">${ico(categoryIcon(p.category), "xs")}</span>
    <span class="li-main"><span class="li-top"><span class="li-title">${h(p.name || "—")}</span>${dist ? `<span class="pl-dist">${h(dist)}</span>` : ""}</span>
    <span class="li-snip">${h(what)}${opts.mika ? `${what ? " · " : ""}<b class="mika-txt">Mika te l'a proposé</b>` : ""}</span></span></button>`;
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
  if (v.regardError) return failedBlock("Ce que Mika avait cherché n'est plus là", v.regardError);
  if (v.regard) {
    out.push(`<div class="group-label mika-label">${ico("sparkle", "xs")}Ce que Mika a ${v.regard.route ? "montré" : "cherché"} <span class="cnt">${v.places.length}</span></div>`);
    if (!v.places.length) out.push(`<div class="empty">${ico("map")}<p>Elle n'a gardé aucun lieu de ce regard.</p></div>`);
    out.push(...v.places.map((p, i) => placeItem(p, placeId(p, i), { on: v.sel === placeId(p, i), mika: true, where: v.where })));
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
  out.push(`<div class="group-label">${h(searchTitle(v.info, v.q, v.cat))} <span class="cnt">${v.places.length}</span><span class="grow"></span><span class="muted">index local, rien ne sort</span></div>`);
  if (v.loading && !v.places.length) out.push(`<div class="empty">${ico("refresh")}<p>Recherche…</p></div>`);
  else if (!v.places.length) out.push(`<div class="empty">${ico("search")}<p>Rien de tel ${v.where === "moi" ? "autour de toi" : "dans cette zone"}.</p></div>`);
  out.push(...v.places.map((p, i) => placeItem(p, placeId(p, i), { on: v.sel === placeId(p, i), mika: false, where: v.where })));
  return out.join("");
}

/** Le lieu choisi de la liste (une adresse : `a<n>`), sinon `null`. */
export function selectedPlace(v: Pick<ExplorerView, "places" | "addresses" | "sel">): Place | null {
  if (!v.sel) return null;
  const a = /^a(\d+)$/.exec(v.sel);
  if (a) return v.addresses[Number(a[1])] ?? null;
  return v.places.find((p, i) => placeId(p, i) === v.sel) ?? null;
}

export function explorerMarkup(v: ExplorerView): string {
  const sel = selectedPlace(v);
  return `<div class="split carte-split">
    <aside class="pane carte-side">
      <div class="cs-search">
        <label class="search-field">${ico("search", "sm")}<input type="search" data-q value="${h(v.q)}" maxlength="200" placeholder="Un lieu, une adresse, un restaurant…" aria-label="Chercher un lieu ou une adresse"></label>
        <div class="cs-cats" role="group" aria-label="Catégories">${categoryChips(v.info, v.cat)}</div>
        <div class="seg" role="group" aria-label="Où chercher">
          <button type="button" aria-pressed="${v.where === "moi"}" data-where="moi">${ico("pin", "sm")}Autour de moi</button>
          <button type="button" aria-pressed="${v.where === "zone"}" data-where="zone">${ico("map", "sm")}Dans cette zone</button></div>
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
  const opt = (id: string, label: string) =>
    `<label class="check"><input type="checkbox" data-avoid="${id}"${v.avoid.includes(id) ? " checked" : ""}${car ? "" : " disabled"}><span>${label}</span></label>`;
  const steps = v.stale ? [] : (v.route?.legs ?? []).flatMap((l) => l.steps);
  return `<div class="split carte-split">
    <aside class="pane carte-side"><div class="pane-scroll iti">
      <div class="iti-points">${points}
        <div class="row"><button class="btn sm ghost" type="button" data-iti-add${n >= 20 ? " disabled" : ""}>${ico("plus", "sm")}Ajouter une étape</button>
          <button class="btn sm ghost" type="button" data-iti-swap>${ico("sort", "sm")}Inverser</button></div>
      </div>
      <div class="seg" role="group" aria-label="Comment">${modes}</div>
      <div class="iti-opts">${opt("peages", "Éviter les péages")}${opt("autoroutes", "Éviter les autoroutes")}${opt("ferries", "Éviter les ferries")}
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
  info: CarteInfo | null;
  now: number;
  map: string;
}

function legMarkup(leg: { distance_m: number; duration_s: number } | undefined): string {
  if (!leg) return "";
  return `<li class="leg">${ico("chev-down", "xs")}${h([duration(leg.duration_s), km(leg.distance_m)].filter(Boolean).join(" · "))}</li>`;
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
          return `${legMarkup(legs.get(s.id))}
            <li class="stop${mika ? " by-mika" : ""}" data-stop="${h(s.id)}" data-day="${d.n}">
              <button class="grip" type="button" data-grip="${h(s.id)}" title="Glisser pour changer l'ordre (ou les flèches du clavier)" aria-label="Déplacer ${h(s.name)}">${ico("grip", "sm")}</button>
              <span class="stop-n">${n}</span><span class="stop-main"><b>${h(s.name || "—")}</b>
              ${what ? `<span class="small muted">${h(what)}</span>` : ""}
              ${mika ? `<span class="stop-mika">${ico("sparkle", "xs")}ajouté par Mika${s.note ? ` : « ${h(s.note)} »` : ""}</span>` : s.note ? `<span class="small stop-note">${h(s.note)}</span>` : ""}</span>
              <button class="btn icon ghost sm stop-x" type="button" title="Retirer cet arrêt" data-retirer="${h(s.id)}">${ico("x", "sm")}</button></li>`;
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
        : along.places.length ? `<ul class="onroute-list">${along.places.map((p, i) => `<li><span class="li-main"><b>${h(p.name || "—")}</b>
            <span class="small muted">${h([placeWhat(p), typeof p.distance_m === "number" ? (p.distance_m < 150 ? "sur la route" : `à ${km(p.distance_m)} de la route`) : "",
              `jour ${alongPlace(t, v.route, p.along_m)[0]}`].filter(Boolean).join(" · "))}</span></span>
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
