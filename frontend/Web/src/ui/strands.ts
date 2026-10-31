/**
 * Les fils de travail du mode pro (ADR 0164), sans DOM : leur liste telle que
 * le serveur l'envoie (trame `strands`), leur nom à l'écran, un identifiant
 * neuf, et les commandes qu'on tape dans le champ (`/clear`…).
 *
 * En mode pro, le chat devient un client à plusieurs fils : chacun son
 * contexte, le fil avec Mika caché. Un fil s'ouvre en choisissant un
 * identifiant neuf et en y écrivant ; rien ne s'efface, un fil se range en
 * l'archivant. Le serveur ne connaît un fil qu'à son premier message (ou à
 * son premier réglage) : jusque-là, il n'existe que dans cet onglet.
 */

/** Un identifiant de fil : 1 à 40 lettres, chiffres, `_` ou `-` (`protocol.py::strand_id`). */
const STRAND_ID = /^[A-Za-z0-9_-]{1,40}$/;
/** Le titre d'un fil, sa description : au plus (`transcript/actions.py`). */
export const STRAND_TITLE_MAX = 120;
export const STRAND_DESCRIPTION_MAX = 2000;
/** Le nom d'un fil sans titre, tiré de son premier message : au plus. */
const LABEL_MAX = 48;

export interface StrandInfo {
  id: string;
  title: string;
  description: string;
  archived: boolean;
  /** Ses messages au serveur ; 0 pour un fil seulement réglé, ou encore à écrire. */
  count: number;
  /** Millisecondes Unix. */
  lastAt: number;
  /** Le début de son premier message : de quoi le nommer sans titre. */
  opener: string;
}

/** Un identifiant de fil valide, ou `undefined`. */
export function strandOf(raw: unknown): string | undefined {
  return typeof raw === "string" && STRAND_ID.test(raw) ? raw : undefined;
}

/** Un identifiant neuf : l'instant et un peu de hasard, en base 36. */
export function newStrandId(now: number = Date.now(), random: () => number = Math.random): string {
  const noise = Math.floor(random() * 36 ** 6).toString(36).padStart(6, "0");
  return `s${now.toString(36)}${noise}`;
}

function str(value: unknown, max: number): string {
  return typeof value === "string" ? value.slice(0, max) : "";
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
}

/** La trame `strands` validée : une entrée sans identifiant valide est ignorée. */
export function parseStrands(raw: unknown): StrandInfo[] {
  const items = (raw as { items?: unknown } | null)?.items;
  if (!Array.isArray(items)) return [];
  const out: StrandInfo[] = [];
  for (const item of items) {
    if (!item || typeof item !== "object") continue;
    const r = item as Record<string, unknown>;
    const id = strandOf(r.id);
    if (!id) continue;
    out.push({
      id,
      title: str(r.title, STRAND_TITLE_MAX),
      description: str(r.description, STRAND_DESCRIPTION_MAX),
      archived: r.archived === true,
      count: num(r.count),
      lastAt: num(r.last_at),
      opener: str(r.opener, 200),
    });
  }
  return out;
}

/** Le nom d'un fil à l'écran : son titre, sinon le début de son premier message, sinon « Nouveau fil ». */
export function strandLabel(strand: Pick<StrandInfo, "title" | "opener"> | undefined): string {
  const title = strand?.title.trim();
  if (title) return title;
  const opener = strand?.opener.replace(/\s+/g, " ").trim() ?? "";
  if (!opener) return "Nouveau fil";
  return opener.length <= LABEL_MAX ? opener : `${opener.slice(0, LABEL_MAX - 1)}…`;
}

/**
 * La liste du serveur, plus les fils de cet onglet qu'il ne connaît pas encore
 * (ouverts, pas encore écrits) — ceux-là en tête, dans l'ordre où on les a
 * ouverts. Un fil local que le serveur connaît désormais prend sa ligne.
 */
export function withLocal(server: StrandInfo[], local: readonly StrandInfo[]): StrandInfo[] {
  const known = new Set(server.map((s) => s.id));
  return [...local.filter((s) => !known.has(s.id)), ...server];
}

/** Un fil que cet onglet vient d'ouvrir : rien encore au serveur. */
export function localStrand(id: string, now: number = Date.now()): StrandInfo {
  return { id, title: "", description: "", archived: false, count: 0, lastAt: now, opener: "" };
}

// ── Les commandes du champ ─────────────────────────────────────────────

export type StrandCommand =
  | { name: "clear" }
  | { name: "rename"; arg: string }
  | { name: "describe"; arg: string }
  | { name: "archive" }
  | { name: "unarchive" }
  | { name: "help" }
  | { name: "unknown"; typed: string };

/** Ce que chaque commande fait, pour l'aide et les suggestions du champ. */
export const COMMANDS: readonly { usage: string; words: readonly string[]; help: string }[] = [
  { usage: "/clear", words: ["clear", "nouveau"], help: "ouvrir un fil neuf (l'actuel reste dans la liste)" },
  { usage: "/renommer <titre>", words: ["renommer"], help: "donner un titre à ce fil" },
  { usage: "/description <texte>", words: ["description"], help: "ce qu'elle relit en tête de ce fil" },
  { usage: "/archiver", words: ["archiver"], help: "ranger ce fil" },
  { usage: "/desarchiver", words: ["desarchiver", "désarchiver"], help: "le sortir des archives" },
  { usage: "/aide", words: ["aide"], help: "ces commandes" },
];

/**
 * Une commande tapée dans le champ (`/renommer Devis IN`), ou `null` pour un
 * message ordinaire. Un `//` en tête échappe : le message part avec un seul
 * `/`, sans être lu comme une commande.
 */
export function parseCommand(text: string): StrandCommand | null {
  const typed = text.trim();
  if (!typed.startsWith("/") || typed.startsWith("//")) return null;
  const body = typed.slice(1);
  const head = body.split(/\s+/, 1)[0];
  const arg = body.slice(head.length).trim();
  switch (head.toLowerCase()) {
    case "clear":
    case "nouveau":
      return { name: "clear" };
    case "renommer":
      return { name: "rename", arg };
    case "description":
      return { name: "describe", arg };
    case "archiver":
      return { name: "archive" };
    case "desarchiver":
    case "désarchiver":
      return { name: "unarchive" };
    case "aide":
    case "help":
      return { name: "help" };
    default:
      return { name: "unknown", typed: `/${head}` };
  }
}

/** Le message à envoyer pour un texte qui commence par `//` : un seul `/`. */
export function unescapeSlash(text: string): string {
  const typed = text.trimStart();
  return typed.startsWith("//") ? typed.slice(1) : text;
}

/** Les commandes que le début tapé (`/re`) peut encore devenir — pour les suggestions du champ. */
export function suggestCommands(text: string): typeof COMMANDS[number][] {
  if (!text.startsWith("/") || text.startsWith("//") || /\s/.test(text)) return [];
  const start = text.slice(1).toLowerCase();
  return COMMANDS.filter((c) => c.words.some((w) => w.startsWith(start)));
}
