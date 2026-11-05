/**
 * Les mots d'une carte, en français : distances, durées, modes, ce qu'un trajet évite, les jours d'un voyage. Purs : le
 * chat (ses miniatures) et l'écran Carte les partagent.
 */
/** « 14:05 » (comme `screens/chat/markup.ts::clock`). */
function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

/** Un espace insécable entre les milliers : « 1 388 km » ne se coupe pas en fin de ligne. */
function grouped(n: number): string {
  return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

/** « 850 m », « 5,8 km », « 47 km », « 1 388 km ». */
export function km(meters: number | null | undefined): string {
  if (typeof meters !== "number" || !Number.isFinite(meters) || meters < 0) return "";
  if (meters < 1000) return `${Math.max(0, Math.round(meters / 10) * 10)} m`;
  if (meters < 10_000) return `${(meters / 1000).toFixed(1).replace(".", ",").replace(",0", "")} km`;
  return `${grouped(meters / 1000)} km`;
}

/** « 1 min », « 45 min », « 7 h 05 », « 16 h ». */
export function duration(seconds: number | null | undefined): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "";
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${String(rest).padStart(2, "0")}` : `${hours} h`;
}

export const MODE_LABELS: Record<string, string> = { voiture: "Voiture", velo: "Vélo", pied: "À pied" };
const MODE_WORDS: Record<string, string> = { voiture: "en voiture", velo: "à vélo", pied: "à pied" };

/** « en voiture », « à vélo », « à pied ». */
export function modeWords(mode: string): string {
  return MODE_WORDS[mode] ?? mode;
}

/** Ce qu'un trajet évite, en mots : « sans péage ni autoroute », ou « péages acceptés » en voiture. */
export function avoidWords(avoid: readonly string[], mode = "voiture"): string {
  const parts = [
    ...(avoid.includes("peages") ? ["péage"] : []),
    ...(avoid.includes("autoroutes") ? ["autoroute"] : []),
    ...(avoid.includes("ferries") ? ["ferry"] : []),
  ];
  if (!parts.length) return mode === "voiture" ? "péages acceptés" : "";
  return `sans ${parts.length > 1 ? `${parts.slice(0, -1).join(", ")} ni ${parts[parts.length - 1]}` : parts[0]}`;
}

const WEEKDAYS = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
const MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
  "novembre", "décembre"];

/** Une date `AAAA-MM-JJ` en date locale (minuit), sinon `null`. */
export function isoDay(text: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text.trim());
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.getMonth() === Number(m[2]) - 1 ? d : null;
}

/** `AAAA-MM-JJ` d'une date locale. */
export function isoOf(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function dayNumber(d: Date): string {
  return d.getDate() === 1 ? "1er" : String(d.getDate());
}

/** « sam. 3 avril » (et l'année, si ce n'est pas celle de `now`). */
export function dayLabel(iso: string, now: number): string {
  const d = isoDay(iso);
  if (!d) return "";
  const year = d.getFullYear() !== new Date(now).getFullYear() ? ` ${d.getFullYear()}` : "";
  return `${WEEKDAYS[d.getDay()]} ${dayNumber(d)} ${MONTHS[d.getMonth()]}${year}`;
}

/**
 * Les dates d'un voyage : « sam. 3 avril », « sam. 21 et dim. 22 novembre », « du sam. 3 au mer. 7 avril 2027 » ;
 * « · passé » quand son dernier jour l'est. Sans date de départ : vide.
 */
export function tripDates(start: string, days: number, now: number): string {
  const first = isoDay(start);
  if (!first) return "";
  const n = Math.max(1, days);
  const last = new Date(first.getFullYear(), first.getMonth(), first.getDate() + n - 1);
  const year = last.getFullYear() !== new Date(now).getFullYear() ? ` ${last.getFullYear()}` : "";
  const sameMonth = first.getMonth() === last.getMonth() && first.getFullYear() === last.getFullYear();
  const a = `${WEEKDAYS[first.getDay()]} ${dayNumber(first)}${sameMonth ? "" : ` ${MONTHS[first.getMonth()]}`}`;
  const b = `${WEEKDAYS[last.getDay()]} ${dayNumber(last)} ${MONTHS[last.getMonth()]}${year}`;
  const text = n === 1 ? b : n === 2 ? `${a} et ${b}` : `du ${a} au ${b}`;
  const today = new Date(now);
  const past = last.getTime() < new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
  return past ? `${text} · passé` : text;
}

/** Le dernier jour d'un voyage est-il passé ? */
export function tripPast(start: string, days: number, now: number): boolean {
  return tripDates(start, days, now).endsWith("· passé");
}

/** « arrivée vers 15:35 si tu pars maintenant ». */
export function arrival(now: number, seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "";
  return `arrivée vers ${clock(now + seconds * 1000)} si tu pars maintenant`;
}

/** « 3 jours », « 1 arrêt ». */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("fr-FR")} ${n > 1 ? many : one}`;
}

/** Ce qu'est un lieu, en une ligne : « Camping · Sévrier ». */
export function placeWhat(p: { kind_fr?: string; town?: string; category?: string }): string {
  return [p.kind_fr || (p.category === "adresse" ? "Adresse" : ""), p.town].filter(Boolean).join(" · ");
}
