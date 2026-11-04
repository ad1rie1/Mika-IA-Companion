/**
 * La matrice de ses droits (`GET /api/moi/rights`, `protocole-moi.md` § 6) : ce que Mika fait de chacun de ses outils
 * pour la personne connectée, par chaque canal et à chaque moment, et seule quand elle travaille. Chaque case est la
 * décision même du moteur (ADR 0187) : le client la montre, il ne la recalcule jamais.
 */
import { getJson, MOI } from "./moi";

export interface Canal {
  key: string;
  label: string;
}

export interface Moment {
  key: string;
  label: string;
}

/** `seule` (elle s'en sert), `carte` (elle te demande), `toi` (ton accord), `non`. */
export type Level = "seule" | "carte" | "toi" | "non";
/** Ce qu'elle garde de ce qu'il rend : un savoir, un souvenir, une confidence, rien. */
export type Keep = "public" | "perso" | "prive" | "rien";
/** Ce qui ferme un outil avant ses lignes : sa condition, son service pas configuré, les accès de sa ressource. */
export type Reason = "" | "when" | "needs" | "fits";

export interface Cell {
  level: Level;
  keep: Keep;
  /** Les lignes qui en décident, en mots (et le canal ou le plafond quand ils serrent). */
  why: string;
  reason: Reason;
  /** Ouvert parce qu'une ressource de l'outil est à toi. */
  owned: boolean;
}

export interface ToolRow {
  name: string;
  description: string;
  acts: boolean;
  /** `<canal>/<moment>` ; `null` : il ne sert pas à ce moment. */
  cells: Record<string, Cell | null>;
}

/** Une ligne de la règle d'un de tes comptes : qui, quand, préparer d'elle-même, comment ça part. */
export interface RuleLine {
  who: string;
  when: string;
  prepare: boolean;
  /** `seule`, `accord`, `brouillon`, `non` */
  reply: string;
  reply_words: string;
}

export interface Rules {
  canal: string;
  /** Faux : son minimum vital (le tableau n'a jamais été réglé). */
  set: boolean;
  lines: RuleLine[];
  default: RuleLine;
}

export interface Resource {
  key: string;
  title: string;
  description?: string;
  tools?: ToolRow[];
  /** Un de tes comptes : sa sorte, son adresse, sa famille d'outils et la règle de son canal. */
  kind?: "mail" | "teams";
  address?: string;
  family?: string;
  rules?: Rules;
}

export type GroupKey = "families" | "accounts" | "services" | "apps";

export interface Group {
  key: GroupKey | string;
  title: string;
  resources: Resource[];
}

export interface Rights {
  canals: Canal[];
  moments: Moment[];
  groups: Group[];
}

export function fetchRights(): Promise<Rights> {
  return getJson(`${MOI}/rights`);
}
