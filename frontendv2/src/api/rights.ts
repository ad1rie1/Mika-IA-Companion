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
  /**
   * Pourquoi, dit à la personne (ADR 0209) : la part de la ligne qui décide qui la concerne (« tout le monde, quand
   * elle répond », « par défaut : personne »), et le canal ou le plafond quand ils serrent ; sinon sa condition, son
   * service pas configuré, une boîte ou un compte à ton nom.
   */
  why: string;
  /** La ligne même, telle que la console la dit (« ligne 2 — … ») : pour une opératrice seulement, vide sinon. */
  line: string;
  reason: Reason;
  /** Ouvert parce qu'une ressource de l'outil est à toi. */
  owned: boolean;
}

export interface ToolRow {
  name: string;
  /** Ce qu'il fait, dit à la personne (« Te promettre un rappel », ADR 0208) ; vide pour un outil venu d'ailleurs. */
  label: string;
  /** Sa consigne au modèle (où « tu », c'est elle) : le nom d'un outil venu d'ailleurs, en repli. */
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
  /** Vrai : la sienne, réglée pour ce compte. */
  set: boolean;
  /** Celle de tout son canal (toutes tes boîtes, tous tes comptes Teams), réglée dans la console ; ni l'une ni
   *  l'autre : son minimum vital. */
  common?: boolean;
  lines: RuleLine[];
  default: RuleLine;
}

export interface Resource {
  key: string;
  title: string;
  /** Ce qu'elle est : une famille ; à quoi sert un service qu'une personne a branché (son but). Vide pour un service
   *  de Mika : son but est la ligne de son catalogue, écrite pour elle (ADR 0209). */
  description?: string;
  /** Où la console montre son tableau (Réglages › Droits) : pour une opératrice seulement, vide sinon. */
  href?: string;
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
