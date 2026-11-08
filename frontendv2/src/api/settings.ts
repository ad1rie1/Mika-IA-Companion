/**
 * Paramètres, par l'API par personne (`protocole-moi.md` § 7, et les listes des § 3 et 4) : son compte, ses boîtes
 * aux lettres et ses comptes Teams, et comment part ce que Mika prépare depuis chacun (ADR 0207). Ce qu'une personne
 * branche est à elle (ADR 0185, 0186) ; un secret ne repart jamais (laissé vide, il reste celui qui est gardé).
 *
 * Les listes des boîtes et des comptes sont lues ici, telles quelles, pour Paramètres et Outils : les écrans Mail et
 * Teams ont leurs propres clients.
 */
import { getJson, MOI, sendJson, type Done } from "./moi";
import type { Rules } from "./rights";

// ── Son compte ───────────────────────────────────────────────────────

export function saveName(name: string): Promise<Done> {
  return sendJson(`${MOI}/account/name`, { name });
}

/** Changer son mot de passe : toutes ses sessions se ferment (`relogin`), on se reconnecte. */
export function savePassword(current: string, password: string): Promise<Done & { relogin?: boolean }> {
  return sendJson(`${MOI}/account/password`, { current, password });
}

// ── Ses boîtes ───────────────────────────────────────────────────────

/** `proprietaire` : la sienne ; sinon ce qu'on lui en partage (ADR 0188). */
export type BoxLevel = "proprietaire" | "lire" | "preparer" | "servir";

export interface BoxFolder {
  name: string;
  label: string;
  role: string;
  polled: boolean;
  total: number;
  unseen: number;
}

export interface Box {
  key: string;
  name: string;
  address: string;
  level: BoxLevel | string;
  ready: boolean;
  can_send: boolean;
  enabled: boolean;
  signature: string;
  last_poll: number;
  error: string;
  drafts_waiting: number;
  folders: BoxFolder[];
  /** Une boîte partagée se montre à son nom (« Boîte de Léa »). */
  owner_name?: string;
  /** « À toi » : commune à ses propriétaires (elle ne se partage pas à l'une d'elles). */
  common?: boolean;
}

export interface Boxes {
  plugged: boolean;
  read_on_open: string;
  boxes: Box[];
}

/** Ce qu'une personne règle d'une boîte (`MailAccount`, sans `owner` ni `shares`). */
export interface BoxValues {
  label: string;
  address: string;
  enabled: boolean;
  auth: "password" | "microsoft";
  imap_host: string;
  imap_port: number;
  imap_ssl: boolean;
  user: string;
  password?: string;
  folders: string[];
  sync_all: boolean;
  since_days: number;
  oauth_client_id: string;
  oauth_tenant: string;
  smtp_host: string;
  smtp_port: number;
  smtp_security: "starttls" | "ssl" | "none" | string;
  smtp_user: string;
  smtp_password?: string;
  save_sent: boolean;
  voice: "elle" | "assistante" | "proprietaire";
  display_name: string;
  sender_name: string;
  tone: string;
  instructions: string;
  signature: string;
}

/** Où en est la connexion Microsoft d'une boîte (ADR 0166). */
export interface SignIn {
  /** `connectee`, `en_attente` (un code à entrer chez Microsoft), `a_faire` */
  state: string;
  code: string;
  url: string;
  /** Jusqu'à quand le code vaut (ms). */
  until: number;
  error: string;
}

export interface BoxSettings {
  box: string;
  values: BoxValues;
  /** Un secret est gardé (jamais rendu). */
  secrets: { password: boolean; smtp_password: boolean };
  ready: boolean;
  can_send: boolean;
  microsoft: boolean;
  signin: SignIn | null;
  /** La règle de son canal : comment part ce qu'elle prépare (ADR 0207). */
  rules: SendRules;
}

export function fetchBoxes(): Promise<Boxes> {
  return getJson(`${MOI}/mail/boxes`);
}

export function fetchBox(box: string): Promise<BoxSettings> {
  return getJson(`${MOI}/mail/box?box=${encodeURIComponent(box)}`);
}

/** Sans `box` : une boîte nouvelle (sa clé tirée de son nom) ; avec : la régler. */
export function saveBox(values: Partial<BoxValues>, box = "", nonce = ""): Promise<Done & { box: string; ready: boolean }> {
  return sendJson(`${MOI}/mail/box/save`, box ? { box, values } : { values }, nonce);
}

export function removeBox(box: string): Promise<Done> {
  return sendJson(`${MOI}/mail/box/remove`, { box });
}

export function testBox(box: string): Promise<Done> {
  return sendJson(`${MOI}/mail/box/test`, { box });
}

/** Connecter une boîte Microsoft : un code à entrer chez Microsoft, que `fetchBox` donne ensuite (`signin`). */
export function connectMicrosoft(box: string): Promise<Done> {
  return sendJson(`${MOI}/mail/box/microsoft`, { box });
}

/** La relever sans attendre (`protocole-moi.md` § 3). */
export function pollBox(box: string): Promise<Done> {
  return sendJson(`${MOI}/mail/poll`, { box });
}

// ── Ses comptes Teams ────────────────────────────────────────────────

export interface ExtensionKey {
  /** Le début de la clé, jamais la clé. */
  hint: string;
  created_at: number;
}

export interface TeamsAccount {
  key: string;
  name: string;
  level: BoxLevel | string;
  enabled: boolean;
  /** Le dernier lot de son extension (ms ; 0 : jamais). */
  last_batch: number;
  /** Son nom dans Teams. */
  self_name: string;
  extension_key: ExtensionKey | null;
  drafts_waiting: number;
  owner_name?: string;
  /** « À toi » : commun à ses propriétaires (il ne se partage pas à l'une d'elles). */
  common?: boolean;
}

export interface TeamsAccounts {
  plugged: boolean;
  /** Teams actif. */
  enabled: boolean;
  accounts: TeamsAccount[];
}

export interface TeamsValues {
  label: string;
  enabled: boolean;
  display_name: string;
  tone: string;
  instructions: string;
  sign: boolean;
  signature: string;
}

export interface TeamsSettings {
  account: string;
  values: TeamsValues;
  extension_key: ExtensionKey | null;
  /** La règle de son canal : comment part ce qu'elle prépare (ADR 0207). */
  rules: SendRules;
}

export function fetchTeamsAccounts(): Promise<TeamsAccounts> {
  return getJson(`${MOI}/teams/accounts`);
}

export function fetchTeamsAccount(account: string): Promise<TeamsSettings> {
  return getJson(`${MOI}/teams/account?account=${encodeURIComponent(account)}`);
}

/** Sans `account` : un compte nouveau ; avec : le régler. */
export function saveTeamsAccount(values: Partial<TeamsValues>, account = "", nonce = ""): Promise<Done & { account: string }> {
  return sendJson(`${MOI}/teams/account/save`, account ? { account, values } : { values }, nonce);
}

/** Une clé neuve pour son extension, rendue cette fois seulement ; l'ancienne ne vaut plus. */
export function newExtensionKey(account: string): Promise<Done & { key: string }> {
  return sendJson(`${MOI}/teams/account/key`, { account });
}

export function revokeExtensionKey(account: string): Promise<Done> {
  return sendJson(`${MOI}/teams/account/revoke`, { account });
}

/** Retirer un de ses comptes Teams : sa clé part avec lui, et ce que son extension avait apporté (conversations,
 *  messages, brouillons) s'efface ; ce qu'elle en a appris reste dans sa vie. */
export function removeTeamsAccount(account: string): Promise<Done> {
  return sendJson(`${MOI}/teams/account/remove`, { account });
}

// ── Comment part ce qu'elle prépare (ADR 0207) ───────────────────────

/**
 * La règle du canal d'un de ses comptes (`courrier:<boîte>`, `teams:<compte>`), telle que le courrier et Teams la
 * lisent : la sienne, sinon celle de tout le canal (`common`, réglée dans la console), sinon celle de départ.
 * `version` : son empreinte, à renvoyer pour la changer.
 */
export interface SendRules extends Rules {
  common: boolean;
  version: string;
}

/** Ce qu'elle en règle, ligne par ligne et par défaut : préparer d'elle-même, comment ça part. */
export interface SendChoice {
  prepare: boolean;
  /** `seule`, `accord`, `brouillon` (Teams seulement), `non` */
  reply: string;
}

export interface SendRulesUpdate {
  canal: string;
  version: string;
  lines: SendChoice[];
  default: SendChoice;
}

/** Régler comment part ce qu'elle prépare depuis un de ses comptes ; une règle changée ailleurs entre-temps : 409. */
export function saveSendRules(update: SendRulesUpdate): Promise<Done> {
  return sendJson(`${MOI}/rules`, { ...update });
}
