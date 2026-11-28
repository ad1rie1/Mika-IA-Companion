/**
 * Les dates de l'Agenda, pures : des jours (`AAAA-MM-JJ`) comptés sans heure d'été, des instants lus à l'heure d'un
 * fuseau (celui du serveur : une période et ce qu'on écrit s'y lisent, `protocole-moi.md` § 13), les mots d'un jour,
 * d'une heure, d'une période, et les bornes de chaque vue (Jour, Semaine, Mois, Planning). La semaine commence le lundi.
 */

export const JOURS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];
export const JC = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
export const MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
export const MC = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

export type View = "jour" | "semaine" | "mois" | "planning";
export const VIEWS: readonly (readonly [View, string])[] = [["jour", "Jour"], ["semaine", "Semaine"], ["mois", "Mois"], ["planning", "Planning"]];
/** Le Planning montre quatre semaines. */
export const PLANNING_DAYS = 28;

export const pad = (n: number): string => String(n).padStart(2, "0");
export const cap = (s: string): string => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

/** `minutes` depuis minuit → « 09:30 ». */
export function hm(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  return `${pad(Math.floor(m / 60) % 24)}:${pad(m % 60)}`;
}

// ── des jours ────────────────────────────────────────────────────────

const DAY_MS = 86_400_000;
const DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

export function isDay(text: string): boolean {
  return DAY.test(text);
}

function utc(key: string): number {
  const m = DAY.exec(key);
  if (!m) return NaN;
  return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

function keyOfUtc(ms: number): string {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

export function addDays(key: string, n: number): string {
  return keyOfUtc(utc(key) + n * DAY_MS);
}

/** Combien de jours de `a` à `b` (`b` après `a` : positif). */
export function daysFrom(a: string, b: string): number {
  return Math.round((utc(b) - utc(a)) / DAY_MS);
}

/** 0 : dimanche… 6 : samedi. */
export function weekday(key: string): number {
  return new Date(utc(key)).getUTCDay();
}

export function mondayOf(key: string): string {
  return addDays(key, -((weekday(key) + 6) % 7));
}

export function partsOf(key: string): { y: number; m: number; d: number } {
  const [y, m, d] = key.split("-").map(Number);
  return { y, m, d };
}

export function monthStart(key: string): string {
  return `${key.slice(0, 7)}-01`;
}

/** Le premier jour du mois, `n` mois plus loin. */
export function addMonths(key: string, n: number): string {
  const { y, m } = partsOf(key);
  const at = new Date(Date.UTC(y, m - 1 + n, 1));
  return keyOfUtc(at.getTime());
}

/** « 1er », « 23 ». */
export function dayNumber(key: string): string {
  const d = partsOf(key).d;
  return d === 1 ? "1er" : String(d);
}

/** « lundi 23 novembre » (l'année si ce n'est pas celle d'aujourd'hui). */
export function dayWords(key: string, today: string): string {
  const { y, m } = partsOf(key);
  return `${JOURS[weekday(key)]} ${dayNumber(key)} ${MOIS[m - 1]}${y !== partsOf(today).y ? ` ${y}` : ""}`;
}

/** « lun. 23 nov. ». */
export function shortDay(key: string): string {
  const { m, d } = partsOf(key);
  return `${JC[weekday(key)]} ${d} ${MC[m - 1]}`;
}

/** « aujourd'hui », « demain », « hier », sinon le jour en mots. */
export function nearDay(key: string, today: string): string {
  const e = daysFrom(today, key);
  return e === 0 ? "aujourd'hui" : e === 1 ? "demain" : e === -1 ? "hier" : dayWords(key, today);
}

// ── des instants, à l'heure d'un fuseau ──────────────────────────────

const FORMATS = new Map<string, Intl.DateTimeFormat>();

function formatOf(zone: string): Intl.DateTimeFormat {
  let f = FORMATS.get(zone);
  if (!f) {
    try {
      f = new Intl.DateTimeFormat("en-GB", { timeZone: zone || "UTC", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    } catch {
      f = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    }
    FORMATS.set(zone, f);
  }
  return f;
}

/** Le jour et la minute d'un instant (ms), à l'heure de `zone`. */
export function localOf(ms: number, zone: string): { day: string; minute: number } {
  const parts: Record<string, string> = {};
  for (const p of formatOf(zone).formatToParts(new Date(ms))) parts[p.type] = p.value;
  const hour = Number(parts.hour) % 24;
  return { day: `${parts.year}-${parts.month}-${parts.day}`, minute: hour * 60 + Number(parts.minute) };
}

/** Ce qu'un champ de formulaire écrit : « 2026-11-23T14:30 », à l'heure de `zone`. */
export function localInput(ms: number, zone: string): string {
  const { day, minute } = localOf(ms, zone);
  return `${day}T${hm(minute)}`;
}

/** Le décalage d'un fuseau à un instant, en mots courts : « UTC+1 », « UTC-5 », « UTC+5:30 ». */
export function offsetWords(zone: string, ms: number): string {
  const { day, minute } = localOf(ms, zone);
  const local = utc(day) + minute * 60_000;
  const off = Math.round((local - Math.floor(ms / 60_000) * 60_000) / 60_000);
  if (!off) return "UTC";
  const sign = off > 0 ? "+" : "-";
  const a = Math.abs(off);
  return `UTC${sign}${Math.floor(a / 60)}${a % 60 ? `:${pad(a % 60)}` : ""}`;
}

// ── les vues ─────────────────────────────────────────────────────────

/** Le premier jour d'une vue et le jour qui suit son dernier. */
export function bounds(view: View, date: string): [string, string] {
  if (view === "jour") return [date, addDays(date, 1)];
  if (view === "semaine") {
    const l = mondayOf(date);
    return [l, addDays(l, 7)];
  }
  if (view === "mois") {
    const first = mondayOf(monthStart(date));
    const next = addMonths(date, 1);
    return [first, addDays(first, Math.ceil(daysFrom(first, next) / 7) * 7)];
  }
  return [date, addDays(date, PLANNING_DAYS)];
}

/** Ce que la barre de titre dit de la période : « 23 – 29 novembre 2026 », « Novembre 2026 »… ; `short` : sur un
 *  téléphone. */
export function periodWords(view: View, date: string, today: string, short = false): string {
  const [first, after] = bounds(view, date);
  const last = addDays(after, -1);
  const a = partsOf(first);
  const b = partsOf(last);
  if (view === "jour") {
    const { y } = partsOf(date);
    return short ? cap(shortDay(date)) : `${cap(dayWords(date, today))}${y === partsOf(today).y ? ` ${y}` : ""}`;
  }
  if (view === "mois") {
    const { y, m } = partsOf(date);
    return `${cap(MOIS[m - 1])} ${y}`;
  }
  if (view === "semaine") {
    if (a.m === b.m) return short ? `${a.d} – ${b.d} ${MC[b.m - 1]}` : `${a.d} – ${b.d} ${MOIS[b.m - 1]} ${b.y}`;
    return `${a.d} ${MC[a.m - 1]} – ${b.d} ${MC[b.m - 1]}${short ? "" : ` ${b.y}`}`;
  }
  return short ? `Dès le ${a.d} ${MC[a.m - 1]}` : `À partir du ${dayWords(first, today)}`;
}

/** La date d'une vue un pas plus loin (`sense` : 1) ou plus tôt (-1) ; un mois qui revient à celui d'aujourd'hui y
 *  revient à aujourd'hui. */
export function step(view: View, date: string, sense: number, today: string): string {
  if (view === "mois") {
    const m = addMonths(date, sense);
    return m.slice(0, 7) === today.slice(0, 7) ? today : m;
  }
  return addDays(date, view === "jour" ? sense : view === "planning" ? PLANNING_DAYS * sense : 7 * sense);
}

/** Les 42 jours du mini-mois (six semaines, à partir du lundi). */
export function miniDays(month: string): string[] {
  const first = mondayOf(monthStart(month));
  return Array.from({ length: 42 }, (_, i) => addDays(first, i));
}

/** « Novembre 2026 ». */
export function monthWords(key: string): string {
  const { y, m } = partsOf(key);
  return `${cap(MOIS[m - 1])} ${y}`;
}
