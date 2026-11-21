/**
 * Projets, le temps (pur) : les mots de la maquette pour un instant en millisecondes (0 : jamais), face à `now`.
 */
const DAYS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];
const DAYS_SHORT = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
const MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
const MONTHS_SHORT = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

export const DAY_MS = 86_400_000;

/** Minuit, heure locale, du jour d'un instant. */
export function dayStart(ms: number): number {
  const d = new Date(ms);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** Combien de jours pleins séparent un instant d'aujourd'hui (0 : aujourd'hui, 1 : hier). */
export function daysAgo(ms: number, now: number): number {
  return Math.round((dayStart(now) - dayStart(ms)) / DAY_MS);
}

/** « 14:05 ». */
export function clock(ms: number): string {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** « 3 nov. ». */
export function shortDate(ms: number): string {
  const d = new Date(ms);
  return `${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`;
}

/** Le repère d'un jour : « Aujourd'hui », « Hier », « Demain », « lundi 2 novembre » — passé ou à venir (un prochain passage). */
export function dayLabel(ms: number, now: number): string {
  const n = daysAgo(ms, now);
  const d = new Date(ms);
  return n === 0 ? "Aujourd'hui" : n === 1 ? "Hier" : n === -1 ? "Demain" : `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

/** Depuis quand, en court : « à l'instant », « il y a 6 min », « il y a 4 h », « hier », « samedi », « 3 nov. ». */
export function when(ms: number, now: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "";
  const minutes = Math.floor((now - ms) / 60_000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const n = daysAgo(ms, now);
  if (n <= 0) return `il y a ${Math.floor(minutes / 60)} h`;
  if (n === 1) return "hier";
  return n < 7 ? DAYS[new Date(ms).getDay()] : shortDate(ms);
}

/** L'âge d'une ligne serrée : `when` sans « il y a ». */
export function age(ms: number, now: number): string {
  return when(ms, now).replace(/^il y a /, "");
}

/** Un instant dit en entier : « aujourd'hui à 14:14 », « hier à 09:02 », « lundi 2 novembre à 18:40 ». */
export function moment(ms: number, now: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "";
  if (now - ms < 60_000 && now >= ms) return "à l'instant";
  return `${dayLabel(ms, now).toLowerCase()} à ${clock(ms)}`;
}

/** Une durée en secondes : « 45 s », « 12 min », « 1 h 05 ». */
export function duration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")}`;
}

/** Le jour de l'axe d'un diagramme : son numéro, son jour court, son mois court. */
export function axisDay(ms: number): { n: number; day: string; month: string; monday: boolean; weekend: boolean } {
  const d = new Date(ms);
  return { n: d.getDate(), day: DAYS_SHORT[d.getDay()], month: MONTHS_SHORT[d.getMonth()], monday: d.getDay() === 1, weekend: d.getDay() === 0 || d.getDay() === 6 };
}
