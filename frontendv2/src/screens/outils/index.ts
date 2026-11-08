/**
 * L'écran « Outils » (ADR 0187) : ce que Mika peut faire pour toi. « Tes droits » est la matrice même du moteur
 * (`GET /api/moi/rights`), ressource par ressource — son chapeau dit où se décident tes accords (le chat) et où se
 * relisent ses brouillons (Teams, Mail) ; « Services », ceux dont elle se sert pour toi, ceux que tu as branchés et
 * ceux qu'on te partage. La forme : `maquette/ecrans/outils.js` ; l'onglet « Accords » attend une route qui rende les
 * cartes et les décisions (ADR 0209).
 */
import { apiUrl } from "../../api/moi";
import type { Rights } from "../../api/rights";
import { $, h, on } from "../../shell/dom";
import { closeModal, openMenu, openModal } from "../../shell/float";
import { ico } from "../../shell/icons";
import type { PaletteEntry } from "../../shell/palette";
import type { ScreenContext, ScreenDef, ScreenTab, Shell } from "../../shell/shell";
import { askMika } from "../parametres/account";
import { errorBlock, loadingBlock } from "../parametres/kit";
import * as store from "../parametres/store";
import { shareWords } from "../parametres/words";
import {
  askFor,
  canalPickMarkup,
  columns,
  FIRST_CANAL,
  labelOf,
  legendMarkup,
  navMarkup,
  receivedWords,
  resourcesOf,
  selectMarkup,
  serviceRows,
  servicesMarkup,
  tableMarkup,
  toolDetailMarkup,
  whyMarkup,
  type MatrixResource,
  type Ownership,
  type ServiceRow,
} from "./matrix";

const ID = "outils";
/** Une page de la console, telle que le moteur la donne à une opératrice : rien d'autre ne s'ouvre d'ici. */
const CONSOLE_PAGE = /^\/inspecteur\/[\w\-/]*(\?[\w=%.\-&]*)?$/;

class OutilsScreen {
  private readonly tabs: ScreenTab[] = [
    { id: "droits", title: "Tes droits" },
    { id: "services", title: "Services" },
  ];
  private body: HTMLElement | null = null;
  private ctx: ScreenContext | null = null;
  private query = "";
  /** Sur un téléphone, le canal dont la colonne se lit (ADR 0209). */
  private canal = FIRST_CANAL;
  private painted = "";

  constructor(private readonly shell: Shell) {
    // la palette (Ctrl K) cherche aussi ses outils : une lecture, un peu après le démarrage
    window.setTimeout(() => void this.loadAll(), 3500);
  }

  def(): ScreenDef {
    return {
      id: ID,
      title: "Outils",
      icon: "tools",
      tabs: this.tabs,
      defaultTab: "droits",
      actions: (ctx) => this.actions(ctx),
      mount: (section) => this.mount(section),
      render: (body, ctx) => this.render(body, ctx),
      search: () => this.searchEntries(),
    };
  }

  // ── Les lectures ───────────────────────────────────────────────────

  private loadAll(force = false): Promise<unknown> {
    return Promise.all([
      store.rights.load(force),
      store.boxes.load(force),
      store.teamsAccounts.load(force),
      store.services.load(force),
    ]);
  }

  private stamp(): string {
    return [this.ctx?.tab, this.ctx?.item, store.rights.version, store.boxes.version, store.teamsAccounts.version,
      store.services.version].join("|");
  }

  private open(): boolean {
    return this.shell.ctx?.screen === ID && !!this.body?.isConnected;
  }

  private async ensure(force = false): Promise<void> {
    await this.loadAll(force);
    if (!this.open()) return;
    const n = this.serviceRows().length;
    if (this.tabs[1].count !== (n || undefined)) {
      this.tabs[1].count = n || undefined;
      this.shell.refreshHead();
    }
    if (this.stamp() !== this.painted) this.paint();
  }

  /** À qui est chaque boîte, chaque compte, chaque service : ce que les listes en disent, à côté de la matrice. */
  private ownership(): Ownership {
    const words = new Map<string, string>();
    for (const b of store.boxes.value?.boxes ?? []) {
      words.set(`mail:${b.key}`, b.level === "proprietaire" ? "à toi" : `partagée avec toi par ${b.owner_name || "quelqu'un"} (${shareWords(b.level).toLowerCase()})`);
    }
    for (const a of store.teamsAccounts.value?.accounts ?? []) {
      words.set(`teams:${a.key}`, a.level === "proprietaire" ? "à toi" : `partagé avec toi par ${a.owner_name || "quelqu'un"} (${shareWords(a.level).toLowerCase()})`);
    }
    for (const s of store.services.value?.items ?? []) words.set(`mcp:${s.name}`, "ton service");
    for (const r of store.services.value?.received ?? []) words.set(`mcp:${r.name}`, receivedWords(r));
    return { words };
  }

  private resources(): MatrixResource[] {
    const rights = store.rights.value;
    return rights ? resourcesOf(rights, this.ownership()) : [];
  }

  // ── Le rendu ───────────────────────────────────────────────────────

  private render(body: HTMLElement, ctx: ScreenContext): void {
    this.body = body;
    this.ctx = ctx;
    this.paint();
    void this.ensure();
  }

  private paint(): void {
    const body = this.body;
    const ctx = this.ctx;
    if (!body || !ctx) return;
    this.painted = this.stamp();
    const rights = store.rights.value;
    if (!rights) {
      body.innerHTML = store.rights.error ? errorBlock(store.rights.error, "Impossible de lire tes droits") : loadingBlock();
      return;
    }
    body.innerHTML = ctx.tab === "services" ? this.servicesMarkup() : this.rightsMarkup(rights, ctx.item);
    // la ressource choisie reste en vue dans le menu, même tout en bas
    body.querySelector<HTMLElement>(".mx-nav .on")?.scrollIntoView({ block: "nearest" });
  }

  private rightsMarkup(rights: Rights, selected: string | null): string {
    const all = this.resources();
    const chosen = selected && all.some((r) => r.key === selected) ? selected : null;
    const shown = chosen ? all.filter((r) => r.key === chosen) : all;
    const cols = columns(rights.canals, rights.moments);
    const tables = shown.map((r) => tableMarkup(r, cols, this.query, this.canal)).join("");
    return `<div class="split mx-split"><aside class="pane">${navMarkup(all, chosen)}</aside>
      <section class="pane"><div class="pane-scroll mx-main" data-mx-main>
        <div class="mx-picks">${selectMarkup(all, chosen)}${canalPickMarkup(rights.canals, this.canal)}</div>
        <div class="mx-top"><p class="lede">Ce que Mika peut faire pour toi, ressource par ressource : chaque case est la décision même de ses règles, pour toi, selon par où tu lui parles et quand. Clique une case pour savoir pourquoi. Tes accords se décident dans le chat ; ce qu'elle prépare se relit dans <a href="#teams/brouillons">Teams</a> et dans <a href="#mail/messages">Mail</a>.</p>
          ${legendMarkup()}</div>
        <div data-mx-tables>${tables || this.nothingFound()}</div></div></section></div>`;
  }

  private nothingFound(): string {
    return `<div class="empty">${ico("search")}<b>Aucun outil</b><p>${this.query.trim() ? `Rien ne correspond à « ${h(this.query)} ».` : "Rien ici."}</p></div>`;
  }

  /** Les lignes de « Services » : ceux dont elle se sert pour toi (la matrice), ceux que tu as branchés, et ceux
   *  qu'on te partage (`matrix.ts::serviceRows`). */
  private serviceRows(): ServiceRow[] {
    return serviceRows(this.resources(), store.services.value?.items ?? [], store.services.value?.received ?? []);
  }

  private servicesMarkup(): string {
    return servicesMarkup(this.serviceRows(), ID);
  }

  // ── La barre de titre ──────────────────────────────────────────────

  private actions(ctx: ScreenContext): string {
    if (ctx.tab === "droits") {
      return `<label class="search mx-search">${ico("search", "sm")}<input type="search" data-q placeholder="Chercher un outil…" value="${h(this.query)}" aria-label="Chercher un outil"></label>`;
    }
    if (ctx.tab === "services") {
      // la route d'action ouvre la fenêtre même, dans Paramètres (et l'adresse y redevient celle de l'onglet)
      return `<a class="btn primary" href="#parametres/mcp/+brancher">${ico("plus", "sm")}<span class="lbl">Brancher un service</span></a>`;
    }
    return "";
  }

  // ── Les gestes ─────────────────────────────────────────────────────

  private mount(section: HTMLElement): void {
    on(section, "[data-res]", "click", (_e, b) => {
      const key = b.dataset.res ?? "";
      this.shell.go(key ? `#${ID}/droits/${encodeURIComponent(key)}` : `#${ID}/droits`);
    });
    on(section, "[data-res-select]", "change", (_e, s) => {
      const key = (s as HTMLSelectElement).value;
      this.shell.go(key ? `#${ID}/droits/${encodeURIComponent(key)}` : `#${ID}/droits`);
    });
    on(section, "[data-mx-canal]", "change", (_e, s) => {
      this.canal = (s as HTMLSelectElement).value || FIRST_CANAL;
      this.repaintTables();
    });
    on(section, "[data-cell]", "click", (e, b) => {
      e.stopPropagation();
      this.why(b);
    });
    on(section, "[data-outil]", "click", (_e, b) => {
      const [res, tool] = (b.dataset.outil ?? "").split("|");
      this.detail(res, tool);
    });
    on(section, "[data-retry]", "click", () => void this.ensure(true));
    on(section, "[data-relogin]", "click", () => location.reload());
    section.addEventListener("input", (e) => {
      const target = e.target as HTMLInputElement;
      if (!target.matches("[data-q]")) return;
      this.query = target.value;
      this.repaintTables();
    });
  }

  /** La recherche filtre les tableaux sans toucher à la barre de titre (la saisie garde son curseur). */
  private repaintTables(): void {
    const rights = store.rights.value;
    const box = this.body ? $<HTMLElement>("[data-mx-tables]", this.body) : null;
    if (!rights || !box) return;
    const all = this.resources();
    const selected = this.ctx?.item ?? null;
    const shown = selected && all.some((r) => r.key === selected) ? all.filter((r) => r.key === selected) : all;
    const cols = columns(rights.canals, rights.moments);
    box.innerHTML = shown.map((r) => tableMarkup(r, cols, this.query, this.canal)).join("") || this.nothingFound();
  }

  private find(resKey: string, toolName: string) {
    const res = this.resources().find((r) => r.key === resKey);
    const tool = res?.tools.find((t) => t.name === toolName);
    return res && tool ? { res, tool } : null;
  }

  private why(button: HTMLElement): void {
    const rights = store.rights.value;
    const row = button.closest<HTMLElement>("tr[data-tool]");
    const section = button.closest<HTMLElement>("[data-res-key]");
    if (!rights || !row || !section) return;
    const found = this.find(section.dataset.resKey ?? "", row.dataset.tool ?? "");
    const key = button.dataset.cell ?? "";
    const cell = found?.tool.cells[key];
    if (!found || !cell) return;
    const [canal, moment] = key.split("/");
    const canalLabel = rights.canals.find((c) => c.key === canal)?.label ?? canal;
    const momentLabel = rights.moments.find((m) => m.key === moment)?.label ?? moment;
    // la ligne même et sa page dans la console : le moteur ne les donne qu'à une opératrice
    const href = found.res.href && CONSOLE_PAGE.test(found.res.href) ? apiUrl(found.res.href) : "";
    openMenu(button, [{ html: whyMarkup(found.tool, cell, canalLabel, momentLabel, href) }], { align: "left" });
  }

  private detail(resKey: string, toolName: string): void {
    const rights = store.rights.value;
    const found = this.find(resKey, toolName);
    if (!rights || !found) return;
    const el = openModal({
      title: labelOf(found.tool),
      size: "narrow",
      body: toolDetailMarkup(found.res, found.tool, rights),
      foot: `<span class="grow"></span><button class="btn" type="button" data-close>Fermer</button>
        <button class="btn mika" type="button" data-demander>${ico("sparkle", "sm")}Lui demander</button>`,
    });
    el.querySelector("[data-demander]")?.addEventListener("click", () => {
      closeModal();
      // la demande posée dans le champ du chat, à relire avant d'envoyer (la même aide que Paramètres › Compte)
      askMika(this.shell, askFor(found.tool));
    });
  }

  /** La palette (Ctrl K) : les outils des familles, des services et des apps, chacun une fois — un compte n'en
   *  recopie aucun. */
  private searchEntries(): PaletteEntry[] {
    const out: PaletteEntry[] = [];
    for (const r of this.resources()) {
      for (const t of r.tools) {
        out.push({
          group: "Outils",
          title: labelOf(t),
          sub: r.title,
          icon: "tools",
          route: `#${ID}/droits/${encodeURIComponent(r.key)}`,
        });
      }
    }
    return out;
  }
}

export function outilsScreen(shell: Shell): ScreenDef {
  return new OutilsScreen(shell).def();
}
