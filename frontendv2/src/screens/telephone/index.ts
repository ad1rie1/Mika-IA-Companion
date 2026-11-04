/**
 * L'écran « Téléphone » (ADR 0120, 0190) : ce que l'application de ton téléphone montre à Mika — tes conversations
 * WhatsApp et Messages, et les réponses qu'elle y a proposées —, tes messageries rangées par appli, ta dernière
 * position. Les données : `protocole-moi.md` § 5 ; la forme : la maquette (`maquette/ecrans/telephone.js`).
 *
 * Ce que l'API ne sait pas encore, l'écran le dit au lieu de le feindre : répondre d'ici et « Préremplir avec Mika »
 * (ADR 0189, 0191), quel téléphone a reçu quel message, les apps autres que les messageries.
 */
import { fetchConversations, fetchMap, fetchPosition, fetchThread, type MapInfo, type Phone, type PhoneThread } from "../../api/phone";
import { isDark, onTheme } from "../../shell/theme";
import type { At, LiveMap } from "./livemap";
import { covers } from "./mapgeo";
import { countOf } from "../../shell/counts";
import { $, h, isMobile, on } from "../../shell/dom";
import { openMenu, type MenuItem } from "../../shell/float";
import { ico } from "../../shell/icons";
import type { PaletteEntry } from "../../shell/palette";
import type { ScreenContext, ScreenDef, ScreenTab, Shell } from "../../shell/shell";
import { Cached, CachedMap, ago, errorBlock, loadingBlock } from "../parametres/kit";
import * as store from "../parametres/store";
import {
  activePhones,
  composerMarkup,
  conversationItem,
  conversationTitle,
  matches,
  notificationsMarkup,
  onlyPhone,
  phoneSwitch,
  mapMarkup,
  positionMarkup,
  shortPhone,
  SWITCH_NOTE,
  threadHead,
  threadMarkup,
} from "./view";

const ID = "telephone";
/** Relire ce qui arrive tant que l'écran est ouvert. */
const EVERY_MS = 30_000;

class TelephoneScreen {
  private readonly conversations = new Cached(() => fetchConversations(), 10_000);
  private readonly phones = store.phones;
  private readonly position = new Cached(() => fetchPosition(), 15_000);
  /** La carte réglée sur le serveur (ADR 0193) : relue toutes les cinq minutes. */
  private readonly mapInfo = new Cached(() => fetchMap(), 5 * 60_000);
  /** La vraie carte, dessinée : elle survit aux redessins de l'onglet, retirée quand on le quitte. */
  private live: LiveMap | null = null;
  private liveAt: At | null = null;
  /** Le dernier montage demandé (MapLibre se charge à part : seul le plus récent se pose). */
  private mapToken = 0;
  private readonly threads = new CachedMap<PhoneThread>((key) => fetchThread(key), 10_000);
  private readonly tabs: ScreenTab[] = [
    { id: "messages", title: "Messages" },
    { id: "notifications", title: "Notifications" },
    { id: "position", title: "Position" },
  ];
  private body: HTMLElement | null = null;
  private ctx: ScreenContext | null = null;
  private query = "";
  /** Le téléphone choisi dans la barre de titre (`null` : tous). */
  private chosen: number | null = null;
  /** Ce qui a été dessiné : on ne redessine que si une lecture a changé. */
  private painted = "";
  private timer = 0;

  constructor(private readonly shell: Shell) {
    // la palette (Ctrl K) cherche aussi ses conversations : une lecture, un peu après le démarrage
    window.setTimeout(() => void this.conversations.load(), 2500);
    onTheme((dark) => {
      if (this.live && this.liveAt) this.live.show(this.liveAt, dark);
    });
  }

  def(): ScreenDef {
    return {
      id: ID,
      title: "Téléphone",
      short: "Tél.",
      icon: "phone",
      tabs: this.tabs,
      defaultTab: "messages",
      count: () => countOf("phone"),
      actions: () => this.actions(),
      mount: (section) => this.mount(section),
      render: (body, ctx) => this.render(body, ctx),
      search: () => this.searchEntries(),
    };
  }

  // ── Les lectures ───────────────────────────────────────────────────

  private open(): boolean {
    return this.shell.ctx?.screen === ID && !!this.body?.isConnected;
  }

  private stamp(): string {
    const key = this.selectedKey();
    const thread = key ? this.threads.get(key).version : 0;
    return [this.ctx?.tab, key, this.conversations.version, this.phones.version, this.position.version,
      this.mapInfo.version, thread].join("|");
  }

  /** Lire ce que l'onglet montre ; redessiner si ça a changé et qu'on y est encore. */
  private async ensure(force = false): Promise<void> {
    const tab = this.ctx?.tab;
    const reads: Promise<unknown>[] = [this.conversations.load(force), this.phones.load(force)];
    if (tab === "position") reads.push(this.position.load(force), this.mapInfo.load());
    await Promise.all(reads);
    if (tab === "messages") {
      const key = this.selectedKey();
      if (key) await this.threads.get(key).load(force);
    }
    if (!this.open()) return;
    const count = this.conversations.value?.items.length;
    const before = this.tabs[0].count;
    this.tabs[0].count = count ? count : undefined;
    if (before !== this.tabs[0].count) this.shell.refreshHead();
    else this.paintHead();
    if (this.stamp() !== this.painted) this.paint();
  }

  private schedule(): void {
    window.clearInterval(this.timer);
    this.timer = window.setInterval(() => {
      if (!this.open()) {
        window.clearInterval(this.timer);
        this.dropMap();
        return;
      }
      if (document.visibilityState === "visible") void this.ensure(true);
    }, EVERY_MS);
  }

  // ── Le rendu ───────────────────────────────────────────────────────

  private render(body: HTMLElement, ctx: ScreenContext): void {
    this.body = body;
    this.ctx = ctx;
    this.paint();
    void this.ensure();
    this.schedule();
  }

  /** La conversation ouverte : celle de la route, sinon (sur un écran large) la plus récente. */
  private selectedKey(): string | null {
    const item = this.ctx?.item;
    if (item) return item;
    if (isMobile()) return null;
    return this.conversations.value?.items[0]?.key ?? null;
  }

  private paint(): void {
    const body = this.body;
    const ctx = this.ctx;
    if (!body || !ctx) return;
    this.painted = this.stamp();
    const now = Date.now();
    if (ctx.tab === "position") {
      this.paintPosition(body, now);
      return;
    }
    this.dropMap();
    const convs = this.conversations;
    if (!convs.value) {
      body.innerHTML = convs.error ? errorBlock(convs.error, "Impossible de lire ton téléphone") : loadingBlock();
      return;
    }
    if (ctx.tab === "notifications") {
      body.innerHTML = notificationsMarkup(convs.value.items, now, this.switchNote());
      return;
    }
    this.paintMessages(body, now);
  }

  /** La position : la vraie carte si le serveur en sert une qui la couvre (gardée d'un redessin à l'autre). */
  private paintPosition(body: HTMLElement, now: number): void {
    const p = this.position.value;
    if (!p) {
      this.dropMap();
      body.innerHTML = this.position.error ? errorBlock(this.position.error, "Impossible de lire ta position") : loadingBlock();
      return;
    }
    const info = this.mapInfo.value;
    const at: At | null = p.known && p.coords ? { lat: p.coords.lat, lon: p.coords.lon, accuracy: p.accuracy_m } : null;
    const live = !!at && covers(info, at.lat, at.lon);
    body.innerHTML = positionMarkup(p, this.phoneOfAll(), now, live);
    if (!live || !at || !info) {
      this.dropMap();
      return;
    }
    this.liveAt = at;
    const slot = $<HTMLElement>("[data-map]", body);
    if (!slot) return;
    if (this.live) {
      slot.replaceWith(this.live.host);
      this.live.resize();
      this.live.show(at, isDark());
      return;
    }
    void this.startMap(info);
  }

  private async startMap(info: MapInfo): Promise<void> {
    const token = ++this.mapToken;
    let mod: typeof import("./livemap");
    try {
      mod = await import("./livemap");
    } catch {
      this.drawnInstead();
      return;
    }
    if (token !== this.mapToken || this.live || !this.open() || this.ctx?.tab !== "position") return;
    const slot = this.body ? $<HTMLElement>("[data-map]", this.body) : null;
    if (!slot || !this.liveAt) return;
    try {
      this.live = mod.mountMap(slot, info, this.liveAt, isDark());
    } catch {
      this.drawnInstead(); // pas de WebGL : le plan dessiné
    }
  }

  /** La carte ne se dessine pas ici : le plan dessiné reprend sa place. */
  private drawnInstead(): void {
    const p = this.position.value;
    const slot = this.body ? $<HTMLElement>("[data-map]", this.body) : null;
    if (slot && p?.known) slot.outerHTML = mapMarkup(p.accuracy_m, p.label.trim());
  }

  private dropMap(): void {
    this.mapToken += 1;
    this.live?.remove();
    this.live = null;
  }

  private paintMessages(body: HTMLElement, now: number): void {
    const items = this.conversations.value?.items ?? [];
    if (!items.length) {
      const phones = this.phones.value?.items ?? [];
      body.innerHTML = `<div class="fill-scroll"><div class="empty">${ico("phone")}<b>Aucun message de ton téléphone</b>
        <p>${phones.length
          ? "Sur ton téléphone, allume « Lui montrer mes messages » : Mika lira tes conversations WhatsApp et Messages."
          : "Installe Mika sur ton téléphone et connecte-toi : elle lira tes conversations WhatsApp et Messages, si tu le lui permets."}</p>
        <a class="btn sm" href="#parametres/telephones">${ico("settings", "sm")}Tes téléphones</a></div></div>`;
      return;
    }
    const key = this.selectedKey();
    const reading = !!this.ctx?.item;
    const list = this.listMarkup(key, now);
    // ce que le dessin d'avant tenait : où en était la liste, le fil, la recherche
    const scroll = $<HTMLElement>("[data-scroll]", body);
    const keepScroll = scroll && body.dataset.thread === key ? scroll.scrollTop : null;
    const atBottom = scroll ? scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 40 : true;
    const listTop = $<HTMLElement>("[data-convs]", body)?.scrollTop ?? 0;
    const search = $<HTMLInputElement>("[data-cq]", body);
    const typing = search !== null && document.activeElement === search ? search.selectionStart : null;
    body.innerHTML = `<div class="split tel-split${reading ? " lire" : ""}">
      <aside class="pane"><div class="pane-head"><label class="search grow">${ico("search", "sm")}<input type="search" data-cq placeholder="Chercher une conversation" value="${h(this.query)}" aria-label="Chercher une conversation"></label></div>
        ${this.switchNote()}<div class="pane-scroll" data-convs>${list}</div></aside>
      <section class="pane tel-thread">${this.threadPane(key, now)}</section></div>`;
    body.dataset.thread = key ?? "";
    const fresh = $<HTMLElement>("[data-scroll]", body);
    if (fresh) fresh.scrollTop = keepScroll !== null && !atBottom ? keepScroll : fresh.scrollHeight;
    const freshList = $<HTMLElement>("[data-convs]", body);
    if (freshList) freshList.scrollTop = listTop;
    if (typing !== null) {
      const input = $<HTMLInputElement>("[data-cq]", body);
      input?.focus();
      input?.setSelectionRange(typing, typing);
    }
  }

  private listMarkup(key: string | null, now: number): string {
    const items = (this.conversations.value?.items ?? []).filter((c) => matches(c, this.query));
    if (!items.length) {
      return `<div class="empty">${ico("search")}<p>Aucune conversation ne correspond à « ${h(this.query)} ».</p></div>`;
    }
    return items.map((c) => conversationItem(c, c.key === key, now)).join("");
  }

  private threadPane(key: string | null, now: number): string {
    const conv = key ? this.conversations.value?.items.find((c) => c.key === key) : null;
    if (!key || !conv) {
      return `<div class="empty">${ico("chat")}<b>${key ? "Conversation introuvable" : "Choisis une conversation"}</b>
        <p>${key ? "Elle n'est plus parmi celles de ton téléphone." : "Ses messages et les réponses que Mika y a proposées s'affichent ici."}</p></div>`;
    }
    const cached = this.threads.get(key);
    const title = conversationTitle(conv);
    const thread = cached.value
      ? `<div class="tel-msgs">${threadMarkup(cached.value, title, now)}</div>`
      : cached.error ? errorBlock(cached.error, "Impossible de lire cette conversation") : loadingBlock();
    return `${threadHead(conv, this.phoneOfAll())}
      <div class="chat-scroll" data-scroll>${thread}</div>
      ${composerMarkup(title)}`;
  }

  /** Le téléphone d'où vient tout, quand un seul a jamais servi ; sinon on ne sait pas. */
  private phoneOfAll(): Phone | null {
    return onlyPhone(this.phones.value?.items ?? []);
  }

  /** Un téléphone choisi parmi plusieurs : le dire, plutôt que feindre un tri. */
  private switchNote(): string {
    const active = activePhones(this.phones.value?.items ?? []);
    if (this.chosen === null || (this.phones.value?.items.length ?? 0) < 2 || !active.length) return "";
    return `<p class="tel-switch-note small muted">${ico("info", "xs")}${h(SWITCH_NOTE)}</p>`;
  }

  // ── La barre de titre ──────────────────────────────────────────────

  private actions(): string {
    return `${phoneSwitch(this.phones.value?.items ?? [], this.chosen, Date.now())}
      <a class="btn icon ghost" href="#parametres/telephones" title="Régler tes téléphones">${ico("settings")}</a>`;
  }

  /** Le sélecteur suit la liste des téléphones sans redessiner tout l'en-tête (ni perdre une saisie). */
  private paintHead(): void {
    const btn = this.ctx?.el.querySelector<HTMLElement>("[data-tel-switch]");
    if (!btn) return;
    btn.outerHTML = phoneSwitch(this.phones.value?.items ?? [], this.chosen, Date.now());
  }

  private switchMenu(anchor: HTMLElement): void {
    const now = Date.now();
    const active = activePhones(this.phones.value?.items ?? []);
    const pick = (id: number | null) => () => {
      this.chosen = id;
      this.paintHead();
      this.paint();
    };
    const items: MenuItem[] = [
      { header: "Tes téléphones" },
      { label: "Tous tes téléphones", icon: "phone", checked: this.chosen === null, action: pick(null) },
      ...active.map((p): MenuItem => ({
        label: `${shortPhone(p.label)}${p.last_used ? ` — vu ${ago(p.last_used, now)}` : ""}`,
        icon: "phone",
        checked: this.chosen === p.id,
        action: pick(p.id),
      })),
      "sep",
      { label: "Gérer tes téléphones", icon: "settings", action: () => this.shell.go("#parametres/telephones") },
    ];
    openMenu(anchor, items);
  }

  // ── Les gestes ─────────────────────────────────────────────────────

  private mount(section: HTMLElement): void {
    on(section, "[data-conv]", "click", (_e, b) => {
      this.shell.go(`#${ID}/messages/${encodeURIComponent(b.dataset.conv ?? "")}`);
    });
    on(section, "[data-retour]", "click", () => this.shell.go(`#${ID}/messages`));
    on(section, "[data-tel-switch]", "click", (e, b) => {
      e.stopPropagation();
      this.switchMenu(b);
    });
    on(section, "[data-more]", "click", (e, b) => {
      e.stopPropagation();
      openMenu(b, [
        { label: "Voir dans Notifications", icon: "bell", action: () => this.shell.go(`#${ID}/notifications`) },
        { label: "Lui en parler dans le chat", icon: "sparkle", action: () => this.shell.go("#chat") },
      ]);
    });
    on(section, "[data-retry]", "click", () => void this.ensure(true));
    on(section, "[data-relogin]", "click", () => location.reload());
    section.addEventListener("input", (e) => {
      const target = e.target as HTMLInputElement;
      if (!target.matches("[data-cq]")) return;
      this.query = target.value;
      const list = $<HTMLElement>("[data-convs]", section);
      if (list) list.innerHTML = this.listMarkup(this.selectedKey(), Date.now());
    });
  }

  private searchEntries(): PaletteEntry[] {
    return (this.conversations.value?.items ?? []).map((c) => ({
      group: "Téléphone",
      title: conversationTitle(c),
      sub: `${c.app_name} · ${c.last.text}`,
      icon: "phone",
      route: `#${ID}/messages/${encodeURIComponent(c.key)}`,
    }));
  }
}

export function telephoneScreen(shell: Shell): ScreenDef {
  return new TelephoneScreen(shell).def();
}
