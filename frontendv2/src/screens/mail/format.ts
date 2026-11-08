/**
 * Les petites formes pures de Mail (et de Teams, qui partage ses niveaux et ses noms) : ce qu'un niveau de partage
 * ouvre, le nom qu'on montre d'une boîte partagée, les adresses, le texte d'un mail en HTML, les « [À COMPLÉTER ».
 * Sans DOM : tout se teste.
 */
import { h, hue, initials } from "../../shell/dom";
import type { IconName } from "../../shell/icons";
import { MAIL_LIMITS, PIECE_LIMITS, type MailBox, type MailFull, type Person } from "../../api/mail";
import { ofName } from "../../shared/names";

/** « de Léa », « d'Adrien » : commun à Mail et à Teams (`shared/names.ts`), réexporté pour l'écran Mail. */
export { ofName };

// ── Les niveaux (ADR 0188) ────────────────────────────────────────────

export interface Caps {
  /** La sienne : la régler, décider des brouillons de Mika. */
  own: boolean;
  /** « Préremplir avec Mika » (ses brouillons attendent alors l'accord du propriétaire). */
  prepare: boolean;
  /** Écrire, répondre, transférer, ranger. */
  write: boolean;
  /** Décider de ses brouillons : le propriétaire seulement. */
  decide: boolean;
}

/** Ce qu'un niveau ouvre : la sienne, tout ; `servir`, comme elle sauf décider ; `preparer`, préremplir ; `lire`, lire. */
export function caps(level: string): Caps {
  const own = level === "proprietaire";
  const write = own || level === "servir";
  return { own, write, prepare: write || level === "preparer", decide: own };
}

/** L'étiquette courte d'un partage (« lecture »…) ; vide pour la sienne. */
export function levelTag(level: string): string {
  return ({ lire: "lecture", preparer: "préparer", servir: "s'en servir" } as Record<string, string>)[level] ?? "";
}

/** Le prénom : « Adrien Moreau » → « Adrien ». */
export function firstName(full: string): string {
  return String(full || "").trim().split(/\s+/)[0] ?? "";
}

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

/** Un rond d'initiales, d'une teinte stable : `<span class="av sm c3">CD</span>`. */
export function avatar(name: string, size = "", key = name): string {
  const label = String(name || key || "?");
  return `<span class="av${size ? ` ${size}` : ""} c${hue(key || label)}" title="${h(label)}">${h(initials(label.replace(/[^\p{L}\p{N}\s._-]/gu, "")) || "?")}</span>`;
}

/** Le nom à montrer d'une personne : son nom, sinon son adresse. */
export function personName(p: Person): string {
  return p.name || p.address;
}

export function sameAddress(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

/** « Nom <adresse> » tel qu'il se relit (un nom qui porte une virgule ou des guillemets est cité). */
export function addressText(p: Person): string {
  if (!p.name || sameAddress(p.name, p.address)) return p.address;
  const name = /[,;:<>@()[\]"\\]/.test(p.name) ? `"${p.name.replace(/["\\]/g, (c) => `\\${c}`)}"` : p.name;
  return `${name} <${p.address}>`;
}

/** Les destinataires d'un en-tête : « A <a@x>, "B, C" <b@x>, c@x » ; une entrée sans @ est écartée. */
export function parseAddresses(field: string): Person[] {
  const out: Person[] = [];
  let part = "";
  let quoted = false;
  let angle = false;
  const flush = () => {
    const raw = part.trim();
    part = "";
    if (!raw) return;
    const m = /^(.*?)<([^<>]+)>\s*$/.exec(raw);
    const address = (m ? m[2] : raw).trim();
    if (!address.includes("@")) return;
    let name = m ? m[1].trim() : "";
    if (name.startsWith('"') && name.endsWith('"') && name.length >= 2) name = name.slice(1, -1).replace(/\\(.)/g, "$1");
    out.push({ name, address: address.toLowerCase() });
  };
  for (let i = 0; i < field.length; i++) {
    const c = field[i];
    if (c === "\\" && quoted) {
      part += c + (field[i + 1] ?? "");
      i++;
      continue;
    }
    if (c === '"') quoted = !quoted;
    else if (c === "<" && !quoted) angle = true;
    else if (c === ">" && !quoted) angle = false;
    if ((c === "," || c === ";") && !quoted && !angle) flush();
    else part += c;
  }
  flush();
  return out;
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

/** Ce qu'en compte le serveur (`len` en Python) : des caractères, pas des unités UTF-16 (un emoji compte pour un). */
export function chars(text: string): number {
  let n = 0;
  for (const _ of String(text ?? "")) n++;
  return n;
}

/** « 20 000 » : les milliers séparés d'une espace fine, comme en français. */
export function thousands(n: number): string {
  return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

/** Au plus `max` caractères, terminé d'une ellipse au besoin : pour un texte qu'on n'a pas tapé (l'objet dérivé
 *  « Re: … » d'une réponse, qui sinon serait refusé sans qu'on le voie). */
export function clip(text: string, max: number): string {
  return chars(text) <= max ? text : `${Array.from(text).slice(0, max - 1).join("")}…`;
}

/** Le compte d'un texte borné, montré quand il approche de sa borne (« 16 400 / 20 000 », comme le champ du chat) ;
 *  vide avant. */
export function countLabel(text: string, max: number): string {
  const n = chars(text);
  if (n < max * 0.8) return "";
  return `${thousands(n)} / ${thousands(max)}${n >= max ? " — la limite" : ""}`;
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

const TO_FILL = /\[\s*(?:a\s*)?(?:completer|remplir|preciser)\b/;

function fold(text: string): string {
  return String(text || "")
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase();
}

/** Reste-t-il un « [À COMPLÉTER » (sous toutes ses graphies, comme `ports/drafts.py::to_fill`) ? */
export function toFill(...texts: string[]): boolean {
  return texts.some((t) => TO_FILL.test(fold(t)));
}

/** Dans un texte déjà échappé : chaque passage à compléter en rouge (`<mark class="completer">`). */
export function markToFill(escaped: string): string {
  return escaped.replace(/\[[^\]\n]{0,300}(?:\]|$)/gm, (m) => (toFill(m) ? `<mark class="completer">${m}</mark>` : m));
}

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

/** Une clé d'envoi (un double clic ne refait rien, `protocole-moi.md` § 1). */
export function newNonce(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  return `n${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}

/** « à l'instant », « il y a 3 min », « il y a 2 h », « il y a 4 j ». */
export function ago(ms: number, now: number): string {
  if (!ms) return "jamais";
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 45) return "à l'instant";
  const min = Math.round(s / 60);
  if (min < 60) return `il y a ${min} min`;
  const hours = Math.round(min / 60);
  if (hours < 24) return `il y a ${hours} h`;
  return `il y a ${Math.round(hours / 24)} j`;
}

/** On y répond (l'API aussi) : un mail reçu, ou une copie reçue d'un mail parti de ta boîte ; un mail parti sans
 *  copie reçue se transfère (`/mail/reply` : 409). */
export function answerable(m: { sent: boolean; received?: boolean }): boolean {
  return !m.sent || !!m.received;
}
