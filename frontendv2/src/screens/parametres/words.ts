/**
 * Les mots de Paramètres, et ce qui se calcule sans DOM : les niveaux d'un partage, l'état d'une boîte ou d'un
 * service, ses outils servis, sa voix, ce qu'un formulaire a changé, les préréglages d'un fournisseur de courrier.
 * Les codes sont ceux du moteur (`vocab/access.py`, `adapters/mail/config.py`, `app/moi/*.py`).
 */
import type { ServiceTool, ToolChoice } from "../../api/mcp";
import type { Box, BoxValues } from "../../api/settings";
import type { ShareKind, ShareLevel } from "../../api/shares";

// ── Les partages (ADR 0188) ──────────────────────────────────────────

export const SHARE_LEVELS: readonly [ShareLevel, string][] = [
  ["lire", "Lire"],
  ["preparer", "Lire et préparer"],
  ["servir", "S'en servir"],
];

/** Les niveaux d'un partage : un service se partage pour lire ou pour s'en servir, jamais « préparer ». */
export function shareLevelsFor(kind: ShareKind): [ShareLevel, string][] {
  return SHARE_LEVELS.filter(([k]) => kind !== "mcp" || k !== "preparer");
}

/** « Lire », « Lire et préparer », « S'en servir » ; « Propriétaire » pour la sienne. */
export function shareWords(level: string): string {
  if (level === "proprietaire") return "Propriétaire";
  return SHARE_LEVELS.find(([k]) => k === level)?.[1] ?? level;
}

/** Ce que la personne pourra, dit en une phrase (la fenêtre « Partager »). */
export function sharePhrase(kind: ShareKind, title: string, person: string, level: ShareLevel): string {
  const first = person.split(/\s+/)[0] || person;
  const where = kind === "mcp" ? "dans ses Outils" : kind === "teams" ? "dans son Teams" : "dans son Mail";
  const can =
    level === "lire"
      ? kind === "mcp"
        ? "pour que Mika s'en serve pour lire, en tête-à-tête avec elle ou lui"
        : "en lecture seule : ni répondre ni ranger"
      : level === "preparer"
        ? "en lecture, et Mika pourra lui préparer des réponses que tu approuveras"
        : kind === "mcp"
          ? "pour que Mika s'en serve pour elle ou lui, sur son accord pour ce qui agit"
          : "pour que Mika s'en serve pour elle ou lui, en tête-à-tête, comme pour toi";
  return `${first} verra « ${title} » ${where}, ${can}.`;
}

export const KIND_WORDS: Record<ShareKind, string> = { mail: "Boîte", teams: "Compte Teams", mcp: "Service" };

export interface ShareTarget {
  kind: ShareKind;
  key: string;
  person: string;
  /** Un partage qu'on change (la fenêtre a été ouverte sur lui). */
  editing: boolean;
  /** Sa personne n'a plus de compte actif (désactivé, relié depuis à une autre personne) : il ne se change plus, il
   *  se retire. */
  gone: boolean;
}

/**
 * Ce qu'un partage enregistre. En modification, la ressource et la personne du partage même — jamais ce que montrent
 * les listes de la fenêtre (désactivées, elles retombent sur leur premier choix quand le sien n'y est plus : le
 * partage partirait à une autre personne). Sinon, ce qu'on a choisi.
 */
export function shareTarget(
  preset: { kind?: ShareKind; key?: string; person?: string },
  picked: { kind: ShareKind; key: string; person: string },
  people: readonly { person: string }[],
): ShareTarget {
  if (preset.kind && preset.key && preset.person) {
    const gone = !people.some((p) => p.person === preset.person);
    return { kind: preset.kind, key: preset.key, person: preset.person, editing: true, gone };
  }
  return { ...picked, editing: false, gone: false };
}

/** À qui partager : tout le monde, sauf, pour une ressource « à toi » (`common`), ses propriétaires — elle est déjà
 *  à elles (l'API refuserait, 400). */
export function sharePeople<P extends { owner?: boolean }>(thing: { common?: boolean } | undefined, people: readonly P[]): P[] {
  return thing?.common ? people.filter((p) => !p.owner) : [...people];
}

/** « de Léa », « d'Adrien », « d'Hélène » : l'élision devant une voyelle ou un h. */
export function ofName(name: string): string {
  return /^[aeiouyhàâäéèêëîïôöùûüœ]/iu.test(name.trim()) ? `d'${name.trim()}` : `de ${name.trim()}`;
}

// ── Les boîtes ───────────────────────────────────────────────────────

/** Son état : [ton, mot] — prête, incomplète, inactive, en erreur. */
export function boxState(b: Pick<Box, "enabled" | "ready" | "error">): [string, string] {
  if (!b.enabled) return ["", "inactive"];
  if (!b.ready) return ["warn", "incomplète"];
  if (b.error) return ["danger", "erreur"];
  return ["ok", "prête"];
}

export const VOICES: readonly [BoxValues["voice"], string][] = [
  ["elle", "En son nom"],
  ["assistante", "En assistante"],
  ["proprietaire", "À ta place"],
];

export function voiceWords(voice: string): string {
  return { elle: "elle y écrit en son nom", assistante: "elle y écrit en assistante", proprietaire: "elle y écrit à ta place" }[voice] ?? "";
}

export function authWords(auth: string): string {
  return auth === "microsoft" ? "Microsoft · OAuth2 (code d'appareil)" : "IMAP/SMTP · mot de passe";
}

export const SMTP_SECURITY: readonly [string, string][] = [
  ["starttls", "STARTTLS (587)"],
  ["ssl", "SSL (465)"],
  ["none", "aucune (tests)"],
];

/** Le non-lu de la réception d'une boîte. */
export function unseenOf(b: Pick<Box, "folders">): number {
  return b.folders.filter((f) => f.role === "inbox" || f.name === "INBOX").reduce((n, f) => n + f.unseen, 0);
}

export type Provider = "microsoft" | "gmail" | "davmail" | "imap";

/** Les fournisseurs de « Ajouter un compte mail » : [clé, titre, ce que c'est, icône]. */
export const PROVIDERS: readonly [Provider, string, string, "globe" | "server" | "mail" | "settings"][] = [
  ["microsoft", "Microsoft", "Outlook.com, Hotmail, Live : connexion par code d'appareil (OAuth2)", "globe"],
  ["davmail", "Exchange pro", "Ta boîte de travail par la passerelle DavMail (O365Graph) sur la machine de Mika", "server"],
  ["gmail", "Gmail", "Avec un mot de passe d'application", "mail"],
  ["imap", "Autre", "N'importe quelle boîte IMAP et SMTP, par mot de passe", "settings"],
];

/** Les réglages de départ d'une boîte, selon son fournisseur. */
export function providerPreset(p: Provider): Partial<BoxValues> {
  switch (p) {
    case "microsoft":
      return { auth: "microsoft", imap_host: "outlook.office365.com", imap_port: 993, imap_ssl: true,
        smtp_host: "smtp-mail.outlook.com", smtp_port: 587, smtp_security: "starttls", oauth_tenant: "consumers" };
    case "gmail":
      return { auth: "password", imap_host: "imap.gmail.com", imap_port: 993, imap_ssl: true, smtp_host: "smtp.gmail.com",
        smtp_port: 587, smtp_security: "starttls", save_sent: false };
    case "davmail":
      return { auth: "password", imap_host: "127.0.0.1", imap_port: 1143, imap_ssl: false, smtp_host: "127.0.0.1",
        smtp_port: 1025, smtp_security: "none" };
    default:
      return { auth: "password", imap_port: 993, imap_ssl: true, smtp_port: 587, smtp_security: "starttls" };
  }
}

/** La sécurité SMTP que son port appelle (465 : SSL ; 587 : STARTTLS), sinon celle qu'on avait. */
export function securityFor(port: number, current: string): string {
  if (port === 465) return "ssl";
  if (port === 587) return "starttls";
  return current;
}

// ── Les formulaires ──────────────────────────────────────────────────

export type FormValue = string | number | boolean | string[];

/** Ce qui a changé d'un formulaire : les champs dont la valeur n'est plus celle de départ. */
export function changed(before: Record<string, FormValue>, after: Record<string, FormValue>): Record<string, FormValue> {
  const out: Record<string, FormValue> = {};
  for (const [k, v] of Object.entries(after)) {
    if (JSON.stringify(v) !== JSON.stringify(before[k])) out[k] = v;
  }
  return out;
}

/** Les bornes que le serveur ne vérifie pas (`Knob(lo, hi)` ne guide que la console) : un port, la fenêtre de relève. */
const RANGES: Record<string, [number, number, string]> = {
  imap_port: [1, 65_535, "un port entre 1 et 65535"],
  smtp_port: [1, 65_535, "un port entre 1 et 65535"],
  since_days: [1, 60, "entre 1 et 60 jours"],
};

export function rangeProblems(values: Record<string, FormValue>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, [lo, hi, words]] of Object.entries(RANGES)) {
    if (!(name in values)) continue;
    const n = Number(values[name]);
    if (!Number.isInteger(n) || n < lo || n > hi) out[name] = words;
  }
  return out;
}

/** La connexion d'une boîte, secret par secret : quand une de ces valeurs change, le secret gardé se redonne — il ne
 *  part jamais vers un autre serveur (`app/moi/settings.py`, `IMAP_CONNECTION` et `SMTP_CONNECTION`). */
export const CONNECTION: Readonly<Record<"password" | "smtp_password", readonly string[]>> = {
  password: ["auth", "imap_host", "imap_port", "imap_ssl", "user", "oauth_client_id", "oauth_tenant"],
  smtp_password: ["smtp_host", "smtp_port", "smtp_security", "smtp_user"],
};

/** Le serveur de chaque secret : vidé, la connexion est retirée (une boîte qui ne fait que lire), rien ne part plus. */
const SECRET_HOST = { password: "imap_host", smtp_password: "smtp_host" } as const;

/**
 * Les secrets gardés qu'un enregistrement doit redonner : sa connexion change et rien n'est tapé à sa place — le
 * serveur le refuserait (400, `app/moi/settings.py`, `_kept_secrets`). L'envoi sans mot de passe à lui se sert de
 * celui de la lecture : changer le serveur d'envoi le redemande aussi, sauf s'il est redonné pour lire dans le même
 * enregistrement. Une connexion dont le serveur est vidé ne redemande rien. Une boîte qui entre par Microsoft n'a
 * aucun mot de passe à redonner (ses champs sont cachés). `auth` : la connexion choisie dans le formulaire ; `hosts` :
 * ses serveurs tels qu'il les montre (changés ou non).
 */
export function secretsToRetype(
  changes: Record<string, FormValue>,
  kept: { password: boolean; smtp_password: boolean },
  auth: string,
  hosts: { imap_host?: FormValue; smtp_host?: FormValue } = {},
): Record<string, string> {
  const out: Record<string, string> = {};
  if (auth === "microsoft") return out;
  for (const secret of ["password", "smtp_password"] as const) {
    if (changes[secret]) continue;
    const host = SECRET_HOST[secret];
    if (!String((host in changes ? changes[host] : hosts[host]) ?? "x").trim()) continue; // retirée : rien ne part
    // ce qui partirait vers cette connexion : son secret, ou pour l'envoi sans le sien, celui de la lecture
    const outgoing = kept[secret] || (secret === "smtp_password" && kept.password && !changes.password);
    if (!outgoing || !CONNECTION[secret].some((f) => f in changes)) continue;
    out[secret] = "à redonner : la connexion a changé, il ne part pas vers un autre serveur";
  }
  return out;
}

/** Les messages d'un formulaire refusé, par champ : la dernière partie du chemin (`accounts.pro.imap_port` → `imap_port`). */
export function fieldErrors(fields: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [path, message] of Object.entries(fields)) {
    const name = path.split(".").pop() || path;
    out[name] = out[name] ? `${out[name]} ; ${message}` : message;
  }
  return out;
}

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
