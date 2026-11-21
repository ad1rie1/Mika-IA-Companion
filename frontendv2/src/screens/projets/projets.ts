/**
 * L'écran « Projets » (ADR 0291) : l'état, les lectures gardées et les gestes. Sa forme est celle de la maquette
 * validée (`maquette/ecrans/projets2*.js`) — trois zones sur toute la largeur, tout se gère dans l'écran — ; ses
 * données sont celles de l'API par personne (`protocole-moi.md` § 11). L'écran ne recalcule aucune règle : pas de
 * bouton sans le droit servi (`can`, `rights`), les mots d'une étape sont ceux du serveur, et un geste refusé se dit
 * sur place avec les siens (un 409 relit ce qu'on lisait). Un envoi, puis tout se relit.
 */
import {
  createProject, fetchActivity, fetchActivityDays, fetchActivityTotals, fetchApprovals, fetchArchives, fetchDiagram, fetchElement, fetchElements, fetchHistory, fetchNewProject, fetchNotebook,
  fetchOverview, fetchRun, fetchRuns, fetchSettings, fetchSheet, fetchTodo, sendGesture,
  type ActivityDays, type ActivityPage, type ActivityTotals, type Approval, type Archived, type Diagram, type EntryDetail, type EntryHistory, type EntryPage, type GestureDone, type Happening,
  type NewProject, type NotebookPage, type Overview, type RunDetail, type RunPage, type Settings, type Sheet, type Waiting,
} from "../../api/projects";
import { ApiError } from "../../api/moi";
import { Cached, CachedMap, confirmModal, errorBlock, failureText, loadingBlock, newNonce, sessionGone } from "../../shared/kit";
import { refreshCounts, countOf } from "../../shell/counts";
import { $, $$, h, isMobile } from "../../shell/dom";
import { closeModal, openMenu, openModal, toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import { nameTitleButtons, type ScreenDef, type Shell } from "../../shell/shell";
import {
  assignRequest, checkpointRequest, gestureRead, gestureRequest, itemAddRequest, linkCandidates, linkRequest, linkWhyRequest, milestoneRequest, noteRequest, objectiveRequest, objectiveStatusRequest, pilotRequest,
  refusalWords, settingsRequest, settleRequest, statusRequest, ticketRequest, type GestureRequest, type Values,
} from "./gestures";
import { drawer as drawerMarkup, F, refusal, served, type DrawerOpts } from "./parts";
import { parsePlace, route, sheetRoute, waitingKey, type Place } from "./routes";
import { cacheKey, fieldErrorsAt, findGoal, followLists, initialState, refusalAt, ticketList, ticketsQuery, type UiState } from "./state";
import { pluggedTab, pluggedTabs, type Act, type FormAct, type TabHost } from "./tabs";
import { activityView } from "./views/activity";
import { diagramView } from "./views/diagram";
import { askDrawerBody, dependenciesView, itemDrawerBody, linkDrawerBody, listsView, settingsView } from "./views/more";
import { goalDrawerBody, milestoneDrawerBody, objectivesView } from "./views/objectives";
import { gridView, overviewView, screenHead, sheetHead } from "./views/sheet";
import { ticketFields, ticketsView } from "./views/tickets";
import { todoView, type Ctx, type Got } from "./views/todo";

/** Ce qu'un formulaire a rendu : ses champs par nom ; une case seule : vrai ou faux ; plusieurs du même nom : une liste. */
export function formValues(form: HTMLFormElement): Values {
  const out: Values = {};
  const boxes = new Map<string, HTMLInputElement[]>();
  for (const el of Array.from(form.elements) as Array<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) {
    if (!el.name) continue;
    if (el instanceof HTMLInputElement && el.type === "checkbox") boxes.set(el.name, [...(boxes.get(el.name) ?? []), el]);
    else if (el instanceof HTMLInputElement && el.type === "radio") {
      if (el.checked) out[el.name] = el.value;
    } else out[el.name] = el.value;
  }
  for (const [name, list] of boxes) {
    out[name] = list.length > 1 || list[0].hasAttribute("value") ? list.filter((b) => b.checked).map((b) => b.value) : list[0].checked;
  }
  return out;
}

class Projets implements TabHost {
  ui: UiState = initialState();
  private body: HTMLElement | null = null;
  private lastRoute = "";
  private openInfos = false;
  private dropTyped = false;
  private drawerMake: (() => DrawerOpts) | null = null;
  private todoMore: Waiting[] = [];
  private readonly feedMore = new Map<string, Happening[]>();
  private readonly feedNext = new Map<string, number>();
  private queryTimer = 0;

  private readonly overview = new Cached<Overview>(fetchOverview);
  private readonly archives = new Cached<{ items: Archived[] }>(fetchArchives, 60_000);
  private readonly fresh = new Cached<NewProject>(fetchNewProject, 60_000);
  private readonly sheets = new CachedMap<Sheet>((id) => fetchSheet(Number(id)));
  private readonly approvals = new CachedMap<{ items: Approval[] }>((id) => fetchApprovals(Number(id)));
  private readonly elements = new CachedMap<EntryPage>((key) => {
    const [id, list, state, q] = key.split("|");
    return fetchElements(Number(id), { list, state: state || undefined, q: q || undefined, size: 100 });
  });
  private readonly element = new CachedMap<EntryDetail>((key) => {
    const [id, list, ...item] = key.split("|");
    return fetchElement(Number(id), list, item.join("|"));
  });
  private readonly settings = new CachedMap<Settings>((id) => fetchSettings(Number(id)));
  /** Le fil : par sorte et par objectif ; ou filtré sur un ticket (l'Historique de ce ticket). */
  private readonly feed = new CachedMap<ActivityPage>((key) => {
    const [id, kind, objective, ticket] = key.split("|");
    return fetchActivity(Number(id), { kind: kind || undefined, objective: Number(objective) || undefined, ticket: Number(ticket) || undefined });
  });
  private readonly totals = new CachedMap<ActivityTotals>((key) => {
    const [id, objective] = key.split("|");
    return fetchActivityTotals(Number(id), { objective: Number(objective) || undefined });
  });
  private readonly history = new CachedMap<EntryHistory>((key) => {
    const [id, ...item] = key.split("|");
    return fetchHistory(Number(id), item.join("|"));
  });
  private readonly days = new CachedMap<ActivityDays>((id) => fetchActivityDays(Number(id)), 60_000);
  private readonly runs = new CachedMap<RunPage>((id) => fetchRuns(Number(id)));
  private readonly run = new CachedMap<RunDetail>((key) => {
    const [id, ...run] = key.split("|");
    return fetchRun(Number(id), run.join("|"));
  });
  private readonly notes = new CachedMap<NotebookPage>((key) => {
    const [id, objective] = key.split("|");
    return fetchNotebook(Number(id), Number(objective) || 0);
  });
  private readonly diagram = new CachedMap<Diagram>((id) => fetchDiagram(Number(id)));

  constructor(private readonly shell: Shell) {}

  screen(): ScreenDef {
    return {
      id: "projets", title: "Projets", icon: "flag", noHead: true,
      tabs: [{ id: "a-faire", title: "À faire" }, { id: "projets", title: "Projets" }],
      mount: () => this.mount(),
      render: (body) => {
        this.body = body;
        this.paint();
      },
      search: () => (this.overview.value?.projects ?? []).map((p) => ({ group: "Projets", title: p.title, sub: p.where || p.status_label, icon: "flag" as const, route: sheetRoute(p.id) })),
      count: () => countOf("projects"),
    };
  }

  // ── Ce que le socle partage (TabHost) ──────────────────────────────

  ctx(): Ctx {
    return { now: Date.now(), mobile: isMobile(), ui: this.ui, me: this.shell.user.displayName || this.shell.user.username };
  }

  read<T>(cached: Cached<T>): Got<T> {
    const before = cached.version;
    void cached.load().then(() => {
      if (cached.version !== before) this.repaint();
    });
    return { value: cached.value, error: cached.error };
  }

  readElement(project: number, list: string, item: string): Got<EntryDetail> {
    return this.read(this.element.get(cacheKey(project, list, item)));
  }

  repaint(): void {
    this.paint();
  }

  go(hash: string): void {
    this.shell.go(hash);
  }

  async send(project: number, request: GestureRequest, where: string, done?: (r: GestureDone) => void): Promise<boolean> {
    if (this.ui.busy) return false;
    this.ui.busy = where;
    try {
      const r = await sendGesture(project, request.route, request.body, newNonce());
      this.ui.busy = "";
      this.ui.refusal = null;
      this.dropTyped = true;
      if (r.message) toast(r.message, { mika: true });
      this.changed();
      const address = location.hash;
      done?.(r);
      // un geste qui mène ailleurs (une page renommée, supprimée) : l'adresse a changé, et c'est elle qui redessine —
      // redessiner ici relirait encore l'ancienne adresse, qui n'existe plus (un 404 de plus, et son message un instant)
      if (location.hash === address) this.paint();
      return true;
    } catch (err) {
      this.ui.busy = "";
      this.refused(err, where);
      return false;
    }
  }

  ask(o: { title: string; label: string; ok: string; required?: boolean; danger?: boolean }): Promise<string | null> {
    return new Promise((resolve) => {
      let answered = false;
      const el = openModal({
        title: o.title, size: "narrow", body: `<div class="stack">${F.long("typed", o.label, "", { rows: 4 })}</div>`,
        foot: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn ${o.danger ? "danger" : "primary"}" type="button" data-ok>${h(o.ok)}</button>`,
      });
      const field = el.querySelector<HTMLTextAreaElement>("textarea");
      el.querySelector("[data-ok]")?.addEventListener("click", () => {
        const text = field?.value.trim() ?? "";
        if (!text && o.required) {
          field?.classList.add("p2-manque");
          field?.focus();
          return;
        }
        answered = true;
        closeModal();
        resolve(text);
      });
      const scrim = el.parentElement;
      const watch = new MutationObserver(() => {
        if (!scrim?.isConnected) {
          watch.disconnect();
          if (!answered) resolve(null);
        }
      });
      if (scrim?.parentElement) watch.observe(scrim.parentElement, { childList: true });
    });
  }

  confirm(o: { title: string; text: string; ok: string; danger?: boolean }): Promise<boolean> {
    return confirmModal(o);
  }

  drawer(make: () => DrawerOpts): void {
    this.drawerMake = make;
    this.paintDrawer(false);
  }

  closeDrawer(): void {
    this.drawerMake = null;
    const root = document.getElementById("p2-drawer-root");
    if (root) root.innerHTML = "";
  }

  // ── Les lectures ───────────────────────────────────────────────────

  /** Après un geste : tout ce qui est lu repart du serveur, et la pastille de la barre du haut avec. */
  private changed(): void {
    this.overview.invalidate();
    this.archives.invalidate();
    for (const map of [this.sheets, this.approvals, this.elements, this.element, this.settings, this.feed, this.totals, this.history, this.days, this.runs, this.run, this.notes, this.diagram]) map.invalidate();
    for (const tab of pluggedTabs()) tab.invalidate?.();
    this.todoMore = [];
    this.feedMore.clear();
    this.feedNext.clear();
    void refreshCounts();
  }

  /** Un refus : ses mots, dits à l'endroit du geste ; un 409, et ce qu'on lisait se relit. */
  private refused(err: unknown, where: string): void {
    if (sessionGone(err)) {
      location.reload();
      return;
    }
    const fields = err instanceof ApiError ? err.fields : {};
    this.ui.refusal = { where, text: refusalWords(failureText(err), fields), fields };
    if (err instanceof ApiError && (err.status === 409 || err.status === 404)) this.changed();
    if (this.drawerMake) this.paintDrawer(true);
    this.paint();
  }

  private todo(): Waiting[] {
    return [...(this.overview.value?.todo ?? []), ...this.todoMore];
  }

  // ── Le dessin ──────────────────────────────────────────────────────

  private paint(): void {
    const sc = this.shell.ctx;
    const body = this.body;
    if (!sc || sc.screen !== "projets" || !body || !body.isConnected) return;
    const place = parsePlace(sc.tab, sc.item);
    if (location.hash !== this.lastRoute) {
      this.ui.infos = this.openInfos && isMobile();
      if (this.lastRoute) this.ui.refusal = null;
      this.lastRoute = location.hash;
    }
    this.openInfos = false;
    const kept = this.keep(body);
    const [head, inner, sheet, rest] = this.draw(place);
    body.innerHTML = `<div class="p2${place.kind === "sheet" ? " p2-fiche" : ""}">${head}<div class="p2-body">${refusal(refusalAt(this.ui, "top")).replace('class="p2-banner', 'class="p2-strip p2-banner')}${inner}</div></div>`;
    this.restore(body, kept);
    const top = $(".page-head", body);
    if (top) nameTitleButtons(top);
    this.after(body);
    if (place.kind === "sheet" && sheet) pluggedTab(place.tab)?.after?.(body, sheet, rest, this);
  }

  private draw(place: Place): [head: string, body: string, sheet: Sheet | null, rest: string[]] {
    const ctx = this.ctx();
    const overview = this.read(this.overview);
    if (place.kind !== "sheet") {
      const head = screenHead(overview.value, place);
      if (!overview.value) return [head, overview.error ? errorBlock(overview.error) : loadingBlock(), null, []];
      // la grille ne lit que la liste : chaque carte y porte de quoi se remplir (`card`)
      if (place.kind === "grid") return [head, gridView(overview.value, this.read(this.archives).value?.items ?? [], ctx), null, []];
      const todo = this.todo();
      const shown = todo.filter((w) => !this.ui.todoProject || w.project === this.ui.todoProject);
      const w = todo.find((x) => x.project === place.project && waitingKey(x) === place.key) ?? (ctx.mobile ? null : (shown[0] ?? null));
      const none = { value: null, error: null };
      const read = w ? gestureRead(w) : { kind: "none" as const };
      return [head, todoView({
        overview: overview.value, todo,
        sheet: w && (read.kind === "plan" || read.kind === "milestone") ? this.read(this.sheets.get(String(w.project))) : none,
        approvals: w && read.kind === "approval" ? this.read(this.approvals.get(String(w.project))) : none,
        element: w && read.kind === "element" ? this.read(this.element.get(cacheKey(w.project, read.list, read.item))) : none,
      }, place.project, place.key, ctx), null, []];
    }
    const got = this.read(this.sheets.get(String(place.id)));
    const sheet = got.value;
    if (!sheet) {
      const head = `<header class="page-head p2-fhead"><a class="p2-crumb" href="${route("projets")}" title="Tous les projets">${ico("chev-left", "sm")}<span>Projets</span></a><div class="ph-title"><h1>Projet</h1></div><div class="ph-actions"></div></header><nav class="p2-tabs"></nav>`;
      return [head, got.error ? errorBlock(got.error, "Impossible d'ouvrir ce projet") : loadingBlock(), null, []];
    }
    const tab = sheet.rights.detail ? place.tab : "vue";
    const rest = place.rest;
    const id = String(sheet.project.id);
    const head = sheetHead(sheet, tab, overview.value?.projects.find((x) => x.id === sheet.project.id)?.card?.led_by ?? "");
    let inner: string;
    if (tab === "objectifs") {
      if (rest[0] === "diagramme") {
        const d = this.read(this.diagram.get(id));
        inner = d.value ? diagramView(sheet, d.value, rest.slice(1), ctx) : d.error ? errorBlock(d.error) : loadingBlock();
      } else {
        const picked = findGoal(sheet, rest[0]);
        const wants = picked && sheet.rights.work !== false && (picked.mission || rest[1] === "rendus");
        const runs = wants && picked ? this.read(this.feed.get(cacheKey(id, "run", picked.o.id))) : { value: null, error: null };
        inner = objectivesView(sheet, rest, runs, ctx);
      }
    } else if (tab === "tickets") {
      const q = ticketsQuery(this.ui.tickets, this.ui.ticketQuery);
      const page = this.read(this.elements.get(cacheKey(id, "tickets", q.state, q.q)));
      const shown = (page.value?.items ?? []).filter((t) => this.ui.tickets !== "yours" || t.yours);
      const number = rest[0] && /^\d+$/.test(rest[0]) ? rest[0] : ctx.mobile ? "" : shown[0] ? String(shown[0].number) : "";
      const none = { value: null, error: null };
      const element = number ? this.read(this.element.get(cacheKey(id, "tickets", `#${number}`))) : none;
      // l'histoire de ses étapes se lit avec le ticket (le volet dit combien) ; le fil filtré sur lui, quand l'Historique est ouvert
      const story = { history: number ? this.read(this.history.get(cacheKey(id, `#${number}`))) : none, around: number && rest[1] === "historique" && sheet.rights.work !== false ? this.read(this.feed.get(cacheKey(id, "", "", number))) : none };
      inner = ticketsView(sheet, rest, page, element, story, ctx);
    } else if (tab === "activite") {
      const none = { value: null, error: null };
      const sub = rest[0] === "executions" ? "runs" : rest[0] === "carnet" ? "notes" : "feed";
      const key = cacheKey(id, this.ui.feedKind, this.ui.feedObjective || "");
      const runs = this.read(this.runs.get(id));
      const wanted = sub === "runs" ? rest[1] || (ctx.mobile ? "" : (runs.value?.items[0]?.id ?? "")) : "";
      inner = activityView(sheet, rest, {
        feed: sub === "feed" ? this.read(this.feed.get(key)) : none, more: this.feedMore.get(key) ?? [], cursor: this.feedNext.get(key) ?? null,
        days: sub === "feed" ? this.read(this.days.get(id)) : none, runs,
        run: wanted ? this.read(this.run.get(cacheKey(id, wanted))) : none,
        notes: sub === "notes" ? this.read(this.notes.get(cacheKey(id, this.ui.notebook || ""))) : none,
        totals: this.read(this.totals.get(cacheKey(id, ""))), filtered: sub === "feed" ? this.read(this.totals.get(cacheKey(id, this.ui.feedObjective || ""))) : none,
      }, ctx);
    } else if (tab === "dependances") inner = dependenciesView(sheet, overview.value, rest, ctx);
    else if (tab === "listes") {
      const lists = followLists(sheet);
      const list = lists.find((l) => l.name === rest[0]) ?? lists[0];
      inner = listsView(sheet, rest, list ? this.read(this.elements.get(cacheKey(id, list.name, "", ""))) : { value: null, error: null }, ctx);
    } else if (tab === "reglages") inner = settingsView(sheet, this.read(this.settings.get(id)), rest, {}, ctx);
    else if (tab === "code" || tab === "documentation") inner = pluggedTab(tab)?.render(sheet, rest, this) ?? "";
    else inner = overviewView(sheet, ctx);
    return [head, inner, sheet, rest];
  }

  /** Ce qui tient d'un dessin à l'autre : où chaque cadre a défilé, ce qui est saisi, où est le curseur. */
  private keep(body: HTMLElement): { scroll: Record<string, number>; typed: Map<string, string | boolean>; focus: [string, number] | null } {
    const scroll: Record<string, number> = {};
    for (const el of $$<HTMLElement>("[data-scroll]", body)) scroll[el.dataset.scroll ?? ""] = el.scrollTop;
    const typed = typedOf(body);
    const active = document.activeElement as HTMLInputElement | null;
    const sel = active && body.contains(active) ? selectorOf(active) : "";
    return { scroll, typed, focus: sel ? [sel, active?.selectionStart ?? 0] : null };
  }

  private restore(body: HTMLElement, kept: ReturnType<Projets["keep"]>): void {
    for (const el of $$<HTMLElement>("[data-scroll]", body)) {
      const y = kept.scroll[el.dataset.scroll ?? ""];
      if (y) el.scrollTop = y;
    }
    if (!this.dropTyped) putTyped(body, kept.typed);
    this.dropTyped = false;
    if (kept.focus) {
      const el = body.querySelector<HTMLInputElement>(kept.focus[0]);
      if (el) {
        el.focus();
        try {
          el.setSelectionRange(kept.focus[1], kept.focus[1]);
        } catch {
          // un champ sans curseur
        }
      }
    }
  }

  /** Après le dessin : les champs conditionnels, et le diagramme (sa piste mesurée, où il avait défilé). */
  private after(root: ParentNode): void {
    for (const form of $$<HTMLFormElement>("form[data-p2-form]", root)) conditions(form);
    for (const zone of $$<HTMLElement>(".p2-dz", root)) balance(zone);
    const gantt = $<HTMLElement>(".p2-gantt.temps", root);
    if (!gantt) return;
    const names = $<HTMLElement>(".p2-g-nom", gantt)?.offsetWidth ?? 0;
    const width = Math.max(0, gantt.clientWidth - names);
    if (width && Math.abs(width - this.ui.trackWidth) > 4) {
      this.ui.trackWidth = width;
      this.paint();
      return;
    }
    gantt.scrollLeft = this.ui.scrollX ?? 0;
  }

  private paintDrawer(keepTyped: boolean): void {
    if (!this.drawerMake) return;
    let root = document.getElementById("p2-drawer-root");
    if (!root) {
      root = document.createElement("div");
      root.id = "p2-drawer-root";
      document.body.appendChild(root);
    }
    const typed = keepTyped ? typedOf(root) : null;
    root.innerHTML = drawerMarkup(this.drawerMake());
    if (typed) putTyped(root, typed);
    this.after(root);
    if (!keepTyped) root.querySelector<HTMLElement>("input:not([type=radio]):not([type=checkbox]), textarea")?.focus();
  }

  // ── Les écouteurs ──────────────────────────────────────────────────

  private mount(): void {
    document.addEventListener("click", (e) => {
      const target = e.target as Element;
      const retry = target.closest?.("[data-screen='projets'] [data-retry]");
      if (retry) {
        this.changed();
        this.paint();
        return;
      }
      if (target.closest?.("[data-screen='projets'] [data-relogin]")) {
        location.reload();
        return;
      }
      const b = target.closest?.("[data-p2]") as HTMLElement | null;
      if (!b) return;
      const act = this.acts[b.dataset.p2 ?? ""] ?? pluggedTabs().map((t) => t.acts?.[b.dataset.p2 ?? ""]).find(Boolean);
      if (!act) return;
      if (b.tagName !== "A" || !b.dataset.va) e.preventDefault();
      void act(b.dataset, b, this);
    });
    document.addEventListener("submit", (e) => {
      const form = (e.target as Element).closest?.("[data-p2-form]") as HTMLFormElement | null;
      if (!form) return;
      e.preventDefault();
      const name = form.dataset.p2Form ?? "";
      const next = this.forms[name] ?? pluggedTabs().map((t) => t.forms?.[name]).find(Boolean);
      if (next) void next(formValues(form), form.dataset, form, this);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") this.closeDrawer();
    });
    addEventListener("hashchange", () => this.closeDrawer());
    document.addEventListener("input", (e) => {
      const el = e.target as HTMLInputElement;
      if (el.matches?.(".p2-manque")) el.classList.remove("p2-manque");
      const form = el.closest?.("form[data-p2-form]") as HTMLFormElement | null;
      if (form) conditions(form);
      if (el.dataset?.p2Saisie === "tickets") {
        this.ui.ticketQuery = el.value;
        window.clearTimeout(this.queryTimer);
        this.queryTimer = window.setTimeout(() => this.paint(), 280);
      }
    });
    document.addEventListener("change", (e) => {
      const el = e.target as HTMLInputElement;
      const form = el.closest?.("form[data-p2-form]") as HTMLFormElement | null;
      if (form) conditions(form);
      if (el.dataset?.p2Change === "linkDirect") {
        void this.send(Number(el.dataset.p), linkRequest(el.checked ? "direct_on" : "direct_off", Number(el.dataset.c)), `link:${el.dataset.p}`);
      }
    });
    document.addEventListener("scroll", (e) => {
      const el = e.target as HTMLElement;
      if (el.matches?.(".p2-gantt.temps")) this.ui.scrollX = el.scrollLeft;
    }, true);
  }

  private sheetOf(id: string | undefined): Sheet | null {
    return this.sheets.get(String(id ?? "")).value;
  }

  /** Les gestes de l'écran : `data-p2="<nom>"`. */
  private readonly acts: Record<string, Act> = {
    infos: () => {
      this.ui.infos = !this.ui.infos;
      this.paint();
    },
    volet: (_d, b) => {
      this.ui.infos = false;
      if (b.getAttribute("href") === location.hash) this.paint();
    },
    drawerClose: () => this.closeDrawer(),
    todoFilter: (d) => {
      this.ui.todoProject = Number(d.c);
      if (d.va) return;
      if (this.shell.ctx?.item) this.go(route("a-faire"));
      else this.paint();
    },
    todoMore: async () => {
      const total = this.overview.value?.todo_total ?? 0;
      const size = this.overview.value?.todo.length || 25;
      try {
        const page = await fetchTodo(Math.floor(this.todo().length / size) + 1);
        const known = new Set(this.todo().map((w) => `${w.project}/${waitingKey(w)}`));
        this.todoMore.push(...page.items.filter((w) => !known.has(`${w.project}/${waitingKey(w)}`)));
        if (!page.items.length && total) toast("Il n'y a rien de plus.", { ico: "info" });
        this.paint();
      } catch (err) {
        this.refused(err, "top");
      }
    },
    todo: async (d, b) => {
      const w = this.todo().find((x) => x.project === Number(d.p) && waitingKey(x) === d.k);
      if (!w) return;
      const where = `todo:${w.project}:${waitingKey(w)}`;
      const read = gestureRead(w);
      const action = d.c ?? "";
      let typed = "";
      if (action === "answer") {
        const field = b.closest(".p2-answer")?.querySelector<HTMLTextAreaElement>("[data-p2-champ]");
        typed = field?.value.trim() ?? "";
        if (!typed) {
          field?.classList.add("p2-manque");
          field?.focus();
          return;
        }
      } else if (d.ask) {
        const said = await this.ask({ title: b.textContent?.trim() || w.gesture.label, label: d.ask, ok: b.textContent?.trim() || "Envoyer", required: !/facultatif/.test(d.ask), danger: action === "refuse" || action === "dismiss" });
        if (said === null) return;
        typed = said;
      }
      const element = read.kind === "element" ? this.element.get(cacheKey(w.project, read.list, read.item)).value : null;
      const digest = read.kind === "approval" ? this.approvals.get(String(w.project)).value?.items.find((a) => a.id === read.id)?.digest : undefined;
      const request = action === "answer" && element && w.gesture.route !== "element/noter" ? noteRequest(element, typed) : gestureRequest(w, action === "answer" || action === "go" ? "" : action, typed, { digest, plan: element?.plan });
      void this.send(w.project, request, where);
    },
    projectNew: () => {
      const make = (): DrawerOpts => {
        const got = this.fresh.value;
        const errors = fieldErrorsAt(this.ui, "new");
        return {
          name: "projectNew", key: "new", title: "Nouveau projet", sub: "Dis-lui ce que tu veux : elle pose ses questions, puis te propose un plan.", submit: "Le lui confier", error: refusalAt(this.ui, "new") || (got && !got.can ? got.why : ""),
          bodyHtml: got ? got.fields.map((f) => served(f, {}, errors)).join("") : loadingBlock(),
        };
      };
      this.ui.refusal = null;
      this.drawer(make);
      if (!this.fresh.value) void this.fresh.load().then(() => this.paintDrawer(false));
    },
    projectMenu: (d, b) => {
      const id = Number(d.p);
      openMenu(b, [
        { label: "Modifier le projet", icon: "settings", action: () => this.go(sheetRoute(id, "reglages")) },
        "sep",
        { label: "Archiver", icon: "archive", action: () => void this.acts.projectArchive({ p: String(id) }, b, this) },
      ]);
    },
    projectArchive: async (d) => {
      const sheet = this.sheetOf(d.p);
      if (!(await this.confirm({ title: "Archiver le projet ?", text: `« ${sheet?.project.title ?? "Ce projet"} » ne travaillera plus et ne te demandera plus rien. Rien n'est effacé : il se désarchive depuis la grille des projets.`, ok: "Archiver" }))) return;
      void this.send(Number(d.p), { route: "archiver", body: {} }, sheet ? `project:${d.p}` : "top", () => this.go(route("projets")));
    },
    projectRestore: (d) => void this.send(Number(d.p), { route: "restaurer", body: {} }, "top", () => this.go(sheetRoute(Number(d.p)))),
    instruct: async (d) => {
      const text = await this.ask({ title: "Donner une consigne", label: "Ta consigne (elle la lira avant son prochain passage)", ok: "Donner la consigne", required: true });
      if (text !== null) void this.send(Number(d.p), pilotRequest("instruct", text), "top");
    },
    runNow: (d) => void this.send(Number(d.p), pilotRequest("now", "", Number(d.o) || 0), "top"),
    pause: (d) => void this.send(Number(d.p), pilotRequest("pause"), "top"),
    resume: (d) => void this.send(Number(d.p), pilotRequest("resume"), "top"),
    goalFilter: (d) => {
      this.ui.objectives = this.ui.objectives === d.c ? "" : (d.c as UiState["objectives"]); // un filtre se retire en le touchant de nouveau
      this.paint();
    },
    goalAdd: (d) => {
      const sheet = this.sheetOf(d.p);
      if (!sheet) return;
      this.ui.refusal = null;
      const key = `goal-new:${d.p}`;
      this.drawer(() => ({ name: "goal", key, data: { p: Number(d.p) }, title: "Ajouter un objectif", sub: "Un objectif ponctuel, ou une mission qui revient.", submit: "Ajouter", error: refusalAt(this.ui, key), bodyHtml: goalDrawerBody(sheet, fieldErrorsAt(this.ui, key)) }));
    },
    goalStatus: async (d) => {
      const sheet = this.sheetOf(d.p);
      const g = sheet ? findGoal(sheet, `${d.m ? "m" : "o"}${d.c}`) : null;
      if (!sheet || !g) return;
      if (d.s === "dropped" && !(await this.confirm({ title: g.mission ? "Retirer la mission ?" : "Retirer l'objectif ?", text: `« ${g.o.text} » sort du projet : elle n'y travaillera plus. ${g.mission ? "Ses passages restent dans l'activité." : "Sa branche, sa pull request et ses comptes rendus restent là où ils sont."}`, ok: "Retirer", danger: true }))) return;
      void this.send(Number(d.p), objectiveStatusRequest(g.o.id, d.s ?? ""), `goal-act:${d.p}:${d.c}`, () => {
        if (d.s === "dropped") this.go(sheetRoute(Number(d.p), "objectifs"));
      });
    },
    milestoneAdd: (d) => this.milestoneDrawer(d, false),
    milestoneEdit: (d) => this.milestoneDrawer(d, true),
    milestoneDrop: async (d) => {
      const sheet = this.sheetOf(d.p);
      const m = sheet?.objectives?.find((o) => o.id === Number(d.o))?.milestones.find((x) => x.id === Number(d.c));
      if (!m) return;
      const reason = await this.ask({ title: "Retirer le jalon ?", label: `« ${m.text} » reste lisible, retiré. Pourquoi (facultatif)`, ok: "Retirer", danger: true });
      if (reason !== null) void this.send(Number(d.p), { route: "jalon/retirer", body: { objective: Number(d.o), milestone: m.id, ...(reason ? { reason } : {}) } }, `goal-act:${d.p}:${d.o}`);
    },
    checkpoint: async (d) => {
      let reason = "";
      if (d.v === "refuse") {
        const said = await this.ask({ title: "Refuser le jalon", label: "Ce qui manque", ok: "Refuser", required: true, danger: true });
        if (said === null) return;
        reason = said;
      }
      void this.send(Number(d.p), checkpointRequest(Number(d.o), Number(d.c), d.v ?? "", reason), `goal-act:${d.p}:${d.o}`);
    },
    ganttFold: (d) => {
      const id = Number(d.c);
      if (this.ui.folded.has(id)) this.ui.folded.delete(id);
      else this.ui.folded.add(id);
      this.paint();
    },
    ganttZoom: (d) => {
      this.ui.zoom = d.c === "weeks" ? "weeks" : "days";
      this.ui.scrollX = null;
      this.paint();
    },
    ganttPick: (_d, b) => {
      this.openInfos = true;
      if (b.getAttribute("href") === location.hash) {
        this.ui.infos = isMobile();
        this.paint();
      }
    },
    ticketFilter: (d) => {
      this.ui.tickets = d.c as UiState["tickets"];
      this.paint();
    },
    ticketNew: (d) => {
      const sheet = this.sheetOf(d.p);
      if (!sheet) return;
      this.ui.refusal = null;
      const key = `ticket-new:${d.p}`;
      this.drawer(() => ({ name: "ticket", key, data: { p: Number(d.p) }, title: "Nouveau ticket", sub: sheet.project.title, submit: "Ouvrir le ticket", error: refusalAt(this.ui, key), bodyHtml: ticketFields(ticketList(sheet), null, fieldErrorsAt(this.ui, key), sheet.rights.ticket_born) }));
    },
    settle: async (d, b) => {
      const e = this.element.get(cacheKey(d.p, "tickets", `#${d.c}`)).value;
      if (!e) return;
      let reason = "";
      if (d.ask) {
        const said = await this.ask({ title: `${b.textContent?.trim()} — #${e.number}`, label: d.ask, ok: b.textContent?.trim() || "Envoyer", required: !/facultatif/.test(d.ask), danger: true });
        if (said === null) return;
        reason = said;
      }
      void this.send(Number(d.p), settleRequest(e, d.v ?? "", reason), `ticket:${d.p}:${d.c}`);
    },
    note: (d, b) => {
      const e = this.element.get(cacheKey(d.p, "tickets", `#${d.c}`)).value;
      const field = b.closest(".p2-note")?.querySelector<HTMLTextAreaElement>("[data-p2-champ]");
      const text = field?.value.trim() ?? "";
      if (!e || !text) {
        field?.classList.add("p2-manque");
        field?.focus();
        return;
      }
      void this.send(Number(d.p), noteRequest(e, text), `ticket:${d.p}:${d.c}`);
    },
    feedKind: (d) => {
      this.ui.feedKind = this.ui.feedKind === d.c ? "" : (d.c ?? "");
      this.paint();
    },
    feedObjective: (d, b) => {
      const sheet = this.sheetOf(d.p);
      const pick = (id: number): void => {
        this.ui.feedObjective = id;
        this.paint();
      };
      openMenu(b, [{ label: "Tous les objectifs", checked: !this.ui.feedObjective, action: () => pick(0) }, "sep",
        ...(sheet?.objectives ?? []).map((o) => ({ label: `n° ${o.id} · ${o.text}`, icon: "p2-target" as const, checked: this.ui.feedObjective === o.id, action: () => pick(o.id) }))], { align: "left" });
    },
    feedMore: async (d) => {
      const sc = this.shell.ctx;
      const place = sc ? parsePlace(sc.tab, sc.item) : null;
      if (!place || place.kind !== "sheet") return;
      const key = cacheKey(place.id, this.ui.feedKind, this.ui.feedObjective || "");
      const known = this.feedMore.get(key) ?? [];
      try {
        const page = await fetchActivity(place.id, { kind: this.ui.feedKind || undefined, objective: this.ui.feedObjective || undefined, before: Number(d.c) });
        this.feedMore.set(key, [...known, ...page.items]);
        this.feedNext.set(key, page.next);
        this.paint();
      } catch (err) {
        this.refused(err, "top");
      }
    },
    notebookFilter: (d) => {
      this.ui.notebook = Number(d.c) || 0;
      this.paint();
    },
    linkAdd: (d) => {
      const sheet = this.sheetOf(d.p);
      if (!sheet?.links) return;
      this.ui.refusal = null;
      const key = `link-new:${d.p}`;
      this.drawer(() => ({ name: "link", key, data: { p: Number(d.p) }, title: "Ajouter une dépendance", sub: `Ce que « ${sheet.project.title} » se met à lire.`, submit: linkCandidates(sheet.links!).length ? "Ajouter" : "", error: refusalAt(this.ui, key), bodyHtml: linkDrawerBody(sheet, fieldErrorsAt(this.ui, key)) }));
    },
    linkWhy: async (d) => {
      const sheet = this.sheetOf(d.p);
      const x = sheet?.links?.reads.find((r) => r.project === Number(d.c));
      if (!sheet || !x) return;
      const why = await this.ask({ title: "Le mot du lien", label: `Pourquoi « ${sheet.project.title} » lit « ${x.title} »`, ok: "Enregistrer", required: true });
      if (why !== null) void this.send(Number(d.p), linkWhyRequest(Number(d.c), why), `link:${d.p}`);
    },
    // « Lui demander quelque chose » : un ticket qu'elle ouvre elle-même chez un projet lu (`ask_here` : la garde, dite d'avance)
    askHere: (d, b) => {
      const sheet = this.sheetOf(d.p);
      const able = (sheet?.links?.reads ?? []).filter((r) => r.ask_here?.can && r.ask_here.project !== null);
      const open = (target: number): void => {
        const x = able.find((r) => r.ask_here?.project === target);
        if (!sheet || !x) return;
        this.ui.refusal = null;
        const key = `ask:${d.p}:${target}`;
        this.drawer(() => ({ name: "ask", key, data: { p: Number(d.p), c: target }, title: "Lui demander quelque chose", sub: `Tu ouvres un ticket chez « ${x.title} », en ton nom : c'est le tien, pas une demande de « ${sheet.project.title} ».`, submit: "Ouvrir le ticket",
          error: refusalAt(this.ui, key), bodyHtml: askDrawerBody(x.ask_here?.born ?? "", fieldErrorsAt(this.ui, key)) }));
      };
      if (d.c) open(Number(d.c));
      else if (able.length === 1) open(able[0].ask_here!.project as number);
      else if (able.length) openMenu(b, [{ header: "À quel projet" }, ...able.map((r) => ({ label: r.title, icon: "flag" as const, action: () => open(r.ask_here!.project as number) }))]);
    },
    itemAdd: (d) => {
      const sheet = this.sheetOf(d.p);
      const list = sheet ? followLists(sheet).find((l) => l.name === d.l) : null;
      if (!list) return;
      this.ui.refusal = null;
      const key = `item-new:${d.p}:${list.name}`;
      this.drawer(() => ({ name: "item", key, data: { p: Number(d.p), l: list.name }, title: `Ajouter à « ${list.title} »`, submit: "Ajouter", error: refusalAt(this.ui, key), bodyHtml: itemDrawerBody(list, fieldErrorsAt(this.ui, key)) }));
    },
    itemAssign: (d, b) => {
      const sheet = this.sheetOf(d.p);
      const list = sheet ? followLists(sheet).find((l) => l.name === d.l) : null;
      const e = this.elements.get(cacheKey(d.p, d.l, "", "")).value?.items.find((x) => x.key === d.c);
      if (!list || !e) return;
      openMenu(b, [{ header: "À la charge de" }, ...(list.actors ?? []).map((a) => ({ label: a.label, checked: e.actor === a.code, action: () => void this.send(Number(d.p), assignRequest(e, a.code), `list:${d.p}`) }))]);
    },
    linkRemove: async (d) => {
      const sheet = this.sheetOf(d.p);
      const x = sheet?.links?.reads.find((r) => r.project === Number(d.c));
      if (!x) return;
      if (!(await this.confirm({ title: "Retirer la dépendance ?", text: `« ${sheet?.project.title} » ne lira plus « ${x.title} ».`, ok: "Retirer", danger: true }))) return;
      void this.send(Number(d.p), linkRequest("remove", Number(d.c)), `link:${d.p}`, () => this.go(sheetRoute(Number(d.p), "dependances")));
    },
    listView: (d) => {
      this.ui.listView = d.c === "table" ? "table" : "columns";
      this.paint();
    },
    itemStatus: (d, b) => {
      const sheet = this.sheetOf(d.p);
      const list = sheet ? followLists(sheet).find((l) => l.name === d.l) : null;
      const e = this.elements.get(cacheKey(d.p, d.l, "", "")).value?.items.find((x) => x.key === d.c);
      if (!list || !e) return;
      openMenu(b, [{ header: e.title }, ...[...list.open, ...list.closed].map((s) => ({ label: s.label, checked: e.status === s.code, action: () => void this.send(Number(d.p), statusRequest(e, s.code), `list:${d.p}`) }))]);
    },
  };

  private milestoneDrawer(d: DOMStringMap, edit: boolean): void {
    const sheet = this.sheetOf(d.p);
    const o = sheet?.objectives?.find((x) => x.id === Number(d.o));
    if (!sheet || !o) return;
    const m = edit ? (o.milestones.find((x) => x.id === Number(d.c)) ?? null) : null;
    this.ui.refusal = null;
    const key = `milestone:${d.p}:${o.id}:${m?.id ?? "new"}`;
    this.drawer(() => ({ name: "milestone", key, data: { p: Number(d.p), o: o.id, c: m?.id ?? "" }, title: m ? "Modifier le jalon" : "Ajouter un jalon", sub: `Objectif n° ${o.id} · ${o.text}`, submit: m ? "Enregistrer" : "Ajouter",
      error: refusalAt(this.ui, key), bodyHtml: milestoneDrawerBody(sheet, m, fieldErrorsAt(this.ui, key)) }));
  }

  /** Les suites des formulaires : `data-p2-form="<nom>"`. */
  private readonly forms: Record<string, FormAct> = {
    projectNew: async (values) => {
      if (this.ui.busy) return;
      this.ui.busy = "new";
      try {
        const r = await createProject(Object.fromEntries(Object.entries(values).filter(([, v]) => v !== "" && v !== false)), newNonce());
        this.ui.busy = "";
        this.ui.refusal = null;
        if (r.message) toast(r.message, { mika: true });
        this.changed();
        this.closeDrawer();
        if (r.project) this.go(sheetRoute(r.project));
        else this.paint();
      } catch (err) {
        this.ui.busy = "";
        this.refused(err, "new");
      }
    },
    goal: (values, d) => {
      const sheet = this.sheetOf(d.p);
      if (!sheet) return;
      const id = Number(d.c) || 0;
      const g = id ? findGoal(sheet, `${d.m === "1" ? "m" : "o"}${id}`) : null;
      const before: Values | null = !g ? null : g.mission
        ? { kind: "constant", text: g.o.text, cadence_hours: g.o.cadence_hours, on: g.o.on.map((t) => t.key), only_on_event: g.o.only_on_event, each_pass: g.o.each_pass }
        : { kind: "once", text: g.o.text, done_when: g.o.done_when };
      const where = g ? `goal:${d.p}:${d.m === "1" ? "m" : "o"}${id}` : `goal-new:${d.p}`;
      void this.send(Number(d.p), objectiveRequest(values, before, id), where, (r) => {
        this.closeDrawer();
        this.ui.objectives = "";
        const mission = g ? g.mission : values.kind === "constant";
        const key = g ? id : r.objective;
        this.go(key ? sheetRoute(Number(d.p), "objectifs", `${mission ? "m" : "o"}${key}`) : sheetRoute(Number(d.p), "objectifs"));
      });
    },
    milestone: (values, d) => {
      const sheet = this.sheetOf(d.p);
      const o = sheet?.objectives?.find((x) => x.id === Number(d.o));
      const m = o?.milestones.find((x) => x.id === Number(d.c));
      // ce qui était servi : sa commande n'est servie qu'avec le droit sur ses fichiers ; sans lui, elle ne part que si on la saisit
      const before: Values | null = m ? { text: m.text, check: m.check, command: m.command ?? "", item_list: m.item_list ?? "", item: m.item ?? "", item_status: m.item_status ?? "" } : null;
      const request = milestoneRequest(Number(d.o), values, before, m?.id ?? 0);
      if (m && values.reason) request.body.reason = String(values.reason).trim();
      void this.send(Number(d.p), request, `milestone:${d.p}:${d.o}:${m?.id ?? "new"}`, () => this.closeDrawer());
    },
    ticket: (values, d) => {
      const e = d.c ? this.element.get(cacheKey(d.p, "tickets", `#${d.c}`)).value : null;
      const before: Values | null = e ? { title: e.title, text: e.body, kind: e.kind, priority: e.priority } : null;
      void this.send(Number(d.p), ticketRequest(values, before, e ? e.handle : ""), e ? `ticket:${d.p}:${d.c}` : `ticket-new:${d.p}`, (r) => {
        this.closeDrawer();
        if (e) this.go(sheetRoute(Number(d.p), "tickets", e.number, "description"));
        else if (r.number) {
          this.ui.tickets = "open";
          this.ui.ticketQuery = "";
          this.go(sheetRoute(Number(d.p), "tickets", r.number));
        }
      });
    },
    item: (values, d) => {
      const list = String(d.l ?? "");
      void this.send(Number(d.p), itemAddRequest(list, values), `item-new:${d.p}:${list}`, () => this.closeDrawer());
    },
    // le ticket s'ouvre chez le projet lu (`d.c`), par la route que `ask_here` nomme ; puis il revient dans les demandes du lien
    ask: (values, d) => {
      const target = Number(d.c);
      const here = this.sheetOf(d.p)?.links?.reads.find((r) => r.ask_here?.project === target)?.ask_here;
      if (!here?.can || !here.route) return;
      void this.send(target, { route: here.route, body: ticketRequest(values, null).body }, `ask:${d.p}:${target}`, () => {
        this.closeDrawer();
        this.go(sheetRoute(Number(d.p), "dependances", `lit-${target}`));
      });
    },
    settings: (values, d) => {
      const section = this.settings.get(String(d.p)).value?.sections.find((s) => s.name === d.s);
      if (section) void this.send(Number(d.p), settingsRequest(section.name, section.fields, values), `settings:${d.p}:${section.name}`);
    },
    link: (values, d) => {
      const project = Number(values.project);
      if (project) void this.send(Number(d.p), linkRequest("add", project, String(values.why ?? "")), `link-new:${d.p}`, () => {
        this.closeDrawer();
        this.go(sheetRoute(Number(d.p), "dependances", `lit-${project}`));
      });
    },
  };
}

/** De quoi retrouver le champ qui avait la main après un dessin. */
function selectorOf(el: HTMLElement): string {
  if (el.dataset.p2Saisie) return `[data-p2-saisie="${el.dataset.p2Saisie}"]`;
  if (el.dataset.keep) return `[data-keep="${el.dataset.keep}"]`;
  const form = el.closest<HTMLElement>("form[data-form-key]");
  const name = el.getAttribute("name");
  return form && name && (el as HTMLInputElement).type !== "radio" && (el as HTMLInputElement).type !== "checkbox" ? `form[data-form-key="${form.dataset.formKey}"] [name="${name}"]` : "";
}

/** Ce qui est saisi : les zones gardées (`data-keep`) et les champs des formulaires, par la clé de leur formulaire. */
function typedOf(root: ParentNode): Map<string, string | boolean> {
  const out = new Map<string, string | boolean>();
  for (const el of $$<HTMLTextAreaElement>("[data-keep]", root)) out.set(`keep:${el.dataset.keep}`, el.value);
  for (const form of $$<HTMLFormElement>("form[data-form-key]", root)) {
    for (const el of Array.from(form.elements) as HTMLInputElement[]) {
      if (!el.name) continue;
      const box = el.type === "checkbox" || el.type === "radio";
      out.set(`${form.dataset.formKey}/${el.name}${box ? `=${el.value}` : ""}`, box ? el.checked : el.value);
    }
  }
  return out;
}

function putTyped(root: ParentNode, typed: Map<string, string | boolean>): void {
  for (const el of $$<HTMLTextAreaElement>("[data-keep]", root)) {
    const v = typed.get(`keep:${el.dataset.keep}`);
    if (typeof v === "string") el.value = v;
  }
  for (const form of $$<HTMLFormElement>("form[data-form-key]", root)) {
    for (const el of Array.from(form.elements) as HTMLInputElement[]) {
      if (!el.name) continue;
      const box = el.type === "checkbox" || el.type === "radio";
      const v = typed.get(`${form.dataset.formKey}/${el.name}${box ? `=${el.value}` : ""}`);
      if (v === undefined) continue;
      if (box) el.checked = v === true;
      else el.value = String(v);
    }
  }
}

/** Les champs conditionnels d'un formulaire : ceux que le serveur réserve à certaines valeurs d'un autre (`data-only`),
 *  et ceux d'un jalon selon la façon de le vérifier (`data-si="champ=valeur"`). */
function conditions(form: HTMLFormElement): void {
  const values = formValues(form);
  for (const el of $$<HTMLElement>("[data-only]", form)) {
    let only: { field: string; values: unknown[] }[] = [];
    try {
      only = JSON.parse(el.dataset.only ?? "[]") as typeof only;
    } catch {
      only = [];
    }
    el.hidden = !only.every((o) => o.values.map(String).includes(String(values[o.field] ?? "")));
  }
  for (const el of $$<HTMLElement>("[data-si]", form)) {
    const [field, value] = (el.dataset.si ?? "").split("=");
    el.hidden = String(values[field] ?? "") !== value;
  }
}

/**
 * La hauteur d'un détail : quand le contenu est court (moins de la moitié de son cadre) alors que le panneau latéral
 * déborde du sien, le panneau prend deux colonnes — la place vide sert, rien ne défile pour rien.
 */
function balance(zone: HTMLElement): void {
  const frame = zone.querySelector<HTMLElement>(":scope > .p2-main > .p2-vbody");
  const content = frame?.querySelector<HTMLElement>(":scope > .p2-c");
  const side = zone.querySelector<HTMLElement>(":scope > .p2-side");
  zone.classList.remove("large-cote");
  if (!frame || !content || !side || !content.lastElementChild) return;
  const used = content.lastElementChild.getBoundingClientRect().bottom - content.getBoundingClientRect().top;
  if (used < frame.clientHeight * 0.5 && side.scrollHeight > side.clientHeight + 12) zone.classList.add("large-cote");
}

export function projetsScreen(shell: Shell): ScreenDef {
  return new Projets(shell).screen();
}
