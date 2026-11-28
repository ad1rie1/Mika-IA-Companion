/**
 * Le dessin de l'Agenda, pur (la maquette validée `maquette/ecrans/agenda.js`) : la barre de titre (Aujourd'hui, ‹ ›,
 * la période ; la vue, chercher, les invitations), la colonne de gauche (Créer, le mini-mois, les agendas par groupe,
 * les comptes en panne, « Brancher un agenda »), les vues (Jour et Semaine en grille horaire, Mois, Planning, la
 * recherche), le bandeau de ce que Mika propose, la fiche d'un événement — le sien, une invitation, ce que Mika propose,
 * une date de sa mémoire — et le volet des invitations. Rien ne se décide ici : chaque bouton n'existe que si le serveur
 * l'ouvre (`can`), et dit ce qu'il fait.
 */
import type { AgendaCalendar, AgendaItem, AgendaPerson, Proposal } from "../../api/agenda";
import { mikaAvatar } from "../../mika/face";
import { h } from "../../shell/dom";
import { ico, type IconName } from "../../shell/icons";
import { personAvatar } from "../../shared/kit";
import { addDays, cap, daysFrom, dayWords, hm, JC, MC, miniDays, monthWords, partsOf, periodWords, shortDay, VIEWS, type View } from "./dates";
import {
  alertWords,
  colorOf,
  columns,
  isPast,
  lanes,
  mikaReminderWords,
  MIKA_REMINDERS,
  providerShort,
  relative,
  ruleWords,
  sortOf,
  whenWords,
  whereWords,
  type Occ,
} from "./model";

/** La hauteur d'une heure dans la grille. */
export const HH = 48;

export interface AgendaView {
  view: View;
  /** Le jour que la vue montre (sa semaine, son mois…). */
  date: string;
  today: string;
  nowMinute: number;
  zoneShort: string;
  zone: string;
  calendars: AgendaCalendar[];
  /** Les agendas décochés dans la vue (l'affichage seulement). */
  off: ReadonlySet<string>;
  /** L'occurrence ouverte (sa clé). */
  selected: string | null;
  /** Le mois du mini-mois, s'il a été déplacé. */
  miniMonth: string | null;
  /** Sur un téléphone, le mois déplié sous le titre. */
  mobileMonth: boolean;
  /** La recherche. */
  q: string;
  searching: boolean;
  /** Les invitations qui attendent sa réponse. */
  invitations: number;
  /** Les comptes en panne : leur nom, leur erreur, leur adresse de réglage. */
  failing: { key: string; label: string; error: string }[];
  /** Le nom de chaque personne qui a un compte (le système désigne une participante par sa clé seule). */
  names: ReadonlyMap<string, string>;
}

/** Le nom d'une participante : le sien, son adresse, sinon celui de la personne qui a un compte. */
export function personName(p: AgendaPerson | null | undefined, names: ReadonlyMap<string, string>): string {
  if (!p) return "";
  return p.name || p.address || (p.person ? names.get(p.person) ?? "" : "");
}

const swatch = (color: string, cls = "") => `<span class="ag-sw${cls ? ` ${cls}` : ""}" style="--c:var(--ag-${h(color)})"></span>`;

export function calOf(v: AgendaView, key: string): AgendaCalendar | undefined {
  return v.calendars.find((c) => c.key === key);
}

/** La couleur d'une occurrence : rose pour ce que Mika propose et sa mémoire, sinon celle de son agenda. */
export function occColor(v: AgendaView, o: Occ): string {
  const s = sortOf(o);
  if (s === "propose" || s === "mika") return "rose";
  return colorOf(calOf(v, o.calendar));
}

// ── la barre de titre ────────────────────────────────────────────────

export function titleBar(v: AgendaView, invitationsOpen: boolean): string {
  const n = v.invitations;
  const search = v.searching || v.q
    ? `<label class="search ag-q ag-chercher">${ico("search", "sm")}<input type="search" data-agq placeholder="Un titre, un lieu, une personne…" value="${h(v.q)}" aria-label="Chercher dans tes agendas"></label>`
    : `<button class="btn icon ghost ag-chercher" type="button" data-agchercher title="Chercher dans tes agendas" aria-label="Chercher dans tes agendas">${ico("search")}</button>`;
  const todayTitle = `Revenir à aujourd'hui, ${dayWords(v.today, v.today)}`;
  return `<div class="ag-tb">
    <div class="ag-tb-nav">
      <button class="btn icon ghost ag-m-only" type="button" data-agcals title="Tes agendas" aria-label="Tes agendas">${ico("menu")}</button>
      <button class="btn sm ag-auj-d" type="button" data-agauj title="${h(todayTitle)}">Aujourd'hui</button>
      <span class="btn-group"><button class="btn sm icon" type="button" data-agpas="-1" title="Précédent" aria-label="Précédent">${ico("chev-left", "sm")}</button><button class="btn sm icon" type="button" data-agpas="1" title="Suivant" aria-label="Suivant">${ico("chev-right", "sm")}</button></span>
      <button class="ag-periode" type="button" data-agperiode aria-expanded="${v.mobileMonth}"><span class="long">${h(periodWords(v.view, v.date, v.today))}</span><span class="court">${h(periodWords(v.view, v.date, v.today, true))}</span>${ico("chev-down", "xs")}</button>
    </div>
    <span class="grow"></span>
    <div class="ag-tb-right">
      <div class="seg ag-vues" role="group" aria-label="La vue">${VIEWS.map(([k, l]) => `<button type="button" data-agvue="${k}" aria-pressed="${v.view === k && !v.q}">${l}</button>`).join("")}</div>
      <span class="ag-tb-outils">${search}
        <button class="btn icon ghost ag-m-only ag-auj-m" type="button" data-agauj title="${h(todayTitle)}" aria-label="${h(todayTitle)}"><span class="ag-auj-ico">${partsOf(v.today).d}</span></button>
        <a class="btn ag-inv-btn${invitationsOpen ? " on" : ""}" href="#agenda/invitations" title="Les invitations qui attendent ta réponse">${ico("inbox", "sm")}<span class="lbl">Invitations</span>${n ? `<b class="badge">${n}</b>` : ""}</a>
        <a class="btn primary icon ag-m-only ag-plus" href="#agenda/nouveau" title="Créer un événement" aria-label="Créer un événement">${ico("plus")}</a></span>
    </div></div>`;
}

// ── la colonne de gauche ─────────────────────────────────────────────

export function miniMonth(v: AgendaView, range: [string, string]): string {
  const month = v.miniMonth ?? `${v.date.slice(0, 7)}-01`;
  const band = v.view === "jour" || v.view === "semaine";
  const [first, after] = range;
  const last = addDays(after, -1);
  const cells = miniDays(month).map((d) => {
    const inside = band && d >= first && d < after;
    const cls = [d.slice(0, 7) !== month.slice(0, 7) ? "hors" : "", d === v.today ? "auj" : "", inside ? "dans" : "",
      inside && d === first ? "debut" : "", inside && d === last ? "fin" : "", d === v.date && d !== v.today ? "sel" : ""].filter(Boolean).join(" ");
    return `<button type="button" class="${cls}" data-agjour="${d}" aria-label="${h(dayWords(d, v.today))}"><i>${partsOf(d).d}</i></button>`;
  }).join("");
  return `<div class="ag-mini"><div class="ag-mini-head"><b>${h(monthWords(month))}</b>
      <button class="btn xs icon ghost" type="button" data-agmini="-1" title="Mois précédent" aria-label="Mois précédent">${ico("chev-left", "xs")}</button>
      <button class="btn xs icon ghost" type="button" data-agmini="1" title="Mois suivant" aria-label="Mois suivant">${ico("chev-right", "xs")}</button></div>
    <div class="ag-mini-grid">${["L", "M", "M", "J", "V", "S", "D"].map((x) => `<span>${x}</span>`).join("")}${cells}</div></div>`;
}

const GROUPS: readonly (readonly [string, string])[] = [["mine", "Mes agendas"], ["shared", "Partagés avec moi"], ["subscriptions", "Abonnements"], ["mika", "L'agenda de Mika"]];

function calendarLine(v: AgendaView, c: AgendaCalendar): string {
  const color = colorOf(c);
  const shares = c.shares ?? [];
  const shared = shares.length
    ? `<span class="ag-shared" title="Partagé dans Mika avec ${h(shares.map((s) => s.name).join(" et "))}">${ico("users", "xs")}${shares.length}</span>`
    : "";
  const sub = providerShort(c);
  return `<div class="ag-cal${c.kind === "mika" ? " mika" : ""}" style="--c:var(--ag-${h(color)})">
    <label title="${h(c.name)} — ${h(sub)}"><input type="checkbox" data-agcoche="${h(c.key)}"${v.off.has(c.key) ? "" : " checked"}><span class="ag-cal-nom"><b>${h(c.name)}</b><small>${h(sub)}${shared}</small></span></label>
    <button class="btn xs icon ghost ag-cal-more" type="button" data-agmenu="${h(c.key)}" title="Afficher seulement celui-ci, couleur, partager, paramètres" aria-label="Plus pour « ${h(c.name)} »">${ico("more", "xs")}</button></div>`;
}

export function calendarGroups(v: AgendaView): string {
  return GROUPS.map(([g, title]) => {
    const list = v.calendars.filter((c) => c.group === g && !c.hidden);
    return list.length ? `<div class="group-label">${h(title)}</div><div class="ag-cals">${list.map((c) => calendarLine(v, c)).join("")}</div>` : "";
  }).join("");
}

export function side(v: AgendaView, range: [string, string]): string {
  const warn = v.failing.map((a) => `<a class="ag-warn" href="#parametres/agendas/${encodeURIComponent(a.key)}">${ico("alert", "sm")}<span><b>${h(a.label)}</b> : ${h(a.error)}</span></a>`).join("");
  return `<aside class="pane ag-side"><div class="pane-scroll ag-side-scroll">
    <a class="btn primary ag-creer" href="#agenda/nouveau">${ico("plus", "sm")}Créer</a>
    ${miniMonth(v, range)}
    ${calendarGroups(v)}
    <div class="ag-side-foot">${warn}<a class="mb-add" href="#parametres/agendas/brancher">${ico("plus", "sm")}Brancher un agenda</a></div>
  </div></aside>`;
}

// ── les pièces communes des vues ─────────────────────────────────────

function classes(v: AgendaView, o: Occ): string {
  return [sortOf(o), isPast(o, v.today, v.nowMinute) ? "passe" : "", v.selected === o.key ? "sel" : ""].filter(Boolean).join(" ");
}

function addedByHer(o: Occ): boolean {
  return o.item?.added?.by === "elle";
}

function mark(o: Occ): string {
  const s = sortOf(o);
  if (s === "propose" || s === "mika" || addedByHer(o)) {
    const t = s === "propose" ? "Mika propose de l'ajouter" : s === "mika" ? "L'agenda de Mika" : "Ajouté par Mika";
    return `<span class="ag-mk" title="${t}">${ico("sparkle", "xs")}</span>`;
  }
  return "";
}

function longTitle(v: AgendaView, o: Occ): string {
  const when = o.allDay ? `${dayWords(o.day, v.today)}, journée entière` : `${dayWords(o.day, v.today)}, ${hm(o.start)} – ${hm(o.end)}`;
  const s = sortOf(o);
  return `${o.title} — ${when}${s === "invite" ? " (invitation)" : s === "propose" ? " (proposé par Mika)" : ""}`;
}

function tags(o: Occ): string {
  const s = sortOf(o);
  const out: string[] = [];
  const from = o.item?.organizer?.name || "";
  if (s === "invite") out.push(`<span class="tag warn">invitation${from ? ` · ${h(from)}` : ""}</span>`);
  if (s === "peut") out.push('<span class="tag">peut-être</span>');
  if (s === "propose") out.push(`<span class="mk">${ico("sparkle")}proposé par Mika</span>`);
  if (addedByHer(o)) out.push(`<span class="mk quiet">${ico("sparkle")}ajouté par Mika</span>`);
  if (s === "mika") out.push(`<span class="mk">${ico("sparkle")}${o.her?.kind === "promesse" ? "promis" : "elle s'en souvient"}</span>`);
  if (o.item?.recurring) out.push(`<span class="ag-rep" title="Se répète">${ico("repeat", "xs")}</span>`);
  return out.join("");
}

const firstPart = (place: string) => place.split(" · ")[0];

// ── Jour et Semaine : la grille horaire ──────────────────────────────

function block(v: AgendaView, x: ReturnType<typeof columns>[number], wide: boolean): string {
  const o = x.o;
  const top = (x.from / 60) * HH;
  const height = Math.max(19, ((o.end - o.start) / 60) * HH - 2);
  const w = 100 / x.cols;
  const left = x.col * w;
  const short = height < 36;
  const s = sortOf(o);
  const when = s === "invite" ? `${hm(o.start)} – ${hm(o.end)} · invitation` : s === "propose" ? `${hm(o.start)} · proposé par Mika` : `${hm(o.start)} – ${hm(o.end)}`;
  const place = o.item?.location && height > 58 ? `<span class="ag-ev-l">${h(firstPart(o.item.location))}</span>` : "";
  const people = wide && o.item && o.item.participants.length > 1 && height > 80 ? `<span class="ag-ev-l">${o.item.participants.length} participants</span>` : "";
  return `<button type="button" class="ag-ev ${classes(v, o)}${short ? " court" : ""}" style="--c:var(--ag-${occColor(v, o)});top:${top}px;height:${height}px;left:calc(${left}% + 2px);width:calc(${w}% - 5px)" data-agev="${h(o.key)}" title="${h(longTitle(v, o))}">
    ${short ? `${mark(o)}<b>${h(o.title)}</b><span>${hm(o.start)}</span>` : `<b>${mark(o)}${h(o.title)}</b><span>${h(when)}</span>${place}${people}`}</button>`;
}

export function gridView(v: AgendaView, occs: readonly Occ[], days: readonly string[]): string {
  const n = days.length;
  const first = days[0];
  const after = addDays(days[n - 1], 1);
  const shown = occs.filter((o) => o.last >= first && o.day < after);
  const bands = lanes(shown.filter((o) => o.allDay), first, n);
  const laneCount = Math.max(1, ...bands.map((b) => b.lane + 1));
  const bandHtml = bands.map((b) => `<button type="button" class="ag-ev ag-ad ${classes(v, b.o)}" style="--c:var(--ag-${occColor(v, b.o)});grid-column:${b.from + 1} / ${b.to + 2};grid-row:${b.lane + 1}" data-agev="${h(b.o.key)}" title="${h(longTitle(v, b.o))}">${mark(b.o)}<b>${h(b.o.title)}</b></button>`).join("");
  const cols = days.map((d) => {
    const placed = columns(shown.filter((o) => !o.allDay && o.day === d));
    const now = d === v.today ? `<div class="ag-now" style="top:${(v.nowMinute / 60) * HH}px" title="Maintenant, ${hm(v.nowMinute)}"></div>` : "";
    return `<div class="ag-col${d === v.today ? " auj" : ""}" data-agcol="${d}">${placed.map((x) => block(v, x, n === 1)).join("")}${now}</div>`;
  }).join("");
  const heads = days.map((d) => `<button type="button" class="ag-dh${d === v.today ? " auj" : ""}" data-agjourvue="${d}" title="${h(cap(dayWords(d, v.today)))}"><span>${JC[new Date(`${d}T12:00:00Z`).getUTCDay()]}</span><b>${partsOf(d).d}</b></button>`).join("");
  const hours = Array.from({ length: 24 }, (_, i) => `<span style="top:${i * HH}px">${i ? `${String(i).padStart(2, "0")}:00` : ""}</span>`).join("");
  return `<div class="ag-grid${n === 1 ? " un" : ""}" style="--n:${n};--hh:${HH}px" data-agscroll="grille">
    <div class="ag-gtop"><div class="ag-gh"><div class="ag-gut ag-tz" title="${h(v.zone)}">${h(v.zoneShort)}</div><div class="ag-dhs">${heads}</div></div>
      <div class="ag-gad"><div class="ag-gut">journée</div><div class="ag-ads" style="grid-template-rows:repeat(${laneCount}, 22px)">${bandHtml}</div></div></div>
    <div class="ag-gb"><div class="ag-gut ag-hours">${hours}</div><div class="ag-cols">${cols}</div></div></div>`;
}

// ── Mois ─────────────────────────────────────────────────────────────

export function monthView(v: AgendaView, occs: readonly Occ[], range: [string, string]): string {
  const [first, after] = range;
  const n = daysFrom(first, after);
  const month = v.date.slice(0, 7);
  let cells = "";
  for (let i = 0; i < n; i++) {
    const d = addDays(first, i);
    const these = occs.filter((o) => o.day <= d && o.last >= d);
    const max = 4;
    const shown = these.slice(0, these.length > max ? max - 1 : max);
    const rest = these.length - shown.length;
    const { d: num, m } = partsOf(d);
    const chips = shown.map((o) => (o.allDay
      ? `<button type="button" class="ag-ev ag-mchip plein ${classes(v, o)}" style="--c:var(--ag-${occColor(v, o)})" data-agev="${h(o.key)}" title="${h(longTitle(v, o))}">${mark(o)}<b>${h(o.title)}</b></button>`
      : `<button type="button" class="ag-mchip ${classes(v, o)}" style="--c:var(--ag-${occColor(v, o)})" data-agev="${h(o.key)}" title="${h(longTitle(v, o))}"><i class="ag-dot"></i><span class="t">${hm(o.start)}</span><b>${h(o.title)}</b></button>`)).join("");
    cells += `<div class="ag-mc${d.slice(0, 7) !== month ? " hors" : ""}${d === v.today ? " auj" : ""}">
      <button type="button" class="ag-mc-n" data-agjourvue="${d}" title="${h(cap(dayWords(d, v.today)))}">${num === 1 ? `1er ${MC[m - 1]}` : num}</button>
      ${chips}${rest ? `<button type="button" class="ag-mc-plus" data-agjourvue="${d}">${rest} de plus</button>` : ""}</div>`;
  }
  return `<div class="ag-month"><div class="ag-mh">${["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."].map((x) => `<span>${x}</span>`).join("")}</div>
    <div class="ag-mg" style="--r:${n / 7}">${cells}</div></div>`;
}

// ── Planning : une liste par jour ────────────────────────────────────

function planLine(v: AgendaView, o: Occ): string {
  const cal = calOf(v, o.calendar);
  const where = o.item?.location ? ` · ${firstPart(o.item.location)}` : o.item?.conference ? " · visio" : "";
  const calName = o.kind === "her" ? "L'agenda de Mika" : cal?.name ?? "";
  return `<button type="button" class="ag-pr ${classes(v, o)}" style="--c:var(--ag-${occColor(v, o)})" data-agev="${h(o.key)}" title="${h(longTitle(v, o))}">
    <span class="ag-pr-h">${o.allDay ? "Journée" : `${hm(o.start)} – ${hm(o.end)}`}</span><i class="ag-pr-dot"></i>
    <span class="ag-pr-main"><b>${h(o.title)}</b><small>${h(calName)}${h(where)}</small></span>
    <span class="ag-pr-marks">${tags(o)}</span></button>`;
}

export function dayList(v: AgendaView, occs: readonly Occ[], opts: { from?: string; until?: string; q?: string } = {}): string {
  const days = new Map<string, Occ[]>();
  for (const o of occs) {
    for (let d = o.day; d <= o.last; d = addDays(d, 1)) {
      if (opts.from && d < opts.from) continue;
      if (opts.until && d >= opts.until) break;
      const list = days.get(d) ?? [];
      list.push(o);
      days.set(d, list);
    }
  }
  if (!days.size) {
    return `<div class="empty">${ico(opts.q ? "search" : "agenda")}<b>${opts.q ? "Rien trouvé" : "Rien de prévu"}</b><p>${opts.q ? `Aucun événement ne correspond à « ${h(opts.q)} » dans tes agendas cochés.` : "Aucun événement dans les agendas cochés sur cette période."}</p></div>`;
  }
  return [...days.entries()].sort(([a], [b]) => (a < b ? -1 : 1)).map(([d, list]) => {
    const today = d === v.today;
    let lines = "";
    let said = false;
    const nowLine = `<div class="ag-pl-now"><span>${hm(v.nowMinute)}</span></div>`;
    for (const o of list.sort((a, b) => Number(b.allDay) - Number(a.allDay) || a.start - b.start)) {
      if (today && !said && !o.allDay && o.start > v.nowMinute) {
        lines += nowLine;
        said = true;
      }
      lines += planLine(v, o);
    }
    if (today && !said) lines += nowLine;
    const e = daysFrom(v.today, d);
    const { d: num, m } = partsOf(d);
    return `<section class="ag-pd${today ? " auj" : ""}"><button type="button" class="ag-pd-date" data-agjourvue="${d}" title="${h(cap(dayWords(d, v.today)))}"><b>${num}</b><span><i>${JC[new Date(`${d}T12:00:00Z`).getUTCDay()]}</i> <i>${MC[m - 1]}</i></span></button>
      <div class="ag-pd-list">${e === 0 ? '<div class="ag-pd-dit">Aujourd\'hui</div>' : e === 1 ? '<div class="ag-pd-dit">Demain</div>' : ""}${lines}</div></section>`;
  }).join("");
}

export function planningView(v: AgendaView, occs: readonly Occ[], range: [string, string]): string {
  return `<div class="ag-plan" data-agscroll="liste">${dayList(v, occs, { from: range[0], until: range[1] })}
    <div class="ag-plan-more"><button class="btn sm" type="button" data-agpas="1">${ico("chev-down", "sm")}Les quatre semaines suivantes</button></div></div>`;
}

export function searchView(v: AgendaView, occs: readonly Occ[] | null, more: boolean, error: string, unchecked = false): string {
  if (unchecked) {
    return `<div class="ag-plan" data-agscroll="liste"><div class="ag-res-head"><b>Aucun agenda n'est coché</b> <span class="muted">· coche ceux où chercher, dans la colonne de gauche</span>
    <button class="btn xs ghost" type="button" data-agqvide>${ico("x", "xs")}Effacer</button></div></div>`;
  }
  const head = (n: string) => `<div class="ag-res-head"><b>${h(n)}</b> pour « ${h(v.q)} » <span class="muted">· dans les agendas cochés, des 90 derniers jours à l'année qui vient${more ? " — les 50 plus proches" : ""}</span>
    <button class="btn xs ghost" type="button" data-agqvide>${ico("x", "xs")}Effacer</button></div>`;
  if (error) return `<div class="ag-plan" data-agscroll="liste">${head("La recherche n'a pas abouti")}<div class="empty">${ico("alert")}<p>${h(error)}</p></div></div>`;
  if (v.q.trim().length < 2) return `<div class="ag-plan" data-agscroll="liste">${head("Deux lettres au moins")}</div>`;
  if (!occs) return `<div class="ag-plan" data-agscroll="liste">${head("Recherche…")}</div>`;
  return `<div class="ag-plan" data-agscroll="liste">${head(`${occs.length} résultat${occs.length > 1 ? "s" : ""}`)}${dayList(v, occs, { q: v.q })}</div>`;
}

// ── ce que Mika propose, en tête de la vue ───────────────────────────

export function strip(v: AgendaView, p: Proposal | null, o: Occ | null, others: number, selected: string | null): string {
  if (!p || !p.draft || !o || selected === `proposition/${p.id}`) return "";
  const cal = calOf(v, p.calendar);
  const color = colorOf(cal);
  return `<div class="ag-strip">${mikaAvatar("xs")}<span class="grow"><b>Mika propose d'ajouter</b> « ${h(p.draft.title)} »
      <span class="long">${h(stripWhen(o, v.today, true))}${cal ? ` · dans ${swatch(color)}${h(cal.name)}` : ""}</span><span class="court">${h(stripWhen(o, v.today, false))}</span>
      <a href="#agenda/proposition/${p.id}">Voir</a>${others ? `<span class="muted">· et ${others} autre${others > 1 ? "s" : ""}</span>` : ""}</span>
    <span class="ag-strip-actions"><button class="btn xs" type="button" data-agprop="refuse:${p.id}">Refuser</button><a class="btn xs" href="#agenda/modifier/proposition/${p.id}">Modifier</a>
      <button class="btn xs primary" type="button" data-agprop="accept:${p.id}"${p.preview?.blocked ? ` disabled title="${h(p.preview.blocked)}"` : ""}>${ico("check", "xs")}Ajouter</button></span></div>`;
}

/** Le moment d'une proposition, dans le bandeau : « · samedi 28 novembre à 20:00 ». */
export function stripWhen(o: Occ, today: string, long: boolean): string {
  if (o.allDay) return `· ${long ? dayWords(o.day, today) : shortDay(o.day)}`;
  return long ? `· ${dayWords(o.day, today)} à ${hm(o.start)}` : `· ${shortDay(o.day)}, ${hm(o.start)}`;
}

// ── la fiche d'un événement ──────────────────────────────────────────

const RESPONSES: readonly (readonly ["oui" | "peut" | "non", string, IconName | ""])[] = [["oui", "Accepter", "check"], ["peut", "Peut-être", ""], ["non", "Refuser", "x"]];
const PEOPLE_TAG: Record<string, [string, string]> = { org: ["accent", "organise"], oui: ["ok", "oui"], peut: ["warn", "peut-être"], non: ["danger", "non"], attente: ["", "sans réponse"], "": ["", "invité"] };

function people(item: AgendaItem, names: ReadonlyMap<string, string>): string {
  const list: (AgendaPerson & { org?: boolean })[] = [];
  if (item.organizer) list.push({ ...item.organizer, org: true });
  for (const p of item.participants) if (!item.organizer || p.address !== item.organizer.address) list.push(p);
  if (list.length < 2 && !item.participants.length) return "";
  const n = { oui: 0, peut: 0, non: 0, attente: 0 };
  for (const p of list) {
    const r = p.org ? "oui" : p.response || "attente";
    if (r in n) n[r as keyof typeof n] += 1;
  }
  const sum = [`${list.length} personnes`, n.oui ? `${n.oui} oui` : "", n.peut ? `${n.peut} peut-être` : "", n.non ? `${n.non} non` : "", n.attente ? `${n.attente} sans réponse` : ""].filter(Boolean).join(" · ");
  return `<div class="ag-sec"><h4 class="rd-h4">Participants <span class="cnt">${h(sum)}</span></h4><ul class="ag-ppl">${list.map((p) => {
    const [cls, word] = PEOPLE_TAG[p.org ? "org" : p.response] ?? PEOPLE_TAG[""];
    const me = p.me || (p.org && item.organized);
    const name = personName(p, names) || (me ? "Toi" : "Une personne qui a un compte ici");
    return `<li>${personAvatar(name, "sm")}<span class="grow"><b>${h(name)}${me && name !== "Toi" ? ' <span class="muted">(toi)</span>' : ""}</b>${p.address && p.name ? `<small>${h(p.address)}</small>` : ""}</span><span class="tag ${cls}">${h(word)}</span></li>`;
  }).join("")}</ul></div>`;
}

/** Répondre à une invitation, et ce que Mika a préparé. */
export function answerBox(item: AgendaItem, compact: boolean, names: ReadonlyMap<string, string> = new Map()): string {
  const r = item.response;
  const prep = item.prepared && item.prepared.decides ? item.prepared : null;
  const from = personName(item.organizer, names);
  const head = compact || !from ? "" : `<div class="ag-invit-head">${personAvatar(from, "sm")}<span><b>${h(from)}</b> t'invite${item.calendar_name ? ` <span class="muted">· dans « ${h(item.calendar_name)} »</span>` : ""}</span></div>`;
  const buttons = RESPONSES.map(([k, l, i]) => `<button class="btn sm${r === k ? " on" : ""}" type="button" data-agrep="${k}" data-agrepev="${item.event}" data-agrepocc="${h(item.occurrence)}">${i ? ico(i, "sm") : ""}${l}</button>`).join("");
  const words = { oui: "Accepter", peut: "Peut-être", non: "Refuser" } as const;
  const prepared = prep
    ? `<div class="mika-note ag-prep">${mikaAvatar("sm")}<div class="mn-body"><div class="mn-title">${ico("sparkle", "xs")}Mika a préparé ta réponse · elle attend ton accord</div>
        <p><b>${h(words[prep.answer as keyof typeof words] ?? prep.answer)}</b>${prep.comment ? `, avec un mot : « ${h(prep.comment)} »` : ""}</p>${prep.why ? `<p class="small text-2">${h(prep.why)}</p>` : ""}
        <div class="mn-actions"><button class="btn sm primary" type="button" data-agprop="accept:${prep.id}"${prep.preview?.blocked ? ` disabled title="${h(prep.preview.blocked)}"` : ""}>${ico("send", "sm")}Envoyer sa réponse</button>
          <button class="btn sm" type="button" data-agrepmot="${item.event}" data-agrepocc="${h(item.occurrence)}" data-agrepprep="${prep.id}">Modifier le mot</button>
          <button class="btn sm ghost" type="button" data-agprop="refuse:${prep.id}">Non merci</button></div></div></div>`
    : "";
  // la réponse d'une série vaut pour toute la série (le choix du lot 6) ; d'ici sans pouvoir répondre, pourquoi
  const series = item.recurring ? '<p class="small text-2 ag-rep-note">Ta réponse vaut pour toute la série.</p>' : "";
  const why = item.respond_why ? `<p class="small text-2 ag-rep-note">${ico("info", "xs")}${h(item.respond_why)}</p>` : "";
  if (r && r !== "attente") {
    // déjà répondu : une ligne, et « Changer » rouvre les trois réponses
    const said = { oui: "oui", peut: "peut-être", non: "non" }[r] ?? r;
    const who = personName(item.organizer, names);
    return `<div class="ag-invit done" data-agrepdone>${ico("check", "sm")}<span>Tu as répondu <b>${h(said)}</b>${who ? ` à ${h(who)}` : ""}.</span>${item.can.respond ? '<button class="linkish small" type="button" data-agrepchanger>Changer</button>' : ""}</div>
      ${item.can.respond ? `<div class="ag-invit" data-agreprow hidden><div class="ag-rep-row"><span class="small text-2">Ta réponse :</span><span class="btn-group">${buttons}</span></div>${series}</div>` : why}`;
  }
  if (!item.can.respond) return `<div class="ag-invit">${head}${why}</div>`;
  return `<div class="ag-invit">${head}
    <div class="ag-rep-row"><span class="small text-2">Ta réponse :</span><span class="btn-group">${buttons}</span></div>${series}${prepared}</div>`;
}

function remindersSection(v: AgendaView, o: Occ, cal: AgendaCalendar | undefined): string {
  const item = o.item;
  if (!item || !cal) return "";
  const provider = item.reminders ?? [];
  const max = cal.provider_reminders?.max ?? 0;
  const who = { google: "par Google", microsoft: "par Outlook", caldav: "par le serveur CalDAV", ical: "dans l'abonnement" }[cal.kind as string] ?? "";
  const lines: string[] = [];
  if (cal.kind === "systeme") lines.push(`<div class="ag-line">${ico("bell", "sm")}<span class="text-2">L'agenda du système n'envoie rien lui-même : c'est Mika qui te le rappelle.</span></div>`);
  else if (provider.length) {
    lines.push(...provider.map((a) => `<div class="ag-line">${ico("bell", "sm")}<span class="text-2">${h(cap(alertWords(a)))}${who ? `, ${who}` : ""}${item.reminders_default ? " <span class=\"muted\">· le réglage de l'agenda</span>" : ""}</span></div>`));
  } else lines.push(`<div class="ag-line">${ico("bell", "sm")}<span class="text-2">${max || cal.kind === "ical" ? `Aucun rappel ${who}` : "Aucun rappel du fournisseur"}</span></div>`);
  const own = item.remind || cal.reminder;
  const mika = cal.can.remind || item.can.remind
    ? `<div class="ag-line mika">${ico("sparkle", "sm")}<span class="grow"><b>${own === "non" ? "Mika ne te le rappelle pas" : `Mika te le rappelle : ${h(mikaReminderWords(own))}`}</b>
        <small>${item.remind ? "pour cet événement" : `le réglage de « ${h(cal.name)} »`} · elle te l'écrit dans le chat, ou par une notification</small></span>
        <button class="btn xs ghost" type="button" data-agrappel="${h(o.key)}">Changer</button></div>`
    : "";
  return `<div class="ag-sec"><h4 class="rd-h4">Rappels</h4>${lines.join("")}${mika}</div>`;
}

export interface FicheOptions {
  /** L'adresse d'une conversation (« Voir la conversation »), si elle s'ouvre d'ici. */
  conversation?: (ref: string) => string;
}

export function eventFiche(v: AgendaView, o: Occ, loading: boolean): string {
  const item = o.item!;
  const cal = calOf(v, o.calendar);
  const [rcls, rword] = relative(o, v.today, v.nowMinute);
  const color = occColor(v, o);
  const readOnly = !cal?.writable;
  const actions = [
    item.can.edit ? `<a class="btn sm" href="#agenda/modifier/${h(o.key.replace(/^evenement\//, ""))}">${ico("pen", "sm")}Modifier</a>` : "",
    item.can.duplicate ? `<button class="btn sm" type="button" data-agaction="dupliquer">${ico("copy", "sm")}${readOnly || !cal?.can.write ? "Copier dans mes agendas" : "Dupliquer"}</button>` : "",
    item.can.delete ? `<button class="btn sm danger" type="button" data-agaction="supprimer">${ico("trash", "sm")}${item.invitation || !item.organized ? "Retirer" : "Supprimer"}</button>` : "",
    '<span class="grow"></span>',
    `<button class="btn sm mika" type="button" data-agaction="demander">${ico("sparkle", "sm")}Demander à Mika</button>`,
  ].join("");
  const kv: string[] = [];
  if (item.recurring && item.rule) kv.push(`<li>${ico("repeat")}<span>${h(ruleWords(item.rule, o.day, v.today))}</span></li>`);
  else if (item.recurring) kv.push(`<li>${ico("repeat")}<span>Une occurrence d'une série</span></li>`);
  if (item.location) kv.push(`<li>${ico("pin")}<span>${h(item.location)}</span></li>`);
  if (item.conference && /^https?:\/\//i.test(item.conference)) {
    kv.push(`<li>${ico("video")}<span><a href="${h(item.conference)}" target="_blank" rel="noopener noreferrer">Rejoindre la réunion</a><small class="mono ellipsis">${h(item.conference)}</small></span></li>`);
  }
  if (item.description) kv.push(`<li>${ico("file")}<span class="text-2 ag-desc">${h(item.description)}</span></li>`);
  // qui l'organise, si ce n'est pas elle (le système ne garde de l'organisatrice que sa clé : un événement qu'elle
  // organise se dit par `organized`)
  const orgName = item.organizer && !item.organizer.me && !item.organized ? personName(item.organizer, v.names) : "";
  const org = orgName ? ` · organisé par ${orgName}, qui seul le modifie` : "";
  kv.push(`<li>${ico("clock")}<span class="text-2">${item.busy ? "Occupé" : "Disponible"} · ${item.private ? "privé" : "visibilité par défaut"}${h(org)}</span></li>`);
  const added = item.added?.by === "elle"
    ? `<div class="ag-line mika ag-par">${ico("sparkle", "sm")}<span><span><b>Ajouté par Mika</b>${item.added.at ? `, le ${h(dayWords(new Date(item.added.at).toISOString().slice(0, 10), v.today))}` : ""}</span>${item.added.conversation ? '<small><a href="#chat">Voir la conversation</a></small>' : ""}</span></div>`
    : "";
  const foot = item.masked
    ? `<p class="ag-ro">${ico("lock", "sm")}<span>Un événement privé : tu n'en vois que le créneau.</span></p>`
    : cal?.group === "shared" && !cal.writable
      ? `<p class="ag-ro">${ico("lock", "sm")}<span>${h(cal.owner_name || "Son propriétaire")} partage cet agenda avec toi${cal.level === "preparer" ? " en lecture et préparation" : " en lecture"} : tu le vois, tu n'y changes rien.</span></p>`
      : cal?.kind === "ical"
        ? `<p class="ag-ro">${ico("lock", "sm")}<span>Un abonnement est en lecture seule : ni toi ni Mika n'y écrivez.</span></p>`
        : cal?.read_only
          ? `<p class="ag-ro">${ico("lock", "sm")}<span>Son fournisseur ne laisse pas écrire dans cet agenda.</span></p>`
          : cal && cal.writable
            ? `<p class="small muted ag-src">${ico("refresh", "xs")}Une modification part tout de suite ${h(whereWords(cal.kind))}${cal.kind === "systeme" ? "" : ", puis l'agenda se relit"}.</p>`
            : "";
  return `<aside class="pane ag-volet" aria-label="L'événement">
    <div class="pane-head ag-vh"><button class="btn sm ghost mobile-back" type="button" data-agfermer>${ico("chev-left", "sm")}Agenda</button>
      ${swatch(color)}<span class="grow ellipsis small text-2">${h(cal?.name ?? "")} <span class="muted">· ${h(cal ? providerShort(cal) : "")}</span></span>
      <button class="btn icon ghost sm ag-vh-x" type="button" data-agfermer title="Fermer" aria-label="Fermer">${ico("x", "sm")}</button></div>
    <div class="pane-scroll"><div class="ag-fiche">
      <div class="ag-f-titre"><h2>${h(o.title)}</h2><p class="ag-quand">${h(whenWords(o, v.today))} <span class="tag ${rcls}">${h(rword)}</span></p></div>
      ${item.response ? answerBox(item, false, v.names) : ""}
      <div class="ag-actions">${actions}</div>
      <ul class="ag-kv">${kv.join("")}</ul>
      ${item.masked ? "" : people(item, v.names)}
      ${remindersSection(v, o, cal)}
      ${added}
      ${foot}
      ${loading ? '<p class="small muted">Relecture…</p>' : ""}
    </div></div></aside>`;
}

export function proposalFiche(v: AgendaView, o: Occ): string {
  const p = o.proposal!;
  const d = p.draft!;
  const cal = calOf(v, p.calendar);
  const [rcls, rword] = relative(o, v.today, v.nowMinute);
  const decides = p.decides;
  const box = `<div class="mika-note ag-box">${mikaAvatar("sm")}<div class="mn-body"><div class="mn-title">${ico("sparkle", "xs")}Mika propose d'ajouter cet événement à « ${h(cal?.name ?? "ton agenda")} »</div>
      ${p.summary ? `<p class="small">${h(p.summary)}</p>` : ""}
      ${decides
        ? `<div class="mn-actions"><button class="btn sm primary" type="button" data-agprop="accept:${p.id}"${p.preview?.blocked ? ` disabled title="${h(p.preview.blocked)}"` : ""}>${ico("check", "sm")}Ajouter</button><a class="btn sm" href="#agenda/modifier/proposition/${p.id}">Modifier</a><button class="btn sm" type="button" data-agprop="refuse:${p.id}">Refuser</button></div>`
        : '<p class="small muted">Son propriétaire en décide : elle attend son accord.</p>'}</div></div>`;
  const kv: string[] = [];
  if (d.rule) kv.push(`<li>${ico("repeat")}<span>${h(ruleWords(d.rule, o.day, v.today))}</span></li>`);
  if (d.location) kv.push(`<li>${ico("pin")}<span>${h(d.location)}</span></li>`);
  if (d.description) kv.push(`<li>${ico("file")}<span class="text-2 ag-desc">${h(d.description)}</span></li>`);
  if (d.invite.length) kv.push(`<li>${ico("users")}<span class="text-2">Invités : ${h(d.invite.join(", "))}</span></li>`);
  const remind = p.remind && p.remind !== "" ? `<div class="ag-sec"><h4 class="rd-h4">Rappels</h4><div class="ag-line mika">${ico("sparkle", "sm")}<span><b>Mika te le rappellera : ${h(mikaReminderWords(p.remind))}</b></span></div></div>` : "";
  return `<aside class="pane ag-volet" aria-label="Ce que Mika propose">
    <div class="pane-head ag-vh"><button class="btn sm ghost mobile-back" type="button" data-agfermer>${ico("chev-left", "sm")}Agenda</button>
      ${swatch("rose")}<span class="grow ellipsis small text-2">${h(cal?.name ?? "")} <span class="muted">· proposé par Mika</span></span>
      <button class="btn icon ghost sm ag-vh-x" type="button" data-agfermer title="Fermer" aria-label="Fermer">${ico("x", "sm")}</button></div>
    <div class="pane-scroll"><div class="ag-fiche">
      ${box}
      <div class="ag-f-titre"><h2>${h(o.title)}</h2><p class="ag-quand">${h(whenWords(o, v.today))} <span class="tag ${rcls}">${h(rword)}</span></p></div>
      <div class="ag-actions"><span class="small muted">Ce n'est pas encore dans ton agenda.</span><span class="grow"></span><button class="btn sm mika" type="button" data-agaction="demander">${ico("sparkle", "sm")}Demander à Mika</button></div>
      <ul class="ag-kv">${kv.join("")}</ul>
      ${remind}
      ${p.preview?.text ? `<details class="ap-more ag-preview"><summary>${ico("chev-right", "xs")}Voir exactement ce qui partira</summary><pre class="ap-raw">${h(p.preview.text)}</pre></details>` : ""}
    </div></div></aside>`;
}

export function herFiche(v: AgendaView, o: Occ): string {
  const d = o.her!;
  const [rcls, rword] = relative(o, v.today, v.nowMinute);
  const said = d.said_at ? dayWords(new Date(d.said_at).toISOString().slice(0, 10), v.today) : "";
  return `<aside class="pane ag-volet" aria-label="L'agenda de Mika">
    <div class="pane-head ag-vh"><button class="btn sm ghost mobile-back" type="button" data-agfermer>${ico("chev-left", "sm")}Agenda</button>
      ${swatch("rose")}<span class="grow ellipsis small text-2">L'agenda de Mika <span class="muted">· sa mémoire · lecture seule</span></span>
      <button class="btn icon ghost sm ag-vh-x" type="button" data-agfermer title="Fermer" aria-label="Fermer">${ico("x", "sm")}</button></div>
    <div class="pane-scroll"><div class="ag-fiche">
      <div class="mika-note ag-box">${mikaAvatar("sm")}<div class="mn-body"><div class="mn-title">${ico("sparkle", "xs")}${d.kind === "promesse" ? "Ce qu'elle t'a promis" : d.kind === "chaque_annee" ? "Ce qu'elle retient, chaque année" : "Ce qu'elle retient de ta vie"}</div>
        ${d.source ? `<p><b>${h(d.source)}</b>${d.conversation ? ' <a href="#chat">Voir la conversation</a>' : ""}</p>` : ""}${said ? `<p class="small text-2">Dit le ${h(said)}.</p>` : ""}</div></div>
      <div class="ag-f-titre"><h2>${h(o.title)}</h2><p class="ag-quand">${h(whenWords(o, v.today))} <span class="tag ${rcls}">${h(rword)}</span></p></div>
      <div class="ag-actions"><button class="btn sm mika" type="button" data-agaction="parler">${ico("sparkle", "sm")}Lui en parler</button></div>
      <p class="ag-ro">${ico("lock", "sm")}<span>C'est sa mémoire, montrée comme un agenda : on ne le modifie pas ici. Dis-le-lui : « c'est fait », « c'est reporté à lundi », « oublie ça ». Elle ne te montre que ce qui te concerne, jamais ce qu'un autre lui a confié.</span></p>
    </div></div></aside>`;
}

export function missingFiche(text: string): string {
  return `<aside class="pane ag-volet"><div class="pane-head ag-vh"><button class="btn sm ghost mobile-back" type="button" data-agfermer>${ico("chev-left", "sm")}Agenda</button><span class="grow"></span>
      <button class="btn icon ghost sm ag-vh-x" type="button" data-agfermer title="Fermer" aria-label="Fermer">${ico("x", "sm")}</button></div>
    <div class="pane-scroll"><div class="empty">${ico("agenda")}<p>${h(text)}</p></div></div></aside>`;
}

// ── les invitations ──────────────────────────────────────────────────

export function invitationsPanel(v: AgendaView, items: readonly AgendaItem[] | null, error: string, whenOf: (item: AgendaItem) => string): string {
  const card = (item: AgendaItem) => {
    const cal = calOf(v, item.calendar);
    const color = colorOf(cal);
    const place = item.location ? ` · ${firstPart(item.location)}` : "";
    return `<article class="ag-invcard"><button type="button" class="ag-invcard-head" data-agev="evenement/${item.event}${item.occurrence ? `/${encodeURIComponent(item.occurrence)}` : ""}" style="--c:var(--ag-${color})">${swatch(color)}
        <span class="grow"><b>${h(item.title || "(sans titre)")}</b><small>${h(whenOf(item))}${h(place)}</small>
        <small>${h(personName(item.organizer, v.names) || "Quelqu'un")} t'invite · ${h(item.calendar_name || cal?.name || "")}</small></span>${ico("chev-right", "sm")}</button>
      ${answerBox(item, true, v.names)}</article>`;
  };
  const list = items ?? [];
  const body = error
    ? `<div class="empty">${ico("alert")}<p>${h(error)}</p></div>`
    : !items
      ? `<div class="empty">${ico("refresh")}<p>Chargement…</p></div>`
      : list.length
        ? list.map(card).join("")
        : `<div class="empty">${ico("inbox")}<b>Tout est répondu</b><p>Une invitation reçue par Outlook, Google ou CalDAV — ou d'une personne qui a un compte ici — arrive ici, avec la réponse que Mika te prépare.</p></div>`;
  return `<aside class="pane ag-volet" aria-label="Les invitations">
    <div class="pane-head ag-vh"><button class="btn sm ghost mobile-back" type="button" data-agfermer>${ico("chev-left", "sm")}Agenda</button>
      <h2>Invitations</h2><span class="cnt">${list.length ? `${list.length} en attente` : items ? "aucune en attente" : ""}</span><span class="grow"></span>
      <button class="btn icon ghost sm ag-vh-x" type="button" data-agfermer title="Fermer" aria-label="Fermer">${ico("x", "sm")}</button></div>
    <div class="pane-scroll"><div class="ag-invs">${body}
      <p class="small muted ag-invs-note">Une invitation arrive par ton agenda (Outlook, Google, CalDAV) et ta réponse repart par lui. Mika prépare une réponse ; elle ne l'envoie jamais sans ton accord.</p>
    </div></div></aside>`;
}

/** « Mika te le rappelle » : les choix du menu « Changer », celui de l'agenda en premier. */
export function remindChoices(cal: AgendaCalendar | undefined): (readonly [string, string])[] {
  return [["", `Comme l'agenda (${mikaReminderWords(cal?.reminder ?? "non")})`], ...MIKA_REMINDERS];
}

