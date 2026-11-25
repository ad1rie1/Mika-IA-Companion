/**
 * Les petites formes pures de Mail : le nom qu'on montre d'une boîte partagée, les adresses d'un en-tête, les bornes
 * d'un envoi, le texte d'un mail en HTML. Ce que Mail partage avec Teams (ce qu'un niveau ouvre, une personne, le
 * compte d'un texte, les « [À COMPLÉTER ») est dans `shared/`. Sans DOM : tout se teste.
 */
import { h } from "../../shell/dom";
import type { IconName } from "../../shell/icons";
import { MAIL_LIMITS, PIECE_LIMITS, type MailBox, type MailDraft, type MailFull, type Person } from "../../api/mail";
import { ofName } from "../../shared/names";
import { firstName, parseAddresses } from "../../shared/people";
import { chars, thousands } from "../../shared/text";

/** « de Léa », « d'Adrien » : commun à Mail et à Teams (`shared/names.ts`), réexporté pour l'écran Mail. */
export { ofName };

// ── Une boîte partagée (ADR 0188) ─────────────────────────────────────

/** Le nom qu'on montre d'une boîte : la sienne, son nom ; partagée, « Boîte de Léa » (ADR 0188), son nom en plus si
 *  la même personne en partage plusieurs. */
export function boxTitle(box: Pick<MailBox, "key" | "name" | "level" | "owner_name">, all: readonly Pick<MailBox, "level" | "owner_name">[] = []): string {
  if (box.level === "proprietaire" || !box.owner_name) return box.name;
  const first = firstName(box.owner_name);
  const same = all.filter((b) => b.level !== "proprietaire" && b.owner_name === box.owner_name).length;
  return same > 1 ? `${box.name} ${ofName(first)}` : `Boîte ${ofName(first)}`;
}

/** Ce qu'un partage permet, en une phrase (le bandeau d'une boîte partagée). */
export function shareSentence(level: string, owner: string): string {
  const who = owner || "son propriétaire";
  if (level === "lire") return `partagée avec toi en lecture seule : tu la lis, sans y répondre ni la ranger.`;
  if (level === "preparer")
    return `partagée avec toi en lecture et préparation : tu la lis, et Mika peut t'y préparer des réponses, que ${who} approuve.`;
  if (level === "servir") return `partagée avec toi pour t'en servir : tu y réponds et tu la ranges ; ses brouillons, c'est ${who} qui en décide.`;
  return "";
}

// ── Les personnes ─────────────────────────────────────────────────────

export function sameAddress(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

/** « Nom <adresse> » tel qu'il se relit (un nom qui porte une virgule ou des guillemets est cité). */
export function addressText(p: Person): string {
  if (!p.name || sameAddress(p.name, p.address)) return p.address;
  const name = /[,;:<>@()[\]"\\]/.test(p.name) ? `"${p.name.replace(/["\\]/g, (c) => `\\${c}`)}"` : p.name;
  return `${name} <${p.address}>`;
}

/** Une liste sans doublon d'adresse, dans l'ordre. */
export function uniquePeople(people: readonly Person[], without: readonly string[] = []): Person[] {
  const seen = new Set(without.map((a) => a.toLowerCase()));
  const out: Person[] = [];
  for (const p of people) {
    const key = p.address.toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(p);
  }
  return out;
}

/** À qui répondre : l'adresse de réponse, sinon l'expéditeur (un mail parti : ses destinataires) ; à tous, les
 *  autres en copie, sans la boîte elle-même. */
export function replyTargets(
  mail: Pick<MailFull, "from" | "to" | "cc" | "reply_to" | "sent">,
  boxAddress: string,
  all: boolean,
): { to: Person[]; cc: Person[] } {
  const replyTo = parseAddresses(mail.reply_to || "");
  const first = mail.sent ? mail.to : replyTo.length ? replyTo : [mail.from];
  const to = uniquePeople(first.filter((p) => p.address), mail.sent ? [boxAddress] : []);
  if (!to.length && mail.from.address) to.push(mail.from);
  if (!all) return { to, cc: [] };
  const cc = uniquePeople([...(mail.sent ? [] : [mail.from]), ...mail.to, ...mail.cc], [boxAddress, ...to.map((p) => p.address)]);
  return { to, cc };
}

/** « Re: … » une fois, pas deux. */
export function replySubject(subject: string): string {
  const s = String(subject || "").trim();
  return /^(re|ré|aw|sv)\s*:/i.test(s) ? s : `Re: ${s}`;
}

/** « Tr : … » une fois, pas deux. */
export function forwardSubject(subject: string): string {
  const s = String(subject || "").trim();
  return /^(tr|fw|fwd)\s*:/i.test(s) ? s : `Tr : ${s}`;
}

// ── Les bornes d'un envoi ─────────────────────────────────────────────

/** Au plus `max` caractères, terminé d'une ellipse au besoin : pour un texte qu'on n'a pas tapé (l'objet dérivé
 *  « Re: … » d'une réponse, qui sinon serait refusé sans qu'on le voie). */
export function clip(text: string, max: number): string {
  return chars(text) <= max ? text : `${Array.from(text).slice(0, max - 1).join("")}…`;
}

/** Les destinataires d'un en-tête dans leur borne : « Nom <adresse> » quand tout tient, sinon leurs seules adresses —
 *  aucun ne se perd ; `null` : même nues, elles la dépassent. */
export function recipientsText(people: readonly Person[], max: number = MAIL_LIMITS.recipients): string | null {
  const named = people.map(addressText).join(", ");
  if (chars(named) <= max) return named;
  const bare = people.map((p) => p.address).join(", ");
  return chars(bare) <= max ? bare : null;
}

/** Ce qui part au serveur : les destinataires en en-têtes, l'objet, le corps. */
export interface OutgoingText {
  to: string;
  cc: string;
  bcc: string;
  subject: string;
  body: string;
}

/**
 * Un mail prêt à partir, dans les bornes de l'API ; sinon pourquoi il ne peut pas partir tel quel (une phrase à dire
 * sous le formulaire). Le serveur refuserait de toute façon : rien ne part coupé.
 */
export function outgoingText(v: { to: readonly Person[]; cc: readonly Person[]; bcc?: readonly Person[]; subject: string; body: string }): { mail: OutgoingText | null; problem: string } {
  const max = MAIL_LIMITS;
  const to = recipientsText(v.to);
  const cc = recipientsText(v.cc);
  const bcc = recipientsText(v.bcc ?? []);
  const crowded = (field: string) =>
    `Trop de destinataires dans « ${field} » : même sans leurs noms, leurs adresses dépassent ${thousands(max.recipients)} caractères. Envoie-le en plusieurs fois.`;
  if (to === null) return { mail: null, problem: crowded("À") };
  if (cc === null) return { mail: null, problem: crowded("Cc") };
  if (bcc === null) return { mail: null, problem: crowded("Cci") };
  const subject = chars(v.subject);
  if (subject > max.subject) return { mail: null, problem: `L'objet est trop long : ${thousands(max.subject)} caractères au plus (il en a ${thousands(subject)}).` };
  const body = chars(v.body);
  if (body > max.body) return { mail: null, problem: `Le message est trop long : ${thousands(max.body)} caractères au plus (il en a ${thousands(body)}).` };
  return { mail: { to, cc, bcc, subject: v.subject, body: v.body }, problem: "" };
}

// ── Les pièces d'un mail qu'on écrit ──────────────────────────────────

/** Ce qu'il faut savoir d'un fichier joint (un `File` du navigateur). */
export interface Piece {
  name: string;
  size: number;
}

const inMegabytes = (bytes: number) => `${bytes / (1024 * 1024)} Mo`;

/**
 * Ceux de `picked` qui s'ajoutent à `current` dans les bornes de l'API (`PIECE_LIMITS`) ; `problem` dit le premier
 * refus (les autres fichiers choisis passent quand même). Le même fichier choisi deux fois (nom et taille) ne compte
 * qu'une fois. `carried` : les pièces d'origine d'un transfert, qui comptent dans le nombre et le total.
 */
export function addPieces<T extends Piece>(current: readonly T[], picked: readonly T[], carried: readonly Piece[] = []): { pieces: T[]; problem: string } {
  const pieces = [...current];
  let total = [...carried, ...pieces].reduce((sum, p) => sum + p.size, 0);
  const also = carried.length ? ", celles du mail d'origine comprises" : "";
  let problem = "";
  for (const file of picked) {
    if (pieces.some((p) => p.name === file.name && p.size === file.size)) continue;
    let refused = "";
    if (!file.size) refused = `« ${file.name} » est vide.`;
    else if (file.size > PIECE_LIMITS.each) refused = `« ${file.name} » est trop grosse : ${inMegabytes(PIECE_LIMITS.each)} par pièce.`;
    else if (pieces.length + carried.length >= PIECE_LIMITS.count) refused = `Un mail porte au plus ${PIECE_LIMITS.count} pièces${also}.`;
    else if (total + file.size > PIECE_LIMITS.total) refused = `Ces pièces sont trop lourdes pour un seul mail : ${inMegabytes(PIECE_LIMITS.total)} en tout${also}.`;
    if (refused) {
      problem ||= refused;
      continue;
    }
    pieces.push(file);
    total += file.size;
  }
  return { pieces, problem };
}

// ── Le texte ──────────────────────────────────────────────────────────

/** Échappé, ses adresses web en liens (un nouvel onglet, sans référent). */
function linked(text: string): string {
  return h(text).replace(/\bhttps?:\/\/[^\s<>"']+/g, (url) => {
    const trail = /[.,;:!?)\]]+$/.exec(url)?.[0] ?? "";
    const clean = trail ? url.slice(0, -trail.length) : url;
    return `<a href="${clean}" target="_blank" rel="noopener noreferrer">${clean}</a>${trail}`;
  });
}

/**
 * Le texte d'un mail en HTML : des paragraphes (une ligne vide les sépare), ses retours à la ligne, et ce qu'il cite
 * (« > ») en citation, imbriquée au besoin. Tout est échappé.
 */
export function textHtml(body: string): string {
  const lines = String(body || "").replace(/\r\n?/g, "\n").split("\n");
  const out: string[] = [];
  let para: string[] = [];
  let quote: string[] = [];
  const flushPara = () => {
    if (para.length) out.push(`<p>${para.map(linked).join("<br>")}</p>`);
    para = [];
  };
  const flushQuote = () => {
    if (quote.length) out.push(`<blockquote>${textHtml(quote.join("\n"))}</blockquote>`);
    quote = [];
  };
  for (const line of lines) {
    if (/^\s*>/.test(line)) {
      flushPara();
      quote.push(line.replace(/^\s*> ?/, ""));
      continue;
    }
    flushQuote();
    if (!line.trim()) flushPara();
    else para.push(line);
  }
  flushPara();
  flushQuote();
  return out.join("");
}

/** Le cœur d'un brouillon en une ligne : le paragraphe après la formule d'appel. */
export function bodyLead(body: string): string {
  const paras = String(body || "")
    .split(/\n\s*\n/)
    .map((p) => p.replace(/\s+/g, " ").trim())
    .filter(Boolean);
  if (!paras.length) return "";
  return paras.length > 1 && paras[0].length < 60 ? paras[1] : paras[0];
}

/** Ce qu'elle en a fait, en mots : « lu par elle », « archivé par elle »… */
export function howLabel(how: string): { text: string; icon: IconName } {
  const verb = !how || how === "lu" ? "lu" : how;
  const icon: IconName = verb.startsWith("archiv") ? "archive" : verb === "corbeille" || verb === "supprimé" ? "trash" : verb === "répondu" ? "reply" : "eye";
  return { text: verb === "corbeille" ? "mis à la corbeille par elle" : `${verb} par elle`, icon };
}

/** Ce que la touche Suppr met à la corbeille : les mails cochés, sinon le mail ouvert si sa boîte permet de le ranger ;
 *  rien hors d'un champ qu'on remplit (une case à cocher n'en est pas un). */
export function deleteTargets(
  key: { key: string; ctrl: boolean; target: { tag: string; type?: string; editable: boolean } },
  checked: readonly string[],
  open: { ref: string; tidy: boolean } | null,
): string[] {
  if (key.key !== "Delete" || key.ctrl) return [];
  const t = key.target;
  if (t.editable || t.tag === "TEXTAREA" || t.tag === "SELECT" || (t.tag === "INPUT" && t.type !== "checkbox")) return [];
  if (checked.length) return [...checked];
  return open?.tidy ? [open.ref] : [];
}

/** Les mails qu'un rangement sort de la vue (archiver, corbeille, déplacer) quittent la liste aussitôt, sans attendre
 *  le serveur (ADR 0302) : sa session IMAP peut attendre derrière un relevé. `leaving` : chacun d'eux → le numéro de la
 *  dernière lecture de la liste partie avant que le serveur ait répondu (`Infinity` tant qu'il n'a pas répondu). Une
 *  liste lue sous le numéro `seq` ne remontre donc ni un mail en route, ni un mail que le serveur gardait encore quand
 *  elle est partie ; partie après sa réponse, elle dit vrai, et le mail n'a plus à être écarté (il sort de `leaving`). */
export function keptRows<T extends { ref: string }>(rows: readonly T[], leaving: Map<string, number>, seq: number): T[] {
  for (const [ref, until] of leaving) if (until < seq) leaving.delete(ref);
  return rows.filter((r) => !leaving.has(r.ref));
}

/** Ce que son tri a fait d'un mail (ADR 0240), en mots : sur la ligne (`row`, rien pour un envoi en masse), dans le
 *  titre de « Ce qu'elle en sait », et ce qu'il faut en savoir (`note`) ; `null` : rien à en dire. */
export function triageLabel(triage: string | undefined): { text: string; icon: IconName; row: boolean; quiet: boolean; note: string } | null {
  switch (triage) {
    case "read":
      return { text: "lu par son tri", icon: "eye", row: true, quiet: true, note: "" };
    case "waiting":
      return { text: "en attente de son tri", icon: "clock", row: true, quiet: false, note: "Son tri ne l'a pas encore lu : il le lira au prochain relevé." };
    case "guessed":
      return { text: "tri deviné", icon: "alert", row: true, quiet: false, note: "Son tri n'a pas pu le lire (modèle indisponible) : son importance est devinée." };
    case "bulk":
      return { text: "survolé (envoi en masse)", icon: "eye", row: false, quiet: true, note: "" };
    default:
      return null;
  }
}

/** Une clé d'envoi (un double clic ne refait rien, `protocole-moi.md` § 1). */
export function newNonce(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  return `n${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}

// ── Ta réponse partie de son brouillon ────────────────────────────────

/** Ce que devient ta réponse partie de son brouillon : il attend, elle passe par lui ; refusé ou plus là, elle part
 *  comme une réponse ordinaire ; parti, approuvé ou en échec, rien de plus ne part (`why` dit pourquoi). */
export type DraftReply<D> = { via: "draft"; draft: D } | { via: "reply" } | { via: "stop"; why: string };

/**
 * Ta réponse partie de son brouillon `id`, d'après ses brouillons relus tels qu'ils sont (pas seulement ceux qui
 * attendent). Seul un brouillon refusé ou absent laisse partir une réponse ordinaire : parti (une réponse du serveur
 * perdue, puis ta retouche ; ou envoyé d'ailleurs), approuvé ou en échec, une seconde réponse partirait.
 */
export function draftReply<D extends { id: string; state: MailDraft["state"] }>(drafts: readonly D[], id: string): DraftReply<D> {
  const d = drafts.find((x) => x.id === id);
  if (!d || d.state === "refuse") return { via: "reply" };
  if (d.state === "attend") return { via: "draft", draft: d };
  return { via: "stop", why: draftNotWaiting(d.state) };
}

/** Pourquoi rien ne part par un de ses brouillons qui n'attend plus (`state` : ce qu'il est devenu). */
export function draftNotWaiting(state: string): string {
  if (state === "parti" || state === "approuve") return "Son brouillon est déjà parti.";
  if (state === "echec") return "L'envoi de son brouillon a échoué : regarde « Ses brouillons ».";
  return "Son brouillon n'attend plus de décision : rien n'est parti.";
}

/** On y répond (l'API aussi) : un mail reçu, ou une copie reçue d'un mail parti de ta boîte ; un mail parti sans
 *  copie reçue se transfère (`/mail/reply` : 409). */
export function answerable(m: { sent: boolean; received?: boolean }): boolean {
  return !m.sent || !!m.received;
}

// ── Les adresses qu'un autre écran ouvre ──────────────────────────────

/** Écrire à quelqu'un depuis un autre écran (Contacts : « Écrire ») : `#mail/messages/ecrire/<adresse>[/<nom>]` ouvre
 *  la fenêtre d'un mail nouveau, le destinataire déjà posé. */
export function writeToHash(address: string, name = ""): string {
  const to = `#mail/messages/ecrire/${encodeURIComponent(address)}`;
  return name && name !== address ? `${to}/${encodeURIComponent(name)}` : to;
}

/** Le destinataire d'une adresse `ecrire/…` (l'objet de la route, déjà décodé segment par segment) ; `null` sinon. Une
 *  adresse ne porte pas de « / » : ce qui suit le premier est son nom. */
export function writeToRoute(item: string | null): { address: string; name: string } | null {
  if (!item?.startsWith("ecrire/")) return null;
  const rest = item.slice("ecrire/".length);
  const cut = rest.indexOf("/");
  const address = (cut < 0 ? rest : rest.slice(0, cut)).trim();
  if (!address) return null;
  return { address, name: cut < 0 ? "" : rest.slice(cut + 1).trim() };
}

/** L'ancien onglet Contacts du courrier (`#mail/contacts…`) mène à l'écran Contacts (ADR 0298) : sa nouvelle adresse,
 *  ou `null` pour une autre. */
export function legacyContactsHash(hash: string): string | null {
  return /^#\/?mail\/+contacts(?:[/?]|$)/.test(hash) ? "#contacts" : null;
}
