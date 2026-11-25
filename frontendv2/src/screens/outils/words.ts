/**
 * Les mots des services MCP (ADR 0192), et ce qui s'y calcule sans DOM : leur état, leurs outils servis, le choix
 * d'un outil, le nom et l'adresse d'un service, les en-têtes gardés à redonner quand l'adresse mène ailleurs. Pour
 * la page de leurs réglages (Paramètres › Services MCP : `settings.ts`) et la matrice d'Outils (`matrix.ts`). Les
 * codes sont ceux du moteur (`app/me/mcp.py`).
 */
import type { ServiceTool, ToolChoice } from "../../api/mcp";
import type { FormValue } from "../../shared/settings";

// ── Les services MCP (ADR 0192) ──────────────────────────────────────

const STATES: Record<string, [string, string]> = {
  connecte: ["ok", "connecté"],
  jamais: ["", "jamais joint"],
  erreur: ["danger", "erreur"],
  panne: ["danger", "en panne"],
  incomplet: ["warn", "incomplet"],
  inactif: ["", "inactif"],
};

export function stateWords(state: string): [string, string] {
  return STATES[state] ?? ["", state];
}

/** Ses outils servis (lecture ou action), sur combien, et combien attendent qu'on les regarde (jamais choisis, changés). */
export function servedOf(tools: readonly ServiceTool[]): { served: number; total: number; review: number } {
  return {
    served: tools.filter((t) => t.choice === "lecture" || t.choice === "action").length,
    total: tools.length,
    review: tools.filter((t) => t.choice === "" || t.new || t.changed).length,
  };
}

export const CHOICES: readonly [ToolChoice, string][] = [
  ["non", "Coupé"],
  ["lecture", "Il lit"],
  ["action", "Il agit"],
];

/** Le nom d'un service : il entre dans le nom de ses outils (`mcp_<nom>_<outil>`). */
export const SERVICE_NAME = /^[a-z][a-z0-9_]{0,23}$/;

export function serviceNameProblem(name: string): string {
  if (!name) return "Un nom court.";
  return SERVICE_NAME.test(name) ? "" : "Des minuscules, chiffres et _, en commençant par une lettre (24 au plus).";
}

export function urlProblem(url: string): string {
  if (!url.trim()) return "Son adresse.";
  return /^https:\/\/\S+$/i.test(url.trim()) ? "" : "Une adresse https://… (l'adresse MCP « streamable HTTP » du service).";
}

/** Où une adresse mène : son schéma, son hôte, son port (celui du schéma s'il n'en dit pas). Illisible : elle-même. */
export function urlOrigin(url: string): string {
  try {
    const u = new URL(url.trim());
    const port = u.port || ({ "https:": "443", "http:": "80" } as Record<string, string>)[u.protocol] || "";
    return `${u.protocol}//${u.hostname.toLowerCase()}:${port}`;
  } catch {
    return url.trim().toLowerCase();
  }
}

/** Ce que dit le champ des en-têtes quand l'adresse mène ailleurs (les mots du serveur, `app/me/mcp.py`). */
export const HEADERS_TO_RETYPE = "à redonner : l'adresse a changé (ou à retirer)";

/**
 * Les en-têtes gardés d'un service à redonner (ADR 0236) : son adresse mène ailleurs — un autre hôte, schéma ou port
 * que [before] — et ni de nouveaux en-têtes ni leur retrait (`clear_headers`) ne partent : le serveur refuserait (400).
 * Un autre chemin sur le même serveur, ou un service sans en-têtes gardés ([kept] faux), ne redemande rien.
 */
export function headersToRetype(changes: Record<string, FormValue>, kept: boolean, before: string): Record<string, string> {
  if (!kept || !("url" in changes) || String(changes.secret_headers ?? "").trim() || changes.clear_headers === true) return {};
  return urlOrigin(String(changes.url)) === urlOrigin(before) ? {} : { secret_headers: HEADERS_TO_RETYPE };
}
