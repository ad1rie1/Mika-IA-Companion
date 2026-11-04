/**
 * Les lectures que Téléphone, Outils et Paramètres partagent : une seule copie de chaque ressource de l'API par
 * personne, que chaque écran relit à son ouverture et qu'un geste invalide (une boîte ajoutée se voit aussi dans
 * Outils, un téléphone révoqué dans Téléphone).
 */
import { fetchMe } from "../../api/me";
import { fetchServices } from "../../api/mcp";
import { fetchPhones } from "../../api/phone";
import { fetchRights } from "../../api/rights";
import { fetchBox, fetchBoxes, fetchTeamsAccount, fetchTeamsAccounts } from "../../api/settings";
import { fetchPeople, fetchShares } from "../../api/shares";
import { Cached, CachedMap } from "./kit";

export const me = new Cached(fetchMe, 30_000);
export const boxes = new Cached(fetchBoxes, 15_000);
export const boxSettings = new CachedMap(fetchBox, 10_000);
export const teamsAccounts = new Cached(fetchTeamsAccounts, 15_000);
export const teamsSettings = new CachedMap(fetchTeamsAccount, 10_000);
export const phones = new Cached(fetchPhones, 15_000);
export const services = new Cached(fetchServices, 10_000);
export const shares = new Cached(fetchShares, 15_000);
export const people = new Cached(fetchPeople, 60_000);
export const rights = new Cached(fetchRights, 20_000);
