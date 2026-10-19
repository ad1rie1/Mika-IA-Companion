/**
 * Les petites bulles de ce qu'elle a fait en écrivant un message (ADR 0119).
 * Aujourd'hui une seule sorte : elle a regardé où était la personne, d'après
 * son téléphone — « 📍 Mika a regardé où tu es · Rue de la République, Lyon ·
 * position de 14:10 », posée juste avant sa réponse. Le navigateur, lui,
 * n'envoie jamais de position : il montre seulement qu'elle a regardé.
 *
 * Fonctions pures, à part du DOM comme `toolActivity.ts` : la validation de
 * `notes` (une liste illisible ne fait jamais perdre le message) et le texte
 * de la bulle. ChatOverlay ne fait que peindre, en `textContent`.
 */

import type { MessageNote } from "../types";

/** La seule sorte connue ; une autre s'ignore. */
export const LOCATION = "location";
/** Une réponse ne regarde pas la position des dizaines de fois. */
export const MAX_NOTES = 10;
/** Le serveur borne le lieu à 200 caractères ; on garde de la marge. */
export const MAX_NOTE_CHARS = 400;
/** En deçà, la position est celle du moment : son heure n'apprend rien. */
export const STALE_FIX_MS = 2 * 60 * 1000;

/**
 * Les petites bulles d'un message, validées : la sorte `location` seulement,
 * le lieu sur une ligne (vide s'il manque : elle a quand même regardé),
 * l'instant de la mesure (`0` s'il est illisible : la bulle ne dit pas
 * d'heure). Une bulle redite à l'identique ne compte qu'une fois. Ce qui
 * n'est pas un tableau vaut une liste vide.
 */
export function messageNotes(raw: unknown): MessageNote[] {
  if (!Array.isArray(raw)) return [];
  const out: MessageNote[] = [];
  for (const item of raw as Array<Partial<MessageNote> | null>) {
    if (!item || typeof item !== "object" || item.kind !== LOCATION) continue;
    const text =
      typeof item.text === "string" ? item.text.slice(0, MAX_NOTE_CHARS).replace(/\s+/g, " ").trim() : "";
    const at = typeof item.at === "number" && Number.isFinite(item.at) && item.at > 0 ? item.at : 0;
    if (out.some((n) => n.text === text && n.at === at)) continue;
    out.push({ kind: LOCATION, text, at });
    if (out.length >= MAX_NOTES) break;
  }
  return out;
}

export function sameNotes(a: readonly MessageNote[] | undefined, b: readonly MessageNote[] | undefined): boolean {
  const x = a ?? [];
  const y = b ?? [];
  return x.length === y.length && x.every((n, i) => n.kind === y[i].kind && n.text === y[i].text && n.at === y[i].at);
}

/**
 * De quand datait la position, quand ça compte : rien pour une mesure du
 * moment (moins de 2 min avant son message), « position de 14:10 » sinon,
 * « position du 18/10 à 23:50 » d'un autre jour que son message. Les mêmes
 * heure et date, en `fr-FR`, que l'infobulle des bulles.
 */
function fixLabel(at: number, messageTs: number): string {
  if (!(at > 0)) return "";
  const known = Number.isFinite(messageTs) && messageTs > 0;
  if (known && messageTs - at < STALE_FIX_MS) return "";
  const fix = new Date(at);
  const time = fix.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  if (!known || fix.toDateString() === new Date(messageTs).toDateString()) return `position de ${time}`;
  return `position du ${fix.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })} à ${time}`;
}

/** Le texte d'une petite bulle, posée avant son message de l'instant `messageTs` (ms). */
export function noteLine(note: MessageNote, messageTs: number): string {
  const parts = ["📍 Mika a regardé où tu es"];
  const place = note.text.trim();
  if (place) parts.push(place);
  const when = fixLabel(note.at, messageTs);
  if (when) parts.push(when);
  return parts.join(" · ");
}
