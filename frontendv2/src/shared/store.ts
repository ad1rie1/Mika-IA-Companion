/**
 * Les lectures que Téléphone, Carte, Outils et Paramètres partagent : une seule copie de chaque ressource de l'API par
 * personne, que chaque écran relit à son ouverture et qu'un geste invalide (une boîte ajoutée se voit aussi dans
 * Outils, un téléphone révoqué dans Téléphone). Ta dernière position est la même pour la Position du Téléphone et pour
 * la Carte (« Autour de moi », « Ma position » d'un itinéraire). Le direct (ADR 0308) les invalide aussi
 * (`followChanges`) : la prochaine lecture d'un écran repart du serveur.
 */
import { fetchAccounts, fetchAgendaRights, fetchCalendars } from "../api/agenda";
import { fetchMe } from "../api/me";
import { fetchServices } from "../api/mcp";
import { fetchPhones, fetchPosition } from "../api/phone";
import { fetchRights } from "../api/rights";
import { fetchBox, fetchBoxes, fetchTeamsAccount, fetchTeamsAccounts } from "../api/settings";
import { fetchPeople, fetchShares } from "../api/shares";
import type { Live, Topic } from "../live/live";
import { Cached, CachedMap } from "./kit";

export const me = new Cached(fetchMe, 30_000);
export const boxes = new Cached(fetchBoxes, 15_000);
export const boxSettings = new CachedMap(fetchBox, 10_000);
export const teamsAccounts = new Cached(fetchTeamsAccounts, 15_000);
export const teamsSettings = new CachedMap(fetchTeamsAccount, 10_000);
export const phones = new Cached(fetchPhones, 15_000);
export const position = new Cached(fetchPosition, 15_000);
export const services = new Cached(fetchServices, 10_000);
export const shares = new Cached(fetchShares, 15_000);
export const people = new Cached(fetchPeople, 60_000);
export const rights = new Cached(fetchRights, 20_000);
/** Ses agendas et ses comptes d'agenda (ADR 0309) : l'Agenda, Paramètres › Agendas et Outils › Droits les partagent. */
export const agendaCalendars = new Cached(fetchCalendars, 20_000);
export const agendaAccounts = new Cached(fetchAccounts, 15_000);
/** Le tableau de droits de chacun de ses agendas (Outils › Droits le règle, Paramètres › Agendas le résume). */
export const agendaRights = new CachedMap(fetchAgendaRights, 20_000);

type Copy = Cached<unknown> | CachedMap<unknown>;

/**
 * Ce que chaque sujet du direct rend périmé ici (`protocole-moi.md`, § 2 bis) : `settings`, ce que règle Paramètres
 * (boîtes, comptes Teams, services, partages, droits) ; `mail` et `teams`, l'état d'une boîte ou d'un compte que
 * Paramètres montre (sa dernière relève, sa panne, le dernier lot de son extension). Le reste n'a pas de copie ici.
 */
export const STALE_ON: Readonly<Partial<Record<Topic, readonly Copy[]>>> = {
  me: [me],
  mail: [boxes, boxSettings],
  teams: [teamsAccounts, teamsSettings],
  "phone.position": [position],
  "phone.phones": [phones],
  settings: [boxes, boxSettings, teamsAccounts, teamsSettings, services, shares, people, rights],
  agenda: [agendaCalendars, agendaAccounts, agendaRights, shares],
};

/** Le direct : chaque sujet invalide ses copies ; chaque ouverture de la connexion, toutes (rien n'est rattrapé). À
 *  brancher avant les écrans, pour qu'une lecture qu'ils lancent sur le même sujet reparte bien du serveur. */
export function followChanges(service: Live): void {
  for (const [topic, copies] of Object.entries(STALE_ON) as [Topic, readonly Copy[]][]) {
    service.onChange(topic, () => {
      for (const c of copies) c.invalidate();
    });
  }
  service.onResync(() => {
    for (const c of [me, boxes, boxSettings, teamsAccounts, teamsSettings, phones, position, services, shares, people, rights, agendaCalendars, agendaAccounts, agendaRights]) c.invalidate();
  });
}
