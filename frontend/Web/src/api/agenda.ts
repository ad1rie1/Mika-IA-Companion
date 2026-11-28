/**
 * Agenda, par l'API par personne (`backend/docs/protocole-moi.md` § 13, ADR 0309) : ses agendas — celui du système,
 * ceux qu'elle branche (Google, Outlook.com / Microsoft 365, CalDAV, un abonnement iCal), ceux qu'on lui partage — et
 * « L'agenda de Mika », sa mémoire montrée comme un agenda ; une période, un événement, chercher, ses invitations et ce
 * que Mika propose ; écrire, répondre, décider ; ses comptes (Paramètres › Agendas) ; le tableau de droits d'un agenda
 * (Outils › Droits). Les instants sont en millisecondes (UTC) avec le nom de leur fuseau ; ce qu'on écrit se dit
 * `AAAA-MM-JJTHH:MM` dans le fuseau de l'agenda, ou `AAAA-MM-JJ` avec `all_day`. Une occurrence se désigne par
 * `event` et `occurrence`.
 */
import { query } from "./mail";
import { getJson, MOI, sendJson, type Done } from "./moi";

const A = `${MOI}/agenda`;

/** Les sortes de compte. */
export type AgendaKind = "systeme" | "google" | "microsoft" | "caldav" | "ical" | "mika";
/** Ce qu'elle a d'un agenda : le sien, ou le niveau d'un partage. */
export type AgendaLevel = "proprietaire" | "lire" | "preparer" | "servir";
export type AgendaGroup = "mine" | "subscriptions" | "shared" | "mika";
/** « Mika te le rappelle » : non, 15 min, 30 min, 1 h, la veille au soir ; vide : le choix de l'agenda. */
export type MikaReminder = "" | "non" | "15" | "30" | "60" | "veille";
/** Un rappel du fournisseur : une notification de son application, ou un e-mail. */
export type AlertMethod = "notification" | "email";

export interface Alert {
  method: AlertMethod;
  minutes: number;
}

export interface Coded {
  code: string;
  label: string;
}

export interface AgendaShare {
  person: string;
  name: string;
  level: Exclude<AgendaLevel, "proprietaire">;
}

export interface AgendaCalendar {
  key: string;
  account: string;
  /** Celui qu'on lui voit : le nom donné dans Mika, sinon celui du fournisseur. */
  name: string;
  /** Le nom chez son fournisseur, quand on lui en a donné un autre ici (lot 6). */
  provider_name: string;
  kind: AgendaKind;
  kind_label: string;
  level: AgendaLevel;
  owner_name: string;
  group: AgendaGroup;
  /** Celle qu'elle a choisie (vide : `provider_color`). */
  color: string;
  provider_color: string;
  primary: boolean;
  /** Masqué : Mika ne s'en sert plus, la vue ne le montre pas. */
  hidden: boolean;
  /** Son compte est coché. */
  enabled: boolean;
  reminder: Exclude<MikaReminder, "">;
  reminder_set: MikaReminder;
  writable: boolean;
  read_only: boolean;
  can: { write: boolean; respond: boolean; settings: boolean; share: boolean; rights: boolean; remind: boolean; rename?: boolean };
  synced_at: number;
  /** Les rappels du fournisseur (lot 6) : combien un événement en garde (0 : aucun), si l'e-mail en est, et ceux de
   *  l'agenda chez lui (Google). */
  provider_reminders?: { max: number; email: boolean; defaults: Alert[] };
  /** Un agenda à elle : la panne de la dernière synchro de son compte, en mots. */
  error?: string;
  shares?: AgendaShare[];
}

export interface Calendars {
  plugged: boolean;
  /** Le fuseau du serveur : une période et ce qu'on écrit se lisent à son heure. */
  zone: string;
  calendars: AgendaCalendar[];
  colors: Coded[];
  reminders: Coded[];
}

export interface AgendaPerson {
  address: string;
  name: string;
  person: string;
  response: "" | "attente" | "oui" | "peut" | "non";
  optional: boolean;
  me: boolean;
}

export interface AgendaItem {
  event: number;
  /** Sa clé dans la série (vide : un événement simple, ou la série). */
  occurrence: string;
  uid: string;
  calendar: string;
  title: string;
  /** Un événement privé d'une autre personne : « Occupé », son créneau seul. */
  masked: boolean;
  start: number;
  end: number;
  all_day: boolean;
  first_day: string;
  last_day: string;
  zone: string;
  location: string;
  description: string;
  conference: string;
  status: "confirme" | "provisoire" | "annule";
  busy: boolean;
  private: boolean;
  recurring: boolean;
  rule: string;
  organizer: AgendaPerson | null;
  participants: AgendaPerson[];
  /** La réponse du compte de l'agenda (vide : il n'est pas invité). */
  response: "" | "attente" | "oui" | "peut" | "non";
  /** Elle attend sa réponse. */
  invitation: boolean;
  /** Faux pour une invitation : seul qui l'organise la modifie. */
  organized: boolean;
  added: { by: string; conversation: string; at: number } | null;
  remind: MikaReminder;
  forgotten: boolean;
  /** Les rappels du fournisseur ; `reminders_default` : ceux de son agenda (Google). */
  reminders?: Alert[];
  reminders_default?: boolean;
  can: { edit: boolean; delete: boolean; respond: boolean; duplicate: boolean; remind: boolean };
  /** Une invitation à laquelle elle ne répond pas d'ici : pourquoi, en une ligne (vide sinon). */
  respond_why?: string;
  /** Une invitation, un événement : le nom de son agenda. */
  calendar_name?: string;
  /** La réponse qu'elle a préparée à cette invitation. */
  prepared?: Proposal | null;
  proposals?: Proposal[];
}

/** Une date de « L'agenda de Mika » : sa mémoire, en lecture seule. */
export interface HerDate {
  ref: string;
  calendar: "mika";
  kind: "promesse" | "moment" | "chaque_annee";
  title: string;
  start: number;
  end: number;
  all_day: boolean;
  day: string;
  /** D'où ça vient, en mots. */
  source: string;
  conversation: string;
  said_at: number;
}

export interface ProposalDraft {
  title: string;
  start: number;
  end: number;
  all_day: boolean;
  zone: string;
  location: string;
  description: string;
  rule: string;
  invite: string[];
}

/** Ce que Mika propose d'écrire dans un de ses agendas et qui attend un accord. */
export interface Proposal {
  id: number;
  op: "ajouter" | "modifier" | "supprimer" | "repondre";
  calendar: string;
  /** Ce qu'elle propose, dans ses mots. */
  summary: string;
  at: number;
  starts: number;
  /** C'est elle qui décide (sinon le propriétaire de l'agenda, ou qui s'occupe de Mika). */
  decides: boolean;
  conversation: string;
  invitation: string;
  target: { event: number; uid: string; occurrence: string } | null;
  draft: ProposalDraft | null;
  change: Record<string, unknown> | null;
  scope: string;
  answer: string;
  comment: string;
  why: string;
  remind: string | null;
  preview: { text: string; digest: string; blocked: string } | null;
}

export interface Period {
  start: string;
  end: string;
  zone: string;
  items: AgendaItem[];
  her: HerDate[];
  proposals: Proposal[];
}

export interface Found {
  q: string;
  items: AgendaItem[];
  her: HerDate[];
  more: boolean;
}

/** Les bornes des champs que l'API reçoit (`plugins/agenda/actions.py`), en caractères. */
export const AGENDA_LIMITS = { title: 300, location: 300, description: 8000, link: 1000, comment: 500, search: 120 } as const;
/** Au plus tant de jours par période (`app/domains/agenda/api.py::PERIOD_DAYS`). */
export const PERIOD_DAYS = 100;

export function fetchCalendars(): Promise<Calendars> {
  return getJson(`${A}/calendars`);
}

/** Une période : `start` et `end` en `AAAA-MM-JJ`, le dernier jour compris ; `calendars` : leurs clés, `mika` compris. */
export function fetchPeriod(start: string, end: string, calendars: readonly string[]): Promise<Period> {
  return getJson(`${A}/period${query({ start, end, calendars: calendars.join(",") })}`);
}

export function fetchEvent(event: number, occurrence = ""): Promise<AgendaItem> {
  return getJson(`${A}/event${query({ event, occurrence })}`);
}

export function searchAgenda(q: string, calendars: readonly string[]): Promise<Found> {
  return getJson(`${A}/search${query({ q, calendars: calendars.join(",") })}`);
}

export function fetchInvitations(): Promise<{ items: AgendaItem[] }> {
  return getJson(`${A}/invitations`);
}

export function fetchProposals(): Promise<{ items: Proposal[] }> {
  return getJson(`${A}/proposals`);
}

// ── écrire ──

/** Ce qu'on écrit d'un événement (`create`, et ce qui change d'un `edit`). `reminders` absent : ceux de l'agenda chez
 *  son fournisseur (une création), tels quels (une modification) ; une liste vide : aucun. */
export interface EventFields {
  title?: string;
  start?: string;
  end?: string;
  all_day?: boolean;
  zone?: string;
  location?: string;
  description?: string;
  conference?: string;
  rule?: string;
  invite?: string[];
  free?: boolean;
  private?: boolean;
  remind?: MikaReminder;
  reminders?: Alert[];
}

export interface Made extends Done {
  made?: { calendar: string; uid: string; event: number };
}

export type Scope = "un" | "suivants" | "tous";

export function createEvent(calendar: string, fields: EventFields, nonce = ""): Promise<Made> {
  return sendJson(`${A}/event/create`, { calendar, ...fields }, nonce);
}

export function editEvent(event: number, occurrence: string, scope: Scope, fields: EventFields, nonce = ""): Promise<Done> {
  return sendJson(`${A}/event/edit`, { event, occurrence, scope, ...fields }, nonce);
}

export function deleteEvent(event: number, occurrence: string, scope: Scope, nonce = ""): Promise<Done> {
  return sendJson(`${A}/event/delete`, { event, occurrence, scope }, nonce);
}

export function duplicateEvent(event: number, occurrence: string, to = "", nonce = ""): Promise<Made> {
  return sendJson(`${A}/event/duplicate`, { event, occurrence, to }, nonce);
}

export function respondEvent(event: number, occurrence: string, answer: "oui" | "peut" | "non", comment = "", scope: "un" | "tous" = "tous", nonce = ""): Promise<Done> {
  return sendJson(`${A}/event/respond`, { event, occurrence, answer, comment, scope }, nonce);
}

export function remindEvent(event: number, value: MikaReminder): Promise<Done> {
  return sendJson(`${A}/event/remind`, { event, value });
}

export function acceptProposal(proposal: number, seen: string, nonce = ""): Promise<Done> {
  return sendJson(`${A}/proposal/accept`, { proposal, seen }, nonce);
}

export function refuseProposal(proposal: number, note = "", nonce = ""): Promise<Done> {
  return sendJson(`${A}/proposal/refuse`, { proposal, note }, nonce);
}

export function editProposal(proposal: number, calendar: string, fields: EventFields, nonce = ""): Promise<Made> {
  return sendJson(`${A}/proposal/edit`, { proposal, calendar, ...fields }, nonce);
}

// ── ses comptes (Paramètres › Agendas) ──

export interface AgendaSignin {
  state: "connectee" | "en_attente" | "a_faire" | string;
  code: string;
  url: string;
  until: number;
  error: string;
}

export interface AgendaAccount {
  key: string;
  kind: Exclude<AgendaKind, "mika">;
  kind_label: string;
  label: string;
  system: boolean;
  address: string;
  enabled: boolean;
  url: string;
  url_set: boolean;
  username: string;
  secrets: { password: boolean };
  oauth_client_id: string;
  oauth_tenant: string;
  synced_at: number;
  tried_at: number;
  failures: number;
  error: string;
  signin: AgendaSignin | null;
  abilities: { write: boolean; calendars: boolean };
  calendars: AgendaCalendar[];
}

export interface AgendaService {
  key: string;
  name: string;
  url: string;
  help: string;
}

export interface Accounts {
  plugged: boolean;
  accounts: AgendaAccount[];
  google: { app: boolean; direct: boolean };
  microsoft_app: boolean;
  kinds: Coded[];
  services: AgendaService[];
  colors: Coded[];
  reminders: Coded[];
  /** Combien de comptes elle peut brancher (`null` : une opératrice). */
  max: number | null;
}

export interface AccountValues {
  label?: string;
  enabled?: boolean;
  url?: string;
  username?: string;
  password?: string;
  address?: string;
  oauth_client_id?: string;
  oauth_tenant?: string;
}

export interface TriedCalendar {
  local: string;
  name: string;
  color: string;
  writable: boolean;
  primary: boolean;
  selected: boolean;
}

export function fetchAccounts(): Promise<Accounts> {
  return getJson(`${A}/accounts`);
}

export function saveAccount(kind: string, account: string, values: AccountValues, nonce = ""): Promise<Done & { account: string }> {
  return sendJson(`${A}/account/save`, account ? { account, values } : { kind, values }, nonce);
}

export function tryCaldav(url: string, username: string, password: string, account = ""): Promise<{ ok: boolean; message: string; calendars: TriedCalendar[] }> {
  return sendJson(`${A}/account/try`, { url, username, password, account });
}

export function googleStart(account: string): Promise<Done & { url: string; until: number; direct: boolean }> {
  return sendJson(`${A}/account/google/start`, { account });
}

export function googleFinish(account: string, text: string): Promise<Done> {
  return sendJson(`${A}/account/google/finish`, { account, text });
}

export function microsoftStart(account: string): Promise<Done & { code: string; url: string; until: number; state: string; error: string }> {
  return sendJson(`${A}/account/microsoft/start`, { account });
}

export function syncAccount(account: string): Promise<Done> {
  return sendJson(`${A}/account/sync`, { account });
}

export function disconnectAccount(account: string): Promise<Done> {
  return sendJson(`${A}/account/disconnect`, { account });
}

export function removeAccount(account: string): Promise<Done> {
  return sendJson(`${A}/account/remove`, { account });
}

export function newCalendar(name: string, account = "", nonce = ""): Promise<Done & { made?: { calendar: string } }> {
  return sendJson(`${A}/calendar/new`, { name, account }, nonce);
}

/** Régler un de ses agendas : son nom, sa couleur, masqué, « Mika te le rappelle », suivi. */
export interface CalendarChanges {
  name?: string;
  color?: string;
  hidden?: boolean;
  reminder?: MikaReminder;
  followed?: boolean | null;
}

export function saveCalendar(calendar: string, changes: CalendarChanges): Promise<Done> {
  return sendJson(`${A}/calendar/save`, { calendar, ...changes });
}

// ── son tableau de droits (Outils › Droits) ──

export type AgendaWrite = "non" | "accord" | "seule";
export type AgendaKeep = "rien" | "prive" | "perso" | "public";

export interface AgendaRule {
  /** Qui (`toi`, `elle`, `personne:<clé>`…), par où (`web`, `web:prive`, `teams`, `interne`…), quand (`conversation`,
   *  `initiative` ; vide : toujours). */
  who: string[];
  canal: string[];
  when: string[];
  read: boolean;
  write: AgendaWrite;
  respond: "non" | "accord";
  keep: AgendaKeep;
  words?: { who: string; canal: string; when: string; read: string; write: string; respond: string; keep: string };
  [more: string]: unknown;
}

export interface AgendaRights {
  calendar: string;
  set: boolean;
  lines: AgendaRule[];
  default: AgendaRule;
}

export function fetchAgendaRights(calendar: string): Promise<AgendaRights> {
  return getJson(`${A}/rights${query({ calendar })}`);
}

export function saveAgendaRights(calendar: string, lines: AgendaRule[], def: AgendaRule): Promise<Done> {
  return sendJson(`${A}/rights/save`, { calendar, lines, default: def });
}

export function resetAgendaRights(calendar: string): Promise<Done> {
  return sendJson(`${A}/rights/save`, { calendar, reset: true });
}
