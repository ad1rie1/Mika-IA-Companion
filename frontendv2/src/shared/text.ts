/**
 * Les petites formes d'un texte ou d'un nombre, que plusieurs écrans partagent : ce qu'en compte le serveur, les
 * milliers, la taille d'un fichier, le texte d'une personne en HTML. Pur.
 */
import { h } from "../shell/dom";

/** Ce qu'en compte le serveur (`len` en Python) : des caractères, pas des unités UTF-16 (un emoji compte pour un). */
export function chars(text: string): number {
  let n = 0;
  for (const _ of String(text ?? "")) n++;
  return n;
}

/** « 20 000 » : les milliers séparés d'une espace fine, comme en français. */
export function thousands(n: number): string {
  return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

/** « 212 Ko », « 1,8 Mo ». */
export function sizeLabel(bytes: number | undefined): string {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} Ko`;
  return `${(bytes / (1024 * 1024)).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} Mo`;
}

/** Le texte d'une personne : échappé, ses retours à la ligne gardés. */
export function plainHtml(text: string): string {
  return h(text).replace(/\n/g, "<br>");
}
