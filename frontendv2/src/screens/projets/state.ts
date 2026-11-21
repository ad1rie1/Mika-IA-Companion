/**
 * Projets, l'état de l'écran et ce qu'on en tire (pur, sans DOM) : les filtres, ce qui est choisi, ce qui est saisi
 * et les refus du serveur dits sur place. Les données, elles, restent celles du serveur : rien n'est recalculé ici
 * que leur présentation (un groupe par projet, les objectifs par état, la requête d'un filtre).
 */
import type { ElementsQuery, Listing, Mission, Objective, Sheet, Waiting } from "../../api/projects";
import { waitingKey } from "./routes";

export interface UiState {
  /** « À faire » : le projet filtré (0 : tous). */
  todoProject: number;
  /** Objectifs : le groupe filtré (`""` : tous) ; un filtre se retire en le touchant de nouveau. */
  objectives: "" | "open" | "missions" | "done";
  /** Tickets : `yours` (à toi), `open`, `all` ; et ce qui est cherché. */
  tickets: "yours" | "open" | "all";
  ticketQuery: string;
  /** Le volet « Infos » d'un téléphone. */
  infos: boolean;
  /** Le fil d'activité : la sorte (`""` : tout) et l'objectif (0 : tous). */
  feedKind: string;
  feedObjective: number;
  /** Le carnet : l'objectif (0 : tout). */
  notebook: number;
  /** Listes : en colonnes ou en tableau. */
  listView: "columns" | "table";
  /** Le diagramme : son échelle (`null` : celle qui tient, `pickZoom`), ce qui est replié, la largeur de sa piste, où il a défilé. */
  zoom: "days" | "weeks" | null;
  folded: Set<number>;
  trackWidth: number;
  scrollX: number | null;
  /** Un refus du serveur, dit sur place : où (une clé), et ses mots. */
  refusal: { where: string; text: string; fields: Record<string, string> } | null;
  /** Un geste est en route : ses boutons attendent. */
  busy: string;
}

export function initialState(): UiState {
  return {
    todoProject: 0, objectives: "", tickets: "open", ticketQuery: "", infos: false, feedKind: "", feedObjective: 0, notebook: 0,
    listView: "columns", zoom: null, folded: new Set(), trackWidth: 0, scrollX: null, refusal: null, busy: "",
  };
}

/** Le refus à dire à cet endroit (`""` : aucun). */
export function refusalAt(ui: UiState, where: string): string {
  return ui.refusal && ui.refusal.where === where ? ui.refusal.text : "";
}

export function fieldErrorsAt(ui: UiState, where: string): Record<string, string> {
  return ui.refusal && ui.refusal.where === where ? ui.refusal.fields : {};
}

// ── À faire ──────────────────────────────────────────────────────────

export interface TodoGroup {
  project: number;
  title: string;
  items: Waiting[];
}

/** « À faire », groupé par projet : les projets dans l'ordre où le serveur les fait paraître, ses attentes dans le sien. */
export function todoGroups(todo: readonly Waiting[]): TodoGroup[] {
  const groups: TodoGroup[] = [];
  for (const w of todo) {
    let g = groups.find((x) => x.project === w.project);
    if (!g) {
      g = { project: w.project, title: w.project_title, items: [] };
      groups.push(g);
    }
    g.items.push(w);
  }
  return groups;
}

/** L'attente choisie : celle de l'adresse ; sinon la première, sauf sur un téléphone où l'on reste sur la liste. */
export function chosenWaiting(todo: readonly Waiting[], project: number, key: string, mobile: boolean): Waiting | null {
  return todo.find((w) => w.project === project && waitingKey(w) === key) ?? (mobile ? null : (todo[0] ?? null));
}

/** L'objet choisi d'une liste : celui de l'adresse ; sinon le premier, sauf sur un téléphone. */
export function chosen<T>(items: readonly T[], key: (x: T) => string, wanted: string | undefined, mobile: boolean): T | null {
  return items.find((x) => key(x) === String(wanted ?? "")) ?? (mobile ? null : (items[0] ?? null));
}

// ── Objectifs ────────────────────────────────────────────────────────

export type Goal = { mission: false; o: Objective } | { mission: true; o: Mission };

/** La clé d'un objectif dans son adresse : `o2` pour un ponctuel, `m5` pour une mission. */
export function goalKey(g: Goal): string {
  return `${g.mission ? "m" : "o"}${g.o.id}`;
}

export interface GoalGroup {
  code: "open" | "missions" | "done";
  label: string;
  items: Goal[];
}

/** Les objectifs en trois groupes, comme la maquette : en cours, les missions, terminés. */
export function goalGroups(sheet: Pick<Sheet, "objectives" | "missions">): GoalGroup[] {
  const once = (sheet.objectives ?? []).map((o): Goal => ({ mission: false, o }));
  const missions = (sheet.missions ?? []).map((o): Goal => ({ mission: true, o }));
  return [
    { code: "open", label: "En cours", items: once.filter((g) => g.o.status !== "done") },
    { code: "missions", label: "Missions", items: missions },
    { code: "done", label: "Terminés", items: once.filter((g) => g.o.status === "done") },
  ];
}

export function findGoal(sheet: Pick<Sheet, "objectives" | "missions">, key: string | undefined): Goal | null {
  return goalGroups(sheet).flatMap((g) => g.items).find((g) => goalKey(g) === key) ?? null;
}

/** Quelque chose attend la personne sur cet objectif : un point d'arrêt prêt, ou elle a besoin d'elle. */
export function goalAwaits(o: Objective): boolean {
  return !!o.need || o.milestones.some((m) => m.ready);
}

/** Les jalons vivants d'un objectif (un jalon retiré reste lisible, mais ne compte plus). */
export function liveMilestones(o: Objective): Objective["milestones"] {
  return o.milestones.filter((m) => m.status !== "dropped");
}

// ── Tickets, listes ──────────────────────────────────────────────────

/** La liste des tickets de la fiche, et ses listes de suivi. */
export function ticketList(sheet: Pick<Sheet, "lists">): Listing | null {
  return (sheet.lists ?? []).find((l) => l.tickets) ?? null;
}

export function followLists(sheet: Pick<Sheet, "lists">): Listing[] {
  return (sheet.lists ?? []).filter((l) => !l.tickets);
}

/** La requête de la liste des tickets pour un filtre : « À toi » se lit dans les ouverts (`yours`), côté écran. */
export function ticketsQuery(filter: UiState["tickets"], q: string): ElementsQuery {
  return { list: "tickets", state: filter === "all" ? undefined : "open", q: q.trim().slice(0, 120) || undefined, size: 100 };
}

/** La clé d'une lecture gardée. */
export function cacheKey(...parts: Array<string | number | undefined>): string {
  return parts.map((p) => String(p ?? "")).join("|");
}
