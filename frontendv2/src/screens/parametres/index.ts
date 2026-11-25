/**
 * L'écran « Paramètres » (ADR 0187) : ce que la personne connectée règle pour elle-même — son compte, ses boîtes, ses
 * comptes Teams, ses téléphones, ses partages et ses services MCP —, par l'API par personne (`protocole-moi.md`
 * § 5, 7, 8 ; `app/me/sharing.py`). La forme : `maquette/ecrans/parametres.js`. Chaque onglet est une page : Compte
 * et Partages ici (`account.ts`, `shares.ts`), les autres dans l'écran de leur domaine (`../mail/settings.ts`,
 * `../teams/settings.ts`, `../agenda/settings.ts`, `../telephone/settings.ts`, `../outils/settings.ts`), toutes
 * dessinées avec le kit de `shared/settings.ts` ; ici, la lecture, le dessin, la barre d'enregistrement, les
 * sous-onglets et les routes d'action (`#parametres/mcp/+brancher` : l'onglet, puis la fenêtre que son bouton ouvre).
 *
 * Le direct (ADR 0308, `protocole-moi.md` § 2 bis) relit la page ouverte : `settings` (boîtes, comptes Teams,
 * services, partages, droits), `me` (ton compte), `phone.phones`, et `mail` et `teams` (l'état d'une boîte, le dernier
 * lot d'une extension) — sauf sous une saisie pas encore enregistrée, comme après un geste. L'écran au second plan, ou
 * l'onglet caché, se relit à son retour. Seule la connexion Microsoft d'une boîte relit encore à son rythme : elle
 * attend Microsoft, que rien du journal ne dit (`../mail/settings.ts::watchSignin`).
 */
import { $, $$, on } from "../../shell/dom";
import type { PaletteEntry } from "../../shell/palette";
import { applyTheme, isThemeChoice, THEME_LABELS } from "../../shell/theme";
import type { ScreenContext, ScreenDef, Shell } from "../../shell/shell";
import { toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import { accountPage } from "./account";
import { agendasPage } from "../agenda/settings";
import { Freshness, live, OneAtATime, pageShown, type Topic } from "../../live/live";
import { ages } from "../../shell/ages";
import { CachedMap, errorBlock, loadingBlock, type Cached } from "../../shared/kit";
import { formOf, SaveBar, type Host, type Page } from "../../shared/settings";
import { mailPage } from "../mail/settings";
import { mcpPage } from "../outils/settings";
import { phonesPage } from "../telephone/settings";
import { sharesPage } from "./shares";
import { teamsPage } from "../teams/settings";

const ID = "parametres";
/** Les pages qu'il montre, dans l'ordre de ses onglets : la liste est écrite ici, chacune importée de l'écran de son
 *  domaine (Compte et Partages sont à lui). */
const PAGES: Page[] = [accountPage, mailPage, teamsPage, agendasPage, phonesPage, sharesPage, mcpPage];
/**
 * Les routes d'action, par onglet : `#parametres/<onglet>/+<geste>` ouvre l'onglet, puis la fenêtre que son bouton
 * ouvre (son `data-act`), sur le sous-onglet qui le porte — ce qu'un bouton d'un autre écran ou la palette promet, le
 * clic le fait. L'adresse redevient celle de l'onglet : revenir en arrière ou recharger ne rouvre rien.
 */
export const ACTION_ROUTES: Record<string, Record<string, { act: string; sub?: string }>> = {
  compte: { "mot-de-passe": { act: "password", sub: "securite" } },
  partages: { partager: { act: "share-new" } },
  mcp: { brancher: { act: "mcp-plug" } },
};

/** Le geste d'une route d'action (`+brancher` sur l'onglet `mcp`) ; `null` : un objet ordinaire, ou rien. */
export function routeAction(tab: string | null, item: string | null): { act: string; sub?: string } | null {
  if (!tab || !item?.startsWith("+")) return null;
  return ACTION_ROUTES[tab]?.[item.slice(1)] ?? null;
}

const TABS = [
  { id: "compte", title: "Compte" },
  { id: "comptes-mail", title: "Comptes mail" },
  { id: "teams", title: "Teams" },
  { id: "agendas", title: "Agendas" },
  { id: "telephones", title: "Téléphones" },
  { id: "partages", title: "Partages" },
  { id: "mcp", title: "Services MCP" },
];
/** Ce que le direct fait relire à la page ouverte (ses lectures, toutes). */
const FOLLOWED: readonly Topic[] = ["settings", "me", "phone.phones", "mail", "teams", "agenda"];

class ParametresScreen {
  private body: HTMLElement | null = null;
  private ctx: ScreenContext | null = null;
  private painted = "";
  /** Le geste d'une route d'action, à faire une fois l'onglet lu et dessiné. */
  private pending: { tab: string; act: string } | null = null;
  private readonly subs = new Map<string, string>();
  private readonly bar: SaveBar;
  private readonly host: Host;
  /** Le direct (ADR 0308) : montré, l'écran relit sa page ; sinon il se relit à son retour. */
  private readonly fresh = new Freshness(() => this.open() && pageShown(), () => void this.relive());
  /** Une relecture de la page à la fois : demandée pendant qu'elle est en vol, elle se refait une fois après. */
  private readonly reliving = new OneAtATime(() => this.ensure(true));

  constructor(private readonly shell: Shell) {
    // ses sujets ensemble : une trame qui en nomme plusieurs (un partage : `settings`, `mail`, `me`) relit la page une fois
    live.onAny(FOLLOWED, () => this.fresh.touch(() => void this.relive()));
    // ses âges (« relevée il y a », « dernier envoi », « vu il y a ») avancent d'eux-mêmes, sans rien relire
    ages.onTick(() => this.agesTick());
    this.bar = new SaveBar({
      save: (form, changes, values) => {
        const page = this.page();
        return page?.save ? page.save(form, changes, values, this.ctx?.item ?? null, this.host) : Promise.resolve(true);
      },
      reset: () => this.paint(),
    });
    this.host = {
      shell,
      bar: this.bar,
      sub: (page, fallback) => this.subs.get(page) ?? fallback,
      setSub: (page, value) => void this.subs.set(page, value),
      repaint: () => this.paint(),
      reload: (...caches) => this.reload(caches),
      go: (hash) => shell.go(hash),
    };
  }

  def(): ScreenDef {
    return {
      id: ID,
      title: "Paramètres",
      // la barre du bas d'un téléphone a huit entrées : un mot plus court y tient
      short: "Réglages",
      icon: "settings",
      tabs: TABS,
      defaultTab: "compte",
      actions: (ctx) => this.page(ctx.tab)?.actions?.(ctx.item, this.host) ?? "",
      mount: (section) => this.mount(section),
      render: (body, ctx) => this.render(body, ctx),
      search: () => this.searchEntries(),
    };
  }

  private page(tab = this.ctx?.tab): Page | undefined {
    return PAGES.find((p) => p.id === tab);
  }

  private open(): boolean {
    return this.shell.ctx?.screen === ID && !!this.body?.isConnected;
  }

  // ── Les lectures ───────────────────────────────────────────────────

  private caches(): Cached<unknown>[] {
    const page = this.page();
    const item = this.ctx?.item ?? null;
    return page ? [...page.needs(item), ...(page.extras?.(item) ?? [])] : [];
  }

  private stamp(): string {
    return [this.ctx?.tab, this.ctx?.item, ...this.caches().map((c) => c.version)].join("|");
  }

  private async ensure(force = false): Promise<void> {
    const page = this.page();
    if (!page) return;
    const item = this.ctx?.item ?? null;
    await Promise.all(page.needs(item).map((c) => c.load(force)));
    // ce qui enrichit la page, une fois ce qu'elle exige arrivé (sa liste peut en dépendre)
    await Promise.all((page.extras?.(item) ?? []).map((c) => c.load(force)));
    if (!this.open() || this.stamp() === this.painted) return;
    // une saisie en cours ne s'efface pas sous les doigts : on redessine à la prochaine ouverture
    if (this.holding()) return;
    this.paint();
    this.shell.refreshHead();
  }

  /** Le direct : ce que la page lit repart du serveur (forcé : une lecture en vol a pu partir avant ce changement) ;
   *  elle se redessine si ça a changé, sauf sous une saisie. Une à la fois (`reliving`). */
  private relive(): Promise<void> {
    return this.reliving.run();
  }

  /** Les âges, toutes les 30 s et d'ici (`shell/ages.ts`) : la page ouverte se repeint de ce qu'elle a déjà lu — pas
   *  sous une saisie pas encore enregistrée, ni quand le curseur (ou le focus) est dans la page : elle attend le pas
   *  suivant. */
  private agesTick(): void {
    const body = this.body;
    if (!body || !this.open() || !pageShown() || this.holding() || body.contains(document.activeElement)) return;
    this.paint();
  }

  /** Un formulaire de la page a des modifications non enregistrées : un nouveau dessin les effacerait. */
  private holding(): boolean {
    return !!this.body && this.bar.holds(this.body);
  }

  /** Relire après un geste (tester, se connecter, partager…), puis redessiner — sauf sous une saisie pas encore
   *  enregistrée : elle reste telle quelle (la barre d'enregistrement aussi), le reste suivra au prochain dessin. */
  private async reload(caches: (Cached<unknown> | CachedMap<unknown>)[]): Promise<void> {
    const all = caches.length ? caches : this.caches();
    for (const c of all) c.invalidate();
    await this.ensure();
    if (!this.open()) return;
    if (!this.holding()) this.paint();
    this.shell.refreshHead();
  }

  // ── Le rendu ───────────────────────────────────────────────────────

  private render(body: HTMLElement, ctx: ScreenContext): void {
    this.body = body;
    this.ctx = ctx;
    const action = routeAction(ctx.tab, ctx.item);
    if (ctx.item?.startsWith("+")) {
      // une route d'action : l'onglet se montre tel quel, et l'adresse redevient la sienne (sans redessiner l'écran)
      ctx.item = null;
      history.replaceState(null, "", `#${ID}/${ctx.tab ?? ""}`);
      this.shell.refreshHead();
    }
    this.pending = action && ctx.tab ? { tab: ctx.tab, act: action.act } : null;
    if (action?.sub && ctx.tab) this.subs.set(ctx.tab, action.sub);
    this.paint();
    if (this.fresh.pending) {
      // revenue après un changement manqué : la page repart du serveur
      this.fresh.fresh();
      for (const c of this.caches()) c.invalidate();
    }
    void this.ensure().then(() => this.runPending());
  }

  /** Le geste d'une route d'action, une fois l'onglet lu : sa fenêtre s'ouvre, comme au clic de son bouton. */
  private runPending(): void {
    const pending = this.pending;
    this.pending = null;
    const page = this.page();
    if (!pending || !page?.act || !this.open() || this.ctx?.tab !== pending.tab) return;
    const el = document.createElement("button");
    el.dataset.act = pending.act;
    page.act(pending.act, el, null, this.host);
  }

  private paint(): void {
    const body = this.body;
    const ctx = this.ctx;
    const page = this.page();
    if (!body || !ctx || !page) return;
    this.painted = this.stamp();
    const needs = page.needs(ctx.item);
    const failed = needs.find((c) => c.value === null && c.error !== null);
    let inner: string;
    if (failed) inner = errorBlock(failed.error);
    else if (needs.some((c) => !c.settled)) inner = loadingBlock();
    else inner = page.view(ctx.item, this.host);
    const scroller = $<HTMLElement>(".fill-scroll", body);
    const top = scroller && body.dataset.view === `${ctx.tab}/${ctx.item ?? ""}` ? scroller.scrollTop : 0;
    body.innerHTML = `<div class="fill-scroll"><div class="page-pad">${inner}</div></div>`;
    body.dataset.view = `${ctx.tab}/${ctx.item ?? ""}`;
    const fresh = $<HTMLElement>(".fill-scroll", body);
    if (fresh) fresh.scrollTop = top;
    for (const form of $$<HTMLElement>("[data-form]", body)) this.bar.track(form);
    page.after?.(body, ctx.item, this.host);
  }

  // ── Les gestes ─────────────────────────────────────────────────────

  private mount(section: HTMLElement): void {
    on(section, "[data-act]", "click", (e, el) => {
      const page = this.page();
      if (!page?.act || el.hasAttribute("disabled")) return;
      e.preventDefault();
      page.act(el.dataset.act ?? "", el, this.ctx?.item ?? null, this.host);
    });
    on(section, "[data-sousv]", "click", (_e, b) => {
      const nav = b.closest<HTMLElement>("[data-souspage]");
      if (!nav) return;
      const page = nav.dataset.souspage ?? "";
      const value = b.dataset.sousv ?? "";
      this.subs.set(page, value);
      for (const x of $$("button", nav)) x.setAttribute("aria-pressed", String(x === b));
      const root = nav.parentElement ?? section;
      for (const s of $$<HTMLElement>("[data-sous]", root)) s.hidden = s.dataset.sous !== value;
    });
    on(section, "[data-retry]", "click", () => void this.reload([]));
    on(section, "[data-relogin]", "click", () => location.reload());
    const touched = (e: Event) => {
      const form = formOf(e.target);
      if (form) this.bar.touched(form);
    };
    section.addEventListener("input", touched);
    section.addEventListener("change", touched);
    section.addEventListener("mika:seg", (e) => {
      const detail = (e as CustomEvent<{ name?: string; value?: string }>).detail;
      if (detail.name === "theme" && isThemeChoice(detail.value)) {
        applyTheme(detail.value);
        this.paintThemeButton();
        toast(`Thème : ${THEME_LABELS[detail.value]}`, { ico: "sun" });
        return;
      }
      touched(e);
    });
    section.addEventListener("submit", (e) => {
      e.preventDefault();
      const form = formOf(e.target);
      if (form) void this.bar.submit(form);
    });
  }

  /** Le bouton du thème de la barre du haut suit le choix fait ici (le cadre ne le repeint qu'à son clic). */
  private paintThemeButton(): void {
    const btn = document.getElementById("theme-btn");
    if (!btn) return;
    const choice = document.documentElement.dataset.themeChoice;
    const dark = document.documentElement.dataset.theme === "dark";
    btn.innerHTML = ico(choice === "system" ? "monitor" : dark ? "moon" : "sun");
    if (isThemeChoice(choice)) btn.title = `Thème : ${THEME_LABELS[choice]} (cliquer pour changer)`;
  }

  private searchEntries(): PaletteEntry[] {
    const out: PaletteEntry[] = [
      // un geste promis s'ouvre au clic : sa route d'action (`ACTION_ROUTES`)
      { group: "Paramètres", title: "Changer le mot de passe", sub: "Compte", icon: "key", route: `#${ID}/compte/+mot-de-passe` },
      { group: "Paramètres", title: "Télécharger l'application Android", sub: "Téléphones", icon: "download", route: `#${ID}/telephones` },
      { group: "Paramètres", title: "Partager une boîte ou un service", sub: "Partages", icon: "users", route: `#${ID}/partages/+partager` },
      { group: "Paramètres", title: "Brancher un service MCP", sub: "Services MCP", icon: "plug", route: `#${ID}/mcp/+brancher` },
    ];
    for (const p of PAGES) out.push(...(p.search?.() ?? []));
    return out;
  }
}

export function parametresScreen(shell: Shell): ScreenDef {
  return new ParametresScreen(shell).def();
}
