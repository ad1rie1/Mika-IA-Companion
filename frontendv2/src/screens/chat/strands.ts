/**
 * Les fils de travail d'une opératrice en mode pro (ADR 0164) et leurs commandes (`/clear`, `/renommer`…) : la liste,
 * le fil actif, ce qu'on en règle, le menu des commandes, leur dessin. Les règles sont dans le module pur
 * `@web/ui/strands`, le balisage dans `markup.ts` ; `chat.ts` lui passe les trames.
 */
import type { WebSocketClient } from "@web/network/WebSocketClient";
import type { StrandResultMessage } from "@web/types";
import type { StoredMessage } from "@web/ui/chatSync";
import {
  COMMANDS,
  localStrand,
  newStrandId,
  parseStrands,
  STRAND_DESCRIPTION_MAX,
  STRAND_TITLE_MAX,
  strandLabel,
  strandOf,
  withLocal,
  type StrandCommand,
  type StrandInfo,
} from "@web/ui/strands";
import { read, write } from "../../shared/storage";
import { $, h, on } from "../../shell/dom";
import { closeModal, openMenu, openModal, toast, type MenuItem } from "../../shell/float";
import { strandHead, strandsPane } from "./markup";

const STRAND_NOTE_MS = 6000;
const STRAND_PREFIX = "mika2_chat_strand";

const STRAND_RESULT_NOTES: Record<string, string> = {
  invalid: "Réglage refusé : un champ est trop long.",
  forbidden: "Réglage refusé : réservé à une opératrice.",
  failed: "Le réglage n'a pas abouti — réessaie.",
};

/** Ce que les fils demandent au chat. */
export interface StrandsHost {
  ws(): WebSocketClient | null;
  body(): HTMLElement | null;
  proMode(): boolean;
  history(): readonly StoredMessage[];
  input(): HTMLTextAreaElement | null;
  focusInput(): void;
  paintThread(toBottom?: boolean): void;
  paintTyping(): void;
  refreshHead(): void;
}

export class WorkStrands {
  private strands: StrandInfo[] = [];
  private localStrands: StrandInfo[] = [];
  /** Le fil montré en mode pro ; il change par `selectStrand`, `ensureStrand` ou `adopt`. */
  activeStrand: string;
  private showArchived = false;
  private strandNote = "";
  private strandNoteTimer: number | null = null;
  private readonly unreadStrands = new Set<string>();
  private readonly strandsAsked = new Set<string>();
  private readonly strandKey: string;

  constructor(
    private readonly host: StrandsHost,
    who: string,
  ) {
    this.strandKey = `${STRAND_PREFIX}:${who}`;
    this.activeStrand = strandOf(read(() => localStorage, this.strandKey)) ?? "";
  }

  private get ws(): WebSocketClient | null {
    return this.host.ws();
  }

  private get body(): HTMLElement | null {
    return this.host.body();
  }

  private get proMode(): boolean {
    return this.host.proMode();
  }

  private get history(): readonly StoredMessage[] {
    return this.host.history();
  }

  /** Ce fil devient le fil actif, retenu par ce navigateur (la palette y mène). */
  adopt(id: string): void {
    this.activeStrand = id;
    write(() => localStorage, this.strandKey, id);
  }

  markRead(id: string): void {
    this.unreadStrands.delete(id);
  }

  /** Une réponse est arrivée dans un fil qu'on ne regarde pas. */
  noteUnread(id: string): void {
    this.unreadStrands.add(id);
    this.paintStrands();
  }

  get allStrands(): StrandInfo[] {
    const all = withLocal(this.strands, this.localStrands);
    if (this.activeStrand && !all.some((s) => s.id === this.activeStrand)) return [localStrand(this.activeStrand), ...all];
    return all;
  }

  strandInfo(id: string): StrandInfo {
    return this.allStrands.find((s) => s.id === id) ?? localStrand(id);
  }

  /** En mode pro, un fil est toujours montré : le dernier choisi, sinon le plus récent, sinon un neuf. */
  ensureStrand(): void {
    if (!this.proMode || this.activeStrand) return;
    const recent = this.allStrands.find((s) => !s.archived);
    this.activeStrand = recent?.id ?? newStrandId();
    write(() => localStorage, this.strandKey, this.activeStrand);
  }

  onStrands(raw: unknown): void {
    this.strands = parseStrands(raw);
    const known = new Set(this.strands.map((s) => s.id));
    // un fil ouvert ici et resté vide s'en va, sauf celui qu'on regarde
    this.localStrands = this.localStrands.filter(
      (s) => !known.has(s.id) && (s.id === this.activeStrand || this.history.some((m) => m.strand === s.id)),
    );
    this.ensureStrand();
    if (this.proMode) this.askStrandHistory(this.activeStrand);
    this.paintStrands();
    this.host.refreshHead();
  }

  onStrandResult(data: StrandResultMessage): void {
    const note = STRAND_RESULT_NOTES[data.status];
    if (note) this.noteStrand(note);
  }

  selectStrand(id: string): void {
    this.activeStrand = id;
    write(() => localStorage, this.strandKey, id);
    this.unreadStrands.delete(id);
    this.askStrandHistory(id);
    this.paintStrands();
    this.host.paintThread(true);
    this.host.paintTyping();
    this.host.focusInput();
  }

  /** Un fil que le serveur connaît mieux que cet onglet : ses messages, une fois par session. */
  askStrandHistory(id: string): void {
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
    this.host.refreshHead();
    toast("Fil neuf ouvert : rien n'est effacé.", { ico: "threads" });
  }

  noteOpener(id: string, text: string): void {
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
    this.host.refreshHead();
  }

  runCommand(command: StrandCommand): void {
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

  commandsMenu(anchor?: HTMLElement | null): void {
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
  complete(word: string): void {
    const input = this.host.input();
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

  paintStrands(): void {
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

  mount(section: HTMLElement): void {
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
  }
}
