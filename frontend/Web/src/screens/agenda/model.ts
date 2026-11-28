/**
 * Ce que l'Agenda montre, pur : les occurrences d'une période (les événements de ses agendas, les dates de « L'agenda de
 * Mika », ce que Mika propose d'ajouter), leur sorte (une invitation, un « peut-être », une proposition, sa mémoire),
 * leur couleur, leur place dans la grille (les chevauchements en colonnes, les journées en bandes), les mots de leur
 * moment, de leur répétition, de leurs rappels ; les adresses de l'écran (`#agenda/…`).
 */
import type { AgendaCalendar, AgendaItem, AgendaRights, AgendaRule, Alert, HerDate, MikaReminder, Proposal } from "../../api/agenda";
import { ofName } from "../../shared/names";
import { addDays, cap, daysFrom, dayNumber, dayWords, hm, JOURS, localOf, MOIS, pad, partsOf, weekday } from "./dates";

export type OccKind = "event" | "her" | "proposal";

/** Une occurrence à montrer. */
export interface Occ {
  /** Sa clé dans l'adresse (`evenement/42/20261125T130000Z`, `proposition/7`, `memoire/<ref>`). */
  key: string;
  kind: OccKind;
  title: string;
  /** La clé de son agenda (`mika` pour sa mémoire). */
  calendar: string;
  /** Son premier et son dernier jour (compris), à l'heure du serveur. */
  day: string;
  last: string;
  /** Une journée entière (ou plusieurs), ou un rendez-vous de 24 h et plus : une bande. */
  allDay: boolean;
  /** Ses minutes dans son premier jour (un rendez-vous ; la fin bornée à minuit). */
  start: number;
  end: number;
  startMs: number;
  endMs: number;
  item?: AgendaItem;
  her?: HerDate;
  proposal?: Proposal;
}

// ── les adresses ─────────────────────────────────────────────────────

export const ID = "agenda";

export function eventKey(event: number, occurrence: string): string {
  return occurrence ? `evenement/${event}/${encodeURIComponent(occurrence)}` : `evenement/${event}`;
}

export function proposalKey(id: number): string {
  return `proposition/${id}`;
}

export function herKey(ref: string): string {
  return `memoire/${encodeURIComponent(ref)}`;
}

export type Target =
  | { kind: "event"; event: number; occurrence: string }
  | { kind: "proposal"; id: number }
  | { kind: "her"; ref: string };

/** Ce qu'une clé d'adresse désigne (`evenement/42[/occ]`, `proposition/7`, `memoire/ref`) ; `null` : rien. */
export function targetOf(parts: readonly string[]): Target | null {
  const [kind, a, b] = parts;
  if (kind === "evenement" && /^\d+$/.test(a ?? "")) return { kind: "event", event: Number(a), occurrence: b ?? "" };
  if (kind === "proposition" && /^\d+$/.test(a ?? "")) return { kind: "proposal", id: Number(a) };
  if (kind === "memoire" && a) return { kind: "her", ref: a };
  return null;
}

export function targetKey(t: Target): string {
  return t.kind === "event" ? eventKey(t.event, t.occurrence) : t.kind === "proposal" ? proposalKey(t.id) : herKey(t.ref);
}

// ── des données aux occurrences ──────────────────────────────────────

const HOUR_MS = 3_600_000;

function placed(startMs: number, endMs: number, allDay: boolean, firstDay: string, lastDay: string, zone: string): Pick<Occ, "day" | "last" | "allDay" | "start" | "end"> {
  if (allDay && firstDay) return { day: firstDay, last: lastDay || firstDay, allDay: true, start: 0, end: 1440 };
  const a = localOf(startMs, zone);
  const b = localOf(Math.max(startMs, endMs), zone);
  if (endMs - startMs >= 24 * HOUR_MS) {
    // un rendez-vous de plusieurs jours : une bande, du jour où il commence à celui où il finit
    const last = b.minute === 0 && b.day > a.day ? addDays(b.day, -1) : b.day;
    return { day: a.day, last, allDay: true, start: a.minute, end: 1440 };
  }
  const end = b.day > a.day ? 1440 : Math.max(b.minute, a.minute);
  return { day: a.day, last: a.day, allDay: false, start: a.minute, end };
}

export function occOfItem(item: AgendaItem, zone: string): Occ {
  return {
    key: eventKey(item.event, item.occurrence),
    kind: "event",
    title: item.masked ? "Occupé" : item.title || "(sans titre)",
    calendar: item.calendar,
    startMs: item.start,
    endMs: item.end,
    item,
    ...placed(item.start, item.end, item.all_day, item.first_day, item.last_day, zone),
  };
}

export function occOfHer(her: HerDate, zone: string): Occ {
  return {
    key: herKey(her.ref),
    kind: "her",
    title: her.title,
    calendar: "mika",
    startMs: her.start,
    endMs: her.end,
    her,
    ...placed(her.start, Math.max(her.end, her.start), her.all_day, her.all_day ? her.day || localOf(her.start, zone).day : "", her.all_day ? her.day || localOf(her.start, zone).day : "", zone),
  };
}

export function occOfProposal(p: Proposal, zone: string): Occ | null {
  const d = p.draft;
  if (!d) return null;
  const allDay = d.all_day;
  const first = allDay ? localOf(d.start, "UTC").day : "";
  const last = allDay ? localOf(Math.max(d.start, d.end - 86_400_000), "UTC").day : "";
  return {
    key: proposalKey(p.id),
    kind: "proposal",
    title: d.title || "(sans titre)",
    calendar: p.calendar,
    startMs: d.start,
    endMs: d.end,
    proposal: p,
    ...placed(d.start, d.end, allDay, first, last, zone),
  };
}

/** Dans l'ordre : par jour, les journées d'abord, puis l'heure. */
export function sortOccs(occs: Occ[]): Occ[] {
  return occs.sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : 0) || Number(b.allDay) - Number(a.allDay) || a.start - b.start || a.title.localeCompare(b.title));
}

/** Les occurrences qui touchent [first, after[. */
export function within(occs: readonly Occ[], first: string, after: string): Occ[] {
  return occs.filter((o) => o.last >= first && o.day < after);
}

// ── leur sorte, leur couleur ─────────────────────────────────────────

export type Sort = "propose" | "invite" | "peut" | "mika" | "";

export function sortOf(o: Occ): Sort {
  if (o.kind === "proposal") return "propose";
  if (o.kind === "her") return "mika";
  if (o.item?.invitation) return "invite";
  if (o.item?.response === "peut") return "peut";
  return "";
}

export const PALETTE = ["indigo", "bleu", "sarcelle", "vert", "ambre", "orange", "violet", "ardoise"] as const;
const RGB: Record<(typeof PALETTE)[number], [number, number, number]> = {
  indigo: [79, 70, 229], bleu: [31, 111, 208], sarcelle: [15, 139, 128], vert: [30, 154, 75], ambre: [192, 132, 6],
  orange: [226, 106, 27], violet: [139, 92, 246], ardoise: [102, 116, 138],
};

/** La couleur de la palette la plus proche d'une couleur `#rrggbb` du fournisseur ; illisible : rien. */
export function nearestColor(hex: string): string {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex.trim());
  if (!m) return "";
  const [r, g, b] = [1, 2, 3].map((i) => parseInt(m[i], 16));
  let best = "";
  let dist = Infinity;
  for (const name of PALETTE) {
    const [x, y, z] = RGB[name];
    const d = (r - x) ** 2 + (g - y) ** 2 + (b - z) ** 2;
    if (d < dist) {
      dist = d;
      best = name;
    }
  }
  return best;
}

/** La couleur d'un agenda : la sienne, celle du fournisseur rapprochée de la palette, sinon une couleur stable ; le
 *  rose est à Mika. */
export function colorOf(cal: (Pick<AgendaCalendar, "key" | "color" | "provider_color" | "kind"> & { primary?: boolean; level?: string }) | undefined): string {
  if (!cal) return "ardoise";
  if (cal.kind === "mika") return "rose";
  if (cal.color) return cal.color;
  // « Mon agenda » : l'indigo, sa couleur de départ (le sien ; celui qu'on te partage prend une autre)
  if (cal.kind === "systeme" && cal.primary && (cal.level ?? "proprietaire") === "proprietaire") return "indigo";
  const near = nearestColor(cal.provider_color || "");
  if (near) return near;
  let x = 0;
  for (const ch of cal.key) x = (x * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[x % PALETTE.length];
}

// ── la grille : les chevauchements ───────────────────────────────────

export interface Placed {
  o: Occ;
  /** Ses minutes, et au moins une demi-heure de haut. */
  from: number;
  to: number;
  col: number;
  cols: number;
}

/** Les rendez-vous d'une journée : ceux qui se touchent se partagent la largeur, en colonnes. */
export function columns(occs: readonly Occ[]): Placed[] {
  const evs: Placed[] = occs.map((o) => ({ o, from: o.start, to: Math.max(o.end, o.start + 24), col: 0, cols: 1 }))
    .sort((a, b) => a.from - b.from || b.to - a.to);
  let group: Placed[] = [];
  let end = -1;
  const flush = () => {
    const cols: number[] = [];
    for (const e of group) {
      let c = cols.findIndex((f) => f <= e.from);
      if (c < 0) {
        c = cols.length;
        cols.push(e.to);
      } else cols[c] = e.to;
      e.col = c;
    }
    for (const e of group) e.cols = cols.length;
    group = [];
  };
  for (const e of evs) {
    if (group.length && e.from >= end) {
      flush();
      end = -1;
    }
    group.push(e);
    end = Math.max(end, e.to);
  }
  if (group.length) flush();
  return evs;
}

export interface Lane {
  o: Occ;
  /** Ses colonnes dans la semaine (0 à n-1). */
  from: number;
  to: number;
  lane: number;
}

/** Les journées d'une semaine (ou d'un jour) en bandes : chacune sur sa ligne libre. */
export function lanes(occs: readonly Occ[], first: string, n: number): Lane[] {
  const out: Lane[] = occs
    .map((o) => ({ o, from: Math.max(0, daysFrom(first, o.day)), to: Math.min(n - 1, daysFrom(first, o.last)), lane: 0 }))
    .sort((a, b) => a.from - b.from || (b.to - b.from) - (a.to - a.from));
  const ends: number[] = [];
  for (const x of out) {
    let l = ends.findIndex((f) => f < x.from);
    if (l < 0) {
      l = ends.length;
      ends.push(x.to);
    } else ends[l] = x.to;
    x.lane = l;
  }
  return out;
}

// ── les mots ─────────────────────────────────────────────────────────

/** « Lundi 23 novembre · 14:00 – 15:00 », « Du … au … · journées entières ». */
export function whenWords(o: Occ, today: string): string {
  if (o.allDay) {
    if (o.day === o.last) return `${cap(dayWords(o.day, today))} · journée entière`;
    return `Du ${dayWords(o.day, today)} au ${dayWords(o.last, today)} · journées entières`;
  }
  return `${cap(dayWords(o.day, today))} · ${hm(o.start)} – ${hm(o.end)}`;
}

/** Où il en est par rapport à maintenant : `["accent", "dans 40 min"]`, `["ok", "en cours"]`, `["", "passé"]`… */
export function relative(o: Occ, today: string, nowMinute: number): [string, string] {
  const e = daysFrom(today, o.day);
  if (o.allDay) {
    if (daysFrom(today, o.last) < 0) return ["", "passé"];
    if (e <= 0) return ["accent", "aujourd'hui"];
    return ["", e === 1 ? "demain" : `dans ${e} jours`];
  }
  if (isPast(o, today, nowMinute)) return ["", "passé"];
  if (e === 0 && o.start <= nowMinute) return ["ok", "en cours"];
  if (e === 0) {
    const m = o.start - nowMinute;
    return ["accent", m < 60 ? `dans ${m} min` : `dans ${Math.floor(m / 60)} h${m % 60 ? ` ${pad(m % 60)}` : ""}`];
  }
  return ["", e === 1 ? "demain" : `dans ${e} jours`];
}

export function isPast(o: Occ, today: string, nowMinute: number): boolean {
  return daysFrom(today, o.last) < 0 || (o.last === today && !o.allDay && o.end <= nowMinute);
}

/** « Mika te le rappelle » en mots. */
export const MIKA_REMINDERS: readonly (readonly [Exclude<MikaReminder, "">, string])[] = [
  ["non", "Non"], ["15", "15 min avant"], ["30", "30 min avant"], ["60", "1 h avant"], ["veille", "La veille au soir"],
];

export function mikaReminderWords(value: string): string {
  return ({ non: "non", 15: "15 min avant", 30: "30 min avant", 60: "1 h avant", veille: "la veille au soir" } as Record<string, string>)[value] ?? value;
}

/** Un rappel du fournisseur en mots : « notification 10 min avant », « e-mail 1 jour avant ». */
export function alertWords(a: Alert): string {
  const how = a.method === "email" ? "e-mail" : "notification";
  return `${how} ${durationWords(a.minutes)} avant`;
}

export function durationWords(minutes: number): string {
  if (minutes === 0) return "au début,";
  if (minutes % 1440 === 0) return `${minutes / 1440} jour${minutes / 1440 > 1 ? "s" : ""}`;
  if (minutes % 60 === 0) return `${minutes / 60} h`;
  return `${minutes} min`;
}

/** Un rappel du fournisseur en champs : la valeur et son unité (minutes, heures, jours). */
export function alertUnit(minutes: number): { n: number; unit: "minutes" | "heures" | "jours" } {
  if (minutes && minutes % 1440 === 0) return { n: minutes / 1440, unit: "jours" };
  if (minutes && minutes % 60 === 0) return { n: minutes / 60, unit: "heures" };
  return { n: minutes, unit: "minutes" };
}

export function alertMinutes(n: number, unit: string): number {
  const v = Math.max(0, Math.round(Number.isFinite(n) ? n : 0));
  return unit === "jours" ? v * 1440 : unit === "heures" ? v * 60 : v;
}

/** Où part une écriture, selon la sorte de l'agenda. */
export function whereWords(kind: string): string {
  return ({ systeme: "sur ce serveur", google: "chez Google", microsoft: "chez Microsoft", caldav: "chez le serveur CalDAV" } as Record<string, string>)[kind] ?? "";
}

/** Ce que le fournisseur de l'agenda est, en court. */
export function providerShort(cal: AgendaCalendar): string {
  if (cal.group === "shared") return `de ${cal.owner_name || "quelqu'un"} · ${levelWords(cal.level).toLowerCase()}`;
  if (cal.kind === "mika") return "sa mémoire · lecture seule";
  if (cal.kind === "ical") return "abonnement iCal";
  if (cal.kind === "systeme") return "Système";
  if (cal.kind === "microsoft") return "Outlook";
  if (cal.kind === "caldav") return "CalDAV";
  if (cal.kind === "google") return "Google";
  return cal.kind_label;
}

export const LEVELS: Record<string, [string, string]> = {
  lire: ["Lire", "voit ses événements dans son Agenda, sans rien y changer."],
  preparer: ["Lire et préparer", "les voit, et Mika peut y préparer un ajout pour elle ou lui : il n'entre qu'avec ton accord."],
  servir: ["S'en servir", "Mika s'en sert avec elle ou lui, en tête-à-tête : trouver un créneau, y ajouter un rendez-vous, selon ton tableau de droits."],
};

export function levelWords(level: string): string {
  return LEVELS[level]?.[0] ?? level;
}

// ── la répétition ────────────────────────────────────────────────────

const BYDAY = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"];

export type RepeatChoice = "" | "jour" | "semaine" | "mois" | "an" | "perso";

export interface CustomRule {
  interval: number;
  unit: "jours" | "semaines" | "mois" | "ans";
  /** Les jours d'une répétition par semaines (0 : dimanche… 6 : samedi). */
  days: number[];
  ends: "jamais" | "le" | "apres";
  until: string;
  count: number;
}

/** La règle RFC 5545 d'un choix du formulaire, au jour `day` ; « Ne se répète pas » : vide. */
export function ruleOf(choice: RepeatChoice, day: string, custom?: CustomRule): string {
  if (choice === "jour") return "FREQ=DAILY";
  if (choice === "semaine") return `FREQ=WEEKLY;BYDAY=${BYDAY[weekday(day)]}`;
  if (choice === "mois") return `FREQ=MONTHLY;BYMONTHDAY=${partsOf(day).d}`;
  if (choice === "an") return "FREQ=YEARLY";
  if (choice !== "perso" || !custom) return "";
  const freq = { jours: "DAILY", semaines: "WEEKLY", mois: "MONTHLY", ans: "YEARLY" }[custom.unit];
  const parts = [`FREQ=${freq}`];
  if (custom.interval > 1) parts.push(`INTERVAL=${Math.min(999, Math.round(custom.interval))}`);
  if (custom.unit === "semaines") {
    const days = custom.days.length ? [...new Set(custom.days)].sort((a, b) => ((a + 6) % 7) - ((b + 6) % 7)) : [weekday(day)];
    parts.push(`BYDAY=${days.map((d) => BYDAY[d]).join(",")}`);
  }
  if (custom.ends === "le" && /^\d{4}-\d{2}-\d{2}$/.test(custom.until)) parts.push(`UNTIL=${custom.until.replace(/-/g, "")}`);
  if (custom.ends === "apres" && custom.count > 0) parts.push(`COUNT=${Math.min(9999, Math.round(custom.count))}`);
  return parts.join(";");
}

/** Le choix du formulaire qui redit une règle au jour `day` (une autre : « Personnalisée »). */
export function choiceOf(rule: string, day: string): RepeatChoice {
  if (!rule) return "";
  for (const c of ["jour", "semaine", "mois", "an"] as const) if (ruleOf(c, day) === rule) return c;
  return "perso";
}

/** Une règle lue dans les champs de « Personnalisée ». */
export function customOf(rule: string, day: string): CustomRule {
  const parts = Object.fromEntries(rule.split(";").map((p) => p.split("=") as [string, string]));
  const unit = ({ DAILY: "jours", WEEKLY: "semaines", MONTHLY: "mois", YEARLY: "ans" } as const)[parts.FREQ as "DAILY"] ?? "semaines";
  const days = (parts.BYDAY ?? "").split(",").map((d: string) => BYDAY.indexOf(d.replace(/^[+-]?\d+/, ""))).filter((d: number) => d >= 0);
  const until = /^\d{8}/.test(parts.UNTIL ?? "") ? `${parts.UNTIL.slice(0, 4)}-${parts.UNTIL.slice(4, 6)}-${parts.UNTIL.slice(6, 8)}` : "";
  return {
    interval: Number(parts.INTERVAL) || 1,
    unit,
    days: days.length ? days : [weekday(day)],
    ends: until ? "le" : parts.COUNT ? "apres" : "jamais",
    until,
    count: Number(parts.COUNT) || 10,
  };
}

/** Une règle en mots : « Chaque lundi », « Chaque année, le 28 novembre », « Toutes les 2 semaines, le lundi et le
 *  jeudi », « jusqu'au … », « 5 fois ». */
export function ruleWords(rule: string, day: string, today: string): string {
  if (!rule) return "";
  const c = customOf(rule, day);
  const parts = Object.fromEntries(rule.split(";").map((p) => p.split("=") as [string, string]));
  let base: string;
  const names = (days: number[]) => {
    const w = days.map((d) => JOURS[d]);
    return w.length === 1 ? w[0] : `${w.slice(0, -1).join(", ")} et ${w[w.length - 1]}`;
  };
  if (c.unit === "jours") base = c.interval > 1 ? `Tous les ${c.interval} jours` : "Chaque jour";
  else if (c.unit === "semaines") base = c.interval > 1 ? `Toutes les ${c.interval} semaines, le ${names(c.days)}` : `Chaque ${names(c.days)}`;
  else if (c.unit === "mois") base = `${c.interval > 1 ? `Tous les ${c.interval} mois` : "Chaque mois"}, le ${parts.BYMONTHDAY ? (parts.BYMONTHDAY === "1" ? "1er" : parts.BYMONTHDAY) : dayNumber(day)}`;
  else base = `${c.interval > 1 ? `Tous les ${c.interval} ans` : "Chaque année"}, le ${dayNumber(day)} ${MOIS[partsOf(day).m - 1]}`;
  if (c.ends === "le" && c.until) base += `, jusqu'au ${dayWords(c.until, today)}`;
  if (c.ends === "apres" && parts.COUNT) base += `, ${parts.COUNT} fois`;
  return base;
}

/** Les choix du formulaire, dits pour le jour `day`. */
export function repeatChoices(day: string): (readonly [RepeatChoice, string])[] {
  return [
    ["", "Ne se répète pas"],
    ["jour", "Chaque jour"],
    ["semaine", `Chaque semaine, le ${JOURS[weekday(day)]}`],
    ["mois", `Chaque mois, le ${dayNumber(day)}`],
    ["an", `Chaque année, le ${dayNumber(day)} ${MOIS[partsOf(day).m - 1]}`],
    ["perso", "Personnalisée…"],
  ];
}

// ── le tableau de droits d'un agenda, en mots ────────────────────────

/** La ligne de son propriétaire quand Mika lui répond : la première qui la nomme (`personne:<sa clé>`, ou « toi »). */
export function ownerLine(t: AgendaRights, me: string, moment = "conversation"): AgendaRule | null {
  return t.lines.find((l) => (l.who.includes(`personne:${me}`) || l.who.includes("proprietaire")) && (!l.when.length || l.when.includes(moment))) ?? null;
}

/** Ce que Mika fait d'un agenda, en une ligne : « Avec toi, elle le lit, y ajoute avec ton accord, prépare tes réponses ;
 *  elle te rappelle ses rendez-vous · aussi avec Léa ». */
export function rightsSummary(t: AgendaRights, me: string, shares: readonly { name: string }[] = [], writable = true): string {
  const l = ownerLine(t, me);
  if (!l) return "";
  // un agenda qu'on n'écrit pas d'ici (un abonnement) : elle ne fait que le lire, quoi que dise son tableau
  const write = writable ? { non: "n'y écrit pas", accord: "y ajoute avec ton accord", seule: "y ajoute seule" }[l.write] ?? "" : "";
  const parts = [l.read ? "le lit" : "ne le lit pas", l.read ? write : "", writable && l.respond === "accord" ? "prépare tes réponses" : ""].filter(Boolean);
  const initiative = ownerLine(t, me, "initiative");
  const remind = initiative && initiative !== l && initiative.read ? " ; elle te rappelle ses rendez-vous" : "";
  const first = (n: string) => n.split(/\s+/)[0] || n;
  const others = shares.length ? ` · aussi avec ${shares.map((s) => first(s.name)).join(" et ")}` : "";
  return `Avec toi, elle ${parts.join(", ")}${remind}${others}`;
}

/** Le nom qu'on montre d'un agenda : « Mon agenda » d'une autre personne, qu'elle te partage, devient « Agenda de Léa »
 *  (le sien et le tien porteraient le même nom). */
export function shownName(cal: AgendaCalendar): string {
  if (cal.group === "shared" && cal.kind === "systeme" && cal.primary && cal.name === "Mon agenda" && cal.owner_name) {
    return `Agenda ${ofName(cal.owner_name.split(/\s+/)[0] || cal.owner_name)}`;
  }
  return cal.name;
}

/** Ses agendas, chacun sous le nom qu'on lui montre. */
export function withShownNames(list: readonly AgendaCalendar[]): AgendaCalendar[] {
  return list.map((c) => {
    const name = shownName(c);
    return name === c.name ? c : { ...c, name };
  });
}
