/**
 * Projets, un geste traduit en requête (pur, sans DOM). Aucune règle n'est refaite ici : ce qu'on peut faire vient du
 * serveur (`can`, `why`, `rights`), et lui seul dit si ce qui est saisi suffit (une raison exigée, un plan réécrit
 * depuis). Ce module dit seulement quelle route et quel corps un bouton envoie (`protocole-moi.md` § 11).
 */
import type { EntryDetail, Field, Gives, Links, ProjectHead, Waiting } from "../../api/projects";

/** La liste des tickets, dans le registre d'un projet. */
export const TICKETS = "tickets";

export interface GestureRequest {
  /** Sous `/api/moi/projets/<id>/`. */
  route: string;
  body: Record<string, unknown>;
}

function filled(body: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(body).filter(([, v]) => v !== undefined && v !== ""));
}

// ── Les mots ─────────────────────────────────────────────────────────

export function plural(n: number, one: string, many: string): string {
  return `${n} ${n > 1 ? many : one}`;
}

/** Pour qui est un projet, tel que le serveur le dit (`mine`, `hers`, `owner_name`). */
export function forWhom(p: Pick<ProjectHead, "mine" | "hers" | "owner_name">): string {
  if (p.mine) return p.hers ? "à Mika · tu t'en occupes" : "à toi";
  return p.owner_name ? `de ${p.owner_name}` : "à quelqu'un d'autre";
}

/** Un lien qu'on peut ouvrir : http ou https seulement (une adresse venue d'ailleurs ne devient jamais autre chose). */
export function safeLink(url: string | null | undefined): string {
  return /^https?:\/\//i.test(url ?? "") ? String(url) : "";
}

/** Ce que dit un refus : son message, puis ce que disent ses champs (une raison exigée, un statut inconnu). */
export function refusalWords(message: string, fields: Record<string, string> = {}): string {
  const more = Object.values(fields).filter((f) => f && !message.includes(f));
  return more.length ? `${message} ${more.join(" ; ")}` : message;
}

// ── Une attente et son geste ─────────────────────────────────────────

/** Ce qu'un geste demande de lire avant de décider : ce qui partirait, la fiche (son plan, un jalon), un élément. */
export type GestureRead =
  | { kind: "none" }
  | { kind: "approval"; id: number }
  | { kind: "plan" }
  | { kind: "milestone"; objective: number; milestone: number }
  | { kind: "element"; list: string; item: string };

export function gestureRead(w: Waiting): GestureRead {
  const { route, args } = w.gesture;
  if (route === "accord") return { kind: "approval", id: Number(args.proposal ?? 0) };
  if (route === "plan") return { kind: "plan" };
  if (route === "jalon") return { kind: "milestone", objective: Number(args.objective ?? w.objective), milestone: Number(args.milestone ?? 0) };
  if (route === "element/statut" || route === "element/noter" || route === "ticket/trancher") {
    return { kind: "element", list: String(args.list ?? TICKETS), item: String(args.item ?? (w.number ? `#${w.number}` : w.key)) };
  }
  // une pull request à fusionner : son ticket se lit (ce qui lui est lié — son objectif, sa pull request, sa CI)
  if (route === "code/pull/fusionner" && w.kind === "ticket" && w.number) return { kind: "element", list: TICKETS, item: `#${w.number}` };
  return { kind: "none" };
}

/** Où se règle une attente : ici (et elle le peut), ici mais pas par elle, dans la console, chez l'hôte du dépôt. */
export type GesturePlace = "here" | "denied" | "console" | "host" | "theirs";

export function gesturePlace(w: Waiting): GesturePlace {
  if (!w.mine) return "theirs";
  if (w.gesture.where === "hote") return "host";
  if (w.gesture.where !== "ici" || !w.gesture.route) return "console";
  return w.can ? "here" : "denied";
}

/** Ce que la personne a lu, et que la requête nomme : le condensé d'un accord, le numéro du plan d'un ticket. */
export interface Read {
  digest?: string;
  plan?: number;
}

/**
 * La requête d'un geste d'« À faire » : la route et les arguments que le serveur a donnés (`gesture`), complétés par
 * le bouton touché (`action`), ce qui est saisi (`typed`) et ce qui a été lu (`read`).
 */
export function gestureRequest(w: Waiting, action: string, typed: string, read: Read = {}): GestureRequest {
  const { route, args } = w.gesture;
  const text = typed.trim();
  if (route === "accord") return { route, body: filled({ ...args, decision: action, seen: action === "accept" ? (read.digest ?? "") : undefined, note: text }) };
  if (route === "plan") return { route, body: filled({ ...args, verdict: action, words: text }) };
  if (route === "piloter") return { route, body: filled({ ...args, text }) };
  if (route === "jalon") return { route, body: filled({ ...args, verdict: action, reason: text }) };
  if (route === "element/statut") return { route, body: filled({ ...args, status: action, note: text }) };
  if (route === "element/noter") return { route, body: filled({ ...args, text }) };
  if (route === "ticket/trancher") {
    // valider nomme le plan lu : celui qu'on a montré, pas celui que la liste portait
    const plan = action === "validate" ? (read.plan ?? Number(args.plan ?? 0)) : undefined;
    return { route, body: filled({ item: args.item, verdict: action, reason: text, plan }) };
  }
  return { route, body: filled({ ...args }) };
}

// ── Les gestes de la fiche ───────────────────────────────────────────

/** Ce que l'API nomme `item` : `#n` pour un ticket, sa clé sinon. */
export function entryItem(e: { list: string; handle: string; key: string }): string {
  return e.list === TICKETS ? e.handle : e.key;
}

/** Trancher un ticket : `accept`, `dismiss`, `validate` (en nommant le plan lu), `refuse`, `done`, `reopen`. */
export function settleRequest(e: Pick<EntryDetail, "handle" | "plan">, verdict: string, reason = ""): GestureRequest {
  const plan = verdict === "validate" ? e.plan : undefined;
  return { route: "ticket/trancher", body: filled({ item: e.handle, verdict, reason: reason.trim(), plan }) };
}

/** Une note dans le fil d'un élément ; sur un ticket qui pose une question, elle y répond. */
export function noteRequest(e: { list: string; handle: string; key: string }, text: string): GestureRequest {
  return { route: "element/noter", body: filled({ list: e.list, item: entryItem(e), text: text.trim() }) };
}

/** Le statut d'un élément d'une liste de suivi. */
export function statusRequest(e: { list: string; handle: string; key: string }, status: string): GestureRequest {
  return { route: "element/statut", body: filled({ list: e.list, item: entryItem(e), status }) };
}

/** Un élément de plus dans une liste de suivi : son titre, et ce qui est saisi d'autre (un texte, un statut, à qui il est). */
export function itemAddRequest(list: string, values: Values): GestureRequest {
  return { route: "element/ajouter", body: filled({ list, title: String(values.title ?? "").trim(), text: String(values.text ?? "").trim(), status: String(values.status ?? ""), actor: String(values.actor ?? "") }) };
}

/** À qui est un élément d'une liste de suivi : `self` (elle), `owner` (le propriétaire du projet). */
export function assignRequest(e: { list: string; handle: string; key: string }, actor: string): GestureRequest {
  return { route: "element/confier", body: { list: e.list, item: entryItem(e), actor } };
}

/** Piloter : une consigne, « vas-y maintenant » (sur un objectif, s'il est nommé), la pause, la reprise. */
export function pilotRequest(what: string, text = "", objective = 0): GestureRequest {
  return { route: "piloter", body: filled({ what, text: text.trim(), objective: objective || undefined }) };
}

/** Un point d'arrêt dit prêt : validé, ou refusé avec ce qui manque. */
export function checkpointRequest(objective: number, milestone: number, verdict: string, reason = ""): GestureRequest {
  return { route: "jalon", body: filled({ objective, milestone, verdict, reason: reason.trim() }) };
}

export function objectiveStatusRequest(objective: number, status: string): GestureRequest {
  return { route: "objectif/statut", body: { objective, status } };
}

/** Ce qu'un formulaire a rendu : ses champs par leur nom (une case cochée : `true` ; plusieurs du même nom : une liste). */
export type Values = Record<string, unknown>;

function same(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) || Array.isArray(b)) return JSON.stringify([...(a as unknown[] ?? [])].map(String).sort()) === JSON.stringify([...(b as unknown[] ?? [])].map(String).sort());
  return String(a ?? "") === String(b ?? "");
}

/** Seulement ce qui change entre ce qui était servi et ce qui est saisi : le reste garde sa valeur. */
export function changed(before: Values, after: Values): Values {
  return Object.fromEntries(Object.entries(after).filter(([k, v]) => !same(before[k], v)));
}

/**
 * Ajouter un objectif (ou une mission), ou le modifier : `objective` nommé, seuls les champs changés partent.
 * `cadence_hours` est un nombre ; `on` une liste de clés ; `each_pass`, une ligne par chose.
 */
export function objectiveRequest(values: Values, before: Values | null, objective = 0): GestureRequest {
  const mission = (before ? before.kind : values.kind) === "constant";
  const v: Values = { text: String(values.text ?? "").trim() };
  if (mission) {
    Object.assign(v, {
      cadence_hours: Number(values.cadence_hours ?? 0) || 0,
      on: ([] as unknown[]).concat(values.on ?? []).map(String).filter(Boolean),
      only_on_event: values.only_on_event === true,
      each_pass: String(values.each_pass ?? "").trim(),
    });
  } else {
    v.done_when = String(values.done_when ?? "").trim();
  }
  if (objective && before) return { route: "objectif/modifier", body: { objective, ...changed(before, v) } };
  const born: Values = { ...v, kind: mission ? "constant" : "once" };
  if (mission && values.at_once === true) born.at_once = true;
  return { route: "objectif", body: filled(born) };
}

/** Ajouter un jalon, ou le modifier (`milestone` nommé : seulement ce qui change). */
export function milestoneRequest(objective: number, values: Values, before: Values | null, milestone = 0): GestureRequest {
  const check = String(values.check ?? "prose");
  const v: Values = { text: String(values.text ?? "").trim(), check };
  if (check === "command") v.command = String(values.command ?? "").trim();
  if (check === "item") Object.assign(v, { item_list: String(values.item_list ?? "").trim(), item: String(values.item ?? "").trim(), item_status: String(values.item_status ?? "").trim() });
  if (milestone && before) return { route: "jalon/modifier", body: { objective, milestone, ...changed(before, v) } };
  return { route: "jalon/ajouter", body: { objective, ...filled(v) } };
}

/** Ouvrir un ticket, ou le modifier (`item` nommé : seulement ce qui change ; son étape ne change pas). */
export function ticketRequest(values: Values, before: Values | null, item = ""): GestureRequest {
  const v: Values = { title: String(values.title ?? "").trim(), text: String(values.text ?? ""), kind: String(values.kind ?? ""), priority: String(values.priority ?? "") };
  if (item && before) return { route: "ticket/modifier", body: { item, ...changed(before, v) } };
  return { route: "ticket", body: filled(v) };
}

/** La valeur d'un champ servi, telle que le formulaire la rend : un booléen, un nombre, une liste, un texte. */
export function fieldValue(f: Field, raw: unknown): unknown {
  if (f.kind === "bool") return raw === true || raw === "on" || raw === "true";
  if (f.kind === "int") return raw === "" || raw === undefined || raw === null ? null : Number(raw);
  if (Array.isArray(f.value)) return ([] as unknown[]).concat(raw ?? []).map(String);
  return String(raw ?? "");
}

/** Les réglages d'une section : seulement les champs qui changent, par leur nom. Un champ que le serveur dit réservé
 *  (`can: false`) ne part jamais : il se montre verrouillé, rien ne s'y saisit. */
export function settingsRequest(section: string, fields: readonly Field[], values: Values): GestureRequest {
  const open = fields.filter((f) => f.can !== false);
  const before: Values = Object.fromEntries(open.map((f) => [f.name, f.kind === "bool" ? f.value === true : f.value]));
  const after: Values = Object.fromEntries(open.map((f) => [f.name, fieldValue(f, values[f.name])]));
  return { route: "reglages/enregistrer", body: { section, values: changed(before, after) } };
}

/** Un champ ne sert que pour certaines valeurs d'un autre (`only`) : se montre-t-il, vu ce qui est saisi ? */
export function fieldShown(f: Field, values: Values): boolean {
  return (f.only ?? []).every((o) => o.values.map(String).includes(String(values[o.field] ?? "")));
}

// ── Ses dépendances ──────────────────────────────────────────────────

/** Les quatre choses qu'un lien donne, dans l'ordre de la maquette. */
export const GIVEN = ["see", "detail", "files", "docs"] as const;

export function givenCount(g: Gives): number {
  return GIVEN.filter((k) => g[k] === true).length;
}

/**
 * Se mettre à lire un projet, ne plus le lire, laisser ses demandes y entrer directement ou non : ce qui change.
 * Le mot du lien (`why`, pourquoi il lit ce projet) se dit en le posant ; il nomme son projet (`why_for`).
 */
export function linkRequest(change: "add" | "remove" | "direct_on" | "direct_off", project: number, why = ""): GestureRequest {
  const word = why.trim();
  return { route: "liens", body: { [change]: [project], ...(change === "add" && word ? { why: word, why_for: project } : {}) } };
}

/** Le mot d'un lien déjà posé, dit seul, plus tard. */
export function linkWhyRequest(project: number, why: string): GestureRequest {
  return { route: "liens", body: { why: why.trim(), why_for: project } };
}

/** Les projets qu'elle peut lui faire lire : ceux qu'elle voit, qu'il ne lit pas déjà. */
export function linkCandidates(links: Links): { project: number; title: string; gives: Gives }[] {
  const read = new Set(links.reads.map((x) => x.project));
  return links.candidates.filter((c) => c.project !== null && c.visible && !read.has(c.project)).map((c) => ({ project: c.project as number, title: c.title, gives: c.gives }));
}
