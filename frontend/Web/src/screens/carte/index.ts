/**
 * L'écran « Carte » (ADR 0194, 0195, 0196, 0259) : chercher un lieu ou une adresse et ouvrir sa fiche (Explorer), voir
 * ce qui se passe autour (Événements), calculer un itinéraire, préparer un voyage jour par jour (Voyages) — à deux : ce
 * que Mika a cherché, proposé ou ajouté se voit en rose, et se retire d'un geste. Les données : `protocole-moi.md` § 10 ; la forme : la maquette (`maquette/ecrans/carte.js`) ;
 * la carte : celle du serveur (`map/`), dessinée par MapLibre, ou son plan dessiné quand elle ne se dessine pas.
 *
 * Le navigateur ne parle qu'au serveur de Mika. Ce qui n'y est pas branché (l'index des lieux, les adresses, les
 * itinéraires) répond 503 : l'écran dit son message, à l'endroit de ce qui manque, et garde le reste. Ce qui sort du
 * serveur (une adresse, un trajet) est borné par compte (429 au-delà) : l'écran le ménage (`requests.ts`) — une adresse
 * se demande après une pause de la saisie et une fois par texte, le trajet d'un voyage une fois ses arrêts immobiles.
 *
 * Ce fichier est le cadre : les onglets, les lectures communes, la carte gardée d'un dessin à l'autre et son cadrage
 * (`fitNext`), ce qui garde la main d'un dessin à l'autre, les photos (`photos.ts` : chargées quand elles paraissent, la
 * visionneuse), la palette. Chaque onglet a son contrôleur, qui porte son état et ses gestes — `explorer.ts` (et la
 * fiche d'un lieu), `events.ts`, `itinerary.ts`, `trip.ts` (la liste des voyages et le voyage ouvert) —, avec les
 * fenêtres d'un voyage (`modals.ts`) et le glisser d'un arrêt (`drag.ts`). Le cadre délègue le dessin et les
 * gestes à l'onglet montré ; un contrôleur reçoit du cadre ce qu'il lui faut (`CarteFrame`, et son hôte), jamais
 * l'état d'un autre onglet.
 *
 * Le direct (ADR 0308, `protocole-moi.md` § 2 bis) : `trips` relit tes voyages et le voyage ouvert (pas pendant tes
 * gestes sur lui : leur relecture suit), `phone.position` ta position ; l'écran au second plan se relit à son retour.
 */
import {
  fetchCarte,
  fetchRegard,
  fetchTrip,
  fetchTrips,
  searchAddresses,
  type CarteInfo,
  type Regard,
  type Trip,
  type TripSummary,
} from "../../api/carte";
import type { PhonePosition } from "../../api/phone";
import { mapInfo } from "../../map/info";
import { LiveMap } from "../../map/live";
import { MiniMaps } from "../../map/minis";
import { regardItem, regardOf } from "../../map/notes";
import { EMPTY_SCENE, sceneBounds, type Scene } from "../../map/scene";
import { placeWhat, tripDates } from "../../map/words";
import { $, $$, on } from "../../shell/dom";
import { ico } from "../../shell/icons";
import type { PaletteEntry } from "../../shell/palette";
import type { ScreenContext, ScreenDef, ScreenTab, Shell } from "../../shell/shell";
import { onTheme } from "../../shell/theme";
import { Freshness, live, pageShown } from "../../live/live";
import { Cached, CachedMap } from "../../shared/kit";
import * as store from "../../shared/store";
import { StopDrag } from "./drag";
import { EventsTab } from "./events";
import { ExplorerTab } from "./explorer";
import { crossOrigin, focusSelector } from "./format";
import { ItineraryTab } from "./itinerary";
import { TripModals } from "./modals";
import { attachPhotos, openViewer } from "./photos";
import { AddressBook } from "./requests";
import { TripsTab } from "./trip";
import { mapPane, tripActions } from "./view";

const ID = "carte";

export interface CarteHooks {
  /** Ouvrir le chat avec une phrase préremplie (« En parler à Mika », « Demander à Mika »). */
  ask: (text: string) => void;
}

/** Ce que l'écran montre : un onglet, et dans Voyages la liste ou un voyage ouvert. */
export type View = "explorer" | "evenements" | "itineraire" | "voyages" | "voyage";

/**
 * Ce que le cadre donne à chaque onglet : les lectures communes, redessiner, savoir si l'écran est ouvert et sur quoi,
 * poser la carte avec sa scène, ses crochets (`ask`) et le `shell`. Ce qu'un onglet demande à un autre passe par son
 * hôte (`ExplorerHost`, `TripHost`, `ModalsHost`…), qui le porte au contrôleur concerné.
 */
export interface CarteFrame {
  readonly shell: Shell;
  readonly hooks: CarteHooks;
  readonly carte: Cached<CarteInfo>;
  readonly trips: Cached<TripSummary[]>;
  /** Ta dernière position (son téléphone) : la même lecture que la Position du Téléphone. */
  readonly position: Cached<PhonePosition>;
  readonly tripCache: CachedMap<Trip>;
  readonly regards: CachedMap<Regard>;
  /** Les adresses déjà trouvées, par texte : un texte ne se redemande pas (ni quand la carte bouge). */
  readonly addressBook: AddressBook;
  /** Les miniatures de la liste des voyages. */
  readonly minis: MiniMaps;
  body(): HTMLElement | null;
  /** L'écran Carte est montré (son corps dans la page). */
  open(): boolean;
  current(): View;
  paint(): void;
  /** Sa dernière position (son téléphone), si elle est connue. */
  here(): { lat: number; lon: number; label: string } | null;
  /** Le prochain dessin cadre la scène (`fit` faux : il ne la cadre pas). */
  fitNext(fit?: boolean): void;
  /** Le cadre de la carte et la scène qu'elle montrera ; `orBase` : vide parce qu'un regard ne se lit pas. */
  pane(scene: Scene, title: string, legend?: string, orBase?: boolean): string;
}

class CarteScreen {
  private readonly tabs: ScreenTab[] = [
    { id: "explorer", title: "Explorer", icon: "search" },
    { id: "evenements", title: "Événements", icon: "calendar" },
    { id: "itineraire", title: "Itinéraire", icon: "map" },
    { id: "voyages", title: "Voyages" },
  ];
  private body: HTMLElement | null = null;
  private ctx: ScreenContext | null = null;
  private current: View = "explorer";
  /** L'objet de route déjà appliqué (un regard, un voyage) : on ne le réapplique pas à chaque dessin. */
  private applied = "";
  /** Chaque fiche ouverte par un lien d'une fiche de l'autre onglet, et celle-ci (`explorer/lieu-…` → `evenements/e:…`). */
  private readonly openedFrom = new Map<string, string>();
  /** Ce que montrait le dernier dessin (la vue et son objet) : ses listes ne gardent leur défilement que pour lui. */
  private painted = "";
  /** Ce qu'un lecteur d'écran annonce (un arrêt déplacé au clavier) ; hors du corps, que chaque dessin refait. */
  private live: HTMLElement | null = null;
  /** La main se repose après un dessin : ce n'est pas la personne qui entre dans un champ. */
  private refocusing = false;
  /** Ce que la barre de titre montre d'un voyage ouvert : ses actions (lu), aucune (en lecture, introuvable). */
  private headTrip: boolean | null = null;
  /** Un dessin demandé pendant qu'on glisse un arrêt : fait quand il tombe. */
  private paintLater = false;
  /** Le direct (ADR 0308) : montré, l'écran relit ; sinon il se relit à son retour. */
  private readonly liveness = new Freshness(() => this.open() && pageShown(), () => void this.ensure(true));

  // ── Les lectures ──
  private readonly carte = new Cached<CarteInfo>(() => fetchCarte(), 60_000);
  private readonly trips = new Cached<TripSummary[]>(() => fetchTrips(), 15_000);
  /** Ta dernière position (son téléphone) : la même lecture que la Position du Téléphone. */
  private readonly position = store.position;
  private readonly tripCache = new CachedMap<Trip>((id) => fetchTrip(id), 10_000);
  private readonly regards = new CachedMap<Regard>((seq) => fetchRegard(seq), 5 * 60_000);
  /** Les adresses déjà trouvées, par texte : un texte ne se redemande pas (ni quand la carte bouge). */
  private readonly addressBook = new AddressBook((q, limit) => searchAddresses(q, limit));
  /** Les miniatures de la liste des voyages. */
  private readonly minis = new MiniMaps();

  // ── La carte ──
  /**
   * La vraie carte (`map/live.ts`, comme la Position du Téléphone) : gardée d'un dessin à l'autre, rendue quand on quitte
   * l'écran ; une autre carte servie se repose sur elle ; une qui ne se dessine pas ici laisse le plan dessiné et sa
   * note, sans réessayer — jusqu'à une autre carte servie.
   */
  private readonly map = new LiveMap({
    slot: () => (this.body ? $<HTMLElement>("[data-carte-map]", this.body) : null),
    showing: () => this.open(),
    repaint: () => this.paint(),
    scene: () => this.scene,
    options: {
      interactive: true,
      onPin: (id) => this.pinClicked(id),
      onMove: () => {
        this.explorer.mapMoved();
        this.events.mapMoved();
      },
    },
    // une scène vide se pose sur le fond de carte : le cadrage d'un regard en échec est fait
    mounted: () => {
      if (sceneBounds(this.scene) || this.sceneOrBase) this.fitNext = false;
    },
  });
  private scene: Scene = EMPTY_SCENE;
  /** Le prochain dessin cadre la scène (une recherche, un voyage ouvert) ; un choix dans la liste, non. */
  private fitNext = true;
  /** La scène est vide parce qu'un regard ne se lit pas : un cadrage demandé revient au fond de carte. */
  private sceneOrBase = false;

  // ── Les onglets ──
  private readonly explorer: ExplorerTab;
  private readonly events: EventsTab;
  private readonly itinerary: ItineraryTab;
  /** La liste des voyages et le voyage ouvert. */
  private readonly tripsTab: TripsTab;
  private readonly modals: TripModals;
  private readonly stopDrag: StopDrag;

  constructor(
    private readonly shell: Shell,
    hooks: CarteHooks,
  ) {
    const frame: CarteFrame = {
      shell,
      hooks,
      carte: this.carte,
      trips: this.trips,
      position: this.position,
      tripCache: this.tripCache,
      regards: this.regards,
      addressBook: this.addressBook,
      minis: this.minis,
      body: () => this.body,
      open: () => this.open(),
      current: () => this.current,
      paint: () => this.paint(),
      here: () => this.here(),
      fitNext: (fit = true) => {
        this.fitNext = fit;
      },
      pane: (scene, title, legend, orBase) => this.pane(scene, title, legend, orBase),
    };
    this.explorer = new ExplorerTab({
      ...frame,
      view: () => this.map.view,
      scene: () => this.scene,
      dropItem: () => {
        this.applied = "explorer/";
        history.replaceState(null, "", "#carte/explorer");
        if (this.ctx) this.ctx.item = null;
      },
      routeTo: (p) => this.itinerary.routeTo(p),
      addPlace: (trip, title, p, day, index, nonce) => this.tripsTab.addPlace(trip, title, p, day, index, nonce),
      newTripModal: (opts) => this.modals.newTripModal(opts),
    });
    this.events = new EventsTab({
      ...frame,
      view: () => this.map.view,
      scene: () => this.scene,
      dropItem: () => {
        this.applied = "evenements/";
        history.replaceState(null, "", "#carte/evenements");
        if (this.ctx) this.ctx.item = null;
      },
      routeTo: (p) => this.itinerary.routeTo(p),
      addPlace: (trip, title, p, day, index, nonce) => this.tripsTab.addPlace(trip, title, p, day, index, nonce),
      newTripModal: (opts) => this.modals.newTripModal(opts),
    });
    this.itinerary = new ItineraryTab({ ...frame, refocusing: () => this.refocusing });
    this.tripsTab = new TripsTab({
      ...frame,
      tripId: () => this.tripId(),
      syncTripHead: () => this.syncTripHead(),
      paintLater: () => this.paintLater,
      say: (text) => this.say(text),
      emptyScene: () => {
        this.scene = EMPTY_SCENE;
      },
      newTripModal: () => this.modals.newTripModal(),
      editTripModal: (trip) => this.modals.editTripModal(trip),
      addStopModal: (day) => this.modals.addStopModal(day),
    });
    this.modals = new TripModals({
      ...frame,
      tripId: () => this.tripId(),
      shownTrip: () => this.tripsTab.shownTrip(),
      addPlace: (trip, title, p, day, index, nonce, note) => this.tripsTab.addPlace(trip, title, p, day, index, nonce, note),
      gesture: (id, write, quiet) => this.tripsTab.gesture(id, write, quiet),
      invalidateTrip: (id) => this.tripsTab.invalidateTrip(id),
    });
    this.stopDrag = new StopDrag({
      body: () => this.body,
      paint: () => this.paint(),
      paintLater: () => this.paintLater,
      shownTrip: () => this.tripsTab.shownTrip(),
      moveTo: (stop, day, index) => this.tripsTab.moveTo(stop, day, index),
    });
    onTheme((dark) => {
      this.map.view?.theme(dark);
      this.minis.theme(dark);
    });
    // quitter l'écran rend sa carte (son contexte WebGL) ; elle se refait au retour
    addEventListener("hashchange", () => {
      if (!/^#carte(\/|$)/.test(location.hash)) this.map.drop();
    });
    live.onChange("trips", () => this.liveness.touch(() => void this.liveTrips()));
    live.onChange("phone.position", () => this.liveness.touch(() => void this.reread([this.position])));
  }

  /** `trips` : tes voyages et le voyage ouvert — sauf pendant tes gestes sur lui (ce qu'ils montrent avant que le
   *  serveur le dise ne recule pas ; leur relecture suit, `TripsTab.gesture`). Sur un autre onglet, seul leur nombre
   *  (l'onglet « Voyages ») suit, s'ils ont déjà été lus. */
  private async liveTrips(): Promise<void> {
    const id = this.tripId();
    const ours = !!id && !this.tripsTab.busy;
    if (ours) this.tripsTab.invalidateTrip(id);
    else this.trips.invalidate();
    if (this.current === "voyages" || this.current === "voyage") {
      await this.reread(ours ? [this.trips, this.tripCache.get(id)] : [this.trips]);
      return;
    }
    if (!this.trips.settled) return;
    await this.trips.load(true);
    if (this.open()) this.syncTabs();
  }

  /** Relire ces lectures ; si l'une a changé, l'écran suit (`ensure` : ce qui en dépend, puis le dessin). */
  private async reread(caches: Cached<unknown>[]): Promise<void> {
    const before = caches.map((c) => c.version);
    await Promise.all(caches.map((c) => c.load(true)));
    if (!this.open() || caches.every((c, i) => c.version === before[i])) return;
    await this.ensure();
  }

  def(): ScreenDef {
    return {
      id: ID,
      title: "Carte",
      icon: "map",
      tabs: this.tabs,
      defaultTab: "explorer",
      actions: (ctx) => this.actions(ctx),
      mount: (section) => this.mount(section),
      render: (body, ctx) => this.render(body, ctx),
      search: () => this.searchEntries(),
    };
  }

  // ── Le cadre ───────────────────────────────────────────────────────

  private open(): boolean {
    return this.shell.ctx?.screen === ID && !!this.body?.isConnected;
  }

  private which(ctx: ScreenContext): View {
    if (ctx.tab === "evenements") return "evenements";
    if (ctx.tab === "itineraire") return "itineraire";
    if (ctx.tab === "voyages") return ctx.item ? "voyage" : "voyages";
    return "explorer";
  }

  private tripId(): string {
    return this.current === "voyage" ? this.ctx?.item ?? "" : "";
  }

  private actions(ctx: ScreenContext): string {
    // la barre de titre se peint avant le corps : le voyage se trouve par la route, pas par `tripId()`
    this.headTrip = ctx.tab === "voyages" && ctx.item ? !!this.tripsTab.tripOf(ctx.item) : null;
    if (ctx.tab === "voyages" && ctx.item) return tripActions(ctx.item, !!this.headTrip);
    if (ctx.tab === "voyages") {
      return `<button class="btn sm primary" type="button" data-new-trip>${ico("plus", "sm")}<span class="lbl">Nouveau voyage</span></button>`;
    }
    return "";
  }

  private render(body: HTMLElement, ctx: ScreenContext): void {
    this.body = body;
    this.ctx = ctx;
    const next = this.which(ctx);
    if (next !== this.current) this.fitNext = true;
    this.current = next;
    this.applyItem(ctx);
    this.paint();
    if (!this.liveness.back()) void this.ensure();
  }

  /**
   * Ce que la route ouvre : un regard de Mika (dans Explorer, Événements ou Itinéraire), une fiche, un voyage. Une fiche
   * ouverte par un lien d'une fiche de l'autre onglet sait d'où elle vient : son retour y ramène (R2-W06).
   */
  private applyItem(ctx: ScreenContext): void {
    const key = `${ctx.tab}/${ctx.item ?? ""}`;
    if (key === this.applied) return;
    // revenir le long du lien (le « Retour » du navigateur) n'est pas en ouvrir un : la fiche garde son retour à elle
    const origin = this.openedFrom.get(this.applied) === key ? null : crossOrigin(this.applied, key);
    if (origin) this.openedFrom.set(key, this.applied);
    this.applied = key;
    const seq = regardOf(ctx.item);
    if (this.current === "explorer") this.explorer.applyItem(ctx.item, origin);
    if (this.current === "evenements") this.events.applyItem(ctx.item, origin);
    if (this.current === "itineraire" && seq) this.itinerary.applyItem(seq);
    if (this.current === "voyage") this.tripsTab.applyItem(ctx.item);
  }

  // ── Les lectures ───────────────────────────────────────────────────

  private async ensure(force = false): Promise<void> {
    const view = this.current;
    const reads: Promise<unknown>[] = [this.carte.load(force), mapInfo.load()];
    if (view === "explorer" || view === "evenements" || view === "itineraire") reads.push(this.position.load(force));
    if (view === "voyages" || view === "voyage") reads.push(this.trips.load(force));
    const seq = regardOf(this.ctx?.item);
    if (seq && (view === "explorer" || view === "evenements" || view === "itineraire")) reads.push(this.regards.get(seq).load(force));
    const id = this.tripId();
    if (id) reads.push(this.tripCache.get(id).load(force));
    await Promise.all(reads);
    this.tripsTab.opened(id, force);
    if (!this.open() || this.current !== view) return;
    // ce que Mika a trouvé, quand ce sont des événements (une miniature ouverte avant d'être lue) : il se montre dans
    // leur onglet — l'adresse est remplacée, pas empilée : « Retour » ramène d'où l'on venait, pas ici (R2-W01)
    const regard = seq ? this.regards.get(seq).value : null;
    if (view === "explorer" && seq && regard?.what === "evenements") {
      history.replaceState(null, "", `#carte/evenements/${regardItem(seq)}`);
      this.shell.refresh();
      return;
    }
    this.syncTabs();
    this.syncTripHead();
    if (view === "explorer") this.explorer.loaded();
    if (view === "evenements") this.events.loaded();
    if (view === "itineraire") this.itinerary.loaded(seq);
    this.paint();
  }

  private syncTabs(): void {
    const n = this.trips.value?.length;
    const tab = this.tabs.find((t) => t.id === "voyages");
    if (!tab) return;
    const before = tab.count;
    tab.count = n ? n : undefined;
    if (before !== tab.count) this.shell.refreshHead();
  }

  /** Le voyage ouvert vient d'être lu, ou ne l'est plus (404) : ses actions arrivent ou partent avec lui. */
  private syncTripHead(): void {
    if (this.current !== "voyage" || !this.open()) return;
    if (!!this.tripsTab.shownTrip() !== this.headTrip) this.shell.refreshHead();
  }

  /** Sa dernière position (son téléphone), si elle est connue. */
  private here(): { lat: number; lon: number; label: string } | null {
    const p = this.position.value;
    return p && p.known && p.coords ? { lat: p.coords.lat, lon: p.coords.lon, label: p.label.trim() } : null;
  }

  // ── Le dessin ──────────────────────────────────────────────────────

  private paint(): void {
    const body = this.body;
    if (!body || !this.ctx) return;
    // un arrêt qu'on glisse : le dessin attend qu'il tombe (sa poignée ne disparaît pas sous le pointeur)
    if (this.stopDrag.drag) {
      this.paintLater = true;
      return;
    }
    this.paintLater = false;
    // ce que le dessin d'avant tenait : le contrôle qui avait la main (un champ en cours de saisie, une catégorie, une
    // poignée), où en était la liste
    const active = document.activeElement as HTMLElement | null;
    const focus = active && body.contains(active) ? focusSelector(active.dataset) : null;
    const typing = active instanceof HTMLInputElement && (active.type === "search" || active.type === "text")
      ? { at: active.selectionStart, end: active.selectionEnd } : null;
    const shown = `${this.current}/${this.ctx.item ?? ""}`;
    const scrolls = shown === this.painted ? $$<HTMLElement>(".pane-scroll", body).map((el) => el.scrollTop) : [];
    this.painted = shown;
    let html: string;
    switch (this.current) {
      case "itineraire":
        html = this.itinerary.itineraryHtml();
        break;
      case "voyages":
        html = this.tripsTab.tripsHtml();
        break;
      case "voyage":
        html = this.tripsTab.tripHtml();
        break;
      case "evenements":
        html = this.events.eventsHtml();
        break;
      default:
        html = this.explorer.explorerHtml();
    }
    body.innerHTML = html;
    $$<HTMLElement>(".pane-scroll", body).forEach((el, i) => {
      if (scrolls[i] !== undefined) el.scrollTop = scrolls[i];
    });
    const again = focus ? $<HTMLElement>(focus, body) : null;
    if (again) {
      this.refocusing = true;
      try {
        again.focus({ preventScroll: true });
        if (typing && typing.at !== null && again instanceof HTMLInputElement) again.setSelectionRange(typing.at, typing.end ?? typing.at);
      } finally {
        this.refocusing = false;
      }
    }
    this.lodgeView();
    if (this.current === "voyages") this.minis.attach(body);
    attachPhotos(body);
  }

  /** Dire à un lecteur d'écran ce qui vient de se passer (sans bouger la main). */
  private say(text: string): void {
    if (!this.live || !text) return;
    this.live.textContent = "";
    window.setTimeout(() => {
      if (this.live) this.live.textContent = text;
    }, 30);
  }

  /** Le cadre de la carte et la scène qu'elle montrera ; `orBase` : vide parce qu'un regard ne se lit pas. */
  private pane(scene: Scene, title: string, legend = "", orBase = false): string {
    this.scene = scene;
    this.sceneOrBase = orBase;
    const info = mapInfo.value;
    return mapPane({ live: this.map.wanted(info, scene), scene, title, why: this.map.why(info, mapInfo.error), legend });
  }

  /** Après un dessin : la carte se repose dans son cadre et montre la scène (sinon elle se monte, ou s'en va). */
  private lodgeView(): void {
    const view = this.map.lodge(mapInfo.value);
    if (!view) return;
    // un cadrage demandé se fait une fois, même sur une scène inchangée (une recherche relancée qui rend la même)
    view.show(this.scene, this.fitNext, this.sceneOrBase);
    // il attend une scène qui ait quelque chose à montrer (un regard qui se lit encore) ; un regard en échec revient
    // au fond de carte
    if (sceneBounds(this.scene) || this.sceneOrBase) this.fitNext = false;
  }

  /** Une épingle touchée : à l'onglet montré (un lieu d'Explorer, un arrêt ou un lieu de « Sur la route »). */
  private pinClicked(id: string): void {
    if (this.current === "explorer") this.explorer.pinClicked(id);
    else if (this.current === "evenements") this.events.pinClicked(id);
    else if (this.current === "voyage") this.tripsTab.pinClicked(id);
  }

  // ── Les gestes ─────────────────────────────────────────────────────

  private mount(section: HTMLElement): void {
    this.live = document.createElement("p");
    this.live.className = "carte-live";
    this.live.setAttribute("aria-live", "polite");
    section.append(this.live);
    // chaque onglet branche les siens : leurs éléments ne sont dans le corps que quand il est montré
    this.explorer.mount(section);
    this.events.mount(section);
    this.itinerary.mount(section);
    this.tripsTab.mount(section);
    this.stopDrag.mount(section);
    on(section, "[data-retry]", "click", () => void this.ensure(true));
    // une photo d'une fiche : la visionneuse, sur les photos de cette fiche ; la tuile du plan recadre la carte
    on(section, "[data-photo]", "click", (_e, b) => {
      const photos = this.current === "evenements" ? this.events.photos() : this.current === "explorer" ? this.explorer.photos() : [];
      openViewer(photos, Number(b.dataset.photo) || 0);
    });
    on(section, "[data-plan]", "click", () => {
      this.fitNext = true;
      this.paint();
    });
    on(section, "[data-relogin]", "click", () => location.reload());
  }

  private searchEntries(): PaletteEntry[] {
    const now = Date.now();
    const trips = (this.trips.value ?? []).map((t): PaletteEntry => ({
      group: "Voyages",
      title: t.title || "Sans titre",
      sub: tripDates(t.start, t.days, now) || "sans date",
      icon: "map",
      route: `#carte/voyages/${encodeURIComponent(t.id)}`,
    }));
    const places = this.explorer.places.slice(0, 8).map((p, i): PaletteEntry => ({
      group: "Lieux",
      title: p.name,
      sub: placeWhat(p),
      icon: "pin",
      action: () => this.explorer.choose(p, i),
    }));
    return [...trips, ...places];
  }
}

export function carteScreen(shell: Shell, hooks: CarteHooks): ScreenDef {
  return new CarteScreen(shell, hooks).def();
}
