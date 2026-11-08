/**
 * Le cadre : la barre du haut (la marque, les rubriques, « Rechercher partout », Mika, le thème, le compte),
 * la barre de titre de chaque écran avec ses onglets, la barre du bas d'un téléphone, la palette Ctrl K et la
 * carte « Ce qu'elle fait ». Le port typé du moteur de la maquette (`frontendv2/maquette/maquette.js`).
 *
 * Écrire un écran :
 *
 *   shell.register({
 *     id: "mail", title: "Mail", icon: "mail",
 *     tabs: [{ id: "messages", title: "Messages" }, { id: "contacts", title: "Contacts" }],
 *     actions: (ctx) => "<button …>",      // HTML des actions de page, à droite de la barre de titre
 *     render: (body, ctx) => { … },        // remplit (ou met à jour) le corps ; rappelé à chaque route
 *     search: () => [{ group: "Mails", title, sub, icon: "mail", route: "#mail/messages/m3" }],
 *   });
 *
 * Mika est dans la pastille du haut ; un écran lui offre une scène plus grande en posant un
 * `[data-mika-scene]` dans son corps (la colonne du chat).
 */
import { MikaCorner } from "../mika/corner";
import { mikaAvatar } from "../mika/face";
import { dreamLabel, driveLabel, momentLabel, placeLabel, sleepLabel } from "../mika/labels";
import { isAsleep } from "../mika/state";
import type { MikaSnapshot, MikaStore } from "../mika/store";
import { facetHtml, facetsOf, percent, projectHtml, promiseHtml, statusLine } from "../mika/view";
import { $, $$, h, initials, isMobile, on } from "./dom";
import { closeMenu, closeModal, modalOpen, openMenu, toast, type MenuItem } from "./float";
import { ico, type IconName } from "./icons";
import { filterPalette, GO_TO, type PaletteEntry } from "./palette";
import { parseRoute, type Route, type ScreenShape } from "./router";
import { applyTheme, currentChoice, nextTheme, onTheme, THEME_LABELS, type ThemeChoice } from "./theme";

export interface Account {
  username: string;
  displayName: string;
  operator: boolean;
  personId: string;
}

export interface ScreenContext extends Route {
  el: HTMLElement;
}

export interface ScreenTab {
  id: string;
  title: string;
  icon?: IconName;
  count?: number | string;
}

export interface ScreenDef {
  id: string;
  title: string;
  icon: IconName;
  /** Le libellé de la barre du bas d'un téléphone, s'il est plus court. */
  short?: string;
  tabs?: ScreenTab[];
  defaultTab?: string;
  subtitle?: (ctx: ScreenContext) => string;
  actions?: (ctx: ScreenContext) => string;
  /** Une fois, à la première ouverture : ses écouteurs délégués. */
  mount?: (section: HTMLElement) => void;
  render: (body: HTMLElement, ctx: ScreenContext) => void;
  search?: () => PaletteEntry[];
  /** La pastille de la barre du haut (`""` : rien). */
  count?: () => number | "";
}

/** L'ordre de la barre du bas d'un téléphone, comme sur Android (et la maquette : sept entrées). */
export const TABBAR_ORDER = ["chat", "mail", "teams", "telephone", "carte", "outils", "parametres"];

function cornerMarkup(): string {
  return `<span class="mika-corner" id="mika-corner" data-size="mini">
    <span class="mc-stage" id="mc-stage">
      <span class="mc-glow" aria-hidden="true"></span>
      <img class="mc-portrait" id="mc-portrait" alt="" draggable="false" hidden>
      <img class="mc-blink" id="mc-blink" alt="" draggable="false" hidden>
      <canvas class="mc-canvas" id="mc-canvas" hidden></canvas>
      <span class="mc-live" id="mc-live" hidden>VRM</span>
    </span>
  </span>`;
}

export class Shell {
  private readonly screens = new Map<string, ScreenDef>();
  private readonly order: string[] = [];
  private current: ScreenContext | null = null;
  private paletteItems: PaletteEntry[] = [];
  private paletteSel = 0;
  corner!: MikaCorner;

  constructor(
    private readonly root: HTMLElement,
    private readonly store: MikaStore,
    private account: Account,
    private readonly hooks: { logout: () => void; console?: string },
  ) {}

  register(def: ScreenDef): void {
    this.screens.set(def.id, def);
    if (!this.order.includes(def.id)) this.order.push(def.id);
  }

  get ctx(): ScreenContext | null {
    return this.current;
  }

  get user(): Account {
    return this.account;
  }

  /**
   * Le compte change de nom — renommé dans Paramètres, ou ailleurs (un autre appareil, la console : `main.ts` le relit
   * avec les pastilles) : le menu suit.
   */
  setAccount(account: Account): void {
    this.account = account;
    this.paintAccount();
  }

  start(): void {
    this.root.innerHTML = this.frameMarkup();
    this.root.hidden = false;
    this.corner = new MikaCorner(this.store);
    this.bind();
    this.paintAccount();
    this.paintTheme();
    onTheme(() => this.paintTheme()); // un changement venu d'ailleurs (Paramètres, le système) le repeint
    this.store.subscribe((snap) => this.paintMika(snap));
    addEventListener("hashchange", () => this.display());
    this.display();
  }

  /** Redessine l'écran ouvert (sa barre de titre et son corps). */
  refresh(): void {
    this.display();
  }

  /** Redessine seulement la barre de titre de l'écran ouvert (son sous-titre, ses actions). */
  refreshHead(): void {
    const ctx = this.current;
    if (!ctx) return;
    const def = this.screens.get(ctx.screen);
    const head = $(".page-head", ctx.el);
    if (def && head) this.paintHead(head, def, ctx);
  }

  go(hash: string): void {
    if (location.hash === hash) this.display();
    else location.hash = hash;
  }

  /** Les pastilles des rubriques : rien tant qu'aucun écran ne compte. */
  updateCounts(): void {
    for (const badge of $$<HTMLElement>("[data-count]", this.root)) {
      const def = this.screens.get(badge.dataset.count ?? "");
      const n = def?.count ? def.count() : "";
      badge.textContent = n ? (n > 99 ? "99+" : String(n)) : "";
    }
  }

  // ── Le cadre ───────────────────────────────────────────────────────

  private frameMarkup(): string {
    const defs = this.order.map((id) => this.screens.get(id)!);
    const nav = defs
      .map(
        (d) => `<a href="#${d.id}" data-nav="${d.id}" title="${h(d.title)}" aria-label="${h(d.title)}">${ico(d.icon)}<span>${h(d.title)}</span><b class="badge" data-count="${d.id}"></b></a>`,
      )
      .join("");
    const tabbar = TABBAR_ORDER.filter((id) => this.screens.has(id))
      .map((id) => this.screens.get(id)!)
      .map(
        (d) => `<a href="#${d.id}" data-nav="${d.id}">${ico(d.icon)}<span>${h(d.short ?? d.title)}</span><b class="badge" data-count="${d.id}"></b></a>`,
      )
      .join("");
    const sections = defs.map((d) => `<section class="screen" data-screen="${d.id}" hidden></section>`).join("");
    return `<header class="top">
      <a class="brand" href="#chat" aria-label="Mika, accueil"><span class="brand-mark" aria-hidden="true">M</span><span class="brand-name">Mika</span></a>
      <button class="brand-face" id="brand-face" type="button" title="Ce qu'elle fait"></button>
      <nav class="nav" id="nav" aria-label="Rubriques">${nav}</nav>
      <div class="top-right">
        <button class="gsearch" id="gsearch" type="button" title="Rechercher partout (Ctrl K)" aria-label="Rechercher partout">
          ${ico("search", "sm")}<span>Rechercher partout</span><kbd class="kbd">Ctrl K</kbd></button>
        <button class="state-pill" id="state-pill" type="button" aria-haspopup="dialog" title="Ce qu'elle fait">
          <span class="sp-face">${cornerMarkup()}
            <span class="sp-static" id="sp-static" aria-hidden="true"></span>
            <i class="sp-on" aria-hidden="true"></i>
            <span class="mc-typing" id="mc-typing" hidden><i></i><i></i><i></i></span>
          </span>
          <span class="sp-text"><b>Mika</b><span class="sp-doing">connexion…</span></span>
        </button>
        <button class="btn icon ghost" id="theme-btn" type="button" title="Thème">${ico("sun")}</button>
        <button class="acct" id="acct-btn" type="button" aria-haspopup="menu" title="Ton compte"></button>
      </div>
    </header>
    <main class="screens" id="screens">${sections}</main>
    <nav class="tabbar" id="tabbar" aria-label="Rubriques">${tabbar}</nav>`;
  }

  private bind(): void {
    $("#theme-btn", this.root)!.addEventListener("click", () => {
      applyTheme(nextTheme(currentChoice()));
      this.paintTheme();
      toast(`Thème : ${THEME_LABELS[currentChoice()]}`, { ico: "sun" });
    });
    $("#acct-btn", this.root)!.addEventListener("click", (e) => {
      e.stopPropagation();
      this.accountMenu(e.currentTarget as HTMLElement);
    });
    for (const id of ["#state-pill", "#brand-face"]) {
      $(id, this.root)!.addEventListener("click", (e) => {
        e.stopPropagation();
        this.toggleStateCard(e.currentTarget as HTMLElement);
      });
    }
    on($("#state-card")!, "[data-close-state]", "click", () => this.closeStateCard());
    $("#gsearch", this.root)!.addEventListener("click", () => this.openPalette());
    const input = $<HTMLInputElement>("#palette-q")!;
    input.addEventListener("input", () => this.filterPalette());
    $("#palette")!.addEventListener("mousedown", (e) => {
      if ((e.target as HTMLElement).id === "palette") this.closePalette();
    });
    on($("#palette-results")!, ".pr", "click", (_e, b) => this.choosePalette(Number(b.dataset.pi)));
    input.addEventListener("keydown", (e) => {
      const buttons = $$(".pr", $("#palette-results")!);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const n = Math.max(1, buttons.length);
        this.paletteSel = (this.paletteSel + (e.key === "ArrowDown" ? 1 : -1) + n) % n;
        buttons.forEach((b, i) => b.classList.toggle("on", i === this.paletteSel));
        buttons[this.paletteSel]?.scrollIntoView({ block: "nearest" });
      }
      if (e.key === "Enter") {
        e.preventDefault();
        this.choosePalette(this.paletteSel);
      }
    });
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if ($("#palette")!.hidden) this.openPalette();
        else this.closePalette();
      }
      if (e.key === "Escape") {
        this.closePalette();
        closeMenu();
        this.closeStateCard();
        if (modalOpen()) closeModal();
      }
    });
    // Un bouton à choix (.seg[data-seg]) se règle d'un clic, où qu'il soit ; « mika:seg » le dit.
    document.addEventListener("click", (e) => {
      const b = (e.target as Element).closest?.(".seg[data-seg] button") as HTMLElement | null;
      if (!b) return;
      const group = b.closest(".seg") as HTMLElement;
      group.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      group.dispatchEvent(
        new CustomEvent("mika:seg", { bubbles: true, detail: { name: group.dataset.seg, value: b.dataset.v } }),
      );
    });
  }

  // ── La navigation ──────────────────────────────────────────────────

  private shapes(): Map<string, ScreenShape> {
    const out = new Map<string, ScreenShape>();
    for (const [id, def] of this.screens) out.set(id, { tabs: def.tabs ?? [], defaultTab: def.defaultTab });
    return out;
  }

  private headMarkup(def: ScreenDef, ctx: ScreenContext): string {
    const tabs = (def.tabs ?? [])
      .map((t) => {
        const count = t.count !== undefined && t.count !== "" ? `<span class="cnt">${h(t.count)}</span>` : "";
        return `<a href="#${ctx.screen}/${t.id}"${t.id === ctx.tab ? ' aria-current="page"' : ""}>${t.icon ? ico(t.icon, "sm") : ""}${h(t.title)}${count}</a>`;
      })
      .join("");
    const sub = def.subtitle ? def.subtitle(ctx) : "";
    return `<div class="ph-title"><h1>${h(def.title)}</h1>${sub ? `<span class="cnt">${h(sub)}</span>` : ""}</div>
      ${tabs ? `<nav class="subtabs" aria-label="Onglets">${tabs}</nav>` : ""}
      <div class="ph-actions">${def.actions ? def.actions(ctx) : ""}</div>`;
  }

  /** La barre de titre, et le nom de ses boutons (`nameTitleButtons`). */
  private paintHead(head: HTMLElement, def: ScreenDef, ctx: ScreenContext): void {
    head.innerHTML = this.headMarkup(def, ctx);
    nameTitleButtons(head);
  }

  private display(): void {
    const route = parseRoute(location.hash, this.shapes());
    const def = this.screens.get(route.screen);
    if (!def) return;
    closeMenu();
    this.closeStateCard();
    for (const s of $$<HTMLElement>(".screen", this.root)) s.hidden = s.dataset.screen !== route.screen;
    const section = $<HTMLElement>(`.screen[data-screen="${route.screen}"]`, this.root)!;
    if (!section.dataset.mounted) {
      section.innerHTML = '<header class="page-head"></header><div class="page-body"></div>';
      section.dataset.mounted = "1";
      def.mount?.(section);
    }
    const ctx: ScreenContext = { ...route, el: section };
    this.current = ctx;
    this.paintHead($(".page-head", section)!, def, ctx);
    this.corner.park();
    def.render($(".page-body", section)!, ctx);
    this.corner.lodge(section.querySelector("[data-mika-scene]"));
    for (const a of $$<HTMLElement>("[data-nav]", this.root)) {
      if (a.dataset.nav === route.screen) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    }
    document.title = `${def.title} — Mika`;
    this.updateCounts();
  }

  // ── Mika, en haut à droite ─────────────────────────────────────────

  private paintMika(snap: MikaSnapshot): void {
    const line = statusLine(snap.state, { link: snap.link, typing: snap.typing, nowMs: Date.now() });
    const asleep = isAsleep(snap.state);
    const pill = $("#state-pill", this.root);
    if (!pill) return;
    $(".sp-doing", pill)!.textContent = line.short;
    pill.title = `Mika : ${line.full} — ce qu'elle fait`;
    pill.dataset.state = line.state;
    $("#brand-face", this.root)!.innerHTML = `${mikaAvatar("sm", asleep ? "away" : "on")}<span>Mika</span>`;
    $("#sp-static", this.root)!.innerHTML = mikaAvatar("sm");
    const card = $("#state-card");
    if (card && !card.hidden) card.innerHTML = this.stateCardMarkup(snap);
  }

  private stateCardMarkup(snap: MikaSnapshot): string {
    const s = snap.state;
    const now = Date.now();
    const line = statusLine(s, { link: snap.link, typing: snap.typing, nowMs: now });
    const asleep = isAsleep(s);
    const sections: string[] = [];
    const facets = facetsOf(s.mood);
    if (facets.length) {
      sections.push(`<div class="sc-sec"><h4>Humeur</h4>${facets.map(facetHtml).join("")}</div>`);
    }
    const body: string[] = [];
    const moment = s.circadian ? momentLabel(s.circadian.phase) : null;
    const awake = sleepLabel(s.sleepPhase);
    body.push(`<div class="sc-line">${ico("clock", "sm")}<span>${h(capital(awake))}${moment ? ` · ${h(moment)}` : ""}</span></div>`);
    if (s.energy !== null) body.push(`<div class="sc-line">${ico("bolt", "sm")}<span>Énergie ${percent(s.energy)}</span></div>`);
    const place = placeLabel(s.place);
    if (place) body.push(`<div class="sc-line">${ico("pin", "sm")}<span>${h(capital(place))}</span></div>`);
    if (s.estime !== null) body.push(`<div class="sc-line">${ico("heart", "sm")}<span>Estime de soi · ${percent(s.estime)}</span></div>`);
    sections.push(`<div class="sc-sec"><h4>Corps</h4>${body.join("")}</div>`);
    if (s.ruminations.length) {
      sections.push(
        `<div class="sc-sec"><h4>Elle repense à…</h4>${s.ruminations
          .slice(0, 3)
          .map((r) => `<div class="sc-line">${ico("sparkle", "sm")}<span>${h(r.summary)}</span></div>`)
          .join("")}</div>`,
      );
    }
    if (s.dream) {
      const meta = [dreamLabel(s.dream.kind), `netteté ${percent(s.dream.vividness)}`, ...(s.dream.recalled ? ["évoqué"] : [])];
      sections.push(
        `<div class="sc-sec"><h4>Son dernier rêve</h4><div class="sc-line">${ico("moon", "sm")}<span>${h(s.dream.content)} <span class="muted">· ${h(meta.join(" · "))}</span></span></div></div>`,
      );
    }
    const needs = Object.entries(s.drives)
      .filter(([, tension]) => tension >= 0.5)
      .sort((a, b) => b[1] - a[1]);
    if (needs.length) {
      sections.push(
        `<div class="sc-sec"><h4>Ses besoins</h4><div class="row wrap">${needs
          .map(([kind]) => `<span class="tag mika">${h(driveLabel(kind))}</span>`)
          .join("")}</div></div>`,
      );
    }
    if (s.commitments.length) {
      sections.push(`<div class="sc-sec"><h4>Ce qu'elle t'a promis</h4>${s.commitments.map(promiseHtml).join("")}</div>`);
    }
    if (s.journal) {
      sections.push(
        `<div class="sc-sec"><h4>${h(s.journal.title || "Son dernier journal")}</h4><p class="text-2">« ${h(s.journal.narrative)} »</p></div>`,
      );
    }
    if (s.projects.length) {
      sections.push(`<div class="sc-sec"><h4>Ses projets avec toi</h4>${s.projects.map(projectHtml).join("")}</div>`);
    }
    return `<div class="sc-head">${mikaAvatar("lg", asleep ? "away" : "on")}<div><b>Mika</b>
        <span>${h(line.full)}</span></div>
        <button class="btn icon ghost sm" type="button" data-close-state style="margin-left:auto" title="Fermer">${ico("x")}</button></div>
      ${sections.join("")}`;
  }

  private readonly closeStateOutside = (e: MouseEvent) => {
    const card = $("#state-card");
    const target = e.target as Element;
    if (card && !card.contains(target) && !target.closest("#state-pill, #brand-face")) this.closeStateCard();
  };

  private toggleStateCard(anchor: HTMLElement): void {
    const card = $("#state-card")!;
    if (!card.hidden) {
      this.closeStateCard();
      return;
    }
    card.innerHTML = this.stateCardMarkup(this.store.current);
    card.hidden = false;
    const r = anchor.getBoundingClientRect();
    const w = card.offsetWidth;
    const hgt = card.offsetHeight;
    let left = r.right - w;
    let top = r.bottom + 8;
    if (top + hgt > innerHeight - 8) top = Math.max(60, r.top - hgt - 8);
    if (left < 8) left = Math.min(r.left, innerWidth - w - 8);
    card.style.left = `${Math.max(8, left)}px`;
    card.style.top = `${top}px`;
    window.setTimeout(() => document.addEventListener("mousedown", this.closeStateOutside), 0);
  }

  /** « Tout ce qu'elle fait », depuis un écran (la colonne du chat). */
  openStateCard(): void {
    const pill = $("#state-pill", this.root);
    const anchor = pill && pill.offsetParent ? pill : $("#brand-face", this.root);
    if (anchor) this.toggleStateCard(anchor);
  }

  closeStateCard(): void {
    const card = $("#state-card");
    if (card) card.hidden = true;
    document.removeEventListener("mousedown", this.closeStateOutside);
  }

  // ── Le thème et le compte ──────────────────────────────────────────

  private paintTheme(): void {
    const choice = currentChoice();
    const dark = document.documentElement.dataset.theme === "dark";
    const btn = $("#theme-btn", this.root)!;
    btn.innerHTML = ico(choice === "system" ? "monitor" : dark ? "moon" : "sun");
    btn.title = `Thème : ${THEME_LABELS[choice]} (cliquer pour changer)`;
  }

  private paintAccount(): void {
    const btn = $("#acct-btn", this.root);
    if (!btn) return;
    const name = this.account.displayName || this.account.username;
    // toi, c'est l'indigo (ce que tu fais) ; elle, le rose
    btn.innerHTML = `<span class="av sm c0">${h(initials(name))}</span>`;
    btn.title = `Ton compte : ${name}`;
  }

  private accountMenu(anchor: HTMLElement): void {
    const choice = currentChoice();
    const name = this.account.displayName || this.account.username;
    const theme = (c: ThemeChoice, icon: IconName): MenuItem => ({
      label: THEME_LABELS[c],
      icon,
      checked: choice === c,
      action: () => {
        applyTheme(c);
        this.paintTheme();
      },
    });
    const items: MenuItem[] = [
      {
        html: `<div class="who"><span class="av lg c0">${h(initials(name))}</span><div><b>${h(name)}</b><span>${h(this.account.username)}${this.account.operator ? " · opérateur" : ""}</span></div></div>`,
      },
      "sep",
      { label: "Mon compte", icon: "user", action: () => this.go("#parametres/compte") },
      { label: "Mes partages", icon: "users", action: () => this.go("#parametres/partages") },
      "sep",
      { header: "Thème" },
      theme("system", "monitor"),
      theme("light", "sun"),
      theme("dark", "moon"),
      "sep",
    ];
    if (this.account.operator && this.hooks.console) {
      const href = this.hooks.console;
      items.push({ label: "Ouvrir la console de Mika", icon: "external", action: () => window.open(href, "_blank", "noopener") });
    }
    items.push({ label: "Se déconnecter", icon: "logout", danger: true, action: () => this.hooks.logout() });
    openMenu(anchor, items);
  }

  // ── La palette Ctrl K ──────────────────────────────────────────────

  private paletteEntries(): PaletteEntry[] {
    const out: PaletteEntry[] = [];
    for (const id of this.order) {
      const def = this.screens.get(id)!;
      out.push({ group: GO_TO, title: def.title, icon: def.icon, route: `#${id}` });
      for (const t of def.tabs ?? []) {
        out.push({ group: GO_TO, title: `${def.title} › ${t.title}`, icon: def.icon, route: `#${id}/${t.id}` });
      }
    }
    for (const id of this.order) {
      const def = this.screens.get(id)!;
      if (def.search) out.push(...def.search());
    }
    return out;
  }

  openPalette(): void {
    $("#palette")!.hidden = false;
    const q = $<HTMLInputElement>("#palette-q")!;
    q.value = "";
    this.filterPalette();
    window.setTimeout(() => q.focus(), 20);
  }

  private closePalette(): void {
    const p = $("#palette");
    if (p) p.hidden = true;
  }

  private filterPalette(): void {
    const q = $<HTMLInputElement>("#palette-q")!.value;
    this.paletteItems = filterPalette(this.paletteEntries(), q);
    this.paletteSel = 0;
    let group: string | null = null;
    $("#palette-results")!.innerHTML = this.paletteItems.length
      ? this.paletteItems
          .map((e, i) => {
            const head = e.group !== group ? `<div class="mh">${h((group = e.group))}</div>` : "";
            return `${head}<button class="pr${i === 0 ? " on" : ""}" type="button" data-pi="${i}">${ico(e.icon ?? "chev-right")}
              <span class="pr-main"><b>${h(e.title)}</b>${e.sub ? `<small>${h(e.sub)}</small>` : ""}</span>${e.side ? `<span class="muted">${h(e.side)}</span>` : ""}</button>`;
          })
          .join("")
      : '<div class="empty"><b>Rien trouvé</b><p>Essaie un écran, un réglage ou un mot de la conversation.</p></div>';
  }

  private choosePalette(i: number): void {
    const e = this.paletteItems[i];
    if (!e) return;
    this.closePalette();
    if (e.action) e.action();
    else if (e.route) this.go(e.route);
  }

  isMobile(): boolean {
    return isMobile();
  }
}

function capital(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

/**
 * Un bouton de la barre de titre garde son nom sur un téléphone, où base.css cache son libellé (`.lbl`) et ne laisse
 * que l'icône : il reçoit `title` (l'infobulle) et `aria-label` (le nom qu'un lecteur d'écran annonce), d'après ce
 * libellé — sauf ceux que l'écran a déjà posés (un `title` qui dit pourquoi un bouton est éteint reste).
 */
export function nameTitleButtons(head: ParentNode): void {
  for (const btn of Array.from(head.querySelectorAll<HTMLElement>(".ph-actions .btn"))) {
    const label = (btn.querySelector(".lbl")?.textContent ?? "").replace(/\s+/g, " ").trim();
    if (!label) continue;
    if (!btn.hasAttribute("title")) btn.setAttribute("title", label);
    if (!btn.hasAttribute("aria-label")) btn.setAttribute("aria-label", label);
  }
}
