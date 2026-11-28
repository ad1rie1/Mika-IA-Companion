/**
 * Teams (ADR 0187, 0189, 0191) : tes discussions comme dans un vrai client — l'extension « Mika · Teams » lit ce que
 * Teams web reçoit et pose ce qui part. Tu réponds toi-même (ton message part par l'extension du compte, sous ton nom,
 * sans accord), ou tu demandes à Mika de préremplir ; ce qu'elle prépare se relit dans la discussion et dans « Ses
 * brouillons ». Ce qu'un partage ne permet pas n'est pas offert. Le contrat : `protocole-moi.md` § 4. Rien ne se relit
 * à intervalles : le direct dit ce qui a changé (ADR 0308, § 2 bis) — `teams` (ses comptes, la liste, le fil ouvert
 * s'il est nommé), `teams.replies` (« Ses brouillons »), `teams.work` (où elle en est, dans le fil ouvert s'il est
 * nommé) —, et l'écran au second plan se relit à son retour.
 */
import { insertEmoji } from "../../ui/emojis";
import type { RuleLine } from "../../api/rights";
import {
  editReply,
  fetchAccounts,
  fetchConversations,
  fetchReplies,
  fetchThread,
  fetchThreadWork,
  prefill,
  redoReply,
  refuseReply,
  sendMessage,
  sendReply,
  TEAMS_LIMITS,
  type Conversation,
  type Reply,
  type TeamsAccount,
  type TeamsMessage,
  type Thread,
  type ThreadWork,
} from "../../api/teams";
import { ofName } from "../../shared/names";
import { me, rights } from "../../shared/store";
import { refreshCounts } from "../../shell/counts";
import { $, $$, h, isMobile, on } from "../../shell/dom";
import { closeModal, openMenu, openModal, toast, type MenuItem } from "../../shell/float";
import { ico } from "../../shell/icons";
import type { PaletteEntry } from "../../shell/palette";
import type { ScreenContext, ScreenDef, ScreenTab, Shell } from "../../shell/shell";
import { bindCounts, canCorrect, correctField, errorText, openAsk, paintCount, toFill } from "../../shared/compose";
import { dayAndClock } from "../../shared/dates";
import { chars, thousands } from "../../shared/text";
import { newNonce } from "../mail/format";
import { tickWork } from "../../mika/work";
import { Freshness, live, names, OneAtATime, pageShown, type Changed } from "../../live/live";
import { ages } from "../../shell/ages";
import { ago, authorLabel, kindLabel, ownAccount, ownBubbles, sentUnder, stillSentHere, threadGone, UNDER_WAY, withoutSent, type SentHere } from "./format";
import {
  capsOf,
  conversationRow,
  dock,
  dockWork,
  extensionChip,
  imageViewer,
  imagesInOrder,
  infoPane,
  listHead,
  repliesTable,
  threadBody,
  threadHead,
  type DockView,
  type Filter,
  type InfoView,
  type ThreadView,
} from "./markup";

const MAX_CHARS = TEAMS_LIMITS.body;
/** Au-delà, l'extension ne s'est pas manifestée depuis trop longtemps pour que ce qui part parte vite. */
const QUIET_MS = 2 * 3600_000;
const EMOJIS = ["😊", "😅", "😂", "🙂", "😉", "😍", "🥲", "🤔", "😬", "🙏", "👍", "👌", "🔥", "✨", "❤️", "💪", "🎉", "☕", "✅", "❌", "👀", "🙌", "😴", "📎"];

export function conversationHash(key: string): string {
  return `#teams/discussions/${encodeURIComponent(key)}`;
}

/** Ce que la relecture discrète d'un fil compare : rien de changé, rien à repeindre. */
function sameThread(a: Thread, b: Thread): boolean {
  return JSON.stringify([a.messages, a.replies, a.pending ?? null, a.under_way, a.asked]) ===
    JSON.stringify([b.messages, b.replies, b.pending ?? null, b.under_way, b.asked]);
}

const DISCUSSIONS_SKELETON = `<div class="split tm-split" data-tm-root="discussions"><aside class="pane" data-tm-list>
    <div class="pane-head" data-tm-list-head></div><div class="pane-scroll" data-tm-convs></div></aside>
  <section class="pane tm-conv" data-tm-conv></section><aside class="pane tm-info" data-tm-info hidden></aside></div>`;

export class TeamsScreen {
  private section: HTMLElement | null = null;
  private body: HTMLElement | null = null;
  private mounted: "discussions" | "brouillons" | null = null;
  private started = false;

  private readonly tabs: ScreenTab[] = [
    { id: "discussions", title: "Discussions" },
    { id: "brouillons", title: "Ses brouillons" },
  ];

  private accounts: TeamsAccount[] = [];
  private plugged = true;
  private enabled = true;
  private accountsError = "";
  private accountsLoaded = false;
  /** Ses comptes, lus une première fois : le niveau d'un compte décide de ce que le fil, le champ et « Ses
   *  brouillons » offrent (un fil peint avant serait en lecture seule). */
  private accountsReady: Promise<void> = Promise.resolve();

  private conversations: Conversation[] = [];
  private convsLoaded = false;
  private convsError = "";
  private filter: Filter = "tout";
  private searching = false;
  private q = "";

  private open = "";
  private thread: Thread | null = null;
  private threadError = "";
  private threadSeq = 0;
  private older: TeamsMessage[] = [];
  /** Il en reste de plus anciens que `older` (sinon, ce que dit la page des plus récents). */
  private olderMore = false;
  private loadingOlder = false;
  private reading = false;
  private info = !matchMedia("(max-width: 1240px)").matches;
  private editing = "";
  /** Ta version de la réponse qu'on retouche, gardée quand le fil se redessine sans elle (un autre onglet). */
  private editText = "";
  /** Ce que le champ montre en ce moment (sa discussion et sa vue) : le redessiner à l'identique n'a pas lieu. */
  private dockSig = "";
  private sending = false;
  /** Le message que tu cites (ADR 0305), dans une discussion : au-dessus du champ, il part avec ton message. */
  private quoting: { conversation: string; ref: string; author: string; at: number; preview: string } | null = null;
  /** Tes envois d'ici que le moteur n'a pas encore pu dire (sa liste `pending` les remplace dès qu'il les connaît). */
  private sent: SentHere[] = [];
  /** Ce que tu as commencé d'écrire, discussion par discussion. */
  private readonly typed = new Map<string, string>();
  /** Les conversations où on lui a demandé une réponse (et depuis quand). */
  private readonly asked = new Map<string, number>();

  private replies: Reply[] = [];
  private repliesLoaded = false;

  private searchTimer = 0;
  /** La réponse que la route désigne dans « Ses brouillons » (`#teams/brouillons/<id>`), et si on y a déjà défilé. */
  private focusReply = "";
  private focusShown = false;

  /** Le direct (ADR 0308) : montré, l'écran relit ce qu'un changement touche ; sinon il se relit à son retour. */
  private readonly fresh = new Freshness(() => this.started && this.visible(), () => void this.refresh());
  // une lecture à la fois par route : une rafale de trames n'en lance pas dix
  private readonly accountsRead = new OneAtATime(() => this.loadAccounts());
  private readonly convsRead = new OneAtATime(() => this.loadConversations());
  private readonly repliesRead = new OneAtATime(() => this.loadReplies());
  private readonly threadRead = new OneAtATime(() => (this.onDiscussions() && this.open ? this.loadThread(true) : Promise.resolve()));
  private readonly workRead = new OneAtATime(() => this.rereadWork());

  constructor(private readonly shell: Shell) {
    // les âges (le dernier signe de l'extension, son dernier lot) avancent d'eux-mêmes, sans rien relire
    ages.onTick(() => this.agesTick());
    live.onChange("teams", (convs) => this.fresh.touch(() => this.teamsChanged(convs)));
    live.onChange("teams.replies", () => this.fresh.touch(() => void this.repliesRead.run()));
    live.onChange("teams.work", (convs) => this.fresh.touch(() => {
      if (this.open && this.thread?.key === this.open && names(convs, this.open)) void this.workRead.run();
    }));
  }

  screen(): ScreenDef {
    return {
      id: "teams",
      title: "Teams",
      icon: "teams",
      tabs: this.tabs,
      actions: () => this.actions(),
      mount: (section) => this.mount(section),
      render: (body, ctx) => this.render(body, ctx),
      search: () => this.searchEntries(),
    };
  }

  // ── Ce qu'on sait ──────────────────────────────────────────────────

  private account(key: string): TeamsAccount | null {
    return this.accounts.find((a) => a.key === key) ?? null;
  }

  private conv(key: string): Conversation | null {
    return this.conversations.find((c) => c.key === key) ?? null;
  }

  private visible(): boolean {
    return !!this.section && !this.section.hidden && pageShown();
  }

  private onDiscussions(): boolean {
    return this.mounted === "discussions" && !!this.body;
  }

  /** La personne de ce compte, à son nom (pour mettre sa mention en valeur) : la tienne sur un compte à toi ; sur un
   *  compte qu'on te partage, celle de son propriétaire — jamais ton nom à toi. */
  private selfName(account: string): string {
    const a = this.account(account);
    return a?.self_name || (ownAccount(a) ? this.shell.user.displayName : a?.owner_name) || "";
  }

  private waitingCount(): number {
    return this.replies.filter((r) => r.state === "attend" && !r.answered && capsOf(this.account(r.account)).decide).length;
  }

  // ── Le cadre ───────────────────────────────────────────────────────

  private actions(): string {
    const a = this.account(this.thread?.account ?? this.conv(this.open)?.account ?? "") ?? this.accounts[0] ?? null;
    if (!a) return "";
    return `${extensionChip(a, Date.now())}
      <button class="btn sm" type="button" data-mode-teams title="Comment part ce qu'elle prépare">${ico("send", "sm")}<span class="lbl">Comment ça part</span>${ico("chev-down", "sm")}</button>`;
  }

  private render(body: HTMLElement, ctx: ScreenContext): void {
    this.body = body;
    const tab = ctx.tab === "brouillons" ? "brouillons" : "discussions";
    if (this.mounted !== tab || !$("[data-tm-root]", body)) {
      // le corps change d'onglet : ce que tu écrivais (ton message, ta version d'une réponse) est gardé avant
      this.keepTyped();
      this.mounted = tab;
      if (tab === "discussions") {
        body.innerHTML = DISCUSSIONS_SKELETON;
        this.paintDiscussions();
      } else this.paintReplies();
    }
    if (!this.started) {
      this.started = true;
      this.accountsReady = this.loadAccounts();
      this.fresh.fresh();
      void this.start();
    } else this.fresh.back();
    if (tab === "discussions") this.route(ctx.item);
    else this.routeReply(ctx.item);
  }

  private async start(): Promise<void> {
    // « Corriger » (ADR 0307) dépend de ce que dit `GET /api/moi` : lu ici aussi, l'écran peut s'ouvrir sur Teams
    void me.load().then(() => this.paintDock(), () => undefined);
    await Promise.all([this.accountsReady, this.loadReplies()]);
    await this.loadConversations();
    if (this.onDiscussions() && !this.open && this.conversations[0] && !isMobile()) this.select(this.conversations[0].key, false);
  }

  /** Tout ce qu'il montre, relu : revenu sur l'écran (ou l'onglet) après un changement manqué, ou à une ouverture de
   *  la connexion (ADR 0308 : rien n'est rattrapé). */
  private async refresh(): Promise<void> {
    await Promise.all([this.accountsRead.run(), this.repliesRead.run(), this.convsRead.run()]);
    await this.threadRead.run();
  }

  /** Les âges, toutes les 30 s et d'ici (`shell/ages.ts`) : la pastille « Extension » (son dernier signe de vie, son
   *  dernier lot), le panneau d'informations, et l'avertissement du champ quand elle se tait — sauf si tu écris dans
   *  le champ : il attend le pas suivant. */
  private agesTick(): void {
    if (!this.started || !this.visible()) return;
    this.shell.refreshHead();
    if (!this.onDiscussions() || !this.thread) return;
    this.paintInfo();
    const dock = $<HTMLElement>("[data-tm-dock]", this.body!);
    if (!dock?.contains(document.activeElement)) this.paintDock();
  }

  /** `teams` (des conversations) : ses comptes (leurs niveaux, son extension), la liste, le fil ouvert s'il est nommé. */
  private teamsChanged(convs: Changed): void {
    void this.accountsRead.run();
    void this.convsRead.run();
    if (this.onDiscussions() && this.open && names(convs, this.open)) void this.threadRead.run();
  }

  // ── Charger ────────────────────────────────────────────────────────

  /** Ce qui, des comptes, décide de ce que le fil et le tableau offrent (le niveau, à qui) — pas leur dernier lot,
   *  qui bouge à chaque passage de l'extension. */
  private accountsShape(): string {
    return JSON.stringify([this.enabled, this.accounts.map((a) => [a.key, a.level, a.owner_name, a.name, a.self_name])]);
  }

  private async loadAccounts(): Promise<void> {
    const before = this.accountsShape();
    let read = false;
    try {
      const got = await fetchAccounts();
      this.accounts = got.accounts;
      this.plugged = got.plugged;
      this.enabled = got.enabled;
      this.accountsError = "";
      read = true;
    } catch (err) {
      this.accountsError = errorText(err);
    }
    this.accountsLoaded = true;
    // le compte du fil ouvert n'est plus à toi (retiré, plus partagé) : le fil se ferme, la liste reste
    if (read && this.open && threadGone(this.thread?.account ?? this.conv(this.open)?.account, this.accounts)) this.closeThread();
    this.shell.refreshHead();
    if (this.accountsShape() !== before) {
      // un niveau arrivé (ou changé) après le fil ou le tableau : le champ, ses cartes et « Ses brouillons » le suivent
      if (this.onDiscussions() && this.thread) this.keepingFocus(() => this.paintThreadPane());
      else if (this.mounted === "brouillons" && this.repliesLoaded) this.paintReplies();
    } else if (this.onDiscussions() && this.thread) {
      // l'extension s'est manifestée (ou tait depuis trop longtemps) : la ligne du champ qui le dit, rien d'autre
      this.paintDock();
    }
  }

  private async loadConversations(): Promise<void> {
    if (!this.accounts.length) {
      this.conversations = [];
      this.convsLoaded = true;
      this.paintConversations();
      if (this.onDiscussions()) this.paintThreadPane();
      return;
    }
    try {
      this.conversations = await fetchConversations({ q: this.q.trim(), size: 100 });
      this.convsError = "";
    } catch (err) {
      this.convsError = errorText(err);
    }
    this.convsLoaded = true;
    this.paintConversations();
  }

  private async loadReplies(): Promise<void> {
    try {
      // le niveau de chaque compte décide de ce que le tableau offre (décider ou non) : ses comptes d'abord
      const [items] = await Promise.all([fetchReplies(), this.accountsReady]);
      this.replies = items;
    } catch (err) {
      if (this.mounted === "brouillons") toast(errorText(err), { ico: "alert" });
      return;
    } finally {
      this.repliesLoaded = true;
    }
    const n = this.waitingCount();
    if (this.tabs[1].count !== (n || undefined)) {
      this.tabs[1].count = n || undefined;
      this.shell.refreshHead();
    }
    if (this.mounted === "brouillons") this.paintReplies();
  }

  private async loadThread(quiet = false): Promise<void> {
    const key = this.open;
    if (!key) return;
    const seq = ++this.threadSeq;
    if (!quiet) {
      this.thread = null;
      this.threadError = "";
      this.older = [];
      this.olderMore = false;
      this.paintThreadPane();
    }
    try {
      const started = Date.now();
      // le niveau du compte décide de ce que le champ et les cartes offrent : ses comptes d'abord (ADR 0188)
      const [t] = await Promise.all([fetchThread(key, { size: 50 }), this.accountsReady]);
      if (seq !== this.threadSeq || this.open !== key) return;
      const before = this.thread && this.thread.key === t.key ? this.thread : null;
      if (quiet && before) {
        // ce qui sort de la page des plus récents (des messages arrivés entre-temps) reste affiché, plus haut
        const fresh = new Set(t.messages.map((m) => m.ref));
        const kept = [...this.older, ...before.messages].filter((m) => !fresh.has(m.ref));
        if (kept.length && !this.older.length) this.olderMore = before.more;
        this.older = kept;
      }
      this.thread = t;
      this.threadError = "";
      // tes envois d'ici : le moteur dit maintenant ce qu'ils sont devenus (`pending`), ou ils sont revenus dans le fil
      const sent = stillSentHere(this.sent, t, started);
      const settled = sent.length !== this.sent.length;
      this.sent = sent;
      // elle a fini (ou renoncé) : le moteur ne dit plus qu'on le lui a demandé
      if (before?.asked && !t.asked) this.asked.delete(key);
      if (quiet && before && !settled && sameThread(before, t)) {
        // rien de neuf : où elle en est a pu changer (sa ligne seule)
        this.paintDock();
        this.settleAsk();
        return;
      }
      const arrived = quiet && !!before && t.replies.some((r) => UNDER_WAY.has(r.state) && !r.answered && !before.replies.some((x) => x.id === r.id));
      if (arrived) {
        this.asked.delete(key);
        toast("Sa réponse est arrivée : elle t'attend dans la discussion.", { mika: true });
        void this.loadReplies();
        void refreshCounts();
      }
      if (quiet && before) {
        this.paintMessages(false);
        // « Elle s'y met… », ce que « Préremplir » répond, ce qui part : le champ suit le fil
        this.paintDock();
      } else {
        // le premier fil lu (ou relu après une erreur) : tout le panneau
        this.paintThreadPane();
        this.shell.refreshHead();
      }
      this.settleAsk();
    } catch (err) {
      if (seq !== this.threadSeq) return;
      if (!quiet) {
        this.threadError = errorText(err);
        this.paintThreadPane();
      }
    }
  }

  /** Une image d'un message, en grand (ADR 0258) : « précédente » et « suivante », les flèches du clavier aussi ;
   *  Échap la ferme (le cadre). */
  private openImage(ref: string, index: number): void {
    const m = [...this.older, ...(this.thread?.messages ?? [])].find((x) => x.ref === ref);
    const count = m ? imagesInOrder(m).length : 0;
    if (!m || !count) return;
    let at = index;
    const title = `${authorLabel(m, this.account(this.thread?.account ?? ""))} · ${dayAndClock(m.at, Date.now())}`;
    const el = openModal({ title, size: "wide", body: imageViewer(m, at) });
    el.classList.add("viewer-modal");
    const body = $<HTMLElement>(".modal-body", el);
    const show = (delta: number): void => {
      at = (at + delta + count) % count;
      if (body) body.innerHTML = imageViewer(m, at);
    };
    on(el, "[data-vw]", "click", (_e, b) => show(Number(b.dataset.vw) < 0 ? -1 : 1));
    el.tabIndex = -1;
    el.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") show(-1);
      else if (e.key === "ArrowRight") show(1);
    });
    window.setTimeout(() => el.focus(), 30);
  }

  private async loadOlder(): Promise<void> {
    const t = this.thread;
    if (!t || this.loadingOlder) return;
    const first = this.older[0] ?? t.messages[0];
    if (!first) return;
    this.loadingOlder = true;
    this.paintMessages(false);
    const scroll = this.body && $<HTMLElement>("[data-scroll]", this.body);
    const fromBottom = scroll ? scroll.scrollHeight - scroll.scrollTop : 0;
    try {
      const got = await fetchThread(t.key, { before: first.at, size: 50 });
      if (this.thread?.key !== t.key) return;
      const known = new Set([...this.older, ...t.messages].map((m) => m.ref));
      this.older = [...got.messages.filter((m) => !known.has(m.ref)), ...this.older];
      this.olderMore = got.more;
    } catch (err) {
      toast(errorText(err), { ico: "alert" });
    }
    this.loadingOlder = false;
    this.paintMessages(false);
    if (scroll) scroll.scrollTop = scroll.scrollHeight - fromBottom;
  }

  // ── Les routes ─────────────────────────────────────────────────────

  private route(item: string | null): void {
    if (!item) {
      if (this.reading) {
        this.reading = false;
        this.paintSplit();
      }
      // sur un grand écran, la plus récente s'ouvre d'elle-même (rien ne se marque en l'ouvrant)
      if (!this.open && this.conversations[0] && !isMobile()) this.select(this.conversations[0].key, false);
      return;
    }
    this.reading = true;
    if (item !== this.open) this.select(item, true);
    else this.paintSplit();
  }

  /** Le fil ouvert se ferme (son compte n'est plus à toi) : l'adresse revient à la liste, la discussion est oubliée. */
  private closeThread(): void {
    this.open = "";
    this.thread = null;
    this.threadError = "";
    this.threadSeq += 1; // une lecture du fil encore en vol n'y revient pas
    this.older = [];
    this.olderMore = false;
    this.editing = "";
    this.editText = "";
    this.reading = false;
    if (/^#teams\/discussions\/./.test(location.hash)) history.replaceState(null, "", "#teams/discussions");
    this.paintSelection();
    this.paintThreadPane();
  }

  private select(key: string, reading: boolean): void {
    this.open = key;
    this.editing = "";
    this.editText = "";
    this.reading = reading;
    this.paintSelection();
    this.shell.refreshHead();
    void this.loadThread();
  }

  // ── Peindre ────────────────────────────────────────────────────────

  private paintDiscussions(): void {
    this.paintListHead();
    this.paintConversations();
    this.paintThreadPane();
    this.paintSplit();
  }

  private paintSplit(): void {
    if (!this.onDiscussions()) return;
    const split = $(".tm-split", this.body!);
    split?.classList.toggle("lire", this.reading);
    split?.classList.toggle("with-info", this.info && !!this.open && !!this.thread);
    const info = $<HTMLElement>("[data-tm-info]", this.body!);
    if (info) info.hidden = !(this.info && !!this.open && !!this.thread);
  }

  private paintListHead(): void {
    if (!this.onDiscussions()) return;
    const head = $("[data-tm-list-head]", this.body!);
    if (head) head.innerHTML = listHead(this.filter, this.searching, this.q);
  }

  private shownConversations(): Conversation[] {
    return this.conversations.filter((c) => this.filter === "tout" || (this.filter === "elle" ? !!c.her : !!c.last?.mentions_me));
  }

  private paintConversations(): void {
    if (!this.onDiscussions()) return;
    const host = $("[data-tm-convs]", this.body!);
    if (!host) return;
    const now = Date.now();
    const many = this.accounts.length > 1;
    let html: string;
    if (!this.plugged) html = `<div class="empty">${ico("teams")}<b>Teams n'est pas branché</b><p>Ce serveur n'a pas Teams.</p></div>`;
    else if (this.accountsError) html = `<div class="empty">${ico("alert")}<b>Tes comptes ne se lisent pas</b><p>${h(this.accountsError)}</p></div>`;
    else if (this.accountsLoaded && !this.accounts.length)
      html = `<div class="empty">${ico("teams")}<b>Aucun compte Teams</b><p>Branche le tien dans Paramètres › Teams : l'extension « Mika · Teams » lira ce que Teams web reçoit.</p><a class="btn sm" href="#parametres/teams">${ico("settings", "sm")}Paramètres › Teams</a></div>`;
    else if (!this.convsLoaded) html = `<div class="empty">${ico("refresh")}<b>Chargement…</b></div>`;
    else if (this.convsError) html = `<div class="empty">${ico("alert")}<b>Les discussions ne se lisent pas</b><p>${h(this.convsError)}</p></div>`;
    else {
      const list = this.shownConversations();
      html = list.length
        ? list.map((c) => conversationRow(c, this.open, now, many, this.account(c.account))).join("")
        : this.q
          ? `<div class="empty">${ico("search")}<b>Rien trouvé</b><p>Aucune discussion ne s'appelle « ${h(this.q)} ».</p></div>`
          : `<div class="empty">${ico("teams")}<b>Rien ici</b><p>${this.filter === "tout" ? "L'extension n'a encore vu aucune discussion : installe « Mika · Teams » avec la clé de ton compte (Paramètres › Teams), puis ouvre Teams web." : "Aucune discussion pour ce filtre."}</p></div>`;
    }
    const scroll = host.scrollTop;
    host.innerHTML = html;
    host.scrollTop = scroll;
  }

  private paintSelection(): void {
    if (!this.onDiscussions()) return;
    for (const el of $$<HTMLElement>("[data-disc]", this.body!)) el.setAttribute("aria-selected", String(el.dataset.disc === this.open));
  }

  private threadView(t: Thread): ThreadView {
    const a = this.account(t.account);
    return {
      now: Date.now(),
      selfName: this.selfName(t.account),
      caps: capsOf(a),
      owner: a?.owner_name ?? "",
      account: a,
      editing: this.editing,
      // ce que le moteur dit de tes messages en attente (en file, posé, pas parti), puis tes envois d'ici pas encore dits
      pending: ownBubbles(t.pending, this.sent.filter((p) => p.conversation === t.key), sentUnder(a)),
    };
  }

  private lastReceived(t: Thread): TeamsMessage | null {
    const all = [...this.older, ...t.messages];
    for (let i = all.length - 1; i >= 0; i--) if (!all[i].own) return all[i];
    return null;
  }

  private paintThreadPane(): void {
    if (!this.onDiscussions()) return;
    const host = $("[data-tm-conv]", this.body!);
    if (!host) return;
    this.keepTyped(); // avant tout dessin : même une discussion qui ne s'ouvre pas ne perd pas ce qu'on tapait
    const t = this.thread;
    const c = this.conv(this.open);
    if (!this.open || (!t && !c && !this.threadError)) {
      host.innerHTML = this.accountsLoaded && !this.accounts.length
        ? `<div class="empty">${ico("teams")}<b>Tes discussions arrivent ici</b><p>Une fois ton compte branché, avec Teams web ouvert et l'extension installée.</p></div>`
        : `<div class="empty">${ico("teams")}<b>Choisis une discussion</b><p>Elle s'ouvre ici, comme dans Teams.</p></div>`;
      this.paintSplit();
      return;
    }
    if (this.threadError) {
      host.innerHTML = `<div class="pane-head thread-head"><button class="btn sm icon ghost mobile-back" type="button" data-retour title="Les discussions">${ico("chev-left", "sm")}</button><div class="grow"><h2>${h(c?.title ?? "")}</h2></div></div>
        <div class="empty">${ico("alert")}<b>Cette discussion ne s'ouvre pas</b><p>${h(this.threadError)}</p></div>`;
      this.paintSplit();
      return;
    }
    const conv = t ?? c!;
    const a = this.account(conv.account);
    const shared = !!a && a.level !== "proprietaire";
    const sub = [kindLabel(conv.kind), this.accounts.length > 1 || shared ? `compte ${a?.name ?? conv.account}${shared && a.owner_name ? ` ${ofName(a.owner_name)}` : ""}` : ""].filter(Boolean).join(" · ");
    // sa photo (ADR 0300) : celle que dit le fil, sinon la liste (un moteur qui ne la dit pas dans le fil)
    const photo = t?.photo || c?.photo || "";
    host.innerHTML = `<div class="pane-head thread-head" data-tm-head>${threadHead({ conv: { title: conv.title, kind: conv.kind, key: conv.key, photo }, sub, infoOpen: this.info })}</div>
      <div class="chat-scroll" data-scroll><div class="tm-msgs" data-tm-msgs></div></div>
      <div class="tm-dock" data-tm-dock></div>`;
    this.paintMessages(true);
    this.paintDock();
    this.paintInfo();
    this.paintSplit();
  }

  private paintMessages(toBottom: boolean): void {
    if (!this.onDiscussions()) return;
    const host = $("[data-tm-msgs]", this.body!);
    const scroll = $<HTMLElement>("[data-scroll]", this.body!);
    const t = this.thread;
    if (!host || !scroll) return;
    if (!t) {
      host.innerHTML = `<div class="empty tm-empty">${ico("refresh")}<b>Chargement…</b></div>`;
      return;
    }
    const atBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 40;
    // ta version d'une réponse qu'on retouche : celle du champ, sinon celle qu'on avait gardée (un autre onglet)
    const editingText = $<HTMLTextAreaElement>("[data-rep-texte]", host)?.value ?? (this.editing && this.editText ? this.editText : undefined);
    host.innerHTML = threadBody(t, this.older, this.threadView(t), this.loadingOlder, this.olderMore);
    if (editingText !== undefined) {
      const area = $<HTMLTextAreaElement>("[data-rep-texte]", host);
      if (area) area.value = editingText;
    }
    if (toBottom || atBottom) scroll.scrollTop = scroll.scrollHeight;
    this.paintInfo();
  }

  private paintDock(): void {
    if (!this.onDiscussions()) return;
    const host = $("[data-tm-dock]", this.body!);
    const t = this.thread;
    if (!host) return;
    if (!t) {
      host.innerHTML = "";
      return;
    }
    const a = this.account(t.account);
    const now = Date.now();
    // elle est là si elle s'est manifestée (un relevé, la connexion en direct), pas seulement si elle a poussé du neuf :
    // un dimanche sans message, le dernier lot vieillit sans qu'elle soit partie (le 2026-11-22)
    const seen = a ? Math.max(a.last_seen || 0, a.last_batch || 0) : 0;
    const quiet = !seen
      ? "L'extension de ce compte ne s'est encore jamais manifestée : rien ne partira tant que Teams web n'est pas ouvert avec elle."
      : now - seen > QUIET_MS
        ? `L'extension ne s'est pas manifestée depuis ${ago(seen, now).replace("il y a ", "")} : ce qui part attend que Teams web soit ouvert avec elle.`
        : "";
    // Teams coupé, ou ce compte décoché : rien n'en part, et elle n'y prépare rien (l'API refuse « Préremplir », 409)
    const off = !this.enabled ? "Teams est désactivé" : a && !a.enabled ? "Ce compte Teams est décoché" : "";
    const view: DockView = {
      title: t.title,
      caps: capsOf(a),
      owner: a?.owner_name ?? "",
      level: a?.level ?? "lire",
      asked: this.asked.has(t.key) || t.asked,
      underWay: t.under_way,
      canPrefill: !!this.lastReceived(t) && !off,
      prefillOff: off ? `${off} : elle n'y prépare rien.` : "",
      quiet: !this.enabled ? "Teams est désactivé : rien ne part." : off ? `${off} : rien n'en part.` : quiet,
      sending: this.sending,
      quoting: this.quoting?.conversation === t.key
        ? { author: this.quoting.author, at: this.quoting.at, preview: this.quoting.preview } : null,
      work: t.work ?? null,
      correct: canCorrect(),
    };
    // rien de changé dans ce qu'il montre : le champ reste tel quel (le focus, une saisie en cours de composition) ;
    // où elle en est (ADR 0306) change à chaque étape : sa ligne se repeint seule, dans sa case
    const sig = `${t.key}|${JSON.stringify({ ...view, work: null })}`;
    if (sig === this.dockSig && host.firstElementChild) {
      this.paintWork(host, view);
      return;
    }
    this.dockSig = sig;
    this.keepTyped();
    this.keepingFocus(() => {
      host.innerHTML = dock(view);
      const input = $<HTMLTextAreaElement>("[data-tm-input]", host);
      if (input) {
        input.dataset.for = t.key;
        input.value = this.typed.get(t.key) ?? "";
        paintCount(input);
      }
    });
    this.paintWork(host, view);
  }

  /** Où elle en est ici (ADR 0306), dans sa case au-dessus du champ : repeinte quand l'étape change, son chrono
   *  court seul (`tickWork`). */
  private paintWork(host: HTMLElement, view: DockView): void {
    const slot = $<HTMLElement>("[data-tm-work]", host);
    if (!slot) return;
    const sig = JSON.stringify([view.work, view.asked, view.underWay]);
    if (slot.dataset.sig === sig) return;
    slot.dataset.sig = sig;
    slot.innerHTML = dockWork(view);
    if (view.work && !view.underWay) tickWork();
  }

  /** Redessiner sans voler la saisie : le champ qui avait le focus le retrouve, son curseur à sa place. */
  private keepingFocus(paint: () => void): void {
    const active = document.activeElement;
    const input = active instanceof HTMLTextAreaElement && active.matches("[data-tm-input]") ? active : null;
    const range = input ? ([input.selectionStart, input.selectionEnd] as const) : null;
    paint();
    if (!input || !range || input.isConnected || !this.body) return;
    const next = $<HTMLTextAreaElement>("[data-tm-input]", this.body);
    if (!next) return;
    next.focus();
    next.setSelectionRange(range[0], range[1]);
  }

  /** Ce qui est tapé dans le champ (et ta version d'une réponse qu'on retouche), gardé pour sa discussion avant de
   *  le redessiner ou de changer d'onglet. */
  private keepTyped(): void {
    const area = this.body && $<HTMLTextAreaElement>("[data-rep-texte]", this.body);
    if (area && this.editing) this.editText = area.value;
    const input = this.body && $<HTMLTextAreaElement>("[data-tm-input]", this.body);
    if (!input?.dataset.for) return;
    if (input.value) this.typed.set(input.dataset.for, input.value);
    else this.typed.delete(input.dataset.for);
  }

  private people(t: Thread): InfoView["people"][number][] {
    const map = new Map<string, InfoView["people"][number]>();
    for (const m of [...this.older, ...t.messages]) {
      const key = m.own ? "__toi" : m.author_id || m.author;
      const got = map.get(key);
      if (got) {
        got.count += 1;
        // la photo la plus récente de qui a écrit (ADR 0300) : celle de son dernier message qui en porte une
        got.photo = m.photo || got.photo;
      } else map.set(key, { name: m.author, key: m.author_id || m.author, own: m.own, count: 1, photo: m.photo ?? "" });
    }
    return [...map.values()].sort((a, b) => Number(a.own) - Number(b.own) || b.count - a.count);
  }

  private paintInfo(): void {
    if (!this.onDiscussions()) return;
    const host = $<HTMLElement>("[data-tm-info]", this.body!);
    const t = this.thread;
    if (!host || !t || !this.info) return;
    const c = this.conv(t.key);
    const scroll = $<HTMLElement>(".pane-scroll", host)?.scrollTop ?? 0;
    host.innerHTML = infoPane({
      conv: { title: t.title, kind: t.kind, key: t.key, messages: c?.messages ?? t.messages.length },
      people: this.people(t),
      selfName: this.selfName(t.account),
      account: this.account(t.account),
      replies: t.replies,
      now: Date.now(),
    });
    // repeint (ses âges, un participant de plus) : là où on l'avait fait défiler
    const fresh = $<HTMLElement>(".pane-scroll", host);
    if (fresh) fresh.scrollTop = scroll;
  }

  private paintReplies(): void {
    if (this.mounted !== "brouillons" || !this.body) return;
    // le corps passe au tableau : ce qui était tapé dans la discussion est gardé avant de disparaître
    this.keepTyped();
    if (!this.repliesLoaded) {
      this.body.innerHTML = `<div class="fill-scroll" data-tm-root="brouillons"><div class="empty">${ico("refresh")}<b>Chargement…</b></div></div>`;
      return;
    }
    const scroll = $(".fill-scroll", this.body)?.scrollTop ?? 0;
    const convs = new Map(this.conversations.map((c) => [c.key, c]));
    this.body.innerHTML = repliesTable(this.replies, { now: Date.now(), convs, decide: (r) => capsOf(this.account(r.account)).decide, focus: this.focusReply });
    const root = $(".fill-scroll", this.body);
    if (root) {
      root.setAttribute("data-tm-root", "brouillons");
      root.scrollTop = scroll;
    }
    this.revealReply();
  }

  /** `#teams/brouillons/<id>` : la réponse désignée se surligne ; `#teams/brouillons`, plus aucune. */
  private routeReply(item: string | null): void {
    const id = item ?? "";
    if (id === this.focusReply) return;
    this.focusReply = id;
    this.focusShown = false;
    if (this.repliesLoaded) this.paintReplies();
  }

  /** Une fois la liste lue : on défile jusqu'à la réponse désignée (une seule fois), ou on dit qu'elle n'y est plus. */
  private revealReply(): void {
    if (!this.focusReply || this.focusShown || !this.repliesLoaded || !this.body) return;
    this.focusShown = true;
    const row = $(`[data-reply-row="${CSS.escape(this.focusReply)}"]`, this.body);
    if (row) row.scrollIntoView({ block: "center" });
    else toast("Cette réponse n'est plus dans « Ses brouillons ».", { ico: "info" });
  }

  // ── Demander, où elle en est ───────────────────────────────────────

  /** Le fil lu : sa réponse est arrivée ici, on ne dit plus qu'on la lui a demandée. */
  private settleAsk(): void {
    const t = this.thread;
    if (t?.under_way) this.asked.delete(t.key);
  }

  /** Où elle en est d'une réponse ici, demandée ou d'elle-même (ADR 0306) : le direct pousse chaque étape qui commence
   *  (`teams.work`, ADR 0308), on relit alors `work`, sans relire le fil ; le fil se relit quand sa réponse arrive, ou
   *  quand elle a fini sans en rendre. */
  private async rereadWork(): Promise<void> {
    const key = this.open;
    if (!key || this.thread?.key !== key) return;
    let got: ThreadWork;
    try {
      got = await fetchThreadWork(key);
    } catch {
      return; // le prochain changement relira
    }
    const t = this.thread;
    if (this.open !== key || !t || t.key !== key) return;
    if (got.under_way || (!got.asked && !got.work)) {
      // sa réponse est arrivée, ou elle a fini sans en rendre : le fil, ses réponses, le champ et les compteurs
      this.asked.delete(key);
      void this.threadRead.run();
      return;
    }
    t.work = got.work;
    t.asked = got.asked;
    this.paintDock();
  }

  private async prefillHere(): Promise<void> {
    const t = this.thread;
    if (!t) return;
    const last = this.lastReceived(t);
    if (!last) {
      toast("Aucun message reçu à quoi répondre ici.", { ico: "info" });
      return;
    }
    try {
      const got = await prefill(last.ref);
      if (got.draft) {
        toast("Une réponse d'elle est déjà en chemin dans cette discussion.", { mika: true });
        this.body && $(`[data-reply-card="${CSS.escape(got.draft)}"]`, this.body)?.scrollIntoView({ block: "center", behavior: "smooth" });
        return;
      }
      const now = Date.now();
      this.asked.set(t.key, now);
      // elle s'y met tout de suite (ADR 0306) : sa ligne paraît sans attendre que le direct dise son étape (ADR 0308)
      t.asked = true;
      t.work ??= { step: "waiting", label: "", since: now, started: now };
      toast(got.message === "Elle y travaille déjà." ? got.message : "Demandé : elle s'y met tout de suite ; sa réponse arrivera ici.", { mika: true });
      this.paintDock();
    } catch (err) {
      toast(errorText(err), { ico: "alert" });
    }
  }

  // ── Écrire ─────────────────────────────────────────────────────────

  /** Citer un message de la discussion ouverte (ADR 0305), comme « Citer » dans Teams : sa carte au-dessus du champ,
   *  le champ prêt à écrire ; `""` : ne plus citer. */
  private quote(ref: string): void {
    const t = this.thread;
    const m = ref && t ? t.messages.find((x) => x.ref === ref) : undefined;
    this.quoting = m && t
      ? { conversation: t.key, ref: m.ref, author: authorLabel(m, this.account(t.account) ?? null), at: m.at,
          preview: m.text.replace(/\s+/g, " ").trim().slice(0, 300) }
      : null;
    this.paintDock();
    const input = this.body && $<HTMLTextAreaElement>("[data-tm-input]", this.body);
    input?.focus();
  }

  /** Aller au message qu'une citation cite, s'il est dans le fil chargé : il défile jusqu'à lui et s'éclaire. */
  private goToMessage(ref: string): void {
    const target = ref && this.body ? $<HTMLElement>(`.tm-msg[data-ref="${CSS.escape(ref)}"]`, this.body) : null;
    if (!target) {
      toast("Ce message n'est plus dans ce qui est chargé ici.", { ico: "info" });
      return;
    }
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    target.classList.remove("flash");
    void target.offsetWidth;
    target.classList.add("flash");
  }

  private async send(): Promise<void> {
    const t = this.thread;
    const input = this.body && $<HTMLTextAreaElement>("[data-tm-input]", this.body);
    if (!t || !input || this.sending) return;
    const text = input.value.trim();
    if (!text) return;
    if (toFill(text)) {
      toast("Il reste des passages [À COMPLÉTER] à remplir.", { ico: "alert" });
      return;
    }
    if (chars(text) > MAX_CHARS) {
      // l'API le refuserait (rien ne part coupé) : le dire avant
      toast(`Ton message est trop long : ${thousands(MAX_CHARS)} caractères au plus (il en a ${thousands(chars(text))}).`, { ico: "alert", duration: 4200 });
      return;
    }
    this.sending = true;
    const button = $<HTMLButtonElement>('[data-tm="envoyer"]', this.body!);
    if (button) button.disabled = true;
    try {
      // la citation en cours part avec lui (ADR 0305) : le serveur la fait dans Teams
      const quoted = this.quoting?.conversation === t.key ? this.quoting.ref : "";
      const done = await sendMessage(t.key, text, quoted, newNonce());
      if (quoted && this.quoting?.ref === quoted) {
        this.quoting = null;
        this.paintDock();
      }
      // le champ de cette discussion tel qu'il est maintenant : un rafraîchissement a pu le redessiner pendant
      // l'envoi, avec ce texte dedans ; le texte parti s'en retire, ce qu'on a tapé depuis reste
      const now = this.body && $<HTMLTextAreaElement>("[data-tm-input]", this.body);
      for (const field of new Set([input, now])) {
        const rest = field?.isConnected && field.dataset.for === t.key ? withoutSent(field.value, text) : null;
        if (field && rest !== null) {
          field.value = rest;
          paintCount(field);
        }
      }
      const kept = withoutSent(this.typed.get(t.key) ?? "", text);
      if (kept === "") this.typed.delete(t.key);
      else if (kept !== null) this.typed.set(t.key, kept);
      this.sent.push({ conversation: t.key, text, at: Date.now() });
      toast(done.message || "En file : l'extension de ce compte l'enverra dans Teams.", { ico: "send" });
      if (t.replies.some((r) => r.state === "attend" && !r.answered)) {
        // sa réponse qui attendait ici ne partira plus (ADR 0199) : « Ses brouillons » et les pastilles le suivent
        void this.loadReplies();
        void refreshCounts();
      }
      if (this.thread?.key === t.key) {
        this.paintMessages(true);
        // ce que le moteur en dit (en file, puis parti ou pas) remplace aussitôt la bulle d'ici
        void this.loadThread(true);
      }
    } catch (err) {
      toast(errorText(err), { ico: "alert", duration: 4200 });
    }
    this.sending = false;
    if (button) button.disabled = false;
    this.paintDock(); // un dessin fait pendant l'envoi a éteint son bouton : il se rallume
  }

  /** « Le réécrire » : le texte d'un de tes messages qui n'est pas parti revient dans le champ, pour le renvoyer. */
  private rewrite(id: string): void {
    const p = this.thread?.pending?.find((x) => x.id === id);
    const input = this.body && $<HTMLTextAreaElement>("[data-tm-input]", this.body);
    if (!p || !input) return;
    if (input.value.trim() && input.value.trim() !== p.body.trim()) {
      toast("Ton champ n'est pas vide : envoie ou efface d'abord ce que tu y as écrit.", { ico: "info" });
      input.focus();
      return;
    }
    input.value = p.body;
    paintCount(input);
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }

  private emojis(anchor: HTMLElement): void {
    const menu = openMenu(anchor, [{ html: `<div class="emoji-grid">${EMOJIS.map((e) => `<button type="button" data-emo="${e}">${e}</button>`).join("")}</div>` }], { align: "left" });
    on(menu, "[data-emo]", "click", (_e, b) => {
      const input = this.body && $<HTMLTextAreaElement>("[data-tm-input]", this.body);
      if (!input) return;
      const next = insertEmoji(input.value, input.selectionStart ?? input.value.length, input.selectionEnd ?? input.value.length, b.dataset.emo ?? "", MAX_CHARS);
      if (!next) return;
      input.value = next.value;
      paintCount(input);
      input.focus();
      input.setSelectionRange(next.caret, next.caret);
    });
  }

  // ── Ses réponses : décider ─────────────────────────────────────────

  private findReply(id: string): Reply | null {
    return this.thread?.replies.find((r) => r.id === id) ?? this.replies.find((r) => r.id === id) ?? null;
  }

  private async afterDecision(): Promise<void> {
    await Promise.all([this.loadReplies(), this.open ? this.loadThread(true) : Promise.resolve(), this.loadConversations()]);
    void refreshCounts();
    if (this.onDiscussions()) this.paintDock();
  }

  private async decide(kind: string, r: Reply): Promise<void> {
    if (kind === "envoyer") {
      if (!r.preview || r.preview.blocked) return;
      try {
        const done = await sendReply(r.id, r.preview.digest, newNonce());
        toast(done.message, { ico: "send" });
      } catch (err) {
        toast(errorText(err), { ico: "alert" });
      }
      await this.afterDecision();
      return;
    }
    if (kind === "retoucher") {
      if (this.onDiscussions() && this.thread?.replies.some((x) => x.id === r.id)) {
        this.editing = r.id;
        this.editText = "";
        this.paintMessages(false);
        const area = this.body && $<HTMLTextAreaElement>("[data-rep-texte]", this.body);
        area?.focus();
        return;
      }
      this.editModal(r);
      return;
    }
    if (kind === "refuser") {
      openAsk({
        title: "Refuser sa réponse",
        lede: `« ${r.body.slice(0, 140)} » ne partira pas ; elle le saura. Dis-lui pourquoi, si tu veux.`,
        label: "Pourquoi (facultatif)",
        placeholder: "« pas besoin de répondre », « je préfère le dire moi-même »…",
        required: false,
        max: TEAMS_LIMITS.note,
        submitLabel: "Refuser",
        danger: true,
        submit: async (note) => {
          const done = await refuseReply(r.id, note);
          await this.afterDecision();
          return done.message;
        },
      });
      return;
    }
    if (kind === "reprendre") {
      openAsk({
        title: "Lui demander de la reprendre",
        lede: "Celle-ci est refusée ; elle en écrit une autre tout de suite, en tenant compte de ce que tu dis.",
        label: "Ce qu'il faut changer",
        placeholder: "« plus court », « propose plutôt 16 h »…",
        required: true,
        max: TEAMS_LIMITS.instruction,
        submitLabel: "Lui demander",
        mika: true,
        submit: async (instruction) => {
          const done = await redoReply(r.id, instruction);
          this.asked.set(r.conversation, Date.now());
          await this.afterDecision();
          return done.message;
        },
      });
    }
  }

  private async saveEdit(r: Reply, body: string): Promise<boolean> {
    const text = body.trim();
    if (!text) {
      toast("Sa réponse ne peut pas être vide.", { ico: "alert" });
      return false;
    }
    try {
      const done = await editReply(r.id, text);
      toast(done.message, { ico: "check" });
      this.editing = "";
      this.editText = "";
      await this.afterDecision();
      return true;
    } catch (err) {
      toast(errorText(err), { ico: "alert" });
      return false;
    }
  }

  private editModal(r: Reply): void {
    const el = openModal({
      title: "Retoucher sa réponse",
      size: "narrow",
      body: `<p class="small text-2 ask-lede">Ta version remplace la sienne (elle apprendra de la différence). Relis-la, puis envoie-la.</p>
        <label class="field"><span>Le message</span><textarea rows="5" data-rep-modal maxlength="${TEAMS_LIMITS.body}">${h(r.body)}</textarea></label>
        <p class="small muted">Sans signature : elle est ajoutée.</p>`,
      foot: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn primary" type="button" data-ok>${ico("check", "sm")}Enregistrer ta version</button>`,
    });
    $<HTMLButtonElement>("[data-ok]", el)!.addEventListener("click", async (e) => {
      const button = e.currentTarget as HTMLButtonElement;
      button.disabled = true;
      if (await this.saveEdit(r, $<HTMLTextAreaElement>("[data-rep-modal]", el)!.value)) closeModal();
      else button.disabled = false;
    });
  }

  private moreMenu(anchor: HTMLElement, r: Reply): void {
    const items: MenuItem[] = [
      { label: "Retoucher", icon: "pen", action: () => void this.decide("retoucher", r) },
      ...(r.in_reply_to ? [{ label: "Lui demander de la reprendre", icon: "refresh", action: () => void this.decide("reprendre", r) } as MenuItem] : []),
      "sep",
      { label: "Refuser", icon: "x", danger: true, action: () => void this.decide("refuser", r) },
    ];
    openMenu(anchor, items);
  }

  // ── « Comment ça part » ────────────────────────────────────────────

  private async howItLeaves(anchor: HTMLElement): Promise<void> {
    // la lecture de tes droits que Paramètres et Outils partagent (`api/rights.ts`, gardée 20 s) : relue si la
    // dernière a échoué
    const got = await rights.load(rights.error !== null);
    if (!got) {
      toast(errorText(rights.error), { ico: "alert" });
      return;
    }
    const accounts = got.groups.find((g) => g.key === "accounts")?.resources.filter((r) => r.kind === "teams") ?? [];
    const line = (l: RuleLine, label?: string) =>
      ({ html: `<div class="rule-line"><b>${h(label ?? l.who)}${l.when && l.when !== "toujours" ? ` · ${h(l.when)}` : ""}</b><span>préparer d'elle-même : ${l.prepare ? "oui" : "non"}</span><span>part : ${h(l.reply_words)}</span></div>` }) as MenuItem;
    const items: MenuItem[] = [{ header: "Comment part ce qu'elle prépare" }];
    for (const a of accounts) {
      if (accounts.length > 1) items.push({ header: a.title });
      for (const l of a.rules?.lines ?? []) items.push(line(l));
      if (a.rules?.default) items.push(line(a.rules.default, "par défaut"));
    }
    if (!accounts.length) items.push({ html: '<p class="small muted rule-none">Aucun compte Teams à toi : ce qui part se règle par son propriétaire.</p>' });
    items.push("sep", { label: "Voir tes droits", icon: "shield", action: () => this.shell.go("#outils/droits") });
    openMenu(anchor, items);
  }

  // ── Les gestes ─────────────────────────────────────────────────────

  private mount(section: HTMLElement): void {
    this.section = section;
    bindCounts(section);
    on(section, "[data-disc]", "click", (_e, b) => this.shell.go(conversationHash(b.dataset.disc ?? "")));
    on(section, "[data-retour]", "click", () => {
      this.reading = false;
      this.paintSplit();
      if (/^#teams\/discussions\/./.test(location.hash)) history.replaceState(null, "", "#teams/discussions");
    });
    on(section, "[data-filtre]", "click", (_e, b) => {
      this.filter = (b.dataset.filtre ?? "tout") as Filter;
      this.paintListHead();
      this.paintConversations();
    });
    on(section, "[data-chercher]", "click", () => {
      this.searching = !this.searching;
      if (!this.searching && this.q) {
        this.q = "";
        void this.loadConversations();
      }
      this.paintListHead();
      if (this.searching) $<HTMLInputElement>("[data-tq]", section)?.focus();
    });
    on(section, "[data-info]", "click", () => {
      this.info = !this.info;
      this.paintSplit();
      this.paintInfo();
      const head = $("[data-tm-head] [data-info]", section);
      head?.classList.toggle("on", this.info);
    });
    on(section, "[data-plus-ancien]", "click", () => void this.loadOlder());
    on(section, "[data-tm-img]", "click", (_e, b) => this.openImage(b.dataset.tmRef ?? "", Number(b.dataset.tmImg) || 0));
    on(section, "[data-tm-quote]", "click", (_e, b) => this.quote(b.dataset.tmQuote ?? ""));
    // au doigt (pas de survol) : toucher un message montre sa barre (« Citer »), comme l'appui de Teams mobile
    on(section, ".tm-msg[data-ref]", "click", (e, el) => {
      if (!matchMedia("(hover: none)").matches || (e.target as HTMLElement).closest("button, a, img")) return;
      const open = !el.classList.contains("tools-open");
      for (const other of $$<HTMLElement>(".tm-msg.tools-open", section)) other.classList.remove("tools-open");
      el.classList.toggle("tools-open", open);
    });
    on(section, "[data-tm-goto]", "click", (_e, b) => this.goToMessage(b.dataset.tmGoto ?? ""));
    on(section, "[data-mode-teams]", "click", (_e, b) => void this.howItLeaves(b));
    on(section, "[data-tm]", "click", (_e, b) => {
      const k = b.dataset.tm;
      if (k === "envoyer") void this.send();
      if (k === "preremplir") void this.prefillHere();
      // ADR 0307 : les fautes de ton message, sans changer ses mots (le champ tel qu'il est à l'écran à la fin)
      if (k === "corriger") {
        void correctField(() => (this.body ? $<HTMLTextAreaElement>("[data-tm-input]", this.body) : null),
          b instanceof HTMLButtonElement ? b : null, () => this.open ?? "");
      }
      if (k === "emoji") this.emojis(b);
      if (k === "sans-citation") this.quote("");
      if (k === "reecrire") this.rewrite(b.dataset.pending ?? "");
    });
    on(section, "[data-rep]", "click", (_e, b) => {
      const card = b.closest<HTMLElement>("[data-reply-card]");
      const id = b.dataset.id ?? card?.dataset.replyCard ?? "";
      const r = this.findReply(id);
      if (!r) return;
      const k = b.dataset.rep ?? "";
      if (k === "plus") return this.moreMenu(b, r);
      if (k === "annuler") {
        this.editing = "";
        this.editText = "";
        this.paintMessages(false);
        return;
      }
      if (k === "enregistrer") {
        const area = card && $<HTMLTextAreaElement>("[data-rep-texte]", card);
        if (area) void this.saveEdit(r, area.value);
        return;
      }
      void this.decide(k, r);
    });
    section.addEventListener("input", (e) => {
      const t = e.target as HTMLInputElement;
      if (!t.matches("[data-tq]")) return;
      this.q = t.value;
      window.clearTimeout(this.searchTimer);
      this.searchTimer = window.setTimeout(() => void this.loadConversations(), 250);
    });
    section.addEventListener("keydown", (e) => {
      const t = e.target as HTMLElement;
      if (t.matches("[data-tm-input]") && e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        void this.send();
      }
    });
  }

  // ── La palette ─────────────────────────────────────────────────────

  private searchEntries(): PaletteEntry[] {
    return this.conversations.slice(0, 40).map((c) => ({
      group: "Teams",
      title: c.title || "(sans titre)",
      sub: c.last ? `${authorLabel(c.last, this.account(c.account))} : ${c.last.text}` : kindLabel(c.kind),
      icon: "teams",
      route: conversationHash(c.key),
    }));
  }
}

