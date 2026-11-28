/**
 * Contacts, par l'API par personne (`backend/docs/protocole-moi.md` § 12, ADR 0298) : ceux que Mika connaît pour
 * toi — vus dans tes comptes Teams et tes boîtes, sur ton téléphone, ou dont tu lui as parlé — et leurs organisations ;
 * la fiche d'un contact (ce qui l'identifie, ce que Mika en sait, où vous vous croisez) ; l'oublier. Le serveur ne dit
 * que ce que tes comptes en montrent : jamais de qui d'autre c'est le contact, jamais la valeur d'une clé du téléphone
 * ni d'un nom raconté. Les instants sont en millisecondes.
 */
import { query } from "./mail";
import { getJson, MOI, sendJson, type Done } from "./moi";

/** Les bornes des chaînes que l'API reçoit (`app/domains/contacts/api.py`, en caractères). */
export const CONTACTS_LIMITS = {
  /** `q` de `/contacts`. */
  search: 200,
} as const;

export type ContactKind = "person" | "org";

/** D'où elle le connaît : Teams, une boîte (sous son nom), le téléphone par appli, ce que tu lui as raconté. */
export type SourceKind = "teams" | "mail" | "whatsapp" | "sms" | "phone" | "told";

export interface ContactSource {
  source: SourceKind | string;
  /** La boîte (`mail`). */
  account?: string;
  label: string;
  /** Combien de fois (0 : un profil seul, l'adresse d'une boîte). */
  count: number;
}

export interface ContactRef {
  id: number;
  name: string;
}

export interface ContactLine {
  id: number;
  kind: ContactKind;
  name: string;
  title: string;
  department: string;
  organisation: ContactRef | null;
  /** Sa fiche est reliée à une personne qui a un compte. */
  linked: boolean;
  /** Cette personne a déjà écrit à Mika (« parle aussi à Mika ») ; sinon, elle n'a qu'un compte. */
  talks: boolean;
  /** Une organisation : ses personnes parmi tes contacts. */
  members: number;
  last: number;
  sources: ContactSource[];
  /** Quatre au plus, jamais une clé du téléphone ni un nom raconté. */
  identifiers: { kind: string; value: string }[];
  /** L'adresse de sa photo de profil Teams (ADR 0300 : `teamsPhotoUrl`), quand un compte Teams où tu lis la garde ;
   *  `null` sinon (ses initiales ; une organisation, son carré). */
  photo?: string | null;
}

export interface ContactsPage {
  total: number;
  page: number;
  size: number;
  /** Chaque sorte, sans la recherche (les choix de l'écran). */
  counts: { all: number; person: number; org: number };
  items: ContactLine[];
}

export interface ContactIdentifier {
  kind: string;
  /** « E-mail », « Identifiant Teams », « Contact WhatsApp »… */
  label: string;
  /** Vide pour un contact du téléphone : sa clé ne se dit pas (`name` : le nom que lui donne ton carnet). */
  value: string;
  name: string;
  /** D'où elle le tient : « Teams », « son profil Teams », le nom d'une boîte, « ton téléphone »… */
  where: string[];
  /** Une adresse sans personne derrière (rangée à son organisation). */
  generic: boolean;
}

export interface ContactFact {
  /** `note` : ce que Mika a compris de ses derniers messages (ADR 0298, lot 6) ; les autres, ce que l'annuaire tient. */
  kind: "title" | "department" | "organisation" | "note" | string;
  label: string;
  value: string;
  /** Une organisation : sa fiche ; un fait (`note`) : de quoi l'oublier. */
  id?: number;
  /** « son profil Teams », « son adresse e-mail » ; un fait : « ses messages dans Teams », « ses mails à Pro ». */
  from: string;
  /** Un fait : sa sorte (`role`, `topic`, `relation`, `expectation`, `manner`, `bond`, `other`). */
  sort?: string;
  /** Un fait : sa confiance, de 0 à 1. */
  confidence?: number;
  /** Un fait : où était le message qui le fonde (« dans le groupe « Projet » », « un mail, objet « … » »). */
  place?: string;
  /** Un fait : la date du message qui le fonde. */
  at?: number;
  /** Un fait : il vient d'un de tes comptes, tu peux le faire oublier. */
  forget?: boolean;
}

/** Où vous vous croisez : une conversation Teams, une boîte, une conversation du téléphone. */
export type ContactPlace =
  | { source: "teams"; conversation: string; account: string; title: string; kind: string; count: number; last: number }
  | { source: "mail"; box: string; box_name: string; count: number; last: number; ref: string; subject: string }
  | { source: "phone"; conversation: string; app: string; app_name: string; title: string; group: boolean; count: number; last: number };

export interface ContactMember {
  id: number;
  name: string;
  title: string;
  department: string;
  last: number;
  linked: boolean;
  talks: boolean;
  /** Comme sur une ligne (`ContactLine.photo`). */
  photo?: string | null;
}

export interface ContactSheet extends Omit<ContactLine, "identifiers" | "members"> {
  first: number;
  identifiers: ContactIdentifier[];
  facts: ContactFact[];
  places: ContactPlace[];
  members: ContactMember[];
  members_total: number;
  /** À qui écrire, si une de tes boîtes envoie. */
  write: { address: string; name: string } | null;
  /** Sa conversation Teams (le tête-à-tête, sinon la plus récente), vide sinon. */
  teams: string;
  /** Sa conversation de ton téléphone (`<appli>|<fil>`), vide sinon. */
  message: string;
  /** `mine` : tout vient de tes comptes ; `shared` : aussi d'un compte qu'on te partage ou d'un compte à Mika. */
  privacy: "mine" | "shared";
  forget: { allowed: boolean; reason: string };
}

export interface ContactsQuery {
  q?: string;
  kind?: ContactKind | "";
  page?: number;
  size?: number;
}

const C = `${MOI}/contacts`;

export function fetchContactsPage(q: ContactsQuery = {}): Promise<ContactsPage> {
  return getJson<ContactsPage>(`${C}${query({ q: q.q, kind: q.kind, page: q.page, size: q.size })}`);
}

export function fetchContactSheet(id: number): Promise<ContactSheet> {
  return getJson<ContactSheet>(`${C}/fiche${query({ id })}`);
}

export function forgetContact(id: number): Promise<Done> {
  return sendJson<Done>(`${C}/forget`, { id });
}

/** Qu'elle oublie un fait qu'elle a tiré de ses messages (seulement d'un de tes comptes ; il ne se réapprend pas). */
export function forgetContactFact(id: number): Promise<Done & { id: number }> {
  return sendJson<Done & { id: number }>(`${C}/fact/forget`, { id });
}
