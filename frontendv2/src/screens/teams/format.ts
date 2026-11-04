/**
 * Les petites formes pures de Teams : l'état d'une réponse de Mika en mots, son mode, les repères de jour du fil, la
 * suite d'un même auteur, une mention mise en valeur. Sans DOM : tout se teste.
 */
import { h, norm } from "../../shell/dom";
import type { ConversationKind, OwnPending, Reply, ReplyMode, ReplyState, TeamsMessage, Thread } from "../../api/teams";
import { clock } from "../chat/markup";

/** Une réponse encore en chemin (une autre ne se prépare pas dans la même conversation). */
export const UNDER_WAY: ReadonlySet<ReplyState> = new Set<ReplyState>(["attend", "approuve", "en_file", "pose"]);

function plain(text: string): string {
  return String(text || "")
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

/** Ce qui est parti diffère de ce qu'elle avait écrit (retouchée ici, ou dans Teams avant l'envoi). */
export function retouched(r: Pick<Reply, "edited" | "sent_text" | "body">): boolean {
  if (r.edited) return true;
  return !!r.sent_text && !!r.body && !plain(r.sent_text).includes(plain(r.body));
}

/** L'état d'une réponse, en mots, et son ton ; `now` pour le délai d'un accord. */
export function replyState(r: Pick<Reply, "state" | "edited" | "sent_text" | "body" | "expires">): [string, string] {
  switch (r.state) {
    case "attend":
      return ["warn", r.expires ? `attend ton accord · jusqu'à ${clock(r.expires)}` : "attend ton accord"];
    case "approuve":
      return ["info", "approuvée, en partance"];
    case "en_file":
      return ["info", "en file"];
    case "pose":
      return ["info", "posée dans Teams"];
    case "parti":
      return ["ok", retouched(r) ? "partie · retouchée" : "partie"];
    case "inutilise":
      return ["danger", "pas servie"];
    case "refuse":
      return ["", "refusée"];
    case "expire":
      return ["", "expirée"];
    case "echec":
      return ["danger", "échec"];
    default:
      return ["", String(r.state)];
  }
}

/** Ce que dit la carte d'une réponse en chemin, dans sa conversation (comme la maquette). */
export function cardState(r: Pick<Reply, "state" | "expires">): [string, string] {
  switch (r.state) {
    case "attend":
      return ["warn", r.expires ? `Ton accord : elle part quand tu l'acceptes, ici · jusqu'à ${clock(r.expires)}` : "Ton accord : elle part quand tu l'acceptes, ici"];
    case "approuve":
    case "en_file":
      return ["info", "En file : l'extension l'envoie dans Teams, sous ton nom"];
    case "pose":
      return ["info", "Posée dans la zone de saisie de Teams : tu l'envoies là-bas"];
    default:
      return ["", ""];
  }
}

/** Comment part ce qu'elle prépare, en mots. */
export function modeLabel(mode: ReplyMode | string): string {
  return ({ brouillon: "brouillon", validation: "ton accord", autonome: "seule" } as Record<string, string>)[mode] ?? mode;
}

export function modeTitle(mode: ReplyMode | string): string {
  return (
    ({
      brouillon: "Posée dans la zone de saisie de Teams : c'est toi qui l'envoies",
      validation: "Après ton accord : elle part une fois que tu l'as acceptée",
      autonome: "Seule : elle part sans te demander",
    } as Record<string, string>)[mode] ?? ""
  );
}

export function kindLabel(kind: ConversationKind | string): string {
  return ({ dm: "tête-à-tête", group: "groupe", channel: "canal", meeting: "réunion" } as Record<string, string>)[kind] ?? "conversation";
}

const WEEKDAYS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];
const MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];

function dayKey(ms: number): number {
  const d = new Date(ms);
  return d.getFullYear() * 10_000 + d.getMonth() * 100 + d.getDate();
}

/** « Aujourd'hui », « Hier », sinon « lundi 2 novembre » (l'année si ce n'est pas celle-ci). */
export function dayLabel(ms: number, now: number): string {
  const today = new Date(now);
  if (dayKey(ms) === dayKey(now)) return "Aujourd'hui";
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1).getTime();
  if (dayKey(ms) === dayKey(yesterday)) return "Hier";
  const d = new Date(ms);
  const label = `${WEEKDAYS[d.getDay()]} ${d.getDate() === 1 ? "1er" : d.getDate()} ${MONTHS[d.getMonth()]}`;
  return d.getFullYear() === today.getFullYear() ? label : `${label} ${d.getFullYear()}`;
}

/** Ce qui précède chaque message : un repère de jour quand il change, et s'il continue le même auteur. */
export function threadMarks(messages: readonly Pick<TeamsMessage, "at" | "author_id" | "author" | "own">[], now: number): { day: string; suite: boolean }[] {
  return messages.map((m, i) => {
    const prev = messages[i - 1];
    const newDay = !prev || dayKey(prev.at) !== dayKey(m.at);
    const sameAuthor = !!prev && (prev.author_id || prev.author) === (m.author_id || m.author) && prev.own === m.own;
    return { day: newDay ? dayLabel(m.at, now) : "", suite: !newDay && sameAuthor && m.at - prev.at < 10 * 60_000 };
  });
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Le texte d'un message, échappé, ses retours à la ligne gardés, et une mention de toi en valeur
 *  (« @Adrien Moreau », « @Adrien »). */
export function messageHtml(text: string, selfName: string, mentioned: boolean): string {
  let out = h(text).replace(/\n/g, "<br>");
  const name = selfName.trim();
  if (mentioned && name) {
    const first = name.split(/\s+/)[0];
    const names = [...new Set([name, first].filter(Boolean))].map((n) => escapeRegExp(h(n)));
    out = out.replace(new RegExp(`@(?:${names.join("|")})`, "g"), (m) => `<span class="tm-at">${m}</span>`);
  }
  return out;
}

// ── Ce que tu as écrit toi-même et qui n'est pas encore dans le fil (ADR 0189) ──

/** Ton envoi depuis cette page, que le moteur n'a pas encore pu dire (`at` : quand il l'a accepté). */
export interface SentHere {
  conversation: string;
  text: string;
  at: number;
}

/** Une bulle de toi qui n'est pas (encore) un message du fil : ce qu'elle dit d'elle-même, et si elle n'est pas
 *  partie. `id` : son brouillon chez le moteur (vide pour un envoi d'ici pas encore relu). */
export interface OwnBubble {
  id: string;
  text: string;
  at: number;
  note: string;
  failed: boolean;
}

/** Ce que dit l'état d'un de tes messages en attente ; `failed` : il ne partira pas. */
export function pendingNote(state: string, reason = ""): { note: string; failed: boolean } {
  switch (state) {
    case "en_file":
      return { note: "en file : l'extension l'envoie dans Teams, sous ton nom", failed: false };
    case "envoi":
      return { note: "en cours d'envoi par l'extension", failed: false };
    case "pose":
      return { note: "posé dans la zone de saisie de Teams : c'est toi qui l'envoies, de là-bas", failed: false };
    case "inutilise":
      return { note: "pas parti : l'extension ne l'a pas relevé à temps (Teams web n'était pas ouvert avec elle)", failed: true };
    case "echec":
      return { note: `pas parti : l'envoi a échoué${reason ? ` (${reason})` : ""}`, failed: true };
    default:
      return { note: String(state || "en attente"), failed: false };
  }
}

/**
 * Tes envois d'ici qui restent à montrer après une lecture du fil. Un moteur qui dit `pending` connaît tout envoi qu'il
 * a accepté avant que la lecture ne commence (`started`) : sa liste fait foi, l'envoi d'ici s'efface. Un moteur qui ne
 * le dit pas : l'envoi s'efface quand un message de toi au même texte revient dans le fil.
 */
export function stillSentHere(local: readonly SentHere[], t: Pick<Thread, "key" | "messages" | "pending">, started: number): SentHere[] {
  return local.filter((p) => {
    if (p.conversation !== t.key) return true;
    if (Array.isArray(t.pending)) return p.at > started;
    const text = norm(p.text).trim();
    return !t.messages.some((m) => m.own && norm(m.text).trim() === text && m.at >= p.at - 120_000);
  });
}

/** Les bulles de toi au bas du fil : ce que le moteur dit de tes messages en attente, du plus ancien au plus récent,
 *  puis tes envois d'ici qu'il n'a pas encore pu dire. */
export function ownBubbles(pending: readonly OwnPending[] | undefined, local: readonly SentHere[]): OwnBubble[] {
  const fromEngine = [...(pending ?? [])]
    .sort((a, b) => a.at - b.at)
    .map((p) => ({ id: p.id, text: p.body, at: p.at, ...pendingNote(p.state, p.reason ?? "") }));
  const here = local.map((p) => ({ id: "", text: p.text, at: p.at, ...pendingNote("en_file") }));
  return [...fromEngine, ...here];
}

/** Un message de toi qui est ce qu'elle avait préparé (une réponse partie, au même texte). */
export function fromHer(m: Pick<TeamsMessage, "own" | "text">, replies: readonly Pick<Reply, "state" | "sent_text" | "body">[]): boolean {
  if (!m.own) return false;
  const text = plain(m.text);
  return replies.some((r) => r.state === "parti" && !!text && (plain(r.sent_text) === text || plain(r.sent_text).startsWith(text) || plain(r.body) === text));
}

/** Ce qui reste d'une saisie une fois `sent` parti : ce qu'on a tapé après lui (vide s'il n'y a rien d'autre), ou
 *  `null` quand la saisie ne commence plus par lui (on y a tapé autre chose : elle reste telle quelle). */
export function withoutSent(value: string, sent: string): string | null {
  const lead = value.trimStart();
  return sent && lead.startsWith(sent) ? lead.slice(sent.length).trimStart() : null;
}
