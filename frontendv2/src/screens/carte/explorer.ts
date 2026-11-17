/**
 * Carte › Explorer : chercher un lieu ou une adresse (autour de toi, ou dans la zone de la carte), le regard de Mika
 * (ce qu'elle a cherché ou montré, en rose), la fiche du lieu choisi, « Itinéraire jusqu'ici » et « Ajouter au
 * voyage ». Son état et ses gestes sont à lui ; le cadre (`index.ts`) lui donne les lectures communes et la carte, et
 * porte vers les autres onglets ce qu'il leur demande (`ExplorerHost`).
 */
import { searchPlaces, type Place, type Regard } from "../../api/carte";
import { regardLine, regardPins } from "../../map/cards";
import { mapInfo } from "../../map/info";
import { regardItem } from "../../map/notes";
import { sceneBounds, type Scene, type ScenePin } from "../../map/scene";
import type { MapView } from "../../map/view";
import { tripSpan } from "../../map/words";
import { $, isMobile, on } from "../../shell/dom";
import { openMenu, type MenuItem } from "../../shell/float";
import { failureText, newNonce } from "../../shared/kit";
import { askAboutPlace, searchReach } from "./format";
import type { CarteFrame } from "./index";
import { ADDRESS_WAIT_MS, gone, wantsAddress } from "./requests";
import { explorerMarkup, legendMarkup, placeId, searchTitle, selectedPlace, type Where } from "./view";

/** Combien de lieux une recherche montre. */
const PLACES_SHOWN = 30;
const TYPE_MS = 350;

/** Ce qu'Explorer demande au cadre, et par lui aux autres onglets. */
export interface ExplorerHost extends CarteFrame {
  /** La vraie carte, si elle est montée (« Dans cette zone » cherche dans son cadre). */
  view(): MapView | null;
  /** La scène que la carte montre (sans vraie carte, son cadre). */
  scene(): Scene;
  /** Quitter l'objet de la route (un regard) : l'adresse suit, sans redessiner l'écran. */
  dropItem(): void;
  /** « Itinéraire jusqu'ici » (Itinéraire). */
  routeTo(p: Place): void;
  /** Ajouter un lieu à un voyage (Voyages). */
  addPlace(trip: string, title: string, p: Place, day: number, index: number, nonce: string): Promise<{ ok: boolean; error: unknown }>;
  /** La fenêtre « Nouveau voyage ». */
  newTripModal(opts?: { first?: Place }): void;
}

/** Un lieu tel que la liste l'attend, depuis ce qu'un regard a gardé (un point nommé n'a ni sorte ni distance). */
function asPlace(p: Partial<Place>): Place {
  return {
    id: p.id ?? "", name: p.name ?? "", kind: p.kind ?? "", kind_fr: p.kind_fr ?? "", category: p.category ?? "",
    lat: p.lat ?? NaN, lon: p.lon ?? NaN, town: p.town ?? "", distance_m: p.distance_m ?? null, along_m: p.along_m ?? null,
  };
}

export class ExplorerTab {
  private q = "";
  private cat = "";
  private where: Where | null = null;
  /** Les lieux de la recherche montrée (la palette les propose aussi). */
  places: Place[] = [];
  private addresses: Place[] = [];
  /** Le texte dont les adresses montrées viennent : la carte bougée, une catégorie ne les redemandent pas. */
  private addrQ = "";
  private error = "";
  private addrError = "";
  private loading = false;
  private searched = false;
  /** La recherche montrée est partie de ta position (inconnue : de la zone de la carte) : ce que dit sa légende. */
  private searchedNear = false;
  /** Le lieu choisi (la palette en choisit un aussi). */
  sel: string | null = null;
  private regard: string | null = null;
  private hint = "";
  private searchSeq = 0;
  private typeTimer = 0;
  private moveTimer = 0;
  private addrTimer = 0;
  /** La dernière frappe dans la recherche : une adresse attend `ADDRESS_WAIT_MS` après elle. */
  private typedAt = 0;
  /** Le regard d'Explorer et ce qu'il en montrait au dernier dessin (lu, en échec) : qu'il change, la carte le cadre. */
  private regardFramed = "";

  constructor(private readonly host: ExplorerHost) {}

  /** Ce que la route ouvre dans Explorer : un regard de Mika, ou rien. */
  applyItem(seq: string | null): void {
    this.regard = seq;
    if (seq) {
      this.sel = null;
      this.host.fitNext();
    } else if (this.places.length && !this.searched) {
      this.places = [];
    }
  }

  /** Les lectures sont là : « Autour de moi » si son téléphone a donné sa position, sinon la zone de la carte. */
  loaded(): void {
    if (this.where === null && this.host.position.settled) {
      this.where = this.host.here() ? "moi" : "zone";
    }
  }

  /** Une épingle touchée : son lieu, choisi. */
  pinClicked(id: string): void {
    this.sel = id;
    this.host.paint();
    this.cardInView();
  }

  /**
   * Sur un téléphone, la carte et la liste défilent ensemble : la fiche du lieu choisi (collée en bas de l'écran) se
   * ramène en vue, au cas où la liste serait trop courte pour qu'elle y colle.
   */
  private cardInView(): void {
    const body = this.host.body();
    if (!isMobile() || !body) return;
    $<HTMLElement>("[data-place-card]", body)?.scrollIntoView({ block: "nearest" });
  }

  /** La personne a bougé la carte : « Dans cette zone » cherche dans ce qu'elle montre maintenant (ses lieux seulement). */
  mapMoved(): void {
    if (this.host.current() !== "explorer" || this.where !== "zone" || this.regard || (!this.q.trim() && !this.cat)) return;
    window.clearTimeout(this.moveTimer);
    this.moveTimer = window.setTimeout(() => void this.search(false), 500);
  }

  private regardShown(): { regard: Regard; seq: string } | null {
    const seq = this.regard;
    const cached = seq ? this.host.regards.get(seq) : null;
    // oublié depuis (404) : ce qu'on en avait lu ne se montre plus
    const regard = cached && !gone(cached.error) ? cached.value : null;
    return seq && regard ? { regard, seq } : null;
  }

  explorerHtml(): string {
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
      const here = this.where === "moi" ? this.host.here() : null;
      scene = { pins, lines: [], here: here ? { lat: here.lat, lon: here.lon } : null };
      legend = this.searched
        ? legendMarkup("search", searchTitle(this.host.carte.value, this.q, this.cat),
          `${this.places.length} lieu${this.places.length > 1 ? "x" : ""} · ${searchReach(this.searchedNear, this.places)}`)
        : "";
    }
    const pending = seq && !shown ? this.host.regards.get(seq) : null;
    // son regard vient d'être lu, ou vient d'échouer (404 ou une panne) : la carte le cadre une fois — ses lieux, ou le
    // fond de carte plutôt que le cadre d'avant ; tant qu'il se lit, elle attend
    const framed = seq && (shown || pending?.error) ? `${seq}/${shown ? "lu" : "échec"}` : "";
    if (framed && framed !== this.regardFramed) this.host.fitNext();
    this.regardFramed = framed;
    const map = this.host.pane(scene, shown ? shown.regard.title : "Carte des lieux", legend, !!pending?.error);
    return explorerMarkup({
      info: this.host.carte.value,
      q: this.q,
      cat: this.cat,
      where: this.where ?? "zone",
      places,
      addresses: seq ? [] : this.addresses,
      error: seq ? "" : this.error,
      regardError: pending?.error ?? null,
      regardGone: !!pending && gone(pending.error),
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
      this.host.paint();
      return;
    }
    await this.host.position.load();
    let near: { lat: number; lon: number } | null = null;
    let bbox: [number, number, number, number] | null = null;
    const where = this.where ?? "zone";
    if (where === "moi") {
      const here = this.host.here();
      if (here) near = here;
      else this.hint = "Mika ne sait pas où tu es : ton téléphone ne lui a pas donné ta position. Elle cherche dans la zone de la carte.";
    }
    if (!near) {
      const view = this.host.view();
      if (view) bbox = view.frame();
      else {
        const b = sceneBounds(this.host.scene()) ?? mapInfo.value?.bounds ?? null;
        bbox = b ? [b[0], b[1], b[2], b[3]] : null;
      }
    }
    if (!q && !near && !bbox) {
      this.hint = "Choisis où chercher : autour de toi, ou dans la zone de la carte.";
      this.host.paint();
      return;
    }
    this.loading = true;
    this.host.paint();
    let places: Place[] = [];
    let error = "";
    try {
      places = await searchPlaces({ q, cat: this.cat, near, bbox, limit: PLACES_SHOWN });
    } catch (err) {
      error = failureText(err);
    }
    if (seq !== this.searchSeq) return;
    this.places = places;
    this.searchedNear = !!near;
    this.error = error;
    if (q !== this.addrQ) this.findAddresses(q, places.length > 0);
    this.loading = false;
    this.searched = true;
    if (this.sel && !selectedPlace({ places: this.places, addresses: this.addresses, sel: this.sel })) this.sel = null;
    this.host.fitNext(refit && where === "moi");
    if (this.host.open() && this.host.current() === "explorer") this.host.paint();
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
    const ready = !!this.host.carte.value?.addresses.ready;
    if (!wantsAddress(q) || (!/\d/.test(q) && (!ready || hasPlaces))) return;
    const known = this.host.addressBook.peek(q);
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
      addresses = await this.host.addressBook.lookup(q);
    } catch (err) {
      addrError = failureText(err);
    }
    if (this.addrQ !== q || this.q.trim() !== q) return;
    this.addresses = addresses;
    this.addrError = addrError;
    if (this.sel && !selectedPlace({ places: this.places, addresses: this.addresses, sel: this.sel })) this.sel = null;
    if (this.host.open() && this.host.current() === "explorer") this.host.paint();
  }

  /** Quitter un regard de Mika pour une recherche à soi (l'adresse suit, sans redessiner l'écran). */
  private leaveRegard(): void {
    if (!this.regard) return;
    this.regard = null;
    this.sel = null;
    this.host.dropItem();
  }

  private chosenPlace(): Place | null {
    const shown = this.regardShown();
    if (shown) {
      const places = shown.regard.places.map(asPlace);
      return places.find((p, i) => placeId(p, i) === this.sel) ?? null;
    }
    return selectedPlace({ places: this.places, addresses: this.addresses, sel: this.sel });
  }

  private async addToTrip(anchor: HTMLElement, p: Place): Promise<void> {
    await this.host.trips.load();
    const list = (this.host.trips.value ?? []).slice(0, 8);
    const items: MenuItem[] = [
      { header: "Ajouter au voyage" },
      ...list.map((t): MenuItem => {
        // la clé de cette intention, faite avec le menu : un clic redit ne l'ajoute qu'une fois
        const nonce = newNonce();
        return {
          // ses dates en court : un menu d'un téléphone n'a pas la place de « du sam. 3 au mer. 7 avril 2027 »
          label: `${t.title || "Sans titre"}${t.start ? ` · ${tripSpan(t.start, t.days, Date.now())}` : ""}`,
          icon: "map",
          action: () => void this.host.addPlace(t.id, t.title, p, Math.max(1, t.days), -1, nonce),
        };
      }),
      ...(list.length ? ["sep" as const] : []),
      { label: "Nouveau voyage…", icon: "plus", action: () => this.host.newTripModal({ first: p }) },
    ];
    openMenu(anchor, items);
  }

  // ── Les gestes ─────────────────────────────────────────────────────

  mount(section: HTMLElement): void {
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
      this.host.paint();
    });
    on(section, "[data-go-route]", "click", () => {
      const p = this.chosenPlace();
      if (p) this.host.routeTo(p);
    });
    on(section, "[data-add-trip]", "click", (e, b) => {
      e.stopPropagation();
      const p = this.chosenPlace();
      if (p) void this.addToTrip(b, p);
    });
    on(section, "[data-ask-place]", "click", () => {
      const p = this.chosenPlace();
      if (p) this.host.hooks.ask(askAboutPlace(p));
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
      }
    });
  }
}
