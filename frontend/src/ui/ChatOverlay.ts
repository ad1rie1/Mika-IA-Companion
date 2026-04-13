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
  private inputEl: HTMLInputElement;
  private sendBtn: HTMLElement;
  private attachBtn: HTMLElement;
  private previewsEl: HTMLElement;
  private fileInput: HTMLInputElement;
  private ws: WebSocketClient;
  private pendingAttachments: PendingAttachment[] = [];

  constructor(ws: WebSocketClient) {
    this.ws = ws;
    this.messagesEl = document.getElementById("chat-messages")!;
    this.inputEl = document.getElementById("chat-input") as HTMLInputElement;
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

    this.setupEvents();
  }

  private setupEvents() {
    this.sendBtn.addEventListener("click", () => this.sendMessage());

    this.inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
    });

    this.attachBtn.addEventListener("click", () => this.fileInput.click());

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
      this.addMessage(data.text, "vtuber");
    });
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
  }

  addMessage(text: string, sender: "user" | "vtuber") {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${sender}`;
    bubble.textContent = text;
    this.messagesEl.appendChild(bubble);

    this.messagesEl.scrollTop = this.messagesEl.scrollHeight;

    while (this.messagesEl.children.length > 50) {
      this.messagesEl.removeChild(this.messagesEl.firstChild!);
    }
  }
}
