/**
 * Qui est connecté, selon l'API par personne (`GET /api/moi`, `backendv2/docs/protocole-moi.md` § 2) : son compte,
 * sa personne, et ce qui l'attend, domaine par domaine (les pastilles de la barre du haut).
 */
import { getJson, MOI } from "./moi";

export interface Counts {
  /** Les non-lus de la réception de ses boîtes, et ses brouillons qui attendent. */
  mail: number;
  /** Ses réponses Teams qui attendent ta décision. */
  teams: number;
  /** Ses réponses offertes au téléphone, qui attendent ton geste. */
  phone: number;
}

export interface Me {
  username: string;
  name: string;
  handle: string;
  /** La clé de sa personne (ce qu'une ressource nomme dans son propriétaire, `personne:<clé>`). */
  person: string;
  operator: boolean;
  /** Une de ses propriétaires : ce qui est « à toi » est à elle. */
  owner: boolean;
  counts: Counts;
}

export function fetchMe(): Promise<Me> {
  return getJson<Me>(MOI);
}
