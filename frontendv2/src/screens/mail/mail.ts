/**
 * Mail (ADR 0187, 0188, 0191) : ses boîtes à gauche, la liste, la liseuse à côté ; ses brouillons à elle se relisent
 * là, à côté de leur mail ; « Préremplir avec Mika » lui demande une réponse, que la saisie reprend. Ce qu'un niveau
 * de partage ne permet pas n'est pas offert (le serveur refuserait de toute façon). Le contrat :
 * `backendv2/docs/protocole-moi.md` § 3 ; le rendu : `markup.ts`.
 */
import {
  editDraft,
  fetchBoxes,
  fetchContacts,
  fetchDrafts,
  fetchMessage,
  fetchMessages,
  fetchSent,
  fileUrl,
  forwardMail,
  frameUrl,
  pollBox,
  prefill,
  redoDraft,
  refuseDraft,
  replyMail,
  sendDraft,
  sendMail,
  showImages,
  tidy,
  MAIL_LIMITS,
  type Contact,
  type Gesture,
  type MailBox,
  type MailDraft,
  type MailFull,
  type MailRow,
  type MailState,
  type MessagesQuery,
  type Outgoing,
  type ReadOnOpen,
  type SentMail,
} from "../../api/mail";
import { ApiError, type Done } from "../../api/moi";
import { refreshCounts } from "../../shell/counts";
import { $, $$, h, isMobile, norm, on } from "../../shell/dom";
import { openMenu, toast, type MenuItem } from "../../shell/float";
import { ico, type IconName } from "../../shell/icons";
import type { PaletteEntry } from "../../shell/palette";
import type { ScreenContext, ScreenDef, ScreenTab, Shell } from "../../shell/shell";
import { dayAndClock } from "../chat/markup";
import * as store from "../../shared/store";
import { bindCounts, bindPieces, bindRecipients, errorText, openAsk, openCompose, paintPieces, readRecipients, type ComposeValues } from "./compose";
import { answerable, caps, clip, forwardSubject, newNonce, outgoingText, parseAddresses, personName, replySubject, replyTargets, toFill, type Caps } from "./format";
import {
  boxesPane,
  boxViews,
  contactCard,
  contactRow,
  draftRow,
  emptyList,
  filtersApply,
  folderIcon,
  inboxOf,
  inlineReply,
  listFilters,
  listFoot,
  listHead,
  listHolds,
  listTools,
  mailRow,
  moveTargets,
  parseView,
  readerDraft,
  readerEmpty,
  readerMail,
  readerTidy,
  sentRow,
  viewHolds,
  viewKey,
  viewTitle,
  type BoxView,
  type InlineReply,
  type RowView,
  type Shown,
  type View,
} from "./markup";

type Open = { kind: "mail"; ref: string } | { kind: "draft"; id: string } | null;

/** Quand un mail ouvert devient lu (ADR 0175) ; `null` : jamais. */
const READ_DELAY: Record<ReadOnOpen, number | null> = { jamais: null, aussitot: 0, "3s": 3000, "10s": 10_000 };
/** Une réponse demandée : relire ses brouillons à ce rythme, tant que la liseuse reste sur le mail. */
const ASK_POLL_MS = 10_000;
/** Au plus si longtemps (elle travaille à son prochain moment, qui peut tarder). */
const ASK_POLL_MAX_MS = 30 * 60_000;
const REFRESH_MS = 60_000;
const PAGE_SIZE = 25;
const CONTACTS_SIZE = 100;

const GESTURE_ICON: Record<Gesture, IconName> = { read: "check", unread: "mail", archive: "archive", flag: "star", unflag: "star", trash: "trash", move: "folder" };

export function mailHash(ref: string): string {
  return `#mail/messages/${encodeURIComponent(ref)}`;
}

export function draftHash(id: string): string {
  return `#mail/messages/brouillon/${encodeURIComponent(id)}`;
}

const MESSAGES_SKELETON = `<div class="split mail-split" data-mail-root="messages"><aside class="pane mb-pane" data-boxes></aside>
  <section class="pane ml-pane" data-list></section><section class="pane rd-pane"><div class="pane-scroll" data-rd></div></section></div>`;
const CONTACTS_SKELETON = `<div class="split ct-split" data-mail-root="contacts"><aside class="pane" data-ct-pane></aside><section class="pane ct-pane" data-ct-card></section></div>`;

export class MailScreen {
  private section: HTMLElement | null = null;
  private body: HTMLElement | null = null;
  private mounted: "messages" | "contacts" | null = null;
  private started = false;
  private stale = false;
  /** Ses boîtes, lues une première fois : le niveau d'une boîte décide de ce que la liseuse offre. */
  private boxesReady: Promise<void> = Promise.resolve();
  private draftsLoaded = false;

  private readonly tabs: ScreenTab[] = [
    { id: "messages", title: "Messages" },
    { id: "contacts", title: "Contacts" },
  ];

  // ses boîtes
  private boxes: MailBox[] = [];
  private plugged = true;
  private readOnOpen: ReadOnOpen = "jamais";
  private boxesError = "";
  private readonly opened = new Set<string>();
  private openedOnce = false;

  // la liste
  private view: View = { kind: "inbox" };
  private filter: MailState = "";
  private q = "";
  private page = 1;
  private rows: MailRow[] = [];
  private sentRows: SentMail[] = [];
  private total = 0;
  private size = PAGE_SIZE;
  private listLoading = true;
  private listError = "";
  private listSeq = 0;
  private readonly checked = new Set<string>();

  // ses brouillons
  private drafts: MailDraft[] = [];

  // la liseuse
  private open: Open = null;
  private mail: MailFull | null = null;
  private mailError = "";
  private mailSeq = 0;
  private reading = false;
  private readonly imagesOnce = new Set<string>();
  private reply: InlineReply | null = null;
  /** La réponse que la liseuse montre en ce moment (son `[data-reply]`) : ce qu'on y tape revient à elle seule, même
   *  quand `reply` vient de changer (une réponse nouvelle, son brouillon repris, une autre rouverte). */
  private shownReply: InlineReply | null = null;
  /** Les réponses commencées, mail par mail : quitter un mail ne perd pas ce qu'on y écrivait, ni une réponse dont
   *  l'envoi a échoué une fois le mail quitté ; le rouvrir la rouvre. */
  private readonly parked = new Map<string, InlineReply>();
  /** Les mails pour lesquels on lui a demandé une réponse (et depuis quand). */
  private readonly asked = new Map<string, number>();
  private readTimer = 0;
  private askTimer = 0;

  // les contacts
  private contacts: Contact[] = [];
  private contactsLoaded = false;
  private contactQ = "";
  private contact = "";
  private contactMails: MailRow[] | null = null;
  private contactSeq = 0;
  private showingContact = false;

  private refreshTimer = 0;
  private searchTimer = 0;

  constructor(private readonly shell: Shell) {}

  screen(): ScreenDef {
    return {
      id: "mail",
      title: "Mail",
      icon: "mail",
      tabs: this.tabs,
      actions: () => this.actions(),
      mount: (section) => this.mount(section),
      render: (body, ctx) => this.render(body, ctx),
      search: () => this.searchEntries(),
    };
  }

  // ── Ce qu'on sait ──────────────────────────────────────────────────

  private boxViewList(): BoxView[] {
    if (!this.openedOnce && this.boxes.length) {
      // au premier affichage, la première de ses boîtes est dépliée, comme dans la maquette
      this.openedOnce = true;
      const first = this.boxes.find((b) => b.level === "proprietaire") ?? this.boxes[0];
      if (first) this.opened.add(first.key);
    }
    return boxViews(this.boxes, this.opened);
  }

  private boxMap(): Map<string, BoxView> {
    return new Map(this.boxViewList().map((b) => [b.box.key, b]));
  }

  private boxOf(key: string): MailBox | undefined {
    return this.boxes.find((b) => b.key === key);
  }

  private capsOf(key: string): Caps {
    return caps(this.boxOf(key)?.level ?? "lire");
  }

  /** Les boîtes d'où elle peut écrire elle-même. */
  private writable(): MailBox[] {
    return this.boxes.filter((b) => caps(b.level).write && b.can_send);
  }

  private draftFor(ref: string): MailDraft | null {
    return this.drafts.find((d) => d.in_reply_to === ref && d.state === "attend") ?? null;
  }

  private visible(): boolean {
    return !!this.section && !this.section.hidden && document.visibilityState === "visible";
  }

  private onMessages(): boolean {
    return this.mounted === "messages" && !!this.body;
  }

  // ── Le cadre ───────────────────────────────────────────────────────

  private actions(): string {
    if (!this.writable().length) return "";
    return `<button class="btn primary" type="button" data-nouveau>${ico("plus", "sm")}<span class="lbl">Nouveau message</span></button>`;
  }

  private render(body: HTMLElement, ctx: ScreenContext): void {
    this.body = body;
    const tab = ctx.tab === "contacts" ? "contacts" : "messages";
    if (this.mounted !== tab || !$("[data-mail-root]", body)) {
      // le corps change d'onglet : ce qu'on écrivait dans la réponse en place est gardé avant qu'il ne disparaisse
      if (this.mounted === "messages") this.captureReply();
      body.innerHTML = tab === "contacts" ? CONTACTS_SKELETON : MESSAGES_SKELETON;
      this.mounted = tab;
      if (tab === "messages") this.paintMessages();
      else this.paintContactsPane();
    }
    if (!this.started) {
      this.started = true;
      // ses boîtes (leur niveau) et qui elle est (une de ses propriétaires ?) décident de ce que la liseuse offre
      this.boxesReady = Promise.all([this.loadBoxes(), store.me.load()]).then(() => undefined);
      void this.start();
    } else if (this.stale) {
      this.stale = false;
      void this.refresh();
    }
    if (tab === "messages") this.route(ctx.item);
    else this.routeContact(ctx.item);
    if (!this.refreshTimer) this.refreshTimer = window.setInterval(() => this.tick(), REFRESH_MS);
  }

  private async start(): Promise<void> {
    await Promise.all([this.boxesReady, this.loadDrafts()]);
    await this.loadList();
    void this.loadContacts();
  }

  /** Revenue sur l'écran, ou toutes les minutes tant qu'il est ouvert : ses boîtes, ses brouillons, la liste. */
  private async refresh(): Promise<void> {
    await Promise.all([this.loadBoxes(), this.loadDrafts()]);
    if (this.onMessages() && !this.checked.size) await this.loadList({ quiet: true });
  }

  private tick(): void {
    if (!this.visible()) {
      this.stale = true;
      return;
    }
    void this.refresh();
  }

  // ── Charger ────────────────────────────────────────────────────────

  private async loadBoxes(): Promise<void> {
    try {
      const got = await fetchBoxes();
      this.boxes = got.boxes;
      this.plugged = got.plugged;
      this.readOnOpen = got.read_on_open;
      this.boxesError = "";
    } catch (err) {
      this.boxesError = errorText(err);
      if (err instanceof ApiError && err.status === 503) this.plugged = false;
    }
    this.paintBoxes();
    this.shell.refreshHead();
  }

  private async loadDrafts(): Promise<void> {
    try {
      this.drafts = await fetchDrafts();
      this.draftsLoaded = true;
    } catch {
      // la liste garde ce qu'elle avait ; une vue « Ses brouillons » le dira
      return;
    }
    this.paintBoxes();
    if (this.view.kind === "drafts" && this.onMessages()) {
      this.total = this.visibleDrafts().length;
      this.paintRows();
    }
    if (this.open?.kind === "draft") this.paintReader();
  }

  private queryOf(v: View): MessagesQuery {
    const base = { q: this.q.trim(), page: this.page, size: PAGE_SIZE };
    switch (v.kind) {
      case "flagged":
        return { ...base, state: "flagged" };
      case "needs_reply":
        return { ...base, state: "needs_reply" };
      case "folder":
        return { ...base, box: v.box, folder: v.folder, state: this.filter };
      default:
        return { ...base, folder: "INBOX", state: this.filter };
    }
  }

  /** Rend `true` quand la liste demandée est là : ni dépassée par une autre demande, ni en erreur. */
  private async loadList(opts: { quiet?: boolean } = {}): Promise<boolean> {
    const seq = ++this.listSeq;
    const v = this.view;
    if (!opts.quiet) {
      this.listLoading = true;
      this.listError = "";
      this.paintRows();
    }
    try {
      if (v.kind === "drafts") {
        await this.loadDrafts();
        if (seq !== this.listSeq) return false;
        this.total = this.visibleDrafts().length;
      } else if (v.kind === "sent") {
        const items = await fetchSent(v.box);
        if (seq !== this.listSeq) return false;
        this.sentRows = items;
        this.total = this.visibleSent().length;
      } else {
        const got = await fetchMessages(this.queryOf(v));
        if (seq !== this.listSeq) return false;
        const same = opts.quiet && JSON.stringify(got.items) === JSON.stringify(this.rows) && got.total === this.total;
        this.rows = got.items;
        this.total = got.total;
        this.page = got.page;
        this.size = got.size;
        if (same && !this.listLoading) return true;
      }
      this.listLoading = false;
      this.listError = "";
    } catch (err) {
      if (seq !== this.listSeq) return false;
      this.listLoading = false;
      this.listError = errorText(err);
    }
    this.paintRows();
    return !this.listError;
  }

  /** Une autre vue, un autre filtre : la liste qui arrive fait foi pour la liseuse (`listHolds`). Ce qui met un mail
   *  dans une vue du serveur n'est pas tout entier dans ce que l'API dit de lui (« Réponse attendue ») : le mail
   *  ouvert reste s'il est à gauche, se ferme s'il n'est pas dans une liste entière. */
  private async loadListAndHold(): Promise<void> {
    const v = this.view;
    const filter = this.filter;
    const ref = this.open?.kind === "mail" ? this.open.ref : null;
    const loaded = await this.loadList();
    if (!loaded || !ref || v.kind === "drafts" || v.kind === "sent" || this.view !== v || this.filter !== filter) return;
    if (this.open?.kind !== "mail" || this.open.ref !== ref) return; // on a ouvert autre chose entre-temps
    if (listHolds(ref, this.rows, this.total) === false) this.closeReader();
  }

  private async loadContacts(): Promise<void> {
    try {
      this.contacts = await fetchContacts(this.contactQ.trim(), CONTACTS_SIZE);
    } catch (err) {
      this.contacts = [];
      if (this.mounted === "contacts") toast(errorText(err), { ico: "alert" });
    }
    this.contactsLoaded = true;
    if (!this.contactQ) {
      const n = this.contacts.length;
      this.tabs[1].count = n >= CONTACTS_SIZE ? `${CONTACTS_SIZE}+` : n || undefined;
      this.shell.refreshHead();
    }
    if (this.mounted === "contacts") {
      if (!this.contact && this.contacts[0] && !isMobile()) this.selectContact(this.contacts[0].address, false);
      this.paintContactsList();
      this.paintContactCard();
    }
  }

  // ── Les routes ─────────────────────────────────────────────────────

  private route(item: string | null): void {
    if (!item) {
      // l'adresse ne nomme rien : la liseuse non plus (un rechargement montrerait « Choisis un mail »)
      if (this.open) this.closeReader();
      else if (this.reading) {
        this.reading = false;
        this.paintSplit();
      }
      return;
    }
    if (item.startsWith("brouillon/")) this.openDraft(item.slice("brouillon/".length));
    else this.openMail(item);
  }

  private routeContact(item: string | null): void {
    if (item) {
      this.showingContact = true;
      if (item !== this.contact) this.selectContact(item, true);
    } else this.showingContact = false;
    this.paintContactSplit();
  }

  /** La liseuse quitte son mail : une réponse commencée (ou qui part encore) y reste, pour quand on le rouvre. */
  private leaveReader(): void {
    window.clearTimeout(this.readTimer);
    window.clearTimeout(this.askTimer);
    this.captureReply();
    const r = this.reply;
    if (r && this.open?.kind === "mail" && (r.sending || r.error || r.fromDraft || r.body.trim() || r.files.length)) this.parked.set(this.open.ref, r);
    this.reply = null;
  }

  private openMail(ref: string): void {
    this.reading = true;
    if (this.open?.kind === "mail" && this.open.ref === ref && (this.mail || !this.mailError)) {
      this.paintSplit();
      return;
    }
    this.leaveReader();
    this.open = { kind: "mail", ref };
    // sa réponse commencée, si on l'avait quitté en l'écrivant
    this.reply = this.parked.get(ref) ?? null;
    this.parked.delete(ref);
    this.mail = null;
    this.mailError = "";
    this.paintSelection();
    this.paintReader();
    this.paintSplit();
    const seq = ++this.mailSeq;
    Promise.all([fetchMessage(ref), this.boxesReady])
      .then(([m]) => {
        if (seq !== this.mailSeq) return;
        this.mail = m;
        this.syncRow(m);
        this.paintReader();
        this.scheduleRead(m);
        this.watchAsk();
      })
      .catch((err) => {
        if (seq !== this.mailSeq) return;
        this.mailError = errorText(err);
        this.paintReader();
      });
  }

  private openDraft(id: string): void {
    this.reading = true;
    this.leaveReader();
    this.open = { kind: "draft", id };
    this.mail = null;
    if (this.view.kind !== "drafts") {
      this.setView({ kind: "drafts", box: "" }, false);
    }
    this.paintSelection();
    this.paintReader();
    this.paintSplit();
  }

  private go(hash: string): void {
    this.shell.go(hash);
  }

  private closeReader(): void {
    this.leaveReader();
    this.open = null;
    this.mail = null;
    this.reading = false;
    if (/^#mail\/messages\/./.test(location.hash)) history.replaceState(null, "", "#mail/messages");
    this.paintSelection();
    this.paintReader();
    this.paintSplit();
  }

  // ── Les vues ───────────────────────────────────────────────────────

  private setView(v: View, load = true): void {
    this.view = v;
    this.page = 1;
    this.checked.clear();
    if ("box" in v && v.box) this.opened.add(v.box);
    this.keepReaderInList();
    if (!this.onMessages()) return;
    this.paintBoxes();
    this.paintListPane();
    if (load) void this.loadListAndHold();
    else if (v.kind === "drafts") {
      this.total = this.visibleDrafts().length;
      this.listLoading = false;
      this.paintRows();
    }
  }

  /** Ce que la liseuse montre, pour savoir si la liste le tient encore. */
  private shown(): Shown {
    const open = this.open;
    if (open?.kind === "draft") return { kind: "draft", box: this.drafts.find((d) => d.id === open.id)?.box ?? null };
    const m = open?.kind === "mail" && this.mail?.ref === open.ref ? this.mail : null;
    return { kind: "mail", mail: m, common: !!m && this.boxOf(m.box)?.level !== "lire" };
  }

  /** À droite, rien qui ne soit de la liste de gauche (la vue et son filtre) : sinon la liseuse se ferme, et l'adresse
   *  avec elle (on décidait d'un brouillon en croyant regarder ses envois). */
  private keepReaderInList(): void {
    if (this.open && !viewHolds(this.view, filtersApply(this.view) ? this.filter : "", this.shown())) this.closeReader();
  }

  private visibleDrafts(): MailDraft[] {
    const v = this.view;
    const q = norm(this.q.trim());
    const list = this.drafts.filter((d) => (v.kind === "drafts" && v.box ? d.box === v.box : true));
    const found = q ? list.filter((d) => norm(`${d.subject} ${d.to} ${d.cc} ${d.body}`).includes(q)) : list;
    return [...found.filter((d) => d.state === "attend"), ...found.filter((d) => d.state !== "attend")];
  }

  private visibleSent(): SentMail[] {
    const q = norm(this.q.trim());
    return q ? this.sentRows.filter((s) => norm(`${s.subject} ${s.snippet} ${s.to.map((p) => `${p.name} ${p.address}`).join(" ")}`).includes(q)) : this.sentRows;
  }

  /** Plusieurs boîtes dans la vue : chaque ligne dit la sienne. */
  private many(): boolean {
    const v = this.view;
    return this.boxes.length > 1 && !(v.kind === "folder" || (("box" in v) && !!v.box));
  }

  // ── Peindre ────────────────────────────────────────────────────────

  private paintMessages(): void {
    this.paintBoxes();
    this.paintListPane();
    this.paintReader();
    this.paintSplit();
  }

  private paintSplit(): void {
    if (!this.onMessages()) return;
    $(".mail-split", this.body!)?.classList.toggle("lire", this.reading);
  }

  private paintBoxes(): void {
    if (!this.onMessages()) return;
    const host = $("[data-boxes]", this.body!);
    if (!host) return;
    const scroll = $(".pane-scroll", host)?.scrollTop ?? 0;
    // « Toutes les réceptions » : tes boîtes, sans celles qu'on ne te partage qu'en lecture (ADR 0200), comme sa liste
    const unseen = this.boxes.reduce((n, b) => n + (b.level === "lire" ? 0 : inboxOf(b)?.unseen ?? 0), 0);
    const waiting = this.drafts.filter((d) => d.state === "attend" && this.capsOf(d.box).decide).length;
    host.innerHTML = boxesPane({
      boxes: this.boxViewList(),
      view: viewKey(this.view),
      unseen,
      waiting,
      plugged: this.plugged,
      error: this.boxesError,
    });
    const s = $(".pane-scroll", host);
    if (s) s.scrollTop = scroll;
  }

  private placeholder(): string {
    if (this.view.kind === "drafts") return "Chercher dans ses brouillons…";
    if (this.view.kind === "sent") return "Chercher dans ce qui est parti…";
    return "Chercher dans tes mails : des mots, un expéditeur…";
  }

  private paintListPane(): void {
    if (!this.onMessages()) return;
    const pane = $("[data-list]", this.body!);
    if (!pane) return;
    const filters = filtersApply(this.view);
    pane.innerHTML = `<div class="pane-head ml-head" data-list-head></div>
      <div class="ml-tools${filters ? "" : " last"}">${listTools(this.q, this.placeholder())}</div>
      ${filters ? `<div class="ml-filters">${listFilters(this.filter)}</div>` : ""}
      <div class="pane-scroll" data-liste></div>
      <div class="pane-foot ml-foot" data-foot hidden></div>`;
    this.paintListHead();
    this.paintRows();
  }

  private paintListHead(): void {
    if (!this.onMessages()) return;
    const head = $("[data-list-head]", this.body!);
    if (head) head.innerHTML = listHead(viewTitle(this.view, this.boxViewList()), this.total, this.checked.size);
  }

  private rowView(): RowView {
    const selected = this.open?.kind === "mail" ? this.open.ref : this.open?.kind === "draft" ? `brouillon/${this.open.id}` : "";
    return { now: Date.now(), selected, checked: this.checked, many: this.many(), boxes: this.boxMap() };
  }

  private rowsMarkup(): string {
    const v = this.view;
    if (!this.plugged) return emptyList("mail", "Le courrier n'est pas branché", "Ce serveur n'a pas de courrier.");
    if (this.listError) {
      return `<div class="empty">${ico("alert")}<b>La liste n'a pas pu se charger</b><p>${h(this.listError)}</p><button class="btn sm" type="button" data-recharger>${ico("refresh", "sm")}Réessayer</button></div>`;
    }
    const rv = this.rowView();
    if (v.kind === "drafts") {
      const list = this.visibleDrafts();
      if (!list.length && !this.draftsLoaded) return emptyList("refresh", "Chargement…", "Ses brouillons se lisent.");
      if (!list.length) {
        return this.q
          ? emptyList("search", "Rien trouvé", `Aucun de ses brouillons ne contient « ${this.q} ».`)
          : emptyList("pen", "Aucun brouillon d'elle", "Ce qu'elle prépare pour toi arrive ici : tu le relis, tu le retouches, tu l'envoies.");
      }
      const waiting = list.filter((d) => d.state === "attend");
      const decided = list.filter((d) => d.state !== "attend");
      return `${waiting.map((d) => draftRow(d, rv)).join("")}${decided.length ? `<div class="group-label">Décidés<span class="cnt">${decided.length}</span></div>${decided.map((d) => draftRow(d, rv)).join("")}` : ""}`;
    }
    if (this.listLoading && !this.rows.length && !this.sentRows.length) return emptyList("refresh", "Chargement…", "Ses boîtes se lisent.");
    if (v.kind === "sent") {
      const list = this.visibleSent();
      if (!list.length) return this.q ? emptyList("search", "Rien trouvé", `Rien de parti ne contient « ${this.q} ».`) : emptyList("send", "Rien n'est parti", "Ce qui part de tes boîtes, de toi ou d'elle, se retrouve ici.");
      return list.map((s) => sentRow(s, rv)).join("");
    }
    if (!this.rows.length) {
      if (this.q) return emptyList("search", "Rien trouvé", `Aucun mail ne contient « ${this.q} ».`);
      if (v.kind === "folder") {
        const f = this.boxOf(v.box)?.folders.find((x) => x.name === v.folder);
        if (f && !f.polled) return emptyList("folder", "Ce dossier n'est pas relevé", "Mika ne relève pas ce dossier : choisis-le dans Paramètres › Comptes mail pour qu'il arrive ici.");
      }
      if (v.kind === "needs_reply") return emptyList("reply", "Rien n'attend de réponse", "Les mails qu'elle juge appeler une réponse arrivent ici, tant qu'ils ne sont pas lus.");
      if (v.kind === "flagged") return emptyList("star", "Aucun mail suivi", "Suis un mail (l'étoile) pour le retrouver ici.");
      return emptyList("inbox", "Rien ici", this.filter ? "Aucun mail pour ce filtre." : "Aucun mail dans ce dossier.");
    }
    return this.rows.map((r) => mailRow(r, rv, this.capsOf(r.box).write)).join("");
  }

  private paintRows(): void {
    if (!this.onMessages()) return;
    const host = $("[data-liste]", this.body!);
    if (!host) return;
    host.innerHTML = this.rowsMarkup();
    const foot = $<HTMLElement>("[data-foot]", this.body!);
    const message = this.view.kind !== "drafts" && this.view.kind !== "sent";
    const pages = message ? listFoot(this.total, this.page, this.size) : "";
    if (foot) {
      foot.innerHTML = pages;
      foot.hidden = !pages;
    }
    const cnt = $(".ml-head .cnt", this.body!);
    if (cnt) cnt.textContent = String(this.total);
  }

  private paintSelection(): void {
    if (!this.onMessages()) return;
    const key = this.rowView().selected;
    for (const el of $$<HTMLElement>("[data-mail], [data-draft]", $("[data-liste]", this.body!) ?? this.body!)) {
      const k = el.dataset.mail ?? `brouillon/${el.dataset.draft}`;
      el.setAttribute("aria-selected", String(k === key));
    }
  }

  private paintReader(): void {
    if (!this.onMessages()) return;
    const host = $<HTMLElement>("[data-rd]", this.body!);
    if (!host) return;
    const active = document.activeElement as HTMLElement | null;
    const typing = active?.matches?.("[data-rd-txt]") ? (active as HTMLTextAreaElement) : null;
    const caret = typing ? [typing.selectionStart, typing.selectionEnd] : null;
    this.captureReply();
    host.innerHTML = this.readerMarkup();
    this.shownReply = $("[data-reply]", host) ? this.reply : null;
    if (caret) {
      const t = $<HTMLTextAreaElement>("[data-rd-txt]", host);
      if (t) {
        t.focus();
        t.setSelectionRange(caret[0] ?? t.value.length, caret[1] ?? t.value.length);
      }
    }
    this.sizeFrame(host);
  }

  private readerMarkup(): string {
    const mobile = isMobile();
    const back = mobile ? `<button class="btn sm ghost rd-back" type="button" data-retour>${ico("chev-left", "sm")}Retour</button>` : "";
    if (this.open?.kind === "draft") {
      const id = this.open.id;
      const d = this.drafts.find((x) => x.id === id);
      if (!d && !this.draftsLoaded) return `${back}${readerEmpty("pen", "Chargement…", "Ses brouillons se lisent.")}`;
      if (!d) return `${back}${readerEmpty("pen", "Ce brouillon n'est plus là", "Il a peut-être été décidé ailleurs. Choisis-en un autre dans la liste.")}`;
      const box = this.boxMap().get(d.box) ?? null;
      return `${back}${readerDraft(d, { now: Date.now(), box, caps: this.capsOf(d.box), mobile })}`;
    }
    if (this.open?.kind === "mail") {
      if (this.mailError) return `${back}${readerEmpty("alert", "Ce mail ne s'ouvre pas", this.mailError)}`;
      const m = this.mail;
      if (!m) return `${back}${readerEmpty("mail", "Chargement…", "Le mail s'ouvre.")}`;
      const bv = this.boxMap().get(m.box) ?? null;
      const c = this.capsOf(m.box);
      const draft = this.draftFor(m.ref) ?? (m.her?.draft ? this.drafts.find((d) => d.id === m.her!.draft && d.state === "attend") ?? null : null);
      const asked = this.asked.has(m.ref) || !!m.her?.asked;
      return back + readerMail(
        m,
        {
          now: Date.now(),
          box: bv,
          caps: c,
          frame: frameUrl(m.ref, this.imagesOnce.has(m.ref)),
          imagesOnce: this.imagesOnce.has(m.ref),
          draft,
          asked,
          composer: this.reply ? inlineReply(this.reply, bv, c.prepare && !m.sent) : "",
          taken: !!this.reply?.fromDraft,
          mobile,
          owner: store.me.value?.owner === true,
        },
        (part) => fileUrl(m.ref, part),
      );
    }
    return readerEmpty("mail", "Choisis un mail", "Il s'ouvre ici, à côté de la liste.");
  }

  /** Un mail HTML : son cadre à la hauteur de son contenu quand on peut la lire (même origine), sinon sa hauteur fixe. */
  private sizeFrame(host: HTMLElement): void {
    const frame = $<HTMLIFrameElement>("[data-frame]", host);
    if (!frame) return;
    frame.addEventListener("load", () => {
      try {
        const doc = frame.contentDocument;
        const height = doc?.documentElement?.scrollHeight ?? 0;
        if (height > 0) frame.style.height = `${Math.min(6000, Math.max(160, height + 8))}px`;
      } catch {
        // une autre origine (le moteur ailleurs que la page) : le cadre garde sa hauteur et défile
      }
    });
  }

  /** Ce que la réponse en place contient maintenant (avant de la redessiner), rendu à la réponse qu'elle montre. */
  private captureReply(): void {
    const r = this.shownReply;
    const host = this.body && $<HTMLElement>("[data-reply]", this.body);
    if (!r || !host) return;
    r.to = readRecipients(host, "to");
    r.cc = readRecipients(host, "cc");
    r.bcc = readRecipients(host, "bcc");
    r.body = $<HTMLTextAreaElement>("[data-rd-txt]", host)?.value ?? r.body;
    r.quote = !!$<HTMLInputElement>("[data-quote]", host)?.checked;
  }

  // ── Lire, ranger ───────────────────────────────────────────────────

  /** Ce que le mail ouvert dit de lui, reporté sur sa ligne (lu, suivi, répondu). */
  private syncRow(m: MailFull): void {
    const row = this.rows.find((r) => r.ref === m.ref);
    if (!row) return;
    const changed = row.seen !== m.seen || row.flagged !== m.flagged || row.answered !== m.answered;
    Object.assign(row, { seen: m.seen, flagged: m.flagged, answered: m.answered, her: m.her ? { ...m.her } : null });
    if (changed) this.paintRows();
  }

  private scheduleRead(m: MailFull): void {
    window.clearTimeout(this.readTimer);
    const delay = READ_DELAY[this.readOnOpen];
    if (m.seen || !answerable(m) || delay === null || !this.capsOf(m.box).write) return;
    const ref = m.ref;
    this.readTimer = window.setTimeout(() => {
      if (this.open?.kind !== "mail" || this.open.ref !== ref || !this.visible()) return;
      void this.gesture([ref], "read", true);
    }, delay);
  }

  private async gesture(refs: string[], g: Gesture, quiet = false, folder = ""): Promise<void> {
    try {
      const done = await tidy(refs, g, folder);
      const gone = g === "archive" || g === "trash" || g === "move";
      for (const r of this.rows) {
        if (!refs.includes(r.ref)) continue;
        if (g === "read" || g === "unread") r.seen = g === "read";
        if (g === "flag" || g === "unflag") r.flagged = g === "flag";
      }
      if (this.mail && refs.includes(this.mail.ref)) {
        if (g === "read" || g === "unread") this.mail.seen = g === "read";
        if (g === "flag" || g === "unflag") this.mail.flagged = g === "flag";
      }
      if (gone) {
        this.rows = this.rows.filter((r) => !refs.includes(r.ref));
        this.total = Math.max(0, this.total - refs.length);
        if (this.open?.kind === "mail" && refs.includes(this.open.ref)) this.closeReader();
      }
      for (const r of refs) this.checked.delete(r);
      this.paintListHead();
      this.paintRows();
      if (this.mail && refs.includes(this.mail.ref)) this.paintReaderTidy();
      if (!quiet) toast(done.message, { ico: GESTURE_ICON[g] });
      void this.loadBoxes();
      void refreshCounts();
      // ce que la vue montre a pu changer (un suivi retiré, un lu dans « non lus ») : la relire sans bruit
      if (!quiet && (this.view.kind === "flagged" || this.filter === "unread")) void this.loadList({ quiet: true });
    } catch (err) {
      // le « lu » posé de lui-même à l'ouverture échoue sans bruit ; un geste de toi dit pourquoi
      if (!quiet) toast(errorText(err), { ico: "alert" });
    }
  }

  /** Les seuls gestes de la liseuse (sans la redessiner : une réponse peut être en cours). */
  private paintReaderTidy(): void {
    const m = this.mail;
    const bar = this.body && $<HTMLElement>("[data-rd-actions]", this.body);
    if (!m || !bar) return;
    for (const el of $$("[data-act='archiver'], [data-act='lu'], [data-act='suivre'], [data-act='deplacer'], [data-act='corbeille']", bar)) el.remove();
    bar.insertAdjacentHTML("beforeend", readerTidy(m));
    const head = $("[data-rd-tags]", this.body!);
    if (head) {
      const star = $(".tag.accent", head);
      if (m.flagged && !star) head.insertAdjacentHTML("beforeend", '<span class="tag accent">★ suivi</span>');
      if (!m.flagged) star?.remove();
    }
  }

  // ── Répondre ───────────────────────────────────────────────────────

  private startReply(all: boolean): void {
    const m = this.mail;
    // un mail parti de sa boîte, sans copie reçue, ne se répond pas (l'API refuse) : il se transfère
    if (!m || !answerable(m)) return;
    const box = this.boxOf(m.box);
    const { to, cc } = replyTargets(m, box?.address ?? "", all);
    this.reply = {
      all,
      to,
      cc,
      showCc: cc.length > 0,
      bcc: [],
      showBcc: false,
      files: [],
      // un objet qu'on ne voit ni ne tape ici : dans sa borne, sinon l'envoi serait refusé sans qu'on sache pourquoi
      subject: clip(replySubject(m.subject), MAIL_LIMITS.subject),
      body: "",
      quote: true,
      fromDraft: "",
      filled: "",
      sending: false,
      error: "",
    };
    this.paintReader();
    this.focusReply();
  }

  private focusReply(): void {
    const t = this.body && $<HTMLTextAreaElement>("[data-rd-txt]", this.body);
    if (!t) return;
    t.focus();
    t.scrollIntoView({ block: "nearest" });
  }

  /** Son brouillon, repris dans ta réponse : il partira de là, et elle apprendra ce que tu y as changé. */
  private takeDraft(d: MailDraft): void {
    const m = this.mail;
    if (!m || !answerable(m)) return;
    const to = parseAddresses(d.to);
    const cc = parseAddresses(d.cc);
    this.captureReply();
    const before = this.reply; // ce que tu y avais joint, et ta copie cachée, ne se perdent pas
    this.reply = {
      all: cc.length > 0,
      to: to.length ? to : replyTargets(m, this.boxOf(m.box)?.address ?? "", false).to,
      cc,
      showCc: cc.length > 0,
      bcc: before?.bcc ?? [],
      showBcc: before?.showBcc ?? false,
      files: before?.files ?? [],
      subject: clip(d.subject || replySubject(m.subject), MAIL_LIMITS.subject),
      body: d.body,
      quote: d.quote,
      fromDraft: d.id,
      filled: "Son brouillon, repris ici",
      sending: false,
      error: "",
    };
    this.paintReader();
    this.focusReply();
  }

  private async prefillMail(): Promise<void> {
    const m = this.mail;
    if (!m) return;
    const c = this.capsOf(m.box);
    try {
      const got = await prefill(m.ref);
      if (got.draft) {
        await this.loadDrafts();
        const d = this.drafts.find((x) => x.id === got.draft);
        if (d && c.write && this.mail?.ref === m.ref) {
          this.takeDraft(d);
          toast("Son brouillon est repris dans ta réponse : relis-le avant d'envoyer.", { mika: true });
        } else {
          toast(c.write ? got.message : `${got.message} Il attend l'accord de ${this.boxOf(m.box)?.owner_name || "son propriétaire"}.`, { mika: true });
          this.paintReader();
        }
        return;
      }
      this.asked.set(m.ref, Date.now());
      toast(got.message && got.message !== "Elle y travaille déjà." ? "Demandé : elle l'écrit à son prochain moment de travail ; sa réponse arrivera ici." : got.message, { mika: true });
      this.paintReader();
      this.watchAsk();
    } catch (err) {
      toast(errorText(err), { ico: "alert" });
    }
  }

  /** Une réponse demandée : relire ses brouillons, tant que la liseuse reste sur ce mail, jusqu'à ce qu'elle arrive. */
  private watchAsk(): void {
    window.clearTimeout(this.askTimer);
    const m = this.mail;
    if (!m) return;
    const since = this.asked.get(m.ref) ?? (m.her?.asked ? Date.now() : 0);
    if (!since || this.draftFor(m.ref)) return;
    if (!this.asked.has(m.ref)) this.asked.set(m.ref, since);
    const ref = m.ref;
    this.askTimer = window.setTimeout(async () => {
      if (this.open?.kind !== "mail" || this.open.ref !== ref) return;
      if (Date.now() - since > ASK_POLL_MAX_MS) return;
      if (!this.visible()) {
        this.watchAsk();
        return;
      }
      await this.loadDrafts();
      if (this.open?.kind !== "mail" || this.open.ref !== ref) return;
      const d = this.draftFor(ref);
      if (d) {
        this.asked.delete(ref);
        toast("Sa réponse est arrivée : elle t'attend ici.", { mika: true });
        this.paintReader();
        return;
      }
      this.watchAsk();
    }, ASK_POLL_MS);
  }

  private async sendReply(): Promise<void> {
    const m = this.mail;
    const r = this.reply;
    if (!m || !r || r.sending) return;
    this.captureReply();
    const fail = (text: string) => {
      r.error = text;
      this.paintReader();
    };
    if (!answerable(m)) return fail("On ne répond pas à un mail parti de ta boîte : transfère-le.");
    if (!r.to.length) return fail("À qui ? Ajoute au moins un destinataire.");
    if (!r.body.trim()) return fail("Ta réponse est vide.");
    if (toFill(r.subject, r.body)) return fail("Il reste des passages [À COMPLÉTER] à remplir.");
    const fits = outgoingText(r);
    if (!fits.mail) return fail(fits.problem);
    r.sending = true;
    r.error = "";
    this.paintReader();
    const ref = m.ref;
    // l'envoi peut durer : la liseuse a pu passer à un autre mail, ou à une autre réponse ; son issue ne touche
    // qu'à celle-ci
    const here = () => this.reply === r && this.open?.kind === "mail" && this.open.ref === ref;
    const mail = { ...fits.mail, quote: r.quote };
    try {
      // un brouillon part tel qu'il est lu : avec des pièces ou une copie cachée, c'est ta réponse qui part (le sien est retiré)
      const asDraft = r.fromDraft && !r.files.length && !mail.bcc && this.capsOf(m.box).decide;
      const done = asDraft ? await this.sendThroughDraft(r.fromDraft, mail, m) : await replyMail(ref, mail, newNonce(), r.files);
      if (this.parked.get(ref) === r) this.parked.delete(ref);
      if (here()) {
        this.reply = null;
        this.paintReader();
      }
      toast(done.message, { ico: "send" });
      void this.afterSend(ref);
    } catch (err) {
      r.sending = false;
      r.error = errorText(err);
      const shown = here();
      if (shown) this.paintReader();
      // on a quitté ce mail : sa réponse, avec ce qui l'a refusée, l'y attend
      else if (!this.parked.has(ref)) this.parked.set(ref, r);
      toast(
        shown
          ? `Ta réponse n'est pas partie : ${r.error}`
          : `Ta réponse à « ${m.subject || "(sans objet)"} » n'est pas partie : ${r.error} Elle t'attend dans ce mail.`,
        { ico: "alert", duration: 6000 },
      );
    }
  }

  /** Ta réponse, partie de son brouillon : ta version d'abord (elle l'apprendra), puis l'envoi tel qu'il se lit. */
  private async sendThroughDraft(id: string, mail: Outgoing & { quote: boolean }, m: MailFull): Promise<Done> {
    const d = (await fetchDrafts()).find((x) => x.id === id);
    if (!d || d.state !== "attend") return replyMail(m.ref, mail, newNonce());
    const same = (a: string, b: string) =>
      parseAddresses(a).map((p) => p.address).join(",") === parseAddresses(b).map((p) => p.address).join(",");
    const changed = !same(d.to, mail.to) || !same(d.cc, mail.cc ?? "") || d.subject !== mail.subject || d.body !== mail.body || d.quote !== mail.quote;
    if (changed) await editDraft(id, mail);
    const now = (await fetchDrafts()).find((x) => x.id === id);
    if (!now?.preview || now.state !== "attend") throw new Error("Son brouillon n'attend plus de décision : rien n'est parti.");
    if (now.preview.blocked) throw new Error(`Il ne peut pas partir tel quel : ${now.preview.blocked}.`);
    return sendDraft(id, now.preview.digest, newNonce());
  }

  private async afterSend(ref: string): Promise<void> {
    await this.loadDrafts();
    void refreshCounts();
    if (this.open?.kind === "mail" && this.open.ref === ref) {
      try {
        const fresh = await fetchMessage(ref);
        if (this.open?.kind === "mail" && this.open.ref === ref) {
          this.mail = fresh;
          this.syncRow(fresh);
          this.paintReader();
        }
      } catch {
        // le mail reste tel qu'on l'a lu
      }
    }
    if (this.view.kind === "sent") void this.loadList({ quiet: true });
  }

  // ── Écrire (la fenêtre) ────────────────────────────────────────────

  private newMail(to: { name: string; address: string }[] = []): void {
    const boxes = this.writable();
    if (!boxes.length) {
      toast("Aucune de tes boîtes ne peut envoyer : sa connexion n'est pas prête (Paramètres › Comptes mail).", { ico: "alert" });
      return;
    }
    const views = boxViews(boxes, new Set());
    const open = this.mail && boxes.some((b) => b.key === this.mail!.box) ? this.mail.box : boxes[0].key;
    openCompose({
      title: "Nouveau message",
      kind: "new",
      boxes: views,
      box: open,
      to,
      cc: [],
      subject: "",
      body: "",
      attachments: 0,
      quote: null,
      submitLabel: "Envoyer",
      submit: async (v: ComposeValues) => {
        const done = await sendMail(v.box, v.mail, newNonce(), v.files);
        if (toFill(v.subject, v.body)) return done.message;
        if (this.view.kind === "sent") void this.loadList({ quiet: true });
        return done.message;
      },
    });
  }

  private forward(m: MailFull): void {
    const views = this.boxViewList();
    openCompose({
      title: "Transférer",
      kind: "forward",
      boxes: views,
      box: m.box,
      to: [],
      cc: [],
      subject: clip(forwardSubject(m.subject), MAIL_LIMITS.subject),
      body: "",
      attachments: m.attachments.length,
      carried: m.attachments,
      quote: null,
      emptyBody: true,
      submitLabel: "Transférer",
      submit: async (v) => {
        const done = await forwardMail(m.ref, { ...v.mail, attachments: v.pieces }, newNonce(), v.files);
        return done.message;
      },
    });
  }

  // ── Ses brouillons : décider ───────────────────────────────────────

  private openedDraft(): MailDraft | null {
    return this.open?.kind === "draft" ? this.drafts.find((d) => d.id === (this.open as { id: string }).id) ?? null : null;
  }

  private async decide(kind: string, d: MailDraft): Promise<void> {
    if (kind === "envoyer") {
      if (!d.preview || d.preview.blocked) return;
      try {
        const done = await sendDraft(d.id, d.preview.digest, newNonce());
        toast(done.message, { ico: "send" });
      } catch (err) {
        toast(errorText(err), { ico: "alert" });
      }
      await this.loadDrafts();
      void refreshCounts();
      return;
    }
    if (kind === "retoucher") {
      const views = this.boxViewList();
      openCompose({
        title: "Retoucher son brouillon",
        kind: "edit",
        boxes: views,
        box: d.box,
        to: parseAddresses(d.to),
        cc: parseAddresses(d.cc),
        subject: d.subject,
        body: d.body,
        attachments: 0,
        quote: d.in_reply_to ? d.quote : null,
        submitLabel: "Enregistrer ta version",
        submit: async (v) => {
          const done = await editDraft(d.id, { ...v.mail, quote: d.in_reply_to ? v.quote : false });
          await this.loadDrafts();
          return done.message;
        },
      });
      return;
    }
    if (kind === "refuser") {
      openAsk({
        title: "Refuser son brouillon",
        lede: `« ${d.subject} » ne partira pas ; elle le saura. Dis-lui pourquoi, si tu veux : elle en tiendra compte.`,
        label: "Pourquoi (facultatif)",
        placeholder: "« trop long », « je préfère répondre moi-même »…",
        required: false,
        max: MAIL_LIMITS.note,
        submitLabel: "Refuser",
        danger: true,
        submit: async (note) => {
          const done = await refuseDraft(d.id, note);
          await this.loadDrafts();
          void refreshCounts();
          return done.message;
        },
      });
      return;
    }
    if (kind === "reprendre") {
      openAsk({
        title: "Lui demander de le reprendre",
        lede: `Celui-ci est refusé ; elle en écrira un autre à son prochain moment de travail, en tenant compte de ce que tu dis. Tu le reliras avant qu'il parte.`,
        label: "Ce qu'il faut changer",
        placeholder: "« plus court », « dis-lui oui pour jeudi »…",
        required: true,
        max: MAIL_LIMITS.instruction,
        submitLabel: "Lui demander",
        mika: true,
        submit: async (instruction) => {
          const done = await redoDraft(d.id, instruction);
          if (d.in_reply_to) this.asked.set(d.in_reply_to, Date.now());
          await this.loadDrafts();
          void refreshCounts();
          return done.message;
        },
      });
    }
  }

  // ── Les contacts ───────────────────────────────────────────────────

  private paintContactsPane(): void {
    if (this.mounted !== "contacts" || !this.body) return;
    const pane = $("[data-ct-pane]", this.body);
    if (pane) {
      pane.innerHTML = `<div class="pane-head"><label class="search grow">${ico("search", "sm")}<input type="search" placeholder="Chercher un contact" data-qc value="${h(this.contactQ)}" aria-label="Chercher un contact" maxlength="${MAIL_LIMITS.contacts}"></label></div>
        <div class="pane-scroll" data-ct-list></div>`;
    }
    this.paintContactsList();
    this.paintContactCard();
    this.paintContactSplit();
  }

  private paintContactsList(): void {
    const host = this.body && $("[data-ct-list]", this.body);
    if (!host) return;
    const now = Date.now();
    host.innerHTML = !this.contactsLoaded
      ? emptyList("refresh", "Chargement…", "Ses correspondants se lisent.")
      : this.contacts.length
        ? this.contacts.map((c) => contactRow(c, this.contact, now)).join("")
        : this.contactQ
          ? emptyList("search", "Personne", `Aucun correspondant ne répond à « ${this.contactQ} ».`)
          : emptyList("users", "Aucun correspondant", "Les personnes qui t'écrivent, et à qui tu écris, arrivent ici.");
  }

  private paintContactCard(): void {
    const host = this.body && $("[data-ct-card]", this.body);
    if (!host) return;
    const c = this.contacts.find((x) => x.address === this.contact) ?? (this.contact ? { address: this.contact, name: "", received: 0, sent: 0, last: 0 } : null);
    host.innerHTML = c
      ? contactCard(c, this.contactMails, Date.now(), this.writable().length > 0, isMobile(), this.boxMap())
      : `<div class="pane-scroll">${readerEmpty("user", "Choisis un correspondant", "Ses moyens de communication et ses derniers mails s'affichent ici.")}</div>`;
  }

  private paintContactSplit(): void {
    if (this.mounted !== "contacts" || !this.body) return;
    $(".ct-split", this.body)?.classList.toggle("lire", this.showingContact);
  }

  private selectContact(address: string, paint: boolean): void {
    this.contact = address;
    this.contactMails = null;
    const seq = ++this.contactSeq;
    fetchMessages({ q: address, size: 20 })
      .then((page) => {
        if (seq !== this.contactSeq) return;
        this.contactMails = page.items.filter((m) => m.from.address.toLowerCase() === address.toLowerCase()).slice(0, 5);
        this.paintContactCard();
      })
      .catch(() => {
        if (seq !== this.contactSeq) return;
        this.contactMails = [];
        this.paintContactCard();
      });
    if (paint) {
      this.paintContactsList();
      this.paintContactCard();
    }
  }

  // ── Les gestes ─────────────────────────────────────────────────────

  private mount(section: HTMLElement): void {
    this.section = section;
    bindRecipients(section);
    bindCounts(section);
    bindPieces(section, {
      pieces: () => this.reply?.files ?? [],
      replace: (next) => {
        if (!this.reply) return;
        this.reply.files = next;
        const host = this.body && $<HTMLElement>("[data-reply]", this.body);
        if (host) paintPieces(host, next);
      },
      say: (problem) => {
        if (problem) toast(problem, { ico: "alert" });
      },
    });
    on(section, "[data-nouveau]", "click", () => this.newMail());
    on(section, "[data-vue]", "click", (_e, b) => {
      const v = parseView(b.dataset.vue ?? "inbox");
      if (viewKey(v) === viewKey(this.view) && !this.reading) {
        void this.loadList();
        return;
      }
      this.reading = false;
      this.paintSplit();
      this.setView(v);
    });
    on(section, "[data-boite]", "click", (_e, b) => {
      const key = b.dataset.boite ?? "";
      if (this.opened.has(key)) this.opened.delete(key);
      else this.opened.add(key);
      this.paintBoxes();
    });
    on(section, "[data-mail]", "click", (e, b) => {
      if ((e.target as Element).closest(".mrow-check")) return;
      this.go(mailHash(b.dataset.mail ?? ""));
    });
    on<KeyboardEvent>(section, "[data-mail]", "keydown", (e, b) => {
      if (e.key === "Enter" && !(e.target as Element).closest("input")) this.go(mailHash(b.dataset.mail ?? ""));
    });
    on(section, "[data-draft]", "click", (_e, b) => this.go(draftHash(b.dataset.draft ?? "")));
    on(section, "[data-ouvrir-brouillon]", "click", (_e, b) => this.go(draftHash(b.dataset.ouvrirBrouillon ?? "")));
    on(section, "[data-ouvrir-mail]", "click", (_e, b) => this.go(mailHash(b.dataset.ouvrirMail ?? "")));
    on(section, "[data-coche]", "change", (_e, b) => {
      const ref = b.dataset.coche ?? "";
      if ((b as HTMLInputElement).checked) this.checked.add(ref);
      else this.checked.delete(ref);
      this.paintListHead();
    });
    on(section, "[data-groupe]", "click", (_e, b) => {
      const g = b.dataset.groupe as Gesture | "none";
      if (g === "none") {
        this.checked.clear();
        this.paintListHead();
        this.paintRows();
        return;
      }
      if (g === "move") {
        this.moveMenu(b, [...this.checked]);
        return;
      }
      void this.gesture([...this.checked], g);
    });
    on(section, "[data-filtre]", "click", (_e, b) => {
      this.filter = (b.dataset.filtre ?? "") as MailState;
      this.page = 1;
      for (const x of $$("[data-filtre]", section)) x.setAttribute("aria-pressed", String(x === b));
      this.keepReaderInList();
      void this.loadListAndHold();
    });
    on(section, "[data-page]", "click", (_e, b) => {
      const p = Number(b.dataset.page);
      if (!Number.isFinite(p) || p < 1) return;
      this.page = p;
      void this.loadList().then(() => $("[data-liste]", section)?.scrollTo({ top: 0 }));
    });
    on(section, "[data-recharger]", "click", () => void this.loadList());
    on(section, "[data-relever]", "click", () => void this.poll());
    on(section, "[data-dossiers]", "click", (_e, b) => this.foldersMenu(b));
    on(section, "[data-retour]", "click", () => {
      this.reading = false;
      this.paintSplit();
      if (/^#mail\/messages\/./.test(location.hash)) history.replaceState(null, "", "#mail/messages");
    });
    on(section, "[data-images]", "click", (_e, b) => void this.images(b.dataset.images ?? ""));
    on(section, "[data-act]", "click", (_e, b) => this.act(b.dataset.act ?? "", b));
    on(section, "[data-decide]", "click", (_e, b) => {
      const d = this.openedDraft();
      if (d) void this.decide(b.dataset.decide ?? "", d);
    });
    on(section, "[data-ecrire-a]", "click", (_e, b) => {
      const address = b.dataset.ecrireA ?? "";
      const c = this.contacts.find((x) => x.address === address);
      this.newMail([{ name: c?.name ?? "", address }]);
    });
    on(section, "[data-contact]", "click", (_e, b) => this.go(`#mail/contacts/${encodeURIComponent(b.dataset.contact ?? "")}`));
    on(section, "[data-retour-c]", "click", () => {
      this.showingContact = false;
      this.paintContactSplit();
      history.replaceState(null, "", "#mail/contacts");
    });
    section.addEventListener("input", (e) => {
      const t = e.target as HTMLInputElement;
      if (t.matches("[data-mq]")) {
        window.clearTimeout(this.searchTimer);
        this.q = t.value;
        this.searchTimer = window.setTimeout(() => {
          this.page = 1;
          if (this.view.kind === "drafts") {
            this.total = this.visibleDrafts().length;
            this.paintRows();
          } else if (this.view.kind === "sent") {
            this.total = this.visibleSent().length;
            this.paintRows();
          } else void this.loadList({ quiet: false });
        }, 280);
      }
      if (t.matches("[data-qc]")) {
        window.clearTimeout(this.searchTimer);
        this.contactQ = t.value;
        this.searchTimer = window.setTimeout(() => void this.loadContacts(), 250);
      }
    });
    section.addEventListener("keydown", (e) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select, [contenteditable]") || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key !== "j" && e.key !== "k") return;
      this.step(e.key === "j" ? 1 : -1);
    });
  }

  /** j/k : le mail suivant ou précédent de la liste. */
  private step(delta: number): void {
    const keys = $$<HTMLElement>("[data-mail], [data-draft]", $("[data-liste]", this.body!) ?? this.body!).map((el) =>
      el.dataset.mail !== undefined ? mailHash(el.dataset.mail) : draftHash(el.dataset.draft ?? ""),
    );
    if (!keys.length) return;
    const current = this.rowView().selected;
    const at = keys.findIndex((k) => k === (current.startsWith("brouillon/") ? draftHash(current.slice(10)) : mailHash(current)));
    const next = keys[Math.max(0, Math.min(keys.length - 1, at < 0 ? 0 : at + delta))];
    if (next) this.go(next);
  }

  private act(kind: string, b: HTMLElement): void {
    const m = this.mail;
    switch (kind) {
      case "repondre":
      case "tous":
        if (m && answerable(m)) this.startReply(kind === "tous");
        return;
      case "transferer":
        if (m) this.forward(m);
        return;
      case "preremplir":
        if (m && !m.sent) void this.prefillMail();
        return;
      case "reprendre-brouillon": {
        const d = m ? this.draftFor(m.ref) ?? this.drafts.find((x) => x.id === m.her?.draft) : null;
        if (d) this.takeDraft(d);
        return;
      }
      case "autre-version": {
        const d = m ? this.draftFor(m.ref) : null;
        if (d) void this.decide("reprendre", d);
        return;
      }
      case "cc":
        if (this.reply) {
          this.captureReply();
          this.reply.showCc = true;
          this.paintReader();
          $<HTMLInputElement>('[data-reply] [data-rcpt="cc"] [data-ac]', this.body!)?.focus();
        }
        return;
      case "cci":
        if (this.reply) {
          this.captureReply();
          this.reply.showBcc = true;
          this.paintReader();
          $<HTMLInputElement>('[data-reply] [data-rcpt="bcc"] [data-ac]', this.body!)?.focus();
        }
        return;
      case "vider":
        if (this.reply) {
          this.captureReply();
          Object.assign(this.reply, { body: "", fromDraft: "", filled: "", error: "" });
          this.paintReader();
          this.focusReply();
        }
        return;
      case "fermer-rep":
        this.reply = null;
        this.paintReader();
        return;
      case "envoyer":
        void this.sendReply();
        return;
      case "archiver":
        if (m) void this.gesture([m.ref], "archive");
        return;
      case "corbeille":
        if (m) void this.gesture([m.ref], "trash");
        return;
      case "lu":
        if (m) void this.gesture([m.ref], m.seen ? "unread" : "read");
        return;
      case "suivre":
        if (m) void this.gesture([m.ref], m.flagged ? "unflag" : "flag");
        return;
      case "deplacer":
        if (m) this.moveMenu(b, [m.ref]);
        return;
      default:
        void b;
    }
  }

  private async images(kind: string): Promise<void> {
    const m = this.mail;
    if (!m) return;
    if (kind === "fois") {
      this.imagesOnce.add(m.ref);
      this.paintReader();
      return;
    }
    const shown = kind === "toujours";
    try {
      const done = await showImages(m.ref, shown);
      m.images.shown = shown;
      if (!shown) this.imagesOnce.delete(m.ref);
      this.paintReader();
      toast(done.message || (shown ? "Ses images s'afficheront désormais pour cet expéditeur." : "Ses images resteront masquées."), { ico: "image" });
    } catch (err) {
      toast(errorText(err), { ico: "alert" });
    }
  }

  /** « Relever maintenant » : une relève passe sur toutes les boîtes (le moteur n'en relève pas une à part), une
   *  demande suffit — par la boîte de la vue si tu peux la relever (pas prête, le refus du serveur est la vraie
   *  réponse : la relève ne la touche pas), sinon la première prête que tu peux relever (une boîte qu'on te partage
   *  pour lire est relevée avec les autres). Chaque demande compte dans tes essais (trente par minute,
   *  `protocole-moi.md` § 1). */
  private async poll(): Promise<void> {
    const v = this.view;
    const writable = this.boxes.filter((b) => this.capsOf(b.key).write);
    const viewBox = "box" in v && v.box && this.capsOf(v.box).write ? v.box : "";
    const key = viewBox || ((writable.find((b) => b.ready) ?? writable[0])?.key ?? "");
    if (!key) {
      void this.loadList();
      return;
    }
    try {
      toast((await pollBox(key)).message || "Relève demandée.", { ico: "refresh" });
      window.setTimeout(() => void this.refresh(), 3000);
    } catch (err) {
      toast(errorText(err), { ico: "alert", duration: 4200 });
    }
  }

  /** « Déplacer » (ADR 0200) : les dossiers de leur boîte, un seul geste pour tous ; des mails de plusieurs boîtes ne se
   *  déplacent pas ensemble (chacune a ses dossiers). */
  private moveMenu(anchor: HTMLElement, refs: string[]): void {
    const found = refs.map((ref) => this.rows.find((r) => r.ref === ref) ?? (this.mail?.ref === ref ? this.mail : null));
    const keys = new Set(found.map((r) => r?.box ?? ""));
    const box = keys.size === 1 ? this.boxOf([...keys][0]) : undefined;
    if (!box || !refs.length) {
      toast("Choisis des mails d'une seule boîte : chacune a ses dossiers.", { ico: "alert" });
      return;
    }
    const here = new Set(found.map((r) => r?.folder ?? ""));
    const targets = moveTargets(box, here.size === 1 ? [...here][0] : "");
    if (!targets.length) {
      toast("Cette boîte n'a pas d'autre dossier où les ranger.", { ico: "folder" });
      return;
    }
    const items: MenuItem[] = [
      { header: refs.length > 1 ? `Déplacer ${refs.length} mails vers` : "Déplacer vers" },
      ...targets.map((f): MenuItem => ({ label: f.label || f.name, icon: folderIcon(f), action: () => void this.gesture(refs, "move", false, f.name) })),
    ];
    openMenu(anchor, items, { align: "right" });
  }

  private foldersMenu(anchor: HTMLElement): void {
    const views = this.boxViewList();
    const pick = (v: View) => () => {
      this.reading = false;
      this.paintSplit();
      this.setView(v);
    };
    const items: MenuItem[] = [
      { header: "Mika" },
      { label: "Ses brouillons", icon: "pen", action: pick({ kind: "drafts", box: "" }) },
      { label: "Réponse attendue", icon: "reply", action: pick({ kind: "needs_reply" }) },
      { header: "Réceptions" },
      { label: "Toutes les réceptions", icon: "inbox", action: pick({ kind: "inbox" }) },
      { label: "Suivis", icon: "star", action: pick({ kind: "flagged" }) },
      { label: "Envoyés", icon: "send", action: pick({ kind: "sent", box: "" }) },
      ...views.map((b): MenuItem => {
        const inbox = inboxOf(b.box);
        return { label: `${b.title} · Réception`, icon: b.box.level === "proprietaire" ? "mail" : "lock", action: pick({ kind: "folder", box: b.box.key, folder: inbox?.name ?? "INBOX" }) };
      }),
    ];
    openMenu(anchor, items, { align: "left" });
  }

  // ── La palette ─────────────────────────────────────────────────────

  private searchEntries(): PaletteEntry[] {
    const now = Date.now();
    const boxes = this.boxMap();
    const out: PaletteEntry[] = this.rows.slice(0, 30).map((r) => ({
      group: "Mails",
      title: r.subject || "(sans objet)",
      sub: `${personName(r.from)} · ${boxes.get(r.box)?.title ?? r.box} · ${dayAndClock(r.date, now)}`,
      icon: "mail",
      route: mailHash(r.ref),
    }));
    for (const d of this.drafts.filter((x) => x.state === "attend")) {
      out.push({ group: "Ses brouillons", title: d.subject || "(sans objet)", sub: `à ${d.to} · attend ton accord`, icon: "pen", route: draftHash(d.id) });
    }
    for (const c of this.contacts.slice(0, 40)) {
      out.push({ group: "Contacts", title: c.name || c.address, sub: c.address, icon: "user", route: `#mail/contacts/${encodeURIComponent(c.address)}` });
    }
    return out;
  }
}

