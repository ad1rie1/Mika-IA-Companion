/**
 * Ses réponses jugées depuis le chat (ADR 0113) : sous chacune, 👍 ou 👎, et,
 * si on veut, ce qu'elle aurait dû dire. Pour l'opératrice seulement ; le
 * serveur garde l'avis à côté du message et le montre dans la console. Ici, la
 * logique pure : quel avis donne un clic, la trame, ce qu'un refus veut dire.
 */
import type { StoredMessage } from "./chatSync";
import type { Verdict, VerdictFrame, VerdictResultMessage } from "../types";

/** Un clic sur 👍 ou 👎 : l'avis choisi, ou retiré si c'était déjà le sien. */
export function nextVerdict(current: Verdict | undefined, clicked: Verdict): Verdict | "" {
  return current === clicked ? "" : clicked;
}

export const COMMENT_MAX = 2000;

export function verdictFrame(messageId: number, verdict: Verdict | "", comment: string): VerdictFrame {
  return {
    type: "verdict",
    message_id: messageId,
    verdict,
    comment: verdict ? comment.trim().slice(0, COMMENT_MAX) : "",
  };
}

/** Pose l'avis sur la réponse `messageId` ; rend `false` si elle n'est pas dans le fil. */
export function applyVerdict(
  history: StoredMessage[],
  messageId: number,
  verdict: Verdict | "",
  note: string
): boolean {
  const msg = history.find((m) => m.id === messageId && m.sender === "vtuber");
  if (!msg) return false;
  msg.verdict = verdict || undefined;
  msg.verdictNote = verdict && note.trim() ? note.trim() : undefined;
  return true;
}

/** Ce qu'un refus du serveur veut dire, en français (`null` : rien à dire). */
export function verdictError(status: VerdictResultMessage["status"]): string | null {
  switch (status) {
    case "ok":
      return null;
    case "forbidden":
      return "Seule une opératrice peut juger ses réponses.";
    case "invalid":
      return "Ce message ne peut pas être jugé (il a peut-être été oublié).";
    default:
      return "L'avis n'a pas été enregistré : réessaie.";
  }
}
