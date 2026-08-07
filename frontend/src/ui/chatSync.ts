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

import type { HistoryEntry, RejectedAttachment } from "../types";

/**
 * What happened to a message the user sent.
 *
 * - `pending`  — painted locally, still in the transport's outbox.
 * - `sent`     — the server acknowledged receiving it (not answering it).
 * - `failed`   — refused, and it will never be answered.
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
   * What the server stores for this message, when it differs from what is
   * displayed. A message carrying files is painted as `texte [photo.png]`
   * while the row holds `texte` alone, so matching on the bubble's text
   * could never adopt it and a reconnect drew it twice.
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
  overloaded: "Mika est saturée, réessaie dans un instant",
  too_long: "message trop long",
  attachments_rejected: "pièces jointes refusées (format ou taille)",
  frame_too_large: "envoi trop volumineux — retire une pièce jointe",
  send_abandoned: "envoi abandonné après plusieurs tentatives",
};

/** French wording for a refusal status, for display. */
export function ackReason(status: string): string {
  return ACK_REASONS[status] ?? "refusé par le serveur";
}

/** Pourquoi une pièce jointe n'est pas passée (backend/pipeline/media.py). */
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

/** Record what the server said became of a message we sent. */
export function applyAck(
  history: StoredMessage[],
  cid: string,
  status: string,
  rejected?: RejectedAttachment[]
): { changed: boolean; failed: boolean } {
  const msg = history.find((m) => m.cid === cid);
  if (!msg) return { changed: false, failed: false };
  const failed = status !== "accepted";
  msg.status = failed ? "failed" : "sent";
  msg.reason = failed ? ackReason(status) : undefined;
  // Un envoi partiel repart avec le statut `accepted` : sans cette note, la
  // bulle affiche trois fichiers dont un que Mika n'a jamais reçu.
  msg.note = rejected?.length ? rejectedNote(rejected) : undefined;
  return { changed: true, failed };
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
  return true;
}

/**
 * Does this server row belong to a bubble we painted ourselves?
 *
 * Exact text is the normal answer. A message carrying files is the one
 * case where the two sides legitimately differ, and they differ *twice*:
 * the bubble shows `regarde ça [photo.png]` while the row holds the
 * caption **plus whatever the preprocessors made of the files** —
 * `regarde ça [image: un chat roux dort sur un canapé]`. So the stored
 * text is neither what we typed nor a substring of what we displayed; it
 * is what we typed, extended. Hence the prefix rule, deliberately
 * narrowed to user messages carrying a non-empty `matchText`: an
 * attachment-only message has nothing to anchor on and would otherwise
 * match any user row at all. It stays recognisable through its
 * `client_msg_id` instead.
 */
function matches(msg: StoredMessage, serverText: string): boolean {
  if (msg.text === serverText) return true;
  if (msg.sender !== "user" || !msg.matchText) return false;
  return serverText === msg.matchText || serverText.startsWith(msg.matchText);
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
    const text =
      sender === "vtuber" ? stripProsody(entry.text ?? "") : entry.text ?? "";
    if (!text) continue;

    if (sender === "vtuber") sawReply = true;

    const mine = history.find(
      (m) => m.id === undefined && m.sender === sender && matches(m, text)
    );
    if (mine) {
      mine.id = entry.id;
      mine.ts = entry.ts ?? mine.ts;
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
