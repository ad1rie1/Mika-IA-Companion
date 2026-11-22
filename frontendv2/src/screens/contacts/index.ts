/**
 * L'écran « Contacts » (ADR 0298) : tous ceux que Mika connaît pour toi — vus dans ton Teams, tes boîtes, ton
 * téléphone, ou dont tu lui as parlé — et leurs organisations. La forme : la maquette validée
 * (`maquette/ecrans/contacts.js`) ; les données : `protocole-moi.md` § 12 ; le rendu : `view.ts`. Il remplace l'onglet
 * Contacts du courrier (`#mail/contacts` y mène).
 *
 * Ce que l'API ne sert pas ne s'invente pas ici : « Ce que Mika en sait » dit ce que l'annuaire tient (son poste, son
 * service, son organisation) et ce qu'elle a compris de ses derniers messages (lot 6), chaque fait d'où il vient — un
 * fait d'un de tes comptes s'oublie par sa croix, après confirmation ; « Lui présenter quelqu'un » ouvre le chat, où la
 * fiche naît de ce que tu lui racontes. Oublier un contact se confirme ; un contact qui ne vient pas que de tes
 * comptes ne s'oublie pas d'ici (le serveur dit pourquoi).
 */
import { fetchContactSheet, fetchContactsPage, forgetContact, forgetContactFact, type ContactKind, type ContactLine, type ContactSheet, type ContactsPage } from "../../api/contacts";
import { ApiError } from "../../api/moi";
import { $, isMobile, on } from "../../shell/dom";
import { toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import type { PaletteEntry } from "../../shell/palette";
import type { ScreenContext, ScreenDef, Shell } from "../../shell/shell";
import { CachedMap, confirmModal, failureText } from "../../shared/kit";
import { clippedQuery, contactHash, forgetFactQuestion, forgetQuestion, ID, listBody, listTools, paletteSub, routeId, sheetMarkup, sheetPlaceholder, type ListView } from "./view";

/** Une page de la liste ; les suivantes s'ajoutent (« Afficher les suivants »). */
const PAGE_SIZE = 100;
/** Relire ce qui arrive tant que l'écran est ouvert. */
const EVERY_MS = 60_000;
const SEARCH_DELAY_MS = 250;

export interface ContactsHooks {
  /** Ouvrir le chat avec une phrase préremplie (« Lui présenter quelqu'un »). */
  ask: (text: string) => void;
}

class ContactsScreen {
  private body: HTMLElement | null = null;
  private ctx: ScreenContext | null = null;
  private q = "";
  private kind: ContactKind | "" = "";
  private page: ContactsPage | null = null;
  private items: ContactLine[] = [];
  private loading = false;
  private error = "";
  private seq = 0;
  private readonly sheets = new CachedMap<ContactSheet>((key) => fetchContactSheet(Number(key)), 30_000);
  private timer = 0;
  private searchTimer = 0;

  constructor(
    private readonly shell: Shell,
    private readonly hooks: ContactsHooks,
  ) {
    // la palette (Ctrl K) cherche aussi parmi tes contacts : une lecture, un peu après le démarrage
    window.setTimeout(() => {
      if (!this.page) void this.load();
    }, 3000);
  }

  def(): ScreenDef {
    return {
      id: ID,
      title: "Contacts",
      icon: "users",
      subtitle: () => (this.page ? `${this.page.counts.all} pour toi` : ""),
      actions: () => `<button class="btn" type="button" data-cx-presenter>${ico("user-plus", "sm")}<span class="lbl">Lui présenter quelqu'un</span></button>`,
      mount: (section) => this.mount(section),
      render: (body, ctx) => this.render(body, ctx),
      search: () => this.searchEntries(),
    };
  }

  // ── Les lectures ───────────────────────────────────────────────────

  private open(): boolean {
    return this.shell.ctx?.screen === ID && !!this.body?.isConnected;
  }

  /** La liste depuis sa première page (une autre recherche, une autre sorte, une relecture). */
  private async load(quiet = false): Promise<void> {
    const seq = ++this.seq;
    if (!quiet) {
      this.loading = true;
      this.paintList();
    }
    try {
      const got = await fetchContactsPage({ q: this.q.trim(), kind: this.kind, page: 1, size: PAGE_SIZE });
      if (seq !== this.seq) return;
      // une relecture discrète garde ce que « Afficher les suivants » avait ajouté, si rien n'a changé devant
      const kept = quiet && this.items.length > got.items.length && JSON.stringify(this.items.slice(0, got.items.length)) === JSON.stringify(got.items);
      this.page = got;
      if (!kept) this.items = got.items;
      this.error = "";
    } catch (err) {
      if (seq !== this.seq) return;
      this.error = failureText(err);
    }
    this.loading = false;
    this.shell.refreshHead();
    this.paint();
  }

  /** « Afficher les suivants » : la page d'après, ajoutée. */
  private async more(): Promise<void> {
    if (!this.page || this.loading) return;
    const seq = this.seq;
    this.loading = true;
    this.paintList();
    try {
      const next = Math.floor(this.items.length / PAGE_SIZE) + 1;
      const got = await fetchContactsPage({ q: this.q.trim(), kind: this.kind, page: next, size: PAGE_SIZE });
      if (seq !== this.seq) return;
      const known = new Set(this.items.map((c) => c.id));
      this.items = [...this.items, ...got.items.filter((c) => !known.has(c.id))];
      this.page = { ...got, page: next };
    } catch (err) {
      if (seq === this.seq) toast(failureText(err), { ico: "alert" });
    }
    this.loading = false;
    this.paintList();
  }

  /** Le contact ouvert : celui de la route, sinon (sur un écran large) le premier de la liste. */
  private selected(): number | null {
    const id = routeId(this.ctx?.item ?? null);
    if (id !== null) return id;
    if (isMobile()) return null;
    return this.items[0]?.id ?? null;
  }

  private async loadSheet(id: number, force = false): Promise<void> {
    const cached = this.sheets.get(String(id));
    const before = cached.version;
    await cached.load(force);
    if (this.open() && this.selected() === id && cached.version !== before) this.paintSheet();
  }

  private schedule(): void {
    window.clearInterval(this.timer);
    this.timer = window.setInterval(() => {
      if (!this.open()) {
        window.clearInterval(this.timer);
        return;
      }
      if (document.visibilityState !== "visible") return;
      void this.load(true);
      const id = this.selected();
      if (id !== null) void this.loadSheet(id, true);
    }, EVERY_MS);
  }

  // ── Le rendu ───────────────────────────────────────────────────────

  private render(body: HTMLElement, ctx: ScreenContext): void {
    this.body = body;
    this.ctx = ctx;
    if (!$(".cx-split", body)) {
      body.innerHTML = `<div class="split ct-split cx-split"><aside class="pane" data-cx-pane></aside><section class="pane ct-pane" data-cx-card></section></div>`;
      this.paintTools();
    }
    this.paint();
    if (!this.page) void this.load();
    this.schedule();
  }

  private paint(): void {
    if (!this.body) return;
    this.paintList();
    this.paintSheet();
  }

  private listView(): ListView {
    return { q: this.q, kind: this.kind, page: this.page, items: this.items, selected: this.selected(), loading: this.loading, error: this.error, now: Date.now() };
  }

  /** La recherche et les choix : dessinés une fois, puis seulement leurs nombres et leur choix (la saisie reste). */
  private paintTools(): void {
    const pane = this.body && $<HTMLElement>("[data-cx-pane]", this.body);
    if (!pane) return;
    pane.innerHTML = `${listTools(this.listView())}<div class="pane-scroll" data-cx-list></div>`;
  }

  private paintList(): void {
    const pane = this.body && $<HTMLElement>("[data-cx-pane]", this.body);
    if (!pane) return;
    const seg = $<HTMLElement>(".ml-tools", pane);
    const fresh = document.createElement("div");
    fresh.innerHTML = listTools(this.listView());
    const freshSeg = $<HTMLElement>(".ml-tools", fresh);
    if (seg && freshSeg) seg.replaceWith(freshSeg);
    const list = $<HTMLElement>("[data-cx-list]", pane);
    if (!list) return;
    const top = list.scrollTop;
    list.innerHTML = listBody(this.listView());
    list.scrollTop = top;
  }

  private paintSheet(): void {
    const card = this.body && $<HTMLElement>("[data-cx-card]", this.body);
    if (!card) return;
    const id = this.selected();
    this.body?.querySelector(".cx-split")?.classList.toggle("lire", routeId(this.ctx?.item ?? null) !== null);
    if (id === null) {
      card.innerHTML = this.page && !this.items.length ? "" : sheetPlaceholder("none");
      return;
    }
    const cached = this.sheets.get(String(id));
    if (cached.value && cached.value.id === id) {
      const scroll = $<HTMLElement>(".pane-scroll", card);
      // la fiche montrée (pas `data-cx` : ce serait un contact à choisir, et tout clic dans la fiche le rechoisirait)
      const top = card.dataset.shown === String(id) && scroll ? scroll.scrollTop : 0;
      card.innerHTML = sheetMarkup(cached.value, Date.now());
      card.dataset.shown = String(id);
      const next = $<HTMLElement>(".pane-scroll", card);
      if (next) next.scrollTop = top;
    } else if (cached.error) {
      const gone = cached.error instanceof ApiError && cached.error.status === 404;
      card.innerHTML = sheetPlaceholder(gone ? "missing" : "error", failureText(cached.error));
    } else {
      card.innerHTML = sheetPlaceholder("loading");
    }
    if (!cached.settled) void this.loadSheet(id);
  }

  // ── Les gestes ─────────────────────────────────────────────────────

  private mount(section: HTMLElement): void {
    on(section, "[data-cx]", "click", (_e, b) => this.shell.go(contactHash(Number(b.dataset.cx))));
    on(section, "[data-cx-lien]", "click", (e, b) => {
      e.preventDefault();
      this.shell.go(contactHash(Number(b.dataset.cxLien)));
    });
    on(section, "[data-retour-cx]", "click", () => this.shell.go(`#${ID}`));
    on(section, "[data-cxsorte]", "click", (_e, b) => {
      const kind = (b.dataset.cxsorte ?? "") as ContactKind | "";
      if (kind === this.kind) return;
      this.kind = kind;
      void this.load();
    });
    on(section, "[data-cx-plus]", "click", () => void this.more());
    on(section, "[data-cx-relire]", "click", () => {
      void this.load();
      const id = this.selected();
      if (id !== null) void this.loadSheet(id, true);
    });
    on(section, "[data-cx-oublier]", "click", () => void this.forget());
    on(section, "[data-cx-oublier-fait]", "click", (_e, b) => void this.forgetFact(Number(b.dataset.cxOublierFait)));
    on(section, "[data-cx-presenter]", "click", () => this.hooks.ask("Je voudrais te présenter quelqu'un : "));
    section.addEventListener("input", (e) => {
      const t = e.target as HTMLInputElement;
      if (!t.matches("[data-cxq]")) return;
      window.clearTimeout(this.searchTimer);
      this.q = clippedQuery(t.value);
      this.searchTimer = window.setTimeout(() => void this.load(), SEARCH_DELAY_MS);
    });
  }

  /** « Oublier ce contact » : seulement ce qui ne vient que de tes comptes (le serveur le dit), après confirmation. */
  private async forget(): Promise<void> {
    const id = this.selected();
    const s = id !== null ? this.sheets.get(String(id)).value : null;
    if (!s) return;
    if (!s.forget.allowed) {
      toast(s.forget.reason, { ico: "lock", duration: 6000 });
      return;
    }
    const sure = await confirmModal({ title: "Oublier ce contact ?", text: forgetQuestion(s), ok: "Oublier", danger: true });
    if (!sure) return;
    try {
      const done = await forgetContact(s.id);
      toast(done.message, { ico: "trash" });
    } catch (err) {
      toast(failureText(err), { ico: "alert", duration: 6000 });
      if (!(err instanceof ApiError && err.status === 404)) return;
    }
    this.sheets.invalidate(String(s.id));
    this.items = this.items.filter((c) => c.id !== s.id);
    this.shell.go(`#${ID}`);
    void this.load(true);
  }

  /** La croix d'un fait : qu'elle l'oublie (un fait d'un de tes comptes), après confirmation ; la fiche se relit. */
  private async forgetFact(factId: number): Promise<void> {
    const id = this.selected();
    const s = id !== null ? this.sheets.get(String(id)).value : null;
    const fact = s?.facts.find((f) => f.kind === "note" && f.id === factId);
    if (!s || !fact) return;
    const sure = await confirmModal({ title: "Oublier ce fait ?", text: forgetFactQuestion(fact), ok: "Oublier", danger: true });
    if (!sure) return;
    try {
      const done = await forgetContactFact(factId);
      toast(done.message, { ico: "x" });
    } catch (err) {
      toast(failureText(err), { ico: "alert", duration: 6000 });
      if (!(err instanceof ApiError && err.status === 404)) return;
    }
    void this.loadSheet(s.id, true);
  }

  private searchEntries(): PaletteEntry[] {
    return this.items.slice(0, 60).map((c) => ({
      group: "Contacts",
      title: c.name,
      sub: paletteSub(c),
      icon: c.kind === "org" ? "users" : "user",
      route: contactHash(c.id),
    }));
  }
}

export function contactsScreen(shell: Shell, hooks: ContactsHooks): ScreenDef {
  return new ContactsScreen(shell, hooks).def();
}
