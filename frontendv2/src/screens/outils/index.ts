/**
 * L'écran « Outils » (ADR 0187) : ce que Mika peut faire pour toi. « Tes droits » est la matrice même du moteur
 * (`GET /api/moi/rights`), ressource par ressource ; « Services », ceux dont elle se sert pour toi et ceux que tu as
 * branchés ; « Accords » dit où se décident ses cartes d'accord (le chat). La forme : `maquette/ecrans/outils.js`.
 */
import type { Service } from "../../api/mcp";
import type { Rights } from "../../api/rights";
import { $, h, on } from "../../shell/dom";
import { closeModal, openMenu, openModal } from "../../shell/float";
import { ico } from "../../shell/icons";
import type { PaletteEntry } from "../../shell/palette";
import type { ScreenContext, ScreenDef, ScreenTab, Shell } from "../../shell/shell";
import { errorBlock, loadingBlock } from "../parametres/kit";
import * as store from "../parametres/store";
import { stateWords, servedOf, shareWords } from "../parametres/words";
import {
  columns,
  KEEP_WORDS,
  legendMarkup,
  navMarkup,
  resourcesOf,
  selectMarkup,
  tableMarkup,
  toolDetailMarkup,
  toolLabel,
  whyMarkup,
  type MatrixResource,
  type Ownership,
} from "./matrix";

const ID = "outils";

class OutilsScreen {
  private readonly tabs: ScreenTab[] = [
    { id: "droits", title: "Tes droits" },
    { id: "services", title: "Services" },
    { id: "accords", title: "Accords" },
  ];
  private body: HTMLElement | null = null;
  private ctx: ScreenContext | null = null;
  private query = "";
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
      store.shares.load(force),
      store.me.load(),
    ]);
  }

  private stamp(): string {
    return [this.ctx?.tab, this.ctx?.item, store.rights.version, store.boxes.version, store.teamsAccounts.version,
      store.services.version, store.shares.version, store.me.version].join("|");
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
    for (const r of store.shares.value?.received ?? []) {
      if (r.kind === "mcp") words.set(`mcp:${r.key}`, `partagé avec toi par ${r.owner_name} (${shareWords(r.level).toLowerCase()})`);
    }
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
    if (ctx.tab === "accords") {
      body.innerHTML = this.accordsMarkup();
      return;
    }
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
    const tables = shown.map((r) => tableMarkup(r, cols, this.query)).join("");
    return `<div class="split mx-split"><aside class="pane">${navMarkup(all, chosen)}</aside>
      <section class="pane"><div class="pane-scroll mx-main" data-mx-main>
        ${selectMarkup(all, chosen)}
        <div class="mx-top"><p class="lede">Ce que Mika peut faire pour toi, ressource par ressource : chaque case est la décision même de ses règles, pour toi, selon par où tu lui parles et quand. Clique une case pour savoir pourquoi.</p>
          ${legendMarkup()}</div>
        <div data-mx-tables>${tables || this.nothingFound()}</div></div></section></div>`;
  }

  private nothingFound(): string {
    return `<div class="empty">${ico("search")}<b>Aucun outil</b><p>${this.query.trim() ? `Rien ne correspond à « ${h(this.query)} ».` : "Rien ici."}</p></div>`;
  }

  /** Les lignes de « Services » : ceux dont elle se sert pour toi (la matrice), et ceux que tu as branchés. */
  private serviceRows(): { key: string; name: string; resource?: MatrixResource; own?: Service }[] {
    const outside = this.resources().filter((r) => r.group === "services" || r.group === "apps");
    const own = store.services.value?.items ?? [];
    const rows: { key: string; name: string; resource?: MatrixResource; own?: Service }[] = outside.map((r) => {
      const name = r.key.replace(/^[a-z]+:/, "");
      return { key: r.key, name, resource: r, own: r.group === "services" ? own.find((s) => s.name === name) : undefined };
    });
    for (const s of own) if (!rows.some((r) => r.own === s)) rows.push({ key: `mcp:${s.name}`, name: s.name, own: s });
    return rows;
  }

  private servicesMarkup(): string {
    const rows = this.serviceRows();
    const meName = store.me.value?.name ?? "";
    const body = rows
      .map(({ key, name, resource, own }) => {
        const open = resource ? resource.tools.filter((t) => Object.values(t.cells).some((c) => c && c.level !== "non")).length : 0;
        const keeps = new Set<string>();
        for (const t of resource?.tools ?? []) for (const c of Object.values(t.cells)) if (c && c.level !== "non") keeps.add(KEEP_WORDS[c.keep] ?? c.keep);
        const app = resource?.group === "apps";
        const where = own ? `<span class="mono">${h(own.url)}</span>` : h(app ? "app de la Forge" : resource?.sub || "un service de Mika");
        const [stateCls, stateText] = own ? stateWords(own.state) : ["", ""];
        const state = own
          ? `<span class="tag ${stateCls}">${h(stateText)}</span>${own.detail ? `<div class="tiny muted">${h(own.detail)}</div>` : ""}`
          : `<span class="muted">—</span>`;
        const served = own ? servedOf(own.tools) : null;
        const tools = resource
          ? `${open} / ${resource.tools.length}`
          : served ? `${served.served} / ${served.total}` : "—";
        const review = served && served.review ? ` <span class="tag warn">${served.review} à regarder</span>` : "";
        const who = own
          ? own.access.map((a) => (a.who === meName ? "toi" : a.who)).filter(Boolean).join(", ") || "—"
          : "—";
        const keep = own
          ? [...new Set(own.access.map((a) => a.keep_words).filter(Boolean))].join(", ") || "—"
          : [...keeps].filter((k) => k !== "rien").join(", ") || "rien";
        const title = resource?.title ?? `Service « ${name} »`;
        return `<tr><td><div class="row nowrap">${ico(app ? "code" : name === "web" ? "globe" : "server", "sm")}<b>${h(title)}</b>${own ? '<span class="tag accent">à toi</span>' : ""}</div></td>
          <td class="small">${where}</td><td class="small text-2">${h(own?.purpose || "—")}</td><td>${state}</td>
          <td class="num nowrap">${h(tools)}${review}</td><td class="small">${h(who)}</td><td class="small">${h(keep)}</td>
          <td class="actions nowrap">${resource ? `<a class="btn xs ghost" href="#${ID}/droits/${encodeURIComponent(key)}">Ses droits</a>` : ""}${own ? ` <a class="btn xs" href="#parametres/mcp/${encodeURIComponent(name)}">Régler</a>` : ""}</td></tr>`;
      })
      .join("");
    const table = rows.length
      ? `<div class="mx-scroll"><table class="tbl svc-tbl"><thead><tr><th>Service</th><th>Où</th><th>À quoi il lui sert</th><th>État</th><th>Outils pour toi</th><th>Avec qui</th><th>Ce qu'elle en garde</th><th></th></tr></thead><tbody>${body}</tbody></table></div>`
      : `<div class="empty">${ico("server")}<b>Aucun service pour toi</b><p>Tu n'as branché aucun service, et aucun de ceux de Mika ne t'est ouvert.</p></div>`;
    const plugged = store.services.value?.items.length ?? 0;
    return `<div class="fill-scroll"><div class="page-pad">
      <p class="lede">Les services d'où viennent ses outils « venus d'ailleurs » : des serveurs MCP et les apps de la Forge. Elle s'en sert pour toi selon leurs lignes d'accès. Tu branches les tiens dans <a href="#parametres/mcp">Paramètres › Services MCP</a>.</p>
      ${table}
      <p class="small muted tbl-help">« Outils pour toi » : ceux qu'au moins une case de tes droits lui ouvre${plugged ? " ; pour un service à toi pas encore servi, ceux que tu as choisis" : ""}.</p></div></div>`;
  }

  private accordsMarkup(): string {
    return `<div class="fill-scroll"><div class="page-pad accords">
      <p class="lede">Les cartes d'accord des services et des apps : seuls leurs boutons décident. Les réponses Teams et les mails qu'elle prépare se relisent dans <a href="#teams/brouillons">Teams</a> et dans <a href="#mail/messages">Mail</a>.</p>
      <div class="acc-note">${ico("shield")}<div class="grow"><b>Tes accords se décident dans le chat</b>
        <p class="small text-2">Quand Mika veut se servir d'un outil qui demande ton accord, une carte arrive au-dessus du champ du chat, avec Accepter et Refuser. Cet écran ne les relit pas encore, ni l'historique de ce que tu as décidé.</p></div>
        <a class="btn sm primary" href="#chat">${ico("chat", "sm")}Ouvrir le chat</a></div></div></div>`;
  }

  // ── La barre de titre ──────────────────────────────────────────────

  private actions(ctx: ScreenContext): string {
    if (ctx.tab === "droits") {
      return `<label class="search mx-search">${ico("search", "sm")}<input type="search" data-q placeholder="Chercher un outil…" value="${h(this.query)}" aria-label="Chercher un outil"></label>`;
    }
    if (ctx.tab === "services") {
      return `<a class="btn primary" href="#parametres/mcp">${ico("plus", "sm")}<span class="lbl">Brancher un service</span></a>`;
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
    box.innerHTML = shown.map((r) => tableMarkup(r, cols, this.query)).join("") || this.nothingFound();
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
    openMenu(button, [{ html: whyMarkup(found.tool, cell, canalLabel, momentLabel) }], { align: "left" });
  }

  private detail(resKey: string, toolName: string): void {
    const rights = store.rights.value;
    const found = this.find(resKey, toolName);
    if (!rights || !found) return;
    const label = toolLabel(found.tool.description, found.tool.name);
    const el = openModal({
      title: label,
      size: "narrow",
      body: toolDetailMarkup(found.res, found.tool, rights),
      foot: `<span class="grow"></span><button class="btn" type="button" data-close>Fermer</button>
        <button class="btn mika" type="button" data-demander>${ico("sparkle", "sm")}Lui demander</button>`,
    });
    el.querySelector("[data-demander]")?.addEventListener("click", () => {
      closeModal();
      this.shell.go("#chat");
      // le champ du chat, une fois l'écran dessiné : la demande y est posée, à relire avant d'envoyer
      window.setTimeout(() => {
        const input = document.querySelector<HTMLTextAreaElement>("[data-chat-input]");
        if (!input || input.disabled) return;
        input.value = `Tu peux te servir de « ${label} » pour moi ?`;
        input.focus();
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }, 80);
    });
  }

  private searchEntries(): PaletteEntry[] {
    const out: PaletteEntry[] = [];
    for (const r of this.resources()) {
      for (const t of r.tools) {
        out.push({
          group: "Outils",
          title: toolLabel(t.description, t.name),
          sub: `${r.title} · ${t.name}`,
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
