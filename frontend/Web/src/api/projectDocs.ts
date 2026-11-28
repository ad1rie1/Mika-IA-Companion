/**
 * La documentation d'un projet (`/api/moi/projets/<id>/documentation…`, ADR 0289) et ses décisions techniques
 * (`…/decisions`, ADR 0290) ; le contrat : `backend/docs/protocole-moi.md` § 11. Un espace à part du dépôt : des pages
 * en Markdown, leurs versions, des images. Enregistrer une page nomme la version lue (`base`) : si elle a changé
 * depuis, le serveur refuse (409) et rien n'est écrasé.
 */
import { apiUrl, getJson, MOI, sendForm, type Done } from "./moi";
import type { AuthorKind } from "./projects";

/** Qui a écrit une version ou ajouté une image, et par où. */
export interface Written {
  author_kind: AuthorKind | string;
  author: string;
  /** `run` (elle, pendant une exécution), `web` (une personne, dans le navigateur), `mcp` (un outil), `console`. */
  via: string;
  via_label: string;
  /** Par MCP : le nom du jeton que l'outil présentait (vide si elle n'a pas le droit de le savoir). */
  tool: string;
}

export interface DocPage extends Written {
  path: string;
  name: string;
  folder: string;
  title: string;
  version: number;
  at: number;
  created_at: number;
  chars: number;
  /** Les images qu'elle cite, par leur nom. */
  images: string[];
}

export interface DocImage extends Written {
  name: string;
  path: string;
  size: number;
  mime: string;
  at: number;
  /** Les pages qui la citent, par leur chemin. */
  used_by: string[];
}

export interface DocLimits {
  page_chars: number;
  pages: number;
  versions: number;
  path_chars: number;
  depth: number;
  word_chars: number;
  image_bytes: number;
  images: number;
  space_bytes: number;
  image_kinds: string[];
}

export interface DocSpace {
  project: number;
  rights: { read: boolean; write: boolean };
  limits: DocLimits;
  pages: DocPage[];
  folders: string[];
  images: DocImage[];
  space_used: number;
}

export interface DocPageText extends DocPage {
  text: string;
  /** Son texte a été oublié. */
  forgotten: boolean;
  can: { write: boolean };
}

export interface DocVersion extends Written {
  n: number;
  at: number;
  /** Le mot sur ce qui a changé. */
  word: string;
  /** La version reprise ; 0 sinon. */
  restored: number;
  chars: number;
  current: boolean;
}

export interface DocHistory {
  path: string;
  version: number;
  kept: number;
  versions: DocVersion[];
}

export interface DocVersionText extends DocVersion {
  path: string;
  text: string;
  forgotten: boolean;
}

export interface DocFound extends DocPage {
  excerpt: string;
}

export interface DecisionCan {
  modify: boolean;
  replace: boolean;
  withdraw: boolean;
  restore: boolean;
  why: string;
}

export interface Decision {
  number: number;
  title: string;
  choice: string;
  /** `active` (en vigueur), `withdrawn`, `superseded`. */
  status: string;
  status_label: string;
  author_kind: string;
  author: string;
  at: number;
  /** Celle qu'elle remplace, celle qui la remplace ; 0 : aucune. */
  replaces: number;
  replaced_by: number;
  objective: number;
  can: DecisionCan;
}

export interface DecisionFull extends Decision {
  context: string;
  /** Les options écartées : un seul texte. */
  options: string;
  reason: string;
}

export interface DecisionList {
  total: number;
  in_force: number;
  can: boolean;
  why: string;
  items: Decision[];
}

const root = (id: number): string => `${MOI}/projets/${id}/documentation`;
const q = (params: Record<string, string | number>): string => `?${new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()}`;

export function fetchDocs(id: number): Promise<DocSpace> {
  return getJson<DocSpace>(root(id));
}

export function fetchDocPage(id: number, path: string): Promise<DocPageText> {
  return getJson<DocPageText>(`${root(id)}/page${q({ path })}`);
}

export function fetchDocHistory(id: number, path: string): Promise<DocHistory> {
  return getJson<DocHistory>(`${root(id)}/historique${q({ path })}`);
}

export function fetchDocVersion(id: number, path: string, n: number): Promise<DocVersionText> {
  return getJson<DocVersionText>(`${root(id)}/version${q({ path, n })}`);
}

export function searchDocs(id: number, words: string): Promise<{ q: string; items: DocFound[] }> {
  return getJson<{ q: string; items: DocFound[] }>(`${root(id)}/chercher${q({ q: words })}`);
}

/**
 * L'adresse des octets d'une image de l'espace : servie par l'API, à qui peut lire la documentation, comme une image
 * et rien d'autre. C'est la seule adresse d'image qu'une page fait charger.
 */
export function docImageUrl(id: number, name: string): string {
  return apiUrl(`${root(id)}/image${q({ name })}`);
}

export interface PageSaved extends Done {
  path: string;
  version: number;
}

/**
 * Enregistrer une page : une version de plus, partie de `base` (la version lue ; 0 : une page nouvelle). En
 * `multipart/form-data` — un corps JSON est borné à 64 Kio, une page à 100 000 caractères. Un refus lève `ApiError`
 * (409 : la page a changé depuis la lecture, avec les mots du serveur).
 */
export function saveDocPage(id: number, page: { path: string; text: string; word: string; base: number }, nonce: string): Promise<PageSaved> {
  // `base` part en texte : un zéro (une page nouvelle) est une valeur, pas une absence
  return sendForm<PageSaved>(`${root(id)}/page/enregistrer`, { path: page.path, text: page.text, word: page.word, base: String(page.base) }, [], nonce);
}

export interface ImageSaved extends Done {
  name: string;
  path: string;
}

/** Téléverser une image : elle rejoint les images de l'espace, sous le nom que le serveur rend. */
export function uploadDocImage(id: number, file: File, nonce: string): Promise<ImageSaved> {
  return sendForm<ImageSaved>(`${root(id)}/image/televerser`, {}, [file], nonce);
}

const decisions = (id: number): string => `${MOI}/projets/${id}`;

/** Ses décisions techniques : toutes (`all`), pour voir aussi celles qu'une autre remplace. */
export function fetchDecisions(id: number): Promise<DecisionList> {
  return getJson<DecisionList>(`${decisions(id)}/decisions${q({ status: "all" })}`);
}

export function fetchDecision(id: number, number: number): Promise<DecisionFull> {
  return getJson<DecisionFull>(`${decisions(id)}/decision${q({ number })}`);
}
