/**
 * Le fil avec elle au-delà de ce que tient le cache (ADR 0215) : ce qu'on demande au serveur, et comment ce qui
 * revient se recoud à ce qu'on a. Des fonctions pures ; l'écran (`chat.ts`) ne fait que les appeler.
 *
 * En mémoire, le fil chargé n'a pas de borne : chaque morceau vient d'un clic. Seul le cache du navigateur se limite
 * aux derniers messages. Le fil reste donc d'un seul tenant : une trame qui ne touche rien de ce qu'on a (à
 * l'ouverture, ou plus de messages manqués que n'en tient la trame) efface du fil avec elle ce qui est plus ancien
 * qu'elle (`mergeSeam`), sinon la remontée sauterait en silence ce qui manque au milieu.
 */
import type { HistoryEntry } from "@web/types";
import { mergeHistory, sortMessages, threadOf, type StoredMessage } from "@web/ui/chatSync";

/** Pour `mergeHistory` : aucune limite par fil, en mémoire. */
export const UNBOUNDED = Number.POSITIVE_INFINITY;

/** Le message le plus ancien du fil avec elle, en mémoire, connu du serveur : d'où repartir. */
export function oldestLoaded(history: readonly StoredMessage[]): number | undefined {
  let oldest: number | undefined;
  for (const m of history) {
    if (threadOf(m) !== "" || typeof m.id !== "number") continue;
    if (oldest === undefined || m.id < oldest) oldest = m.id;
  }
  return oldest;
}

/**
 * Cette trame touche-t-elle quelque chose qu'on a déjà ? Sinon, ce qui est plus vieux qu'elle ne se recoud pas. Une
 * ligne d'un fil de travail compte : le curseur est commun à tous les fils, on avait donc tout vu jusqu'à elle.
 */
export function touchesLoaded(history: readonly StoredMessage[], entries: readonly HistoryEntry[]): boolean {
  const known = new Set(history.map((m) => m.id).filter((id): id is number => typeof id === "number"));
  return entries.some((e) => typeof e?.id === "number" && known.has(e.id));
}

/**
 * Une trame qui peut ne rien toucher de chargé, fusionnée. Si elle touche, il ne manque rien entre les deux : tout
 * reste. Sinon, le fil avec elle repart d'elle, et la remontée reprendra juste au-dessus. La coupe se fait par
 * identifiant, jamais par nombre de lignes : la trame porte tout le compte, fils de travail compris, et peut ne tenir
 * que trois lignes de ce fil. Une bulle sans identifiant reste ; `limit` borne chaque fil, comme le cache.
 */
export function mergeSeam(history: StoredMessage[], entries: HistoryEntry[], limit: number): ReturnType<typeof mergeHistory> {
  if (touchesLoaded(history, entries)) return mergeHistory(history, entries, UNBOUNDED);
  const ids = entries.map((e) => e?.id).filter((id): id is number => typeof id === "number");
  if (!ids.length) return mergeHistory(history, entries, limit);
  const start = Math.min(...ids);
  const kept = history.filter((m) => threadOf(m) !== "" || typeof m.id !== "number" || m.id >= start);
  return mergeHistory(kept, entries, limit);
}

/**
 * Une page de messages anciens, fusionnée. Une bulle encore sans identifiant (en attente, refusée) reste à l'écart :
 * au même texte qu'un vieux message, elle s'y confondrait (`mergeHistory` adopte par le texte).
 */
export function mergeOlder(history: readonly StoredMessage[], entries: readonly HistoryEntry[]): StoredMessage[] {
  const unsent = history.filter((m) => m.id === undefined);
  const sent = history.filter((m) => m.id !== undefined);
  return sortMessages([...mergeHistory(sent, [...entries], UNBOUNDED).history, ...unsent]);
}
