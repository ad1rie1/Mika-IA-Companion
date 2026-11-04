/**
 * Ses services MCP (ADR 0192 ; `protocole-moi.md` § 8) : ceux qu'elle a branchés, à elle — distants, par une adresse
 * https —, leur état, leurs outils (coupés tant qu'on ne les a pas choisis, ADR 0129) et leurs lignes d'accès. Ce que
 * Mika en offre reste dans la matrice des droits (`rights.ts`).
 */
import { getJson, MOI, sendJson, type Done } from "./moi";

/** `jamais`, `connecte`, `erreur`, `panne`, `incomplet`, `inactif` */
export type ServiceState = "jamais" | "connecte" | "erreur" | "panne" | "incomplet" | "inactif";
/** Ce qu'on choisit pour un outil : coupé, servi en lecture, servi en action ; vide : jamais choisi. */
export type ToolChoice = "non" | "lecture" | "action";

export interface ServiceTool {
  remote: string;
  /** Son nom chez Mika (vide : jamais regardé). */
  name: string;
  description: string;
  choice: ToolChoice | "";
  new: boolean;
  changed: boolean;
}

/** Une ligne d'accès, en codes et en mots. */
export interface AccessLine {
  who: string;
  when: string;
  read: string;
  act: string;
  keep: string;
  read_words: string;
  act_words: string;
  keep_words: string;
  tools: string[];
}

export interface Service {
  name: string;
  purpose: string;
  when_to_use: string;
  enabled: boolean;
  url: string;
  /** Des en-têtes sont gardés (jamais rendus). */
  headers: boolean;
  state: ServiceState | string;
  detail: string;
  tools: ServiceTool[];
  access: AccessLine[];
  default: AccessLine | null;
}

export interface Services {
  plugged: boolean;
  items: Service[];
}

export interface PlugForm {
  name: string;
  purpose: string;
  url: string;
  headers?: string;
  when_to_use?: string;
}

export interface ServiceValues {
  purpose: string;
  when_to_use: string;
  enabled: boolean;
  url: string;
  /** Laissés vides, les en-têtes gardés restent. */
  secret_headers: string;
}

export function fetchServices(): Promise<Services> {
  return getJson(`${MOI}/mcp/services`);
}

export function plugService(form: PlugForm, nonce = ""): Promise<Done & { name: string }> {
  return sendJson(`${MOI}/mcp/plug`, { ...form }, nonce);
}

/** Rouvrir une session et relire ses outils : `ok` faux quand le service ne répond pas. */
export function testService(name: string): Promise<{ ok: boolean; message: string }> {
  return sendJson(`${MOI}/mcp/test`, { name });
}

export function chooseTools(name: string, choices: Record<string, ToolChoice>): Promise<Done & { decided?: unknown }> {
  return sendJson(`${MOI}/mcp/tools`, { name, choices });
}

export function saveService(name: string, values: Partial<ServiceValues>): Promise<Done> {
  return sendJson(`${MOI}/mcp/save`, { name, values });
}

export function removeService(name: string): Promise<Done> {
  return sendJson(`${MOI}/mcp/remove`, { name });
}
