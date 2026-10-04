import { renderInline } from "./inlineMarkup";
import { WebSocketClient } from "../network/WebSocketClient";
import { API_BASE } from "../network/api";
import type {
  AckMessage,
  ApprovalCard,
  ApprovalDecision,
  HistoryMessage,
  RejectedAttachment,
  SentFile,
} from "../types";
import {
  acceptRefusal,
  approvalResult,
  cardControls,
  decisionFrame,
  EMPTY_APPROVALS,
  expiryLabel,
  isDecisionTaken,
  isExpired,
  canAccept,
  nextRefreshDelay,
  resultMessage,
  sameCard,
  withApprovals,
  withConnection,
  withDecisionSent,
  withResult,
} from "./approvals";
import type { ApprovalsState } from "./approvals";
import {
  applyAck,
  ASLEEP_NOTE,
  asleepNoteShown,
  bindServerId,
  consoleHref,
  cursorOf,
  fromAnotherLife,
  keepAcrossLives,
  markAsleep,
  mergeHistory,
  nextClientMsgId,
  readCache,
  restoredStatus,
  stripProsody,
  withAttachments,
  writeCache,
  sentFiles,
} from "./chatSync";
import type { MessageStatus, StoredMessage } from "./chatSync";

// Re-exported: it was defined here before the synchronisation rules were
// pulled out, and callers should not have to know which file they moved to.
export { stripProsody };
export type { MessageStatus, StoredMessage };

interface PendingAttachment {
  name: string;
  type: string;
  data: string;       // base64, no data-URI prefix
  preview?: string;   // data-URI for image previews
}

const ACCEPTED_TYPES = [
  "image/jpeg", "image/png", "image/gif", "image/webp",
  "audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg", "audio/webm",
  "text/plain", "text/csv", "text/markdown", "application/json",
  "application/pdf", // extrait côté backend (pipeline/preprocessors/files.py)
].join(",");

const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5 MB
const MAX_ATTACHMENTS = 5;
const MAX_MESSAGES = 50;
/**
 * La longueur maximale d'un message, celle du serveur
 * (`adapters/web/protocol.py::MAX_MESSAGE_CHARS`) : au-delà, il le refuse
 * (`too_long`) — et le champ, vidé à l'envoi, avait déjà perdu le texte.
 */
export const MAX_MESSAGE_CHARS = 2000;
/** Le compteur ne se montre qu'à l'approche de la limite. */
const COUNTER_FROM = 1800;
/**
 * Prefix of the per-identity cache key. It used to be a single global key,
 * which meant the thread survived a change of identity: "Réinitialiser ton
 * identité" mints a new `person_id` and reloads, and the previous person's
 * conversation was still on screen under the new one — a server that has
 * never heard of it, and, when two accounts share a browser, someone else's
 * messages.
 */
const HISTORY_KEY_PREFIX = "vtuber_chat_history";
/** The pre-scoping key, cleaned up on sight. */
const LEGACY_HISTORY_KEY = "vtuber_chat_history";
// How long the "typing" indicator survives without a reply. It has to clear
// the *whole* wait, which is not just the AI call: `ai.call_timeout_seconds`
// defaults to 120s, the turn may sit behind another one in the single-worker
// queue, and a cosmetic thinking delay follows. At 75s (sized against an
// AI_CALL_TIMEOUT that is no longer 60s) the indicator vanished while the
// answer was still coming, which reads as "she gave up".
const TYPING_TIMEOUT_MS = 300000;
/** Le sort d'une décision d'accord reste lisible ce temps-là, puis s'efface. */
const APPROVAL_NOTE_MS = 6000;
const OFFLINE_NOT_SENT =
  "Hors ligne : ta décision n'est pas partie. Réessaie à la reconnexion.";

/** Une carte d'accord peinte, et les éléments qu'un rafraîchissement touche. */
interface ApprovalView {
  card: ApprovalCard;
  root: HTMLElement;
  refusal: HTMLElement;
  expiry: HTMLElement;
  accept: HTMLButtonElement;
  refuse: HTMLButtonElement;
  state: HTMLElement;
}

function fileIcon(type: string): string {
  if (type.startsWith("image/")) return "🖼️";
  if (type.startsWith("audio/")) return "🎵";
  return "📄";
}

/** « 7,2 Mo » — un refus qui donne la taille dit du même coup pourquoi. */
function formatSize(bytes: number): string {
  const mo = bytes / (1024 * 1024);
  return `${mo.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} Mo`;
}

async function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // Strip "data:...;base64," prefix
      const base64 = result.split(",")[1] ?? result;
      resolve(base64);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function readFileAsDataURI(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export class ChatOverlay {
  private messagesEl: HTMLElement;
  private inputEl: HTMLTextAreaElement;
  private sendBtn: HTMLElement;
  private attachBtn: HTMLElement;
  private previewsEl: HTMLElement;
  private fileInput: HTMLInputElement;
  private ws: WebSocketClient;
  private pendingAttachments: PendingAttachment[] = [];
  /**
   * Ce que le dernier dépôt a écarté, dit en clair.
   *
   * Un fichier refusé ici ne quitte jamais le navigateur : les plafonds
   * client sont ceux de `pipeline/media.py`, donc le serveur ne le verra
   * jamais et aucun `ack` ne peut le refuser à voix haute. C'est le dernier
   * endroit du trajet où l'information existe encore.
   */
  private attachmentNotices: string[] = [];
  private history: StoredMessage[] = [];
  /** L'empreinte de la vie d'où vient ce fil (voir chatSync.CachedThread). */
  private life = "";
  private counterEl: HTMLElement | null = null;
  private typingEl: HTMLElement | null = null;
  private typingTimer: number | null = null;
  /** The server dropped the oldest part of a catch-up; said, not hidden. */
  private truncated = false;
  /** Cache key for *this* identity's thread — see HISTORY_KEY_PREFIX. */
  private historyKey: string;
  /**
   * La bande des cartes d'accord (voir approvals.ts), épinglée au-dessus de la
   * saisie plutôt que dans le fil : ce n'est pas une parole, et une demande qui
   * défilerait vers le haut serait une décision qu'on ne voit plus.
   */
  private approvalsEl: HTMLElement;
  private approvalsHeadEl: HTMLElement;
  private approvalsHintEl: HTMLElement;
  private approvalsListEl: HTMLElement;
  private approvalNoteEl: HTMLElement;
  private approvals: ApprovalsState = EMPTY_APPROVALS;
  /** Par identifiant, dans l'ordre de la liste. */
  private approvalViews = new Map<number, ApprovalView>();
  /** Un seul minuteur pour les échéances, réarmé à chaque peinture. */
  private approvalTimer: number | null = null;
  private approvalNoteTimer: number | null = null;

  constructor(ws: WebSocketClient, personId: string = "") {
    this.ws = ws;
    this.historyKey = personId
      ? `${HISTORY_KEY_PREFIX}:${personId}`
      : HISTORY_KEY_PREFIX;
    this.dropForeignCaches();
    this.messagesEl = document.getElementById("chat-messages")!;
    this.inputEl = document.getElementById("chat-input") as HTMLTextAreaElement;
    this.sendBtn = document.getElementById("chat-send")!;
    this.attachBtn = document.getElementById("chat-attach")!;
    this.previewsEl = document.getElementById("attachment-previews")!;
    // La limite du serveur, connue du champ : on ne tape pas 2 500 caractères
    // pour se les voir refuser après l'envoi.
    this.inputEl.maxLength = MAX_MESSAGE_CHARS;
    this.counterEl = document.createElement("div");
    this.counterEl.className = "chat-note chat-counter";
    this.counterEl.hidden = true;
    this.previewsEl.after(this.counterEl);

    this.approvalsEl = document.createElement("section");
    this.approvalsEl.className = "chat-approvals";
    this.approvalsEl.setAttribute("aria-label", "Demandes d'accord");
    this.approvalsEl.hidden = true;
    this.approvalsHeadEl = document.createElement("div");
    this.approvalsHeadEl.className = "approvals-head";
    this.approvalsHeadEl.textContent = "Mika attend ton accord";
    this.approvalsHintEl = document.createElement("div");
    this.approvalsHintEl.className = "approvals-hint";
    this.approvalsHintEl.textContent = "Hors ligne — tu pourras décider à la reconnexion.";
    this.approvalsHintEl.hidden = true;
    this.approvalsListEl = document.createElement("div");
    this.approvalsListEl.className = "approvals-list";
    this.approvalNoteEl = document.createElement("div");
    this.approvalNoteEl.className = "chat-note approval-note";
    this.approvalNoteEl.setAttribute("role", "status");
    this.approvalNoteEl.hidden = true;
    this.approvalsEl.append(
      this.approvalsHeadEl, this.approvalsHintEl, this.approvalsListEl, this.approvalNoteEl,
    );
    this.messagesEl.after(this.approvalsEl);

    // Hidden file input
    this.fileInput = document.createElement("input");
    this.fileInput.type = "file";
    this.fileInput.multiple = true;
    this.fileInput.accept = ACCEPTED_TYPES;
    this.fileInput.style.display = "none";
    document.body.appendChild(this.fileInput);

    this.restoreHistory();
    this.setupEvents();
  }

  /** Repaint messages persisted from the previous session (no animation).
   *
   * This is a *cache*, not the record. It exists so a reload paints
   * instantly instead of flashing empty, and it is replaced by whatever the
   * server sends moments later. Treating it as the record is what made
   * missed replies permanently invisible: the browser was the only party
   * that ever decided what the conversation contained.
   */
  /**
   * Remove every cached thread that is not ours.
   *
   * Scoping the key stops a stale thread from being *read*; it does not stop
   * it from sitting in localStorage. A conversation is exactly the kind of
   * thing that should not outlive the identity it belongs to on a shared
   * browser, so the previous one is dropped rather than merely ignored.
   */
  private dropForeignCaches() {
    try {
      const doomed: string[] = [];
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (!key) continue;
        const ours = key === this.historyKey;
        const scoped = key.startsWith(`${HISTORY_KEY_PREFIX}:`);
        if ((scoped || key === LEGACY_HISTORY_KEY) && !ours) doomed.push(key);
      }
      for (const key of doomed) localStorage.removeItem(key);
    } catch {
      // Private mode / storage disabled — nothing cached, nothing to clean.
    }
  }

  private restoreHistory() {
    try {
      const cached = readCache(localStorage.getItem(this.historyKey));
      this.life = cached.life;
      const stored = cached.messages as Array<Partial<StoredMessage> | null>;
      if (!stored.length) return;
      this.history = stored
        .filter(
          (m): m is StoredMessage =>
            !!m &&
            typeof m.text === "string" &&
            (m.sender === "user" || m.sender === "vtuber")
        )
        .map((m): StoredMessage => {
          // Un "pending" restauré ment : l'outbox qui aurait pu le faire
          // avancer était en mémoire dans l'onglet précédent (voir
          // restoredStatus). On ne touche `reason` que dans ce cas — un
          // "failed" restauré garde le sien.
          const { status, reason } = restoredStatus(m.status);
          return reason ? { ...m, status, reason } : { ...m, status };
        })
        .slice(-MAX_MESSAGES);
      this.repaint({ animate: false });
    } catch {
      this.history = [];
    }
  }

  /**
   * Highest server id this client has actually rendered — the cursor it
   * hands the transport on every reconnect. Derived from what is on screen
   * rather than tracked separately, so it can never claim delivery of a
   * frame that a throwing handler dropped on the floor.
   */
  cursor(): number {
    return cursorOf(this.history);
  }

  private persistHistory() {
    try {
      localStorage.setItem(this.historyKey, writeCache(this.life, this.history));
    } catch {
      // Quota exceeded / private mode — history is best-effort only.
    }
  }

  /** Wipe the displayed messages + persisted history (typing bubble kept). */
  clearHistory() {
    this.history = [];
    this.truncated = false;
    try {
      localStorage.removeItem(this.historyKey);
    } catch {
      // best-effort
    }
    for (const child of Array.from(this.messagesEl.children)) {
      if (child !== this.typingEl) child.remove();
    }
  }

  private setupEvents() {
    this.sendBtn.addEventListener("click", () => this.sendMessage());

    this.inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
    });

    // Auto-resize the textarea up to ~5 lines, then scroll inside.
    this.inputEl.addEventListener("input", () => {
      this.autoResizeInput();
      this.updateCounter();
    });

    this.attachBtn.addEventListener("click", () => this.fileInput.click());

    document.getElementById("chat-clear")?.addEventListener("click", () => {
      if (!confirm("Effacer l'historique du chat affiché ?")) return;
      this.clearHistory();
    });

    this.fileInput.addEventListener("change", () => {
      if (this.fileInput.files) {
        this.handleFiles(this.fileInput.files);
        this.fileInput.value = ""; // reset so same file can be re-selected
      }
    });

    // Drag & drop on the whole chat container
    const container = document.getElementById("chat-container")!;
    container.addEventListener("dragover", (e) => {
      e.preventDefault();
      container.classList.add("drag-over");
    });
    container.addEventListener("dragleave", () => {
      container.classList.remove("drag-over");
    });
    container.addEventListener("drop", (e) => {
      e.preventDefault();
      container.classList.remove("drag-over");
      if (e.dataTransfer?.files) this.handleFiles(e.dataTransfer.files);
    });

    // Paste images
    document.addEventListener("paste", (e) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      const files: File[] = [];
      for (const item of Array.from(items)) {
        if (item.kind === "file") {
          const f = item.getAsFile();
          if (f) files.push(f);
        }
      }
      if (files.length) this.handleFiles(files);
    });

    // The transport asks us what we already have, because we are the only
    // ones who know what actually reached the screen.
    this.ws.setCursorProvider(() => this.cursor());

    this.ws.on("speech", (data) => {
      this.hideTyping();
      // Bind the reply's own row, and the user message it answers, to the
      // bubbles already on screen. Doing it here — rather than waiting for
      // the next history frame — is what keeps the cursor moving during a
      // normal conversation, so a later reconnect asks for a small gap
      // instead of the whole window.
      if (data.client_msg_id) {
        this.bindServerId(data.client_msg_id, data.user_message_id ?? undefined);
        // Elle dort : la réponse attend son réveil. Sans ce mot, « Mika
        // écrit… » s'éteignait et la bulle restait là, sans explication.
        if (!data.text && data.voice_reason === "asleep") {
          if (markAsleep(this.history, data.client_msg_id)) {
            this.persistHistory();
            this.repaint({ animate: false });
          }
        }
      }
      if (typeof data.text === "string" && data.text) {
        // Un murmure n'est pas persisté : il n'aura jamais d'id. Sans
        // `localOnly`, « pas d'id » veut dire « le plus récent » et la pensée
        // restait épinglée en bas du fil, sous les réponses venues après.
        const inner = data.voice_persona === "inner";
        this.addMessage(data.text, "vtuber", {
          id: data.message_id ?? undefined,
          localOnly: inner && data.message_id == null,
          inner,
          files: sentFiles(data.attachments),
        });
      }
    });

    this.ws.on("ack", (data) => this.applyAck(data));

    this.ws.on("history", (data) => this.receiveHistory(data));

    // A terminal refusal (4401) means nothing queued will ever be sent.
    // Leaving those bubbles "en attente d'envoi" reads as "still on its
    // way", which is the one thing it is not.
    this.ws.on("connection", (data) => {
      // Les cartes d'accord repartent de zéro à chaque ouverture (le serveur
      // ne renvoie la liste que si elle n'est pas vide) ; coupée, les
      // boutons s'éteignent.
      this.approvals = withConnection(this.approvals, data.status);
      this.renderApprovals();
      if (data.status !== "unauthorized") return;
      this.failPending("session expirée — reconnecte-toi");
    });
  }

  /** Mark everything still queued as refused, with a reason. */
  private failPending(reason: string) {
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
    this.persistHistory();
    this.repaint({ animate: false });
  }

  // ── Synchronisation ───────────────────────────────────────────────

  /** Record what the server said became of a message we sent. */
  private applyAck(data: AckMessage) {
    const rejected: RejectedAttachment[] | undefined = data.rejected_attachments;
    const { changed, settled } = applyAck(
      this.history, data.client_msg_id, data.status, rejected,
      { reason: data.reason, detail: data.detail, href: data.href },
    );
    if (!changed) return;
    // A refused message — or one whose reply will not come — is never
    // answered, so the typing indicator has to go with it: otherwise it
    // spins until its own timeout and reads as "she is thinking about it".
    if (settled) this.hideTyping();
    this.persistHistory();
    this.repaint({ animate: false });
  }

  /**
   * Un morceau du fil arrive. S'il vient d'une autre vie que ce que l'écran
   * garde (empreinte changée, ou `reset` : le curseur dépassait la tête du
   * fil), l'écran est vidé d'abord — sinon le fil d'avant (l'ancien moteur,
   * une sauvegarde plus récente que celle restaurée) cachait celui-ci.
   */
  private receiveHistory(data: HistoryMessage) {
    let wiped = false;
    if (fromAnotherLife(this.life, data)) {
      this.history = keepAcrossLives(this.history);
      this.truncated = false;
      wiped = true;
    }
    if (typeof data.life === "string" && data.life) this.life = data.life;
    this.mergeHistory(
      data.messages ?? [],
      data.truncated === true,
      data.mode === "initial" ? "initial" : "catchup",
      wiped,
    );
  }

  /**
   * Attach server ids to the optimistic bubbles a reply refers to.
   * `userId` is the row created for what the user typed; the reply's own
   * id arrives with its text and is set by `addMessage`.
   */
  private bindServerId(cid: string, userId?: number) {
    if (bindServerId(this.history, cid, userId)) this.persistHistory();
  }

  /**
   * Fold the server's version of the conversation into what is displayed.
   *
   * Three cases per incoming row: already held (by id) → ignore; matches an
   * un-bound bubble we painted ourselves → adopt its id rather than draw it
   * twice; otherwise → new, insert it. The middle case is what a reconnect
   * needs: a message sent from the outbox has no id until the server
   * answers, so without it every reconnect duplicated whatever was in
   * flight.
   */
  private mergeHistory(
    entries: HistoryMessage["messages"],
    truncated: boolean,
    mode: "initial" | "catchup" = "catchup",
    wiped = false,
  ) {
    const before = this.history.length;
    const result = mergeHistory(this.history, entries, MAX_MESSAGES);
    this.history = result.history;
    // An `initial` frame is a whole window, not a diff, so it settles the
    // question of whether anything is missing; a `catchup` can only ever add
    // to it. Without the reset the note stayed on screen for the rest of the
    // session, long after the gap it described had been filled.
    this.truncated =
      mode === "initial" ? truncated : this.truncated || truncated;
    const changed = wiped || result.added > 0 || result.adopted > 0;
    if (!changed && this.history.length === before && !truncated) {
      // Nothing new and nothing to say about a gap: repainting would flash
      // the whole thread for no reason.
      return;
    }
    // Adoption counts as a change even though nothing appears: the bubbles
    // gained their server ids, and those ids *are* the cursor. Returning
    // early here — the old behaviour, which only looked at `added` — left
    // them unsaved, so the next reload asked the server again for messages
    // already on screen.
    this.persistHistory();
    this.repaint({ animate: false });
    // Anything the server has answered is no longer being awaited.
    if (result.sawReply) this.hideTyping();
  }

  // ── Cartes d'accord (backendv2, ADR 0064) ─────────────────────────

  /**
   * La liste entière des cartes (trame `approvals`), montrée telle quelle :
   * une carte absente n'attend plus rien. Seuls les boutons décident — un
   * « oui » tapé dans le chat n'est jamais un accord.
   */
  setApprovals(items: unknown) {
    this.approvals = withApprovals(this.approvals, items);
    this.renderApprovals();
  }

  /** Le sort d'une décision (`approval_result`), dit brièvement ; la liste à jour suit. */
  showApprovalResult(data: unknown) {
    const result = approvalResult(data);
    if (!result) return;
    this.approvals = withResult(this.approvals, result.id);
    this.showApprovalNote(resultMessage(result.status), isDecisionTaken(result.status));
    this.refreshApprovals();
  }

  /**
   * Réconcilie les cartes peintes avec la liste : une carte inchangée garde
   * sa vue (le défilement de son texte, le bouton sous le pointeur), une
   * carte changée en reçoit une neuve — son empreinte n'est plus la même.
   */
  private renderApprovals() {
    const views = new Map<number, ApprovalView>();
    for (const card of this.approvals.cards) {
      const old = this.approvalViews.get(card.id);
      views.set(card.id, old && sameCard(old.card, card) ? old : this.buildApprovalCard(card));
    }
    for (const [id, view] of this.approvalViews) {
      if (views.get(id) !== view) view.root.remove();
    }
    this.approvalViews = views;
    // dans l'ordre du serveur : `append` déplace un nœud déjà en place
    for (const view of views.values()) this.approvalsListEl.append(view.root);
    this.refreshApprovals();
  }

  /** Boutons, échéances et motifs, recalculés à l'instant ; réarme le minuteur. */
  private refreshApprovals() {
    const now = Date.now();
    for (const view of this.approvalViews.values()) {
      const controls = cardControls(this.approvals, view.card, now);
      const refusal = acceptRefusal(view.card, now);
      view.accept.disabled = !controls.accept;
      view.refuse.disabled = !controls.refuse;
      view.accept.title = controls.accept ? "" : refusal;
      view.state.hidden = !controls.sending;
      view.refusal.textContent = refusal;
      view.refusal.hidden = !refusal;
      // une carte expirée le dit dans son motif ; l'échéance ne se répète pas
      const expiry = isExpired(view.card, now) ? "" : expiryLabel(view.card, now);
      view.expiry.textContent = expiry;
      view.expiry.hidden = !expiry;
      view.root.classList.toggle("blocked", !canAccept(view.card, now));
    }
    const count = this.approvals.cards.length;
    this.approvalsHeadEl.hidden = count === 0;
    this.approvalsHintEl.hidden = count === 0 || this.approvals.connected;
    this.approvalsEl.hidden = count === 0 && this.approvalNoteEl.hidden;

    if (this.approvalTimer !== null) {
      window.clearTimeout(this.approvalTimer);
      this.approvalTimer = null;
    }
    const delay = nextRefreshDelay(this.approvals.cards, now);
    if (delay !== null) {
      this.approvalTimer = window.setTimeout(() => {
        this.approvalTimer = null;
        this.refreshApprovals();
      }, delay);
    }
  }

  private buildApprovalCard(card: ApprovalCard): ApprovalView {
    const root = document.createElement("div");
    root.className = "approval-card";
    const title = document.createElement("div");
    title.className = "approval-title";
    title.textContent = card.title;
    // Exactement ce qui partira : du texte brut, jamais interprété.
    const text = document.createElement("pre");
    text.className = "approval-text";
    text.textContent = card.text;
    const refusal = document.createElement("div");
    refusal.className = "approval-refusal";
    const expiry = document.createElement("div");
    expiry.className = "approval-expiry";
    const actions = document.createElement("div");
    actions.className = "approval-actions";
    const accept = document.createElement("button");
    accept.type = "button";
    accept.className = "approval-btn approval-accept";
    accept.textContent = "Accepter";
    accept.addEventListener("click", () => this.decideApproval(card.id, "accept"));
    const refuse = document.createElement("button");
    refuse.type = "button";
    refuse.className = "approval-btn approval-refuse";
    refuse.textContent = "Refuser";
    refuse.addEventListener("click", () => this.decideApproval(card.id, "refuse"));
    const state = document.createElement("span");
    state.className = "approval-state";
    state.textContent = "envoyé…";
    state.hidden = true;
    actions.append(accept, refuse, state);
    root.append(title, text, refusal, expiry, actions);
    return { card, root, refusal, expiry, accept, refuse, state };
  }

  /**
   * Un clic. La trame porte l'empreinte de la carte affichée ; elle ne part
   * que si la connexion est ouverte (jamais mise en file), et les deux
   * boutons s'éteignent jusqu'à la réponse ou la liste suivante.
   */
  private decideApproval(id: number, decision: ApprovalDecision) {
    const frame = decisionFrame(this.approvals, id, decision, Date.now());
    if (!frame) {
      // un bouton que le minuteur n'avait pas encore éteint : repeindre suffit
      this.refreshApprovals();
      return;
    }
    if (!this.ws.sendApproval(frame)) {
      this.showApprovalNote(OFFLINE_NOT_SENT, false);
      this.refreshApprovals();
      return;
    }
    this.approvals = withDecisionSent(this.approvals, id);
    this.refreshApprovals();
  }

  /** Une note sous les cartes, qui s'efface d'elle-même. */
  private showApprovalNote(text: string, taken: boolean) {
    if (this.approvalNoteTimer !== null) window.clearTimeout(this.approvalNoteTimer);
    this.approvalNoteEl.textContent = text;
    this.approvalNoteEl.classList.toggle("ok", taken);
    this.approvalNoteEl.hidden = false;
    this.approvalsEl.hidden = false;
    this.approvalNoteTimer = window.setTimeout(() => {
      this.approvalNoteTimer = null;
      this.approvalNoteEl.hidden = true;
      this.refreshApprovals();
    }, APPROVAL_NOTE_MS);
  }

  private trimHistory() {
    if (this.history.length > MAX_MESSAGES) {
      this.history = this.history.slice(-MAX_MESSAGES);
    }
  }


  private autoResizeInput() {
    this.inputEl.style.height = "auto";
    const max = 120; // ~5 lines
    this.inputEl.style.height =
      Math.min(this.inputEl.scrollHeight, max) + "px";
  }

  /** « 1 850 / 2 000 » à l'approche de la limite ; rien avant. */
  private updateCounter() {
    if (!this.counterEl) return;
    const n = this.inputEl.value.length;
    this.counterEl.hidden = n < COUNTER_FROM;
    this.counterEl.textContent =
      `${n.toLocaleString("fr-FR")} / ${MAX_MESSAGE_CHARS.toLocaleString("fr-FR")} caractères` +
      (n >= MAX_MESSAGE_CHARS ? " — c'est la limite" : "");
  }

  /** Animated "Mika écrit…" bubble shown between send and reply. */
  private showTyping() {
    if (this.typingEl) {
      this.resetTypingTimer();
      return;
    }
    const bubble = document.createElement("div");
    bubble.className = "chat-bubble vtuber typing-indicator";
    bubble.setAttribute("aria-label", "Mika écrit…");
    for (let i = 0; i < 3; i++) {
      const dot = document.createElement("span");
      dot.className = "typing-dot";
      bubble.appendChild(dot);
    }
    this.messagesEl.appendChild(bubble);
    this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
    this.typingEl = bubble;
    this.resetTypingTimer();
  }

  private resetTypingTimer() {
    if (this.typingTimer !== null) window.clearTimeout(this.typingTimer);
    this.typingTimer = window.setTimeout(
      () => this.hideTyping(),
      TYPING_TIMEOUT_MS
    );
  }

  private hideTyping() {
    if (this.typingTimer !== null) {
      window.clearTimeout(this.typingTimer);
      this.typingTimer = null;
    }
    this.typingEl?.remove();
    this.typingEl = null;
  }

  private async handleFiles(files: FileList | File[]) {
    const arr = Array.from(files);
    const remaining = MAX_ATTACHMENTS - this.pendingAttachments.length;
    // Chaque dépôt raconte son propre sort : garder les refus du précédent
    // ferait porter à des pastilles acceptées le reproche d'un autre lot.
    this.attachmentNotices = [];
    const dropped = arr.length - remaining;
    if (dropped > 0) {
      this.attachmentNotices.push(
        dropped > 1
          ? `${dropped} fichiers ignorés : maximum ${MAX_ATTACHMENTS} pièces jointes.`
          : `1 fichier ignoré : maximum ${MAX_ATTACHMENTS} pièces jointes.`
      );
    }
    for (const file of arr.slice(0, remaining)) {
      if (file.size > MAX_FILE_SIZE) {
        this.attachmentNotices.push(
          `${file.name} ignoré : ${formatSize(file.size)} (maximum ` +
            `${formatSize(MAX_FILE_SIZE)}).`
        );
        continue;
      }
      try {
        const base64 = await readFileAsBase64(file);
        const att: PendingAttachment = { name: file.name, type: file.type, data: base64 };
        if (file.type.startsWith("image/")) {
          att.preview = await readFileAsDataURI(file);
        }
        this.pendingAttachments.push(att);
      } catch (e) {
        console.error("Erreur lecture fichier:", file.name, e);
        this.attachmentNotices.push(`${file.name} illisible : non joint.`);
      }
    }
    this.renderPreviews();
  }

  private renderPreviews() {
    this.previewsEl.innerHTML = "";
    for (let i = 0; i < this.pendingAttachments.length; i++) {
      const att = this.pendingAttachments[i];
      const chip = document.createElement("div");
      chip.className = "attachment-chip";

      if (att.preview) {
        const img = document.createElement("img");
        img.src = att.preview;
        chip.appendChild(img);
      } else {
        const icon = document.createElement("span");
        icon.className = "chip-icon";
        icon.textContent = fileIcon(att.type);
        chip.appendChild(icon);
      }

      const name = document.createElement("span");
      name.className = "chip-name";
      name.textContent = att.name;
      chip.appendChild(name);

      const rm = document.createElement("span");
      rm.className = "chip-remove";
      rm.textContent = "✕";
      const idx = i;
      rm.addEventListener("click", () => {
        this.pendingAttachments.splice(idx, 1);
        this.renderPreviews();
      });
      chip.appendChild(rm);

      this.previewsEl.appendChild(chip);
    }

    // Sous les pastilles, là où l'utilisateur regarde déjà pour compter ses
    // fichiers : cinq pastilles pour huit fichiers déposés, sinon, ne se
    // distingue pas d'un glisser-déposer réussi.
    for (const notice of this.attachmentNotices) {
      const note = document.createElement("div");
      note.className = "attachment-notice";
      note.textContent = notice;
      this.previewsEl.appendChild(note);
    }
  }

  private sendMessage() {
    const text = this.inputEl.value.trim();
    if (!text && this.pendingAttachments.length === 0) return;

    const cid = nextClientMsgId();
    let sent: boolean;

    if (this.pendingAttachments.length > 0) {
      // La même composition que le fil relu (chatSync.withAttachments) : la
      // ligne du serveur reconnaît ainsi la bulle qui lui appartient.
      // `matchText` — ce qui a été tapé — l'adopte encore si un fichier n'est
      // pas passé.
      const display = withAttachments(
        text, this.pendingAttachments.map((a) => a.name),
      );
      this.addMessage(display, "user", {
        cid,
        status: "pending",
        matchText: text,
      });
      sent = this.ws.sendChatWithAttachments(
        text, this.pendingAttachments, cid,
      );
      this.pendingAttachments = [];
      this.attachmentNotices = [];
      this.renderPreviews();
    } else {
      this.addMessage(text, "user", { cid, status: "pending" });
      sent = this.ws.sendChat(text, cid);
      // Le message parti, la note a fait son office : la laisser en ferait un
      // reproche accroché au tour suivant, qui n'a rien écarté.
      if (this.attachmentNotices.length) {
        this.attachmentNotices = [];
        this.renderPreviews();
      }
    }

    this.inputEl.value = "";
    this.autoResizeInput();
    this.updateCounter();
    // A message that never left the browser is not being answered, so no
    // typing indicator: the pending mark on the bubble is the truthful
    // signal, and it clears itself when the ack arrives after a reconnect.
    if (sent) this.showTyping();
  }

  addMessage(
    text: string,
    sender: "user" | "vtuber",
    opts: {
      id?: number;
      cid?: string;
      status?: MessageStatus;
      matchText?: string;
      /** For a bubble the server will never give an id — see StoredMessage. */
      localOnly?: boolean;
      /** Pensée murmurée — voir StoredMessage.inner. */
      inner?: boolean;
      /** Ce qu'elle envoie avec ce message — voir StoredMessage.files. */
      files?: SentFile[];
    } = {}
  ) {
    const display = sender === "vtuber" ? stripProsody(text) : text;
    if (!display) return;
    // A reply can arrive twice: once live, once in the catch-up that
    // follows a reconnect racing the same turn. The id is what makes the
    // second one recognisable.
    if (
      typeof opts.id === "number" &&
      this.history.some((m) => m.id === opts.id)
    ) {
      return;
    }
    const ts = Date.now();
    this.history.push({
      text: display,
      sender,
      ts,
      id: opts.id,
      cid: opts.cid,
      status: opts.status,
      matchText: opts.matchText,
      after: opts.localOnly ? this.cursor() : undefined,
      inner: opts.inner || undefined,
      ...(opts.files?.length ? { files: opts.files } : {}),
    });
    this.trimHistory();
    this.persistHistory();
    this.repaint({ animate: true });
  }

  /**
   * Redraw the thread from the model.
   *
   * Full repaint rather than incremental DOM surgery: a history merge can
   * insert messages *before* ones already displayed (a reply that arrived
   * while the tab was away sits earlier than what was typed since), and
   * append-only rendering cannot express that. The list is capped at
   * MAX_MESSAGES, so this is fifty nodes.
   */
  private repaint(opts: { animate: boolean }) {
    for (const child of Array.from(this.messagesEl.children)) {
      if (child !== this.typingEl) child.remove();
    }

    if (this.truncated) {
      const note = document.createElement("div");
      note.className = "chat-note";
      note.textContent =
        "Historique plus ancien tronqué : seuls les derniers messages sont affichés ici.";
      this.insertBeforeTyping(note);
    }

    this.history.forEach((msg, index) => {
      this.insertBeforeTyping(this.buildBubble(msg, opts.animate));
      // Ce que le serveur a écarté de cet envoi. Sous la bulle plutôt que
      // dans son infobulle : l'envoi a été *accepté*, donc rien dans son
      // apparence ne le distingue d'un envoi complet.
      if (msg.note) this.insertBeforeTyping(this.buildNote(msg.note));
      // La réponse ne viendra pas : dit sous la bulle (le message, lui, est
      // bien reçu) — pour une opératrice, avec où réparer.
      if (msg.replyNote) {
        this.insertBeforeTyping(this.buildNote(msg.replyNote, msg.replyHref));
      } else if (asleepNoteShown(this.history, index)) {
        this.insertBeforeTyping(this.buildNote(ASLEEP_NOTE));
      }
    });
    this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
  }

  /** Une note de la machine sous une bulle (jamais une parole de Mika). Un
   * lien n'y mène qu'à une page de la console. */
  private buildNote(text: string, href?: string): HTMLElement {
    const note = document.createElement("div");
    note.className = "chat-note";
    note.textContent = text;
    const page = consoleHref(href);
    if (page) {
      const link = document.createElement("a");
      link.href = `${API_BASE}${page}`;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "ouvrir la console";
      note.append(" ", link);
    }
    return note;
  }

  private insertBeforeTyping(el: HTMLElement) {
    // The typing indicator must stay the last child.
    if (this.typingEl) {
      this.messagesEl.insertBefore(el, this.typingEl);
    } else {
      this.messagesEl.appendChild(el);
    }
  }

  private buildBubble(msg: StoredMessage, animate: boolean): HTMLElement {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${msg.sender}`;
    if (!animate) bubble.classList.add("no-anim");
    if (msg.inner) bubble.classList.add("inner");
    if (msg.sender === "user" && msg.status && msg.status !== "sent") {
      bubble.classList.add(`status-${msg.status}`);
    }
    if (msg.sender === "vtuber") renderInline(bubble, msg.text);
    else bubble.textContent = msg.text;
    for (const file of msg.files ?? []) bubble.append(this.buildFile(file));

    const parts: string[] = [];
    if (msg.inner) parts.push("pensée à voix haute");
    if (msg.ts) {
      parts.push(
        new Date(msg.ts).toLocaleString("fr-FR", {
          day: "2-digit",
          month: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        })
      );
    }
    if (msg.status === "pending") parts.push("en attente d'envoi");
    if (msg.status === "failed") {
      // The reason is the whole point: "rate limited" and "your files were
      // rejected" are different problems with different fixes, and a single
      // "refusé" made them look like the same shrug.
      parts.push(msg.reason ? `refusé — ${msg.reason}` : "refusé par le serveur");
    }
    if (parts.length) bubble.title = parts.join(" · ");

    return bubble;
  }

  /**
   * Un fichier qu'elle a envoyé, sous son texte : un dessin en vignette (un clic
   * l'ouvre), un autre fichier en lien. Il se charge avec la session du
   * navigateur ; seul le compte dont le fil le porte peut le lire. Retiré par la
   * rétention : son nom, barré d'un mot.
   */
  private buildFile(file: SentFile): HTMLElement {
    const box = document.createElement("div");
    box.className = "chat-file";
    if (file.available === false) {
      box.textContent = `${file.name} (plus disponible)`;
      box.classList.add("gone");
      return box;
    }
    const link = document.createElement("a");
    link.href = `${API_BASE}${file.url}`;
    link.target = "_blank";
    link.rel = "noopener";
    if (file.kind === "image") {
      const img = document.createElement("img");
      img.className = "chat-image";
      img.src = link.href;
      img.alt = file.name;
      img.loading = "lazy";
      // la vignette n'a pas pu se charger (retirée, session expirée) : le lien reste
      img.addEventListener("error", () => {
        img.remove();
        link.textContent = file.name;
      });
      link.append(img);
    } else {
      link.textContent = `📎 ${file.name}`;
      link.download = file.name;
    }
    box.append(link);
    return box;
  }
}
