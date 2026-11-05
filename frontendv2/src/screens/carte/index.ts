/**
 * L'écran « Carte » (ADR 0194, 0195, 0196) : chercher un lieu ou une adresse (Explorer), calculer un itinéraire,
 * préparer un voyage jour par jour (Voyages) — à deux : ce que Mika a cherché, proposé ou ajouté se voit en rose, et
 * se retire d'un geste. Les données : `protocole-moi.md` § 10 ; la forme : la maquette (`maquette/ecrans/carte.js`) ;
 * la carte : celle du serveur (`map/`), dessinée par MapLibre, ou son plan dessiné quand elle ne se dessine pas.
 *
 * Le navigateur ne parle qu'au serveur de Mika. Ce qui n'y est pas branché (l'index des lieux, les adresses, les
 * itinéraires) répond 503 : l'écran dit son message, à l'endroit de ce qui manque, et garde le reste. Ce qui sort du
 * serveur (une adresse, un trajet) est borné par compte (429 au-delà) : l'écran le ménage (`requests.ts`) — une adresse
 * se demande après une pause de la saisie et une fois par texte, le trajet d'un voyage une fois ses arrêts immobiles.
 */
import {
  addStop,
  changeTrip,
  createTrip,
  fetchCarte,
  fetchOnRoute,
  fetchRegard,
  fetchRoute,
  fetchTrip,
  fetchTripRoute,
  fetchTrips,
  moveStop,
  optimizeDay,
  removeStop,
  removeTrip,
  searchAddresses,
  searchPlaces,
  tripGpxUrl,
  AVOIDS,
  CARTE_LIMITS,
  MODES,
  type CarteInfo,
  type Place,
  type Regard,
  type Route,
  type Trip,
  type TripSummary,
} from "../../api/carte";
import { ApiError } from "../../api/moi";
import { fetchPosition, type MapInfo, type PhonePosition } from "../../api/phone";
import { regardLine, regardPins, tripPins } from "../../map/cards";
import { infoKey, mapInfo } from "../../map/info";
import { loadMapView, noteWebglMissing, webglMissing } from "../../map/load";
import { covers } from "../../map/mapgeo";
import { MiniMaps } from "../../map/minis";
import { regardItem, regardOf } from "../../map/notes";
import { safeDecode, type LatLon } from "../../map/polyline";
import { EMPTY_SCENE, sceneBounds, straightLine, type Scene, type ScenePin } from "../../map/scene";
import type { MapView } from "../../map/view";
import { modeWords, placeWhat, tripDates } from "../../map/words";
import { $, $$, h, on } from "../../shell/dom";
import { closeModal, openMenu, openModal, toast, type MenuItem } from "../../shell/float";
import { ico } from "../../shell/icons";
import type { PaletteEntry } from "../../shell/palette";
import type { ScreenContext, ScreenDef, ScreenTab, Shell } from "../../shell/shell";
import { isDark, onTheme } from "../../shell/theme";
import { Cached, CachedMap, confirmModal, errorBlock, failureText, loadingBlock, newNonce, toastFailure } from "../parametres/kit";
import {
  alongPlace,
  askAboutPlace,
  askAboutRoute,
  askAboutTrip,
  dropIndex,
  fileName,
  focusSelector,
  movedTrip,
  movedWords,
  noopMove,
  removedTrip,
  routeGpx,
  stepMove,
  tripLines,
  tripRouteKey,
} from "./format";
import { ADDRESS_WAIT_MS, AddressBook, alongAfterRoute, GestureQueue, refused, TripRoutes, wantsAddress } from "./requests";
import {
  chosenPoints,
  explorerMarkup,
  itiKey,
  itineraryMarkup,
  legendMarkup,
  mapPane,
  placeId,
  pointLetter,
  searchTitle,
  selectedPlace,
  tripEditorMarkup,
  tripsMarkup,
  typedPoint,
  type ItiPoint,
  type Where,
} from "./view";

const ID = "carte";
/** Combien de lieux une recherche montre. */
const PLACES_SHOWN = 30;
/** Combien d'adresses une liste de propositions montre (un point d'itinéraire, un arrêt). */
const ADDRESSES_SUGGESTED = 4;
/** La largeur du couloir de « Sur la route », en mètres (les mots de la maquette : « à moins de 10 km »). */
const CORRIDOR_M = 10_000;
const TYPE_MS = 350;

export interface CarteHooks {
  /** Ouvrir le chat avec une phrase préremplie (« En parler à Mika », « Demander à Mika »). */
  ask: (text: string) => void;
}

type View = "explorer" | "itineraire" | "voyages" | "voyage";

interface Suggestion {
  label: string;
  sub: string;
  mine?: boolean;
  point: ItiPoint;
}

/** Les propositions du point ouvert : sa position, les adresses (après une pause de la saisie), les lieux de l'index. */
interface Suggestions {
  mine: Suggestion[];
  addresses: Suggestion[];
  places: Suggestion[];
  /** Ce que les adresses n'ont pas pu dire (429, 503), en mots. */
  note: string;
}

const NO_SUGGESTIONS: Suggestions = { mine: [], addresses: [], places: [], note: "" };

/** « Sur la route » d'un voyage : ses lieux, et pour quels arrêts ils ont été cherchés (`key`). */
interface AlongState {
  trip: string;
  cat: string;
  places: Place[];
  error: string;
  loading: boolean;
  routed: boolean;
  /** `tripRouteKey` du voyage quand ils ont été cherchés : un autre trajet, ils se recherchent. */
  key: string;
  /** Une clé d'envoi par lieu de la liste : un double clic sur « Ajouter » ne l'ajoute qu'une fois. */
  keys: string[];
  /** Le lieu qui s'ajoute. */
  sending: number | null;
  /**
   * Un de ses lieux vient d'être ajouté : le trajet change (il y passe), la liste reste vraie — elle prend la clé du
   * prochain trajet au lieu de se rechercher (dix ajouts : dix trajets relus, pas vingt demandes).
   */
  adopt: boolean;
}

function emptyAlong(trip: string): AlongState {
  return { trip, cat: "", places: [], error: "", loading: false, routed: true, key: "", keys: [], sending: null, adopt: false };
}

/** Un lieu tel que la liste l'attend, depuis ce qu'un regard a gardé (un point nommé n'a ni sorte ni distance). */
function asPlace(p: Partial<Place>): Place {
  return {
    id: p.id ?? "", name: p.name ?? "", kind: p.kind ?? "", kind_fr: p.kind_fr ?? "", category: p.category ?? "",
    lat: p.lat ?? NaN, lon: p.lon ?? NaN, town: p.town ?? "", distance_m: p.distance_m ?? null, along_m: p.along_m ?? null,
  };
}

function emptyPoint(): ItiPoint {
  return { query: "", name: "", lat: null, lon: null };
}

function suggestionOf(p: Place): Suggestion {
  return { label: p.name, sub: placeWhat(p), point: { query: p.name, name: p.name, lat: p.lat, lon: p.lon } };
}

/** Ce qui désigne un lieu, d'une recherche à l'autre (son identifiant d'index change à chaque reconstruction). */
function placeIntent(p: Place): string {
  return `${p.lat},${p.lon},${p.name}`;
}

function gone(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

/** Télécharger un texte comme fichier (fait dans le navigateur, sans réseau). */
function download(name: string, text: string, type: string): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

class CarteScreen {
  private readonly tabs: ScreenTab[] = [
    { id: "explorer", title: "Explorer", icon: "search" },
    { id: "itineraire", title: "Itinéraire", icon: "map" },
    { id: "voyages", title: "Voyages" },
  ];
  private body: HTMLElement | null = null;
  private ctx: ScreenContext | null = null;
  private current: View = "explorer";
  /** L'objet de route déjà appliqué (un regard, un voyage) : on ne le réapplique pas à chaque dessin. */
  private applied = "";
  /** Ce que montrait le dernier dessin (la vue et son objet) : ses listes ne gardent leur défilement que pour lui. */
  private painted = "";
  /** Ce qu'un lecteur d'écran annonce (un arrêt déplacé au clavier) ; hors du corps, que chaque dessin refait. */
  private live: HTMLElement | null = null;
  /** La main se repose après un dessin : ce n'est pas la personne qui entre dans un champ. */
  private refocusing = false;

  // ── Les lectures ──
  private readonly carte = new Cached<CarteInfo>(() => fetchCarte(), 60_000);
  private readonly trips = new Cached<TripSummary[]>(() => fetchTrips(), 15_000);
  private readonly position = new Cached<PhonePosition>(() => fetchPosition(), 30_000);
  private readonly tripCache = new CachedMap<Trip>((id) => fetchTrip(id), 10_000);
  /** Le trajet de chaque voyage, pour ses arrêts tels qu'ils sont ; relu après un geste, une fois qu'ils ne bougent plus. */
  private readonly routes = new TripRoutes((id) => fetchTripRoute(id), (id) => this.routeLanded(id));
  private readonly regards = new CachedMap<Regard>((seq) => fetchRegard(seq), 5 * 60_000);
  /** Les adresses déjà trouvées, par texte : un texte ne se redemande pas (ni quand la carte bouge). */
  private readonly addressBook = new AddressBook((q, limit) => searchAddresses(q, limit));
  /** Les miniatures de la liste des voyages. */
  private readonly minis = new MiniMaps();

  // ── La carte ──
  private view: MapView | null = null;
  private viewKey = "";
  private viewToken = 0;
  /** La carte du serveur qui ne s'est pas dessinée ici : le plan dessiné, sans réessayer (une autre se réessaie). */
  private failedKey: string | null = null;
  /** Pourquoi elle ne s'est pas dessinée : ses tuiles, MapLibre qui ne vient pas, ou ce navigateur (pas de WebGL). */
  private failedWhy: "tiles" | "load" | "webgl" = "webgl";
  private scene: Scene = EMPTY_SCENE;
  /** Le prochain dessin cadre la scène (une recherche, un voyage ouvert) ; un choix dans la liste, non. */
  private fitNext = true;

  // ── Explorer ──
  private q = "";
  private cat = "";
  private where: Where | null = null;
  private places: Place[] = [];
  private addresses: Place[] = [];
  /** Le texte dont les adresses montrées viennent : la carte bougée, une catégorie ne les redemandent pas. */
  private addrQ = "";
  private error = "";
  private addrError = "";
  private loading = false;
  private searched = false;
  private sel: string | null = null;
  private regard: string | null = null;
  private hint = "";
  private searchSeq = 0;
  private typeTimer = 0;
  private moveTimer = 0;
  private addrTimer = 0;
  /** La dernière frappe (dans la recherche, un point, un arrêt) : une adresse attend `ADDRESS_WAIT_MS` après elle. */
  private typedAt = 0;

  // ── Itinéraire ──
  private points: ItiPoint[] = [emptyPoint(), emptyPoint()];
  private mode = "voiture";
  private avoid: string[] = [];
  private route: Route | null = null;
  /** `itiKey` des points, du mode et de ce qu'évitait le trajet montré : un autre, il est passé. */
  private routeFor = "";
  private routeError = "";
  private routing = false;
  private routeSeq = 0;
  private suggestFor: number | null = null;
  private sugg: Suggestions = NO_SUGGESTIONS;
  private suggestSeq = 0;
  /** Ce que Mika a calculé (un regard du chat), tel qu'elle l'a gardé, jusqu'à ton premier changement. */
  private itiRegard: { title: string; distance_m: number | null; duration_s: number | null; line: LatLon[]; key: string } | null = null;
  /** Le regard dont les points ont été posés : il ne se repose pas sur ce que tu as changé depuis. */
  private itiFrom: string | null = null;
  private pointTimer = 0;
  private pointAddrTimer = 0;
  /** « En faire un voyage » : en cours, et la clé de cette intention (redemandé après une panne : le même voyage). */
  private sendingTrip = false;
  private tripIntent: { key: string; nonce: string } | null = null;

  // ── Un voyage ──
  private along: AlongState = emptyAlong("");
  private alongSeq = 0;
  /** Un voyage montré avant que le serveur le dise (un arrêt déplacé, retiré). */
  private optimistic: Trip | null = null;
  private drag: { stop: string; pointer: number; target: { day: number; before: string | null } | null } | null = null;
  /** Un dessin demandé pendant qu'on glisse un arrêt : fait quand il tombe. */
  private paintLater = false;
  /** Les gestes sur le voyage, l'un après l'autre. */
  private readonly gestures = new GestureQueue();
  private optimizing = false;

  constructor(
    private readonly shell: Shell,
    private readonly hooks: CarteHooks,
  ) {
    onTheme((dark) => {
      this.view?.theme(dark);
      this.minis.theme(dark);
    });
    // quitter l'écran rend sa carte (son contexte WebGL) ; elle se refait au retour
    addEventListener("hashchange", () => {
      if (!/^#carte(\/|$)/.test(location.hash)) this.dropView();
    });
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
    if (ctx.tab === "itineraire") return "itineraire";
    if (ctx.tab === "voyages") return ctx.item ? "voyage" : "voyages";
    return "explorer";
  }

  private tripId(): string {
    return this.current === "voyage" ? this.ctx?.item ?? "" : "";
  }

  private actions(ctx: ScreenContext): string {
    if (ctx.tab === "voyages" && ctx.item) {
      const id = ctx.item;
      return `<button class="btn sm" type="button" data-optimize title="Le meilleur ordre des arrêts de chaque jour ; le départ et la nuit ne bougent pas">${ico("refresh", "sm")}<span class="lbl">Optimiser l'ordre</span></button>
        <a class="btn sm" href="${h(tripGpxUrl(id))}" download title="Le tracé et les arrêts, pour un GPS ou une app de navigation">${ico("download", "sm")}<span class="lbl">GPX</span></a>
        <button class="btn sm mika" type="button" data-ask-trip>${ico("sparkle", "sm")}<span class="lbl">Demander à Mika</span></button>`;
    }
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
    void this.ensure();
  }

  /** Ce que la route ouvre : un regard de Mika (dans Explorer ou Itinéraire), un voyage. */
  private applyItem(ctx: ScreenContext): void {
    const key = `${ctx.tab}/${ctx.item ?? ""}`;
    if (key === this.applied) return;
    this.applied = key;
    const seq = regardOf(ctx.item);
    if (this.current === "explorer") {
      this.regard = seq;
      if (seq) {
        this.sel = null;
        this.fitNext = true;
      } else if (this.places.length && !this.searched) {
        this.places = [];
      }
    }
    if (this.current === "itineraire" && seq) {
      this.itiRegard = null;
      this.itiFrom = null;
      this.applyRouteRegard(seq);
    }
    if (this.current === "voyage") {
      this.optimistic = null;
      this.fitNext = true;
      if (this.along.trip !== ctx.item) this.along = emptyAlong(ctx.item ?? "");
    }
  }

  // ── Les lectures ───────────────────────────────────────────────────

  private async ensure(force = false): Promise<void> {
    const view = this.current;
    const reads: Promise<unknown>[] = [this.carte.load(force), mapInfo.load()];
    if (view === "explorer" || view === "itineraire") reads.push(this.position.load(force));
    if (view === "voyages" || view === "voyage") reads.push(this.trips.load(force));
    const seq = regardOf(this.ctx?.item);
    if (seq && (view === "explorer" || view === "itineraire")) reads.push(this.regards.get(seq).load(force));
    const id = this.tripId();
    if (id) reads.push(this.tripCache.get(id).load(force));
    await Promise.all(reads);
    // le trajet d'un voyage qu'on ouvre : de suite s'il n'est plus celui de ses arrêts (des gestes en cours le reliront)
    const trip = id ? this.tripCache.get(id).value : null;
    if (trip && !this.gestures.busy) this.routes.want(trip, { soon: true, force });
    if (!this.open() || this.current !== view) return;
    this.syncTabs();
    if (view === "explorer" && this.where === null && this.position.settled) {
      this.where = this.here() ? "moi" : "zone";
    }
    if (view === "itineraire" && seq && this.itiFrom !== seq && this.regards.get(seq).value) this.applyRouteRegard(seq);
    // un itinéraire part de sa position, quand son téléphone l'a donnée (comme la maquette : « Ma position · … »)
    const start = this.points[0];
    const here = this.here();
    if (view === "itineraire" && !seq && here && !start.query && start.lat === null) this.points[0] = this.herePoint(here);
    this.paint();
  }

  private syncTabs(): void {
    const n = this.trips.value?.length;
    const before = this.tabs[2].count;
    this.tabs[2].count = n ? n : undefined;
    if (before !== this.tabs[2].count) this.shell.refreshHead();
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
    if (this.drag) {
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
        html = this.itineraryHtml();
        break;
      case "voyages":
        html = this.tripsHtml();
        break;
      case "voyage":
        html = this.tripHtml();
        break;
      default:
        html = this.explorerHtml();
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
  }

  /** Dire à un lecteur d'écran ce qui vient de se passer (sans bouger la main). */
  private say(text: string): void {
    if (!this.live || !text) return;
    this.live.textContent = "";
    window.setTimeout(() => {
      if (this.live) this.live.textContent = text;
    }, 30);
  }

  /** La carte du serveur, si elle se dessine ici : prête, pas déjà refusée, et elle montre au moins un point de la scène. */
  private liveWanted(scene: Scene): boolean {
    const info = mapInfo.value;
    // une autre carte servie depuis l'échec (le serveur l'a dite injoignable, puis de nouveau prête) : on réessaie
    if (this.failedKey !== null && this.failedKey !== infoKey(info)) this.failedKey = null;
    if (!info?.ready || !info.tiles || webglMissing() || this.failedKey === infoKey(info)) return false;
    const points: LatLon[] = [...scene.pins.map((p): LatLon => [p.lat, p.lon]), ...scene.lines.flatMap((l) => l.points)];
    return !points.length || points.some(([la, lo]) => covers(info, la, lo));
  }

  /** Pourquoi un plan plutôt que la carte, en mots. */
  private whyDrawn(): string {
    const info = mapInfo.value;
    if (!info) return mapInfo.error ? failureText(mapInfo.error) : "la carte du serveur se lit…";
    if (!info.ready) return info.reason || "aucune carte n'est réglée sur ce serveur.";
    if (webglMissing()) return "elle ne se dessine pas dans ce navigateur.";
    if (this.failedKey === infoKey(info)) {
      return this.failedWhy === "tiles" ? "ses tuiles ne se lisent pas sur ce serveur en ce moment."
        : this.failedWhy === "load" ? "elle n'a pas pu se charger : recharge la page." : "elle ne se dessine pas dans ce navigateur.";
    }
    return "ces lieux sont hors de la zone qu'elle couvre.";
  }

  private pane(scene: Scene, title: string, legend = ""): string {
    this.scene = scene;
    return mapPane({ live: this.liveWanted(scene), scene, title, why: this.whyDrawn(), legend });
  }

  private lodgeView(): void {
    const body = this.body;
    const slot = body ? $<HTMLElement>("[data-carte-map]", body) : null;
    if (!slot) {
      this.dropView();
      return;
    }
    const info = mapInfo.value;
    if (!info) return;
    if (this.view) {
      slot.replaceWith(this.view.host);
      if (infoKey(info) !== this.viewKey) {
        this.view.restyle(info);
        this.viewKey = infoKey(info);
      }
      this.view.resize();
      this.view.show(this.scene, this.fitNext);
      // un cadrage demandé attend une scène qui ait quelque chose à montrer (un regard qui se lit encore)
      if (sceneBounds(this.scene)) this.fitNext = false;
      return;
    }
    void this.startView(info);
  }

  private async startView(info: MapInfo): Promise<void> {
    const token = ++this.viewToken;
    const key = infoKey(info);
    let kit: Awaited<ReturnType<typeof loadMapView>>;
    try {
      kit = await loadMapView();
    } catch {
      this.mapFailed(key, "load");
      return;
    }
    if (token !== this.viewToken || this.view || !this.open()) return;
    const slot = this.body ? $<HTMLElement>("[data-carte-map]", this.body) : null;
    if (!slot) return;
    try {
      this.view = new kit.MapView(kit.lib, slot, info, this.scene, {
        dark: isDark(),
        interactive: true,
        onPin: (id) => this.pinClicked(id),
        onFail: () => this.mapFailed(this.viewKey || key, "tiles"),
        onMove: () => this.mapMoved(),
      });
      this.viewKey = key;
      if (sceneBounds(this.scene)) this.fitNext = false;
    } catch {
      noteWebglMissing();
      this.mapFailed(key, "webgl");
    }
  }

  private mapFailed(key: string, why: "tiles" | "load" | "webgl"): void {
    this.failedKey = key;
    this.failedWhy = why;
    this.dropView();
    if (this.open()) this.paint();
  }

  private dropView(): void {
    this.viewToken += 1;
    this.view?.remove();
    this.view = null;
    this.viewKey = "";
  }

  private pinClicked(id: string): void {
    if (this.current === "explorer") {
      this.sel = id;
      this.paint();
    } else if (this.current === "voyage") {
      const li = this.body ? $<HTMLElement>(`[data-stop="${CSS.escape(id)}"]`, this.body) : null;
      li?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      li?.classList.add("flash");
      window.setTimeout(() => li?.classList.remove("flash"), 1200);
    }
  }

  /** La personne a bougé la carte : « Dans cette zone » cherche dans ce qu'elle montre maintenant (ses lieux seulement). */
  private mapMoved(): void {
    if (this.current !== "explorer" || this.where !== "zone" || this.regard || (!this.q.trim() && !this.cat)) return;
    window.clearTimeout(this.moveTimer);
    this.moveTimer = window.setTimeout(() => void this.search(false), 500);
  }

  // ── Explorer ───────────────────────────────────────────────────────

  private regardShown(): { regard: Regard; seq: string } | null {
    const seq = this.regard;
    const cached = seq ? this.regards.get(seq) : null;
    // oublié depuis (404) : ce qu'on en avait lu ne se montre plus
    const regard = cached && !gone(cached.error) ? cached.value : null;
    return seq && regard ? { regard, seq } : null;
  }

  private explorerHtml(): string {
    const shown = this.regardShown();
    const seq = this.regard;
    let places = this.places;
    let scene: Scene;
    let legend: string;
    if (shown) {
      places = shown.regard.places.map(asPlace);
      // ses épingles portent l'identifiant de leur lieu dans la liste (`placeId`) : un clic sur l'une choisit l'autre
      scene = { pins: regardPins(shown.regard).map((p) => ({ ...p, selected: p.id === this.sel })), lines: regardLine(shown.regard) };
      legend = legendMarkup("sparkle", shown.regard.title || "Ce que Mika a cherché", `${places.length} lieu${places.length > 1 ? "x" : ""} · ce que Mika a ${shown.regard.what === "trajet" || shown.regard.kind === "map" ? "montré" : "cherché"}`);
    } else if (seq) {
      // son regard se lit encore (ou n'est plus là) : rien de la recherche d'avant
      places = [];
      scene = { pins: [], lines: [] };
      legend = "";
    } else {
      const pins: ScenePin[] = [
        ...this.places.map((p, i) => ({ id: placeId(p, i), lat: p.lat, lon: p.lon, title: p.name, selected: this.sel === placeId(p, i) })),
        ...this.addresses.map((p, i) => ({ id: `a${i}`, lat: p.lat, lon: p.lon, title: p.name, selected: this.sel === `a${i}` })),
      ];
      const here = this.where === "moi" ? this.here() : null;
      scene = { pins, lines: [], here: here ? { lat: here.lat, lon: here.lon } : null };
      legend = this.searched
        ? legendMarkup("search", searchTitle(this.carte.value, this.q, this.cat),
          `${this.places.length} lieu${this.places.length > 1 ? "x" : ""} · ${this.where === "moi" ? "autour de ta position" : "dans cette zone"}`)
        : "";
    }
    const pending = seq && !shown ? this.regards.get(seq) : null;
    const map = this.pane(scene, shown ? shown.regard.title : "Carte des lieux", legend);
    return explorerMarkup({
      info: this.carte.value,
      q: this.q,
      cat: this.cat,
      where: this.where ?? "zone",
      places,
      addresses: seq ? [] : this.addresses,
      error: seq ? "" : this.error,
      regardError: pending?.error ? failureText(pending.error) : "",
      addrError: seq ? "" : this.addrError,
      loading: seq ? !!pending && !pending.error : this.loading,
      searched: seq ? !!shown : this.searched,
      sel: this.sel,
      regard: shown ? {
        title: shown.regard.title,
        route: shown.regard.what === "trajet" || shown.regard.kind === "map",
        links: [
          ...(shown.regard.what === "trajet" ? [{ href: `#carte/itineraire/${regardItem(shown.seq)}`, label: "Ouvrir dans Itinéraire" }] : []),
          ...(shown.regard.trip ? [{ href: `#carte/voyages/${encodeURIComponent(shown.regard.trip)}`, label: "Ouvrir le voyage" }] : []),
        ],
      } : null,
      hint: this.hint,
      map,
    });
  }

  /**
   * Une recherche : l'index local (le texte, la catégorie, autour de toi ou dans la zone), et les adresses — elles ne
   * dépendent pas de la zone : seul un autre texte les redemande (`findAddresses`).
   */
  private async search(refit = true): Promise<void> {
    const q = this.q.trim();
    const seq = ++this.searchSeq;
    this.hint = "";
    if (!q && !this.cat) {
      window.clearTimeout(this.addrTimer);
      this.places = [];
      this.addresses = [];
      this.addrQ = "";
      this.error = "";
      this.addrError = "";
      this.searched = false;
      this.loading = false;
      this.paint();
      return;
    }
    await this.position.load();
    let near: { lat: number; lon: number } | null = null;
    let bbox: [number, number, number, number] | null = null;
    const where = this.where ?? "zone";
    if (where === "moi") {
      const here = this.here();
      if (here) near = here;
      else this.hint = "Mika ne sait pas où tu es : ton téléphone ne lui a pas donné ta position. Elle cherche dans la zone de la carte.";
    }
    if (!near) {
      if (this.view) bbox = this.view.frame();
      else {
        const b = sceneBounds(this.scene) ?? mapInfo.value?.bounds ?? null;
        bbox = b ? [b[0], b[1], b[2], b[3]] : null;
      }
    }
    if (!q && !near && !bbox) {
      this.hint = "Choisis où chercher : autour de toi, ou dans la zone de la carte.";
      this.paint();
      return;
    }
    this.loading = true;
    this.paint();
    let places: Place[] = [];
    let error = "";
    try {
      places = await searchPlaces({ q, cat: this.cat, near, bbox, limit: PLACES_SHOWN });
    } catch (err) {
      error = failureText(err);
    }
    if (seq !== this.searchSeq) return;
    this.places = places;
    this.error = error;
    if (q !== this.addrQ) this.findAddresses(q, places.length > 0);
    this.loading = false;
    this.searched = true;
    if (this.sel && !selectedPlace({ places: this.places, addresses: this.addresses, sel: this.sel })) this.sel = null;
    this.fitNext = refit && where === "moi";
    if (this.open() && this.current === "explorer") this.paint();
  }

  /**
   * Les adresses d'un texte nouveau : un numéro, ou cinq caractères que l'index ne connaît pas — à la Géoplateforme,
   * une fois la saisie arrêtée (`ADDRESS_WAIT_MS`), et une fois par texte. Sans adresses branchées, un numéro reçoit le
   * message du serveur (503).
   */
  private findAddresses(q: string, hasPlaces: boolean): void {
    window.clearTimeout(this.addrTimer);
    this.addrQ = q;
    this.addresses = [];
    this.addrError = "";
    const ready = !!this.carte.value?.addresses.ready;
    if (!wantsAddress(q) || (!/\d/.test(q) && (!ready || hasPlaces))) return;
    const known = this.addressBook.peek(q);
    if (known) {
      this.addresses = known;
      return;
    }
    this.addrTimer = window.setTimeout(() => void this.lookAddresses(q), Math.max(0, this.typedAt + ADDRESS_WAIT_MS - Date.now()));
  }

  private async lookAddresses(q: string): Promise<void> {
    if (this.addrQ !== q || this.q.trim() !== q) return;
    let addresses: Place[] = [];
    let addrError = "";
    try {
      addresses = await this.addressBook.lookup(q);
    } catch (err) {
      addrError = failureText(err);
    }
    if (this.addrQ !== q || this.q.trim() !== q) return;
    this.addresses = addresses;
    this.addrError = addrError;
    if (this.sel && !selectedPlace({ places: this.places, addresses: this.addresses, sel: this.sel })) this.sel = null;
    if (this.open() && this.current === "explorer") this.paint();
  }

  /** Quitter un regard de Mika pour une recherche à soi (l'adresse suit, sans redessiner l'écran). */
  private leaveRegard(): void {
    if (!this.regard) return;
    this.regard = null;
    this.sel = null;
    this.applied = "explorer/";
    history.replaceState(null, "", "#carte/explorer");
    if (this.ctx) this.ctx.item = null;
  }

  private chosenPlace(): Place | null {
    const shown = this.regardShown();
    if (shown) {
      const places = shown.regard.places.map(asPlace);
      return places.find((p, i) => placeId(p, i) === this.sel) ?? null;
    }
    return selectedPlace({ places: this.places, addresses: this.addresses, sel: this.sel });
  }

  /** Sa position, en point d'un itinéraire (son nom, celui du lieu : c'est lui qu'un voyage gardera). */
  private herePoint(here: { lat: number; lon: number; label: string }): ItiPoint {
    return { query: here.label ? `Ma position · ${here.label}` : "Ma position", name: here.label || "Ma position", lat: here.lat, lon: here.lon };
  }

  private routeTo(p: Place): void {
    const here = this.here();
    this.points = [here ? this.herePoint(here) : emptyPoint(), { query: p.name, name: p.name, lat: p.lat, lon: p.lon }];
    this.route = null;
    this.routeFor = "";
    this.routeError = "";
    this.itiRegard = null;
    this.fitNext = true;
    this.shell.go("#carte/itineraire");
    void this.computeRoute();
  }

  private async addToTrip(anchor: HTMLElement, p: Place): Promise<void> {
    await this.trips.load();
    const list = (this.trips.value ?? []).slice(0, 8);
    const items: MenuItem[] = [
      { header: "Ajouter au voyage" },
      ...list.map((t): MenuItem => {
        // la clé de cette intention, faite avec le menu : un clic redit ne l'ajoute qu'une fois
        const nonce = newNonce();
        return {
          label: `${t.title || "Sans titre"}${t.start ? ` · ${tripDates(t.start, t.days, Date.now()).replace(/ · passé$/, "")}` : ""}`,
          icon: "map",
          action: () => void this.addPlace(t.id, t.title, p, Math.max(1, t.days), -1, nonce),
        };
      }),
      ...(list.length ? ["sep" as const] : []),
      { label: "Nouveau voyage…", icon: "plus", action: () => this.newTripModal({ first: p }) },
    ];
    openMenu(anchor, items);
  }

  /**
   * Ajouter un lieu à un voyage, avec la clé de cette intention (`nonce`) : redit (un double clic, un réessai), le serveur
   * ne l'ajoute qu'une fois. Au voyage ouvert, après ses autres gestes. Rend ce qui s'est passé (`error` : son refus).
   */
  private async addPlace(trip: string, title: string, p: Place, day: number, index: number, nonce: string,
    note = ""): Promise<{ ok: boolean; error: unknown }> {
    const write = async () => {
      const done = await addStop(trip, { name: p.name.slice(0, CARTE_LIMITS.name) || "Lieu", lat: p.lat, lon: p.lon, kind: (p.kind_fr || "").slice(0, CARTE_LIMITS.kind),
        day, index, ...(note ? { note } : {}) }, nonce);
      toast(done.deduped ? `Déjà ajouté au voyage « ${title || "sans titre"} ».` : `Ajouté au voyage « ${title || "sans titre"} », jour ${day}.`, { ico: "plus" });
    };
    if (trip === this.tripId()) return this.gesture(trip, write);
    try {
      await write();
      this.invalidateTrip(trip);
      return { ok: true, error: null };
    } catch (err) {
      toastFailure(err);
      return { ok: false, error: err };
    }
  }

  // ── Itinéraire ─────────────────────────────────────────────────────

  /**
   * Ce que Mika a calculé, posé tel qu'elle l'a gardé : ses points, son mode, ce qu'elle évitait (quand le regard le
   * dit), son tracé et son résumé. Rien ne se recalcule avant ton premier changement (ou « Recalculer »).
   */
  private applyRouteRegard(seq: string): void {
    const regard = this.regards.get(seq).value;
    if (!regard) return;
    this.itiFrom = seq;
    const pts = regard.places.filter((p) => typeof p.lat === "number" && typeof p.lon === "number");
    if (pts.length >= 2) {
      this.points = pts.slice(0, CARTE_LIMITS.points).map((p) => ({ query: p.name ?? "", name: p.name ?? "", lat: p.lat as number, lon: p.lon as number }));
    }
    const route = regard.route;
    if (route?.mode && (MODES as readonly string[]).includes(route.mode)) this.mode = route.mode;
    // un regard d'avant ne dit pas ce qu'il évitait : tes cases restent
    const avoided = route?.avoid;
    if (Array.isArray(avoided)) this.avoid = AVOIDS.filter((a) => avoided.includes(a));
    this.itiRegard = { title: regard.title, distance_m: route?.distance_m ?? null, duration_s: route?.duration_s ?? null,
      line: safeDecode(route?.shape), key: itiKey(this.points, this.mode, this.avoid) };
    this.route = null;
    this.routeFor = "";
    this.routeError = "";
    this.routing = false;
    this.routeSeq += 1;
    this.fitNext = true;
  }

  /** Ce que montre l'itinéraire est-il celui de ses points (un point retapé, un trajet qui se recalcule : non) ? */
  private itiStale(): boolean {
    const shownKey = this.route ? this.routeFor : this.itiRegard?.key ?? null;
    return typedPoint(this.points) || (shownKey !== null && shownKey !== itiKey(this.points, this.mode, this.avoid));
  }

  private suggestionList(): Suggestion[] {
    return [...this.sugg.mine, ...this.sugg.addresses, ...this.sugg.places];
  }

  private itineraryHtml(): string {
    const n = this.points.length;
    const stale = this.itiStale();
    const pins: ScenePin[] = this.points.flatMap((p, i) =>
      typeof p.lat === "number" && typeof p.lon === "number"
        ? [{ id: `pt${i}`, lat: p.lat, lon: p.lon, label: pointLetter(i, n), title: p.name || p.query, mika: !!this.itiRegard && !this.route }]
        : []);
    // un tracé qui n'est plus celui de ces points ne se montre pas
    const lines = stale ? []
      : this.route ? this.route.legs.map((l) => ({ points: safeDecode(l.shape) })).filter((l) => l.points.length >= 2)
      : this.itiRegard && this.itiRegard.line.length >= 2 ? [{ points: this.itiRegard.line, mika: true }] : [];
    const chosen = chosenPoints(this.points);
    const title = chosen.length >= 2 ? `Itinéraire de ${chosen[0].name} à ${chosen[chosen.length - 1].name}` : "Itinéraire";
    const map = this.pane({ pins, lines }, title);
    return itineraryMarkup({
      points: this.points,
      mode: this.mode,
      avoid: this.avoid,
      route: this.route,
      stale,
      error: this.routeError,
      loading: this.routing,
      suggestFor: this.suggestFor,
      suggestions: this.suggestionList(),
      suggestNote: this.sugg.note,
      regard: this.itiRegard && !this.route ? { title: this.itiRegard.title, distance_m: this.itiRegard.distance_m, duration_s: this.itiRegard.duration_s } : null,
      now: Date.now(),
      map,
    });
  }

  /** Tu changes l'itinéraire (un mode, une case, un point) : ce que Mika avait calculé cède la place, il se recalcule. */
  private changed(): void {
    if (this.itiRegard && this.itiRegard.key === itiKey(this.points, this.mode, this.avoid) && !typedPoint(this.points)) {
      this.paint(); // rien de ce qui fait le trajet n'a changé (une étape vide retirée)
      return;
    }
    this.itiRegard = null;
    void this.computeRoute();
  }

  /** Le trajet de ces points : demandé seulement s'ils sont tous choisis et qu'il n'est pas déjà celui-là (`force` : si). */
  private async computeRoute(force = false): Promise<void> {
    const chosen = chosenPoints(this.points);
    const key = itiKey(this.points, this.mode, this.avoid);
    const seq = ++this.routeSeq;
    const paint = () => {
      if (this.open() && this.current === "itineraire") this.paint();
    };
    if (chosen.length < 2 || typedPoint(this.points) || (!force && this.route && this.routeFor === key)) {
      // un point retapé, pas encore choisi : rien ne part (le trajet d'avant se montre, passé)
      if (chosen.length < 2) {
        this.route = null;
        this.routeFor = "";
      }
      this.routeError = "";
      this.routing = false;
      paint();
      return;
    }
    this.routing = true;
    paint();
    try {
      const route = await fetchRoute(chosen, this.mode, this.mode === "voiture" ? this.avoid : []);
      if (seq !== this.routeSeq) return;
      this.route = route;
      this.routeFor = key;
      this.routeError = "";
      this.itiRegard = null;
      this.fitNext = true;
    } catch (err) {
      if (seq !== this.routeSeq) return;
      this.route = null;
      this.routeFor = "";
      this.routeError = failureText(err);
    } finally {
      if (seq === this.routeSeq) this.routing = false;
    }
    paint();
  }

  /**
   * Les propositions d'un point : sa position, les lieux de l'index (rien ne sort) ; une adresse, si le texte en a l'air,
   * gardée par texte et demandée après une pause de la saisie. Un refus des adresses (429…) se dit sous la liste.
   */
  private async suggest(i: number, text: string): Promise<void> {
    const q = text.trim();
    const seq = ++this.suggestSeq;
    window.clearTimeout(this.pointAddrTimer);
    const here = this.here();
    const mine: Suggestion[] = here && (!q || "ma position".startsWith(q.toLowerCase()))
      ? [{ label: "Ma position", sub: here.label || "ta dernière position", mine: true, point: this.herePoint(here) }] : [];
    const info = this.carte.value;
    const places = q.length >= 2 && info?.places.ready ? await searchPlaces({ q, near: here, limit: 6 }).catch(() => [] as Place[]) : [];
    if (seq !== this.suggestSeq || !this.open() || this.current !== "itineraire") return;
    const wanted = !!info?.addresses.ready && wantsAddress(q);
    const known = wanted ? this.addressBook.peek(q) : null;
    this.sugg = { mine, addresses: (known ?? []).slice(0, ADDRESSES_SUGGESTED).map(suggestionOf), places: places.map(suggestionOf), note: "" };
    if (wanted && !known) {
      this.pointAddrTimer = window.setTimeout(() => void this.suggestAddresses(i, q, seq), Math.max(0, this.typedAt + ADDRESS_WAIT_MS - Date.now()));
    }
    this.showSuggestions(i);
  }

  private async suggestAddresses(i: number, q: string, seq: number): Promise<void> {
    let found: Place[] = [];
    let note = "";
    try {
      found = await this.addressBook.lookup(q);
    } catch (err) {
      note = failureText(err);
    }
    if (seq !== this.suggestSeq || !this.open() || this.current !== "itineraire") return;
    this.sugg = { ...this.sugg, addresses: found.slice(0, ADDRESSES_SUGGESTED).map(suggestionOf), note };
    this.showSuggestions(i);
  }

  private showSuggestions(i: number): void {
    this.suggestFor = this.suggestionList().length || this.sugg.note ? i : null;
    this.paint();
  }

  private closeSuggestions(): void {
    window.clearTimeout(this.pointAddrTimer);
    this.suggestSeq += 1;
    this.suggestFor = null;
    this.sugg = NO_SUGGESTIONS;
  }

  private pick(i: number, j: number): void {
    const s = this.suggestionList()[j];
    if (!s || !this.points[i]) return;
    this.points[i] = { ...s.point };
    this.closeSuggestions();
    this.fitNext = true;
    this.changed();
    this.paint();
    // la suite : le point suivant encore vide
    const next = this.points.findIndex((p) => typeof p.lat !== "number");
    if (next >= 0) $<HTMLInputElement>(`[data-pt="${next}"]`, this.body ?? document)?.focus();
  }

  /** Ce qu'on dit à Mika du trajet montré : le calculé, sinon le sien ; passé, rien que ses points. */
  private routeFacts(): { distance_m: number; duration_s: number } | null {
    if (this.itiStale()) return null;
    if (this.route) return this.route;
    const r = this.itiRegard;
    return r && typeof r.distance_m === "number" && typeof r.duration_s === "number" ? { distance_m: r.distance_m, duration_s: r.duration_s } : null;
  }

  /**
   * « En faire un voyage » : le voyage, puis ses arrêts au jour 1. Une clé par intention (ces points, ce mode) : redit
   * après une panne à mi-chemin, le serveur rend le même voyage et n'ajoute pas deux fois un arrêt déjà là.
   */
  private async routeToTrip(): Promise<void> {
    const chosen = chosenPoints(this.points);
    if (chosen.length < 2 || this.sendingTrip || this.itiStale()) return;
    this.sendingTrip = true;
    const key = itiKey(this.points, this.mode, this.avoid);
    if (this.tripIntent?.key !== key) this.tripIntent = { key, nonce: newNonce() };
    const nonce = this.tripIntent.nonce;
    const title = `${chosen[0].name} → ${chosen[chosen.length - 1].name}`.slice(0, CARTE_LIMITS.title);
    try {
      const made = await createTrip({ title, mode: this.mode, avoid: this.mode === "voiture" ? this.avoid : [] }, nonce);
      for (const [i, p] of chosen.entries()) {
        await addStop(made.id, { name: p.name.slice(0, CARTE_LIMITS.name) || "Point", lat: p.lat, lon: p.lon, day: 1, index: -1 }, `${nonce}-${i + 1}`);
      }
      this.tripIntent = null;
      this.trips.invalidate();
      toast("Voyage créé : ses arrêts, au jour 1.", { ico: "plus" });
      this.shell.go(`#carte/voyages/${encodeURIComponent(made.id)}`);
    } catch (err) {
      if (refused(err)) this.tripIntent = null;
      toastFailure(err);
    } finally {
      this.sendingTrip = false;
    }
  }

  private routeGpxDownload(): void {
    const chosen = chosenPoints(this.points);
    if (chosen.length < 2 || this.itiStale()) return;
    const title = `${chosen[0].name} → ${chosen[chosen.length - 1].name}`;
    // le tracé calculé, sinon celui que Mika a gardé (résumé)
    const track = this.route
      ? this.route.legs.flatMap((l, i) => {
        const pts = safeDecode(l.shape);
        return i ? pts.slice(1) : pts;
      })
      : this.itiRegard?.line ?? [];
    download(fileName(title, "gpx"), routeGpx(title, chosen, track), "application/gpx+xml");
    toast("Le fichier GPX se télécharge : le tracé et les arrêts.", { ico: "download" });
  }

  // ── Voyages ────────────────────────────────────────────────────────

  private tripsHtml(): string {
    const trips = this.trips;
    if (!trips.value) {
      return trips.error ? `<div class="fill-scroll">${errorBlock(trips.error, "Impossible de lire tes voyages")}</div>` : loadingBlock();
    }
    // sa miniature se relit si la liste dit le voyage changé depuis (par elle dans le chat, ailleurs)
    return tripsMarkup(trips.value, (t) => this.minis.dataOf({ kind: "trip", ref: t.id }, t.updated), Date.now());
  }

  private shownTrip(): Trip | null {
    const id = this.tripId();
    if (!id) return null;
    if (this.optimistic && this.optimistic.id === id) return this.optimistic;
    return this.tripCache.get(id).value;
  }

  private tripHtml(): string {
    const id = this.tripId();
    const cached = this.tripCache.get(id);
    const trip = this.shownTrip();
    if (!trip) {
      this.scene = EMPTY_SCENE;
      return cached.error
        ? `<div class="fill-scroll">${gone(cached.error)
          ? `<div class="empty">${ico("map")}<b>Ce voyage n'existe pas</b><p>Il a été supprimé, ou il n'est pas à toi.</p><a class="btn sm" href="#carte/voyages">${ico("chev-left", "sm")}Tes voyages</a></div>`
          : errorBlock(cached.error, "Impossible de lire ce voyage")}</div>`
        : loadingBlock();
    }
    // le trajet de ces arrêts-ci, jamais celui d'avant un geste : en attendant, les arrêts reliés à vol d'oiseau
    const shown = this.routes.shown(trip);
    const route = shown.route;
    const pins = tripPins(trip);
    const routed = tripLines(route);
    const straight = straightLine(pins.map((p): LatLon => [p.lat, p.lon]));
    const lines = routed.length ? routed.map((points) => ({ points })) : straight ? [straight] : [];
    const map = this.pane({ pins, lines }, trip.title || "Le voyage");
    return tripEditorMarkup({
      trip,
      route,
      routePending: shown.pending,
      routeError: shown.error && !gone(shown.error) ? failureText(shown.error) : "",
      onRoute: this.along.trip === id ? this.along : emptyAlong(id),
      info: this.carte.value,
      now: Date.now(),
      map,
    });
  }

  private invalidateTrip(id: string): void {
    this.tripCache.invalidate(id);
    this.trips.invalidate();
    this.minis.invalidate({ kind: "trip", ref: id });
  }

  /**
   * Un geste sur le voyage ouvert : écrit après ceux d'avant (`GestureQueue`), puis — quand plus rien n'attend — le
   * voyage relu, et son trajet un moment après. Un refus se dit (un toast, sauf `quiet`) ; rend ce qui s'est passé.
   */
  private async gesture(id: string, write: () => Promise<unknown>, quiet = false): Promise<{ ok: boolean; error: unknown }> {
    let ok = false;
    let error: unknown = null;
    try {
      ok = await this.gestures.run(async () => {
        await write();
      });
    } catch (err) {
      error = err;
      if (!quiet) toastFailure(err);
    }
    if (!this.gestures.busy) void this.reloadTrip(id);
    return { ok, error };
  }

  /** Après les gestes : le voyage relu (c'est local), redessiné ; son trajet, `ROUTE_WAIT_MS` après le dernier. */
  private async reloadTrip(id: string): Promise<void> {
    this.invalidateTrip(id);
    await this.tripCache.get(id).load(true);
    if (this.gestures.busy) return; // un autre geste est parti : il relira après lui
    this.optimistic = null;
    const trip = this.tripCache.get(id).value;
    if (trip) this.routes.want(trip);
    // revenu à des arrêts dont on a déjà le trajet (monté puis redescendu) : rien ne se relit, « Sur la route » suit
    if (trip && !this.routes.shown(trip).pending) this.routeLanded(id);
    else if (this.open()) this.paint();
  }

  /** Un trajet (ou son refus) vient d'arriver : « Sur la route » suit s'il avait été cherché pour d'autres arrêts. */
  private routeLanded(id: string): void {
    const trip = this.tripCache.get(id).value;
    if (trip && this.along.trip === id) {
      const next = alongAfterRoute(this.along, tripRouteKey(trip));
      if (next === "adopt") this.along = { ...this.along, key: tripRouteKey(trip), adopt: false };
      if (next === "reload") void this.loadAlong(id, this.along.cat);
    }
    if (this.open() && this.current === "voyage" && this.tripId() === id) this.paint();
  }

  private async loadAlong(id: string, cat: string): Promise<void> {
    const seq = ++this.alongSeq;
    const trip = this.tripCache.get(id).value;
    const key = trip ? tripRouteKey(trip) : "";
    this.along = { ...emptyAlong(id), cat, loading: true, key };
    this.paint();
    try {
      const got = await fetchOnRoute(id, { cat, day: 0, corridor: CORRIDOR_M, limit: 12 });
      if (seq !== this.alongSeq) return;
      // une clé par lieu, faite avec la liste : « Ajouter » cliqué deux fois ne l'ajoute qu'une fois
      this.along = { ...emptyAlong(id), cat, places: got.places, routed: got.route, key, keys: got.places.map(() => newNonce()) };
    } catch (err) {
      if (seq !== this.alongSeq) return;
      this.along = { ...emptyAlong(id), cat, error: failureText(err), key };
    }
    if (this.open() && this.current === "voyage") this.paint();
  }

  private moveTo(stop: string, day: number, index: number): void {
    const id = this.tripId();
    const trip = this.shownTrip();
    // lâché où il était (un tremblement de la poignée) : rien ne part
    if (!id || !trip || noopMove(trip, stop, day, index)) {
      if (this.paintLater) this.paint();
      return;
    }
    this.optimistic = movedTrip(trip, stop, day, index);
    this.paint();
    const nonce = newNonce();
    void this.gesture(id, () => moveStop(id, stop, day, index, nonce));
  }

  private remove(stop: string): void {
    const id = this.tripId();
    const trip = this.shownTrip();
    const s = trip?.days.flatMap((d) => d.stops).find((x) => x.id === stop);
    if (!id || !trip || !s) return;
    // retiré de suite à l'écran : un second clic ne trouve plus son bouton
    this.optimistic = removedTrip(trip, stop);
    this.paint();
    const nonce = newNonce();
    void this.gesture(id, async () => {
      await removeStop(id, stop, nonce);
      toast(s.by === "mika" ? "Arrêt retiré. Mika le saura en relisant le voyage." : "Arrêt retiré.", { ico: "x" });
    });
  }

  private async optimize(): Promise<void> {
    const id = this.tripId();
    const trip = this.shownTrip();
    if (!id || !trip || this.optimizing) return;
    const days = trip.days.filter((d) => d.stops.length >= 3);
    if (!days.length) {
      toast("Rien à réordonner : il faut trois arrêts dans un même jour.", { ico: "info" });
      return;
    }
    this.optimizing = true;
    let moved = 0;
    const { ok } = await this.gesture(id, async () => {
      for (const d of days) {
        const got = await optimizeDay(id, d.n, newNonce());
        if ((got.order ?? []).join(",") !== d.stops.map((s) => s.id).join(",")) moved += 1;
      }
    });
    this.optimizing = false;
    if (ok) toast(moved ? "Les arrêts de chaque jour remis dans le meilleur ordre ; départ et nuit ne bougent pas." : "Déjà dans le meilleur ordre.", { ico: "refresh" });
  }

  private addAlong(i: number): void {
    const id = this.tripId();
    const trip = this.shownTrip();
    const p = this.along.places[i];
    const nonce = this.along.keys[i];
    if (!id || !trip || !p || !nonce || this.along.sending === i) return;
    const [day, index] = alongPlace(trip, this.routes.shown(trip).route, p.along_m);
    const along = this.along;
    this.along = { ...along, sending: i };
    this.paint();
    void this.addPlace(id, trip.title, p, day, index, nonce).then(({ ok }) => {
      if (this.along.trip === id && this.along.keys === along.keys && this.along.sending === i) {
        this.along = { ...this.along, sending: null, adopt: this.along.adopt || ok };
        if (this.open()) this.paint();
      }
    });
  }

  // ── Les fenêtres ───────────────────────────────────────────────────

  /** Un voyage neuf : un titre, une date, un mode ; `first` : son premier arrêt (« Ajouter au voyage »). */
  private newTripModal(opts: { first?: Place } = {}): void {
    const el = openModal({
      title: "Nouveau voyage",
      size: "narrow",
      body: `<form class="stack" data-trip-form>
        <label class="field"><span>Titre</span><input name="title" maxlength="${CARTE_LIMITS.title}" required placeholder="Les Alpes en cinq jours" value="${h(opts.first ? `Autour de ${opts.first.town || opts.first.name}` : "")}"></label>
        <label class="field"><span>Départ <span class="muted">(facultatif)</span></span><input name="start" type="date"></label>
        <label class="field"><span>Comment</span><select name="mode">${["voiture", "velo", "pied"].map((m) => `<option value="${m}">${h(modeWords(m))}</option>`).join("")}</select></label>
        ${opts.first ? `<p class="small muted">Premier arrêt : ${h(opts.first.name)}${opts.first.town ? `, ${h(opts.first.town)}` : ""}.</p>` : ""}
        <p class="small cf-error" data-erreur hidden></p></form>`,
      foot: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button>
        <button class="btn primary" type="button" data-ok>${ico("plus", "sm")}Créer</button>`,
    });
    const form = el.querySelector<HTMLFormElement>("[data-trip-form]")!;
    const error = el.querySelector<HTMLElement>("[data-erreur]")!;
    const ok = el.querySelector<HTMLButtonElement>("[data-ok]")!;
    // les clés de cette fenêtre : « Créer » redit après une panne rend le même voyage, et son premier arrêt une fois
    let nonce = newNonce();
    let firstNonce = newNonce();
    const submit = async () => {
      if (ok.disabled) return;
      const data = new FormData(form);
      const title = String(data.get("title") ?? "").trim();
      if (!title) {
        error.innerHTML = `${ico("alert", "xs")}<span>Un voyage a un titre.</span>`;
        error.hidden = false;
        return;
      }
      ok.disabled = true;
      try {
        const made = await createTrip({ title, start: String(data.get("start") ?? ""), mode: String(data.get("mode") ?? "voiture") }, nonce);
        if (opts.first) {
          await addStop(made.id, { name: opts.first.name.slice(0, CARTE_LIMITS.name) || "Lieu", lat: opts.first.lat, lon: opts.first.lon,
            kind: (opts.first.kind_fr || "").slice(0, CARTE_LIMITS.kind), day: 1, index: -1 }, firstNonce);
        }
        closeModal();
        this.trips.invalidate();
        toast("Voyage créé.", { ico: "plus" });
        this.shell.go(`#carte/voyages/${encodeURIComponent(made.id)}`);
      } catch (err) {
        // refusé (un titre, la borne des voyages) : la prochaine fois est une autre demande
        if (refused(err)) {
          nonce = newNonce();
          firstNonce = newNonce();
        }
        ok.disabled = false;
        error.innerHTML = `${ico("alert", "xs")}<span>${h(failureText(err))}</span>`;
        error.hidden = false;
      }
    };
    ok.addEventListener("click", () => void submit());
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      void submit();
    });
  }

  private editTripModal(trip: Trip): void {
    const el = openModal({
      title: "Le voyage",
      size: "narrow",
      body: `<form class="stack" data-trip-form>
        <label class="field"><span>Titre</span><input name="title" maxlength="${CARTE_LIMITS.title}" value="${h(trip.title)}"></label>
        <label class="field"><span>Départ <span class="muted">(vide : sans date)</span></span><input name="start" type="date" value="${h(trip.start)}"></label>
        <label class="field"><span>Comment</span><select name="mode">${["voiture", "velo", "pied"].map((m) => `<option value="${m}"${trip.mode === m ? " selected" : ""}>${h(modeWords(m))}</option>`).join("")}</select></label>
        <div class="field"><span>En voiture, éviter</span>
          ${[["peages", "les péages"], ["autoroutes", "les autoroutes"], ["ferries", "les ferries"]].map(([id, label]) =>
            `<label class="check"><input type="checkbox" name="avoid" value="${id}"${trip.avoid.includes(id) ? " checked" : ""}><span>${label}</span></label>`).join("")}</div>
        <p class="small cf-error" data-erreur hidden></p></form>`,
      foot: `<button class="btn danger" type="button" data-delete>${ico("trash", "sm")}Supprimer le voyage</button><span class="grow"></span>
        <button class="btn" type="button" data-close>Annuler</button><button class="btn primary" type="button" data-ok>${ico("check", "sm")}Enregistrer</button>`,
    });
    const form = el.querySelector<HTMLFormElement>("[data-trip-form]")!;
    const error = el.querySelector<HTMLElement>("[data-erreur]")!;
    const okButton = el.querySelector<HTMLButtonElement>("[data-ok]")!;
    const say = (text: string) => {
      error.innerHTML = `${ico("alert", "xs")}<span>${h(text)}</span>`;
      error.hidden = false;
    };
    let nonce = newNonce();
    okButton.addEventListener("click", async () => {
      if (okButton.disabled) return;
      const data = new FormData(form);
      const values: { title?: string; start?: string; mode?: string; avoid?: string[] } = {};
      const title = String(data.get("title") ?? "").trim();
      if (!title) return say("Un voyage a un titre.");
      if (title !== trip.title) values.title = title;
      const start = String(data.get("start") ?? "");
      if (start !== trip.start) values.start = start;
      const mode = String(data.get("mode") ?? trip.mode);
      if (mode !== trip.mode) values.mode = mode;
      const avoid = data.getAll("avoid").map(String);
      if (avoid.join(",") !== trip.avoid.join(",")) values.avoid = avoid;
      if (!Object.keys(values).length) {
        closeModal();
        return;
      }
      okButton.disabled = true;
      // après les autres gestes ; son trajet se relit s'il a changé de mode ou de ce qu'il évite
      const { ok, error: err } = await this.gesture(trip.id, () => changeTrip(trip.id, values, nonce), true);
      okButton.disabled = false;
      if (ok) {
        closeModal();
        toast("Voyage modifié.", { ico: "check" });
        return;
      }
      if (refused(err)) nonce = newNonce();
      if (err) say(failureText(err));
    });
    el.querySelector("[data-delete]")?.addEventListener("click", async () => {
      closeModal();
      const yes = await confirmModal({ title: "Supprimer ce voyage ?", text: `« ${trip.title} » et tous ses arrêts disparaissent. Mika ne s'en souviendra plus comme d'un voyage à faire.`, ok: "Supprimer", danger: true });
      if (!yes) return;
      try {
        await removeTrip(trip.id, newNonce());
        this.invalidateTrip(trip.id);
        toast("Voyage supprimé.", { ico: "trash" });
        this.shell.go("#carte/voyages");
      } catch (err) {
        toastFailure(err);
      }
    });
  }

  /** Ajouter un arrêt à un jour : un lieu de l'index, une adresse, ta position. */
  private addStopModal(day: number): void {
    const id = this.tripId();
    const trip = this.shownTrip();
    if (!id || !trip) return;
    const el = openModal({
      title: `Ajouter un arrêt · jour ${day}`,
      body: `<div class="stack add-stop-modal">
        <label class="search-field">${ico("search", "sm")}<input type="search" data-stop-q maxlength="200" placeholder="Un lieu, une adresse…" aria-label="Chercher un lieu ou une adresse" autocomplete="off"></label>
        <div class="add-stop-list" data-stop-list></div>
        <label class="field"><span>Une note <span class="muted">(facultatif)</span></span><input data-stop-note maxlength="${CARTE_LIMITS.note}" placeholder="Réserver avant le 15, arriver avant 17 h…"></label></div>`,
      foot: `<span class="grow"></span><button class="btn" type="button" data-close>Fermer</button>`,
    });
    const input = el.querySelector<HTMLInputElement>("[data-stop-q]")!;
    const list = el.querySelector<HTMLElement>("[data-stop-list]")!;
    const noteInput = el.querySelector<HTMLInputElement>("[data-stop-note]")!;
    let found: Place[] = [];
    let message = "";
    let seq = 0;
    let timer = 0;
    let addrTimer = 0;
    let typedAt = 0;
    /** Un lieu qui s'ajoute (les autres attendent) ; la clé de chaque lieu choisi, gardée le temps de la fenêtre. */
    let sending = false;
    const keys = new Map<string, string>();
    const here = this.here();
    // chercher près de ce jour du voyage (son dernier arrêt, sinon celui d'avant) ; un voyage vide : près de toi
    const near = (() => {
      const before = trip.days.filter((d) => d.n <= day).flatMap((d) => d.stops)
        .filter((s) => typeof s.lat === "number" && typeof s.lon === "number");
      const last = before[before.length - 1] ?? tripPins(trip)[0];
      return last ? { lat: last.lat as number, lon: last.lon as number } : here;
    })();
    const paintList = () => {
      const off = sending ? " disabled" : "";
      const mine = here && !input.value.trim()
        ? `<button class="li place" type="button" data-stop-here${off}>${ico("pin", "sm")}<span class="li-main"><span class="li-title">Ma position</span><span class="li-snip">${h(here.label || "ta dernière position")}</span></span></button>` : "";
      list.innerHTML = mine + (message ? `<p class="small muted">${h(message)}</p>` : "") + found
        .map((p, i) => `<button class="li place" type="button" data-stop-pick="${i}"${off}>${ico("search", "sm")}<span class="li-main"><span class="li-title">${h(p.name)}</span><span class="li-snip">${h(placeWhat(p))}</span></span></button>`)
        .join("");
    };
    const run = async () => {
      const q = input.value.trim();
      const mine = ++seq;
      window.clearTimeout(addrTimer);
      if (q.length < 2) {
        found = [];
        message = "";
        paintList();
        return;
      }
      let placesError = "";
      const places = await searchPlaces({ q, near, limit: 8 }).catch((err: unknown) => {
        placesError = failureText(err);
        return [] as Place[];
      });
      if (mine !== seq) return;
      // une adresse, si le texte en a l'air : gardée par texte, demandée une fois la saisie arrêtée
      const wanted = !!this.carte.value?.addresses.ready && wantsAddress(q);
      const known = wanted ? this.addressBook.peek(q) : null;
      found = [...(known ?? []).slice(0, ADDRESSES_SUGGESTED), ...places];
      const waiting = wanted && !known;
      message = placesError || (!found.length && !waiting ? "Rien de tel." : "");
      paintList();
      if (!waiting) return;
      addrTimer = window.setTimeout(async () => {
        let addrError = "";
        const got = await this.addressBook.lookup(q).catch((err: unknown) => {
          addrError = `Adresses : ${failureText(err)}`;
          return [] as Place[];
        });
        if (mine !== seq) return;
        found = [...got.slice(0, ADDRESSES_SUGGESTED), ...places];
        message = [placesError, addrError].filter(Boolean).join(" ") || (!found.length ? "Rien de tel." : "");
        paintList();
      }, Math.max(0, typedAt + ADDRESS_WAIT_MS - Date.now()));
    };
    input.addEventListener("input", () => {
      typedAt = Date.now();
      window.clearTimeout(timer);
      window.clearTimeout(addrTimer);
      timer = window.setTimeout(() => void run(), 300);
    });
    const choose = async (p: Place) => {
      if (sending) return;
      // une clé par lieu choisi : un double clic, un réessai après une panne ne l'ajoutent qu'une fois
      const intent = placeIntent(p);
      const nonce = keys.get(intent) ?? newNonce();
      keys.set(intent, nonce);
      sending = true;
      paintList();
      const { ok, error } = await this.addPlace(id, trip.title, p, day, -1, nonce, noteInput.value.trim().slice(0, CARTE_LIMITS.note));
      sending = false;
      if (ok) {
        closeModal();
        return;
      }
      if (refused(error)) keys.delete(intent);
      paintList();
    };
    on(list, "[data-stop-pick]", "click", (_e, b) => {
      const p = found[Number(b.dataset.stopPick)];
      if (p) void choose(p);
    });
    on(list, "[data-stop-here]", "click", () => {
      if (here) void choose({ id: "", name: here.label || "Ma position", kind: "", kind_fr: "Ta position", category: "", lat: here.lat, lon: here.lon, town: "", distance_m: null, along_m: null });
    });
    paintList();
  }

  // ── Glisser un arrêt ───────────────────────────────────────────────

  /** Le jour et l'arrêt avant lequel tomberait l'arrêt glissé, sous le pointeur. */
  private dropTarget(x: number, y: number): { day: number; before: string | null } | null {
    const under = document.elementFromPoint(x, y) as HTMLElement | null;
    const li = under?.closest<HTMLElement>("li.stop");
    if (li && this.body?.contains(li)) {
      const r = li.getBoundingClientRect();
      const day = Number(li.dataset.day);
      if (y < r.top + r.height / 2) return { day, before: li.dataset.stop ?? null };
      const next = li.nextElementSibling?.matches("li.leg") ? li.nextElementSibling.nextElementSibling : li.nextElementSibling;
      return { day, before: (next as HTMLElement | null)?.dataset?.stop ?? null };
    }
    const box = under?.closest<HTMLElement>("[data-day-box]");
    if (box && this.body?.contains(box)) return { day: Number(box.dataset.dayBox), before: null };
    return null;
  }

  private showDrop(target: { day: number; before: string | null } | null): void {
    if (!this.body) return;
    for (const el of $$<HTMLElement>(".drop-before, .drop-end", this.body)) el.classList.remove("drop-before", "drop-end");
    if (!target) return;
    if (target.before) $<HTMLElement>(`li.stop[data-stop="${CSS.escape(target.before)}"]`, this.body)?.classList.add("drop-before");
    else $<HTMLElement>(`[data-day-list="${target.day}"]`, this.body)?.classList.add("drop-end");
  }

  /**
   * Glisser une poignée : suivi sur le document (le geste ne se perd pas si la poignée quitte la page), et l'écran ne
   * se redessine pas tant que l'arrêt n'est pas tombé (`paint` attend).
   */
  private startDrag(e: PointerEvent, grip: HTMLElement): void {
    const stop = grip.dataset.grip ?? "";
    if (!stop || e.button !== 0 || this.drag) return;
    e.preventDefault();
    grip.setPointerCapture(e.pointerId);
    this.drag = { stop, pointer: e.pointerId, target: null };
    grip.closest("li.stop")?.classList.add("dragging");
    const move = (ev: PointerEvent) => {
      if (!this.drag || ev.pointerId !== this.drag.pointer) return;
      this.drag.target = this.dropTarget(ev.clientX, ev.clientY);
      this.showDrop(this.drag.target);
    };
    const end = (ev: PointerEvent) => {
      if (this.drag && ev.pointerId !== this.drag.pointer) return;
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", end);
      document.removeEventListener("pointercancel", end);
      const drag = this.drag;
      this.drag = null;
      this.showDrop(null);
      if (this.body) for (const el of $$<HTMLElement>("li.stop.dragging", this.body)) el.classList.remove("dragging");
      const trip = this.shownTrip();
      if (drag && ev.type === "pointerup" && drag.target && trip && drag.target.before !== drag.stop) {
        this.moveTo(drag.stop, drag.target.day, dropIndex(trip, drag.stop, drag.target.day, drag.target.before));
      } else if (this.paintLater) {
        this.paint();
      }
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", end);
    document.addEventListener("pointercancel", end);
  }

  // ── Les gestes ─────────────────────────────────────────────────────

  private mount(section: HTMLElement): void {
    this.live = document.createElement("p");
    this.live.className = "carte-live";
    this.live.setAttribute("aria-live", "polite");
    section.append(this.live);
    // Explorer
    on(section, "[data-cat]", "click", (_e, b) => {
      this.leaveRegard();
      const cat = b.dataset.cat ?? "";
      this.cat = this.cat === cat ? "" : cat;
      this.sel = null;
      void this.search();
    });
    on(section, "[data-where]", "click", (_e, b) => {
      this.where = b.dataset.where === "moi" ? "moi" : "zone";
      this.leaveRegard();
      this.sel = null;
      void this.search();
    });
    on(section, "[data-lieu]", "click", (_e, b) => {
      const id = b.dataset.lieu ?? null;
      this.sel = this.sel === id ? null : id;
      this.paint();
    });
    on(section, "[data-go-route]", "click", () => {
      const p = this.chosenPlace();
      if (p) this.routeTo(p);
    });
    on(section, "[data-add-trip]", "click", (e, b) => {
      e.stopPropagation();
      const p = this.chosenPlace();
      if (p) void this.addToTrip(b, p);
    });
    on(section, "[data-ask-place]", "click", () => {
      const p = this.chosenPlace();
      if (p) this.hooks.ask(askAboutPlace(p));
    });
    // Itinéraire
    on(section, "[data-mode]", "click", (_e, b) => {
      this.mode = b.dataset.mode ?? "voiture";
      this.changed();
    });
    section.addEventListener("change", (e) => {
      const t = e.target as HTMLInputElement;
      if (!t.matches("[data-avoid]")) return;
      const id = t.dataset.avoid ?? "";
      this.avoid = t.checked ? [...new Set([...this.avoid, id])] : this.avoid.filter((a) => a !== id);
      this.changed();
    });
    on(section, "[data-iti-add]", "click", () => {
      if (this.points.length >= CARTE_LIMITS.points) return;
      this.points.splice(this.points.length - 1, 0, emptyPoint());
      this.paint();
      $<HTMLInputElement>(`[data-pt="${this.points.length - 2}"]`, section)?.focus();
    });
    on(section, "[data-iti-swap]", "click", () => {
      this.points.reverse();
      this.changed();
    });
    on(section, "[data-iti-remove]", "click", (_e, b) => {
      this.points.splice(Number(b.dataset.itiRemove), 1);
      this.changed();
    });
    on(section, "[data-iti-compute]", "click", () => void this.computeRoute(true));
    // une proposition se choisit sans que le champ perde la main (sinon il les replierait avant le clic)
    on(section, ".iti-sugg", "mousedown", (e) => e.preventDefault());
    on(section, "[data-pick]", "click", (_e, b) => {
      const [i, j] = (b.dataset.pick ?? "").split(":").map(Number);
      this.pick(i, j);
    });
    on(section, "[data-iti-trip]", "click", () => void this.routeToTrip());
    on(section, "[data-iti-gpx]", "click", () => this.routeGpxDownload());
    on(section, "[data-iti-ask]", "click", () => {
      const chosen = chosenPoints(this.points);
      this.hooks.ask(askAboutRoute(chosen.map((p) => p.name), this.routeFacts(), this.mode));
    });
    // Voyages
    on(section, "[data-new-trip]", "click", () => this.newTripModal());
    on(section, "[data-edit-trip]", "click", () => {
      const trip = this.shownTrip();
      if (trip) this.editTripModal(trip);
    });
    on(section, "[data-ask-trip]", "click", () => {
      const trip = this.shownTrip();
      if (trip) this.hooks.ask(askAboutTrip(trip));
    });
    on(section, "[data-optimize]", "click", () => void this.optimize());
    on(section, "[data-retirer]", "click", (_e, b) => this.remove(b.dataset.retirer ?? ""));
    on(section, "[data-add-stop]", "click", (_e, b) => this.addStopModal(Number(b.dataset.addStop) || 1));
    on(section, "[data-onroute]", "click", (_e, b) => {
      const id = this.tripId();
      const cat = b.dataset.onroute ?? "";
      if (!id) return;
      if (this.along.trip === id && this.along.cat === cat) {
        this.alongSeq += 1;
        this.along = emptyAlong(id);
        this.paint();
        return;
      }
      void this.loadAlong(id, cat);
    });
    on(section, "[data-add-along]", "click", (_e, b) => this.addAlong(Number(b.dataset.addAlong)));
    section.addEventListener("pointerdown", (e) => {
      const grip = (e.target as Element | null)?.closest?.("[data-grip]") as HTMLElement | null;
      if (grip && section.contains(grip)) this.startDrag(e, grip);
    });
    section.addEventListener("keydown", (e) => {
      const t = e.target as HTMLElement;
      if (t.matches("[data-grip]") && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
        const trip = this.shownTrip();
        const stop = t.dataset.grip ?? "";
        const step = trip ? stepMove(trip, stop, e.key === "ArrowUp" ? -1 : 1) : null;
        if (!step) return;
        e.preventDefault();
        // déplacé de suite à l'écran (la main reste sur sa poignée), dit au lecteur d'écran ; le trajet suit après
        this.moveTo(stop, step[0], step[1]);
        const moved = this.shownTrip();
        if (moved) this.say(movedWords(moved, stop));
        return;
      }
      if (t.matches("[data-pt]") && e.key === "Escape") {
        this.closeSuggestions();
        this.paint();
      }
      if (t.matches("[data-pt]") && e.key === "Enter" && this.suggestFor === Number(t.dataset.pt) && this.suggestionList().length) {
        e.preventDefault();
        this.pick(Number(t.dataset.pt), 0);
      }
    });
    section.addEventListener("input", (e) => {
      const t = e.target as HTMLInputElement;
      if (t.matches("[data-q]")) {
        this.q = t.value;
        this.typedAt = Date.now();
        this.leaveRegard();
        window.clearTimeout(this.typeTimer);
        window.clearTimeout(this.addrTimer);
        this.typeTimer = window.setTimeout(() => {
          this.sel = null;
          void this.search();
        }, TYPE_MS);
        return;
      }
      if (t.matches("[data-pt]")) {
        const i = Number(t.dataset.pt);
        const p = this.points[i];
        if (!p) return;
        // retapé : le point perd ses coordonnées, le trajet montré est passé jusqu'à ce qu'on en choisisse un
        this.points[i] = { query: t.value, name: "", lat: null, lon: null };
        this.typedAt = Date.now();
        window.clearTimeout(this.pointTimer);
        window.clearTimeout(this.pointAddrTimer);
        this.pointTimer = window.setTimeout(() => void this.suggest(i, t.value), 250);
      }
    });
    section.addEventListener("focusin", (e) => {
      const t = e.target as HTMLInputElement;
      if (this.refocusing) return; // la main reposée après un dessin : ses propositions sont déjà là
      if (t.matches("[data-pt]") && !t.value && this.suggestFor !== Number(t.dataset.pt)) void this.suggest(Number(t.dataset.pt), "");
    });
    section.addEventListener("focusout", (e) => {
      const t = e.target as HTMLInputElement;
      const next = (e as FocusEvent).relatedTarget as HTMLElement | null;
      if (!t.matches("[data-pt]") || next?.closest?.(".iti-sugg")) return;
      window.setTimeout(() => {
        if (this.suggestFor === null || $(".iti-sugg", section)?.contains(document.activeElement)) return;
        const focused = document.activeElement as HTMLElement | null;
        if (focused?.matches?.("[data-pt]")) return;
        this.closeSuggestions();
        if (this.current === "itineraire") this.paint();
      }, 150);
    });
    on(section, "[data-retry]", "click", () => void this.ensure(true));
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
    const places = this.places.slice(0, 8).map((p, i): PaletteEntry => ({
      group: "Lieux",
      title: p.name,
      sub: placeWhat(p),
      icon: "pin",
      action: () => {
        this.sel = placeId(p, i);
        this.shell.go("#carte/explorer");
      },
    }));
    return [...trips, ...places];
  }
}

export function carteScreen(shell: Shell, hooks: CarteHooks): ScreenDef {
  return new CarteScreen(shell, hooks).def();
}
