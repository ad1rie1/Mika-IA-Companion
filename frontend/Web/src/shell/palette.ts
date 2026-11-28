/**
 * La palette Ctrl K : « Rechercher partout ». Les routes de chaque écran et de ses onglets (« Aller à »),
 * puis ce que chaque écran sait chercher (les messages chargés du chat, les fils de travail). La part
 * pure : quelles entrées montrer pour ce qui est tapé.
 */
import { norm } from "./dom";
import type { IconName } from "./icons";

export interface PaletteEntry {
  group: string;
  title: string;
  sub?: string;
  side?: string;
  icon?: IconName;
  /**
   * Tout le texte où chercher, quand le titre n'en montre que le début (un message) : trouvé là seulement, l'entrée a
   * pour titre le passage trouvé (`excerpt`).
   */
  text?: string;
  /** Une route (`#mail/contacts`), ou une action. */
  route?: string;
  action?: () => void;
}

export const GO_TO = "Aller à";
const MAX_RESULTS = 40;
/** Un groupe n'en montre pas plus : des messages qui se ressemblent ne cachent pas le reste. */
const MAX_PER_GROUP = 10;
/** Sans rien de tapé : les écrans, puis quelques entrées des écrans. */
const IDLE_EXTRA = 6;
/** La longueur d'un passage trouvé, en caractères, et ce qu'il garde avant ce qu'on cherche. */
const EXCERPT_WIDTH = 70;
const EXCERPT_BEFORE = 24;

export function filterPalette(entries: readonly PaletteEntry[], query: string): PaletteEntry[] {
  const q = norm(query.trim().replace(/\s+/g, " "));
  if (!q) {
    const screens = entries.filter((e) => e.group === GO_TO && !e.title.includes("›"));
    const extra = entries.filter((e) => e.group !== GO_TO).slice(0, IDLE_EXTRA);
    return [...screens, ...extra].slice(0, MAX_RESULTS);
  }
  const out: PaletteEntry[] = [];
  const perGroup = new Map<string, number>();
  for (const e of entries) {
    if (out.length >= MAX_RESULTS) break;
    const shown = perGroup.get(e.group) ?? 0;
    if (shown >= MAX_PER_GROUP) continue;
    let found: PaletteEntry | null = null;
    if (norm(`${e.title} ${e.sub ?? ""} ${e.group}`).includes(q)) found = e;
    else if (e.text && norm(e.text).includes(q)) found = { ...e, title: excerpt(e.text, q) };
    if (!found) continue;
    perGroup.set(e.group, shown + 1);
    out.push(found);
  }
  return out;
}

/** Où `q` (déjà replié par `norm`) commence et finit dans `text`, en positions de `text` ; absent : `null`. */
function foldedRange(text: string, q: string): [number, number] | null {
  if (!q) return null;
  let folded = "";
  const starts: number[] = [];
  const ends: number[] = [];
  for (let i = 0; i < text.length; ) {
    const ch = String.fromCodePoint(text.codePointAt(i) ?? 0);
    const f = norm(ch);
    for (let k = 0; k < f.length; k++) {
      starts.push(i);
      ends.push(i + ch.length);
    }
    folded += f;
    i += ch.length;
  }
  const at = folded.indexOf(q);
  return at < 0 ? null : [starts[at], ends[at + q.length - 1]];
}

/**
 * Le passage de `text` où se trouve `q` (déjà replié par `norm` : sans accents ni casse), d'environ
 * `EXCERPT_WIDTH` caractères, coupé entre deux mots, « … » aux coupes. Pas trouvé : le début du texte.
 */
export function excerpt(text: string, q: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  const range = foldedRange(flat, q);
  if (!range) return flat.length > EXCERPT_WIDTH ? `${flat.slice(0, EXCERPT_WIDTH - 1).trimEnd()}…` : flat;
  const [from, to] = range;
  let start = Math.max(0, from - EXCERPT_BEFORE);
  if (start > 0) {
    const space = flat.indexOf(" ", start);
    if (space >= 0 && space < from) start = space + 1;
  }
  let end = Math.max(to, Math.min(flat.length, start + EXCERPT_WIDTH));
  if (end < flat.length) {
    const space = flat.lastIndexOf(" ", end);
    if (space >= to) end = space;
  }
  return `${start > 0 ? "…" : ""}${flat.slice(start, end).trim()}${end < flat.length ? "…" : ""}`;
}
