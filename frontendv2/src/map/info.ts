/**
 * La carte que le serveur sert (ADR 0193, `GET /api/moi/phone/map`), lue une fois pour toutes les cartes de la page
 * (Téléphone, Carte, les miniatures du chat) et relue toutes les cinq minutes : une source changée dans la console,
 * des polices ajoutées, une autre zone — chaque carte ouverte suit (`restyle`).
 */
import { fetchMap, type MapInfo } from "../api/phone";
import { Cached } from "../screens/parametres/kit";

export const MAP_INFO_TTL = 5 * 60_000;

/** Ce qui distingue une carte servie d'une autre : la même clé, la même carte (sa version est dans ses adresses). */
export function infoKey(info: MapInfo | null): string {
  return JSON.stringify(info ?? null);
}

export const mapInfo = new Cached<MapInfo>(() => fetchMap(), MAP_INFO_TTL);
