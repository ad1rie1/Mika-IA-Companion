/**
 * L'API par personne (`/api/moi/…`, ADR 0187 ; le contrat : `backendv2/docs/protocole-moi.md`) : ce que montrent
 * Outils, Mail, Teams, Téléphone et Paramètres — ses boîtes, ses comptes Teams, ses téléphones, ses services, ses
 * partages et ses droits, tels que le moteur les calcule pour elle. Sous la session du navigateur ; une écriture
 * passe par `sendJson` (et `postJson` du client web dessous), le seul chemin qui porte le jeton CSRF. Chaque
 * domaine a son client typé à côté (`mail.ts`, `teams.ts`, `phone.ts`, `rights.ts`, `settings.ts`, `shares.ts`,
 * `mcp.ts`).
 */
import { API_BASE, BackendUnreachableError, postJson } from "@web/network/api";

export { postJson };

/** Un refus du serveur : il a répondu, il dit non (`{"error": "…"}` en français quand il le dit) ; ``fields`` : un
 * message par champ d'un formulaire refusé. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly fields: Record<string, string> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Le texte qu'on montre pour un statut sans message. */
export function statusMessage(status: number): string {
  if (status === 401) return "Ta session a expiré : reconnecte-toi.";
  if (status === 403) return "Ce n'est pas à toi.";
  if (status === 404) return "Introuvable.";
  if (status === 429) return "Trop de demandes d'affilée : attends un instant.";
  if (status >= 500) return "Le serveur n'a pas pu répondre.";
  return `Refusé (HTTP ${status}).`;
}

/**
 * Lire une ressource de l'API, en JSON, avec la session (`credentials: "include"`). Jamais depuis le cache du
 * navigateur : ce sont les données de la personne, et le moteur peut les changer à tout moment.
 */
export async function getJson<T = unknown>(path: string): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}${path}`, {
      credentials: "include",
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
  } catch (err) {
    throw new BackendUnreachableError(err);
  }
  const body: unknown = await resp.json().catch(() => null);
  if (!resp.ok) {
    const said = body && typeof body === "object" ? (body as { error?: unknown }).error : undefined;
    throw new ApiError(resp.status, typeof said === "string" && said ? said : statusMessage(resp.status));
  }
  return body as T;
}

/** Les adresses de l'API par personne, pour qu'aucun écran ne les écrive à la main. */
export const MOI = "/api/moi";

/** Ce que rend une écriture réussie (`protocole-moi.md` § 1), plus ce que chaque route ajoute. */
export interface Done {
  ok: true;
  message: string;
  deduped?: boolean;
}

/**
 * Écrire par l'API (`POST`, corps JSON, jeton CSRF : `postJson` du client web). ``nonce`` : la clé d'un envoi (un
 * double clic ne refait rien). Un refus lève `ApiError`, avec ses messages par champ.
 */
export async function sendJson<T = Done>(path: string, body: Record<string, unknown>, nonce = ""): Promise<T> {
  let resp: Response;
  try {
    resp = await postJson(path, nonce ? { ...body, nonce } : body);
  } catch (err) {
    if (err instanceof BackendUnreachableError) throw err;
    throw new BackendUnreachableError(err);
  }
  const got: unknown = await resp.json().catch(() => null);
  if (!resp.ok) {
    const o = got && typeof got === "object" ? (got as { error?: unknown; fields?: unknown }) : {};
    const fields = o.fields && typeof o.fields === "object" ? (o.fields as Record<string, string>) : {};
    throw new ApiError(resp.status, typeof o.error === "string" && o.error ? o.error : statusMessage(resp.status),
      fields);
  }
  return got as T;
}

/** Une adresse de l'API à ouvrir telle quelle (un fichier à télécharger, un cadre) : sur le serveur, pas sur Vite. */
export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}
