/**
 * Le code d'un projet (`/api/moi/projets/<id>/code…`, ADR 0288 ; le contrat : `backendv2/docs/protocole-moi.md` § 11,
 * « Le code d'un projet ») : ses fichiers, ses commits et leur diff, ses branches, ses pull requests, ses issues, sa
 * CI. Rien n'est recalculé ici : les mots sont ceux du serveur (`…_label`, `why`, `files_why`, `cut_label`), et tout
 * texte de l'hôte arrive marqué (`{"text", "outside": true}`, ou `null`).
 */
import { getJson, MOI } from "./moi";
import type { Milestone, OutsideText } from "./projects";

/** Un commit, partout où il apparaît. `outside` : venu du dépôt distant — son message et son auteur ne sont pas d'elle. */
export interface Commit {
  sha: string;
  short: string;
  title: string;
  at: number;
  /** `self` : elle ; `other`. */
  author_kind: string;
  author: string;
  outside: boolean;
  branch: string;
  base: boolean;
  /** Une fusion. */
  merge: boolean;
  files: number;
  insertions: number;
  deletions: number;
  /** Ceux qui lui sont liés ; 0 : aucun. */
  objective: number;
  ticket: number;
  /** Sa page chez l'hôte, composée par le serveur ; vide sans dépôt distant. */
  url: string;
}

export interface LinkedObjective {
  id: number;
  text: string;
  kind: string;
  status: string;
  status_label: string;
}

export interface LinkedTicket {
  number: number;
  handle: string;
  title: string;
  veiled: string;
  veiled_label: string;
  status: string;
  status_label: string;
  open: boolean;
  hand: string;
  hand_label: string;
  yours: boolean;
}

export interface ChecksBrief {
  /** `none`, `pending`, `passed`, `failed`. */
  state: string;
  state_label: string;
  sha: string;
  at: number;
  /** La fin du journal d'un échec (sur une pull request lue seule, et dans la liste de la CI). */
  said?: OutsideText | null;
}

export interface ReviewBrief {
  /** `null` : pas encore de verdict. */
  ok: boolean | null;
  asked: boolean;
  label: string;
  at: number;
  commit: string;
  refused: number;
  handed_over: boolean;
  /** Sur une pull request lue seule : qui l'a relue, ses constats, son dernier refus. */
  by?: string;
  text?: string;
  last_refusal?: string;
}

/** Une pull request en bref : là où elle est liée à autre chose. */
export interface PullBrief {
  /** 0 : pas encore de numéro (proposée, elle attend un accord). */
  number: number;
  title: string;
  /** `proposed`, `open`, `ready`, `merged`, `closed`. */
  state: string;
  state_label: string;
  url: string;
  branch: string;
  checks: ChecksBrief | null;
  review: ReviewBrief | null;
}

/** Ce qui est lié à un commit, à une branche : l'objectif, son ticket, sa pull request, ses vérifications. */
export interface Linked {
  objective: LinkedObjective | null;
  ticket: LinkedTicket | null;
  pull: PullBrief | null;
  checks: ChecksBrief | null;
}

/** Peut-elle la fusionner : la garde de la route, dite d'avance ; et où en est une fusion déjà demandée. */
export interface MergeState {
  can: boolean;
  why: string;
  asked: boolean;
  asked_at: number;
  asked_by: string;
  /** Pourquoi la dernière demande n'a pas abouti, en mots. */
  refused: string;
  refused_at: number;
}

/** Une pull request dans la liste. */
export interface PullLine extends PullBrief {
  base: string;
  at: number;
  conflicts: boolean;
  changes_asked: boolean;
  awaits_accord: number;
  unsent: boolean;
  objective: LinkedObjective | null;
  ticket: LinkedTicket | null;
  merge: MergeState;
}

export interface DiffLine {
  /** `" "`, `"+"`, `"-"`. */
  kind: string;
  /** Ses numéros avant et après ; 0 quand la ligne n'y est pas. */
  old: number;
  new: number;
  text: string;
}

export interface Hunk {
  header: string;
  lines: DiffLine[];
}

export interface DiffFile {
  path: string;
  /** `added`, `modified`, `deleted`. */
  status: string;
  status_label: string;
  insertions: number;
  deletions: number;
  binary: boolean;
  /** Ses passages ne sont pas tous là (la borne du diff) : il se relit seul par `path=`. */
  cut: boolean;
  /** Un fichier caché : son chemin et ses comptes, sans ses passages (`why`). */
  hidden?: boolean;
  why?: string;
  hunks: Hunk[];
}

export interface Diff {
  files: DiffFile[];
  cut: boolean;
  cut_label: string;
  insertions: number;
  deletions: number;
  /** Faux : elle ne lit pas ses fichiers (`files_why`), et `files` est vide. */
  files_readable: boolean;
  files_why: string;
}

export interface CodeSummary {
  has_repo: boolean;
  base: string;
  current: string;
  remote: { has: boolean; web: string; branch: string; flow: string; by_pulls: boolean; synced_at: number };
  rights: { files: boolean; merge: boolean };
  counts: { commits: number; branches: number; pulls_open: number; pulls_ready: number; issues_open: number; checks_failed: number };
  last_commit: Commit | null;
}

export interface TreeEntry {
  path: string;
  name: string;
  /** `dir`, `file`, `link`, `module`. */
  kind: string;
  kind_label: string;
  size: number;
}

export interface Tree {
  ref: string;
  path: string;
  parent: string | null;
  readme: string;
  /** Les entrées cachées qu'il tait. */
  hidden?: number;
  items: TreeEntry[];
  last_commit: Commit | null;
}

export interface Blob {
  ref: string;
  sha: string;
  path: string;
  name: string;
  kind: string;
  kind_label: string;
  size: number;
  binary: boolean;
  too_big: boolean;
  readable: boolean;
  /** Pourquoi il ne dit pas son contenu, en mots. */
  why: string;
  text: string;
  lines: number;
  last_commit: Commit | null;
  history: Commit[];
  history_total: number;
  url: string;
}

export interface CommitPage {
  ref: string;
  total: number;
  page: number;
  size: number;
  items: Commit[];
}

export interface CommitDetail extends Diff {
  commit: Commit & { body: string; parents: string[] };
  linked: Linked;
}

export interface Branch extends Linked {
  name: string;
  base: boolean;
  current: boolean;
  ahead: number;
  behind: number;
  head: Commit;
}

export interface BranchList {
  base: string;
  items: Branch[];
}

export interface BranchDetail extends Diff {
  branch: Branch;
  commits: Commit[];
}

export interface PullPage {
  total: number;
  page: number;
  size: number;
  items: PullLine[];
}

export interface PullFull extends PullLine {
  /** Le commit au bout de sa branche : celui à nommer pour la fusionner. */
  head: string;
  fork: string;
  done_when: string;
  result: string;
  milestones: Milestone[];
  /** Le dernier mot de l'hôte. */
  said: OutsideText | null;
}

export interface PullDetail extends Diff {
  pull: PullFull;
  commits: Commit[];
}

/** Un échange venu de l'hôte ; `from_here` : publié d'ici, sous le compte du jeton. */
export interface Remark {
  id: number | string;
  at: number;
  from_here: boolean;
  outside: boolean;
  account: OutsideText | null;
  text: string;
}

export interface CheckRun {
  name: OutsideText | null;
  state: string;
  state_label: string;
  started: number;
  at: number;
  seconds: number;
}

/** Les vérifications d'un commit, relues chez l'hôte. */
export interface HostChecks {
  sha: string;
  state: string;
  state_label: string;
  error: string;
  at: number;
  read_at: number;
  runs: CheckRun[];
  failed: OutsideText[];
  log: { name: OutsideText | null; tail: OutsideText | null } | null;
}

/** Ce que l'hôte dit d'une pull request, maintenant. */
export interface PullHost {
  number: number;
  error: string;
  title: OutsideText | null;
  body: OutsideText | null;
  head: string;
  mergeable: boolean | null;
  state?: string;
  at?: number;
  read_at?: number;
  talk: Remark[];
  checks: HostChecks | null;
}

export interface Issue {
  number: number;
  url: string;
  /** `null` : elle ne se lit pas d'ici (`veiled`). */
  title: OutsideText | null;
  veiled: string;
  veiled_label: string;
  /** `open`, `closed`, ou vide si l'hôte ne l'a pas dite. */
  state: string;
  state_label: string;
  dropped: boolean;
  labels: OutsideText[];
  comments: number;
  at: number;
  from_here: boolean;
  account: OutsideText | null;
  ticket: LinkedTicket | null;
}

export interface IssuePage {
  total: number;
  page: number;
  size: number;
  error: string;
  items: Issue[];
}

export interface IssueDetail extends Issue {
  error: string;
  body: OutsideText | null;
  talk: Remark[];
}

/** Les vérifications que le moteur suit, pour le commit d'une pull request. */
export interface TrackedChecks extends ChecksBrief {
  commit: Commit | null;
  branch: string;
  objective: LinkedObjective | null;
  pull: PullBrief | null;
}

export interface CommitChecks extends HostChecks {
  commit: Commit;
  linked: Linked;
}

function query(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") q.set(key, String(value));
  }
  const said = q.toString();
  return said ? `?${said}` : "";
}

const root = (id: number): string => `${MOI}/projets/${id}/code`;

export function fetchCode(id: number): Promise<CodeSummary> {
  return getJson<CodeSummary>(root(id));
}

/** Un dossier à une référence, un niveau à la fois. */
export function fetchTree(id: number, ref: string, path: string): Promise<Tree> {
  return getJson<Tree>(`${root(id)}/fichiers${query({ ref, path })}`);
}

export function fetchBlob(id: number, ref: string, path: string): Promise<Blob> {
  return getJson<Blob>(`${root(id)}/fichier${query({ path, ref })}`);
}

/** L'histoire d'une branche, ou de toutes sans `ref`, du plus récent. */
export function fetchCommits(id: number, ref: string, page = 1, size = 100): Promise<CommitPage> {
  return getJson<CommitPage>(`${root(id)}/commits${query({ ref, page: page > 1 ? page : undefined, size })}`);
}

/** Un commit et son diff ; `path` : un seul fichier, relu en entier (un fichier coupé). */
export function fetchCommit(id: number, sha: string, path = ""): Promise<CommitDetail> {
  return getJson<CommitDetail>(`${root(id)}/commit${query({ sha, path })}`);
}

export function fetchBranches(id: number): Promise<BranchList> {
  return getJson<BranchList>(`${root(id)}/branches`);
}

export function fetchBranch(id: number, name: string): Promise<BranchDetail> {
  return getJson<BranchDetail>(`${root(id)}/branche${query({ name })}`);
}

export function fetchPulls(id: number): Promise<PullPage> {
  return getJson<PullPage>(`${root(id)}/pulls${query({ size: 100 })}`);
}

/** Une pull request : par son numéro, ou par son objectif tant qu'elle n'en a pas (`number` : 0). */
export function fetchPull(id: number, number: number, objective = 0, path = ""): Promise<PullDetail> {
  return getJson<PullDetail>(`${root(id)}/pull${query(number ? { number, path } : { objective, path })}`);
}

export function fetchPullHost(id: number, number: number): Promise<PullHost> {
  return getJson<PullHost>(`${root(id)}/pull/hote${query({ number })}`);
}

export function fetchIssues(id: number): Promise<IssuePage> {
  return getJson<IssuePage>(`${root(id)}/issues${query({ size: 100 })}`);
}

export function fetchIssue(id: number, number: number): Promise<IssueDetail> {
  return getJson<IssueDetail>(`${root(id)}/issue${query({ number })}`);
}

export function fetchChecks(id: number): Promise<{ items: TrackedChecks[] }> {
  return getJson<{ items: TrackedChecks[] }>(`${root(id)}/ci`);
}

export function fetchCommitChecks(id: number, sha: string): Promise<CommitChecks> {
  return getJson<CommitChecks>(`${root(id)}/ci/commit${query({ sha })}`);
}
