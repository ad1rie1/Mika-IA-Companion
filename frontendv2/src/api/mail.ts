/**
 * Mail, par l'API par personne (`backendv2/docs/protocole-moi.md` § 3) : ses boîtes et leurs dossiers, une page de
 * messages, un mail entier, ses brouillons à relire, ses envoyés, ses correspondants ; écrire, répondre, transférer,
 * ranger, lui demander une réponse, décider de ses brouillons. Les instants sont en millisecondes (0 : jamais).
 */
import { apiUrl, getJson, MOI, sendJson, type Done } from "./moi";

/**
 * Les bornes des chaînes que l'API reçoit (`app/moi/mail.py`, en caractères) : au-delà, elle refuse (400, avec
 * `fields: {"<nom>": "N caractères au plus"}`) — elle ne coupe jamais. Le client les tient d'avance (`maxlength`, un
 * envoi trop long ne part pas). `recipients` vaut pour `to` comme pour `cc`.
 */
export const MAIL_LIMITS = {
  recipients: 300,
  subject: 200,
  body: 20_000,
  note: 500,
  instruction: 4000,
  /** `q` de `/mail/messages`. */
  search: 200,
  /** `q` de `/mail/contacts`. */
  contacts: 100,
} as const;

/** Son niveau sur une boîte : la sienne, ou ce qu'on lui en partage (ADR 0188). */
export type Level = "proprietaire" | "servir" | "preparer" | "lire";

/** Quand un mail ouvert devient lu (ADR 0175) : le client pose le geste `read` lui-même. */
export type ReadOnOpen = "jamais" | "aussitot" | "3s" | "10s";

export interface MailFolder {
  name: string;
  label: string;
  /** `inbox`, `sent`, `drafts`, `archive`, `junk`, `trash`, ou vide (un autre dossier). */
  role: string;
  /** Relevé par Mika : sinon, ses mails ne sont pas dans le cache. */
  polled: boolean;
  total: number;
  unseen: number;
}

export interface MailBox {
  key: string;
  name: string;
  address: string;
  level: Level;
  ready: boolean;
  can_send: boolean;
  enabled: boolean;
  signature: string;
  last_poll: number;
  error: string;
  drafts_waiting: number;
  folders: MailFolder[];
  /** Une boîte partagée : le nom de son propriétaire (« Boîte de Léa ») ; vide pour la sienne. */
  owner_name: string;
  /** « À toi » : commune à ses propriétaires. */
  common?: boolean;
}

export interface BoxesReply {
  plugged: boolean;
  read_on_open: ReadOnOpen;
  boxes: MailBox[];
}

export interface Person {
  name: string;
  address: string;
}

/** Ce qu'elle a fait d'un mail, à part de ton non-lu. */
export interface HerMark {
  noticed: boolean;
  important: boolean;
  needs_reply: boolean;
  /** Lu de son côté (`how` : « lu », « archivé », « corbeille »…). */
  read: boolean;
  how: string;
  /** Un brouillon d'elle qui attend (son identifiant). */
  draft: string;
  /** Une réponse qu'on lui a demandée, pas encore écrite. */
  asked: boolean;
  /** Ce qu'elle en a retenu (le mail entier seulement). */
  summary?: string;
}

export interface MailRow {
  ref: string;
  box: string;
  folder: string;
  from: Person;
  to: Person[];
  subject: string;
  snippet: string;
  date: number;
  /** Ton lu : le drapeau du serveur. */
  seen: boolean;
  flagged: boolean;
  answered: boolean;
  attachments: number;
  html: boolean;
  bulk: boolean;
  her: HerMark | null;
}

export interface MailPage {
  total: number;
  page: number;
  size: number;
  items: MailRow[];
}

export interface MailAttachment {
  part: string;
  name: string;
  mime: string;
  size: number;
}

export interface MailFull extends Omit<MailRow, "attachments"> {
  attachments: MailAttachment[];
  cc: Person[];
  reply_to: string;
  in_reply_to: string;
  body: string;
  complete: boolean;
  /** Parti d'une de ses boîtes (un envoi qu'elle sait, ou rangé dans « Envoyés »). */
  sent: boolean;
  /** Une copie reçue ailleurs que dans « Envoyés » (en copie à soi) : on y répond. */
  received?: boolean;
  images: { remote: boolean; shown: boolean };
}

export type DraftState = "attend" | "approuve" | "parti" | "refuse" | "echec";

/** Exactement ce qui partira (seulement tant qu'il attend). */
export interface DraftPreview {
  sender: string;
  to: string;
  cc: string;
  subject: string;
  text: string;
  /** À renvoyer pour l'envoyer tel qu'il a été lu. */
  digest: string;
  /** Pourquoi il ne peut pas partir tel quel (un `[À COMPLÉTER`). */
  blocked: string;
}

export interface MailDraft {
  id: string;
  box: string;
  state: DraftState;
  at: number;
  decided_at: number;
  by: string;
  note: string;
  /** Le mail auquel il répond (sa référence). */
  in_reply_to: string;
  original: { subject: string; from: string } | null;
  to: string;
  cc: string;
  subject: string;
  body: string;
  quote: boolean;
  edited: boolean;
  to_fill: boolean;
  preview: DraftPreview | null;
}

export interface SentMail {
  ref: string;
  box: string;
  to: Person[];
  cc: Person[];
  subject: string;
  snippet: string;
  date: number;
  /** Vide : elle, après un accord. */
  by: string;
  draft: string;
  attachments: number;
}

export interface Contact {
  address: string;
  name: string;
  received: number;
  sent: number;
  last: number;
}

/** « Où elle est passée » : ceux qu'elle a remarqués. */
export type MailState = "" | "unread" | "flagged" | "noticed";

export interface MessagesQuery {
  box?: string;
  folder?: string;
  q?: string;
  state?: MailState;
  page?: number;
  size?: number;
}

export type Gesture = "read" | "unread" | "archive" | "flag" | "unflag" | "trash";

export interface PrefillReply extends Done {
  /** Un brouillon d'elle qui attend déjà pour ce mail : la saisie le reprend. */
  draft: string;
  /** Elle l'écrira à son prochain moment de travail. */
  asked: boolean;
}

export interface Outgoing {
  to: string;
  cc?: string;
  subject: string;
  body: string;
}

/** `?a=1&b=…`, sans les valeurs vides. */
export function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "" || value === false) continue;
    q.set(key, value === true ? "1" : String(value));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

const M = `${MOI}/mail`;

export function fetchBoxes(): Promise<BoxesReply> {
  return getJson<BoxesReply>(`${M}/boxes`);
}

export function fetchMessages(q: MessagesQuery): Promise<MailPage> {
  return getJson<MailPage>(`${M}/messages${query({ ...q })}`);
}

export function fetchMessage(ref: string): Promise<MailFull> {
  return getJson<MailFull>(`${M}/message${query({ ref })}`);
}

export async function fetchDrafts(): Promise<MailDraft[]> {
  return (await getJson<{ items: MailDraft[] }>(`${M}/drafts`)).items;
}

export async function fetchSent(box = ""): Promise<SentMail[]> {
  return (await getJson<{ items: SentMail[] }>(`${M}/sent${query({ box })}`)).items;
}

export async function fetchContacts(q = "", size = 25, box = ""): Promise<Contact[]> {
  return (await getJson<{ items: Contact[] }>(`${M}/contacts${query({ q, box, size })}`)).items;
}

/** Le HTML d'un mail, purgé, à poser dans un `<iframe sandbox>` (ADR 0169) ; `images` : ses images distantes, cette fois. */
export function frameUrl(ref: string, images = false): string {
  return apiUrl(`${M}/frame${query({ ref, images })}`);
}

/** Une pièce jointe, toujours en téléchargement. */
export function fileUrl(ref: string, part: string): string {
  return apiUrl(`${M}/file${query({ ref, part })}`);
}

export function sendMail(box: string, mail: Outgoing, nonce = ""): Promise<Done> {
  return sendJson(`${M}/send`, { box, ...mail, cc: mail.cc ?? "" }, nonce);
}

export function replyMail(ref: string, mail: Outgoing & { quote: boolean }, nonce = ""): Promise<Done> {
  return sendJson(`${M}/reply`, { ref, ...mail, cc: mail.cc ?? "" }, nonce);
}

export function forwardMail(ref: string, mail: Outgoing & { attachments: boolean }, nonce = ""): Promise<Done> {
  return sendJson(`${M}/forward`, { ref, ...mail, cc: mail.cc ?? "" }, nonce);
}

export function tidy(refs: string[], gesture: Gesture): Promise<Done> {
  return sendJson(`${M}/tidy`, { refs, gesture });
}

export function prefill(ref: string, instruction = ""): Promise<PrefillReply> {
  return sendJson<PrefillReply>(`${M}/prefill`, instruction ? { ref, instruction } : { ref });
}

export function sendDraft(id: string, seen: string, nonce = ""): Promise<Done> {
  return sendJson(`${M}/draft/send`, { id, seen }, nonce);
}

export function editDraft(id: string, mail: Outgoing & { quote: boolean }): Promise<Done> {
  return sendJson(`${M}/draft/edit`, { id, ...mail, cc: mail.cc ?? "" });
}

export function refuseDraft(id: string, note = ""): Promise<Done> {
  return sendJson(`${M}/draft/refuse`, { id, note });
}

export function redoDraft(id: string, instruction: string): Promise<Done> {
  return sendJson(`${M}/draft/redo`, { id, instruction });
}

/** Les images distantes de cet expéditeur : toujours (`shown`), ou plus. */
export function showImages(ref: string, shown: boolean): Promise<Done> {
  return sendJson(`${M}/images`, { ref, shown });
}

export function pollBox(box: string): Promise<Done> {
  return sendJson(`${M}/poll`, { box });
}
