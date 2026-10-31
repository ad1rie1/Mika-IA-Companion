/**
 * Le sélecteur d'emojis, à droite du champ : un bouton 😊 et son panneau,
 * ouvert au-dessus de la saisie. Choisir un emoji le pose au curseur sans
 * fermer le panneau (on en met souvent plusieurs) ; un clic ailleurs ou
 * Échap le referme. Les familles, l'insertion et les récents sont dans
 * `emojis.ts`.
 *
 * Le champ garde le focus et sa sélection : les boutons du panneau ne le
 * prennent pas (`mousedown` sans défaut), et une insertion émet `input`,
 * comme une frappe — la hauteur du champ, le compteur et les suggestions de
 * commandes suivent sans que ce panneau les connaisse.
 */

import { EMOJI_GROUPS, insertEmoji, parseRecent, withRecent } from "./emojis";

const RECENT_KEY = "vtuber_chat_emoji_recent";
const RECENT_TAB = -1;

function readRecent(): string[] {
  try {
    return parseRecent(localStorage.getItem(RECENT_KEY));
  } catch {
    return [];
  }
}

function writeRecent(recent: readonly string[]): void {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(recent));
  } catch {
    // stockage fermé : les récents valent pour cet onglet seulement
  }
}

export class EmojiPicker {
  private readonly root: HTMLElement;
  private readonly toggle: HTMLButtonElement;
  private readonly input: HTMLTextAreaElement;
  private readonly panel: HTMLElement;
  private readonly tabs: HTMLElement;
  private readonly grid: HTMLElement;
  private recent: string[];
  /** L'onglet montré : `RECENT_TAB`, ou l'indice d'une famille. */
  private tab: number;

  constructor(root: HTMLElement, input: HTMLTextAreaElement) {
    this.root = root;
    this.input = input;
    this.recent = readRecent();
    this.tab = this.recent.length ? RECENT_TAB : 0;

    this.toggle = document.createElement("button");
    this.toggle.type = "button";
    this.toggle.className = "emoji-toggle";
    this.toggle.textContent = "😊";
    this.toggle.title = "Emojis";
    this.toggle.setAttribute("aria-label", "Emojis");
    this.toggle.setAttribute("aria-haspopup", "dialog");
    this.toggle.setAttribute("aria-expanded", "false");

    this.panel = document.createElement("div");
    this.panel.className = "emoji-panel";
    this.panel.setAttribute("role", "dialog");
    this.panel.setAttribute("aria-label", "Choisir un emoji");
    this.panel.hidden = true;
    this.tabs = document.createElement("div");
    this.tabs.className = "emoji-tabs";
    this.tabs.setAttribute("role", "tablist");
    this.grid = document.createElement("div");
    this.grid.className = "emoji-grid";
    this.panel.append(this.tabs, this.grid);
    this.root.append(this.panel, this.toggle);

    this.toggle.addEventListener("click", () => this.setOpen(this.panel.hidden));
    // le champ garde son focus et sa sélection pendant qu'on choisit
    this.panel.addEventListener("mousedown", (e) => e.preventDefault());
    // le chemin, pas la cible : un onglet cliqué est déjà remplacé quand le clic arrive ici
    document.addEventListener("click", (e) => {
      if (!this.panel.hidden && !e.composedPath().includes(this.root)) this.setOpen(false);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !this.panel.hidden) {
        this.setOpen(false);
        this.input.focus();
      }
    });
  }

  private setOpen(open: boolean) {
    if (open) this.paint();
    this.panel.hidden = !open;
    this.toggle.setAttribute("aria-expanded", String(open));
    this.toggle.classList.toggle("open", open);
  }

  private paint() {
    if (this.tab === RECENT_TAB && !this.recent.length) this.tab = 0;
    const tabs: HTMLButtonElement[] = [];
    if (this.recent.length) tabs.push(this.tabButton(RECENT_TAB, "🕘", "Récents"));
    EMOJI_GROUPS.forEach((g, i) => tabs.push(this.tabButton(i, g.icon, g.label)));
    this.tabs.replaceChildren(...tabs);

    const list = this.tab === RECENT_TAB ? this.recent : EMOJI_GROUPS[this.tab].emojis;
    this.grid.replaceChildren(
      ...list.map((emoji) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "emoji-cell";
        b.textContent = emoji;
        b.addEventListener("click", () => this.pick(emoji));
        return b;
      })
    );
    this.grid.scrollTop = 0;
  }

  private tabButton(index: number, icon: string, label: string): HTMLButtonElement {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "emoji-tab";
    b.textContent = icon;
    b.title = label;
    b.setAttribute("role", "tab");
    b.setAttribute("aria-label", label);
    b.setAttribute("aria-selected", String(index === this.tab));
    b.addEventListener("click", () => {
      this.tab = index;
      this.paint();
    });
    return b;
  }

  /** Pose l'emoji au curseur ; un champ plein le refuse sans rien couper. */
  private pick(emoji: string) {
    const { value, selectionStart, selectionEnd, maxLength } = this.input;
    const limit = maxLength > 0 ? maxLength : Infinity;
    const next = insertEmoji(value, selectionStart, selectionEnd, emoji, limit);
    if (!next) return;
    this.input.value = next.value;
    this.input.focus();
    this.input.setSelectionRange(next.caret, next.caret);
    this.input.dispatchEvent(new Event("input", { bubbles: true }));
    this.recent = withRecent(this.recent, emoji);
    writeRecent(this.recent);
    // l'onglet « Récents » se réordonne à sa prochaine ouverture, pas sous le pointeur
  }
}
