/**
 * Projets, ce qui se pose après le dessin : le contenu d'un fichier et les lignes d'un diff. **Par insertion de
 * texte, jamais de HTML** — chaque ligne, chaque jeton est un nœud de texte (`textContent`) : rien de ce qu'un fichier
 * du dépôt contient ne peut devenir une balise. La vue ne pose qu'un emplacement vide (`slot`) ; `paintAll` le
 * remplit une fois le dessin fait. Une table construite est gardée et reposée telle quelle au dessin suivant.
 *
 * Ce qui est posé après coup ne peut pas retrouver seul où il avait défilé (le cadre était vide quand l'écran a remis
 * ses défilements) : `keepLateScroll` s'en charge, pour le code comme pour l'éditeur d'une page.
 */
import type { DiffFile, DiffLine } from "../../api/projectCode";
import { h } from "../../shell/dom";
import { linesOf, sideRows, tokens, unifiedRows } from "./codeparts";

export type Paint = { kind: "source"; text: string; path: string } | { kind: "diff"; file: DiffFile; side: boolean };

const waiting = new Map<string, Paint>();
const built = new Map<string, HTMLElement>();
/** Les tables gardées d'un dessin à l'autre, au plus. */
const KEPT = 30;

/**
 * Un emplacement pour du code : `key` dit ce qu'il montre (le commit lu, le chemin, la forme) — la même clé, la même
 * table. Le HTML rendu ne porte aucun caractère du fichier.
 */
export function slot(key: string, paint: Paint, cls = "p2-codewrap"): string {
  waiting.set(key, paint);
  return `<div class="${cls}" data-p2-code="${h(key)}"></div>`;
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls = "", text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** Une ligne de code dans sa cellule : ses jetons, en nœuds de texte. */
function code(cell: HTMLElement, line: string, path: string): void {
  const found = tokens(line, path);
  if (!found.length) {
    cell.textContent = " ";
    return;
  }
  for (const [cls, text] of found) cell.append(cls ? el("span", `t-${cls}`, text) : document.createTextNode(text));
}

function sourceTable(text: string, path: string): HTMLElement {
  const table = el("table", "p2-src");
  const body = el("tbody");
  linesOf(text).forEach((line, i) => {
    const row = el("tr");
    const cell = el("td", "cd");
    code(cell, line, path);
    row.append(el("td", "ln", String(i + 1)), cell);
    body.append(row);
  });
  table.append(body);
  return table;
}

const number = (n: number): string => (n ? String(n) : "");

function unifiedTable(file: DiffFile): HTMLElement {
  const table = el("table", "p2-diff");
  const body = el("tbody");
  for (const r of unifiedRows(file.hunks)) {
    const row = el("tr");
    if (r.kind === "hunk") {
      row.className = "hunk";
      const cell = el("td", "cd", r.header);
      cell.colSpan = 2;
      row.append(el("td", "ln"), el("td", "ln"), cell);
    } else {
      const { line } = r;
      row.className = line.kind === "+" ? "add" : line.kind === "-" ? "del" : "";
      const cell = el("td", "cd");
      code(cell, line.text, file.path);
      row.append(el("td", "ln", number(line.old)), el("td", "ln", number(line.new)), el("td", "sg", line.kind === "+" ? "+" : line.kind === "-" ? "−" : ""), cell);
    }
    body.append(row);
  }
  table.append(body);
  return table;
}

function sideTable(file: DiffFile): HTMLElement {
  const table = el("table", "p2-diff cote");
  const cols = el("colgroup");
  cols.append(el("col", "n"), el("col"), el("col", "n"), el("col"));
  const body = el("tbody");
  const half = (row: HTMLElement, line: DiffLine | null, n: number, cls: string): void => {
    if (!line) {
      row.append(el("td", "ln rien"), el("td", "cd rien"));
      return;
    }
    const cell = el("td", `cd ${cls}`.trim());
    code(cell, line.text, file.path);
    row.append(el("td", "ln", number(n)), cell);
  };
  for (const r of sideRows(file.hunks)) {
    const row = el("tr");
    if (r.kind === "hunk") {
      row.className = "hunk";
      const cell = el("td", "cd", r.header);
      cell.colSpan = 4;
      row.append(cell);
    } else {
      half(row, r.left, r.left?.old ?? 0, r.left?.kind === "-" ? "del" : "");
      half(row, r.right, r.right?.new ?? 0, r.right?.kind === "+" ? "add" : "");
    }
    body.append(row);
  }
  table.append(cols, body);
  return table;
}

/** Remplit les emplacements du dessin qui vient d'être fait. */
export function paintAll(root: ParentNode): void {
  for (const place of Array.from(root.querySelectorAll<HTMLElement>("[data-p2-code]"))) {
    const key = place.dataset.p2Code ?? "";
    const paint = waiting.get(key);
    if (!paint) continue;
    const node = built.get(key) ?? (paint.kind === "source" ? sourceTable(paint.text, paint.path) : paint.side ? sideTable(paint.file) : unifiedTable(paint.file));
    built.delete(key);
    built.set(key, node); // la dernière posée est la dernière à partir
    place.replaceChildren(node);
  }
  for (const key of Array.from(built.keys()).slice(0, Math.max(0, built.size - KEPT))) built.delete(key);
  waiting.clear();
}

// ── Où un cadre rempli après coup avait défilé ───────────────────────

const scrolls = new Map<string, number>();
let lastHash = "";
let hooked = false;

/**
 * Pour chaque élément `selector` posé après le dessin : son cadre (`[data-scroll]`) retrouve où il avait défilé, tant
 * que l'adresse n'a pas changé.
 */
export function keepLateScroll(root: ParentNode, selector: string): void {
  if (!hooked) {
    hooked = true;
    document.addEventListener("scroll", (e) => {
      const frame = e.target as HTMLElement | null;
      if (frame?.dataset?.p2Late) scrolls.set(frame.dataset.scroll ?? "", frame.scrollTop);
    }, true);
  }
  if (location.hash !== lastHash) {
    scrolls.clear();
    lastHash = location.hash;
  }
  for (const node of Array.from(root.querySelectorAll<HTMLElement>(selector))) {
    const frame = node.closest<HTMLElement>("[data-scroll]");
    if (!frame) continue;
    frame.dataset.p2Late = "1";
    const y = scrolls.get(frame.dataset.scroll ?? "");
    if (y) frame.scrollTop = y;
  }
}
