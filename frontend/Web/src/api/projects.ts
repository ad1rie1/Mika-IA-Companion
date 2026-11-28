/**
 * Projets, par l'API par personne (`backend/docs/protocole-moi.md` § 11, ADR 0282, 0288, 0290, 0293) : ses projets, ce qui
 * l'y attend (« À faire »), la fiche d'un projet, son registre (tickets et listes de suivi), ses dépendances, ses
 * gestes ; ce qui s'y gère (le projet et ses réglages, ses objectifs, ses jalons, un ticket) ; son activité (le fil,
 * les trente jours, les exécutions, le carnet) et le diagramme de ses objectifs. Le code et la documentation d'un
 * projet ont leurs clients à côté (lot S4b).
 *
 * Ce que le serveur calcule et que l'écran ne refait jamais : l'ordre d'« À faire », `mine` et `can` de chaque
 * attente, son geste (`gesture`), `rights` de la fiche, `can` d'un élément, `ticket_born`, `veiled`, `hand` / `yours`,
 * `visible` d'un projet lié, tous les `…_label`, la carte d'un projet (`card`), son prochain passage (`next`), le parcours
 * d'un ticket (`journey`), ce que ses formulaires proposent (`forms`). Ses mots non plus : pourquoi un geste ne se fait pas d'ici (`why`), les
 * sortes et les priorités d'un ticket (`kinds`, `priorities`), qui a écrit (`author_kind`, `author`), l'adresse d'une
 * pull request (`gesture.url`). Un texte venu d'ailleurs porte `outside` (ou est un `OutsideText`).
 * Les instants sont en millisecondes (0 : jamais).
 */
import { getJson, MOI, sendJson, type Done } from "./moi";

/** Un texte venu d'ailleurs (un commentaire de l'hôte, la fin d'un journal, la sortie d'une commande) : cité, jamais lu. */
export interface OutsideText {
  text: string;
  outside: true;
}

/** Où se fait un geste : ici (une route de cette API), dans la console, chez l'hôte du dépôt. */
export type GestureWhere = "ici" | "console" | "hote";

export interface Gesture {
  /** La route d'ici, sous `/projets/<id>/` (`""` : rien ici ne le fait). */
  route: string;
  /** Ce que le serveur sait déjà du geste ; l'écran complète (une raison, un statut, le condensé lu). */
  args: Record<string, unknown>;
  label: string;
  where: GestureWhere | string;
  /** Pour un geste chez l'hôte : la page de la pull request, composée par le serveur (`""` : aucune). */
  url: string;
}

/** Une attente : ce qui attend quelqu'un dans un projet, et le geste qui la règle. */
export interface Waiting {
  project: number;
  project_title: string;
  kind: string;
  kind_label: string;
  what: string;
  about: string;
  since: number;
  /** C'est elle qu'on attend. */
  mine: boolean;
  /** Elle peut le faire ici : la garde de la route, dite d'avance. */
  can: boolean;
  /** Pourquoi elle ne le peut pas, en mots (`""` quand `can`) : le refus même que la route rendrait. */
  why: string;
  /** Qui elle attend : la personne nommée ; pour un accord, qui s'occupe d'elle ; `""` : le propriétaire. */
  waits_for: string;
  objective: number;
  number: number;
  key: string;
  /** Un élément qu'elle ne peut pas lire (ni titre ni clé). */
  veiled: string;
  outside: boolean;
  gesture: Gesture;
}

export interface ProjectHead {
  id: number;
  title: string;
  status: string;
  status_label: string;
  mine: boolean;
  /** Un projet à Mika. */
  hers: boolean;
  owner_name: string;
  steer: string;
  steer_label: string;
  detail: boolean;
  where: string;
  last_run: number;
  plan: string;
  plan_label: string;
  waiting: number;
  /** De quoi remplir sa carte sans lire sa fiche (`null` sans le détail ; absent d'une fiche). */
  card?: ProjectCard | null;
}

/** Un segment de la barre d'une carte : un objectif ponctuel, et où il en est (`done`, `doing`, `todo`, `blocked`). */
export interface ProgressState {
  id: number;
  state: string;
  state_label: string;
}

/** La carte d'un projet (ADR 0293) : la progression de ses objectifs, ses compteurs, ses dépendances, par qui il est mené. */
export interface ProjectCard {
  objectives: { total: number; done: number; doing: number; todo: number; blocked: number; states: ProgressState[] };
  pulls_open: number;
  tickets_open: number;
  /** Ce dont il dépend, ce qui dépend de lui (un projet qu'elle ne voit pas : `null`, `""`, `false`). */
  reads: Linked[];
  readers: Linked[];
  /** Par qui il est mené : son nom à elle. */
  led_by: string;
  last_activity: number;
}

/** Ce qu'elle peut faire, la garde de la route dite d'avance, et sinon pourquoi (en mots à afficher tels quels). */
export interface Allowed {
  can: boolean;
  why: string;
}

export interface Overview {
  projects: ProjectHead[];
  todo: Waiting[];
  todo_total: number;
  /** Peut-elle lui confier un projet d'ici. */
  create?: Allowed;
}

export interface TodoPage {
  total: number;
  page: number;
  size: number;
  items: Waiting[];
}

/** Ce qui attend son accord : `text` est exactement ce qui partirait, `digest` le condensé à renvoyer (`seen`). */
export interface Approval {
  id: number;
  project: number;
  project_title: string;
  capability: string;
  label: string;
  summary: string;
  text: string;
  digest: string;
  blocked: string;
  at: number;
  /** Ce qu'il concerne (ADR 0293) : un objectif (0 : aucun), un ticket, une issue et une pull request de l'hôte (0 : aucune). */
  concerns?: { objective: number; ticket: TicketLine | null; issue: number; pull: number };
  /** Où cela part, en mots ; et sa page chez l'hôte, composée par le serveur (`""` : aucune). */
  where?: string;
  where_url?: string;
  asked_by_kind?: string;
  asked_by?: string;
  /** Les mots de la personne dont elle porte la demande (un pilotage demandé) ; vide ailleurs. */
  why?: string;
}

/** Un ticket en une ligne (sur un objectif, un accord) : son titre est vide s'il ne se lit pas. */
export interface TicketLine {
  number: number;
  handle: string;
  title: string;
  veiled: string;
  veiled_label: string;
  status: string;
  status_label: string;
  step: string;
  step_label: string;
  open: boolean;
}

export interface Rights {
  steer: string;
  steer_label: string;
  detail: boolean;
  ticket: boolean;
  /** `open`, `proposed` (il naîtra proposé), ou vide. */
  ticket_born: string;
  note: boolean;
  status: boolean;
  settle: boolean;
  plan: boolean;
  pilot: boolean;
  links: boolean;
  approve: boolean;
  /** Lire le contenu de ses fichiers et ses diffs. */
  files?: boolean;
  /** Fusionner ses pull requests. */
  merge?: boolean;
  /** Changer son cadre : ses réglages, l'archiver. */
  frame?: boolean;
  /** Ses objectifs, ses jalons, ses tickets, ses décisions. */
  edit?: boolean;
  /** Écrire chez l'hôte sur une pull request. */
  pull_write?: boolean;
  /** Lire son activité. */
  work?: boolean;
}

/** Ce qu'elle peut faire d'un objectif ou d'une mission de la fiche. */
export interface ObjectiveCan {
  modify: boolean;
  reopen: boolean;
  done: boolean;
  drop: boolean;
  /** Lui ajouter un jalon. */
  milestone: boolean;
  why: string;
}

export interface MilestoneCan {
  modify: boolean;
  drop: boolean;
  why: string;
}

export interface Mission {
  id: number;
  text: string;
  status: string;
  status_label: string;
  cadence_hours: number;
  cadence_label: string;
  on: { key: string; label: string }[];
  only_on_event: boolean;
  last_run: number;
  passes: number;
  each_pass: string;
  need: string;
  can?: ObjectiveCan;
}

export interface Milestone {
  id: number;
  text: string;
  check: string;
  check_label: string;
  status: string;
  status_label: string;
  /** Un point d'arrêt qui attend. */
  ready: boolean;
  ready_at: number;
  reached_at: number;
  refused_at: number;
  how: string;
  proof: OutsideText | null;
  reason: string;
  commit: string;
  /** Elle s'y est mise : une exécution est partie depuis que le jalon d'avant est atteint. */
  started?: boolean;
  /** Ce qui le lie à un élément de son registre (vides sinon). */
  item_list?: string;
  item?: string;
  item_status?: string;
  item_status_label?: string;
  /** Sa commande, telle qu'on la taperait — seulement avec le droit sur ses fichiers. */
  command?: string;
  can?: MilestoneCan;
}

export interface Pull {
  number: number;
  /** Son titre (vide tant qu'elle n'en a pas). */
  title?: string;
  url: string;
  state: string;
  state_label: string;
  words: string;
  changes_asked: boolean;
  conflicts: boolean;
  at: number;
  awaits_accord: number;
  said: OutsideText | null;
}

export interface Checks {
  state: string;
  state_label: string;
  sha: string;
  at: number;
  said: OutsideText | null;
}

export interface Review {
  ok: boolean;
  label: string;
  at: number;
  text: string;
  refused: number;
  handed_over: boolean;
  last_refusal: string;
}

export interface Objective {
  id: number;
  text: string;
  status: string;
  status_label: string;
  done_when: string;
  ticket: number;
  need: string;
  note: string;
  result: string;
  runs: number;
  last_run: number;
  closed_at: number;
  branch: string;
  /** Les tickets qui lui sont liés : celui dont il est né, ceux qu'il tient. */
  tickets?: TicketLine[];
  milestones: Milestone[];
  pull: Pull | null;
  checks: Checks | null;
  review: Review | null;
  can?: ObjectiveCan;
}

export interface Plan {
  state: string;
  state_label: string;
  text: string;
  questions: string;
  at: number;
  version: number;
  asked_by: string;
}

export interface Status {
  code: string;
  label: string;
}

export interface Listing {
  name: string;
  title: string;
  /** C'est la liste des tickets. */
  tickets: boolean;
  open: Status[];
  closed: Status[];
  counts: Record<string, number>;
  total: number;
  living: number;
  actor: string;
  actor_label: string;
  /** Pour la liste des tickets : les sortes et les priorités d'un ticket (code et mots), et celles par défaut. */
  kinds: Status[];
  kind_default: string;
  priorities: Status[];
  priority_default: string;
  /** La liste des tickets : ses tickets comptés par étape du parcours (les six). */
  journey?: { code: string; label: string; count: number }[];
  /** Une liste de suivi : ce qu'elle peut y faire, et à qui un élément peut être (`self`, `owner`, avec leurs mots). */
  can?: { add: boolean; assign: boolean; why: string };
  actors?: Status[];
}

/** Un commit en bref : son message et son instant (un commit venu du dépôt distant porte `outside`). */
export interface CommitBrief {
  sha: string;
  short: string;
  title: string;
  at: number;
  author_kind?: string;
  author?: string;
  outside?: boolean;
  branch?: string;
}

/**
 * Une demande entre deux projets : du projet (`from: "project"`), ou un ticket qu'elle a ouvert chez le projet lié (`you`).
 * `title` est le titre du ticket (vide et `veiled` si elle ne le lit pas là-bas) : le serveur ne sert pas ici le titre de
 * l'autre projet — il se lit dans le lien du même numéro (`reads`, `readers`).
 */
export interface Demand {
  /** L'autre projet (`null` : elle ne le voit pas). */
  project: number | null;
  title: string;
  visible: boolean;
  /** `sent`, `received`. */
  direction: string;
  from: string;
  /** 0 si elle ne voit pas le projet où vit le ticket. */
  number: number;
  veiled: boolean;
  status: string;
  status_label: string;
  step: string;
  step_label: string;
  at: number;
  closed_at: number;
}

/** « Lui demander quelque chose » : ouvrir un ticket chez un projet lié (`POST /projets/<project>/<route>`). */
export interface AskHere {
  can: boolean;
  why: string;
  /** `open`, `proposed`, ou vide. */
  born: string;
  project: number | null;
  route: string;
}

/** Ce qu'un lien donne. */
export interface Gives {
  see: boolean;
  detail: boolean;
  files: boolean;
  /** Sa documentation (ADR 0289). */
  docs?: boolean;
  ask: string;
  ask_label: string;
}

/** Un projet lié : son numéro et son titre seulement si elle le voit elle-même. */
export interface Linked {
  project: number | null;
  title: string;
  visible: boolean;
}

export interface Reading extends Linked {
  suspended: boolean;
  gives: Gives;
  direct: boolean;
  /** Depuis quand le lien est posé, et le mot de son propriétaire (vide : aucun, ou un projet qu'elle ne voit pas). */
  since?: number;
  why?: string;
  /** Le commit que montre la vue de son atelier (`null` : le lien ne donne pas ses fichiers, ou elle n'en lit pas le détail). */
  commit?: CommitBrief | null;
  /** Les demandes entre les deux : celles du projet, et les tickets qu'elle y a ouverts elle-même. */
  asks?: Demand[];
  ask_here?: AskHere;
}

export interface Reader extends Linked {
  gives: Gives;
  since?: number;
  why?: string;
  asks?: Demand[];
}

/** Un projet qu'elle peut lui faire lire, et ce que le lien donnerait (`see: false` : rien pour l'instant). */
export interface Candidate extends Linked {
  gives: Gives;
}

export interface Links {
  reads: Reading[];
  plan_asks: Linked[];
  readers: Reader[];
  /** Ses demandes à d'autres projets, et celles qu'il a reçues. */
  asks: Demand[];
  received?: Demand[];
  /** Elle peut poser ses liens. */
  can: boolean;
  candidates: Candidate[];
  /** Les mots de cette vue, « Dépendances ». */
  labels?: { title: string; reads: string; readers: string; asks: string };
}

export interface Repo {
  has_remote: boolean;
  remote: string;
  branch: string;
  flow: string;
  flow_label: string;
  auto_push: boolean;
  last_commit: string;
  remote_ok: boolean;
  remote_at: number;
  remote_line: OutsideText | null;
  /** Son dernier commit, lu dans le dépôt de l'atelier (`null` sans dépôt). */
  commit?: CommitBrief | null;
}

/** Son prochain passage (ADR 0293) : le moteur n'estime rien — sans date, `at` vaut 0. */
export interface NextPass {
  at: number;
  /** `due`, `running`, `paused`, `on_demand`, `idle`. */
  state: string;
  state_label: string;
  /** `frame`, `review`, `run`, ou vide. */
  sort: string;
  sort_label: string;
  objective: { id: number; text: string; kind: string } | null;
}

/** Son rythme en mots : son agenda, sa plage, les deux en une phrase. */
export interface Rhythm {
  schedule: string;
  window: string;
  summary: string;
}

/** Une consigne en attente : elle la lira à sa prochaine exécution. */
export interface Instruction {
  seq: number;
  at: number;
  text: string;
  /** D'un niveau qu'elle n'entend pas : le texte n'est pas servi. */
  veiled: boolean;
  author_kind: string;
  author: string;
}

/** Ce qui peut déclencher une mission : sa clé s'envoie telle quelle dans `on`. */
export interface Trigger {
  key: string;
  label: string;
  sort: string;
  sort_label: string;
  project: number | null;
  title: string;
}

/** Une façon de vérifier un jalon, avec ses mots et ce qu'il faut saisir pour elle. */
export interface CheckKind {
  code: string;
  label: string;
  help: string;
  fields: { name: string; label: string; help: string; required: boolean }[];
}

/** De quoi remplir les formulaires d'un objectif et d'un jalon. */
export interface Forms extends Allowed {
  triggers: Trigger[];
  triggers_max: number;
  checks: CheckKind[];
}

/** La fiche. Qui ne fait que voir le projet reçoit `project`, `rights` et `todo`, rien d'autre. */
export interface Sheet {
  project: ProjectHead & { description: string };
  rights: Rights;
  todo: Waiting[];
  missions?: Mission[];
  objectives?: Objective[];
  plan?: Plan;
  lists?: Listing[];
  links?: Links;
  repo?: Repo;
  next?: NextPass;
  rhythm?: Rhythm;
  instructions?: Instruction[];
  forms?: Forms;
}

/** Qui a écrit : elle, la personne connectée, une autre personne, un autre projet, quelqu'un chez l'hôte du dépôt. */
export type AuthorKind = "self" | "you" | "person" | "project" | "host";

/** Une ligne d'une liste : un ticket, ou un élément d'une liste de suivi. */
export interface Entry {
  list: string;
  /** `#n` pour un ticket, sa clé sinon. */
  handle: string;
  number: number;
  key: string;
  title: string;
  veiled: string;
  veiled_label: string;
  status: string;
  status_label: string;
  open: boolean;
  hand: string;
  hand_label: string;
  /** À elle, et elle peut trancher. */
  yours: boolean;
  kind: string;
  kind_label: string;
  priority: string;
  priority_label: string;
  actor: string;
  actor_label: string;
  author_kind: AuthorKind | string;
  /** Qui l'a ouvert, en mots à afficher (un nom seulement si elle a le droit de le savoir). */
  author: string;
  outside: boolean;
  objective: number;
  notes: number;
  at: number;
  updated_at: number;
  /** Le numéro de son plan (0 : aucun). */
  plan: number;
  issue: number;
  pull: number;
  /** Son étape du parcours, parmi les six (vide : écarté, ou pas un ticket). */
  step?: string;
  step_label?: string;
  /** Ce que l'hôte a dit en dernier de son issue (`open`, `closed`, ou vide). */
  issue_state?: string;
  issue_state_label?: string;
}

/** Une étape du parcours d'un ticket : passée, en cours, à venir, sautée. */
export interface JourneyStep {
  code: string;
  label: string;
  /** `done`, `current`, `todo`, `skipped`. */
  state: string;
  state_label: string;
}

/** Le parcours d'un ticket en six étapes (ADR 0293) ; l'étape fine est la précision de l'étape en cours. */
export interface Journey {
  steps: JourneyStep[];
  current: string;
  current_label: string;
  fine: string;
  fine_label: string;
  /** Il passe par une pull request ; sinon il saute `skips`, et `skips_label` dit pourquoi. */
  through_pull: boolean;
  skips: string[];
  skips_label: string;
  /** Vide, `treated`, `dismissed`. */
  ended: string;
  ended_label: string;
}

/** Ce qui est lié à un ticket : l'objectif qui le tient, sa pull request et ses vérifications (comme sur la fiche). */
export interface EntryLinked {
  objective: { id: number; text: string; status: string; status_label: string } | null;
  pull: Pull | null;
  checks: Checks | null;
}

/** Un passage de l'histoire d'un ticket : l'étape où il entre, celle qu'il quitte, qui l'y a fait passer. */
export interface Passage {
  seq: number;
  at: number;
  status: string;
  status_label: string;
  /** Vide : sa naissance. */
  was: string;
  was_label: string;
  step: string;
  step_label: string;
  author_kind: AuthorKind | string;
  author: string;
  outside: boolean;
}

export interface EntryHistory {
  item: string;
  /** Trop d'événements pour tout rejouer. */
  cut: boolean;
  items: Passage[];
}

export interface EntryPage {
  list: string;
  total: number;
  page: number;
  size: number;
  items: Entry[];
}

export interface ThreadNote {
  seq: number;
  at: number;
  author_kind: AuthorKind | string;
  author: string;
  /** Sa sorte : `note`, `change` (ce qui a été dit d'un changement), `question`, `plan`. */
  kind: string;
  kind_label: string;
  text: string;
  outside: boolean;
}

export interface EntryCan {
  note: boolean;
  status: boolean;
  /** Changer à qui il est : un élément d'une liste de suivi. */
  assign?: boolean;
  accept: boolean;
  dismiss: boolean;
  dismiss_needs_reason: boolean;
  validate: boolean;
  refuse: boolean;
  modify?: boolean;
  /** Le fermer comme traité. */
  close?: boolean;
  reopen?: boolean;
}

export interface EntryDetail extends Entry {
  body: string;
  link: string;
  thread: ThreadNote[];
  /** Le plan à lire avant de le valider. */
  plan_text: string;
  small: boolean;
  statuses: Status[];
  /** Pour un ticket (sinon `null`). */
  journey?: Journey | null;
  linked?: EntryLinked;
  can: EntryCan;
}

export interface ElementsQuery {
  list?: string;
  state?: string;
  status?: string;
  q?: string;
  page?: number;
  size?: number;
}

const ROOT = `${MOI}/projets`;

function query(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") q.set(key, String(value));
  }
  const said = q.toString();
  return said ? `?${said}` : "";
}

export function fetchOverview(): Promise<Overview> {
  return getJson<Overview>(ROOT);
}

export function fetchTodo(page: number): Promise<TodoPage> {
  return getJson<TodoPage>(`${ROOT}/a-faire${query({ page })}`);
}

export function fetchApprovals(project?: number): Promise<{ items: Approval[] }> {
  return getJson<{ items: Approval[] }>(`${ROOT}/accords${query({ project })}`);
}

export function fetchSheet(id: number): Promise<Sheet> {
  return getJson<Sheet>(`${ROOT}/${id}`);
}

export function fetchElements(id: number, q: ElementsQuery): Promise<EntryPage> {
  return getJson<EntryPage>(`${ROOT}/${id}/elements${query({ ...q })}`);
}

export function fetchElement(id: number, list: string, item: string): Promise<EntryDetail> {
  return getJson<EntryDetail>(`${ROOT}/${id}/element${query({ list, item })}`);
}

/** L'histoire des étapes d'un ticket (`item` : `#n`), de la plus ancienne à la plus récente. */
export function fetchHistory(id: number, item: string): Promise<EntryHistory> {
  return getJson<EntryHistory>(`${ROOT}/${id}/element/historique${query({ item })}`);
}

/** Ce que rend un geste : `number` et `proposed` pour un ticket ouvert, `status` pour un accord décidé, `project` pour
 * un projet confié, `objective` pour un objectif ajouté, `list` et `key` pour un élément ajouté à une liste. */
export interface GestureDone extends Done {
  number?: number;
  proposed?: boolean;
  status?: string;
  project?: number;
  objective?: number;
  list?: string;
  key?: string;
}

// ── Gérer un projet (ADR 0290) ───────────────────────────────────────

/** Un champ d'une action de la console, décrit par elle : le client n'écrit aucun libellé. */
export interface Field {
  name: string;
  label: string;
  help: string;
  /** `text`, `textarea`, `select`, `bool`, `int`… */
  kind: string;
  required: boolean;
  choices: Status[];
  value: unknown;
  min?: number | null;
  max?: number | null;
  /** Les valeurs d'un autre champ qui le rendent utile. */
  only?: { field: string; values: unknown[] }[];
  /** Elle peut le changer : la garde de l'enregistrement, dite d'avance ; sinon pourquoi (absents d'un champ de « Nouveau projet »). */
  can?: boolean;
  why?: string;
}

export interface NewProject extends Allowed {
  fields: Field[];
}

export interface SettingsSection {
  /** `general`, `rythme`, `accords`, `depot`, `outils`. */
  name: string;
  title: string;
  /** La section en une ligne. */
  summary: string;
  /** Au moins un de ses champs se change ; sinon pourquoi. */
  can?: boolean;
  why?: string;
  fields: Field[];
}

export interface Settings extends Allowed {
  renamable: boolean;
  archive: Allowed;
  sections: SettingsSection[];
}

export interface Archived {
  id: number;
  title: string;
  archived_at: number;
  owner_name: string;
}

// ── L'activité d'un projet ───────────────────────────────────────────

/** Une ligne du fil. */
export interface Happening {
  seq: number;
  at: number;
  /** `run`, `commit`, `pull`, `ticket`, `gesture`. */
  kind: string;
  kind_label: string;
  what: string;
  title: string;
  sub: string;
  objective: number;
  ticket: number;
  pull: number;
  sha: string;
  verdict: string;
  verdict_label: string;
  /** L'exécution à ouvrir. */
  run: string;
  author_kind: AuthorKind | string;
  author: string;
  outside: boolean;
}

export interface ActivityPage {
  kinds: Status[];
  size: number;
  /** Le curseur à renvoyer dans `before` (0 : il n'y a plus rien). */
  next: number;
  items: Happening[];
}

/** Un jour des trente derniers : un compte par sorte, et `total`. */
export interface ActivityDay {
  day: string;
  total: number;
  [kind: string]: number | string;
}

export interface ActivityDays {
  days: ActivityDay[];
  totals: Record<string, number>;
  total: number;
  kinds: Status[];
  by: { who: string; label: string; count: number }[];
  cut: boolean;
}

export interface RunObjective {
  id: number;
  text: string;
  kind: string;
  ticket: number;
  status: string;
  status_label: string;
}

export interface Run {
  id: string;
  at: number;
  /** `frame` (cadrage), `run` (travail), `review` (relecture). */
  sort: string;
  sort_label: string;
  objective: RunObjective | null;
  running: boolean;
  outcome: string;
  outcome_label: string;
  seconds: number;
  verdict: string;
  verdict_label: string;
  proven: boolean;
  summary: string;
  commit: string;
  branch: string;
  /** Elle a demandé quelque chose. */
  asked: boolean;
}

export interface RunPage {
  total: number;
  size: number;
  next: number;
  sorts: Status[];
  items: Run[];
}

export interface RunStep {
  tool: string;
  label: string;
  aim: string;
  ok: boolean;
  ran: boolean;
  ms: number;
  /** Il change quelque chose. */
  acts: boolean;
  /** Ce que cet outil rend vient d'ailleurs. */
  outside: boolean;
}

export interface RunDetail extends Run {
  report: string;
  need: string;
  steps: RunStep[];
  steps_cut?: boolean;
  steps_kept?: boolean;
  /** Ce que chaque pas visait se dit (le droit sur les fichiers) ; sinon pourquoi. */
  steps_aims?: boolean;
  steps_aims_why?: string;
}

export interface NotebookNote {
  seq: number;
  at: number;
  text: string;
  /** Celui qu'elle visait en l'écrivant, ou `null`. */
  objective: RunObjective | null;
  run: string;
}

export interface NotebookPage {
  size: number;
  next: number;
  items: NotebookNote[];
  /** Combien de notes, pour ce filtre ; `total_cut` : le compte est incomplet. */
  total?: number;
  total_cut?: boolean;
}

/** Les totaux de son activité, sur toute son histoire et pour un filtre (ADR 0293). */
export interface ActivityTotals {
  kinds: { code: string; label: string; count: number }[];
  totals: Record<string, number>;
  total: number;
  /** Trop d'événements : le compte est incomplet. */
  cut: boolean;
  /** Les notes de son carnet, et ses exécutions. */
  notes: number;
  notes_cut: boolean;
  runs: number;
}

/** Un jalon du diagramme : de vraies dates seulement (0 : pas encore arrivé). */
export interface DiagramMilestone {
  id: number;
  text: string;
  status: string;
  status_label: string;
  check: string;
  check_label: string;
  ready: boolean;
  added_at: number;
  started_at: number;
  ready_at: number;
  reached_at: number;
  runs: number;
}

export interface DiagramObjective {
  id: number;
  text: string;
  /** `once`, `constant` (une mission). */
  kind: string;
  status: string;
  status_label: string;
  /** L'objectif dont il dépend (0 : aucun). */
  after: number;
  rank: number;
  ticket: number;
  added_at: number;
  started_at: number;
  last_run: number;
  closed_at: number;
  runs: number;
  reached: number;
  milestones_total: number;
  /** Les passages d'une mission. */
  passes: number[];
  milestones: DiagramMilestone[];
}

export interface Diagram {
  now: number;
  from: number;
  cut: boolean;
  objectives: DiagramObjective[];
}

/**
 * Un geste : `POST /api/moi/projets/<project>/<route>`, avec sa clé d'envoi (un double clic ne refait rien). Un refus
 * lève `ApiError`, avec les mots du serveur et ses messages par champ.
 */
export function sendGesture(project: number, route: string, body: Record<string, unknown>, nonce: string): Promise<GestureDone> {
  return sendJson<GestureDone>(`${ROOT}/${project}/${route}`, body, nonce);
}

export function fetchNewProject(): Promise<NewProject> {
  return getJson<NewProject>(`${ROOT}/nouveau`);
}

/** Lui confier un projet : il naît à cadrer → `project`, à ouvrir. */
export function createProject(body: Record<string, unknown>, nonce: string): Promise<GestureDone> {
  return sendJson<GestureDone>(`${ROOT}/nouveau/creer`, body, nonce);
}

export function fetchArchives(): Promise<{ items: Archived[] }> {
  return getJson<{ items: Archived[] }>(`${ROOT}/archives`);
}

export function fetchSettings(id: number): Promise<Settings> {
  return getJson<Settings>(`${ROOT}/${id}/reglages`);
}

export interface ActivityQuery {
  kind?: string;
  objective?: number;
  /** Ce qui arrive à ce ticket, et aux objectifs nés de lui. */
  ticket?: number;
  before?: number;
  size?: number;
}

export function fetchActivity(id: number, q: ActivityQuery = {}): Promise<ActivityPage> {
  return getJson<ActivityPage>(`${ROOT}/${id}/activite${query({ ...q, objective: q.objective || undefined, ticket: q.ticket || undefined, before: q.before || undefined })}`);
}

export function fetchActivityTotals(id: number, q: { objective?: number; ticket?: number } = {}): Promise<ActivityTotals> {
  return getJson<ActivityTotals>(`${ROOT}/${id}/activite/totaux${query({ objective: q.objective || undefined, ticket: q.ticket || undefined })}`);
}

export function fetchActivityDays(id: number): Promise<ActivityDays> {
  return getJson<ActivityDays>(`${ROOT}/${id}/activite/jours`);
}

export function fetchRuns(id: number, before = 0): Promise<RunPage> {
  return getJson<RunPage>(`${ROOT}/${id}/executions${query({ before: before || undefined })}`);
}

export function fetchRun(id: number, run: string): Promise<RunDetail> {
  return getJson<RunDetail>(`${ROOT}/${id}/execution${query({ id: run })}`);
}

export function fetchNotebook(id: number, objective = 0): Promise<NotebookPage> {
  return getJson<NotebookPage>(`${ROOT}/${id}/carnet${query({ objective: objective || undefined })}`);
}

export function fetchDiagram(id: number): Promise<Diagram> {
  return getJson<Diagram>(`${ROOT}/${id}/diagramme`);
}
