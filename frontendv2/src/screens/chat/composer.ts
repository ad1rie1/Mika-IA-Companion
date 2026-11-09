/**
 * Le champ du chat : les pièces jointes, les emojis, le compteur, la phrase préremplie, l'envoi. Une commande tapée en
 * mode pro part vers `strands.ts` au lieu d'être envoyée. Le balisage est dans `markup.ts` ; ce qui part, `chat.ts` le
 * pose dans le fil (`addMessage`).
 */
import type { WebSocketClient } from "@web/network/WebSocketClient";
import type { ChatMode, HistoryAttachment } from "@web/types";
import { nextClientMsgId, proMode, withAttachments, type MessageStatus } from "@web/ui/chatSync";
import { insertEmoji } from "@web/ui/emojis";
import { parseCommand, unescapeSlash, type StrandCommand } from "@web/ui/strands";
import { $, on } from "../../shell/dom";
import { openMenu } from "../../shell/float";
import { attachmentsMarkup, type PendingAttachment } from "./markup";

/** Ce que le champ accepte en pièces jointes (les plafonds du serveur, `pipeline/media.py`). */
export const ACCEPTED_TYPES = [
  "image/jpeg", "image/png", "image/gif", "image/webp",
  "audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg", "audio/webm",
  "text/plain", "text/csv", "text/markdown", "application/json",
  "application/pdf",
].join(",");
const MAX_FILE_SIZE = 5 * 1024 * 1024;
const MAX_ATTACHMENTS = 5;
/** La longueur maximale d'un message, celle du serveur (`adapters/web/protocol.py::MAX_MESSAGE_CHARS`). */
export const MAX_MESSAGE_CHARS = 2000;
const COUNTER_FROM = 1800;

const EMOJIS = ["😊", "😅", "😂", "🙂", "😉", "😍", "🥲", "😴", "🤔", "😬", "🙏", "👍", "👌", "🔥", "✨", "❤️", "💪", "🎉", "☕", "🌧️", "🚶", "📎", "✅", "❌"];

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

/** Ce qu'un message envoyé emporte dans le fil. */
export interface OutgoingMessage {
  cid: string;
  status: MessageStatus;
  matchText?: string;
  attachments?: HistoryAttachment[];
  mode?: "pro";
  strand?: string;
}

/** Ce que le champ demande au chat. */
export interface ComposerHost {
  ws(): WebSocketClient | null;
  body(): HTMLElement | null;
  proMode(): boolean;
  activeStrand(): string;
  /** L'écran Chat est-il celui qu'on regarde ? */
  onScreen(): boolean;
  addMessage(text: string, opts: OutgoingMessage): void;
  runCommand(command: StrandCommand): void;
  noteOpener(id: string, text: string): void;
  showTyping(): void;
}

export class ChatComposer {
  private pending: PendingAttachment[] = [];
  private notices: string[] = [];
  /** Une phrase à poser dans le champ au prochain dessin (l'écran Carte : « Demander à Mika »). */
  private pendingDraft: string | null = null;

  constructor(private readonly host: ComposerHost) {}

  private get ws(): WebSocketClient | null {
    return this.host.ws();
  }

  private get body(): HTMLElement | null {
    return this.host.body();
  }

  private get proMode(): boolean {
    return this.host.proMode();
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

  paintAttachments(): void {
    const zone = this.body ? $("[data-attach]", this.body) : null;
    if (!zone) return;
    zone.innerHTML = attachmentsMarkup(this.pending, this.notices);
    zone.hidden = !this.pending.length && !this.notices.length;
  }

  // ── L'envoi ───────────────────────────────────────────────────────

  input(): HTMLTextAreaElement | null {
    return this.body ? $<HTMLTextAreaElement>("[data-chat-input]", this.body) : null;
  }

  focusInput(): void {
    this.input()?.focus();
  }

  send(): void {
    const input = this.input();
    if (!input || !this.ws) return;
    const typed = input.value.trim();
    if (!typed && !this.pending.length) return;
    // en mode pro, une commande (`/clear`…) agit sur les fils et ne part pas
    const command = this.proMode ? parseCommand(typed) : null;
    if (command) {
      this.clearInput(input);
      this.host.runCommand(command);
      return;
    }
    const text = this.proMode ? unescapeSlash(typed) : typed;
    const cid = nextClientMsgId();
    // le mode et le fil sont pris à l'envoi et voyagent avec la trame
    const mode: ChatMode = this.proMode ? "pro" : "";
    const pro = proMode(mode);
    const strand = pro ? this.host.activeStrand() : undefined;
    let sent: boolean;
    if (this.pending.length) {
      // la même composition que le fil relu : la ligne du serveur reconnaîtra sa bulle
      const display = withAttachments(text, this.pending.map((a) => a.name));
      this.host.addMessage(display, { cid, status: "pending", matchText: text, mode: pro, strand,
        attachments: this.pending.map((a) => ({ name: a.name, kind: a.type.startsWith("image/") ? "image" : a.type.startsWith("audio/") ? "audio" : "file" })) });
      sent = this.ws.sendChatWithAttachments(text, this.pending, cid, mode, strand);
      this.pending = [];
    } else {
      this.host.addMessage(text, { cid, status: "pending", mode: pro, strand });
      sent = this.ws.sendChat(text, cid, mode, strand);
    }
    this.notices = [];
    this.paintAttachments();
    this.clearInput(input);
    if (strand) this.host.noteOpener(strand, text);
    // un message resté dans le navigateur n'est pas en train d'être répondu
    if (sent) this.host.showTyping();
  }

  private clearInput(input: HTMLTextAreaElement): void {
    input.value = "";
    this.resizeInput(input);
    this.paintCounter(input);
    this.ws?.noteComposing("");
  }

  resizeInput(input: HTMLTextAreaElement): void {
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

  emojis(anchor: HTMLElement): void {
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
  focusOnType(e: KeyboardEvent): void {
    if (!this.host.onScreen() || e.ctrlKey || e.metaKey || e.altKey) return;
    const target = e.target as HTMLElement;
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target.isContentEditable) return;
    if (document.querySelector(".modal-scrim, .menu") || !document.getElementById("palette")?.hidden) return;
    if (e.key.length === 1) this.focusInput();
  }

  /** Une phrase à poser dans le champ au prochain dessin. */
  setDraft(text: string): void {
    this.pendingDraft = text;
  }

  /** La phrase préremplie, posée dans le champ (après ce qui y était déjà écrit), le curseur au bout. */
  applyDraft(): void {
    const text = this.pendingDraft;
    const input = this.input();
    if (text === null || !input) return;
    this.pendingDraft = null;
    const before = input.value.trim();
    input.value = (before ? `${before}\n${text}` : text).slice(0, MAX_MESSAGE_CHARS);
    this.resizeInput(input);
    this.paintCounter(input);
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
    this.ws?.noteComposing(input.value);
  }

  mount(section: HTMLElement): void {
    section.addEventListener("input", (e) => {
      const target = e.target as HTMLElement;
      if (!target.matches("[data-chat-input]")) return;
      const input = target as HTMLTextAreaElement;
      this.resizeInput(input);
      this.paintCounter(input);
      this.ws?.noteComposing(input.value);
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
}
