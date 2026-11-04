/**
 * Ses partages (ADR 0188 ; `backendv2/src/mika/app/moi/shares.py`) : ce qu'elle partage — ses boîtes, ses comptes
 * Teams, ses services — avec qui et à quel niveau, ce qu'on lui partage, et les personnes à qui elle peut partager
 * (chaque compte actif, sauf elle). Seul le propriétaire partage, et seulement avec une personne qui a un compte.
 */
import { getJson, MOI, sendJson, type Done } from "./moi";

export type ShareKind = "mail" | "teams" | "mcp";
/** Lire ; lire et préparer ; s'en servir. */
export type ShareLevel = "lire" | "preparer" | "servir";

export interface GivenShare {
  kind: ShareKind;
  key: string;
  title: string;
  /** La clé de la personne. */
  person: string;
  name: string;
  level: ShareLevel;
}

export interface ReceivedShare {
  kind: ShareKind;
  key: string;
  title: string;
  level: ShareLevel;
  owner_name: string;
}

export interface Shares {
  given: GivenShare[];
  received: ReceivedShare[];
}

export interface Person {
  person: string;
  name: string;
  /** Une de ses propriétaires : ce qui est « à toi » est déjà à elle (un partage lui serait refusé). */
  owner?: boolean;
}

export function fetchShares(): Promise<Shares> {
  return getJson(`${MOI}/shares`);
}

export function fetchPeople(): Promise<{ items: Person[] }> {
  return getJson(`${MOI}/people`);
}

/** Partager une de ses ressources avec une personne, à un niveau ; un niveau vide retire le partage. */
export function setShare(kind: ShareKind, key: string, person: string, level: ShareLevel | ""): Promise<Done> {
  return sendJson(`${MOI}/shares/set`, { kind, key, person, level });
}
