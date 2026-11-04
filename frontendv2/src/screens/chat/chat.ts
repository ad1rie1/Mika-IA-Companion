/**
 * Le chat : la conversation avec Mika, et le mode pro d'une opératrice (ADR 0116 : outils en direct, une
 * bulle en Markdown ; ADR 0164 : les fils de travail ; ADR 0064/0170 : les cartes d'accord et « Tout
 * accepter » ; ADR 0113 : 👍/👎 ; ADR 0119 : la bulle de sa position ; ADR 0112 : ses bulles l'une après
 * l'autre).
 *
 * Le comportement est celui du client web (`frontend/Web/src/ui/ChatOverlay.ts`), par les mêmes modules purs
 * (`@web/ui/chatSync`, `approvals`, `toolActivity`, `strands`, `verdicts`, `bubbles`, `messageNotes`) ; le
 * rendu, celui de la maquette (`markup.ts`). Le contrat : `backendv2/docs/protocole-chat.md`.
 */
import { API_BASE } from "@web/network/api";
import type { WebSocketClient } from "@web/network/WebSocketClient";
import type {
  AckMessage,
  ApprovalDecision,
  ChatMode,
  HistoryMessage,
  MessageNote,
  SentFile,
  SpeechMessage,
  StrandResultMessage,
  Verdict,
  VerdictResultMessage,
} from "@web/types";
import { BubbleReveal, splitBubbles } from "@web/ui/bubbles";
import {
  applyAck,
  bindServerId,
  cursorOf,
  fromAnotherLife,
  keepAcrossLives,
  markAsleep,
  mergeHistory,
  MAX_STRANDS_CACHED,
  nextClientMsgId,
  proMode,
  readCache,
  replyText,
  restoredStatus,
  sentFiles,
  threadOf,
  trimThreads,
  withAttachments,
  writeCache,
  type MessageStatus,
  type StoredMessage,
} from "@web/ui/chatSync";
import {
  approvalKey,
  approvalResult,
  autoAcceptFrame,
  decisionFrame,
  EMPTY_APPROVALS,
  isDecisionTaken,
  nextRefreshDelay,
  resultMessage,
  withApprovals,
  withConnection,
  withDecisionSent,
  withResult,
  type ApprovalsState,
} from "@web/ui/approvals";
import { insertEmoji } from "@web/ui/emojis";
import { messageNotes } from "@web/ui/messageNotes";
import {
  COMMANDS,
  localStrand,
  newStrandId,
  parseCommand,
  parseStrands,
  STRAND_DESCRIPTION_MAX,
  STRAND_TITLE_MAX,
  strandLabel,
  strandOf,
  suggestCommands,
  unescapeSlash,
  withLocal,
  type StrandCommand,
  type StrandInfo,
} from "@web/ui/strands";
import { cardKey, isRunning, toolFrame, toolUses, withAnswer, withToolFrame, type WorkCard } from "@web/ui/toolActivity";
import { applyVerdict, COMMENT_MAX, nextVerdict, verdictError, verdictFrame } from "@web/ui/verdicts";
import { $, h, norm, on } from "../../shell/dom";
import { closeModal, openMenu, openModal, toast, type MenuItem } from "../../shell/float";
import { ico } from "../../shell/icons";
import type { PaletteEntry } from "../../shell/palette";
import type { Account, ScreenContext, ScreenDef, Shell } from "../../shell/shell";
import type { MikaSnapshot, MikaStore } from "../../mika/store";
import { facetsOf, percent, statusLine, type LinkState } from "../../mika/view";
import {
  accordToggle,
  approvalsMarkup,
  attachmentsMarkup,
  cardKinds,
  elsewhere,
  type CardKind,
  composerMarkup,
  filesTable,
  strandHead,
  strandsPane,
  threadMarkup,
  type ApprovalNote,
  type PendingAttachment,
} from "./markup";

/** Ce que le champ accepte en pièces jointes (les plafonds du serveur, `pipeline/media.py`). */
const ACCEPTED_TYPES = [
  "image/jpeg", "image/png", "image/gif", "image/webp",
  "audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg", "audio/webm",
  "text/plain", "text/csv", "text/markdown", "application/json",
  "application/pdf",
].join(",");
const MAX_FILE_SIZE = 5 * 1024 * 1024;
const MAX_ATTACHMENTS = 5;
/** Les messages gardés par fil, dans l'écran et dans le cache (ceux que le serveur rend à l'ouverture). */
const MAX_MESSAGES = 50;
/** La longueur maximale d'un message, celle du serveur (`adapters/web/protocol.py::MAX_MESSAGE_CHARS`). */
export const MAX_MESSAGE_CHARS = 2000;
const COUNTER_FROM = 1800;
/** « Mika écrit… » ne survit pas plus longtemps sans réponse (le tour entier peut attendre longtemps). */
const TYPING_TIMEOUT_MS = 300_000;
const APPROVAL_NOTE_MS = 6000;
const STRAND_NOTE_MS = 6000;
const OFFLINE_NOT_SENT = "Hors ligne : ta décision n'est pas partie. Réessaie à la reconnexion.";

/** Le fil gardé par ce navigateur, pour ce compte seulement. */
export const CACHE_PREFIX = "mika2_chat";
const PRO_KEY = "mika2_chat_pro";
/** « Tout accepter » (ADR 0170) : retenu par l'onglet seulement. */
const AUTO_KEY = "mika2_chat_auto_accept";
const STRAND_PREFIX = "mika2_chat_strand";

const STRAND_RESULT_NOTES: Record<string, string> = {
  invalid: "Réglage refusé : un champ est trop long.",
  forbidden: "Réglage refusé : réservé à une opératrice.",
  failed: "Le réglage n'a pas abouti — réessaie.",
};

const EMOJIS = ["😊", "😅", "😂", "🙂", "😉", "😍", "🥲", "😴", "🤔", "😬", "🙏", "👍", "👌", "🔥", "✨", "❤️", "💪", "🎉", "☕", "🌧️", "🚶", "📎", "✅", "❌"];

function read(storage: () => Storage, key: string): string | null {
  try {
    return storage().getItem(key);
  } catch {
    return null;
  }
}

function write(storage: () => Storage, key: string, value: string | null): void {
  try {
    if (value === null) storage().removeItem(key);
    else storage().setItem(key, value);
  } catch {
    // stockage fermé : le choix vaut pour cette page
  }
}

/** Le temps que sa bouche bouge pour une bulle : un peu moins que de la lire à voix haute. */
export function talkMs(text: string): number {
  return Math.min(5000, Math.max(900, text.length * 45));
}

/** « 7,2 Mo » — un refus qui donne la taille dit du même coup pourquoi. */
function megabytes(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} Mo`;
}

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result ?? "");
      resolve(result.split(",")[1] ?? result);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

/** Supprimer les fils gardés d'un autre compte (un navigateur partagé). */
export function dropForeignCaches(ownKey: string): void {
  try {
    const doomed: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(`${CACHE_PREFIX}:`) && key !== ownKey) doomed.push(key);
    }
    for (const key of doomed) localStorage.removeItem(key);
  } catch {
    // stockage fermé : rien de gardé, rien à nettoyer
  }
}

export class ChatScreen {
  private ws: WebSocketClient | null = null;
  private history: StoredMessage[] = [];
  private life = "";
  private truncated = false;
  private readonly cacheKey: string;
  private readonly strandKey: string;

  private approvals: ApprovalsState = EMPTY_APPROVALS;
  private readonly autoAccepted = new Set<string>();
  private autoPreferred: boolean;
  private approvalNote: ApprovalNote | null = null;
  private approvalNoteTimer: number | null = null;
  private approvalTimer: number | null = null;
  private readonly approvalOpen = new Set<number>();
  /** Ce que veut faire chaque carte (sa capacité, son brouillon), relevé dans la trame brute. */
  private cardKinds = new Map<number, CardKind>();

  private work: readonly WorkCard[] = [];
  private readonly openWork = new Set<string>();

  private strands: StrandInfo[] = [];
  private localStrands: StrandInfo[] = [];
  private activeStrand: string;
  private showArchived = false;
  private strandNote = "";
  private strandNoteTimer: number | null = null;
  private readonly unreadStrands = new Set<string>();
  private readonly strandsAsked = new Set<string>();

  private proPreferred: boolean;
  /** Le fil où « Mika écrit… » attend sa réponse (`""` : le fil avec elle) ; `null` : elle n'écrit pas. */
  private typingThread: string | null = null;
  private typingTimer: number | null = null;

  private readonly verdictPending = new Map<number, { verdict?: Verdict; note?: string }>();
  private readonly verdictErrors = new Map<number, string>();

  private pending: PendingAttachment[] = [];
  private notices: string[] = [];
  private link: LinkState = "connecting";
  private search: string | null = null;

  private body: HTMLElement | null = null;
  private mounted: "ordinary" | "pro" | null = null;
  /** Le fil suit le bas tant qu'on y est : une image qui se charge, une bulle qui arrive le gardent en vue. */
  private stick = true;
  private resize: ResizeObserver | null = null;
  /** Sa réponse qui s'écrit bulle par bulle (ADR 0112) : « Mika écrit… » entre deux, sa bouche à chacune. */
  private readonly reveal = new BubbleReveal<StoredMessage>((done) => {
    this.paintThread();
    this.store.talk(1400);
    if (done) this.hideTyping();
    else this.showTyping("");
  });

  constructor(
    private readonly shell: Shell,
    private readonly store: MikaStore,
    private readonly account: Account,
  ) {
    const who = account.personId || account.username;
    this.cacheKey = `${CACHE_PREFIX}:${who}`;
    this.strandKey = `${STRAND_PREFIX}:${who}`;
    dropForeignCaches(this.cacheKey);
    this.proPreferred = read(() => localStorage, PRO_KEY) === "1";
    this.autoPreferred = read(() => sessionStorage, AUTO_KEY) === "1";
    this.activeStrand = strandOf(read(() => localStorage, this.strandKey)) ?? "";
    this.restore();
    store.subscribe((snap) => this.paintMika(snap));
    document.addEventListener("keydown", (e) => this.focusOnType(e));
  }

  // ── Le compte et les modes ────────────────────────────────────────

  private get operator(): boolean {
    return this.account.operator;
  }

  /** Le prochain message part-il en mode pro ? Seulement pour une opératrice qui l'a choisi. */
  private get proMode(): boolean {
    return this.operator && this.proPreferred;
  }

  private get autoAccept(): boolean {
    return this.operator && this.autoPreferred;
  }

  /** Le fil que l'écran montre : en mode pro, le fil de travail actif ; sinon le fil avec elle (`""`). */
  private get viewThread(): string {
    return this.proMode ? this.activeStrand : "";
  }

  /** Oublier le fil de ce navigateur (la déconnexion : un navigateur partagé ne le garde pas). */
  forget(): void {
    write(() => localStorage, this.cacheKey, null);
  }

  // ── La connexion ──────────────────────────────────────────────────

  /** Brancher le chat sur une connexion (neuve après une reconnexion du compte). */
  bind(ws: WebSocketClient): void {
    this.ws = ws;
    ws.setCursorProvider(() => cursorOf(this.history));
    ws.on("speech", (d) => this.onSpeech(d));
    ws.on("tool", (d) => this.onTool(d));
    ws.on("ack", (d) => this.onAck(d));
    ws.on("history", (d) => this.onHistory(d));
    ws.on("verdict_result", (d) => this.onVerdictResult(d));
    ws.on("strands", (d) => this.onStrands(d));
    ws.on("strand_result", (d) => this.onStrandResult(d));
    ws.on("approvals", (d) => this.onApprovals(d.items));
    ws.on("approval_result", (d) => this.onApprovalResult(d));
    ws.on("connection", (d) => {
      this.approvals = withConnection(this.approvals, d.status);
      if (d.status === "connected") this.autoAccepted.clear();
      this.link =
        d.status === "connected" ? "connected" : d.status === "unauthorized" ? "unauthorized" : d.status === "reconnecting" ? "connecting" : "offline";
      this.store.setLink(this.link);
      this.paintApprovals();
      this.refreshHead();
      if (d.status === "unauthorized") this.failPending("session expirée — reconnecte-toi");
    });
  }

  // ── Le cache ──────────────────────────────────────────────────────

  private restore(): void {
    const cached = readCache(read(() => localStorage, this.cacheKey));
    this.life = cached.life;
    const stored = cached.messages as Array<Partial<StoredMessage> | null>;
    this.history = stored
      .filter(
        (m): m is StoredMessage => !!m && typeof m.text === "string" && (m.sender === "user" || m.sender === "vtuber"),
      )
      .map((m): StoredMessage => {
        // un « en attente » restauré ment : la file qui l'aurait fait partir était dans l'onglet d'avant
        const { status, reason } = restoredStatus(m.status);
        const restored: StoredMessage = reason ? { ...m, status, reason } : { ...m, status };
        restored.mode = proMode(m.mode);
        const tools = toolUses(m.tools);
        restored.tools = tools.length ? tools : undefined;
        const notes = m.sender === "vtuber" ? messageNotes(m.notes) : [];
        restored.notes = notes.length ? notes : undefined;
        restored.files = m.sender === "vtuber" ? sentFiles(m.files) : undefined;
        if (!restored.files?.length) delete restored.files;
        restored.strand = strandOf(m.strand);
        if (!restored.strand) delete restored.strand;
        return restored;
      });
    this.history = trimThreads(this.history, MAX_MESSAGES, MAX_STRANDS_CACHED);
  }

  private persist(): void {
    write(() => localStorage, this.cacheKey, writeCache(this.life, this.history));
  }

  // ── Les trames ────────────────────────────────────────────────────

  private onSpeech(data: SpeechMessage): void {
    this.store.mood(data);
    // une réponse qui s'écrivait encore se montre en entier : la suivante arrive
    this.reveal.finish();
    const strand = strandOf(data.strand);
    if ((strand ?? "") === this.typingThread) this.hideTyping();
    const pro = proMode(data.mode);
    const userId = typeof data.user_message_id === "number" ? data.user_message_id : null;
    const replyId = typeof data.message_id === "number" ? data.message_id : null;
    if (data.client_msg_id) {
      if (bindServerId(this.history, data.client_msg_id, userId ?? undefined)) this.persist();
      // elle dort : la réponse attend son réveil, une note le dit sous la bulle
      if (!data.text && data.voice_reason === "asleep" && markAsleep(this.history, data.client_msg_id)) {
        this.persist();
        this.paintThread();
      }
    }
    if (typeof data.text !== "string" || !data.text) {
      this.paintThread();
      return;
    }
    // un murmure n'a jamais d'identifiant : il se range après le curseur, pas en bas pour toujours
    const inner = data.voice_persona === "inner";
    if (pro) this.work = withAnswer(this.work, userId, replyId);
    this.addMessage(data.text, "vtuber", {
      id: replyId ?? undefined,
      localOnly: inner && replyId === null,
      inner,
      files: sentFiles(data.attachments),
      reveal: !inner && !pro,
      mode: pro,
      notes: messageNotes(data.notes),
      strand,
    });
    if (this.reveal.writing) this.showTyping("");
    if (strand && strand !== this.viewThread) {
      this.unreadStrands.add(strand);
      this.paintStrands();
    }
    if (!pro) this.store.talk(talkMs(splitBubbles(replyText(data.text))[0] ?? ""));
  }

  private onTool(raw: unknown): void {
    const frame = toolFrame(raw);
    if (!frame) return;
    const key = cardKey(frame);
    this.work = withToolFrame(this.work, frame);
    const card = this.work.find((c) => c.key === key);
    // la carte prend la place de « Mika écrit… »
    if (card && isRunning(card) && (card.strand ?? "") === this.typingThread) this.hideTyping();
    this.paintThread();
  }

  private onAck(data: AckMessage): void {
    const { changed, settled } = applyAck(this.history, data.client_msg_id, data.status, data.rejected_attachments, {
      reason: data.reason,
      detail: data.detail,
      href: data.href,
    });
    if (!changed) return;
    // un refus, ou une réponse qui ne viendra pas : « Mika écrit… » s'en va avec
    if (settled) this.hideTyping();
    this.persist();
    this.paintThread();
  }

  private onHistory(data: HistoryMessage): void {
    if (data.mode === "strand") {
      // un fil de travail relu (ADR 0164) : des lignes à fusionner, jamais un curseur ni une autre vie
      this.merge(data.messages ?? [], false, "catchup");
      return;
    }
    let wiped = false;
    if (fromAnotherLife(this.life, data)) {
      this.history = keepAcrossLives(this.history);
      this.truncated = false;
      this.work = [];
      wiped = true;
    }
    if (typeof data.life === "string" && data.life) this.life = data.life;
    this.merge(data.messages ?? [], data.truncated === true, data.mode === "initial" ? "initial" : "catchup", wiped);
  }

  private merge(entries: HistoryMessage["messages"], truncated: boolean, mode: "initial" | "catchup", wiped = false): void {
    const before = this.history.length;
    const result = mergeHistory(this.history, entries, MAX_MESSAGES);
    this.history = result.history;
    this.truncated = mode === "initial" ? truncated : this.truncated || truncated;
    const changed = wiped || result.added > 0 || result.adopted > 0 || result.judged > 0 || result.enriched > 0;
    if (!changed && this.history.length === before && !truncated) return;
    this.persist();
    this.paintThread();
    if (result.sawReply) this.hideTyping();
  }

  private addMessage(
    text: string,
    sender: "user" | "vtuber",
    opts: {
      id?: number;
      cid?: string;
      status?: MessageStatus;
      matchText?: string;
      localOnly?: boolean;
      inner?: boolean;
      files?: SentFile[];
      reveal?: boolean;
      mode?: "pro";
      notes?: MessageNote[];
      strand?: string;
    } = {},
  ): void {
    const display = sender === "vtuber" ? replyText(text, opts.mode) : text;
    if (!display) return;
    // une réponse peut arriver deux fois (en direct, puis dans le rattrapage d'une reconnexion)
    if (typeof opts.id === "number" && this.history.some((m) => m.id === opts.id)) return;
    const stored: StoredMessage = {
      text: display,
      sender,
      ts: Date.now(),
      id: opts.id,
      cid: opts.cid,
      status: opts.status,
      matchText: opts.matchText,
      after: opts.localOnly ? cursorOf(this.history) : undefined,
      inner: opts.inner || undefined,
      ...(opts.files?.length ? { files: opts.files } : {}),
      ...(opts.mode ? { mode: opts.mode } : {}),
      ...(opts.notes?.length ? { notes: opts.notes } : {}),
      ...(opts.strand ? { strand: opts.strand } : {}),
    };
    this.history.push(stored);
    if (opts.reveal && sender === "vtuber") this.reveal.start(stored, display);
    this.history = trimThreads(this.history, MAX_MESSAGES, MAX_STRANDS_CACHED);
    this.persist();
    this.paintThread(sender === "user");
  }

  private failPending(reason: string): void {
    let changed = false;
    for (const msg of this.history) {
      if (msg.sender === "user" && msg.status === "pending") {
        msg.status = "failed";
        msg.reason = reason;
        changed = true;
      }
    }
    if (!changed) return;
    this.hideTyping();
    this.persist();
    this.paintThread();
  }

  // ── « Mika écrit… » ───────────────────────────────────────────────

  private showTyping(thread: string = this.viewThread): void {
    this.typingThread = thread;
    if (this.typingTimer !== null) window.clearTimeout(this.typingTimer);
    this.typingTimer = window.setTimeout(() => this.hideTyping(), TYPING_TIMEOUT_MS);
    this.store.setTyping(true);
    this.paintTyping();
  }

  private hideTyping(): void {
    if (this.typingTimer !== null) window.clearTimeout(this.typingTimer);
    this.typingTimer = null;
    this.typingThread = null;
    this.store.setTyping(false);
    this.paintTyping();
  }

  private paintTyping(): void {
    const row = this.body ? $("[data-typing]", this.body) : null;
    if (!row) return;
    const shown = this.typingThread !== null && this.typingThread === this.viewThread;
    if (row.hidden === !shown) return;
    const scroller = row.closest<HTMLElement>("[data-scroll]");
    row.hidden = !shown;
    if (scroller && this.stick) scroller.scrollTop = scroller.scrollHeight;
  }

  // ── Les cartes d'accord ───────────────────────────────────────────

  private onApprovals(items: unknown): void {
    this.cardKinds = cardKinds(items);
    this.approvals = withApprovals(this.approvals, items);
    const ids = new Set(this.approvals.cards.map((c) => c.id));
    for (const id of [...this.approvalOpen]) if (!ids.has(id)) this.approvalOpen.delete(id);
    this.paintApprovals();
    this.autoAcceptPending();
  }

  private onApprovalResult(data: unknown): void {
    const result = approvalResult(data);
    if (!result) return;
    this.approvals = withResult(this.approvals, result.id);
    this.noteApproval(resultMessage(result.status), isDecisionTaken(result.status));
    this.paintApprovals();
  }

  private decide(id: number, decision: ApprovalDecision): void {
    const frame = decisionFrame(this.approvals, id, decision, Date.now());
    if (!frame) {
      // un bouton que le minuteur n'avait pas encore éteint : repeindre suffit
      this.paintApprovals();
      return;
    }
    if (!this.ws?.sendApproval(frame)) {
      this.noteApproval(OFFLINE_NOT_SENT, false);
      this.paintApprovals();
      return;
    }
    this.approvals = withDecisionSent(this.approvals, id);
    this.paintApprovals();
  }

  /** « Tout accepter » (ADR 0170) : la première carte acceptable part acceptée, une à la fois. */
  private autoAcceptPending(): void {
    if (!this.autoAccept || !this.ws) return;
    // un brouillon de mail ou une réponse Teams se décide là où il partira (ADR 0191) : jamais accepté d'office ici
    const here = { ...this.approvals, cards: this.approvals.cards.filter((c) => !elsewhere(this.cardKinds.get(c.id))) };
    const frame = autoAcceptFrame(here, Date.now(), this.autoAccepted);
    if (!frame || !this.ws.sendApproval(frame)) return;
    this.autoAccepted.add(approvalKey(frame));
    this.approvals = withDecisionSent(this.approvals, frame.id);
    this.paintApprovals();
  }

  private noteApproval(text: string, ok: boolean): void {
    if (this.approvalNoteTimer !== null) window.clearTimeout(this.approvalNoteTimer);
    this.approvalNote = { text, ok };
    this.approvalNoteTimer = window.setTimeout(() => {
      this.approvalNoteTimer = null;
      this.approvalNote = null;
      this.paintApprovals();
    }, APPROVAL_NOTE_MS);
  }

  private paintApprovals(): void {
    if (this.approvalTimer !== null) window.clearTimeout(this.approvalTimer);
    this.approvalTimer = null;
    const now = Date.now();
    const zone = this.body ? $("[data-approvals]", this.body) : null;
    if (zone) {
      zone.innerHTML = approvalsMarkup(this.approvals, now, {
        note: this.approvalNote,
        auto: this.autoAccept,
        open: this.approvalOpen,
        kinds: this.cardKinds,
      });
      zone.hidden = !zone.innerHTML.trim();
    }
    const delay = nextRefreshDelay(this.approvals.cards, now);
    if (delay !== null) {
      this.approvalTimer = window.setTimeout(() => {
        this.approvalTimer = null;
        this.paintApprovals();
      }, delay);
    }
  }

  // ── Les fils de travail (ADR 0164) ────────────────────────────────

  private get allStrands(): StrandInfo[] {
    const all = withLocal(this.strands, this.localStrands);
    if (this.activeStrand && !all.some((s) => s.id === this.activeStrand)) return [localStrand(this.activeStrand), ...all];
    return all;
  }

  private strandInfo(id: string): StrandInfo {
    return this.allStrands.find((s) => s.id === id) ?? localStrand(id);
  }

  /** En mode pro, un fil est toujours montré : le dernier choisi, sinon le plus récent, sinon un neuf. */
  private ensureStrand(): void {
    if (!this.proMode || this.activeStrand) return;
    const recent = this.allStrands.find((s) => !s.archived);
    this.activeStrand = recent?.id ?? newStrandId();
    write(() => localStorage, this.strandKey, this.activeStrand);
  }

  private onStrands(raw: unknown): void {
    this.strands = parseStrands(raw);
    const known = new Set(this.strands.map((s) => s.id));
    // un fil ouvert ici et resté vide s'en va, sauf celui qu'on regarde
    this.localStrands = this.localStrands.filter(
      (s) => !known.has(s.id) && (s.id === this.activeStrand || this.history.some((m) => m.strand === s.id)),
    );
    this.ensureStrand();
    if (this.proMode) this.askStrandHistory(this.activeStrand);
    this.paintStrands();
    this.refreshHead();
  }

  private onStrandResult(data: StrandResultMessage): void {
    const note = STRAND_RESULT_NOTES[data.status];
    if (note) this.noteStrand(note);
  }

  private selectStrand(id: string): void {
    this.activeStrand = id;
    write(() => localStorage, this.strandKey, id);
    this.unreadStrands.delete(id);
    this.askStrandHistory(id);
    this.paintStrands();
    this.paintThread(true);
    this.paintTyping();
    this.focusInput();
  }

  /** Un fil que le serveur connaît mieux que cet onglet : ses messages, une fois par session. */
  private askStrandHistory(id: string): void {
    const info = this.strands.find((s) => s.id === id);
    if (!info || this.strandsAsked.has(id) || !this.ws) return;
    const here = this.history.filter((m) => m.strand === id && m.id !== undefined).length;
    if (info.count <= here) return;
    if (this.ws.requestStrandHistory({ type: "strand_history", id })) this.strandsAsked.add(id);
  }

  private openNewStrand(): void {
    const id = newStrandId();
    this.localStrands = [localStrand(id), ...this.localStrands];
    this.selectStrand(id);
    this.refreshHead();
    toast("Fil neuf ouvert : rien n'est effacé.", { ico: "threads" });
  }

  private noteOpener(id: string, text: string): void {
    const local = this.localStrands.find((s) => s.id === id);
    if (!local || local.opener) return;
    this.localStrands = this.localStrands.map((s) => (s.id === id ? { ...s, opener: text } : s));
    this.paintStrands();
  }

  private setStrand(change: Partial<Pick<StrandInfo, "title" | "description" | "archived">>): void {
    const id = this.activeStrand;
    const next: StrandInfo = { ...this.strandInfo(id), ...change };
    const sent = this.ws?.sendStrand({
      type: "strand",
      id,
      title: next.title,
      description: next.description,
      archived: next.archived,
    });
    if (!sent) {
      this.noteStrand("Hors ligne : le réglage n'est pas parti.");
      return;
    }
    const known = this.strands.some((s) => s.id === id);
    this.strands = known ? this.strands.map((s) => (s.id === id ? next : s)) : this.strands;
    this.localStrands = known ? this.localStrands : [next, ...this.localStrands.filter((s) => s.id !== id)];
    this.paintStrands();
    this.refreshHead();
  }

  private runCommand(command: StrandCommand): void {
    switch (command.name) {
      case "clear":
        this.openNewStrand();
        return;
      case "rename":
        if (command.arg) this.setStrand({ title: command.arg.slice(0, STRAND_TITLE_MAX) });
        else this.editStrand();
        return;
      case "describe":
        if (command.arg) this.setStrand({ description: command.arg.slice(0, STRAND_DESCRIPTION_MAX) });
        else this.editStrand();
        return;
      case "archive":
        this.setStrand({ archived: true });
        toast("Fil archivé", { ico: "archive" });
        return;
      case "unarchive":
        this.setStrand({ archived: false });
        return;
      case "help":
        this.commandsMenu();
        return;
      case "unknown":
        this.noteStrand(`Commande inconnue : ${command.typed} — tape /aide.`);
        return;
    }
  }

  private noteStrand(text: string): void {
    this.strandNote = text;
    if (this.strandNoteTimer !== null) window.clearTimeout(this.strandNoteTimer);
    this.strandNoteTimer = window.setTimeout(() => {
      this.strandNote = "";
      this.strandNoteTimer = null;
      this.paintStrands();
    }, STRAND_NOTE_MS);
    this.paintStrands();
  }

  private editStrand(): void {
    const info = this.strandInfo(this.activeStrand);
    const el = openModal({
      title: "Le fil",
      size: "narrow",
      body: `<div class="stack"><label class="field"><span>Titre</span><input data-f="title" maxlength="${STRAND_TITLE_MAX}" value="${h(info.title)}" placeholder="${h(strandLabel(info))}"></label>
        <label class="field"><span>Petite description</span><textarea data-f="description" rows="3" maxlength="${STRAND_DESCRIPTION_MAX}" placeholder="Ce que Mika doit savoir de ce fil, et rien d'autre.">${h(info.description)}</textarea></label></div>`,
      foot: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn primary" type="button" data-ok>Enregistrer</button>`,
    });
    el.querySelector("[data-ok]")!.addEventListener("click", () => {
      const title = el.querySelector<HTMLInputElement>('[data-f="title"]')!.value.trim();
      const description = el.querySelector<HTMLTextAreaElement>('[data-f="description"]')!.value.trim();
      closeModal();
      this.setStrand({ title, description });
    });
  }

  private commandsMenu(anchor?: HTMLElement | null): void {
    const at: HTMLElement | null = anchor ?? (this.body ? $<HTMLElement>('[data-cmp="commandes"]', this.body) : null) ?? this.body;
    if (!at) return;
    const items: MenuItem[] = [
      { header: "Commandes du fil" },
      { label: "/clear — ouvrir un fil neuf", icon: "plus", action: () => this.runCommand({ name: "clear" }) },
      { label: "/renommer <titre>", icon: "pen", action: () => this.complete("renommer") },
      { label: "/description <texte>", icon: "threads", action: () => this.complete("description") },
      { label: "/archiver", icon: "archive", action: () => this.runCommand({ name: "archive" }) },
      { label: "/desarchiver", icon: "archive", action: () => this.runCommand({ name: "unarchive" }) },
      { label: "/aide — // en tête envoie un seul /", icon: "info", action: () => toast("// en tête envoie le message avec un seul /.", { ico: "info" }) },
    ];
    openMenu(at, items, { align: "left" });
  }

  /** Le champ prêt pour une commande à argument : « /renommer ». */
  private complete(word: string): void {
    const input = this.input();
    if (!input) return;
    const c = COMMANDS.find((x) => x.words.includes(word));
    input.value = c ? `/${c.words[0]}${c.usage.includes("<") ? " " : ""}` : `/${word} `;
    input.focus();
  }

  private strandsMenu(anchor: HTMLElement): void {
    const live = this.allStrands.filter((s) => !s.archived || s.id === this.activeStrand);
    openMenu(
      anchor,
      [
        { header: "Fils de travail" },
        ...live.map((s): MenuItem => ({
          label: strandLabel(s),
          icon: s.id === this.activeStrand ? "check" : "threads",
          action: () => this.selectStrand(s.id),
        })),
        "sep",
        { label: "Nouveau fil", icon: "plus", action: () => this.openNewStrand() },
      ],
      { align: "left" },
    );
  }

  private paintStrands(): void {
    if (!this.body || !this.proMode) return;
    const pane = $("[data-strands-pane]", this.body);
    if (pane) {
      pane.innerHTML = strandsPane(this.allStrands, this.activeStrand, {
        showArchived: this.showArchived,
        unread: this.unreadStrands,
        now: Date.now(),
      });
    }
    const head = $("[data-strand-head]", this.body);
    if (head) head.innerHTML = strandHead(this.strandInfo(this.activeStrand), this.strandNote);
  }

  // ── Ses réponses jugées (ADR 0113) ────────────────────────────────

  private judge(id: number, verdict: Verdict | "", note?: string): void {
    const msg = this.history.find((m) => m.id === id && m.sender === "vtuber");
    if (!msg || !this.ws) return;
    const comment = verdict ? (note ?? msg.verdictNote ?? "") : "";
    const before = { verdict: msg.verdict, note: msg.verdictNote };
    this.verdictErrors.delete(id);
    if (!this.ws.sendVerdict(verdictFrame(id, verdict, comment))) {
      this.verdictErrors.set(id, "Hors ligne : ton avis n'est pas parti.");
      this.paintThread();
      return;
    }
    if (!this.verdictPending.has(id)) this.verdictPending.set(id, before);
    applyVerdict(this.history, id, verdict, comment);
    this.persist();
    this.paintThread();
  }

  private onVerdictResult(data: VerdictResultMessage): void {
    const id = data.message_id;
    const before = this.verdictPending.get(id);
    this.verdictPending.delete(id);
    const error = verdictError(data.status);
    if (error) {
      if (before) applyVerdict(this.history, id, before.verdict ?? "", before.note ?? "");
      this.verdictErrors.set(id, error);
    } else {
      applyVerdict(this.history, id, data.verdict, data.comment ?? "");
      this.verdictErrors.delete(id);
    }
    this.persist();
    this.paintThread();
  }

  private verdictClick(id: number, clicked: Verdict): void {
    const msg = this.history.find((m) => m.id === id && m.sender === "vtuber");
    if (!msg) return;
    const next = nextVerdict(msg.verdict, clicked);
    this.judge(id, next);
    if (next === "ok") toast("Noté : bonne réponse.", { ico: "thumb-up" });
    if (next !== "ko") return;
    // 👎 : on dit d'ordinaire ce qu'elle aurait dû dire
    const el = openModal({
      title: "Ce qu'elle aurait dû dire",
      size: "narrow",
      body: `<p class="text-2 small" style="margin-bottom:8px">Ta version reste à côté de la sienne, comme exemple (ADR 0113).</p>
        <textarea rows="4" maxlength="${COMMENT_MAX}" data-f="note" placeholder="Ce qu'elle aurait dû répondre, ou pourquoi (facultatif)">${h(msg.verdictNote ?? "")}</textarea>`,
      foot: `<span class="grow"></span><button class="btn" type="button" data-close>Plus tard</button><button class="btn primary" type="button" data-ok>Enregistrer</button>`,
    });
    el.querySelector("[data-ok]")!.addEventListener("click", () => {
      const note = el.querySelector<HTMLTextAreaElement>('[data-f="note"]')!.value;
      closeModal();
      this.judge(id, "ko", note);
    });
  }

  // ── Les pièces jointes ────────────────────────────────────────────

  private async addFiles(files: FileList | File[]): Promise<void> {
    const list = Array.from(files);
    const room = MAX_ATTACHMENTS - this.pending.length;
    // chaque dépôt raconte son propre sort
    this.notices = [];
    const dropped = list.length - room;
    if (dropped > 0) {
      this.notices.push(
        dropped > 1
          ? `${dropped} fichiers ignorés : ${MAX_ATTACHMENTS} pièces jointes au plus.`
          : `1 fichier ignoré : ${MAX_ATTACHMENTS} pièces jointes au plus.`,
      );
    }
    for (const file of list.slice(0, Math.max(0, room))) {
      if (file.size > MAX_FILE_SIZE) {
        this.notices.push(`${file.name} ignoré : ${megabytes(file.size)} (${megabytes(MAX_FILE_SIZE)} au plus).`);
        continue;
      }
      try {
        this.pending.push({ name: file.name, type: file.type, size: file.size, data: await readBase64(file) });
      } catch {
        this.notices.push(`${file.name} illisible : non joint.`);
      }
    }
    this.paintAttachments();
  }

  private paintAttachments(): void {
    const zone = this.body ? $("[data-attach]", this.body) : null;
    if (!zone) return;
    zone.innerHTML = attachmentsMarkup(this.pending, this.notices);
    zone.hidden = !this.pending.length && !this.notices.length;
  }

  // ── L'envoi ───────────────────────────────────────────────────────

  private input(): HTMLTextAreaElement | null {
    return this.body ? $<HTMLTextAreaElement>("[data-chat-input]", this.body) : null;
  }

  private focusInput(): void {
    this.input()?.focus();
  }

  private send(): void {
    const input = this.input();
    if (!input || !this.ws) return;
    const typed = input.value.trim();
    if (!typed && !this.pending.length) return;
    // en mode pro, une commande (`/clear`…) agit sur les fils et ne part pas
    const command = this.proMode ? parseCommand(typed) : null;
    if (command) {
      this.clearInput(input);
      this.runCommand(command);
      return;
    }
    const text = this.proMode ? unescapeSlash(typed) : typed;
    const cid = nextClientMsgId();
    // le mode et le fil sont pris à l'envoi et voyagent avec la trame
    const mode: ChatMode = this.proMode ? "pro" : "";
    const pro = proMode(mode);
    const strand = pro ? this.activeStrand : undefined;
    let sent: boolean;
    if (this.pending.length) {
      // la même composition que le fil relu : la ligne du serveur reconnaîtra sa bulle
      const display = withAttachments(text, this.pending.map((a) => a.name));
      this.addMessage(display, "user", { cid, status: "pending", matchText: text, mode: pro, strand });
      sent = this.ws.sendChatWithAttachments(text, this.pending, cid, mode, strand);
      this.pending = [];
    } else {
      this.addMessage(text, "user", { cid, status: "pending", mode: pro, strand });
      sent = this.ws.sendChat(text, cid, mode, strand);
    }
    this.notices = [];
    this.paintAttachments();
    this.clearInput(input);
    if (strand) this.noteOpener(strand, text);
    // un message resté dans le navigateur n'est pas en train d'être répondu
    if (sent) this.showTyping();
  }

  private clearInput(input: HTMLTextAreaElement): void {
    input.value = "";
    this.resizeInput(input);
    this.paintCounter(input);
    this.ws?.noteComposing("");
  }

  private resizeInput(input: HTMLTextAreaElement): void {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
  }

  private paintCounter(input: HTMLTextAreaElement): void {
    const counter = this.body ? $("[data-counter]", this.body) : null;
    if (!counter) return;
    const n = input.value.length;
    counter.hidden = n < COUNTER_FROM;
    counter.textContent = `${n.toLocaleString("fr-FR")} / ${MAX_MESSAGE_CHARS.toLocaleString("fr-FR")}${n >= MAX_MESSAGE_CHARS ? " — la limite" : ""}`;
  }

  private emojis(anchor: HTMLElement): void {
    const menu = openMenu(
      anchor,
      [{ html: `<div class="emoji-grid">${EMOJIS.map((e) => `<button type="button" data-emo="${e}">${e}</button>`).join("")}</div>` }],
      { align: "left" },
    );
    on(menu, "[data-emo]", "click", (_e, b) => {
      const input = this.input();
      if (!input) return;
      const next = insertEmoji(input.value, input.selectionStart ?? input.value.length, input.selectionEnd ?? input.value.length, b.dataset.emo ?? "", MAX_MESSAGE_CHARS);
      if (!next) return;
      input.value = next.value;
      input.focus();
      input.setSelectionRange(next.caret, next.caret);
      this.ws?.noteComposing(input.value);
    });
  }

  /** Taper n'importe où (hors d'un champ) écrit dans le chat, comme dans le client web. */
  private focusOnType(e: KeyboardEvent): void {
    if (this.shell.ctx?.screen !== "chat" || e.ctrlKey || e.metaKey || e.altKey) return;
    const target = e.target as HTMLElement;
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target.isContentEditable) return;
    if (document.querySelector(".modal-scrim, .menu") || !document.getElementById("palette")?.hidden) return;
    if (e.key.length === 1) this.focusInput();
  }

  // ── L'écran ───────────────────────────────────────────────────────

  private refreshHead(): void {
    if (this.shell.ctx?.screen === "chat") this.shell.refreshHead();
  }

  private toggleMode(): void {
    this.proPreferred = !this.proPreferred;
    write(() => localStorage, PRO_KEY, this.proPreferred ? "1" : "0");
    this.ensureStrand();
    if (this.proMode) this.askStrandHistory(this.activeStrand);
    this.shell.refresh();
    toast(
      this.proMode ? "Mode pro : sans son caractère, ses outils en direct, tes fils de travail." : "Retour à la conversation avec Mika.",
      { ico: "terminal" },
    );
    this.focusInput();
  }

  private toggleAuto(): void {
    this.autoPreferred = !this.autoPreferred;
    write(() => sessionStorage, AUTO_KEY, this.autoPreferred ? "1" : "0");
    this.paintComposer();
    this.paintApprovals();
    this.autoAcceptPending();
  }

  private paintComposer(): void {
    const btn = this.body ? $('[data-cmp="accord"]', this.body) : null;
    if (!btn) return;
    const view = accordToggle(this.autoAccept);
    btn.innerHTML = view.html;
    btn.title = view.title;
    btn.classList.toggle("bolt", this.autoAccept);
    btn.setAttribute("aria-pressed", String(this.autoAccept));
  }

  private paintThread(toBottom = false): void {
    const el = this.body ? $("[data-thread]", this.body) : null;
    if (!el) return;
    const scroller = el.closest<HTMLElement>("[data-scroll]");
    if (toBottom) this.stick = true;
    const thread = this.viewThread;
    const query = this.search ? norm(this.search.trim()) : "";
    el.innerHTML = threadMarkup({
      messages: this.history.filter((m) => threadOf(m) === thread),
      cards: this.work.filter((c) => (c.strand ?? "") === thread),
      operator: this.operator,
      pro: this.proMode,
      shown: (m, total) => this.reveal.shown(m, total),
      split: splitBubbles,
      typing: this.typingThread !== null && this.typingThread === thread,
      openWork: this.openWork,
      verdictErrors: this.verdictErrors,
      truncated: this.truncated,
      now: Date.now(),
      api: API_BASE,
      filter: query ? (m) => norm(m.text).includes(query) : undefined,
    });
    if (scroller && this.stick && !query) scroller.scrollTop = scroller.scrollHeight;
  }

  /** Le fil défile dans son cadre : on suit le bas tant qu'on y est, même quand une image arrive après coup. */
  private followBottom(): void {
    this.resize?.disconnect();
    const scroller = this.body ? $("[data-scroll]", this.body) : null;
    const thread = this.body ? $("[data-thread]", this.body) : null;
    if (!scroller || !thread) return;
    // Seule la personne décroche du bas, en remontant : un fil qui grandit (une image chargée après coup) ne
    // fait jamais reculer le défilement, et ne la décroche donc pas.
    let last = scroller.scrollTop;
    scroller.addEventListener(
      "scroll",
      () => {
        const top = scroller.scrollTop;
        if (scroller.scrollHeight - top - scroller.clientHeight < 80) this.stick = true;
        else if (top < last - 2) this.stick = false;
        last = top;
      },
      { passive: true },
    );
    this.resize = new ResizeObserver(() => {
      if (this.stick && !this.search) scroller.scrollTop = scroller.scrollHeight;
    });
    this.resize.observe(thread);
    this.resize.observe(scroller);
  }

  private paintMika(snap: MikaSnapshot): void {
    const who = this.body ? $("[data-mika-who]", this.body) : null;
    const body = this.body ? $("[data-mika-body]", this.body) : null;
    if (!who || !body) return;
    const s = snap.state;
    const line = statusLine(s, { link: snap.link, typing: snap.typing, nowMs: Date.now() });
    who.innerHTML = `<b>Mika</b><span>${h(line.full)}</span>`;
    const sections: string[] = [];
    const facets = facetsOf(s.mood);
    sections.push(
      `<section><h4>Humeur</h4>${
        facets.length
          ? facets
              .map((f) => `<div class="facet"><span>${h(f.label)}</span><span class="bar"><i style="width:${Math.round(f.value * 100)}%"></i></span><span class="num">${percent(f.value)}</span></div>`)
              .join("")
          : `<p class="muted">Elle ne laisse rien paraître pour l'instant.</p>`
      }</section>`,
    );
    if (s.ruminations.length) {
      sections.push(`<section><h4>Elle repense à…</h4>${s.ruminations.slice(0, 2).map((r) => `<p>${h(r.summary)}</p>`).join("")}</section>`);
    }
    if (s.commitments.length) {
      sections.push(
        `<section><h4>Ce qu'elle t'a promis</h4>${s.commitments
          .slice(0, 5)
          .map((c) => `<div class="sc-line">${ico("check", "sm")}<span>${h(c)}</span></div>`)
          .join("")}</section>`,
      );
    }
    body.innerHTML = `${sections.join("")}<button class="btn sm ghost cm-more" type="button" data-more-state>${ico("sparkle", "sm")}Tout ce qu'elle fait</button>`;
  }

  private ordinarySkeleton(): string {
    return `<div class="chat-split"><div class="chat-wrap"><div class="chat-col">
        <div class="chat-scroll" data-scroll><div class="chat-thread" data-thread></div></div>
        <div class="chat-dock"><div class="ap-zone" data-approvals hidden></div>${composerMarkup({ pro: false, operator: this.operator, auto: this.autoAccept }, MAX_MESSAGE_CHARS, ACCEPTED_TYPES)}</div>
      </div></div>
      <aside class="chat-mika" aria-label="Mika">
        <div class="cm-scene" data-mika-scene></div>
        <div class="cm-who" data-mika-who></div>
        <div class="cm-body" data-mika-body></div>
      </aside></div>`;
  }

  private proSkeleton(): string {
    return `<div class="split pro-split">
        <aside class="pane fils-pane" data-strands-pane></aside>
        <section class="pane chat-pro">
          <div class="pane-head strand-head" data-strand-head></div>
          <div class="chat-scroll" data-scroll><div class="chat-thread wide" data-thread></div></div>
          <div class="chat-dock wide"><div class="ap-zone" data-approvals hidden></div>${composerMarkup({ pro: true, operator: this.operator, auto: this.autoAccept }, MAX_MESSAGE_CHARS, ACCEPTED_TYPES)}</div>
        </section></div>`;
  }

  private render(body: HTMLElement): void {
    this.body = body;
    const mode = this.proMode ? "pro" : "ordinary";
    if (this.mounted !== mode || !$("[data-thread]", body)) {
      const draft = this.input()?.value ?? "";
      body.innerHTML = mode === "pro" ? this.proSkeleton() : this.ordinarySkeleton();
      this.mounted = mode;
      const input = this.input();
      if (input && draft) {
        input.value = draft;
        this.resizeInput(input);
      }
      this.paintComposer();
      this.paintAttachments();
      this.paintStrands();
      this.paintMika(this.store.current);
      this.paintApprovals();
      this.followBottom();
      this.paintThread(true);
      return;
    }
    this.paintThread();
  }

  private mount(section: HTMLElement): void {
    on(section, "[data-head]", "click", (_e, b) => {
      if (b.dataset.head === "fichiers") {
        const thread = this.viewThread;
        openModal({
          title: "Les fichiers échangés",
          body: filesTable(this.history.filter((m) => threadOf(m) === thread), API_BASE, Date.now()),
        });
      }
      if (b.dataset.head === "chercher") {
        this.search = this.search === null ? "" : null;
        this.shell.refreshHead();
        this.paintThread(true);
        if (this.search !== null) $<HTMLInputElement>("[data-chat-q]", section)?.focus();
      }
    });
    section.addEventListener("input", (e) => {
      const target = e.target as HTMLElement;
      if (target.matches("[data-chat-q]")) {
        this.search = (target as HTMLInputElement).value;
        this.paintThread();
        return;
      }
      if (!target.matches("[data-chat-input]")) return;
      const input = target as HTMLTextAreaElement;
      this.resizeInput(input);
      this.paintCounter(input);
      this.ws?.noteComposing(input.value);
    });
    on(section, "[data-cmp]", "click", (_e, b) => {
      switch (b.dataset.cmp) {
        case "pro":
          this.toggleMode();
          break;
        case "accord":
          this.toggleAuto();
          break;
        case "envoyer":
          this.send();
          break;
        case "emoji":
          this.emojis(b);
          break;
        case "commandes":
          this.commandsMenu(b);
          break;
        case "joindre":
          $<HTMLInputElement>("[data-file]", section)?.click();
          break;
      }
    });
    section.addEventListener("change", (e) => {
      const target = e.target as HTMLInputElement;
      if (!target.matches("[data-file]") || !target.files) return;
      void this.addFiles(target.files).then(() => {
        target.value = "";
      });
    });
    on(section, "[data-unattach]", "click", (_e, b) => {
      this.pending.splice(Number(b.dataset.unattach), 1);
      this.notices = [];
      this.paintAttachments();
    });
    on(section, "[data-ap]", "click", (_e, b) => {
      this.decide(Number(b.dataset.id), b.dataset.ap === "accept" ? "accept" : "refuse");
    });
    // les dépliants restent comme on les a laissés d'un rendu à l'autre (`toggle` ne remonte pas : on le capte)
    section.addEventListener(
      "toggle",
      (e) => {
        const d = e.target as HTMLDetailsElement;
        if (d.dataset.work) {
          if (d.open) this.openWork.add(d.dataset.work);
          else this.openWork.delete(d.dataset.work);
        }
        if (d.dataset.apMore) {
          const id = Number(d.dataset.apMore);
          if (d.open) this.approvalOpen.add(id);
          else this.approvalOpen.delete(id);
        }
      },
      true,
    );
    on(section, "[data-fil]", "click", (_e, b) => this.selectStrand(b.dataset.fil ?? ""));
    on(section, "[data-archives]", "click", () => {
      this.showArchived = !this.showArchived;
      this.paintStrands();
    });
    on(section, "[data-fils-mobile]", "click", (_e, b) => this.strandsMenu(b));
    on(section, "[data-cmd]", "click", (_e, b) => {
      const cmd = b.dataset.cmd;
      if (cmd === "nouveau") this.runCommand({ name: "clear" });
      if (cmd === "renommer") this.editStrand();
      if (cmd === "archiver") this.runCommand({ name: "archive" });
      if (cmd === "desarchiver") this.runCommand({ name: "unarchive" });
    });
    on(section, "[data-verdict]", "click", (_e, b) => {
      this.verdictClick(Number(b.dataset.mid), b.dataset.verdict === "ko" ? "ko" : "ok");
    });
    on(section, "[data-more-state]", "click", (e) => {
      e.stopPropagation();
      this.shell.openStateCard();
    });
    section.addEventListener("keydown", (e) => {
      const target = e.target as HTMLElement;
      if (!target.matches("[data-chat-input]")) return;
      const input = target as HTMLTextAreaElement;
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        this.send();
        return;
      }
      if (!this.proMode) return;
      // en mode pro, Tab complète la commande commencée (« /ren » → « /renommer »)
      if (e.key === "Tab") {
        const [first] = suggestCommands(input.value);
        if (first) {
          e.preventDefault();
          this.complete(first.words[0]);
        }
      }
      if (e.key === "/" && !input.value) window.setTimeout(() => this.commandsMenu(), 0);
    });
    // déposer ou coller des fichiers
    section.addEventListener("dragover", (e) => {
      if (e.dataTransfer?.types.includes("Files")) e.preventDefault();
    });
    section.addEventListener("drop", (e) => {
      if (!e.dataTransfer?.files.length) return;
      e.preventDefault();
      void this.addFiles(e.dataTransfer.files);
    });
    section.addEventListener("paste", (e) => {
      const files = Array.from(e.clipboardData?.items ?? [])
        .filter((it) => it.kind === "file")
        .map((it) => it.getAsFile())
        .filter((f): f is File => !!f);
      if (files.length) void this.addFiles(files);
    });
  }

  private subtitle(): string {
    if (this.proMode) {
      const n = this.allStrands.filter((s) => !s.archived).length;
      return `mode pro · ${n} fil${n > 1 ? "s" : ""}`;
    }
    if (this.link === "connected") return "Mika · en ligne";
    if (this.link === "unauthorized") return "Mika · session expirée";
    return this.link === "offline" ? "Mika · hors ligne" : "Mika · connexion…";
  }

  private actions(): string {
    const search =
      this.search !== null
        ? `<label class="search chat-search">${ico("search", "sm")}<input type="search" data-chat-q placeholder="Chercher dans la conversation…" value="${h(this.search)}" aria-label="Chercher dans la conversation"></label>`
        : "";
    return `${search}<button class="btn icon ghost" type="button" data-head="chercher" title="${this.search !== null ? "Fermer la recherche" : "Chercher dans la conversation"}"${this.search !== null ? ' aria-pressed="true"' : ""}>${ico(this.search !== null ? "x" : "search")}</button>
      <button class="btn ghost sm" type="button" data-head="fichiers" title="Les fichiers échangés">${ico("clip", "sm")}<span class="lbl">Fichiers</span></button>`;
  }

  private searchEntries(): PaletteEntry[] {
    const main = this.history.filter((m) => threadOf(m) === "" && !m.inner).slice(-6).reverse();
    const out: PaletteEntry[] = main.map((m) => ({
      group: "Conversation",
      title: m.text.replace(/\s+/g, " ").slice(0, 70),
      sub: `${m.sender === "user" ? "Toi" : "Mika"} · ${new Date(m.ts).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}`,
      icon: "chat",
      action: () => {
        if (this.proMode) this.toggleMode();
        this.shell.go("#chat");
      },
    }));
    if (this.operator) {
      for (const s of this.allStrands) {
        out.push({
          group: "Fils de travail",
          title: strandLabel(s),
          sub: s.description,
          icon: "terminal",
          action: () => {
            this.activeStrand = s.id;
            write(() => localStorage, this.strandKey, s.id);
            if (!this.proMode) this.toggleMode();
            else this.selectStrand(s.id);
            this.shell.go("#chat");
          },
        });
      }
    }
    return out;
  }

  /** L'écran, pour le cadre. */
  screen(): ScreenDef {
    return {
      id: "chat",
      title: "Chat",
      icon: "chat",
      subtitle: () => this.subtitle(),
      actions: () => this.actions(),
      mount: (section) => this.mount(section),
      render: (body: HTMLElement, _ctx: ScreenContext) => this.render(body),
      search: () => this.searchEntries(),
    };
  }
}
