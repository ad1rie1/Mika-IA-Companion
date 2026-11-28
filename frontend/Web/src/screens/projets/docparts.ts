/**
 * Projets, l'onglet Documentation : ce qui se calcule sans DOM (pur). Les adresses de la maquette
 * (`documentation/pages/<chemin>`, `…/modifier/<chemin>`, `…/historique/<chemin>`, `…/images/<nom>`,
 * `…/decisions/<n>/<volet>`), l'arborescence des pages, le chemin d'une page nouvelle, le Markdown que l'éditeur rend
 * remis en forme, et **le brouillon d'une page** : ce qui est tapé, la version lue, l'enregistrement et son conflit —
 * un refus du serveur ne fait jamais perdre ce qui a été écrit. Aucune règle n'est refaite ici.
 */
import type { Decision, DecisionFull, DocPage } from "../../api/projectDocs";
import { changed, type GestureRequest, type Values } from "./gestures";
import { sheetRoute } from "./routes";

// ── Les adresses ─────────────────────────────────────────────────────

export type DocTab = "pages" | "images" | "decisions";
export type PageMode = "pages" | "modifier" | "historique";

export interface DocPlace {
  tab: DocTab;
  /** Pour une page : la lire, la modifier, son historique. */
  mode: PageMode;
  /** Le chemin de la page, ou le nom de l'image. */
  path: string;
  /** Ce qui suit le sous-onglet (une décision : son numéro, son volet). */
  rest: string[];
}

export function docPlace(rest: readonly string[]): DocPlace {
  const [first, ...more] = rest;
  if (first === "decisions") return { tab: "decisions", mode: "pages", path: "", rest: more };
  if (first === "images") return { tab: "images", mode: "pages", path: more.join("/"), rest: more };
  const mode: PageMode = first === "modifier" || first === "historique" ? first : "pages";
  return { tab: "pages", mode, path: first === "pages" || mode !== "pages" ? more.join("/") : "", rest: more };
}

/** L'adresse d'une page : chaque segment de son chemin encodé, les barres gardées. */
export function pageRoute(id: number, mode: PageMode, path = ""): string {
  return sheetRoute(id, "documentation", mode, ...path.split("/"));
}

export function imageRoute(id: number, name = ""): string {
  return sheetRoute(id, "documentation", "images", name);
}

export function decisionRoute(id: number, number: number | string = "", pane = ""): string {
  return sheetRoute(id, "documentation", "decisions", number, pane);
}

// ── L'arborescence ───────────────────────────────────────────────────

export interface TreeNode {
  name: string;
  /** Le chemin du dossier, ou de la page. */
  path: string;
  page: DocPage | null;
  children: TreeNode[];
}

/** Les pages à plat, en arbre : les dossiers d'abord, `accueil.md` en tête, puis l'ordre alphabétique. */
export function pageTree(pages: readonly DocPage[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", page: null, children: [] };
  for (const page of pages) {
    const parts = page.path.split("/");
    let node = root;
    parts.forEach((name, i) => {
      const path = parts.slice(0, i + 1).join("/");
      const leaf = i === parts.length - 1;
      let next = node.children.find((c) => c.name === name && !c.page === !leaf);
      if (!next) {
        next = { name, path, page: leaf ? page : null, children: [] };
        node.children.push(next);
      }
      node = next;
    });
  }
  const sort = (n: TreeNode): void => {
    n.children.sort((a, b) => Number(!!a.page) - Number(!!b.page) || (a.name === "accueil.md" ? -1 : b.name === "accueil.md" ? 1 : a.name.localeCompare(b.name)));
    n.children.forEach(sort);
  };
  sort(root);
  return root.children;
}

/** La page qui s'ouvre quand l'adresse n'en nomme pas : `accueil.md`, sinon la première. */
export function homePage(pages: readonly DocPage[]): DocPage | null {
  return pages.find((p) => p.path === "accueil.md") ?? pages[0] ?? null;
}

// ── Le chemin d'une page ─────────────────────────────────────────────

/** Un nom replié comme le serveur l'attend (il ne corrige rien) : minuscules, chiffres, tirets ; sans accents. */
export function slug(text: string): string {
  return String(text ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/\.md$/, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** Un dossier tapé (`Guide/Avancé`) replié segment par segment ; vide : la racine. */
export function folderPath(text: string): string {
  return String(text ?? "").split("/").map(slug).filter(Boolean).join("/");
}

/** Le chemin d'une page dans un dossier : `guide/depannage.md` ; vide si le nom ne donne rien. */
export function pagePath(folder: string, name: string): string {
  const leaf = slug(name);
  return leaf ? `${folder ? `${folder}/` : ""}${leaf}.md` : "";
}

export function folderOf(path: string): string {
  return path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
}

export function nameOf(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

/** Le texte d'une image dans une page, depuis son nom de fichier : `schema-reseau.png` → « schema reseau ». */
export function imageAlt(name: string): string {
  return name.replace(/\.[A-Za-z0-9]+$/, "").replace(/-/g, " ");
}

/** Ce qu'une page écrit pour citer une image de l'espace. */
export function imageMarkdown(name: string): string {
  return `![${imageAlt(name)}](images/${name})`;
}

/**
 * Ce que l'éditeur rend redevient le Markdown de la maison : des tirets pour les puces, un texte pour chaque image,
 * une seule fin de ligne au bout. Les blocs de code ne sont pas touchés.
 */
export function tidyMarkdown(md: string): string {
  let fenced = false;
  const lines = String(md ?? "").replace(/\r\n?/g, "\n").split("\n").map((line) => {
    if (/^```/.test(line)) fenced = !fenced;
    if (fenced) return line;
    return line
      .replace(/^(\s*)\* /, "$1- ")
      .replace(/!\[[\d.]*\]\(([^)\s]+)((?:\s+"[^"]*")?)\)/g, (_m, src: string, caption: string) => `![${caption ? caption.trim().slice(1, -1) : imageAlt(nameOf(src))}](${src})`);
  });
  return `${lines.join("\n").replace(/\n+$/, "")}\n`;
}

// ── Le brouillon d'une page ──────────────────────────────────────────

/** Ce qu'on écrit d'une page, tant que ce n'est pas enregistré. */
export interface Draft {
  path: string;
  /** La version lue : celle que l'enregistrement nomme (`base`). */
  base: number;
  /** Le texte lu à cette version, et ce qui est tapé depuis. */
  read: string;
  text: string;
  /** Un refus du serveur à l'enregistrement, avec ses mots ; `conflict` : la page a changé depuis la lecture (409). */
  refusal: string;
  conflict: boolean;
}

export function startDraft(page: { path: string; version: number; text: string }): Draft {
  return { path: page.path, base: page.version, read: page.text, text: page.text, refusal: "", conflict: false };
}

/** La page a-t-elle été modifiée sans être enregistrée ? */
export function isDirty(d: Draft | null | undefined): boolean {
  return !!d && d.text !== d.read;
}

/** Ce qui vient d'être tapé ; le refus d'avant reste dit tant qu'on n'a pas relu ni réenregistré. */
export function typed(d: Draft, text: string): Draft {
  return { ...d, text };
}

/** Ce que l'enregistrement envoie : le Markdown, le mot sur ce qui a changé, et la version lue. */
export function saveBody(d: Draft, word: string): { path: string; text: string; word: string; base: number } {
  return { path: d.path, text: d.text, word: word.trim().slice(0, 200), base: d.base };
}

/** Enregistré : la version rendue devient la version lue, plus rien n'est en attente. */
export function saved(d: Draft, version: number): Draft {
  return { ...d, base: version, read: d.text, refusal: "", conflict: false };
}

/**
 * Refusé : les mots du serveur se disent, et **ce qui est écrit reste**. C'est un conflit seulement si la page a
 * bougé depuis la lecture (`moved`, voir `movedOn`) : rien n'est écrasé, il faut relire avant de reprendre. Le
 * serveur répond 409 à d'autres refus — le même texte, une page disparue, une borne atteinte — qui n'en sont pas un.
 */
export function refused(d: Draft, words: string, moved = false): Draft {
  return { ...d, refusal: words, conflict: moved };
}

/**
 * La page a-t-elle bougé depuis la lecture ? Elle existe (`current`, relue après un 409) et n'en est plus à la
 * version que le brouillon nomme — ce qui vaut aussi pour une page nouvelle (`base` 0) qui existe déjà.
 */
export function movedOn(d: Draft, current: { version: number } | null): boolean {
  return current !== null && current.version !== d.base;
}

/**
 * Reprendre après un conflit, une fois la version actuelle relue : elle devient la version de départ, le texte tapé
 * reste entier. L'enregistrement qui suit en fait une version de plus, sans rien écraser à l'aveugle.
 */
export function rebased(d: Draft, current: { version: number; text: string }): Draft {
  return { ...d, base: current.version, read: current.text, refusal: "", conflict: false };
}

/** La clé du brouillon d'une page. */
export function draftKey(project: number, path: string): string {
  return `${project}:${path}`;
}

// ── Les gestes sur une page, une image ───────────────────────────────

export function moveRequest(path: string, to: string): GestureRequest {
  return { route: "documentation/page/deplacer", body: { path, to } };
}

export function removeRequest(path: string): GestureRequest {
  return { route: "documentation/page/supprimer", body: { path } };
}

/** Revenir à une version gardée : une version de plus, partie de la version courante lue. */
export function restoreRequest(path: string, version: number, base: number): GestureRequest {
  return { route: "documentation/page/revenir", body: { path, version, base } };
}

export function imageRemoveRequest(name: string): GestureRequest {
  return { route: "documentation/image/retirer", body: { name } };
}

// ── Les décisions techniques ─────────────────────────────────────────

const DECISION_TEXTS = ["title", "choice", "context", "reason", "options"] as const;

/**
 * Consigner une décision, ou la modifier (`number` nommé : seulement ce qui change — un texte facultatif vidé est
 * retiré). `replaces` : la décision en vigueur qu'elle remplace, à la création seulement.
 */
export function decisionRequest(values: Values, before: DecisionFull | null): GestureRequest {
  const after: Values = Object.fromEntries(DECISION_TEXTS.map((k) => [k, String(values[k] ?? "").trim()]));
  if (before) {
    const was: Values = Object.fromEntries(DECISION_TEXTS.map((k) => [k, before[k] ?? ""]));
    return { route: "decision/modifier", body: { number: before.number, ...changed(was, after) } };
  }
  const replaces = Number(values.replaces) || 0;
  return { route: "decision/ajouter", body: { ...Object.fromEntries(Object.entries(after).filter(([, v]) => v !== "")), ...(replaces ? { replaces } : {}) } };
}

export function decisionStatusRequest(number: number, status: "withdrawn" | "active"): GestureRequest {
  return { route: "decision/statut", body: { number, status } };
}

/** Les décisions dans l'ordre de la liste : celles en vigueur, puis les retirées, puis les remplacées. */
export function decisionOrder<T extends Pick<Decision, "status">>(items: readonly T[]): T[] {
  const rank = (d: T): number => (d.status === "active" ? 0 : d.status === "withdrawn" ? 1 : 2);
  return [...items].sort((a, b) => rank(a) - rank(b));
}

/** Les options écartées, une par ligne non vide (le serveur les garde en un seul texte). */
export function optionLines(options: string): { title: string; why: string }[] {
  return String(options ?? "").split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
    const i = l.indexOf(" : ");
    return i > 0 ? { title: l.slice(0, i).trim(), why: l.slice(i + 3).trim() } : { title: l, why: "" };
  });
}
