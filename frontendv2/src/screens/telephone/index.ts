/**
 * L'écran « Téléphone » (ADR 0120, 0190) : ce que l'application de ton téléphone montre à Mika — tes conversations
 * WhatsApp et Messages, et les réponses qu'elle y a proposées —, et ta dernière position. Les données :
 * `protocole-moi.md` § 5 ; la forme : la maquette (`maquette/ecrans/telephone.js`). Les autres apps (un colis, un
 * rendez-vous) viendront avec leur onglet, Notifications, quand l'application les lira (ADR 0190, 0233) : d'ici là, il
 * ne ferait que redire Messages.
 *
 * Ce que l'API ne sait pas encore, l'écran le dit au lieu de le feindre : répondre d'ici et « Préremplir avec Mika »
 * (ADR 0189, 0191). Il ne propose pas non plus de choisir un téléphone, tant que le serveur ne dit pas lequel a reçu
 * quel message : la barre de titre dit l'état de tes téléphones (lequel, vu quand, s'il reçoit les notifications) et
 * mène à Paramètres › Téléphones (ADR 0233). À un compte qui n'est pas propriétaire, Messages dit que Mika ne lit pas
 * ses messages (`owner` de `GET /api/moi`). « Lui en parler dans le chat » ouvre le chat avec une phrase qui nomme la
 * conversation (`TelephoneHooks.ask`).
 *
 * Rien ne se relit à intervalles : le direct (ADR 0308, `protocole-moi.md` § 2 bis) dit ce qui a changé — `phone` (la
 * liste, le fil ouvert s'il est nommé), `phone.position`, `phone.phones`, `me` —, et l'écran au second plan, ou
 * l'onglet caché, se relit à son retour.
 */
import { fetchConversations, fetchThread, type Phone, type PhoneThread } from "../../api/phone";
import { Freshness, live, names, pageShown, type Changed } from "../../live/live";
import { ages } from "../../shell/ages";
import { mapInfo } from "../../map/info";
import { LiveMap } from "../../map/live";
import { EMPTY_SCENE, type Scene } from "../../map/scene";
import { onTheme } from "../../shell/theme";
import { countOf } from "../../shell/counts";
import { $, h, isMobile, on } from "../../shell/dom";
import { openMenu } from "../../shell/float";
import { ico } from "../../shell/icons";
import type { PaletteEntry } from "../../shell/palette";
import type { ScreenContext, ScreenDef, ScreenTab, Shell } from "../../shell/shell";
import { Cached, CachedMap, errorBlock, loadingBlock } from "../../shared/kit";
import * as store from "../../shared/store";
import {
  askAboutConversation,
  composerMarkup,
  conversationItem,
  conversationTitle,
  emptyMessagesMarkup,
  matches,
  onlyPhone,
  phoneState,
  phoneStateMarkup,
  positionMarkup,
  positionScene,
  TELEPHONE_TABS,
  threadHead,
  threadMarkup,
} from "./view";

const ID = "telephone";

export interface TelephoneHooks {
  /** Ouvrir le chat avec une phrase préremplie (« Lui en parler dans le chat », depuis un fil). */
  ask: (text: string) => void;
}

class TelephoneScreen {
  private readonly conversations = new Cached(() => fetchConversations(), 10_000);
  private readonly phones = store.phones;
  /** Son compte : `owner` dit si Mika peut lire ses messages (la porte du téléphone refuse les autres). */
  private readonly me = store.me;
  /** Ta dernière position : la même lecture que la Carte. */
  private readonly position = store.position;
  /** La carte réglée sur le serveur (ADR 0193), partagée par toutes les cartes de la page : relue toutes les cinq
   *  minutes. */
  private readonly mapInfo = mapInfo;
  /** Ce que la carte de la position montre (son point et sa précision), au dernier dessin. */
  private scene: Scene = EMPTY_SCENE;
  /**
   * La vraie carte de la position (`map/live.ts`, comme la Carte) : gardée d'un dessin à l'autre, rendue quand on quitte
   * l'onglet ; une autre carte servie se repose sur elle ; une qui ne se dessine pas ici (pas de WebGL, MapLibre absent,
   * ses tuiles en échec de suite) laisse le plan dessiné et sa note, sans réessayer — jusqu'à une autre carte servie.
   */
  private readonly map = new LiveMap({
    slot: () => (this.body ? $<HTMLElement>("[data-map]", this.body) : null),
    showing: () => this.open() && this.ctx?.tab === "position",
    repaint: () => this.paint(),
    scene: () => this.scene,
    options: { interactive: true },
    needsHere: true,
  });
  private readonly threads = new CachedMap<PhoneThread>((key) => fetchThread(key), 10_000);
  /** Ses onglets (une copie : Messages y porte son nombre). */
  private readonly tabs: ScreenTab[] = TELEPHONE_TABS.map((t) => ({ ...t }));
  private body: HTMLElement | null = null;
  private ctx: ScreenContext | null = null;
  private query = "";
  /** Ce qui a été dessiné : on ne redessine que si une lecture a changé. */
  private painted = "";
  /** Le direct (ADR 0308) : montré, l'écran relit ce qu'un changement touche ; sinon il se relit à son retour. */
  private readonly fresh = new Freshness(() => this.open() && pageShown(), () => void this.ensure(true));

  constructor(
    private readonly shell: Shell,
    private readonly hooks: TelephoneHooks,
  ) {
    // la palette (Ctrl K) cherche aussi ses conversations : une lecture, un peu après le démarrage
    window.setTimeout(() => void this.conversations.load(), 2500);
    onTheme((dark) => this.map.view?.theme(dark));
    // la carte de la position se rend dès qu'on quitte l'écran (comme celle de la Carte)
    addEventListener("hashchange", () => {
      if (!new RegExp(`^#${ID}(/|$)`).test(location.hash)) this.map.drop();
    });
    live.onChange("phone", (convs) => this.fresh.touch(() => void this.phoneChanged(convs)));
    // ses âges (« vu il y a » de tes téléphones, une proposition décidée « il y a ») avancent d'eux-mêmes
    ages.onTick(() => this.agesTick());
    // la position relue, la carte servie aussi si elle a vieilli (au plus toutes les cinq minutes : aucun sujet ne la dit)
    live.onChange("phone.position", () => this.fresh.touch(() => void this.reread(this.ctx?.tab === "position" ? [this.position] : [], [this.mapInfo])));
    live.onChange("phone.phones", () => this.fresh.touch(() => void this.reread([this.phones])));
    live.onChange("me", () => this.fresh.touch(() => void this.reread([this.me])));
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
    return [this.ctx?.tab, key, this.conversations.version, this.phones.version, this.me.version, this.position.version,
      this.mapInfo.version, thread].join("|");
  }

  /** Lire ce que l'onglet montre ; redessiner si ça a changé et qu'on y est encore. */
  private async ensure(force = false): Promise<void> {
    const tab = this.ctx?.tab;
    const reads: Promise<unknown>[] = [this.conversations.load(force), this.phones.load(force), this.me.load(force)];
    if (tab === "position") reads.push(this.position.load(force), this.mapInfo.load());
    await Promise.all(reads);
    if (tab === "messages") {
      const key = this.selectedKey();
      if (key) await this.threads.get(key).load(force);
    }
    this.settle();
  }

  /** Ce qui a été lu, à l'écran : le nombre de l'onglet, l'état des téléphones, le corps s'il a changé. */
  private settle(): void {
    if (!this.open()) return;
    const count = this.conversations.value?.items.length;
    const before = this.tabs[0].count;
    this.tabs[0].count = count ? count : undefined;
    if (before !== this.tabs[0].count) this.shell.refreshHead();
    else this.paintHead();
    if (this.stamp() !== this.painted) this.paint();
  }

  /** Le direct : relire ces lectures-là (une lecture en vol suffit : la suivante se refait une fois après, `Cached`) ;
   *  `aged` : celles-ci aussi, si elles ont vieilli. */
  private async reread(caches: Cached<unknown>[], aged: Cached<unknown>[] = []): Promise<void> {
    if (!caches.length) return;
    await Promise.all([...caches.map((c) => c.load(true)), ...aged.map((c) => c.load())]);
    this.settle();
  }

  /** `phone` (des conversations) : la liste, et le fil ouvert s'il est nommé (ses réponses offertes avec). */
  private async phoneChanged(convs: Changed): Promise<void> {
    const key = this.ctx?.tab === "messages" ? this.selectedKey() : null;
    const reads: Promise<unknown>[] = [this.conversations.load(true)];
    if (key && names(convs, key)) reads.push(this.threads.get(key).load(true));
    await Promise.all(reads);
    // la conversation ouverte d'office (la plus récente) a pu changer : la sienne se lit
    const now = this.ctx?.tab === "messages" ? this.selectedKey() : null;
    if (now && now !== key) await this.threads.get(now).load();
    this.settle();
  }

  // ── Le rendu ───────────────────────────────────────────────────────

  private render(body: HTMLElement, ctx: ScreenContext): void {
    this.body = body;
    this.ctx = ctx;
    this.paint();
    if (!this.fresh.back()) void this.ensure();
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
    this.map.drop();
    const convs = this.conversations;
    if (!convs.value) {
      body.innerHTML = convs.error ? errorBlock(convs.error, "Impossible de lire ton téléphone") : loadingBlock();
      return;
    }
    this.paintMessages(body, now);
  }

  /** La position : la vraie carte si le serveur en sert une qui la couvre (gardée d'un redessin à l'autre). */
  private paintPosition(body: HTMLElement, now: number): void {
    const p = this.position.value;
    if (!p) {
      this.map.drop();
      body.innerHTML = this.position.error ? errorBlock(this.position.error, "Impossible de lire ta position") : loadingBlock();
      return;
    }
    const info = this.mapInfo.value;
    const scene = p.known ? positionScene(p.coords, p.accuracy_m) : EMPTY_SCENE;
    const before = this.scene.here;
    const here = scene.here;
    this.scene = scene;
    body.innerHTML = positionMarkup(p, this.phoneOfAll(), now, this.map.wanted(info, scene));
    // la carte ouverte suit la position ; elle ne se recentre que si tu as bougé (son zoom reste le tien)
    const moved = !!before && !!here && (before.lat !== here.lat || before.lon !== here.lon);
    this.map.lodge(info)?.show(scene, moved);
  }

  private paintMessages(body: HTMLElement, now: number): void {
    const items = this.conversations.value?.items ?? [];
    if (!items.length) {
      body.innerHTML = emptyMessagesMarkup(this.owner(), this.phones.value?.items.length ?? 0);
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
        <div class="pane-scroll" data-convs>${list}</div></aside>
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
    return `${threadHead(conv)}
      <div class="chat-scroll" data-scroll>${thread}</div>
      ${composerMarkup(title)}`;
  }

  /** Une de ses propriétaires ? `undefined` tant que son compte n'est pas lu. */
  private owner(): boolean | undefined {
    return this.me.value?.owner;
  }

  /** Le téléphone d'où vient tout, quand un seul a jamais servi ; sinon on ne sait pas. */
  private phoneOfAll(): Phone | null {
    return onlyPhone(this.phones.value?.items ?? []);
  }

  // ── La barre de titre ──────────────────────────────────────────────

  /** L'état de ses téléphones : un lien vers Paramètres › Téléphones, pas un choix (le serveur ne dit pas lequel a reçu
   *  quel message). */
  private actions(): string {
    return phoneStateMarkup(phoneState(this.phones.value?.items ?? [], Date.now()));
  }

  /** Les âges, toutes les 30 s et d'ici (`shell/ages.ts`) : l'état de tes téléphones, et les messages (leurs
   *  propositions décidées) quand rien n'y a le focus. La Position ne montre que des heures : rien. */
  private agesTick(): void {
    if (!this.open() || !pageShown()) return;
    this.paintHead();
    const body = this.body;
    if (body && this.ctx?.tab !== "position" && this.conversations.value && !body.contains(document.activeElement)) this.paint();
  }

  /** L'état suit la liste des téléphones sans redessiner tout l'en-tête (ni perdre une saisie). */
  private paintHead(): void {
    const link = this.ctx?.el.querySelector<HTMLElement>("[data-tel-state]");
    if (!link) return;
    link.outerHTML = this.actions();
  }

  // ── Les gestes ─────────────────────────────────────────────────────

  private mount(section: HTMLElement): void {
    on(section, "[data-conv]", "click", (_e, b) => {
      this.shell.go(`#${ID}/messages/${encodeURIComponent(b.dataset.conv ?? "")}`);
    });
    on(section, "[data-retour]", "click", () => this.shell.go(`#${ID}/messages`));
    on(section, "[data-more]", "click", (e, b) => {
      e.stopPropagation();
      openMenu(b, [{ label: "Lui en parler dans le chat", icon: "sparkle", action: () => this.askAbout() }]);
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

  /** « Lui en parler dans le chat » : le chat s'ouvre avec une phrase qui nomme la conversation ouverte. */
  private askAbout(): void {
    const key = this.selectedKey();
    const conv = key ? this.conversations.value?.items.find((c) => c.key === key) : null;
    if (conv) this.hooks.ask(askAboutConversation(conv));
    else this.shell.go("#chat");
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

export function telephoneScreen(shell: Shell, hooks: TelephoneHooks): ScreenDef {
  return new TelephoneScreen(shell, hooks).def();
}
