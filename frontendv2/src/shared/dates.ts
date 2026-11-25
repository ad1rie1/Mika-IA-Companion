/**
 * Les heures et les jours en court, comme une liste de messagerie : « 14:05 », « hier », « lun. », « 28 oct. »,
 * « aujourd'hui 14:05 ». Le chat, Mail, Teams, Contacts, Téléphone et Paramètres les partagent ; les dates en mots
 * (« lundi 2 novembre », « il y a 3 min », « dans 1 h 52 ») sont dans `kit.ts`. Pur.
 */

/** « 14:05 ». */
export function clock(ts: number): string {
  if (!Number.isFinite(ts) || ts <= 0) return "";
  return new Date(ts).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

const WEEKDAYS = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

function dayStart(ms: number): number {
  const d = new Date(ms);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** Quand, en court, comme une liste de messagerie : « 13:31 », « hier », « lun. », « 28 oct. ». */
export function shortWhen(ms: number, now: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "";
  const days = Math.round((dayStart(now) - dayStart(ms)) / 86_400_000);
  if (days <= 0) return clock(ms);
  if (days === 1) return "hier";
  const d = new Date(ms);
  if (days < 7) return WEEKDAYS[d.getDay()];
  const label = `${d.getDate()} ${MONTHS[d.getMonth()]}`;
  return d.getFullYear() === new Date(now).getFullYear() ? label : `${label} ${d.getFullYear()}`;
}

/** « aujourd'hui 14:05 », « hier 21:41 », « lun. 08:12 », « 28 oct. 13:31 ». */
export function dayAndClock(ms: number, now: number): string {
  const day = shortWhen(ms, now);
  if (!day) return "";
  const time = clock(ms);
  return day === time ? `aujourd'hui ${time}` : `${day} ${time}`;
}
