/**
 * Chat synchronisation — reconciling what is on screen with what the server holds.
 *
 * Pure functions over a message list, deliberately separate from the DOM.
 * The rules here are the whole substance of the fix; the widget around them
 * only paints. Keeping them apart means they can be tested for what they
 * actually are — a merge with three cases and one total order — instead of
 * through a rendered bubble.
 *
 * The problem they solve: a `speech` frame is fire-and-forget. It is sent
 * with `group_send`, which drops silently when nobody is in the group. The
 * browser painted its own bubble before sending and kept its thread in
 * localStorage, so a tab disconnected for any reason — restart, timeout,
 * sleeping laptop — showed the question and never the answer, permanently,
 * while the database held both.
 */

import type { AckMessage, HistoryAttachment, HistoryEntry, RejectedAttachment, SentFile } from "../types";

/**
 * What happened to a message the user sent.
 *
 * - `pending`  — painted locally, still in the transport's outbox.
 * - `sent`     — the server acknowledged receiving it (not answering it).
 * - `failed`   — refused: the server never took it, so it will never be
 *                answered. A message the server *did* take and could not
 *                answer stays `sent` — see `replyNote` (ADR 0056).
 *
 * Only user messages carry one. Before this existed, a queued message and a
 * delivered one looked identical, which is how three messages could sit on
 * screen looking sent while the socket was dead.
 */
export type MessageStatus = "pending" | "sent" | "failed";

export interface StoredMessage {
  text: string;
  sender: "user" | "vtuber";
  ts: number;
  /**
   * Server `Message.pk`. Absent while a message exists only in this browser.
   * The highest one present is the synchronisation cursor, which is why it
   * is persisted alongside the text: after a reload the client must still
   * know what it has already seen.
   */
  id?: number;
  /** Client-minted correlation id, for our own optimistic bubbles. */
  cid?: string;
  status?: MessageStatus;
  /**
   * What was typed, when it differs from what is displayed. A message
   * carrying files is painted as `texte [photo.png]` while the server row's
   * `text` holds `texte` alone (the files come apart, by name).
   */
  matchText?: string;
  /** Why a message failed, in French, for the bubble's tooltip. */
  reason?: string;
  /**
   * Ce que le serveur a écarté de cet envoi, en français, affiché sous la
   * bulle. Un envoi partiel est *accepté* — le tour part avec ce qui reste —
   * donc ni le statut ni le motif d'échec ne peuvent le porter, et une
   * infobulle ne se survole pas : le fichier que Mika n'a jamais reçu doit
   * se voir.
   */
  note?: string;
  /**
   * Where a message that will *never* get a server id belongs in the order.
   *
   * A project report is shown in the thread but is not a `Message` row, so
   * it has no id — and "no id" otherwise means "not written yet, therefore
   * newest", which pinned every report to the bottom of the thread for the
   * rest of the session, below replies that came long after it. Recording
   * the cursor at the moment it arrived says what it actually is: after
   * everything displayed then, before everything since.
   */
  after?: number;
  /**
   * Pensée murmurée pour elle-même (`voice_persona: "inner"`), pas une
   * réponse. Affichée en italique : dans une bulle ordinaire, « c'est qui
   * ça ? » se lisait comme une question posée à l'interlocuteur.
   */
  inner?: boolean;
  /**
   * Ce qu'est devenue la réponse à ce message quand elle ne viendra pas
   * (second `ack` `no_reply`), en français, affiché **sous** la bulle. Le
   * message, lui, est reçu : rayer sa bulle (« refusé — Mika est saturée »)
   * disait l'inverse de ce qui s'était passé.
   */
  replyNote?: string;
  /** Pour une opératrice : où réparer (une page de la console, `/inspecteur/…`). */
  replyHref?: string;
  /**
   * Elle dort : la réponse attend son réveil (`speech` sans texte,
   * `voice_reason: "asleep"`). Dit sous la bulle tant qu'elle n'a rien dit
   * depuis — voir `asleepNoteShown`.
   */
  waiting?: "asleep";
  /**
   * Les fichiers qu'elle a envoyés avec ce message (un dessin s'affiche en
   * vignette, un autre fichier en lien) — validés par `sentFiles`.
   */
  files?: SentFile[];
}

/**
 * Why a message was refused. Anything not listed is still refused — the
 * client must not assume an unknown status means success — it just gets the
 * generic wording.
 *
 * Les deux derniers viennent du client, pas du serveur : un frame trop gros
 * pour le transport n'atteint jamais le consumer, donc personne d'autre ne
 * peut le dire.
 */
const ACK_REASONS: Record<string, string> = {
  rate_limited: "trop de messages d'affilée",
  empty: "message vide",
  // Une file pleine : le message n'a pas été pris. (Une réponse qui échoue
  // n'est plus dite ainsi : c'est `no_reply`, et le message reste envoyé.)
  overloaded: "Mika est saturée, réessaie dans un instant",
  too_long: "message trop long",
  attachments_rejected: "pièces jointes refusées (format ou taille)",
  frame_too_large: "envoi trop volumineux — retire une pièce jointe",
  send_abandoned: "envoi abandonné après plusieurs tentatives",
  unauthorized: "session expirée — reconnecte-toi",
};

/** French wording for a refusal status, for display. */
export function ackReason(status: string): string {
  return ACK_REASONS[status] ?? "refusé par le serveur";
}

/** Pourquoi une pièce jointe n'est pas passée (old/backend/pipeline/media.py). */
const REJECT_REASONS: Record<string, string> = {
  too_large: "trop volumineux",
  too_many: "au-delà de la limite de pièces jointes",
  invalid: "illisible",
};

/** Ce qui n'a pas été transmis, en français, pour la note sous la bulle. */
export function rejectedNote(rejected: RejectedAttachment[]): string {
  const noms = rejected
    .map((r) => `${r.name} (${REJECT_REASONS[r.reason] ?? "refusé"})`)
    .join(", ");
  return `Non transmis à Mika : ${noms}`;
}

let cidCounter = 0;

/** Correlation id for one outgoing message — unique within this tab. */
export function nextClientMsgId(): string {
  cidCounter += 1;
  return `c${Date.now().toString(36)}-${cidCounter}`;
}

/**
 * Prosodic tokens ([SIGH], [PAUSE:400], …) are stage directions for the TTS
 * (see TTSService) — they must never be shown raw in a chat bubble. Also
 * drops any [EMOTION:…] tag that survived backend extraction.
 */
export function stripProsody(text: string): string {
  return text
    .replace(/\[(?:PAUSE(?::\d+)?|SIGH|LAUGH|BREATH)\]/gi, " ")
    .replace(/\[EMOTION:[^\]]*\]/gi, " ")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/ +([,.!?;:])/g, "$1")
    .trim();
}

/**
 * Highest server id the client has taken delivery of.
 *
 * Derived from the rendered list rather than tracked separately, so it can
 * never claim delivery of a frame that a throwing handler dropped.
 */
export function cursorOf(history: StoredMessage[]): number {
  let max = 0;
  for (const m of history) {
    if (typeof m.id === "number" && m.id > max) max = m.id;
  }
  return max;
}

/**
 * Chronological order, with server ids as the authority.
 *
 * Timestamps cannot arbitrate: an optimistic bubble is stamped by the
 * browser clock and its server row by the database, and the two disagree by
 * however long the message spent in the outbox. Ids are assigned by the one
 * writer, so they are the only total order both sides share. Messages with
 * no id yet are by construction the newest — they have not been written —
 * so they sort last, among themselves by local time.
 *
 * The exception is a message that will never *have* an id (`after`): a
 * project report is displayed in the thread but is not a `Message` row, and
 * treating it as un-persisted pinned it below everything that followed.
 * It sorts just after the cursor it recorded on arrival.
 *
 * Sorts in place and returns the same array, matching Array.prototype.sort.
 */
function orderKey(m: StoredMessage): number {
  if (m.id !== undefined) return m.id;
  if (m.after !== undefined) return m.after + 0.5;
  return Number.POSITIVE_INFINITY;
}

export function sortMessages(history: StoredMessage[]): StoredMessage[] {
  return history.sort((a, b) => {
    const ka = orderKey(a);
    const kb = orderKey(b);
    if (ka !== kb) return ka - kb;
    return a.ts - b.ts;
  });
}

/** Only the three known states survive a reload.
 *
 * Anything else in the cache is from an older build, and a bubble with an
 * unknown status renders as a CSS class that does not exist — invisible,
 * and indistinguishable from delivered.
 */
export function coerceStatus(raw: unknown): MessageStatus | undefined {
  return raw === "sent" || raw === "pending" || raw === "failed"
    ? raw
    : undefined;
}

/**
 * Pourquoi une bulle restaurée « en attente d'envoi » ne peut plus jamais le
 * devenir : voir `restoredStatus`.
 */
export const RESTORED_PENDING_REASON = "non envoyé — recharge de la page";

/**
 * Ce qu'un statut restauré du localStorage doit devenir à l'ouverture.
 *
 * `outbox` (network/WebSocketClient) est en mémoire seulement — une bulle
 * peinte juste avant l'envoi et jamais confirmée ne dispose plus, après un
 * rechargement, d'aucun frame vivant susceptible de la faire progresser :
 * l'ancien onglet qui la portait a disparu avec elle. Sans cette règle un
 * `pending` restauré affichait « en attente d'envoi » pour toujours, un état
 * que plus rien ne pouvait faire avancer. Un `sent` ou un `failed` restauré
 * reste tel quel : le premier a bien été accusé réception, le second porte
 * déjà sa propre raison.
 */
export function restoredStatus(
  raw: unknown
): { status: MessageStatus | undefined; reason?: string } {
  const status = coerceStatus(raw);
  if (status === "pending") {
    return { status: "failed", reason: RESTORED_PENDING_REASON };
  }
  return { status };
}

/** Le statut d'un message reçu dont la réponse ne viendra pas (ADR 0056). */
export const NO_REPLY = "no_reply";

/**
 * La note posée sous la bulle quand la réponse ne viendra pas. Pour tout le
 * monde : que Mika n'a pas pu répondre, et quoi faire. Une opératrice reçoit
 * en plus la cause en clair (`detail`) — à elle seule, le serveur ne l'envoie
 * qu'à ses connexions — jamais une consigne d'administration dite à quelqu'un
 * qui ne peut rien y faire.
 */
export function noReplyNote(reason?: string, detail?: string): string {
  const base =
    reason === "too_late"
      ? "Mika n'a pas pu répondre à temps — redis-le-lui si c'est encore d'actualité."
      : "Mika n'a pas pu répondre — réessaie.";
  const cause = typeof detail === "string" ? detail.trim() : "";
  return cause ? `${base} (${cause})` : base;
}

/** Une page de la console, et rien d'autre : le lien posé sous une bulle ne
 * mène jamais hors de `/inspecteur/`. */
export function consoleHref(href: unknown): string | undefined {
  return typeof href === "string" && /^\/inspecteur\/[\w\-/]*$/.test(href)
    ? href
    : undefined;
}

/**
 * « Pourquoi a-t-elle dit ça ? », pour une opératrice : la page de la console
 * qui explique une bulle (`/inspecteur/parole/<seq>`), ou `undefined`.
 *
 * L'identifiant serveur d'une bulle est le `seq` du journal, celui que la
 * console sait expliquer. Une de ses paroles (réponse ou initiative) y mène ;
 * une pensée murmurée n'en a pas (pas dans le fil). Un message de la personne
 * n'y mène que quand sa réponse ne viendra pas (`replyNote`) : la même page dit
 * alors pourquoi elle n'a pas répondu. Le lien n'ouvre aucun droit — la console
 * garde sa propre porte d'opératrice.
 */
export function whyLink(msg: StoredMessage): { href: string; label: string } | undefined {
  if (typeof msg.id !== "number" || !Number.isInteger(msg.id) || msg.id <= 0) return undefined;
  let label: string;
  if (msg.sender === "vtuber" && !msg.inner) label = "pourquoi ?";
  else if (msg.sender === "user" && msg.replyNote) label = "pourquoi pas de réponse ?";
  else return undefined;
  const href = consoleHref(`/inspecteur/parole/${msg.id}`);
  return href ? { href, label } : undefined;
}

/** Record what the server said became of a message we sent.
 *
 * `failed` : the message was refused (it never reached her). `settled` : no
 * reply is coming — a refusal, or a `no_reply` on a message she did receive;
 * the caller stops the typing indicator on either.
 */
export function applyAck(
  history: StoredMessage[],
  cid: string,
  status: string,
  rejected?: RejectedAttachment[],
  extra: Pick<AckMessage, "reason" | "detail" | "href"> = {}
): { changed: boolean; failed: boolean; settled: boolean } {
  const msg = history.find((m) => m.cid === cid);
  if (!msg) return { changed: false, failed: false, settled: false };
  if (status === NO_REPLY || status === "too_late") {
    // Reçu : la bulle reste envoyée (et garde la note d'un envoi partiel,
    // posée par le premier `ack`) ; la réponse ne viendra pas, une note le dit.
    msg.status = "sent";
    msg.reason = undefined;
    msg.waiting = undefined;
    const reason = status === "too_late" ? "too_late" : extra.reason;
    msg.replyNote = noReplyNote(reason, extra.detail);
    msg.replyHref = consoleHref(extra.href);
    return { changed: true, failed: false, settled: true };
  }
  const failed = status !== "accepted";
  msg.status = failed ? "failed" : "sent";
  msg.reason = failed ? ackReason(status) : undefined;
  // Un envoi partiel repart avec le statut `accepted` : sans cette note, la
  // bulle affiche trois fichiers dont un que Mika n'a jamais reçu.
  msg.note = rejected?.length ? rejectedNote(rejected) : undefined;
  return { changed: true, failed, settled: failed };
}

/** Sa note de sommeil : « elle dort, elle te répondra à son réveil ». */
export const ASLEEP_NOTE = "Mika dort — elle te répondra à son réveil.";

/**
 * Une trame `speech` sans texte, `voice_reason: "asleep"` : elle dort, la
 * réponse à ce message attend son réveil. Rien ne le disait — « Mika
 * écrit… » s'éteignait et la bulle restait là, sans explication.
 */
export function markAsleep(history: StoredMessage[], cid: string): boolean {
  const msg = history.find((m) => m.cid === cid);
  if (!msg || msg.waiting === "asleep") return false;
  msg.waiting = "asleep";
  return true;
}

/**
 * La note de sommeil ne se montre que tant qu'elle n'a rien dit depuis : sa
 * réponse au réveil (ou n'importe quelle parole qui suit, pas un murmure)
 * la rend caduque, même arrivée par un rattrapage après un rechargement.
 */
export function asleepNoteShown(history: StoredMessage[], index: number): boolean {
  const msg = history[index];
  if (!msg || msg.waiting !== "asleep") return false;
  return !history
    .slice(index + 1)
    .some((m) => m.sender === "vtuber" && !m.inner);
}

/**
 * Attach a server id to the optimistic bubble a reply refers to.
 *
 * Done as the reply arrives rather than at the next history merge, so the
 * cursor keeps moving during a normal conversation and a later reconnect
 * asks for a small gap instead of the whole window.
 */
export function bindServerId(
  history: StoredMessage[],
  cid: string,
  userId?: number
): boolean {
  const msg = history.find((m) => m.cid === cid);
  if (!msg) return false;
  if (typeof userId === "number") msg.id = userId;
  msg.status = "sent";
  // Quoi que dise cette trame (sa réponse au réveil, un silence choisi), elle
  // n'est plus en train de dormir sur ce message.
  msg.waiting = undefined;
  return true;
}

/**
 * Ce que montre la bulle d'un message avec des fichiers : `texte [a.png,
 * b.pdf]`, ou `[a.png]` sans légende. La même composition à l'envoi et au
 * rechargement — c'est ce qui permet de reconnaître sa propre bulle.
 */
export function withAttachments(text: string, names: string[]): string {
  const label = names.filter((n) => typeof n === "string" && n).join(", ");
  if (!label) return text;
  return text ? `${text} [${label}]` : `[${label}]`;
}

const FILE_ID = /^[0-9a-f]{32}$/;

/**
 * Les fichiers d'un message de Mika, tels qu'on peut les afficher sans
 * danger : un identifiant de 32 caractères hexadécimaux, et une adresse qui
 * est exactement `/files/<id>` (jamais une autre page, jamais un autre hôte).
 * Ce qui ne passe pas est ignoré.
 */
export function sentFiles(raw: unknown): SentFile[] {
  if (!Array.isArray(raw)) return [];
  const out: SentFile[] = [];
  for (const a of raw as Array<Partial<SentFile> | null>) {
    if (!a || typeof a.id !== "string" || !FILE_ID.test(a.id)) continue;
    if (a.url !== `/files/${a.id}`) continue;
    out.push({
      id: a.id,
      name: typeof a.name === "string" && a.name ? a.name : "fichier",
      kind: a.kind === "image" ? "image" : "file",
      mime: typeof a.mime === "string" ? a.mime : undefined,
      size: typeof a.size === "number" ? a.size : undefined,
      url: a.url,
      available: a.available !== false,
    });
  }
  return out;
}

function attachmentNames(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((a: Partial<HistoryAttachment> | null) =>
      a && typeof a.name === "string" ? a.name : ""
    )
    .filter((n) => n);
}

/**
 * Does this server row belong to a bubble we painted ourselves?
 *
 * The server now sends what was typed (`text`) and the files by name
 * (`attachments`) apart from what the preprocessors made of them (ADR 0056),
 * so the display both sides compose is the same: exact equality is the
 * rule. `matchText` — what was typed — still adopts a bubble whose files
 * did not all make it (the server dropped one, or cleaned its name), never
 * an attachment-only bubble (nothing to anchor on: it stays recognisable
 * through its `client_msg_id`). The old prefix rule (« what we typed,
 * extended by the preprocessors ») is gone with the reason it existed.
 */
function matches(msg: StoredMessage, display: string, typed: string): boolean {
  if (msg.text === display) return true;
  if (msg.sender !== "user" || !msg.matchText) return false;
  return typed === msg.matchText;
}

/**
 * Fold the server's version of the conversation into what is displayed.
 *
 * Three cases per incoming row:
 *  - already held (by id) → ignore;
 *  - matches an un-bound bubble we painted ourselves → adopt its id rather
 *    than draw it twice;
 *  - otherwise → new, insert it.
 *
 * The middle case is what a reconnect needs: a message flushed from the
 * outbox has no id until the server answers, so without it every reconnect
 * duplicated whatever was in flight.
 *
 * Mutates and returns `history`, sorted. `added` counts genuinely new rows,
 * `adopted` counts bubbles that gained a server id (a mutation the caller
 * must persist, or the cursor regresses at the next reload and the client
 * re-asks for what it already has), and `sawReply` says whether any of them
 * was Mika's — the caller uses it to decide whether anything is still being
 * awaited.
 */
export function mergeHistory(
  history: StoredMessage[],
  entries: HistoryEntry[],
  maxMessages: number
): {
  history: StoredMessage[];
  added: number;
  adopted: number;
  sawReply: boolean;
} {
  const known = new Set(
    history.map((m) => m.id).filter((id): id is number => typeof id === "number")
  );

  let added = 0;
  let adopted = 0;
  let sawReply = false;

  for (const entry of entries ?? []) {
    if (typeof entry?.id !== "number" || known.has(entry.id)) continue;
    const sender = entry.role === "user" ? "user" : "vtuber";
    const typed = typeof entry.text === "string" ? entry.text : "";
    // Sa bulle comme à l'envoi : ce qu'elle a tapé, ses fichiers par leur nom
    // — jamais ce que les préprocesseurs en ont tiré.
    const text =
      sender === "vtuber"
        ? stripProsody(typed)
        : withAttachments(typed, attachmentNames(entry.attachments));
    if (!text) continue;

    if (sender === "vtuber") sawReply = true;

    const mine = history.find(
      (m) => m.id === undefined && m.sender === sender && matches(m, text, typed)
    );
    const files = sender === "vtuber" ? sentFiles(entry.attachments) : [];
    if (mine) {
      mine.id = entry.id;
      mine.ts = entry.ts ?? mine.ts;
      if (files.length && !mine.files?.length) mine.files = files;
      if (sender === "user") {
        mine.status = "sent";
        mine.reason = undefined;
      }
      adopted += 1;
    } else {
      history.push({
        text,
        sender,
        ts: entry.ts ?? Date.now(),
        id: entry.id,
        status: sender === "user" ? "sent" : undefined,
        ...(files.length ? { files } : {}),
      });
      added += 1;
    }
    known.add(entry.id);
  }

  sortMessages(history);
  if (history.length > maxMessages) {
    history = history.slice(-maxMessages);
  }
  return { history, added, adopted, sawReply };
}

// ── Le fil d'une autre vie (ADR 0056) ─────────────────────────────────

/**
 * Ce que le navigateur garde du fil : ses messages, et l'empreinte de la vie
 * d'où ils viennent (`HistoryMessage.life`).
 *
 * Sans empreinte, un cache survivait au changement de moteur : l'ancien
 * envoyait la clé Django d'un message, le nouveau le `seq` de son journal,
 * qui repart de quelques dizaines, sous la **même** clé de cache
 * (`user_<n>`). Le curseur de l'ancien fil cachait alors le nouveau, et ses
 * identifiants passaient pour des messages déjà connus.
 */
export interface CachedThread {
  life: string;
  messages: unknown[];
}

/** Relire le cache : `{life, messages}`, ou un simple tableau (un cache d'avant
 * l'empreinte, donc d'une vie inconnue). Illisible : rien. */
export function readCache(raw: string | null): CachedThread {
  if (!raw) return { life: "", messages: [] };
  try {
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed)) return { life: "", messages: parsed };
    if (parsed && typeof parsed === "object") {
      const { life, messages } = parsed as { life?: unknown; messages?: unknown };
      return {
        life: typeof life === "string" ? life : "",
        messages: Array.isArray(messages) ? messages : [],
      };
    }
  } catch {
    // illisible : comme vide
  }
  return { life: "", messages: [] };
}

export function writeCache(life: string, messages: StoredMessage[]): string {
  return JSON.stringify({ life, messages });
}

/**
 * Ce que montre l'écran vient-il d'une autre vie que celle qui parle ?
 *
 * Oui quand le serveur le dit (`reset` : le curseur dépassait la tête de ce
 * fil — une sauvegarde plus ancienne restaurée, un fil oublié), ou quand son
 * empreinte n'est pas celle du cache — un cache **sans** empreinte compris :
 * il vient de l'ancien moteur. Un serveur qui n'envoie pas d'empreinte ne
 * fait rien vider (on ne sait pas).
 */
export function fromAnotherLife(
  cachedLife: string,
  frame: { life?: unknown; reset?: unknown }
): boolean {
  if (frame.reset === true) return true;
  return typeof frame.life === "string" && frame.life !== "" && frame.life !== cachedLife;
}

/**
 * Ce qui survit au changement de vie : seulement les messages de cet onglet
 * encore en partance (`pending`, dans la file d'envoi) — ils partiront vers
 * la vie qui parle. Tout le reste (identifiants d'ailleurs, pensées, échecs
 * d'avant) est vidé avant de fusionner le fil du serveur.
 */
export function keepAcrossLives(history: StoredMessage[]): StoredMessage[] {
  return history.filter(
    (m) => m.sender === "user" && m.id === undefined && m.status === "pending"
  );
}

// ── Repères de temps dans le fil ──────────────────────────────────────

/**
 * Un repère posé avant une bulle : le jour qui commence (« Aujourd'hui »,
 * « Hier », « lundi 28 septembre »), ou l'heure d'une reprise après un long
 * silence dans la même journée (« 18 h 05 »).
 *
 * Mika raisonne sur le temps vécu (ADR 0041) — « comme tu me disais hier
 * soir », « ça faisait une semaine » — alors que le fil empilait cinquante
 * bulles sur plusieurs jours sans rien entre elles, et que l'heure d'un
 * message ne se lisait qu'au survol.
 */
export interface TimeMarker {
  kind: "day" | "resume";
  label: string;
}

/** Au-delà de ce silence dans une même journée, la reprise dit son heure. */
export const RESUME_GAP_MS = 3 * 60 * 60 * 1000;

/**
 * En deçà de cet écart, deux messages se suivent, même de part et d'autre de
 * minuit : une bulle optimiste porte l'heure du navigateur, sa réponse
 * relue celle du serveur, et quelques secondes de désaccord entre les deux
 * horloges ne doivent pas glisser un jour entre une question et sa réponse.
 * Un échange qui enjambe minuit reste sous le jour où il a commencé jusqu'à
 * sa première pause.
 */
export const CLOCK_SKEW_MS = 5 * 60 * 1000;

const WEEKDAYS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];
const MONTHS = [
  "janvier", "février", "mars", "avril", "mai", "juin",
  "juillet", "août", "septembre", "octobre", "novembre", "décembre",
];

/** Le jour local du navigateur, comparable par égalité. */
function localDayKey(d: Date): number {
  return d.getFullYear() * 10000 + d.getMonth() * 100 + d.getDate();
}

/** « Aujourd'hui », « Hier », sinon « lundi 28 septembre » (l'année si ce n'est pas celle-ci). */
function dayLabel(t: number, now: number): string {
  const d = new Date(t);
  const today = new Date(now);
  const key = localDayKey(d);
  if (key === localDayKey(today)) return "Aujourd'hui";
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  if (key === localDayKey(yesterday)) return "Hier";
  const date = d.getDate() === 1 ? "1er" : String(d.getDate());
  const label = `${WEEKDAYS[d.getDay()]} ${date} ${MONTHS[d.getMonth()]}`;
  return d.getFullYear() === today.getFullYear() ? label : `${label} ${d.getFullYear()}`;
}

/** « 18 h 05 ». */
function hourLabel(t: number): string {
  const d = new Date(t);
  return `${d.getHours()} h ${String(d.getMinutes()).padStart(2, "0")}`;
}

/**
 * Les repères à poser avant chaque message du fil, dans l'ordre affiché :
 * `markers[i]` précède `history[i]`, `null` quand il n'y a rien à dire.
 *
 * Calculés à chaque rendu à partir de `ts`, jamais stockés : ni le cache ni
 * le curseur n'en savent rien, et « Aujourd'hui » devient « Hier » au premier
 * rendu après minuit. Trois précautions, parce que tous les `ts` ne se valent
 * pas :
 *  - l'heure ne recule jamais : un message rangé plus bas (par son
 *    identifiant) mais horodaté plus tôt par une autre horloge reste dans le
 *    jour de ce qui le précède ;
 *  - un message rangé par `after` (pensée murmurée, rapport de projet) est
 *    placé par le curseur, pas par l'heure : il ne dépasse pas l'heure du
 *    message qui le suit, sans quoi une pensée arrivée après minuit, rangée
 *    avant une réponse relue de la veille, faisait naître un jour fantôme ;
 *  - un écart de moins de `CLOCK_SKEW_MS` ne change jamais de jour.
 */
export function timeMarkers(history: StoredMessage[], now: number): Array<TimeMarker | null> {
  // L'heure retenue pour chacun, de la fin vers le début : un message rangé
  // par `after` est borné par le suivant ; un `ts` illisible (un cache
  // d'avant) n'en a pas.
  const times: Array<number | undefined> = new Array(history.length);
  let next: number | undefined;
  for (let i = history.length - 1; i >= 0; i--) {
    const m = history[i];
    const own = Number.isFinite(m.ts) && m.ts > 0 ? m.ts : undefined;
    if (m.id === undefined && m.after !== undefined) {
      const bound = Math.min(own ?? Infinity, next ?? Infinity);
      times[i] = Number.isFinite(bound) ? bound : undefined;
    } else {
      times[i] = own;
      if (own !== undefined) next = own;
    }
  }

  const markers: Array<TimeMarker | null> = [];
  let previous: number | undefined;
  let day: number | undefined;
  for (const t of times) {
    if (t === undefined) {
      markers.push(null);
      continue;
    }
    const at = previous === undefined ? t : Math.max(previous, t);
    const key = localDayKey(new Date(at));
    let marker: TimeMarker | null = null;
    if (previous === undefined) {
      marker = { kind: "day", label: dayLabel(at, now) };
      day = key;
    } else if (key !== day) {
      if (at - previous >= CLOCK_SKEW_MS) {
        marker = { kind: "day", label: dayLabel(at, now) };
        day = key;
      }
    } else if (at - previous >= RESUME_GAP_MS) {
      marker = { kind: "resume", label: hourLabel(at) };
    }
    markers.push(marker);
    previous = at;
  }
  return markers;
}
