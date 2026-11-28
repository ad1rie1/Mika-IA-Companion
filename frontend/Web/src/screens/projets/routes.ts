/**
 * Projets, les adresses (pur, sans DOM) : celles de la maquette validée, reprises telles quelles.
 *
 *   #projets/a-faire[/<projet>/<attente>]
 *   #projets/projets
 *   #projets/projets/<id>[/<onglet>[/…]]      onglet : objectifs, tickets, code, documentation, activite, dependances,
 *                                              listes, reglages (« Modifier le projet ») ; sans onglet : Vue d'ensemble
 *
 * La coquille découpe l'écran, l'onglet (`a-faire`, `projets`) et l'objet (le reste, segments décodés).
 */
import type { Waiting } from "../../api/projects";

/** Les onglets d'une fiche, dans l'ordre de la maquette : leur segment d'adresse et leur titre. */
export const SHEET_TABS = [
  ["vue", "Vue d'ensemble"],
  ["objectifs", "Objectifs"],
  ["tickets", "Tickets"],
  ["code", "Code"],
  ["documentation", "Documentation"],
  ["activite", "Activité"],
  ["dependances", "Dépendances"],
  ["listes", "Listes"],
] as const;

export type SheetTab = (typeof SHEET_TABS)[number][0] | "reglages";

export type Place =
  | { kind: "todo"; project: number; key: string }
  | { kind: "grid" }
  | { kind: "sheet"; id: number; tab: SheetTab; rest: string[] };

/** Une adresse de l'écran : `route("a-faire", 3, "ticket-4")` → `#projets/a-faire/3/ticket-4`. */
export function route(...parts: Array<string | number | null | undefined>): string {
  const said = parts.filter((x) => x !== null && x !== undefined && x !== "").map((x) => encodeURIComponent(String(x)));
  return `#projets/${said.join("/")}`;
}

/** L'adresse d'une fiche, d'un de ses onglets, de ce qui s'y ouvre ; « vue » n'a pas de segment. */
export function sheetRoute(id: number, ...parts: Array<string | number | null | undefined>): string {
  const [tab, ...rest] = parts;
  return tab === "vue" || tab === "" || tab === null || tab === undefined ? route("projets", id) : route("projets", id, tab, ...rest);
}

/** Où l'on est : l'onglet de l'écran (`a-faire`, `projets`) et l'objet de la route. Un onglet inconnu : Vue d'ensemble. */
export function parsePlace(tab: string | null, item: string | null): Place {
  const segments = (item ?? "").split("/");
  if (tab !== "projets") {
    const project = /^\d+$/.test(segments[0] ?? "") ? Number(segments[0]) : 0;
    return { kind: "todo", project, key: project ? segments.slice(1).join("/") : "" };
  }
  const [id, name, ...rest] = segments;
  if (!/^\d+$/.test(id ?? "")) return { kind: "grid" };
  const known = name === "reglages" || SHEET_TABS.some(([t]) => t === name);
  return { kind: "sheet", id: Number(id), tab: known ? (name as SheetTab) : "vue", rest: known ? rest : [] };
}

/**
 * La clé d'une attente dans son adresse (`ticket-4`, `pr-11`, `plan`, `jalon-2-3`…) : stable d'une lecture à l'autre,
 * faite de ce que le serveur dit d'elle.
 */
export function waitingKey(w: Waiting): string {
  const args = w.gesture?.args ?? {};
  if (w.kind === "approval") return `accord-${String(args.proposal ?? w.number)}`;
  if (w.kind === "plan") return "plan";
  if (w.kind === "ticket") return w.what === "merge" ? `pr-${String(args.number ?? w.number)}` : `ticket-${w.number}`;
  if (w.kind === "checkpoint") return `jalon-${w.objective}-${String(args.milestone ?? 0)}`;
  if (w.kind === "item") return `element-${w.what}-${w.key}`;
  if (w.kind === "need") return `besoin-${w.objective}`;
  return [w.kind, w.objective || "", w.number || "", w.key].filter((x) => x !== "").join("-");
}

/** L'adresse d'une attente dans « À faire ». */
export function waitingRoute(w: Waiting): string {
  return route("a-faire", w.project, waitingKey(w));
}

/** Où l'attente vit dans la fiche de son projet : son ticket, son objectif, sa liste, sa pull request. */
export function waitingHome(w: Waiting): string {
  if (w.kind === "ticket") {
    return w.what === "merge" ? sheetRoute(w.project, "code", "pulls", String(w.gesture?.args?.number ?? "")) : sheetRoute(w.project, "tickets", w.number);
  }
  if (w.kind === "item") return sheetRoute(w.project, "listes", w.what);
  if (w.objective) return sheetRoute(w.project, "objectifs", `o${w.objective}`);
  return sheetRoute(w.project);
}
