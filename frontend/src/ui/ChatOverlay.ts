import { WebSocketClient } from "../network/WebSocketClient";

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
].join(",");

const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5 MB
const MAX_ATTACHMENTS = 5;
const MAX_MESSAGES = 50;
const HISTORY_KEY = "vtuber_chat_history";
// How long the "typing" indicator survives without a reply. Slightly above
// the backend AI_CALL_TIMEOUT (60s) so it disappears on its own when the
// backend gave up silently.
const TYPING_TIMEOUT_MS = 75000;

interface StoredMessage {
  text: string;
  sender: "user" | "vtuber";
  ts: number;
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

function fileIcon(type: string): string {
  if (type.startsWith("image/")) return "🖼️";
  if (type.startsWith("audio/")) return "🎵";
  return "📄";
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
  private history: StoredMessage[] = [];
  private typingEl: HTMLElement | null = null;
  private typingTimer: number | null = null;

  constructor(ws: WebSocketClient) {
    this.ws = ws;
    this.messagesEl = document.getElementById("chat-messages")!;
    this.inputEl = document.getElementById("chat-input") as HTMLTextAreaElement;
    this.sendBtn = document.getElementById("chat-send")!;
    this.attachBtn = document.getElementById("chat-attach")!;
    this.previewsEl = document.getElementById("attachment-previews")!;

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

  /** Repaint messages persisted from the previous session (no animation). */
  private restoreHistory() {
    try {
      const raw = localStorage.getItem(HISTORY_KEY);
      if (!raw) return;
      const stored = JSON.parse(raw);
      if (!Array.isArray(stored)) return;
      this.history = stored
        .filter(
          (m): m is StoredMessage =>
            m &&
            typeof m.text === "string" &&
            (m.sender === "user" || m.sender === "vtuber")
        )
        .slice(-MAX_MESSAGES);
      for (const msg of this.history) {
        this.renderBubble(msg.text, msg.sender, { animate: false, ts: msg.ts });
      }
      this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
    } catch {
      this.history = [];
    }
  }

  private persistHistory() {
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(this.history));
    } catch {
      // Quota exceeded / private mode — history is best-effort only.
    }
  }

  /** Wipe the displayed messages + persisted history (typing bubble kept). */
  clearHistory() {
    this.history = [];
    try {
      localStorage.removeItem(HISTORY_KEY);
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
    this.inputEl.addEventListener("input", () => this.autoResizeInput());

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

    this.ws.on("speech", (data) => {
      this.hideTyping();
      if (typeof data.text === "string" && data.text) {
        this.addMessage(data.text, "vtuber");
      }
    });
  }

  private autoResizeInput() {
    this.inputEl.style.height = "auto";
    const max = 120; // ~5 lines
    this.inputEl.style.height =
      Math.min(this.inputEl.scrollHeight, max) + "px";
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
    for (const file of arr.slice(0, remaining)) {
      if (file.size > MAX_FILE_SIZE) {
        console.warn(`Fichier trop grand ignoré: ${file.name} (${file.size} bytes)`);
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
  }

  private sendMessage() {
    const text = this.inputEl.value.trim();
    if (!text && this.pendingAttachments.length === 0) return;

    // Build display label for attachments
    if (this.pendingAttachments.length > 0) {
      const label = this.pendingAttachments.map((a) => a.name).join(", ");
      const display = text ? `${text} [${label}]` : `[${label}]`;
      this.addMessage(display, "user");
    } else {
      this.addMessage(text, "user");
    }

    if (this.pendingAttachments.length > 0) {
      this.ws.sendChatWithAttachments(text, this.pendingAttachments);
      this.pendingAttachments = [];
      this.renderPreviews();
    } else {
      this.ws.sendChat(text);
    }

    this.inputEl.value = "";
    this.autoResizeInput();
    this.showTyping();
  }

  addMessage(text: string, sender: "user" | "vtuber") {
    const display = sender === "vtuber" ? stripProsody(text) : text;
    if (!display) return;
    const ts = Date.now();
    this.renderBubble(display, sender, { animate: true, ts });

    this.history.push({ text: display, sender, ts });
    if (this.history.length > MAX_MESSAGES) {
      this.history = this.history.slice(-MAX_MESSAGES);
    }
    this.persistHistory();
  }

  private renderBubble(
    text: string,
    sender: "user" | "vtuber",
    opts: { animate: boolean; ts?: number }
  ) {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${sender}`;
    if (!opts.animate) bubble.classList.add("no-anim");
    bubble.textContent = text;
    if (opts.ts) {
      const d = new Date(opts.ts);
      bubble.title = d.toLocaleString("fr-FR", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    }
    // The typing indicator must stay the last child.
    if (this.typingEl) {
      this.messagesEl.insertBefore(bubble, this.typingEl);
    } else {
      this.messagesEl.appendChild(bubble);
    }
    this.messagesEl.scrollTop = this.messagesEl.scrollHeight;

    while (this.messagesEl.children.length > MAX_MESSAGES + 1) {
      const first = this.messagesEl.firstChild!;
      if (first === this.typingEl) break;
      this.messagesEl.removeChild(first);
    }
  }
}
