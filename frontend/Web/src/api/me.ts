/**
 * Qui est connecté, selon l'API par personne (`GET /api/moi`, `backend/docs/protocole-moi.md` § 2) : son compte,
 * sa personne, et ce qui l'attend, domaine par domaine (les pastilles de la barre du haut).
 */
import { getJson, MOI, sendJson } from "./moi";

/** Ce qui attend ta décision, domaine par domaine (ADR 0200) : une pastille n'a que ce sens-là. */
export interface Counts {
  /** Ses brouillons de mail qui attendent ta décision, dans tes boîtes (les non-lus ont leurs compteurs dans Mail). */
  mail: number;
  /** Ses réponses Teams qui attendent ta décision. */
  teams: number;
  /** Ses réponses offertes au téléphone, qui attendent ton geste. */
  phone: number;
  /** Ce qui t'attend, toi, dans tes projets (« À faire », `protocole-moi.md` § 11). */
  projects: number;
  /** Ses invitations en attente, et ce que Mika propose dont elle décide (ADR 0309, § 13). */
  agenda?: number;
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
  /** « Corriger » marche : un modèle est donné au rôle `correct` (ADR 0307) ; absent d'un moteur qui ne le dit pas. */
  correct?: boolean;
}

export function fetchMe(): Promise<Me> {
  return getJson<Me>(MOI);
}

/** Un texte corrigé (ADR 0307) : ses fautes, sans changer ses mots ; `changes` : combien de corrections ; `refused` :
 *  combien de changements du modèle ont été écartés parce qu'ils touchaient aux mots. */
export interface Corrected {
  text: string;
  changes: number;
  refused?: number;
}

export function correctText(text: string): Promise<Corrected> {
  return sendJson<Corrected>(`${MOI}/correct`, { text });
}
