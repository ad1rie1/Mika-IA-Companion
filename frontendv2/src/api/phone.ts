/**
 * Téléphone, par l'API par personne (`backendv2/docs/protocole-moi.md` § 5) : ce que l'application du téléphone a lu
 * dans ses notifications, rangé par conversation, les réponses que Mika y a proposées, sa dernière position, et ses
 * téléphones (les jetons `mobile` de son compte), qu'elle révoque elle-même (ADR 0190).
 */
import { apiUrl, getJson, MOI, sendJson, type Done } from "./moi";

/** Un message lu sur le téléphone ; `own` : écrit par la personne du compte. */
export interface PhoneMessage {
  id: string;
  at: number;
  own: boolean;
  sender: string;
  text: string;
}

/**
 * Le sort d'une réponse que Mika a proposée : préparée, offerte au téléphone (qui attend le geste), puis ce que le
 * téléphone en dit, ou l'échéance.
 */
export type OfferState = "prepared" | "offered" | "sent" | "other" | "copied" | "ignored" | "failed" | "expired";

export interface PhoneOffer {
  id: number;
  state: OfferState | string;
  at: number;
  expires: number;
  decided_at: number;
  /** Un code écrit par le code, jamais un texte venu d'ailleurs. */
  reason: string;
  reply_to: string;
  text: string;
}

export interface PhoneConversation {
  /** `<appli>|<fil>` */
  key: string;
  app: string;
  app_name: string;
  group: boolean;
  /** Le groupe, sinon qui écrit. */
  title: string;
  count: number;
  last_at: number;
  last: PhoneMessage;
  /** Une réponse de Mika en chemin. */
  her: { state: string; id: number } | null;
}

export interface PhoneThread {
  key: string;
  app: string;
  app_name: string;
  group: boolean;
  title: string;
  messages: PhoneMessage[];
  more: boolean;
  offers: PhoneOffer[];
}

export type PhonePosition =
  | { known: false }
  | {
      known: true;
      coords: { lat: number; lon: number } | null;
      label: string;
      accuracy_m: number;
      at: number;
    };

/** Un de ses téléphones (jamais son secret) ; `push` : il a dit où le notifier. */
export interface Phone {
  id: number;
  label: string;
  created_at: number;
  last_used: number;
  revoked: boolean;
  push: boolean;
}

export interface Phones {
  items: Phone[];
  /** L'application est déposée sur le serveur. */
  apk: boolean;
}

export function fetchConversations(size = 100): Promise<{ items: PhoneConversation[] }> {
  return getJson(`${MOI}/phone/conversations?size=${size}`);
}

export function fetchThread(conversation: string, size = 100): Promise<PhoneThread> {
  return getJson(`${MOI}/phone/thread?conversation=${encodeURIComponent(conversation)}&size=${size}`);
}

export function fetchPosition(): Promise<PhonePosition> {
  return getJson(`${MOI}/phone/position`);
}

/**
 * La carte de sa position (ADR 0193), servie par le serveur seul : ses tuiles, ses polices et ses icônes sont des
 * chemins de l'API (jamais une adresse du dehors, qui dirait où tu es). `ready` faux : le plan dessiné, `reason` dit
 * pourquoi.
 */
export interface MapInfo {
  ready: boolean;
  reason: string;
  kind?: "vecteur" | "image";
  minzoom?: number;
  maxzoom?: number;
  /** Ouest, sud, est, nord ; `null` : partout. */
  bounds?: [number, number, number, number] | null;
  attribution?: string;
  /** `…/tiles/{z}/{x}/{y}` */
  tiles?: string;
  /** `…/fonts/{fontstack}/{range}.pbf` ; `null` : pas de polices (une carte sans noms). */
  glyphs?: string | null;
  /** `…/sprites/v4` (la planche suit : `/light`, `/dark`) ; `null` : pas d'icônes. */
  sprite?: string | null;
}

export function fetchMap(): Promise<MapInfo> {
  return getJson(`${MOI}/phone/map`);
}

export function fetchPhones(): Promise<Phones> {
  return getJson(`${MOI}/phone/phones`);
}

/** Révoquer un de ses téléphones : son jeton ne vaut plus rien, ses connexions se ferment, ses messages restent. */
export function revokePhone(id: number): Promise<Done> {
  return sendJson(`${MOI}/phone/revoke`, { id });
}

/** L'application à télécharger : sur le serveur (derrière la session), jamais sur Vite. */
export const APK_URL = apiUrl(`${MOI}/phone/apk`);
