/**
 * Projets, l'onglet Code : ce qui se calcule sans DOM (pur). Les adresses de la maquette (`code/fichiers/<branche>/…`,
 * `code/commits/<empreinte courte>`, `code/pulls/<n>/<volet>`, `code/branches/<nom>`, `code/issues/<n>`,
 * `code/ci/<empreinte courte>`), la coloration simple d'une ligne (des jetons de texte, jamais du HTML), la mise en
 * lignes d'un diff — unifié ou côte à côte —, et les requêtes des gestes d'une pull request : la fusionner en nommant
 * le commit de tête lu, la modifier, y répondre. Aucune règle n'est refaite ici (`merge.can`, `merge.why`).
 */
import type { Commit, Diff, DiffFile, DiffLine, Hunk, PullDetail, PullLine } from "../../api/projectCode";
import { changed, plural, type GestureRequest, type Values } from "./gestures";
import { sheetRoute } from "./routes";

// ── Les adresses ─────────────────────────────────────────────────────

export const CODE_TABS = [
  ["fichiers", "Fichiers"],
  ["commits", "Commits"],
  ["pulls", "Pull requests"],
  ["branches", "Branches"],
  ["issues", "Issues"],
  ["ci", "CI"],
] as const;

export type CodeTab = (typeof CODE_TABS)[number][0];

/** Le sous-onglet ouvert et ce qui le suit ; un sous-onglet inconnu : Fichiers. */
export function codePlace(rest: readonly string[]): { tab: CodeTab; rest: string[] } {
  const known = CODE_TABS.some(([t]) => t === rest[0]);
  return { tab: known ? (rest[0] as CodeTab) : "fichiers", rest: known ? rest.slice(1) : [] };
}

/**
 * La branche et le chemin d'une adresse de fichier (`<branche>/<chemin>`). Une branche peut porter des « / »
 * (`work/objective-3`) : c'est la plus longue des branches connues qui ouvre l'adresse ; aucune : son premier segment
 * (un commit), ou la branche par défaut si l'adresse est vide.
 */
export function splitRef(segments: readonly string[], refs: readonly string[], fallback: string): { ref: string; path: string } {
  const said = segments.filter((s) => s !== "");
  if (!said.length) return { ref: fallback, path: "" };
  let best = "";
  for (const ref of refs) {
    const parts = ref.split("/");
    if (parts.length <= said.length && parts.every((p, i) => p === said[i]) && ref.length > best.length) best = ref;
  }
  if (best) return { ref: best, path: said.slice(best.split("/").length).join("/") };
  return { ref: said[0], path: said.slice(1).join("/") };
}

/** L'adresse d'un fichier (ou d'un dossier) à une branche : chaque segment encodé, les barres gardées. */
export function fileRoute(id: number, ref: string, path = ""): string {
  return sheetRoute(id, "code", "fichiers", ...ref.split("/"), ...path.split("/"));
}

/** Un fichier Markdown du dépôt : il peut se lire rendu (le rendu sûr des pages de documentation), ou en source. */
export function isMarkdown(path: string): boolean {
  return /\.(md|markdown)$/i.test(path);
}

/**
 * Où mène un lien relatif écrit dans un fichier du dépôt (`base` : le chemin de ce fichier) : un chemin du même dépôt,
 * depuis sa racine — ou `null` s'il nomme autre chose (une adresse avec un schéma, `//hôte`, une ancre seule) ou s'il
 * sort de la racine. Le chemin rendu ne sert qu'à composer une adresse de l'écran ; le serveur juge s'il existe.
 */
export function repoLink(base: string, href: string): string | null {
  const raw = href.trim().split(/[?#]/)[0];
  if (!raw || /^[a-z][a-z0-9+.-]*:/i.test(raw) || raw.startsWith("//") || raw.includes("\\")) return null;
  const out = raw.startsWith("/") ? [] : base.split("/").slice(0, -1);
  for (const part of raw.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") {
      if (!out.length) return null;
      out.pop();
    } else out.push(part);
  }
  return out.length ? out.join("/") : null;
}

export function commitRoute(id: number, c: Pick<Commit, "short" | "sha">): string {
  return sheetRoute(id, "code", "commits", c.short || c.sha.slice(0, 7));
}

/** La clé d'une pull request dans son adresse : son numéro ; `o<objectif>` tant qu'elle n'en a pas (proposée). */
export function pullKey(p: { number: number; objective?: { id: number } | null }): string {
  return p.number ? String(p.number) : `o${p.objective?.id ?? 0}`;
}

export function parsePullKey(key: string | undefined): { number: number; objective: number } {
  const o = /^o(\d+)$/.exec(key ?? "");
  if (o) return { number: 0, objective: Number(o[1]) };
  return { number: /^\d+$/.test(key ?? "") ? Number(key) : 0, objective: 0 };
}

export function pullRoute(id: number, p: { number: number; objective?: { id: number } | null }, pane = ""): string {
  return sheetRoute(id, "code", "pulls", pullKey(p), pane);
}

export function branchRoute(id: number, name: string): string {
  return sheetRoute(id, "code", "branches", ...name.split("/"));
}

export function checksRoute(id: number, sha: string, pane = ""): string {
  return sheetRoute(id, "code", "ci", sha.slice(0, 7), pane);
}

/** Le commit d'une liste que nomme une empreinte, courte ou entière. */
export function bySha<T extends { sha: string }>(items: readonly T[], said: string | undefined): T | null {
  const s = (said ?? "").toLowerCase();
  return /^[0-9a-f]{4,40}$/.test(s) ? (items.find((x) => x.sha.startsWith(s)) ?? null) : null;
}

// ── Le code : une coloration simple ──────────────────────────────────

/** Un jeton d'une ligne : sa classe (`c` commentaire, `s` chaîne, `d` décorateur ou clé, `k` mot-clé, `n` nombre ; vide : rien) et son texte. */
export type Token = [cls: string, text: string];

const RE_PY = /(#.*$)|("""[\s\S]*?"""|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(@\w+)|\b(def|class|import|from|return|if|elif|else|for|in|with|as|try|except|raise|continue|not|and|or|is|lambda|None|True|False|pass|while|yield|async|await|break|finally|global|assert)\b|\b(\d+(?:\.\d+)?)\b/g;
const RE_CONF = /(#.*$)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(^\s*-?\s*[\w.-]+(?=\s*[:=]))|(^\[[\w.-]+\])|\b(\d+(?:\.\d+)?)\b/g;
const RE_C = /(\/\/.*$|\/\*.*?\*\/)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)|(@\w+)|\b(const|let|var|function|return|if|else|for|while|do|switch|case|break|continue|class|extends|implements|interface|type|enum|import|export|from|default|new|this|super|try|catch|finally|throw|async|await|static|public|private|protected|readonly|void|null|undefined|true|false|typeof|instanceof|fn|pub|use|mod|struct|impl|trait|match|package|func|defer|val|fun|namespace|using)\b|\b(\d+(?:\.\d+)?)\b/g;

function grammar(path: string): RegExp | null {
  const ext = /\.([A-Za-z0-9]+)$/.exec(path)?.[1]?.toLowerCase() ?? "";
  if (ext === "py") return RE_PY;
  if (["toml", "yml", "yaml", "ini", "cfg", "sh", "bash", "env"].includes(ext)) return RE_CONF;
  if (["js", "mjs", "cjs", "ts", "tsx", "jsx", "json", "c", "h", "cpp", "java", "go", "rs", "cs", "kt", "swift", "php", "css"].includes(ext)) return RE_C;
  return null;
}

const CLASSES = ["c", "s", "d", "k", "n"];

/**
 * Une ligne de code en jetons : leur texte, mis bout à bout, est la ligne même, caractère pour caractère. Rien n'y est
 * du HTML : le dessin les pose par insertion de texte.
 */
export function tokens(line: string, path: string): Token[] {
  const re = line.length > 2000 ? null : grammar(path); // une ligne démesurée (un fichier minifié) ne se colore pas
  if (!re) return line ? [["", line]] : [];
  re.lastIndex = 0;
  const out: Token[] = [];
  let at = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(line))) {
    if (!m[0].length) {
      re.lastIndex += 1;
      continue;
    }
    if (m.index > at) out.push(["", line.slice(at, m.index)]);
    out.push([CLASSES[m.slice(1).findIndex((g) => g !== undefined)] ?? "", m[0]]);
    at = m.index + m[0].length;
  }
  if (at < line.length) out.push(["", line.slice(at)]);
  return out;
}

const LANGUAGES: Record<string, string> = {
  py: "Python", toml: "TOML", yml: "YAML", yaml: "YAML", md: "Markdown", json: "JSON", js: "JavaScript", ts: "TypeScript", tsx: "TypeScript",
  sh: "Shell", css: "CSS", html: "HTML", rs: "Rust", go: "Go", java: "Java", kt: "Kotlin", c: "C", h: "C", cpp: "C++", cs: "C#", txt: "texte",
};

/** Le langage d'un fichier, d'après son extension ; « texte » sinon. */
export function languageOf(path: string): string {
  return LANGUAGES[/\.([A-Za-z0-9]+)$/.exec(path)?.[1]?.toLowerCase() ?? ""] ?? "texte";
}

/** Un poids en octets, en mots : « 812 o », « 1,3 Ko », « 2,4 Mo ». */
export function sizeWords(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} o`;
  const comma = (n: number): string => (Math.round(n * 10) / 10).toString().replace(".", ",");
  return bytes < 1_048_576 ? `${comma(bytes / 1024)} Ko` : `${comma(bytes / 1_048_576)} Mo`;
}

/** Les lignes d'un texte : la dernière, vide après un saut final, ne compte pas. */
export function linesOf(text: string): string[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  return lines;
}

// ── Un diff, mis en lignes ───────────────────────────────────────────

/** Une rangée du diff unifié : l'en-tête d'un passage, ou une ligne avec ses deux numéros (0 : elle n'y est pas). */
export type UnifiedRow = { kind: "hunk"; header: string } | { kind: "line"; line: DiffLine };

export function unifiedRows(hunks: readonly Hunk[]): UnifiedRow[] {
  return hunks.flatMap((hunk): UnifiedRow[] => [{ kind: "hunk", header: hunk.header }, ...hunk.lines.map((line): UnifiedRow => ({ kind: "line", line }))]);
}

/** Une rangée du diff côte à côte : l'avant à gauche, l'après à droite ; `null` : rien de ce côté. */
export type SideRow = { kind: "hunk"; header: string } | { kind: "pair"; left: DiffLine | null; right: DiffLine | null };

/**
 * Côte à côte : une ligne inchangée est des deux côtés ; une suite de lignes retirées fait face à celles qui la
 * remplacent, rangée par rangée, et ce qui dépasse d'un côté n'a rien en face.
 */
export function sideRows(hunks: readonly Hunk[]): SideRow[] {
  const out: SideRow[] = [];
  for (const hunk of hunks) {
    out.push({ kind: "hunk", header: hunk.header });
    const lines = hunk.lines;
    for (let i = 0; i < lines.length; ) {
      const line = lines[i];
      if (line.kind !== "-" && line.kind !== "+") {
        out.push({ kind: "pair", left: line, right: line });
        i += 1;
        continue;
      }
      const gone: DiffLine[] = [];
      const come: DiffLine[] = [];
      while (i < lines.length && lines[i].kind === "-") gone.push(lines[i++]);
      while (i < lines.length && lines[i].kind === "+") come.push(lines[i++]);
      for (let k = 0; k < Math.max(gone.length, come.length); k += 1) out.push({ kind: "pair", left: gone[k] ?? null, right: come[k] ?? null });
    }
  }
  return out;
}

/** Les fichiers d'un diff rangés par dossier, dans l'ordre où ils viennent : le sommaire du panneau. */
export function byFolder(files: readonly DiffFile[]): { folder: string; files: { file: DiffFile; index: number }[] }[] {
  const out: { folder: string; files: { file: DiffFile; index: number }[] }[] = [];
  files.forEach((file, index) => {
    const folder = file.path.includes("/") ? file.path.slice(0, file.path.lastIndexOf("/")) : "";
    let group = out.find((g) => g.folder === folder);
    if (!group) {
      group = { folder, files: [] };
      out.push(group);
    }
    group.files.push({ file, index });
  });
  return out;
}

// ── Une pull request : ses gestes ────────────────────────────────────

/** Où en est sa fusion, pour choisir le bandeau : faite, demandée, refusée par l'hôte, possible, retenue. */
export type MergeStage = "merged" | "asked" | "refused" | "ready" | "held";

export function mergeStage(p: Pick<PullLine, "state" | "merge">): MergeStage {
  if (p.state === "merged") return "merged";
  if (p.merge.asked) return "asked";
  if (p.merge.can) return "ready";
  return p.merge.refused ? "refused" : "held";
}

/** Ce que la confirmation dit de ce qui va être fusionné : lu sur la pull request qu'on vient de relire. */
export interface MergeFacts {
  number: number;
  title: string;
  branch: string;
  base: string;
  /** Le commit de tête, entier : celui que la demande nomme. */
  head: string;
  commits: number;
  files: number;
  insertions: number;
  deletions: number;
  /** Ses comptes sont lisibles (elle lit ses fichiers). */
  counted: boolean;
  /** Ce que le serveur dit de sa relecture et de ses vérifications. */
  review: string;
  checks: string;
  conflicts: boolean;
}

export function mergeFacts(d: PullDetail): MergeFacts {
  const p = d.pull;
  return {
    number: p.number, title: p.objective?.text || p.title, branch: p.branch, base: p.base, head: p.head, commits: d.commits.length,
    files: d.files.length, insertions: d.insertions, deletions: d.deletions, counted: d.files_readable,
    review: p.review?.label ?? "", checks: p.checks?.state_label ?? "", conflicts: p.conflicts,
  };
}

/** Les mots de la confirmation, ligne par ligne : ses commits, ses fichiers si elle les lit, et où elle en est. */
export function mergeLines(f: MergeFacts): { icon: "p2-commit" | "file" | "check"; text: string }[] {
  const state = [f.review ? `relecture : ${f.review}` : "", f.checks ? `vérifications : ${f.checks}` : "", f.conflicts ? "des conflits" : "aucun conflit"].filter(Boolean).join(" · ");
  return [
    { icon: "p2-commit" as const, text: plural(f.commits, "commit", "commits") },
    ...(f.counted ? [{ icon: "file" as const, text: `${plural(f.files, "fichier", "fichiers")}, +${f.insertions} −${f.deletions}` }] : []),
    { icon: "check" as const, text: state },
  ];
}

/**
 * La demande de fusion : elle nomme le commit de tête que l'écran a montré (`pull.head`, entier). Si la branche a
 * bougé depuis, le serveur refuse (409) et rien ne part.
 */
export function mergeRequest(p: { number: number; head: string }): GestureRequest {
  return { route: "code/pull/fusionner", body: { number: p.number, head: p.head } };
}

/** Modifier son titre et son texte chez l'hôte : seulement ce qui change (un champ vide ne change rien). */
export function pullEditRequest(number: number, values: Values, before: Values): GestureRequest {
  const after: Values = { title: String(values.title ?? "").trim(), body: String(values.body ?? "") };
  const body = Object.fromEntries(Object.entries(changed(before, after)).filter(([, v]) => v !== ""));
  return { route: "code/pull/modifier", body: { number, ...body } };
}

export function pullCommentRequest(number: number, text: string): GestureRequest {
  return { route: "code/pull/commenter", body: { number, text: text.trim() } };
}

/** Les comptes d'un diff, en mots courts pour un titre : « 3 fichiers ». */
export function filesWords(d: Pick<Diff, "files">): string {
  return plural(d.files.length, "fichier", "fichiers");
}
