/**
 * Les notes de carte d'un de ses messages (ADR 0196 ; `protocole-chat.md` § 4) : elle a cherché des lieux ou calculé
 * un trajet (`look`), montré une carte (`map`), créé ou changé un voyage (`trip`). Chacune a ce qu'elle ouvre (`ref` :
 * le `seq` d'un regard, l'identifiant d'un voyage). Le chat les montre en carte miniature, qui s'ouvre dans l'écran
 * Carte. La bulle 📍 (`location`) reste à `@web/ui/messageNotes` ; une sorte inconnue s'ignore ; une note vidée (un
 * regard oublié, un voyage supprimé : `text` vide, pas de `ref`) ne montre rien. Du JSON jamais vérifié : validé ici.
 */

export type MapNoteKind = "trip" | "map" | "look";

export interface MapNote {
  kind: MapNoteKind;
  /** Ce qu'elle a cherché, le titre de la carte ou du voyage. */
  text: string;
  /** L'instant du regard, ou du dernier changement du voyage (ms ; 0 : inconnu). */
  at: number;
  /** Le `seq` du regard ou de la carte, l'identifiant du voyage. */
  ref: string;
}

const KINDS: ReadonlySet<string> = new Set<MapNoteKind>(["trip", "map", "look"]);
/** Des chiffres, comme les identifiants du serveur (le `seq` d'un événement). */
const REF = /^\d{1,18}$/;
/** Une réponse ne porte pas des dizaines de cartes. */
export const MAX_MAP_NOTES = 6;
const MAX_TEXT = 300;

/** Les notes de carte d'un message, validées : les trois sortes, avec un texte et ce qu'elles ouvrent. */
export function mapNotes(raw: unknown): MapNote[] {
  if (!Array.isArray(raw)) return [];
  const out: MapNote[] = [];
  for (const item of raw as Array<Record<string, unknown> | null>) {
    if (!item || typeof item !== "object" || typeof item.kind !== "string" || !KINDS.has(item.kind)) continue;
    const text = typeof item.text === "string" ? item.text.slice(0, MAX_TEXT).replace(/\s+/g, " ").trim() : "";
    const ref = typeof item.ref === "string" ? item.ref.trim() : typeof item.ref === "number" ? String(item.ref) : "";
    if (!text || !REF.test(ref)) continue; // oubliée, supprimée : rien à montrer
    const at = typeof item.at === "number" && Number.isFinite(item.at) && item.at > 0 ? item.at : 0;
    if (out.some((n) => n.kind === item.kind && n.ref === ref)) continue;
    out.push({ kind: item.kind as MapNoteKind, text, at, ref });
    if (out.length >= MAX_MAP_NOTES) break;
  }
  return out;
}

export function sameMapNotes(a: readonly MapNote[] | undefined, b: readonly MapNote[] | undefined): boolean {
  const x = a ?? [];
  const y = b ?? [];
  return x.length === y.length && x.every((n, i) => n.kind === y[i].kind && n.ref === y[i].ref && n.text === y[i].text && n.at === y[i].at);
}

/** La clé d'une note : ce que la miniature garde d'un dessin à l'autre. */
export function noteKey(note: Pick<MapNote, "kind" | "ref">): string {
  return `${note.kind}:${note.ref}`;
}

/** Ce qu'une note ouvre dans l'écran Carte : le voyage, ou le regard (ses lieux dans Explorer). */
export function noteRoute(note: Pick<MapNote, "kind" | "ref">): string {
  if (note.kind === "trip") return `#carte/voyages/${encodeURIComponent(note.ref)}`;
  return `#carte/explorer/${regardItem(note.ref)}`;
}

/** L'objet d'une route de l'écran Carte qui montre un regard : `regard-<seq>`. */
export function regardItem(seq: string): string {
  return `regard-${seq}`;
}

/** Le `seq` d'un regard dans l'objet d'une route (`regard-812`), sinon `null`. */
export function regardOf(item: string | null | undefined): string | null {
  const m = /^regard-(\d{1,18})$/.exec(item ?? "");
  return m ? m[1] : null;
}
