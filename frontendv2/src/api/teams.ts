/**
 * Teams, par l'API par personne (`backendv2/docs/protocole-moi.md` § 4) : ses comptes, ses conversations et leurs
 * fils, les réponses que Mika y prépare ; écrire soi-même (ADR 0189), lui demander une réponse, décider des siennes.
 * Une conversation se désigne par sa clé (`<compte>~<identifiant>`, l'identifiant seul pour `principal`), un message
 * par sa référence. Les instants sont en millisecondes.
 */
import type { Level } from "./mail";
import { query } from "./mail";
import { apiUrl, getJson, MOI, sendJson, type Done } from "./moi";

/** Les bornes des chaînes que l'API reçoit (`app/me/teams.py`, en caractères) : au-delà, elle refuse (400, `fields`). */
export const TEAMS_LIMITS = {
  body: 4000,
  note: 500,
  instruction: 4000,
  /** `q` de `/teams/conversations`. */
  search: 100,
} as const;

export interface TeamsAccount {
  key: string;
  name: string;
  level: Level;
  enabled: boolean;
  /** Le dernier lot de son extension (0 : jamais) : quand elle a eu du neuf à pousser. */
  last_batch: number;
  /** La dernière fois que son extension s'est manifestée — un relevé, la connexion en direct, un lot (0 : jamais
   *  depuis le démarrage du serveur). C'est sur lui qu'on juge si elle est là ; absent d'un serveur d'avant. */
  last_seen?: number;
  /** Son nom dans Teams. */
  self_name: string;
  /** La clé de son extension, jamais en clair (`null` : pas de clé, ou un compte partagé). */
  extension_key: { hint: string; created_at: number } | null;
  drafts_waiting: number;
  /** Un compte partagé : le nom de son propriétaire ; vide pour le sien. */
  owner_name: string;
  /** « À toi » : commun à ses propriétaires. */
  common?: boolean;
}

export interface AccountsReply {
  plugged: boolean;
  /** Teams actif. */
  enabled: boolean;
  /** L'extension à télécharger (ADR 0246) ; `null` : elle n'est pas à côté du serveur. */
  extension: { version: string } | null;
  accounts: TeamsAccount[];
}

export type ConversationKind = "dm" | "group" | "channel" | "meeting" | "other";

export interface TeamsMessage {
  ref: string;
  author: string;
  author_id: string;
  at: number;
  text: string;
  /** Écrit par la personne du compte. */
  own: boolean;
  mentions_me: boolean;
  /** Ses images (ADR 0258), sans leurs octets : `teamsImageUrl` les sert ; `seen` : ce que Mika y a vu. */
  images?: TeamsImage[];
  /** Ses réactions (ADR 0300), dans l'ordre de Teams ; absent d'un moteur qui ne les dit pas. */
  reactions?: TeamsReaction[];
  /** L'adresse de la photo de profil de son auteur (ADR 0300 : `teamsPhotoUrl`), vide sans photo. */
  photo?: string;
  /** Le message qu'il cite (ADR 0305) — son texte ne le reprend pas ; `null` : aucun. */
  quote?: TeamsQuote | null;
}

/** Le message qu'un message cite (ADR 0305). */
export interface TeamsQuote {
  author: string;
  author_id: string;
  /** Un extrait (ce que Teams en a gardé). */
  preview: string;
  /** Son heure (ms). */
  at: number;
  /** Sa référence chez Mika, pour y aller ; vide : elle ne l'a pas. */
  ref: string;
}

/** Une réaction à un message (ADR 0300). */
export interface TeamsReaction {
  /** Sa clé dans Teams (`like`, `heart`, `1f44f_clappinghands`…). */
  key: string;
  /** Son emoji ; vide quand le serveur ne le connaît pas : on montre la clé. */
  emoji: string;
  count: number;
  /** La personne du compte en est : toi sur un compte à toi, son propriétaire sur un compte qu'on te partage. */
  mine: boolean;
  /** Qui l'a posée, sous le nom que le compte lui connaît (dix au plus, sans la personne du compte). */
  names: string[];
}

export interface TeamsImage {
  id: string;
  position: number;
  mime: string;
  seen: string;
}

/** Une réponse de Mika en chemin dans une conversation. */
export interface UnderWay {
  state: ReplyState;
  draft: string;
}

export interface Conversation {
  key: string;
  account: string;
  /** Son nom : un tête-à-tête, l'autre personne (sinon la liste des membres que donne Teams) ; une autre, celui de
   *  Teams (vide sans titre). */
  title: string;
  kind: ConversationKind;
  /** Sa photo (ADR 0300) : celle de l'autre personne d'un tête-à-tête, même quand le dernier message est le tien ;
   *  vide pour une autre conversation, ou sans photo. */
  photo?: string;
  last_at: number;
  messages: number;
  last: TeamsMessage | null;
  her: UnderWay | null;
}

/**
 * `attend` ta décision, `approuve`, `en_file` (pour l'extension), `pose` (dans la zone de saisie de Teams),
 * `parti`, `inutilise` (pas servie à temps), `refuse`, `expire`, `echec`.
 */
export type ReplyState = "attend" | "approuve" | "en_file" | "pose" | "parti" | "inutilise" | "refuse" | "expire" | "echec";

/** Comment part ce qu'elle prépare : posé dans Teams, après ton accord, seule. */
export type ReplyMode = "brouillon" | "validation" | "autonome";

export interface Reply {
  id: string;
  account: string;
  conversation: string;
  title: string;
  in_reply_to: string;
  state: ReplyState;
  mode: ReplyMode;
  at: number;
  decided_at: number;
  by: string;
  note: string;
  /** Demandée (« Préremplir avec Mika »), sinon d'elle-même. */
  asked: boolean;
  /** Retouchée (ta version a remplacé la sienne). */
  edited: boolean;
  /** Une carte d'accord : jusqu'à quand elle vaut (0 : sans délai). */
  expires: number;
  /** La personne du compte a répondu autrement dans la discussion : elle ne partira pas (ADR 0199) — refusée, ou
   *  sur le point de l'être ; absent d'un moteur qui ne le dit pas. */
  answered?: boolean;
  body: string;
  /** Ce qui est vraiment parti. */
  sent_text: string;
  to_fill: boolean;
  /** Tant qu'elle attend : exactement ce qui partira (signature comprise). */
  preview: { text: string; digest: string; blocked: string } | null;
}

/**
 * Ce que devient un message que tu as écrit toi-même (ADR 0189) tant qu'il n'est pas revenu dans le fil : `en_file`
 * (l'extension le relèvera), `envoi` (une extension l'envoie), `pose` (posé dans la zone de saisie de Teams) ; puis,
 * pendant 24 h, `inutilise` (jamais parti : l'extension ne l'a pas relevé à temps) ou `echec`.
 */
export type OwnPendingState = "en_file" | "envoi" | "pose" | "inutilise" | "echec";

export interface OwnPending {
  id: string;
  body: string;
  /** Quand tu l'as écrit (ms). */
  at: number;
  state: OwnPendingState | string;
  /** Qui l'a écrit (son adresse `user_N`). */
  by: string;
  /** Pourquoi il n'est pas parti, quand le moteur le dit. */
  reason?: string;
}

export interface Thread {
  key: string;
  account: string;
  title: string;
  kind: ConversationKind;
  /** Sa photo, comme dans la liste (`Conversation.photo`). */
  photo?: string;
  messages: TeamsMessage[];
  /** Il y a des messages plus anciens (`before`). */
  more: boolean;
  replies: Reply[];
  /** Ce que tu y as écrit toi-même et qui n'est pas (encore) dans le fil, du plus ancien au plus récent ; absent
   *  d'un moteur qui ne le dit pas. */
  pending?: OwnPending[];
  under_way: boolean;
  asked: boolean;
}

export interface PrefillReply extends Done {
  /** Une réponse déjà en chemin dans cette conversation. */
  draft: string;
  asked: boolean;
}

const T = `${MOI}/teams`;

/** L'adresse des octets d'une image d'un message (derrière la connexion). */
export function teamsImageUrl(message: string, image: string): string {
  return apiUrl(`${T}/image${query({ message, image })}`);
}

/** Le début de l'adresse d'une photo de profil (ADR 0300), telle que l'API la donne (`photo`). */
const PHOTO_PATH = `${T}/photo?`;

/**
 * L'adresse à charger d'une photo de profil (ADR 0300) : celle que l'API donne (`photo` d'un message, d'une
 * conversation, d'un contact), sur le serveur et derrière la connexion, comme les images des messages. Toute autre
 * adresse ne se charge pas (vide : les initiales).
 */
export function teamsPhotoUrl(path: string | null | undefined): string {
  return path && path.startsWith(PHOTO_PATH) ? apiUrl(path) : "";
}

export function fetchAccounts(): Promise<AccountsReply> {
  return getJson<AccountsReply>(`${T}/accounts`);
}

export async function fetchConversations(opts: { account?: string; q?: string; size?: number } = {}): Promise<Conversation[]> {
  return (await getJson<{ items: Conversation[] }>(`${T}/conversations${query({ ...opts })}`)).items;
}

/** Le fil, les plus récents ; `before` : avant cet instant (ms). */
export function fetchThread(conversation: string, opts: { before?: number; size?: number } = {}): Promise<Thread> {
  return getJson<Thread>(`${T}/thread${query({ conversation, ...opts })}`);
}

export async function fetchReplies(): Promise<Reply[]> {
  return (await getJson<{ items: Reply[] }>(`${T}/replies`)).items;
}

/** Ton message (ADR 0189) : en file pour l'extension du compte, qui l'envoie sous ton nom. */
export function sendMessage(conversation: string, body: string, replyTo = "", nonce = ""): Promise<Done> {
  return sendJson(`${T}/send`, replyTo ? { conversation, body, reply_to: replyTo } : { conversation, body }, nonce);
}

export function prefill(message: string, instruction = ""): Promise<PrefillReply> {
  return sendJson<PrefillReply>(`${T}/prefill`, instruction ? { message, instruction } : { message });
}

export function sendReply(id: string, seen: string, nonce = ""): Promise<Done> {
  return sendJson(`${T}/reply/send`, { id, seen }, nonce);
}

export function editReply(id: string, body: string): Promise<Done> {
  return sendJson(`${T}/reply/edit`, { id, body });
}

export function refuseReply(id: string, note = ""): Promise<Done> {
  return sendJson(`${T}/reply/refuse`, { id, note });
}

export function redoReply(id: string, instruction: string): Promise<Done> {
  return sendJson(`${T}/reply/redo`, { id, instruction });
}
