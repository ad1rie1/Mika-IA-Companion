/**
 * L'écran « Agenda » (ADR 0309, lot 6) : tous ses agendas en un seul écran — celui du système, ceux qu'elle branche
 * (Google, Outlook, CalDAV, un abonnement), ceux qu'on lui partage, et « L'agenda de Mika », sa mémoire montrée comme
 * un agenda. La forme : la maquette validée (`maquette/ecrans/agenda.js`) ; les données : `protocole-moi.md` § 13 ; le
 * dessin : `view.ts` ; créer et modifier : `form.ts` ; partager : `share.ts`.
 *
 * Adresses : `#agenda/<vue>` (jour, semaine, mois, planning), `#agenda/evenement/<n°>[/<occurrence>]`,
 * `#agenda/proposition/<n°>` (ce que Mika propose), `#agenda/memoire/<réf>` (une date de sa mémoire),
 * `#agenda/invitations`, `#agenda/nouveau`, `#agenda/modifier/<n°>[/<occurrence>]`, `#agenda/modifier/proposition/<n°>`,
 * `#agenda/partager/<agenda>`. Décocher un agenda à gauche ne change que l'affichage (retenu par ce navigateur) ; le
 * masquer (Paramètres › Agendas) coupe aussi Mika.
 *
 * Rien ne se relit à intervalles : le direct (ADR 0308) dit `agenda` — ses agendas, la période affichée, l'événement
 * ouvert, ses invitations et ce que Mika propose se relisent ; l'écran au second plan, ou l'onglet caché, à son retour.
 * L'agenda de Mika n'est pas poussé : il se relit à l'ouverture de l'écran.
 */
import type { AgendaCalendar, AgendaItem, Calendars, Period, Proposal, Scope } from "../../api/agenda";
import {
  acceptProposal,
  createEvent,
  deleteEvent,
  editEvent,
  editProposal,
  fetchEvent,
  fetchInvitations,
  fetchPeriod,
  fetchProposals,
  refuseProposal,
  remindEvent,
  respondEvent,
  saveCalendar,
  searchAgenda,
  type MikaReminder,
} from "../../api/agenda";
import { ApiError } from "../../api/moi";
import { fetchPeople } from "../../api/shares";
import { Freshness, live, OneAtATime, pageShown } from "../../live/live";
import { Cached, CachedMap, confirmModal, failureText, newNonce, toastFailure } from "../../shared/kit";
import * as store from "../../shared/store";
import { countOf, refreshCounts } from "../../shell/counts";
import { $, h, isMobile, on } from "../../shell/dom";
import { closeMenu, closeModal, modalOpen, openMenu, toast, type MenuItem } from "../../shell/float";
import { ico } from "../../shell/icons";
import type { PaletteEntry } from "../../shell/palette";
import type { ScreenContext, ScreenDef, Shell } from "../../shell/shell";
import { addMonths, bounds, cap, hm, localOf, offsetWords, shortDay, step, VIEWS, type View } from "./dates";
import { hiddenHere, onShownChange, savedView, saveView, setShown, showOnly } from "./display";
import { askAnswer, askScope, openEventForm, type FormMode, type FormSpec, type FormValues } from "./form";
import {
  colorOf,
  eventKey,
  ID,
  mikaReminderWords,
  occOfHer,
  occOfItem,
  occOfProposal,
  PALETTE,
  providerShort,
  sortOccs,
  targetKey,
  withShownNames,
  targetOf,
  whenWords,
  type Occ,
  type Target,
} from "./model";
import { openShare } from "./share";
import {
  calendarGroups,
  eventFiche,
  gridView,
  herFiche,
  HH,
  invitationsPanel,
  missingFiche,
  miniMonth,
  monthView,
  planningView,
  proposalFiche,
  remindChoices,
  searchView,
  side,
  strip,
  titleBar,
  type AgendaView,
} from "./view";

const SEARCH_DELAY_MS = 300;

export interface AgendaHooks {
  /** Ouvrir le chat avec une phrase préremplie (« Demander à Mika », « Lui en parler »). */
  ask: (text: string) => void;
}

interface RouteState {
  view: View | null;
  /** Ce que le volet montre. */
  target: Target | null;
  invitations: boolean;
  /** La fenêtre qui s'ouvre. */
  modal: "nouveau" | "modifier" | "partager" | null;
  /** Ce qu'elle vise (l'occurrence à modifier, l'agenda à partager). */
  rest: string[];
}

function parse(item: string | null): RouteState {
  const parts = (item ?? "").split("/").filter((x, i) => x || i === 0);
  const head = parts[0] ?? "";
  const out: RouteState = { view: null, target: null, invitations: false, modal: null, rest: parts.slice(1) };
  if (VIEWS.some(([k]) => k === head)) out.view = head as View;
  else if (head === "invitations") out.invitations = true;
  else if (head === "nouveau" || head === "modifier" || head === "partager") out.modal = head;
  else out.target = targetOf(parts);
  return out;
}

class AgendaScreen {
  private body: HTMLElement | null = null;
  private ctx: ScreenContext | null = null;
  private view: View;
  private date = "";
  private miniMonth: string | null = null;
  private mobileMonth = false;
  private q = "";
  private searching = false;
  private found: { q: string; occs: Occ[]; more: boolean; error: string; unchecked?: boolean } | null = null;
  private searchSeq = 0;
  private searchTimer = 0;
  /** La route d'avant : une autre route recentre la vue sur ce qu'elle ouvre. */
  private lastRoute = "";
  /** La fenêtre ouverte par une route (elle ne se rouvre pas à chaque dessin). */
  private modalFor = "";
  /** Une écriture en cours (la fenêtre fermée pendant qu'elle part ne ramène pas la route). */
  private saving = false;
  /** La route ouvre quelque chose qui n'était pas encore lu : la vue s'y recentrera une fois lu. */
  private recenterPending = false;
  private readonly periods = new CachedMap<Period>((key) => {
    const [start, end, cals] = key.split("|");
    return fetchPeriod(start, end, cals ? cals.split(",") : []);
  }, 20_000);
  private readonly events = new CachedMap<AgendaItem>((key) => {
    const [event, occurrence] = key.split("|");
    return fetchEvent(Number(event), occurrence ?? "");
  }, 15_000);
  private readonly invitations = new Cached(() => fetchInvitations(), 20_000);
  private readonly proposals = new Cached(() => fetchProposals(), 20_000);
  private readonly people = new Cached(() => fetchPeople(), 60_000);
  /** Le direct : ce que l'écran montre, relu une fois à la fois ; caché, à son retour. */
  private readonly reading = new OneAtATime(() => this.reread());
  private readonly fresh = new Freshness(() => this.open() && pageShown(), () => void this.reading.run());

  constructor(
    private readonly shell: Shell,
    private readonly hooks: AgendaHooks,
  ) {
    this.view = savedView(isMobile() ? "planning" : "semaine");
    // un autre écran (Paramètres › Agendas) coche ou décoche un agenda : la vue suit
    onShownChange(() => {
      if (this.open()) this.paint();
    });
    live.onChange("agenda", () => {
      this.invalidate();
      this.fresh.touch(() => void this.reading.run());
    });
  }

  def(): ScreenDef {
    return {
      id: ID,
      title: "Agenda",
      icon: "agenda",
      actions: (ctx) => this.actions(ctx),
      mount: (section) => this.mount(section),
      render: (body, ctx) => this.render(body, ctx),
      search: () => this.searchEntries(),
      count: () => countOf("agenda"),
    };
  }

  // ── les lectures ───────────────────────────────────────────────────

  private open(): boolean {
    return this.shell.ctx?.screen === ID && !!this.body?.isConnected;
  }

  private invalidate(): void {
    store.agendaCalendars.invalidate();
    this.periods.invalidate();
    this.events.invalidate();
    this.invitations.invalidate();
    this.proposals.invalidate();
  }

  private get cals(): Calendars | null {
    return store.agendaCalendars.value;
  }

  private zone(): string {
    return this.cals?.zone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  }

  private now(): { today: string; minute: number } {
    const { day, minute } = localOf(Date.now(), this.zone());
    return { today: day, minute };
  }

  /** Les agendas qu'on lit : tous ceux qu'elle voit (sauf les masqués), et celui de Mika. */
  private readKeys(): string[] {
    const list = (this.cals?.calendars ?? []).filter((c) => !c.hidden).map((c) => c.key);
    return list.includes("mika") ? list : [...list, "mika"];
  }

  private periodKey(): string | null {
    if (!this.cals || !this.date) return null;
    const [first, after] = bounds(this.view, this.date);
    const last = shortBefore(after);
    return `${first}|${last}|${this.readKeys().join(",")}`;
  }

  private async load(force = false): Promise<void> {
    const before = this.stamp();
    await store.agendaCalendars.load(force);
    if (!this.date) this.date = this.now().today;
    const key = this.periodKey();
    const target = parse(this.ctx?.item ?? null).target;
    await Promise.all([
      key ? this.periods.get(key).load(force) : Promise.resolve(null),
      this.invitations.load(force),
      this.proposals.load(force),
      store.agendaAccounts.load(force),
      this.people.load(),
      store.me.load(),
      target?.kind === "event" ? this.events.get(`${target.event}|${target.occurrence}`).load(force) : Promise.resolve(null),
    ]);
    if (this.recenterPending && this.ctx) {
      // ce que la route ouvre est lu maintenant : la vue va à son jour (sa semaine, son mois), et la relit
      const was = this.periodKey();
      this.recenter(parse(this.ctx.item));
      if (!this.recenterPending && this.periodKey() !== was) {
        await this.load(force);
        return;
      }
    }
    if (this.open() && this.stamp() !== before) this.paint();
    // la fenêtre qu'une route ouvre attendait peut-être ces lectures (une route venue d'un autre écran, le direct)
    this.openModalRoute();
  }

  private stamp(): string {
    const key = this.periodKey();
    const target = parse(this.ctx?.item ?? null).target;
    return [store.agendaCalendars.version, key, key ? this.periods.get(key).version : 0, this.invitations.version,
      this.proposals.version, store.agendaAccounts.version, this.people.version,
      target?.kind === "event" ? this.events.get(`${target.event}|${target.occurrence}`).version : 0].join("|");
  }

  private async reread(): Promise<void> {
    await this.load(true);
    if (this.q.trim().length >= 2) await this.search();
    void refreshCounts();
  }

  // ── ce que la vue montre ───────────────────────────────────────────

  private calendarsList(): AgendaCalendar[] {
    return withShownNames(this.cals?.calendars ?? []);
  }

  private viewState(): AgendaView {
    const { today, minute } = this.now();
    const zone = this.zone();
    const failing = (store.agendaAccounts.value?.accounts ?? []).filter((a) => a.error && a.enabled && !a.system)
      .map((a) => ({ key: a.key, label: a.label, error: a.error }));
    return {
      view: this.view, date: this.date || today, today, nowMinute: minute, zone, zoneShort: offsetWords(zone, Date.now()),
      calendars: this.calendarsList(), off: hiddenHere(), selected: this.selectedKey(), miniMonth: this.miniMonth,
      mobileMonth: this.mobileMonth, q: this.q, searching: this.searching, invitations: this.invitations.value?.items.length ?? 0,
      failing, names: this.names(),
    };
  }

  /** Le nom de chaque personne qui a un compte, elle comprise. */
  private names(): Map<string, string> {
    const out = new Map<string, string>((this.people.value?.items ?? []).map((p) => [p.person, p.name]));
    const me = store.me.value;
    if (me?.person) out.set(me.person, me.name || "Toi");
    return out;
  }

  private selectedKey(): string | null {
    const t = parse(this.ctx?.item ?? null).target;
    return t ? targetKey(t) : null;
  }

  private shown(calendar: string): boolean {
    if (hiddenHere().has(calendar)) return false;
    if (calendar === "mika") return true;
    const c = this.calendarsList().find((x) => x.key === calendar);
    return !!c && !c.hidden;
  }

  /** Les occurrences de la période lue, des agendas cochés ; ce que Mika propose, toujours (il attend ta décision). */
  private occurrences(): Occ[] {
    const key = this.periodKey();
    const period = key ? this.periods.get(key).value : null;
    if (!period) return [];
    const zone = this.zone();
    const out: Occ[] = [];
    for (const item of period.items) if (this.shown(item.calendar)) out.push(occOfItem(item, zone));
    if (this.shown("mika")) for (const d of period.her) out.push(occOfHer(d, zone));
    for (const p of period.proposals) {
      const o = occOfProposal(p, zone);
      if (o) out.push(o);
    }
    return sortOccs(out);
  }

  private pendingProposals(): Proposal[] {
    return (this.proposals.value?.items ?? []).filter((p) => p.op === "ajouter" && p.decides && p.draft);
  }

  /** L'occurrence que le volet ouvre : dans la période, sinon lue à part (un événement), ou dans ce qui attend. */
  private targetOcc(t: Target): Occ | null {
    const zone = this.zone();
    if (t.kind === "event") {
      const detail = this.events.get(`${t.event}|${t.occurrence}`).value;
      if (detail) return occOfItem(detail, zone);
      return this.occurrences().find((o) => o.kind === "event" && o.item?.event === t.event && (o.item.occurrence === t.occurrence || !t.occurrence)) ?? null;
    }
    if (t.kind === "proposal") {
      const p = (this.proposals.value?.items ?? []).find((x) => x.id === t.id);
      return p ? occOfProposal(p, zone) : null;
    }
    const key = this.periodKey();
    const her = key ? this.periods.get(key).value?.her.find((d) => d.ref === t.ref) : undefined;
    return her ? occOfHer(her, zone) : null;
  }

  // ── le rendu ───────────────────────────────────────────────────────

  private actions(ctx: ScreenContext): string {
    this.ctx = ctx;
    const r = parse(ctx.item);
    if (!this.date) this.date = this.now().today;
    return titleBar(this.viewState(), r.invitations);
  }

  private render(body: HTMLElement, ctx: ScreenContext): void {
    this.body = body;
    this.ctx = ctx;
    const r = parse(ctx.item);
    if (r.view && r.view !== this.view) {
      this.view = r.view;
      saveView(r.view);
    }
    if (!this.date) this.date = this.now().today;
    if (ctx.item !== this.lastRoute) {
      this.lastRoute = ctx.item ?? "";
      this.mobileMonth = false;
      this.recenter(r);
    }
    if (!r.modal && modalOpen() && document.querySelector("#modal-root .ag-modal") && !this.saving) closeModal();
    if (!r.modal) this.modalFor = "";
    this.paint();
    if (!this.cals) this.fresh.fresh();
    if (!this.fresh.back()) void this.load();
    this.openModalRoute();
  }

  /** Une route qui ouvre un événement y ramène la vue (son jour). */
  private recenter(r: RouteState): void {
    const t = r.target ?? (r.modal === "modifier" ? targetOf(r.rest[0] === "proposition" ? r.rest : ["evenement", ...r.rest]) : null);
    if (!t) return;
    const o = this.targetOcc(t);
    this.recenterPending = !o;
    if (o) {
      this.date = o.day;
      this.miniMonth = null;
    }
  }

  private paint(head = true): void {
    const body = this.body;
    const ctx = this.ctx;
    if (!body || !ctx) return;
    const cals = store.agendaCalendars;
    if (!cals.value) {
      body.innerHTML = cals.error
        ? `<div class="empty">${ico("alert")}<b>Impossible de lire tes agendas</b><p>${h(failureText(cals.error))}</p><button class="btn sm" type="button" data-agrelire>${ico("refresh", "sm")}Réessayer</button></div>`
        : `<div class="empty">${ico("refresh")}<p>Chargement…</p></div>`;
      return;
    }
    const r = parse(ctx.item);
    const v = this.viewState();
    const range = bounds(this.view, this.date);
    const occs = this.occurrences();
    const key0 = this.periodKey();
    let volet = "";
    if (r.target) {
      const o = this.targetOcc(r.target);
      if (o) volet = o.kind === "event" ? eventFiche(v, o, false) : o.kind === "proposal" ? proposalFiche(v, o) : herFiche(v, o);
      else {
        const t = r.target;
        const err = t.kind === "event" ? this.events.get(`${t.event}|${t.occurrence}`).error : null;
        const reading = (t.kind === "proposal" && !this.proposals.settled) || (t.kind === "her" && !(key0 && this.periods.get(key0).settled));
        volet = reading ? missingFiche("Chargement…") : err || t.kind !== "event" ? missingFiche(t.kind === "proposal" ? "Cette proposition n'attend plus : elle a été décidée, ou sa date est passée." : t.kind === "her" ? "Cette date n'est plus dans la période affichée." : failureText(err)) : missingFiche("Chargement…");
      }
    } else if (r.invitations) {
      const inv = this.invitations;
      volet = invitationsPanel(v, inv.value?.items ?? null, inv.value ? "" : inv.error ? failureText(inv.error) : "", (item) => whenWords(occOfItem(item, this.zone()), v.today));
    }
    ctx.el.classList.toggle("ag-volet-ouvert", !!volet);
    const key = this.periodKey();
    const period = key ? this.periods.get(key) : null;
    let main: string;
    if (this.q) {
      const mine = this.found && this.found.q === this.q ? this.found : null;
      main = searchView(v, mine ? mine.occs : null, this.found?.more ?? false, mine ? mine.error : "", mine?.unchecked ?? false);
    } else if (period && !period.value && period.error) main = `<div class="empty">${ico("alert")}<b>Impossible de lire cette période</b><p>${h(failureText(period.error))}</p><button class="btn sm" type="button" data-agrelire>${ico("refresh", "sm")}Réessayer</button></div>`;
    else if (this.view === "mois") main = monthView(v, occs, range);
    else if (this.view === "planning") main = planningView(v, occs, range);
    else if (this.view === "jour") main = gridView(v, occs, [this.date]);
    else main = gridView(v, occs, Array.from({ length: 7 }, (_, i) => shift(range[0], i)));
    const pending = this.pendingProposals();
    const first = pending[0] ?? null;
    const firstOcc = first ? occOfProposal(first, this.zone()) : null;
    const old = $<HTMLElement>("[data-agscroll]", body);
    const kept = old ? { kind: old.dataset.agscroll, top: old.scrollTop } : null;
    const sideScroll = $<HTMLElement>(".ag-side-scroll", body)?.scrollTop ?? 0;
    const mobileMonth = this.mobileMonth ? `<div class="ag-mm">${miniMonth(v, range)}</div>` : "";
    body.innerHTML = `<div class="ag${volet ? " avec-volet" : ""}">${side(v, range)}<section class="pane ag-main">${mobileMonth}${strip(v, first, firstOcc, Math.max(0, pending.length - 1), v.selected)}${main}</section>${volet}</div>`;
    const sc = $<HTMLElement>("[data-agscroll]", body);
    const sideNow = $<HTMLElement>(".ag-side-scroll", body);
    if (sideNow) sideNow.scrollTop = sideScroll;
    if (sc && sc.dataset.agscroll === "grille") {
      const t = r.target ? this.targetOcc(r.target) : null;
      const aim = t && !t.allDay ? Math.max(0, (t.start / 60) * HH - 3 * HH) : 7.5 * HH;
      sc.scrollTop = kept && kept.kind === "grille" ? kept.top : aim;
      if (t && !t.allDay && ((t.start / 60) * HH < sc.scrollTop || (t.end / 60) * HH > sc.scrollTop + sc.clientHeight - 120)) sc.scrollTop = aim;
    } else if (sc && kept && kept.kind === sc.dataset.agscroll) sc.scrollTop = kept.top;
    if (head) this.shell.refreshHead();
  }

  // ── les fenêtres d'une route ───────────────────────────────────────

  private routeBack(): string {
    return `#${ID}/${this.view}`;
  }

  /** `#agenda/nouveau`, `#agenda/modifier/…`, `#agenda/partager/…` : la fenêtre s'ouvre une fois, ses données lues. */
  private openModalRoute(): void {
    const ctx = this.ctx;
    if (!ctx || !this.open()) return;
    const r = parse(ctx.item);
    if (!r.modal || !this.cals) return;
    const id = ctx.item ?? "";
    if (this.modalFor === id) return;
    if (r.modal === "partager") {
      const key = decodeURIComponent(r.rest.join("/"));
      const cal = this.calendarsList().find((c) => c.key === key);
      if (!cal) return;
      this.modalFor = id;
      void this.people.load().then(() => {
        openShare(cal, this.people.value?.items ?? [], {
          changed: () => {
            store.agendaCalendars.invalidate();
            void this.load(true);
          },
          hide: (k) => setShown(k, false),
        });
        this.watchClose(id);
      });
      return;
    }
    if (r.modal === "nouveau") {
      this.modalFor = id;
      this.form("nouveau", null);
      return;
    }
    // modifier : un événement, ou ce que Mika propose
    const t = r.rest[0] === "proposition" ? targetOf(r.rest) : targetOf(["evenement", ...r.rest]);
    if (!t) return;
    const o = this.targetOcc(t);
    if (!o) {
      if (t.kind === "event") void this.events.get(`${t.event}|${t.occurrence}`).load().then(() => this.openModalRoute());
      return;
    }
    this.modalFor = id;
    this.form(t.kind === "proposal" ? "proposition" : "modifier", o);
  }

  /** La fenêtre d'une route fermée sans rien enregistrer : la route redevient la vue (sans redessiner). */
  private watchClose(id: string): void {
    const root = document.getElementById("modal-root");
    if (!root) return;
    const watch = new MutationObserver(() => {
      if (root.querySelector(".ag-modal")) return;
      watch.disconnect();
      if (this.ctx?.item === id && !this.saving) {
        this.modalFor = "";
        history.replaceState(null, "", this.routeBack());
        this.lastRoute = this.view;
        if (this.ctx) this.ctx.item = this.view;
      }
    });
    watch.observe(root, { childList: true, subtree: true });
  }

  private writable(): AgendaCalendar[] {
    return this.calendarsList().filter((c) => c.writable && c.can.write && !c.hidden);
  }

  private defaultCalendar(): string {
    const w = this.writable();
    return (w.find((c) => c.kind === "systeme" && c.primary) ?? w[0])?.key ?? "";
  }

  /** La fenêtre d'un événement : créer, modifier, dupliquer, ou modifier ce que Mika propose. */
  private form(mode: FormMode, o: Occ | null, slot?: { day: string; minute: number }, values?: FormValues): void {
    const writable = this.writable();
    if (!writable.length) {
      toast("Aucun de tes agendas ne s'écrit d'ici : branche-en un dans Paramètres › Agendas.", { ico: "info", duration: 5000 });
      return;
    }
    const { today, minute } = this.now();
    const item = o?.item;
    const proposal = o?.proposal;
    const fromCal = item?.calendar ?? proposal?.calendar ?? "";
    const calendar = mode === "nouveau" ? this.defaultCalendar() : writable.some((c) => c.key === fromCal) ? fromCal : mode === "modifier" ? fromCal : this.defaultCalendar();
    const spec: FormSpec = {
      mode, today, zone: this.zone(), writable, calendars: this.calendarsList(), calendar,
      occ: o ?? undefined, item, proposal, slot, nowMinute: minute,
    };
    const routeId = this.ctx?.item ?? "";
    openEventForm(spec, {
      save: (result, v) => this.saveForm(mode, o, result, v, spec),
      closed: () => {
        if (this.saving) return;
        if (this.ctx?.item === routeId && (routeId.startsWith("nouveau") || routeId.startsWith("modifier"))) {
          this.modalFor = "";
          history.replaceState(null, "", o && mode === "modifier" ? `#${ID}/${o.key}` : this.routeBack());
          this.lastRoute = (location.hash.replace(/^#agenda\/?/, ""));
          if (this.ctx) this.ctx.item = this.lastRoute;
        }
      },
    }, values);
  }

  private async saveForm(mode: FormMode, o: Occ | null, result: { calendar: string; fields: import("../../api/agenda").EventFields; recurring: boolean }, values: FormValues, spec: FormSpec): Promise<boolean> {
    const cal = this.calendarsList().find((c) => c.key === result.calendar);
    try {
      if (mode === "modifier" && o?.item) {
        if (!Object.keys(result.fields).length) {
          toast("Rien n'a changé.", { ico: "info" });
          return true;
        }
        let scope: Scope = "un";
        if (result.recurring) {
          this.saving = true;
          const asked = await askScope(o, "modifier", spec.today);
          if (!asked) {
            this.saving = false;
            this.form(mode, o, undefined, values);
            return false;
          }
          scope = asked;
        }
        const done = await editEvent(o.item.event, o.item.occurrence, scope, result.fields, newNonce());
        toast(done.message, { ico: "check" });
        this.after(`#${ID}/${o.key}`);
        return true;
      }
      if (mode === "proposition" && o?.proposal) {
        const done = await editProposal(o.proposal.id, result.calendar, result.fields, newNonce());
        toast(done.message || `Ajouté à « ${cal?.name ?? ""} », avec tes changements.`, { ico: "check" });
        this.after(done.made?.event ? `#${ID}/${eventKey(done.made.event, "")}` : this.routeBack());
        return true;
      }
      const done = await createEvent(result.calendar, result.fields, newNonce());
      toast(done.message || `Enregistré dans « ${cal?.name ?? ""} ».`, { ico: "check" });
      this.after(done.made?.event ? `#${ID}/${eventKey(done.made.event, "")}` : this.routeBack());
      return true;
    } catch (err) {
      toastFailure(err);
      if (this.saving) {
        // la fenêtre a cédé la place à la question de la portée : elle revient, telle qu'on l'avait laissée
        this.saving = false;
        this.form(mode, o, undefined, values);
      }
      return false;
    } finally {
      this.saving = false;
    }
  }

  /** Après un geste : la route suivante, tout se relit, les pastilles aussi. */
  private after(hash: string): void {
    this.modalFor = "";
    this.invalidate();
    if (location.hash !== hash) this.shell.go(hash);
    else void this.load(true);
    void refreshCounts();
  }

  // ── les gestes ─────────────────────────────────────────────────────

  private mount(section: HTMLElement): void {
    const go = (hash: string) => this.shell.go(hash);
    on(section, "[data-agauj]", "click", () => {
      this.date = this.now().today;
      this.miniMonth = null;
      this.q = "";
      this.searching = false;
      void this.load();
      this.paint();
    });
    on(section, "[data-agpas]", "click", (_e, b) => {
      this.date = step(this.view, this.date, Number(b.dataset.agpas), this.now().today);
      this.miniMonth = null;
      this.paint();
      void this.load();
      if (this.view === "planning") {
        const sc = $<HTMLElement>("[data-agscroll]", section);
        if (sc) sc.scrollTop = 0;
      }
    });
    on(section, "[data-agvue]", "click", (_e, b) => {
      this.q = "";
      this.searching = false;
      go(`#${ID}/${b.dataset.agvue}`);
    });
    on(section, "[data-agperiode]", "click", () => {
      if (!isMobile()) return;
      this.mobileMonth = !this.mobileMonth;
      this.paint();
    });
    on(section, "[data-agmini]", "click", (_e, b) => {
      const m = this.miniMonth ?? `${this.date.slice(0, 7)}-01`;
      this.miniMonth = addMonths(m, Number(b.dataset.agmini));
      this.paint();
    });
    on(section, "[data-agjour]", "click", (_e, b) => {
      this.date = b.dataset.agjour ?? this.date;
      this.miniMonth = null;
      this.mobileMonth = false;
      this.q = "";
      const r = parse(this.ctx?.item ?? null);
      if (r.target || r.invitations) go(this.routeBack());
      else {
        this.paint();
        void this.load();
      }
    });
    on(section, "[data-agjourvue]", "click", (_e, b) => {
      this.date = b.dataset.agjourvue ?? this.date;
      this.q = "";
      go(`#${ID}/jour`);
    });
    section.addEventListener("change", (e) => {
      const c = (e.target as HTMLElement).closest<HTMLInputElement>("[data-agcoche]");
      if (c) setShown(c.dataset.agcoche ?? "", c.checked);
    });
    on(section, "[data-agmenu]", "click", (e, b) => {
      e.stopPropagation();
      this.calendarMenu(b, b.dataset.agmenu ?? "");
    });
    on(section, "[data-agcals]", "click", (e, b) => {
      e.stopPropagation();
      this.calendarsMenu(b);
    });
    on(section, "[data-agev]", "click", (_e, b) => go(`#${ID}/${b.dataset.agev}`));
    on(section, "[data-agfermer]", "click", () => go(this.routeBack()));
    on(section, "[data-agcol]", "click", (e, col) => {
      if (e.target !== col) return;
      const r = col.getBoundingClientRect();
      const minute = Math.max(0, Math.min(1410, Math.floor(((e as MouseEvent).clientY - r.top) / HH * 2) * 30));
      this.modalFor = "nouveau";
      history.pushState(null, "", `#${ID}/nouveau`);
      if (this.ctx) this.ctx.item = "nouveau";
      this.lastRoute = "nouveau";
      this.form("nouveau", null, { day: col.dataset.agcol ?? this.date, minute });
    });
    on(section, "[data-agprop]", "click", (_e, b) => void this.decide(b.dataset.agprop ?? ""));
    on(section, "[data-agrep]", "click", (_e, b) => void this.respond(Number(b.dataset.agrepev), b.dataset.agrepocc ?? "", (b.dataset.agrep ?? "oui") as "oui" | "peut" | "non"));
    on(section, "[data-agrepmot]", "click", (_e, b) => void this.respondWithWord(Number(b.dataset.agrepmot), b.dataset.agrepocc ?? "", Number(b.dataset.agrepprep)));
    on(section, "[data-agaction]", "click", (_e, b) => void this.action(b.dataset.agaction ?? ""));
    on(section, "[data-agrepchanger]", "click", (_e, b) => {
      const done = b.closest<HTMLElement>("[data-agrepdone]");
      const row = done?.nextElementSibling as HTMLElement | null;
      if (done && row?.matches("[data-agreprow]")) {
        done.hidden = true;
        row.hidden = false;
      }
    });
    on(section, "[data-agrappel]", "click", (e, b) => {
      e.stopPropagation();
      this.remindMenu(b);
    });
    on(section, "[data-agrelire]", "click", () => void this.load(true));
    on(section, "[data-agchercher]", "click", () => {
      this.searching = true;
      this.shell.refreshHead();
      $<HTMLInputElement>("[data-agq]", section)?.focus();
    });
    on(section, "[data-agqvide]", "click", () => {
      this.q = "";
      this.searching = false;
      this.found = null;
      this.shell.refreshHead();
      this.paint();
    });
    section.addEventListener("input", (e) => {
      const t = e.target as HTMLInputElement;
      if (!t.matches("[data-agq]")) return;
      this.q = t.value.slice(0, 120);
      this.searching = true;
      window.clearTimeout(this.searchTimer);
      this.searchTimer = window.setTimeout(() => void this.search(), SEARCH_DELAY_MS);
      this.paintMain();
    });
    section.addEventListener("focusout", (e) => {
      const t = e.target as HTMLElement;
      if (!t.matches("[data-agq]") || this.q) return;
      this.searching = false;
      this.shell.refreshHead();
    });
    // le menu des agendas d'un téléphone vit hors de l'écran
    document.addEventListener("change", (e) => {
      const c = (e.target as HTMLElement).closest<HTMLInputElement>(".menu [data-agcoche]");
      if (c) setShown(c.dataset.agcoche ?? "", c.checked);
    });
  }

  /** La vue seule (pendant la saisie d'une recherche : la barre de titre garde le curseur). */
  private paintMain(): void {
    if (!this.body) return;
    this.paint(false);
  }

  private async search(): Promise<void> {
    const q = this.q.trim();
    const seq = ++this.searchSeq;
    if (q.length < 2) {
      this.found = null;
      if (this.open()) this.paint(false);
      return;
    }
    try {
      const keys = this.readKeys().filter((k) => !hiddenHere().has(k));
      if (!keys.length) {
        // aucun agenda coché : une liste vide voudrait dire « partout » pour le serveur ; on ne cherche pas
        this.found = { q: this.q, occs: [], more: false, error: "", unchecked: true };
        if (this.open()) this.paint(false);
        return;
      }
      const got = await searchAgenda(q, keys);
      if (seq !== this.searchSeq) return;
      const zone = this.zone();
      const occs = sortOccs([...got.items.map((i) => occOfItem(i, zone)), ...got.her.map((d) => occOfHer(d, zone))]);
      this.found = { q: this.q, occs, more: got.more, error: "" };
    } catch (err) {
      if (seq !== this.searchSeq) return;
      this.found = { q: this.q, occs: [], more: false, error: failureText(err) };
    }
    if (this.open()) this.paint(false);
  }

  private calendarMenu(anchor: HTMLElement, key: string): void {
    const cal = this.calendarsList().find((c) => c.key === key);
    if (!cal) return;
    const owner = cal.level === "proprietaire";
    const items: MenuItem[] = [
      { header: cal.name },
      {
        label: "Afficher seulement celui-ci", icon: "eye", action: () => showOnly(key, [...this.calendarsList().map((c) => c.key), "mika"]),
      },
    ];
    if (cal.kind === "mika") items.push({ html: '<div class="mh">Couleur · son rose, qui ne change pas</div>' });
    else if (owner && cal.can.settings) {
      items.push({ header: "Couleur" });
      items.push({ html: `<div class="ag-swatches">${PALETTE.map((k) => `<button type="button" class="ag-swatch${colorOf(cal) === k ? " on" : ""}" style="--c:var(--ag-${k})" data-agcoul="${k}" title="${cap(k)}" aria-label="${cap(k)}"></button>`).join("")}</div>` });
    }
    items.push("sep");
    items.push({ label: owner ? "Partager" : "Partager (seul son propriétaire)", icon: "users", action: () => this.shell.go(`#${ID}/partager/${encodeURIComponent(key)}`) });
    if (cal.kind !== "mika") {
      items.push({ label: owner ? "Paramètres" : "Paramètres › Agendas", icon: "settings", action: () => this.shell.go(owner ? `#parametres/agendas/${encodeURIComponent(cal.account)}` : "#parametres/agendas") });
    }
    const menu = openMenu(anchor, items, { align: "left" });
    on(menu, "[data-agcoul]", "click", (_e, b) => {
      closeMenu();
      void saveCalendar(key, { color: b.dataset.agcoul ?? "" }).then(() => {
        store.agendaCalendars.invalidate();
        void this.load(true);
      }, toastFailure);
    });
  }

  private calendarsMenu(anchor: HTMLElement): void {
    const v = this.viewState();
    openMenu(anchor, [{ html: `<div class="ag-cals-menu">${calendarGroups(v)}</div>` }, "sep",
      { label: "Brancher un agenda", icon: "plus", action: () => this.shell.go("#parametres/agendas/brancher") }]);
  }

  private remindMenu(anchor: HTMLElement): void {
    const t = parse(this.ctx?.item ?? null).target;
    const o = t ? this.targetOcc(t) : null;
    const item = o?.item;
    if (!item) return;
    const cal = this.calendarsList().find((c) => c.key === item.calendar);
    openMenu(anchor, [{ header: "Mika te le rappelle" }, ...remindChoices(cal).map(([k, l]) => ({
      label: l,
      checked: item.remind === k,
      action: () => {
        void remindEvent(item.event, k as MikaReminder).then(() => {
          toast(k === "non" ? "Elle ne te le rappellera pas." : k ? `Elle te le rappellera ${mikaReminderWords(k)}.` : "Elle suit le réglage de l'agenda.", { mika: true, ico: "bell" });
          this.after(location.hash);
        }, toastFailure);
      },
    }))]);
  }

  private findProposal(id: number): Proposal | null {
    const all = [...(this.proposals.value?.items ?? [])];
    for (const i of this.invitations.value?.items ?? []) if (i.prepared) all.push(i.prepared);
    const t = parse(this.ctx?.item ?? null).target;
    if (t?.kind === "event") {
      const d = this.events.get(`${t.event}|${t.occurrence}`).value;
      if (d?.prepared) all.push(d.prepared);
    }
    return all.find((p) => p.id === id) ?? null;
  }

  /** Accepter (tel qu'il a été lu) ou refuser ce que Mika propose. */
  private async decide(spec: string): Promise<void> {
    const [what, raw] = spec.split(":");
    const id = Number(raw);
    const p = this.findProposal(id);
    try {
      if (what === "accept") {
        const done = await acceptProposal(id, p?.preview?.digest ?? "", newNonce());
        toast(done.message, { ico: "check" });
      } else {
        const done = await refuseProposal(id, "", newNonce());
        toast(done.message, { ico: "x" });
      }
    } catch (err) {
      toastFailure(err);
      if (!(err instanceof ApiError && (err.status === 404 || err.status === 409))) return;
    }
    const t = parse(this.ctx?.item ?? null).target;
    this.after(t?.kind === "proposal" && t.id === id ? this.routeBack() : location.hash);
  }

  private async respond(event: number, occurrence: string, answer: "oui" | "peut" | "non", comment = ""): Promise<void> {
    try {
      const done = await respondEvent(event, occurrence, answer, comment, "tous", newNonce());
      toast(done.message, { ico: answer === "non" ? "x" : "check" });
    } catch (err) {
      toastFailure(err);
    }
    this.after(location.hash);
  }

  private async respondWithWord(event: number, occurrence: string, prepared: number): Promise<void> {
    const p = this.findProposal(prepared);
    const item = this.invitations.value?.items.find((i) => i.event === event) ?? this.events.get(`${event}|${occurrence}`).value;
    const to = item?.organizer?.name || item?.organizer?.address || "l'organisateur";
    const cal = this.calendarsList().find((c) => c.key === item?.calendar);
    const via = cal?.kind === "systeme" ? "dans son Agenda" : cal ? `par ${providerShort(cal)}` : "par l'agenda";
    const got = await askAnswer(to, p?.answer || "oui", p?.comment ?? "", via);
    if (got) await this.respond(event, occurrence, got.answer, got.comment);
  }

  private async action(kind: string): Promise<void> {
    const t = parse(this.ctx?.item ?? null).target;
    const o = t ? this.targetOcc(t) : null;
    if (!o) return;
    const { today } = this.now();
    if (kind === "demander") {
      this.hooks.ask(`à propos de « ${o.title} » (${shortDay(o.day)}${o.allDay ? "" : ` à ${hm(o.start)}`}) : `);
      return;
    }
    if (kind === "parler") {
      this.hooks.ask(`à propos de « ${o.title.charAt(0).toLowerCase()}${o.title.slice(1)} » : `);
      return;
    }
    if (kind === "dupliquer") {
      this.form("dupliquer", o);
      return;
    }
    if (kind === "supprimer" && o.item) {
      const item = o.item;
      let scope: Scope = "un";
      if (item.recurring && item.occurrence) {
        const asked = await askScope(o, "supprimer", today);
        if (!asked) return;
        scope = asked;
      } else {
        const cal = this.calendarsList().find((c) => c.key === item.calendar);
        const sure = await confirmModal({
          title: item.invitation || !item.organized ? "Retirer l'invitation" : "Supprimer l'événement",
          text: item.invitation || !item.organized
            ? `Retirer « ${o.title} » (${shortDay(o.day)}) de ton agenda ? C'est la refuser : la réponse part à qui l'organise.`
            : `Supprimer « ${o.title} » (${shortDay(o.day)}) ? Il disparaît aussi ${cal ? whereLine(cal) : "de l'agenda"}.${item.participants.length > 1 ? " Les participants sont prévenus." : ""}`,
          ok: item.invitation || !item.organized ? "Retirer" : "Supprimer",
          danger: true,
        });
        if (!sure) return;
      }
      try {
        const done = await deleteEvent(item.event, item.occurrence, scope, newNonce());
        toast(done.message, { ico: "trash" });
        this.after(this.routeBack());
      } catch (err) {
        toastFailure(err);
      }
    }
  }

  private searchEntries(): PaletteEntry[] {
    const out: PaletteEntry[] = [
      { group: "Agenda", title: "Créer un événement", icon: "plus", route: `#${ID}/nouveau` },
      { group: "Agenda", title: "Les invitations", sub: `${this.invitations.value?.items.length ?? 0} en attente`, icon: "inbox", route: `#${ID}/invitations` },
    ];
    const { today } = this.now();
    for (const o of this.occurrences().filter((x) => x.day >= today).slice(0, 40)) {
      const cal = this.calendarsList().find((c) => c.key === o.calendar);
      out.push({ group: "Agenda", title: o.title, sub: `${o.kind === "her" ? "L'agenda de Mika" : cal?.name ?? ""} · ${shortDay(o.day)}${o.allDay ? "" : ` ${hm(o.start)}`}`, icon: "agenda", route: `#${ID}/${o.key}` });
    }
    for (const c of this.calendarsList().filter((x) => !x.hidden && x.kind !== "mika")) {
      out.push({ group: "Agenda", title: `Agenda « ${c.name} »`, sub: providerShort(c), icon: "agenda", route: c.level === "proprietaire" ? `#parametres/agendas/${encodeURIComponent(c.account)}` : "#parametres/agendas" });
    }
    return out;
  }
}

function whereLine(cal: AgendaCalendar): string {
  return ({ systeme: "de ce serveur", google: "chez Google", microsoft: "chez Microsoft", caldav: "chez le serveur CalDAV" } as Record<string, string>)[cal.kind] ?? "de l'agenda";
}

function shift(day: string, n: number): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function shortBefore(day: string): string {
  return shift(day, -1);
}

export function agendaScreen(shell: Shell, hooks: AgendaHooks): ScreenDef {
  return new AgendaScreen(shell, hooks).def();
}

