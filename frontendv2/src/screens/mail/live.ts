/**
 * Mail face au direct (ADR 0308, `protocole-moi.md` § 2 bis) : ce qu'un changement poussé fait relire à l'écran.
 * `mail` (des boîtes) : ses boîtes, la page de messages affichée si elle montre une de ces boîtes (ou toutes), le mail
 * ouvert s'il est dans l'une d'elles, ce qui est parti ; `mail.drafts` : ses brouillons ; `mail.work` (des mails) : où
 * elle en est d'une réponse au mail ouvert. Pur : l'écran (`mail.ts`) relit, ceci décide.
 */
import type { MailBox, MailFull } from "../../api/mail";
import { names, type Changed } from "../../live/live";
import type { View } from "./markup";

/** La page de messages affichée relit-elle sur un `mail` qui nomme ces boîtes ? Une vue de toutes tes boîtes
 *  (réceptions, suivis, réponse attendue, tout ce qui est parti) : oui ; une boîte : si elle est nommée. Ses
 *  brouillons ont leur sujet à eux (`mail.drafts`). */
export function pageShows(view: View, boxes: Changed): boolean {
  switch (view.kind) {
    case "drafts":
      return false;
    case "folder":
      return names(boxes, view.box);
    case "sent":
      return view.box ? names(boxes, view.box) : true;
    default:
      return true;
  }
}

/** La vue ne tient plus à ses boîtes (relues dans `…/mail/boxes`) : la boîte qu'elle montre n'est plus à toi (retirée,
 *  plus partagée), ou son dossier n'y est plus. On revient alors à « Toutes les réceptions », plutôt que de redire
 *  « Introuvable » sous un titre périmé. Une boîte dont les dossiers ne se disent pas (vides : pas encore lus, ou en
 *  panne) garde sa vue. */
export function viewGone(view: View, boxes: readonly Pick<MailBox, "key" | "folders">[]): boolean {
  if (!("box" in view) || !view.box) return false;
  const box = boxes.find((b) => b.key === view.box);
  if (!box) return true;
  return view.kind === "folder" && box.folders.length > 0 && !box.folders.some((f) => f.name === view.folder);
}

/** Le mail ouvert n'est plus d'une de tes boîtes : la liseuse se ferme (rien d'autre ne le dirait qu'un 404). */
export function openGone(open: Pick<MailFull, "box"> | null, boxes: readonly Pick<MailBox, "key">[]): boolean {
  return !!open && !boxes.some((b) => b.key === open.box);
}

/** Le mail ouvert relit-il sur un `mail` qui nomme ces boîtes ? S'il est dans l'une d'elles. */
export function openShows(open: Pick<MailFull, "box"> | null, boxes: Changed): boolean {
  return !!open && names(boxes, open.box);
}

/** Ce que le direct change de la liseuse, sans y toucher plus qu'il ne faut : ses marques (lu, suivi) et où elle en
 *  est d'une réponse (`work`, la demande) se repeignent en place ; ce que la liseuse montre d'autre (une étiquette,
 *  « Ce qu'elle en sait », son brouillon, le texte) la redessine — ta réponse commencée et le défilement gardés. */
export type ReaderChange = "same" | "parts" | "whole";

const PARTS = ["seen", "flagged", "work"] as const;

function rest(m: MailFull): string {
  const copy: Record<string, unknown> = { ...m };
  for (const k of PARTS) delete copy[k];
  copy.her = m.her ? { ...m.her, asked: false } : null;
  return JSON.stringify(copy);
}

function parts(m: MailFull): string {
  return JSON.stringify([m.seen, m.flagged, m.work ?? null, !!m.her?.asked]);
}

export function readerChange(before: MailFull, after: MailFull): ReaderChange {
  if (rest(before) !== rest(after)) return "whole";
  return parts(before) === parts(after) ? "same" : "parts";
}
