/**
 * Les mots des réglages d'une boîte (Paramètres › Comptes mail : `settings.ts`), et ce qui s'y calcule sans DOM :
 * son état, sa voix, sa connexion, la sécurité de l'envoi, son non-lu, les préréglages d'un fournisseur, les bornes
 * que le serveur ne vérifie pas, les secrets gardés qu'un enregistrement doit redonner. Les codes sont ceux du
 * moteur (`adapters/mail/config.py`, `app/me/settings.py`).
 */
import type { Box, BoxValues } from "../../api/settings";
import type { FormValue } from "../../shared/settings";

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
  ["microsoft", "Microsoft", "Outlook.com, Hotmail, Live : tu te connectes chez Microsoft, par un code", "globe"],
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
 *  part jamais vers un autre serveur (`app/me/settings.py`, `IMAP_CONNECTION` et `SMTP_CONNECTION`). */
export const CONNECTION: Readonly<Record<"password" | "smtp_password", readonly string[]>> = {
  password: ["auth", "imap_host", "imap_port", "imap_ssl", "user", "oauth_client_id", "oauth_tenant"],
  smtp_password: ["smtp_host", "smtp_port", "smtp_security", "smtp_user"],
};

/** Le serveur de chaque secret : vidé, la connexion est retirée (une boîte qui ne fait que lire), rien ne part plus. */
const SECRET_HOST = { password: "imap_host", smtp_password: "smtp_host" } as const;

/**
 * Les secrets gardés qu'un enregistrement doit redonner : sa connexion change et rien n'est tapé à sa place — le
 * serveur le refuserait (400, `app/me/settings.py`, `_kept_secrets`). L'envoi sans mot de passe à lui se sert de
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
