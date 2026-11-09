/**
 * Le chat : la conversation avec Mika, et le mode pro d'une opératrice (ADR 0116 : outils en direct, une
 * bulle en Markdown ; ADR 0164 : les fils de travail ; ADR 0064/0170 : les cartes d'accord et « Tout
 * accepter » ; ADR 0113 : 👍/👎 ; ADR 0119 : la bulle de sa position ; ADR 0112 : ses bulles l'une après
 * l'autre).
 *
 * Le comportement est celui du client web (`frontend/Web/src/ui/ChatOverlay.ts`), par les mêmes modules purs
 * (`@web/ui/chatSync`, `approvals`, `toolActivity`, `strands`, `verdicts`, `bubbles`, `messageNotes`) ; le
 * rendu, celui de la maquette (`markup.ts`). Le contrat : `backendv2/docs/protocole-chat.md`. Ce fichier garde les
 * trames, l'état du fil et l'orchestration ; les cartes d'accord sont dans `approvals.ts`, les fils de travail et leurs
 * commandes dans `strands.ts`, le champ et l'envoi dans `composer.ts`.
 *
 * Ses notes de carte (ADR 0196 : `look`, `map`, `trip`) ne passent pas par `@web/ui/messageNotes`, qui ne garde que
 * la bulle 📍 (l'ancien client web les ignore) : elles se lisent ici (`map/notes.ts`), se gardent avec le message
 * (`maps`) et se montrent en cartes miniatures (`map/minis.ts`), qui s'ouvrent dans l'écran Carte.
 */
import { API_BASE } from "@web/network/api";
import type { WebSocketClient } from "@web/network/WebSocketClient";
import type {
  AckMessage,
  HistoryAttachment,
  HistoryMessage,
  MessageNote,
  SentFile,
  SpeechMessage,
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
  proMode,
  readCache,
  replyText,
  restoredStatus,
  sentFiles,
  threadOf,
  trimThreads,
  userAttachments,
  writeCache,
  type MessageStatus,
  type StoredMessage,
} from "@web/ui/chatSync";
import { messageNotes } from "@web/ui/messageNotes";
import { strandLabel, strandOf, suggestCommands } from "@web/ui/strands";
import { cardKey, isRunning, toolFrame, toolUses, withAnswer, withToolFrame, type WorkCard } from "@web/ui/toolActivity";
import { applyVerdict, COMMENT_MAX, nextVerdict, verdictError, verdictFrame } from "@web/ui/verdicts";
import { attributionText, miniCard, pendingMini } from "../../map/cards";
import { mapInfo } from "../../map/info";
import { MiniMaps, slotKey } from "../../map/minis";
import { mapNotes, sameMapNotes, type MapNote } from "../../map/notes";
import { read, write } from "../../shared/storage";
import { onTheme } from "../../shell/theme";
import { $, h, norm, on } from "../../shell/dom";
import { closeModal, openModal, toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import type { PaletteEntry } from "../../shell/palette";
import type { Account, ScreenContext, ScreenDef, Shell } from "../../shell/shell";
import type { MikaSnapshot, MikaStore } from "../../mika/store";
import { facetHtml, facetsOf, promiseHtml, statusLine, type LinkState } from "../../mika/view";
import { ApprovalCards } from "./approvals";
import { ACCEPTED_TYPES, ChatComposer, MAX_MESSAGE_CHARS } from "./composer";
import { mergeOlder, mergeSeam, oldestLoaded, UNBOUNDED } from "./older";
import { composerMarkup, dayAndClock, filesTable, messageKey, threadMarkup } from "./markup";
import { WorkStrands } from "./strands";

/**
 * Par fil, ce que garde le cache du navigateur et ce qu'une trame sans contact laisse en mémoire ; hors de ce cas, la
 * mémoire n'a pas de borne (ADR 0215). C'est aussi ce que le serveur rend à l'ouverture : une trame aussi longue peut
 * en laisser de plus anciens.
 */
const MAX_MESSAGES = 50;
/** Sans réponse au bout de ce temps (une trame ignorée au-delà du débit), le bouton redevient cliquable. */
const OLDER_WAIT_MS = 10_000;
/** « Mika écrit… » ne survit pas plus longtemps sans réponse (le tour entier peut attendre longtemps). */
const TYPING_TIMEOUT_MS = 300_000;
/** Le message que la palette montre reste surligné ce temps-là. */
const FOUND_MS = 2400;
/** L'écart entre le haut du champ (et de ses cartes) et le bas des toasts, sur l'écran Chat. */
const TOAST_GAP_PX = 8;
/** Dans la palette, le début d'un message ; ce qu'on y trouve plus loin se montre en passage (`palette.ts::excerpt`). */
const PALETTE_TITLE_CHARS = 70;

/** Le fil gardé par ce navigateur, pour ce compte seulement. */
export const CACHE_PREFIX = "mika2_chat";
const PRO_KEY = "mika2_chat_pro";

/** Un message gardé, et ses notes de carte (ADR 0196), qu'il emporte dans le cache du navigateur. */
type Kept = StoredMessage & { maps?: MapNote[] };

/** Les notes de carte d'un message (aucune : `[]`). */
function mapsOf(msg: StoredMessage): MapNote[] {
  return (msg as Kept).maps ?? [];
}

/** Poser (ou retirer) les notes de carte d'un message ; rend vrai si elles ont changé. */
function setMaps(msg: StoredMessage, maps: MapNote[]): boolean {
  if (sameMapNotes(mapsOf(msg), maps)) return false;
  if (maps.length) (msg as Kept).maps = maps;
  else delete (msg as Kept).maps;
  return true;
}

/** Le temps que sa bouche bouge pour une bulle : un peu moins que de la lire à voix haute. */
export function talkMs(text: string): number {
  return Math.min(5000, Math.max(900, text.length * 45));
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
  /** Le fil avec elle a-t-il, au serveur, des messages plus anciens que ce qui est chargé ? (ADR 0215) */
  private moreOlder = false;
  private olderTimer: number | null = null;
  private readonly cacheKey: string;

  private readonly approvalCards: ApprovalCards;
  private readonly strands: WorkStrands;
  private readonly composer: ChatComposer;

  private work: readonly WorkCard[] = [];
  private readonly openWork = new Set<string>();

  private proPreferred: boolean;
  /** Le fil où « Mika écrit… » attend sa réponse (`""` : le fil avec elle) ; `null` : elle n'écrit pas. */
  private typingThread: string | null = null;
  private typingTimer: number | null = null;

  private readonly verdictPending = new Map<number, { verdict?: Verdict; note?: string }>();
  private readonly verdictErrors = new Map<number, string>();

  private link: LinkState = "connecting";
  private search: string | null = null;

  private body: HTMLElement | null = null;
  private mounted: "ordinary" | "pro" | null = null;
  /** Ses cartes miniatures (ADR 0196) : au plus quatre vraies cartes à la fois, les autres en plan dessiné. */
  private readonly minis = new MiniMaps();
  /** Le fil suit le bas tant qu'on y est : une image qui se charge, une bulle qui arrive le gardent en vue. */
  private stick = true;
  private resize: ResizeObserver | null = null;
  /** La hauteur du champ et de ses cartes : les toasts passent au-dessus (`placeToasts`). */
  private dockWatch: ResizeObserver | null = null;
  /** Le message que la palette a choisi (sa `messageKey`), à montrer au prochain dessin ; puis celui qu'on surligne. */
  private showing: string | null = null;
  private found: string | null = null;
  private foundTimer: number | null = null;
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
    dropForeignCaches(this.cacheKey);
    this.proPreferred = read(() => localStorage, PRO_KEY) === "1";
    this.approvalCards = new ApprovalCards({
      ws: () => this.ws,
      body: () => this.body,
      operator: () => this.operator,
    });
    this.strands = new WorkStrands(
      {
        ws: () => this.ws,
        body: () => this.body,
        proMode: () => this.proMode,
        history: () => this.history,
        input: () => this.composer.input(),
        focusInput: () => this.composer.focusInput(),
        paintThread: (toBottom) => this.paintThread(toBottom),
        paintTyping: () => this.paintTyping(),
        refreshHead: () => this.refreshHead(),
      },
      who,
    );
    this.composer = new ChatComposer({
      ws: () => this.ws,
      body: () => this.body,
      proMode: () => this.proMode,
      activeStrand: () => this.strands.activeStrand,
      onScreen: () => this.shell.ctx?.screen === "chat",
      addMessage: (text, opts) => this.addMessage(text, "user", opts),
      runCommand: (command) => this.strands.runCommand(command),
      noteOpener: (id, text) => this.strands.noteOpener(id, text),
      showTyping: () => this.showTyping(),
    });
    this.restore();
    store.subscribe((snap) => this.paintMika(snap));
    onTheme((dark) => this.minis.theme(dark));
    document.addEventListener("keydown", (e) => this.composer.focusOnType(e));
    addEventListener("resize", () => this.placeToasts());
  }

  // ── Le compte et les modes ────────────────────────────────────────

  private get operator(): boolean {
    return this.account.operator;
  }

  /** Le prochain message part-il en mode pro ? Seulement pour une opératrice qui l'a choisi. */
  private get proMode(): boolean {
    return this.operator && this.proPreferred;
  }

  /** Le fil que l'écran montre : en mode pro, le fil de travail actif ; sinon le fil avec elle (`""`). */
  private get viewThread(): string {
    return this.proMode ? this.strands.activeStrand : "";
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
    ws.on("strands", (d) => this.strands.onStrands(d));
    ws.on("strand_result", (d) => this.strands.onStrandResult(d));
    ws.on("approvals", (d) => this.approvalCards.onApprovals(d.items));
    ws.on("approval_result", (d) => this.approvalCards.onApprovalResult(d));
    ws.on("connection", (d) => {
      this.approvalCards.onConnection(d.status);
      if (d.status !== "connected") this.endOlder();
      this.link =
        d.status === "connected" ? "connected" : d.status === "unauthorized" ? "unauthorized" : d.status === "reconnecting" ? "connecting" : "offline";
      this.store.setLink(this.link);
      this.approvalCards.paintApprovals();
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
        setMaps(restored, m.sender === "vtuber" ? mapNotes((m as Partial<Kept>).maps) : []);
        restored.files = m.sender === "vtuber" ? sentFiles(m.files) : undefined;
        if (!restored.files?.length) delete restored.files;
        restored.attachments = m.sender === "user" ? userAttachments(m.attachments) : undefined;
        if (!restored.attachments?.length) delete restored.attachments;
        restored.strand = strandOf(m.strand);
        if (!restored.strand) delete restored.strand;
        return restored;
      });
    this.history = trimThreads(this.history, MAX_MESSAGES, MAX_STRANDS_CACHED);
  }

  private persist(): void {
    write(() => localStorage, this.cacheKey, writeCache(this.life, trimThreads(this.history, MAX_MESSAGES, MAX_STRANDS_CACHED)));
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
    const maps = mapNotes(data.notes);
    // un voyage qu'elle vient de changer : ses miniatures se relisent quand elles reparaissent
    for (const note of maps) this.minis.invalidate(note);
    this.addMessage(data.text, "vtuber", {
      id: replyId ?? undefined,
      localOnly: inner && replyId === null,
      inner,
      files: sentFiles(data.attachments),
      reveal: !inner && !pro,
      mode: pro,
      notes: messageNotes(data.notes),
      maps,
      strand,
    });
    if (this.reveal.writing) this.showTyping("");
    if (strand && strand !== this.viewThread) this.strands.noteUnread(strand);
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
      // un fil relu : des lignes à fusionner, jamais un curseur ni une autre vie ; le fil avec elle (ADR 0215), ou
      // un fil de travail (ADR 0164)
      if (data.strand === "") this.onOlder(data);
      else this.merge(data.messages ?? [], false, "catchup");
      return;
    }
    let wiped = false;
    if (fromAnotherLife(this.life, data)) {
      this.history = keepAcrossLives(this.history);
      this.moreOlder = false;
      this.work = [];
      wiped = true;
    }
    if (typeof data.life === "string" && data.life) this.life = data.life;
    this.merge(data.messages ?? [], data.truncated === true, data.mode === "initial" ? "initial" : "catchup", wiped);
  }

  private merge(entries: HistoryMessage["messages"], truncated: boolean, mode: "initial" | "catchup", wiped = false): void {
    const before = this.history.length;
    const moreBefore = this.moreOlder;
    // à l'ouverture, ou quand il en manque trop : ce qui est plus vieux qu'une trame qui ne touche rien de chargé ne
    // se recoud pas, le fil avec elle repart de cette trame (ADR 0215)
    const seam = mode === "initial" || truncated;
    const result = seam ? mergeSeam(this.history, entries ?? [], MAX_MESSAGES) : mergeHistory(this.history, entries, UNBOUNDED);
    this.history = result.history;
    if (seam) this.moreOlder = truncated || (entries?.length ?? 0) >= MAX_MESSAGES;
    const mapped = this.mergeMaps(entries);
    const changed = wiped || result.added > 0 || result.adopted > 0 || result.judged > 0 || result.enriched > 0 || mapped > 0;
    if (!changed && this.history.length === before && !truncated && this.moreOlder === moreBefore) return;
    this.persist();
    this.paintThread();
    if (result.sawReply) this.hideTyping();
  }

  /** Une page de messages anciens du fil avec elle (ADR 0215) : au-dessus de ce qui est lu, sans bouger la lecture. */
  private onOlder(data: HistoryMessage): void {
    const entries = data.messages ?? [];
    this.stopOlderTimer();
    this.moreOlder = data.more === true;
    this.history = mergeOlder(this.history, entries);
    this.mergeMaps(entries);
    const scroller = this.body ? $<HTMLElement>("[data-scroll]", this.body) : null;
    const fromBottom = scroller ? scroller.scrollHeight - scroller.scrollTop : 0;
    this.paintThread();
    if (scroller) scroller.scrollTop = scroller.scrollHeight - fromBottom;
  }

  /** « Messages plus anciens » (ADR 0215) : la page d'avant, une à la fois. */
  private askOlder(): void {
    if (this.olderTimer !== null || !this.moreOlder || !this.ws) return;
    const before = oldestLoaded(this.history);
    const sent = this.ws.requestStrandHistory({ type: "strand_history", id: "", ...(before !== undefined ? { before } : {}) });
    if (!sent) {
      toast("Hors ligne : réessaie quand la connexion est revenue.", { ico: "alert" });
      return;
    }
    this.stick = false;  // on lit vers le haut : rien ne redescend tout seul
    this.olderTimer = window.setTimeout(() => {
      this.olderTimer = null;
      this.paintThread();
    }, OLDER_WAIT_MS);
    this.paintThread();
  }

  private stopOlderTimer(): void {
    if (this.olderTimer !== null) window.clearTimeout(this.olderTimer);
    this.olderTimer = null;
  }

  /** La connexion est tombée : la page demandée ne viendra pas, le bouton redevient cliquable. */
  private endOlder(): void {
    if (this.olderTimer === null) return;
    this.stopOlderTimer();
    this.paintThread();
  }

  /**
   * Ses notes de carte, telles que le fil relu les dit (ADR 0196) : posées sur ses messages (une note oubliée depuis,
   * un voyage supprimé, renommé, changé : la miniature suit). Rend combien de messages ont changé.
   */
  private mergeMaps(entries: HistoryMessage["messages"]): number {
    let changed = 0;
    for (const entry of entries ?? []) {
      if (typeof entry?.id !== "number" || entry.role === "user") continue;
      const shown = this.history.find((m) => m.id === entry.id);
      if (!shown || shown.sender !== "vtuber") continue;
      const maps = mapNotes((entry as { notes?: unknown }).notes);
      const before = mapsOf(shown);
      if (!setMaps(shown, maps)) continue;
      for (const note of maps) {
        if (!before.some((b) => b.kind === note.kind && b.ref === note.ref && b.at === note.at)) this.minis.invalidate(note);
      }
      changed += 1;
    }
    return changed;
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
      attachments?: HistoryAttachment[];
      inner?: boolean;
      files?: SentFile[];
      reveal?: boolean;
      mode?: "pro";
      notes?: MessageNote[];
      maps?: MapNote[];
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
      ...(opts.attachments?.length ? { attachments: opts.attachments } : {}),
      ...(opts.mode ? { mode: opts.mode } : {}),
      ...(opts.notes?.length ? { notes: opts.notes } : {}),
      ...(opts.maps?.length ? { maps: opts.maps } : {}),
      ...(opts.strand ? { strand: opts.strand } : {}),
    };
    this.history.push(stored);
    if (opts.reveal && sender === "vtuber") this.reveal.start(stored, display);
    this.history = trimThreads(this.history, UNBOUNDED, MAX_STRANDS_CACHED);
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

  // ── L'écran ───────────────────────────────────────────────────────

  private refreshHead(): void {
    if (this.shell.ctx?.screen === "chat") this.shell.refreshHead();
  }

  /** Le mode choisi, retenu par ce navigateur ; un toast le dit. Ne redessine rien. */
  private setPro(pro: boolean): void {
    this.proPreferred = pro;
    write(() => localStorage, PRO_KEY, pro ? "1" : "0");
    this.strands.ensureStrand();
    if (this.proMode) this.strands.askStrandHistory(this.strands.activeStrand);
    toast(
      this.proMode ? "Mode pro : sans son caractère, ses outils en direct, tes fils de travail." : "Retour à la conversation avec Mika.",
      { ico: "terminal" },
    );
  }

  private toggleMode(): void {
    this.setPro(!this.proPreferred);
    this.shell.refresh();
    this.composer.focusInput();
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
      older: thread !== "" || !this.moreOlder ? "none" : this.olderTimer !== null ? "loading" : "more",
      now: Date.now(),
      api: API_BASE,
      filter: query ? (m) => norm(m.text).includes(query) : undefined,
      mapCards: (m) => this.mapCards(m),
      found: this.found ?? undefined,
    });
    // ses cartes miniatures : les vivantes se relogent, les nouvelles s'observent
    this.minis.attach(el);
    if (scroller && this.stick && !query) scroller.scrollTop = scroller.scrollHeight;
  }

  /** Ses cartes miniatures d'un message : ce qu'on en sait déjà, sinon le texte de sa note en attendant. */
  private mapCards(msg: StoredMessage): string {
    const notes = mapsOf(msg);
    if (!notes.length) return "";
    const owner = typeof msg.id === "number" ? String(msg.id) : `t${msg.ts}`;
    const attribution = attributionText(mapInfo.value);
    return notes.map((n) => miniCard(slotKey(owner, n), this.minis.dataOf(n) ?? pendingMini(n), attribution)).join("");
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
        facets.length ? facets.map(facetHtml).join("") : `<p class="muted">Elle ne laisse rien paraître pour l'instant.</p>`
      }</section>`,
    );
    // sa forme courte, voulue : deux pensées en simples paragraphes (la carte « Ce qu'elle fait » en montre trois)
    if (s.ruminations.length) {
      sections.push(`<section><h4>Elle repense à…</h4>${s.ruminations.slice(0, 2).map((r) => `<p>${h(r.summary)}</p>`).join("")}</section>`);
    }
    if (s.commitments.length) {
      sections.push(`<section><h4>Ce qu'elle t'a promis</h4>${s.commitments.slice(0, 5).map(promiseHtml).join("")}</section>`);
    }
    body.innerHTML = `${sections.join("")}<button class="btn sm ghost cm-more" type="button" data-more-state>${ico("sparkle", "sm")}Tout ce qu'elle fait</button>`;
  }

  private ordinarySkeleton(): string {
    return `<div class="chat-split"><div class="chat-wrap"><div class="chat-col">
        <div class="chat-scroll" data-scroll><div class="chat-thread" data-thread></div></div>
        <div class="chat-dock"><div class="ap-zone" data-approvals hidden></div>${composerMarkup({ pro: false, operator: this.operator, auto: this.approvalCards.autoAccept }, MAX_MESSAGE_CHARS, ACCEPTED_TYPES)}</div>
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
          <div class="chat-dock wide"><div class="ap-zone" data-approvals hidden></div>${composerMarkup({ pro: true, operator: this.operator, auto: this.approvalCards.autoAccept }, MAX_MESSAGE_CHARS, ACCEPTED_TYPES)}</div>
        </section></div>`;
  }

  private render(body: HTMLElement): void {
    this.body = body;
    const mode = this.proMode ? "pro" : "ordinary";
    if (this.mounted !== mode || !$("[data-thread]", body)) {
      const draft = this.composer.input()?.value ?? "";
      body.innerHTML = mode === "pro" ? this.proSkeleton() : this.ordinarySkeleton();
      this.mounted = mode;
      const input = this.composer.input();
      if (input && draft) {
        input.value = draft;
        this.composer.resizeInput(input);
      }
      this.approvalCards.paintToggle();
      this.composer.paintAttachments();
      this.strands.paintStrands();
      this.paintMika(this.store.current);
      this.approvalCards.paintApprovals();
      this.followBottom();
      this.watchDock();
      this.paintThread(true);
      this.composer.applyDraft();
      this.applyShow();
      this.placeToasts();
      return;
    }
    this.paintThread();
    this.composer.applyDraft();
    this.applyShow();
    this.placeToasts();
  }

  // ── Les toasts, au-dessus du champ (Q15) ──────────────────────────

  /** Le champ et ses cartes changent de hauteur (une ligne de plus, une carte qui arrive), ou l'écran se cache. */
  private watchDock(): void {
    this.dockWatch?.disconnect();
    const dock = this.body ? $(".chat-dock", this.body) : null;
    if (!dock) return;
    this.dockWatch = new ResizeObserver(() => this.placeToasts());
    this.dockWatch.observe(dock);
  }

  /**
   * Sur l'écran Chat, les toasts passent au-dessus du champ et de ses cartes, jamais dessus : on ne les cache pas au
   * moment d'écrire ou de décider. La variable `--toast-bottom`, posée sur `#toasts`, que base.css et app.css lisent ;
   * le chat caché, elle s'en va et les toasts reprennent leur place.
   */
  private placeToasts(): void {
    const toasts = document.getElementById("toasts");
    if (!toasts) return;
    const dock = this.body ? $(".chat-dock", this.body) : null;
    if (!dock || !dock.offsetParent) {
      toasts.style.removeProperty("--toast-bottom");
      return;
    }
    const above = Math.max(0, Math.round(innerHeight - dock.getBoundingClientRect().top)) + TOAST_GAP_PX;
    toasts.style.setProperty("--toast-bottom", `${above}px`);
  }

  // ── La palette mène à un message (F1-05) ──────────────────────────

  /**
   * Montrer un message chargé, choisi dans la palette : son fil, dans le mode qu'il demande (le fil avec elle est caché
   * en mode pro : on en sort, comme « Demander à Mika » depuis la Carte), la recherche du chat fermée ; au dessin
   * suivant, le message au milieu du fil, surligné un instant (`applyShow`).
   */
  private showMessage(m: StoredMessage): void {
    const thread = threadOf(m);
    const pro = thread !== "";
    if (pro) {
      this.strands.adopt(thread);
      this.strands.markRead(thread);
    }
    if (pro !== this.proMode) this.setPro(pro);
    else if (pro) {
      // déjà en mode pro : un autre fil, comme `selectStrand`, sans prendre la main du champ
      this.strands.askStrandHistory(thread);
      this.strands.paintStrands();
      this.paintTyping();
    }
    this.search = null;
    this.showing = messageKey(m);
    this.shell.go("#chat");
  }

  /** Le message choisi dans la palette : au milieu du fil, surligné `FOUND_MS` ; parti entre-temps, un toast le dit. */
  private applyShow(): void {
    const key = this.showing;
    if (key === null || !this.body) return;
    this.showing = null;
    const el = $(`[data-msg="${CSS.escape(key)}"]`, this.body);
    if (!el) {
      toast("Ce message n'est plus dans la conversation chargée.", { ico: "info" });
      return;
    }
    if (this.foundTimer !== null) window.clearTimeout(this.foundTimer);
    this.found = key;
    el.classList.add("found");
    // le fil ne redescend plus de lui-même : on lit ce message
    this.stick = false;
    el.scrollIntoView({ block: "center" });
    this.foundTimer = window.setTimeout(() => {
      this.foundTimer = null;
      this.found = null;
      this.paintThread();
    }, FOUND_MS);
  }

  /**
   * Ouvrir le chat avec une phrase préremplie (l'écran Carte : « Demander à Mika », « En parler à Mika ») : elle ne part
   * pas d'elle-même, on la complète et on l'envoie. Ses outils de carte servent dans la conversation : le mode pro, s'il
   * était choisi, cède la place.
   */
  prefill(text: string): void {
    if (this.proMode) this.setPro(false);
    this.composer.setDraft(text);
    this.shell.go("#chat");
  }

  private mount(section: HTMLElement): void {
    on(section, "[data-older]", "click", () => this.askOlder());
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
      }
    });
    on(section, "[data-cmp]", "click", (_e, b) => {
      switch (b.dataset.cmp) {
        case "pro":
          this.toggleMode();
          break;
        case "accord":
          this.approvalCards.toggleAuto();
          break;
        case "envoyer":
          this.composer.send();
          break;
        case "emoji":
          this.composer.emojis(b);
          break;
        case "commandes":
          this.strands.commandsMenu(b);
          break;
        case "joindre":
          $<HTMLInputElement>("[data-file]", section)?.click();
          break;
      }
    });
    this.composer.mount(section);
    this.approvalCards.mount(section);
    this.strands.mount(section);
    // les dépliants restent comme on les a laissés d'un rendu à l'autre (`toggle` ne remonte pas : on le capte)
    section.addEventListener(
      "toggle",
      (e) => {
        const d = e.target as HTMLDetailsElement;
        if (d.dataset.work) {
          if (d.open) this.openWork.add(d.dataset.work);
          else this.openWork.delete(d.dataset.work);
        }
      },
      true,
    );
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
        this.composer.send();
        return;
      }
      if (!this.proMode) return;
      // en mode pro, Tab complète la commande commencée (« /ren » → « /renommer »)
      if (e.key === "Tab") {
        const [first] = suggestCommands(input.value);
        if (first) {
          e.preventDefault();
          this.strands.complete(first.words[0]);
        }
      }
      if (e.key === "/" && !input.value) window.setTimeout(() => this.strands.commandsMenu(), 0);
    });
  }

  private subtitle(): string {
    if (this.proMode) {
      const n = this.strands.allStrands.filter((s) => !s.archived).length;
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

  /** Un message chargé, dans la palette : son début en titre, tout son texte où chercher ; le choisir y mène. */
  private messageEntry(m: StoredMessage, group: string, where: string, now: number): PaletteEntry {
    const text = m.text.replace(/\s+/g, " ").trim();
    const title = text.length > PALETTE_TITLE_CHARS ? `${text.slice(0, PALETTE_TITLE_CHARS - 1).trimEnd()}…` : text;
    return {
      group,
      title,
      sub: [m.sender === "user" ? "Toi" : "Mika", where, dayAndClock(m.ts, now)].filter(Boolean).join(" · "),
      text,
      icon: "chat",
      action: () => this.showMessage(m),
    };
  }

  /**
   * Ce que la palette cherche ici : tous les messages chargés, en entier (sans rien de tapé, elle montre les six plus
   * récents de la conversation) ; pour une opératrice, ses fils de travail, puis leurs messages.
   */
  private searchEntries(): PaletteEntry[] {
    const now = Date.now();
    const loaded = this.history.filter((m) => !m.inner && m.text.trim());
    const out: PaletteEntry[] = loaded
      .filter((m) => threadOf(m) === "")
      .reverse()
      .map((m) => this.messageEntry(m, "Conversation", "", now));
    if (this.operator) {
      for (const s of this.strands.allStrands) {
        out.push({
          group: "Fils de travail",
          title: strandLabel(s),
          sub: s.description,
          icon: "terminal",
          action: () => {
            this.strands.adopt(s.id);
            if (!this.proMode) this.toggleMode();
            else this.strands.selectStrand(s.id);
            this.shell.go("#chat");
          },
        });
      }
      const inStrands = loaded.filter((m) => threadOf(m) !== "").sort((a, b) => b.ts - a.ts);
      for (const m of inStrands) {
        out.push(this.messageEntry(m, "Fils de travail", `« ${strandLabel(this.strands.strandInfo(threadOf(m)))} »`, now));
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
