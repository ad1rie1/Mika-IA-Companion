/**
 * Carte › Événements : ce qui se calcule et se montre sans DOM ni réseau (ADR 0259 ; `protocole-moi.md` § 10) — quand
 * chercher (aujourd'hui, ce week-end, cette semaine, des dates), les événements groupés par jour, leur ligne, la
 * couverture de la zone, le jour d'un voyage où un événement tombe, la phrase qu'on prépare pour Mika. Les événements
 * viennent des offices de tourisme, par DATAtourisme : une base de ce serveur, lue par cases autour des personnes.
 */
import type { CarteInfo, Choice, Coverage, EventItem } from "../../api/carte";
import { isoDay, isoOf, km } from "../../map/words";
import { h } from "../../shell/dom";
import { ico } from "../../shell/icons";
import { errorBlock } from "../../shared/kit";
import { priceWords, themeWords } from "./fiche";
import { coverageLine, photoImg } from "./sources";
import { failedBlock, legendMarkup, type Where } from "./view";

// ── Quand ────────────────────────────────────────────────────────────

export type WhenKind = "today" | "weekend" | "week" | "dates";

export const WHEN_LABELS: ReadonlyArray<readonly [WhenKind, string]> = [
  ["today", "Aujourd'hui"], ["weekend", "Ce week-end"], ["week", "Cette semaine"], ["dates", "Des dates…"],
];

function addDays(d: Date, n: number): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
}

/**
 * Les jours d'une recherche, `AAAA-MM-JJ` (à l'heure locale) : aujourd'hui ; ce week-end (le samedi et le dimanche qui
 * viennent — un samedi, lui et demain ; un dimanche, lui seul) ; cette semaine (jusqu'au dimanche ; un dimanche, la
 * semaine qui vient) ; des dates (celles qu'on a choisies, remises dans l'ordre ; une seule : ce jour-là).
 */
export function whenRange(kind: WhenKind, now: number, dates: { start: string; end: string } = { start: "", end: "" }): { start: string; end: string } {
  const t = new Date(now);
  const today = new Date(t.getFullYear(), t.getMonth(), t.getDate());
  const dow = today.getDay(); // 0 : dimanche
  if (kind === "today") return { start: isoOf(today), end: isoOf(today) };
  if (kind === "weekend") {
    if (dow === 0) return { start: isoOf(today), end: isoOf(today) };
    const saturday = addDays(today, 6 - dow);
    return { start: isoOf(saturday), end: isoOf(addDays(saturday, 1)) };
  }
  if (kind === "week") return { start: isoOf(today), end: isoOf(addDays(today, dow === 0 ? 7 : 7 - dow)) };
  const a = isoDay(dates.start) ? dates.start : "";
  const b = isoDay(dates.end) ? dates.end : "";
  if (!a && !b) return { start: isoOf(today), end: isoOf(addDays(today, 6)) };
  if (!a || !b) return { start: a || b, end: a || b };
  return a <= b ? { start: a, end: b } : { start: b, end: a };
}

// ── Les jours ────────────────────────────────────────────────────────

const WEEKDAYS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];
const WEEKDAYS_SHORT = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
const MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
const MONTHS_SHORT = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

/** Le jour d'un événement (`AAAA-MM-JJ`), de sa prochaine date (`start`, une date ou une date et une heure). */
export function eventDayOf(e: Pick<EventItem, "start">): string {
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(e.start ?? "");
  return m && isoDay(m[1]) ? m[1] : "";
}

/** La tête d'un jour : « Aujourd'hui · vendredi 20 novembre », « Demain · samedi 21 novembre », « Lundi 23 novembre ». */
export function dayHeading(iso: string, now: number): string {
  const d = isoDay(iso);
  if (!d) return "Plus tard";
  const t = new Date(now);
  const today = new Date(t.getFullYear(), t.getMonth(), t.getDate());
  const diff = Math.round((d.getTime() - today.getTime()) / 86_400_000);
  const year = d.getFullYear() !== today.getFullYear() ? ` ${d.getFullYear()}` : "";
  const day = `${WEEKDAYS[d.getDay()]} ${d.getDate() === 1 ? "1er" : d.getDate()} ${MONTHS[d.getMonth()]}${year}`;
  if (diff === 0) return `Aujourd'hui · ${day}`;
  if (diff === 1) return `Demain · ${day}`;
  return day[0].toUpperCase() + day.slice(1);
}

/** « sam. 21 nov. » d'un jour : ce par quoi commence le `when_text` d'un événement de ce jour-là. */
function shortDay(iso: string): string {
  const d = isoDay(iso);
  return d ? `${WEEKDAYS_SHORT[d.getDay()]} ${d.getDate() === 1 ? "1er" : d.getDate()} ${MONTHS_SHORT[d.getMonth()]}` : "";
}

/** Son quand, sous la tête de son jour : sans le jour qu'elle dit déjà (« sam. 21 nov. · 19:00–22:00 » → « 19:00–22:00 »). */
export function whenInDay(e: Pick<EventItem, "when_text" | "start">): string {
  const text = (e.when_text ?? "").trim();
  const day = shortDay(eventDayOf(e));
  return day && text.startsWith(`${day} · `) ? text.slice(day.length + 3) : text;
}

export interface EventDayGroup {
  /** `AAAA-MM-JJ` (vide : une date illisible, à la fin). */
  day: string;
  title: string;
  events: EventItem[];
}

/** Les événements groupés par jour, dans l'ordre du serveur (les plus tôt d'abord, puis les plus proches). */
export function eventDays(events: readonly EventItem[], now: number): EventDayGroup[] {
  const groups = new Map<string, EventItem[]>();
  for (const e of events) {
    const day = eventDayOf(e);
    const list = groups.get(day);
    if (list) list.push(e);
    else groups.set(day, [e]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => (a === b ? 0 : !a ? 1 : !b ? -1 : a < b ? -1 : 1))
    .map(([day, list]) => ({ day, title: dayHeading(day, now), events: list }));
}

// ── Un événement et un voyage ────────────────────────────────────────

/**
 * Le jour d'un voyage où tombe un événement (« Ajouter au voyage », au bon jour) : `start` (sa date de départ) et
 * `days` (combien de jours) ; hors du voyage ou sans date : son dernier jour (−1).
 */
export function eventTripDay(trip: { start: string; days: number }, e: Pick<EventItem, "start">): number {
  const first = isoDay(trip.start ?? "");
  const day = isoDay(eventDayOf(e));
  if (!first || !day) return -1;
  const n = Math.round((day.getTime() - first.getTime()) / 86_400_000) + 1;
  return n >= 1 && n <= Math.max(1, trip.days) ? n : -1;
}

/** « En parler à Mika » d'un événement : la phrase qu'on lui prépare. */
export function askAboutEvent(e: Pick<EventItem, "name" | "when_text" | "place">): string {
  const what = [e.when_text, e.place].map((x) => x?.trim()).filter(Boolean).join(", ");
  return `Tu as vu « ${e.name} »${what ? ` (${what})` : ""} ? `;
}

/** Les libellés des thèmes, depuis ce que le serveur sait (`GET /carte` : `themes`). */
export function themeLabels(info: CarteInfo | null): Map<string, string> {
  return new Map((info?.themes ?? []).map((t) => [t.id, t.label]));
}

// ── L'onglet ─────────────────────────────────────────────────────────

export interface EventsView {
  info: CarteInfo | null;
  q: string;
  when: WhenKind;
  /** Les dates choisies (« Des dates… »). */
  dates: { start: string; end: string };
  themes: readonly string[];
  free: boolean;
  where: Where;
  events: EventItem[];
  coverage: Coverage | null;
  error: string;
  loading: boolean;
  searched: boolean;
  /** L'événement choisi (son identifiant). */
  sel: string | null;
  hint: string;
  /** Ce que Mika a trouvé (un de ses regards) : ses événements, en rose. */
  regard: { title: string } | null;
  regardError?: unknown;
  regardGone?: boolean;
  /** La fiche ouverte, en HTML (`fiche.ts`) : elle remplace la liste. */
  fiche: string;
  seen: (ref: string) => boolean;
  now: number;
  map: string;
}

/** La ligne d'un événement : son nom, son quand et son lieu, son prix, sa distance, une vignette s'il a une photo. */
export function eventItem(e: EventItem, o: { on: boolean; mika: boolean; themes: ReadonlyMap<string, string>; seen: (ref: string) => boolean; inDay: boolean }): string {
  const dist = typeof e.distance_m === "number" ? km(e.distance_m) : "";
  const theme = themeWords({ themes: e.themes.slice(0, 1) }, o.themes);
  const when = o.inDay ? whenInDay(e) : e.when_text;
  const line = [theme, when, e.place].map((x) => x?.trim()).filter(Boolean).join(" · ");
  const price = priceWords(e);
  const img = e.photo ? photoImg(e.photo, "", o.seen) : "";
  const lead = img ? `<span class="pl-thumb">${img}</span>` : `<span class="pl-dot${o.mika ? " mika" : ""}">${ico("calendar", "xs")}</span>`;
  return `<button class="li place ev${o.on ? " on" : ""}${o.mika ? " by-mika" : ""}" type="button" data-ev="${h(e.id)}">${lead}
    <span class="li-main"><span class="li-top"><span class="li-title">${h(e.name || "—")}</span>${dist ? `<span class="pl-dist">${h(dist)}</span>` : ""}</span>
    ${line ? `<span class="li-snip">${h(line)}</span>` : ""}
    ${price || o.mika ? `<span class="li-snip${e.free ? " ok-txt" : ""}">${h(price)}${o.mika ? `${price ? " · " : ""}<b class="mika-txt">repéré par Mika</b>` : ""}</span>` : ""}</span></button>`;
}

function chip(attr: string, value: string, label: string, on: boolean, icon = ""): string {
  return `<button type="button" class="cat${on ? " on" : ""}" ${attr}="${h(value)}" aria-pressed="${on}">${icon}${h(label)}</button>`;
}

function listMarkup(v: EventsView): string {
  const themes = themeLabels(v.info);
  const out: string[] = [];
  if (v.hint) out.push(`<p class="small muted cs-hint">${ico("info", "xs")}${h(v.hint)}</p>`);
  if (v.regardError) {
    return out.join("") + (v.regardGone
      ? failedBlock("Ce que Mika avait trouvé n'est plus là", "Elle l'a peut-être oublié, ou c'était pour quelqu'un d'autre.")
      : errorBlock(v.regardError, "Ce que Mika avait trouvé ne se lit pas"));
  }
  if (v.error) return out.join("") + failedBlock("Les événements ne se cherchent pas ici", v.error);
  if (!v.searched) {
    out.push(v.loading ? `<div class="empty">${ico("refresh")}<p>Recherche…</p></div>`
      : `<div class="empty">${ico("calendar")}<b>Ce qui se passe autour</b><p>Concerts, expositions, marchés, fêtes… : autour de toi, ou dans la zone de la carte. Ils viennent des offices de tourisme, gardés sur ce serveur : chercher ne fait rien sortir.</p></div>`);
    return out.join("");
  }
  const cover = coverageLine(v.coverage, "Événements des offices de tourisme lus", v.now);
  const title = v.regard ? (v.regard.title || "Ce que Mika a trouvé") : "Événements";
  out.push(`<div class="group-label${v.regard ? " mika-label" : ""}">${v.regard ? ico("sparkle", "xs") : ""}${h(title)} <span class="cnt">${v.events.length}</span><span class="grow"></span>${
    v.regard ? "" : `<span class="muted">${h(v.where === "moi" ? "autour de toi" : "dans cette zone")}</span>`}</div>`);
  if (cover) out.push(`<p class="small muted cov-line">${ico("info", "xs")}<span>${h(cover)}</span></p>`);
  if (v.loading && !v.events.length) out.push(`<div class="empty">${ico("refresh")}<p>Recherche…</p></div>`);
  else if (!v.events.length) out.push(`<div class="empty">${ico("calendar")}<p>${h(v.regard ? "Elle n'a gardé aucun événement de ce regard." : `Rien de prévu ${v.where === "moi" ? "autour de toi" : "dans cette zone"} à ces dates.`)}</p></div>`);
  for (const g of eventDays(v.events, v.now)) {
    out.push(`<div class="day-label">${h(g.title)}</div>`);
    out.push(...g.events.map((e) => eventItem(e, { on: v.sel === e.id, mika: !!v.regard, themes, seen: v.seen, inDay: !!g.day })));
  }
  if (v.events.length) out.push(`<p class="src-line">${ico("info", "xs")}<span>Les offices de tourisme, par DATAtourisme (Licence Ouverte) : une base sur ce serveur, lue autour de toi et remise à jour chaque soir.</span></p>`);
  return out.join("");
}

export function eventsMarkup(v: EventsView): string {
  if (v.fiche) return `<div class="split carte-split"><aside class="pane carte-side">${v.fiche}</aside>${v.map}</div>`;
  const themes: readonly Choice[] = v.info?.themes ?? [];
  const dates = v.when === "dates"
    ? `<div class="row wrap ev-dates-pick"><label class="field-inline"><span>Du</span><input type="date" data-ev-start value="${h(v.dates.start)}"></label>
        <label class="field-inline"><span>au</span><input type="date" data-ev-end value="${h(v.dates.end)}"></label></div>` : "";
  const search = v.regard ? "" : `<div class="cs-search">
      <label class="search-field">${ico("search", "sm")}<input type="search" data-evq value="${h(v.q)}" maxlength="200" placeholder="Un concert, un marché, une fête…" aria-label="Chercher un événement"></label>
      <div class="cs-cats" role="group" aria-label="Quand">${WHEN_LABELS.map(([id, label]) => chip("data-when", id, label, v.when === id, id === "dates" ? ico("calendar", "xs") : "")).join("")}</div>
      ${dates}
      <div class="cs-cats" role="group" aria-label="Quoi">${themes.map((t) => chip("data-theme", t.id, t.label, v.themes.includes(t.id))).join("")}${chip("data-free", "1", "Gratuit", v.free)}</div>
      <div class="seg" role="group" aria-label="Où chercher">
        <button type="button" aria-pressed="${v.where === "moi"}" data-ev-where="moi">${ico("pin", "sm")}Autour de moi</button>
        <button type="button" aria-pressed="${v.where === "zone"}" data-ev-where="zone">${ico("map", "sm")}Dans cette zone</button></div>
    </div>`;
  const foot = v.regard ? `<div class="pane-foot row wrap"><a class="btn sm" href="#carte/evenements">${ico("chev-left", "sm")}Tous les événements</a></div>` : "";
  return `<div class="split carte-split">
    <aside class="pane carte-side">${search}<div class="pane-scroll" data-results>${listMarkup(v)}</div>${foot}</aside>
    ${v.map}</div>`;
}

/** La légende de la carte des événements. */
export function eventsLegend(v: Pick<EventsView, "events" | "where" | "regard" | "searched">): string {
  if (!v.searched) return "";
  const n = `${v.events.length} événement${v.events.length > 1 ? "s" : ""}`;
  return v.regard ? legendMarkup("sparkle", v.regard.title || "Ce que Mika a trouvé", `${n} · ce que Mika a trouvé`)
    : legendMarkup("pin", "Événements", `${n} · ${v.where === "moi" ? "autour de ta position" : "dans cette zone"}`);
}
