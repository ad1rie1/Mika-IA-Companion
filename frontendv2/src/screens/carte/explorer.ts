/**
 * Carte › Explorer : chercher un lieu ou une adresse (autour de toi, ou dans la zone de la carte), filtrée et rangée
 * (ouvert, terrasse, végétarien…, sa note Google, sa cuisine ; la distance ou la note), le regard de Mika (ce qu'elle a
 * cherché ou montré, en rose), et la fiche d'un lieu (`GET …/lieu/<id>`, ADR 0259 : ses photos, ce qu'en disent Google
 * Maps, OpenStreetMap et l'office de tourisme, les événements tout près, « Actualiser »), « Itinéraire jusqu'ici » et
 * « Ajouter au voyage ». Son état et ses gestes sont à lui ; le cadre (`index.ts`) lui donne les lectures communes et la
 * carte, et porte vers les autres onglets ce qu'il leur demande (`ExplorerHost`).
 *
 * « Autour de moi » cherche par `near=ici` : le serveur prend ta dernière position (celle du téléphone) et précharge les
 * notes de ta case — elles arrivent au prochain affichage. Une fiche s'ouvre par la route (`#carte/explorer/lieu-<id>`).
 */
import { fetchPlace, listPlaces, refreshPlace, type Coverage, type Photo, type Place, type PlaceFiche, type Regard } from "../../api/carte";
import { ApiError } from "../../api/moi";
import { regardLine, regardPins } from "../../map/cards";
import { mapInfo } from "../../map/info";
import { regardItem, regardOf } from "../../map/notes";
import { sceneBounds, type Scene, type ScenePin } from "../../map/scene";
import type { MapView } from "../../map/view";
import { tripSpan } from "../../map/words";
import { $, isMobile, on } from "../../shell/dom";
import { openMenu, toast, type MenuItem } from "../../shell/float";
import { CachedMap, failureText, newNonce } from "../../shared/kit";
import { placeFicheMarkup, type FicheBack } from "./fiche";
import { askAboutPlace, ficheId, lieuItem, lieuOf, searchReach } from "./format";
import type { CarteFrame } from "./index";
import { photoSeen } from "./photos";
import { ADDRESS_WAIT_MS, gone, wantsAddress } from "./requests";
import { shownPhotos } from "./sources";
import {
  explorerMarkup,
  legendMarkup,
  MIN_RATING,
  NO_FILTERS,
  placeId,
  searchTitle,
  selectedPlace,
  type ExplorerFilters,
  type Where,
} from "./view";

/** Combien de lieux une recherche montre. */
const PLACES_SHOWN = 30;
const TYPE_MS = 350;
/** Une fiche lue se garde un moment (60 fiches par minute et par compte : ne pas les relire à chaque clic). */
const FICHE_TTL = 2 * 60_000;
/** Après « Autour de moi », les notes préchargées arrivent : la liste se relit une fois, quelques secondes plus tard. */
const PRELOAD_REREAD_MS = 6000;

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

/** Ce que le menu « Ajouter au voyage » demande (Explorer et Événements le partagent). */
export type TripMenuHost = Pick<ExplorerHost, "trips" | "addPlace" | "newTripModal">;

/**
 * Le menu « Ajouter au voyage » : ses voyages (les dates en court), puis « Nouveau voyage… ». `dayOf` : le jour où le
 * poser (un événement tombe un jour précis) ; sinon, ou hors du voyage (−1), son dernier jour.
 */
export async function addToTripMenu(host: TripMenuHost, anchor: HTMLElement, p: Place, dayOf?: (t: { start: string; days: number }) => number): Promise<void> {
  await host.trips.load();
  const list = (host.trips.value ?? []).slice(0, 8);
  const items: MenuItem[] = [
    { header: "Ajouter au voyage" },
    ...list.map((t): MenuItem => {
      // la clé de cette intention, faite avec le menu : un clic redit ne l'ajoute qu'une fois
      const nonce = newNonce();
      const day = dayOf ? dayOf(t) : -1;
      return {
        // ses dates en court : un menu d'un téléphone n'a pas la place de « du sam. 3 au mer. 7 avril 2027 »
        label: `${t.title || "Sans titre"}${t.start ? ` · ${tripSpan(t.start, t.days, Date.now())}` : ""}${day > 0 ? ` · jour ${day}` : ""}`,
        icon: "map",
        action: () => void host.addPlace(t.id, t.title, p, day > 0 ? day : Math.max(1, t.days), -1, nonce),
      };
    }),
    ...(list.length ? ["sep" as const] : []),
    { label: "Nouveau voyage…", icon: "plus", action: () => host.newTripModal({ first: p }) },
  ];
  openMenu(anchor, items);
}

/** Un lieu tel que la liste l'attend, depuis ce qu'un regard a gardé (un point nommé n'a ni sorte ni distance). */
function asPlace(p: Partial<Place>): Place {
  return {
    id: p.id ?? "", name: p.name ?? "", kind: p.kind ?? "", kind_fr: p.kind_fr ?? "", category: p.category ?? "",
    lat: p.lat ?? NaN, lon: p.lon ?? NaN, town: p.town ?? "", distance_m: p.distance_m ?? null, along_m: p.along_m ?? null,
    ...(p.osm ? { osm: p.osm } : {}),
  };
}

export class ExplorerTab {
  private q = "";
  private cat = "";
  private where: Where | null = null;
  private filters: ExplorerFilters = { ...NO_FILTERS };
  /** Les lieux de la recherche montrée (la palette les propose aussi). */
  places: Place[] = [];
  private addresses: Place[] = [];
  /** Ce que le cache des avis sait de l'endroit cherché (la ligne « Notes Google Maps lues le … »). */
  private coverage: Coverage | null = null;
  /** Le texte dont les adresses montrées viennent : la carte bougée, une catégorie ne les redemandent pas. */
  private addrQ = "";
  private error = "";
  private addrError = "";
  private loading = false;
  private searched = false;
  /** La recherche montrée est partie de ta position (inconnue : de la zone de la carte) : ce que dit sa légende. */
  private searchedNear = false;
  /** Où le serveur a dit que tu étais (`near=ici`). */
  private hereFix: { lat: number; lon: number } | null = null;
  /** Le lieu choisi (la palette en choisit un aussi). */
  sel: string | null = null;
  private regard: string | null = null;
  private hint = "";
  private searchSeq = 0;
  private typeTimer = 0;
  private moveTimer = 0;
  private addrTimer = 0;
  private rereadTimer = 0;
  /** La dernière frappe dans la recherche : une adresse attend `ADDRESS_WAIT_MS` après elle. */
  private typedAt = 0;
  /** Le regard d'Explorer et ce qu'il en montrait au dernier dessin (lu, en échec) : qu'il change, la carte le cadre. */
  private regardFramed = "";

  // ── La fiche d'un lieu ──
  /** Le lieu dont la fiche est ouverte (l'identifiant de la route), sinon `null`. */
  private fiche: string | null = null;
  /** Sa ligne de la liste (ce qu'on montre en attendant la fiche). */
  private ficheHit: Place | null = null;
  /** Elle vient d'un regard de Mika (en rose). */
  private ficheMika = false;
  private readonly fiches = new CachedMap<PlaceFiche>((id) => fetchPlace(id), FICHE_TTL);
  private refreshing = false;
  /** Ce qui n'a pas pu se relire (« Actualiser »), en mots. */
  private refreshNote = "";

  constructor(private readonly host: ExplorerHost) {}

  /** Ce que la route ouvre dans Explorer : la fiche d'un lieu, un regard de Mika, ou rien. */
  applyItem(item: string | null): void {
    const lieu = lieuOf(item);
    if (lieu) {
      this.openFiche(lieu);
      return;
    }
    const back = this.fiche !== null;
    this.fiche = null;
    this.ficheHit = null;
    this.refreshNote = "";
    const seq = regardOf(item);
    if (seq) {
      // de retour de la fiche d'un de ses lieux : le regard reste tel qu'on l'a laissé (son lieu choisi, son cadre)
      if (back && this.regard === seq) return;
      this.regard = seq;
      this.sel = null;
      this.host.fitNext();
    } else {
      this.regard = null;
      if (!back && this.places.length && !this.searched) this.places = [];
    }
  }

  /** Les lectures sont là : « Autour de moi » si son téléphone a donné sa position, sinon la zone de la carte. */
  loaded(): void {
    if (this.where === null && this.host.position.settled) {
      this.where = this.host.here() ? "moi" : "zone";
    }
  }

  /** Une épingle touchée : la fiche de son lieu (une adresse, un point sans fiche : choisi). */
  pinClicked(id: string): void {
    if (this.fiche && id === "fiche") return;
    const p = this.listed().find((x, i) => placeId(x, i) === id);
    if (p && this.openFromList(p, id)) return;
    this.sel = id;
    this.host.paint();
    this.cardInView();
  }

  /** La palette choisit un lieu de la recherche : sa fiche (une adresse : choisie dans la liste). */
  choose(p: Place, i: number): void {
    if (this.openFromList(p, placeId(p, i))) return;
    this.sel = placeId(p, i);
    this.host.shell.go("#carte/explorer");
  }

  /** Les lieux que la liste montre (ceux du regard, ou ceux de la recherche). */
  private listed(): Place[] {
    const shown = this.regardShown();
    return shown ? shown.regard.places.map(asPlace) : this.places;
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
    if (this.host.current() !== "explorer" || this.fiche || this.where !== "zone" || this.regard || (!this.q.trim() && !this.cat)) return;
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

  // ── La fiche ───────────────────────────────────────────────────────

  /** Ouvrir la fiche d'un lieu de la liste (par la route) ; un lieu sans fiche (une adresse) : faux. */
  private openFromList(p: Place, id: string): boolean {
    const fid = ficheId(p);
    if (!fid) return false;
    this.sel = id;
    this.ficheHit = p;
    this.ficheMika = !!this.regardShown();
    this.host.shell.go(`#carte/explorer/${lieuItem(encodeURIComponent(fid))}`);
    return true;
  }

  /** La route ouvre la fiche de ce lieu : elle se lit (gardée un moment), la carte le montre. */
  private openFiche(id: string): void {
    if (this.fiche !== id) {
      this.refreshNote = "";
      this.refreshing = false;
      // ouverte d'ailleurs (la palette, le lieu d'un événement, une adresse collée) : sa ligne n'est pas celle-là
      if (this.ficheHit && ficheId(this.ficheHit) !== id) this.ficheHit = null;
      if (!this.ficheHit) this.ficheMika = false;
    }
    this.fiche = id;
    // un lieu qui n'est pas dans la liste : la carte se cadre sur lui
    if (!this.ficheHit) this.host.fitNext();
    void this.readFiche(false);
  }

  private async readFiche(force: boolean): Promise<void> {
    const id = this.fiche;
    if (!id) return;
    const cached = this.fiches.get(id);
    const before = cached.version;
    if (!cached.settled || force) this.host.paint();
    await cached.load(force);
    if (this.fiche !== id || !this.host.open() || this.host.current() !== "explorer") return;
    if (cached.version !== before || force) this.host.paint();
  }

  /** « Actualiser » : sa fiche relue chez Google et à l'office de tourisme ; ce qui n'a pas pu se relire se dit. */
  private async refresh(): Promise<void> {
    const id = this.fiche;
    if (!id || this.refreshing) return;
    this.refreshing = true;
    this.refreshNote = "";
    this.host.paint();
    let note = "";
    try {
      const got = await refreshPlace(id);
      this.fiches.get(id).put({ place: got.place, osm: got.osm, tourism: got.tourism, reviews: got.reviews, events: got.events });
      toast(got.message || "Fiche relue.", { ico: "refresh" });
    } catch (err) {
      note = failureText(err);
      // ce qui a pu se relire est gardé : la fiche se relit (sauf un refus de trop de demandes, qui n'a rien tenté)
      if (!(err instanceof ApiError && err.status === 429)) await this.fiches.get(id).load(true);
    }
    if (this.fiche !== id) return;
    this.refreshing = false;
    this.refreshNote = note;
    if (this.host.open() && this.host.current() === "explorer") this.host.paint();
  }

  /** Les photos de la fiche ouverte, dans l'ordre de sa bande (la visionneuse les suit). */
  photos(): Photo[] {
    const f = this.fiche ? this.fiches.get(this.fiche).value : null;
    return f ? shownPhotos(f.tourism?.photos, f.reviews?.photos) : [];
  }

  /** Où revenir de la fiche : la liste d'où elle s'est ouverte (le regard de Mika, ou la recherche). */
  private ficheBack(): FicheBack {
    if (this.regard) return { href: `#carte/explorer/${regardItem(this.regard)}`, label: "Ce que Mika a cherché" };
    return { href: "#carte/explorer", label: this.searched && this.places.length ? "Les résultats" : "Explorer" };
  }

  private ficheHtml(): { html: string; scene: Scene; title: string } {
    const id = this.fiche as string;
    const cached = this.fiches.get(id);
    const fiche = gone(cached.error) ? null : cached.value;
    const p = fiche?.place ?? this.ficheHit;
    const here = this.hereFix ?? (this.host.here() ? { lat: this.host.here()!.lat, lon: this.host.here()!.lon } : null);
    const html = placeFicheMarkup({
      place: this.ficheHit && fiche ? { ...fiche.place, distance_m: fiche.place.distance_m ?? this.ficheHit.distance_m } : p,
      fiche,
      loading: !cached.settled,
      error: cached.error,
      gone: gone(cached.error),
      refreshing: this.refreshing,
      refreshNote: this.refreshNote,
      back: this.ficheBack(),
      mika: this.ficheMika,
      here: this.where === "moi" ? here : null,
      seen: photoSeen,
      now: Date.now(),
    });
    // la carte : la liste d'où elle vient, son lieu choisi ; ouverte d'ailleurs, son lieu seul
    const listed = this.listed();
    const at = this.ficheHit ? listed.findIndex((x) => x === this.ficheHit || (ficheId(x) !== null && ficheId(x) === ficheId(this.ficheHit!))) : -1;
    let pins: ScenePin[];
    if (at >= 0) {
      pins = listed.map((x, i) => ({ id: placeId(x, i), lat: x.lat, lon: x.lon, title: x.name, mika: this.ficheMika, selected: i === at }));
    } else {
      pins = p && Number.isFinite(p.lat) && Number.isFinite(p.lon) ? [{ id: "fiche", lat: p.lat, lon: p.lon, title: p.name, selected: true, mika: this.ficheMika }] : [];
    }
    const scene: Scene = { pins, lines: [], here: this.where === "moi" && here ? here : null };
    return { html, scene, title: p?.name || "Ce lieu" };
  }

  // ── Le dessin ──────────────────────────────────────────────────────

  explorerHtml(): string {
    if (this.fiche) {
      const f = this.ficheHtml();
      const map = this.host.pane(f.scene, f.title, legendMarkup("pin", f.title));
      return explorerMarkup({ ...this.viewBase(), fiche: f.html, map });
    }
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
      const here = this.where === "moi" ? this.hereFix ?? this.host.here() : null;
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
      ...this.viewBase(),
      places,
      addresses: seq ? [] : this.addresses,
      error: seq ? "" : this.error,
      regardError: pending?.error ?? null,
      regardGone: !!pending && gone(pending.error),
      addrError: seq ? "" : this.addrError,
      loading: seq ? !!pending && !pending.error : this.loading,
      searched: seq ? !!shown : this.searched,
      coverage: seq ? null : this.coverage,
      regard: shown ? {
        title: shown.regard.title,
        route: shown.regard.what === "trajet" || shown.regard.kind === "map",
        links: [
          ...(shown.regard.what === "trajet" ? [{ href: `#carte/itineraire/${regardItem(shown.seq)}`, label: "Ouvrir dans Itinéraire" }] : []),
          ...(shown.regard.trip ? [{ href: `#carte/voyages/${encodeURIComponent(shown.regard.trip)}`, label: "Ouvrir le voyage" }] : []),
        ],
      } : null,
      map,
    });
  }

  private viewBase() {
    return {
      info: this.host.carte.value,
      q: this.q,
      cat: this.cat,
      where: this.where ?? "zone",
      places: this.places,
      addresses: this.addresses,
      error: this.error,
      addrError: this.addrError,
      loading: this.loading,
      searched: this.searched,
      sel: this.sel,
      regard: null,
      hint: this.hint,
      map: "",
      filters: this.filters,
      coverage: this.coverage,
      seen: photoSeen,
      now: Date.now(),
    };
  }

  // ── La recherche ───────────────────────────────────────────────────

  /**
   * Une recherche : l'index local (le texte, la catégorie, autour de toi ou dans la zone, les filtres), et les
   * adresses — elles ne dépendent pas de la zone : seul un autre texte les redemande (`findAddresses`). `reread` : la
   * relecture qui suit « Autour de moi » (les notes préchargées sont arrivées) — elle ne recadre rien, ne redemande pas
   * d'adresse et ne précharge plus.
   */
  private async search(refit = true, reread = false): Promise<void> {
    const q = this.q.trim();
    const seq = ++this.searchSeq;
    if (!reread) {
      this.hint = "";
      window.clearTimeout(this.rereadTimer);
    }
    if (!q && !this.cat) {
      window.clearTimeout(this.addrTimer);
      this.places = [];
      this.addresses = [];
      this.addrQ = "";
      this.error = "";
      this.addrError = "";
      this.coverage = null;
      this.searched = false;
      this.loading = false;
      this.host.paint();
      return;
    }
    await this.host.position.load();
    let ici = false;
    let bbox: [number, number, number, number] | null = null;
    const where = this.where ?? "zone";
    if (where === "moi") {
      if (this.host.here()) ici = true;
      else this.hint = "Mika ne sait pas où tu es : ton téléphone ne lui a pas donné ta position. Elle cherche dans la zone de la carte.";
    }
    if (!ici) bbox = this.zone();
    if (!q && !ici && !bbox) {
      this.hint = "Choisis où chercher : autour de toi, ou dans la zone de la carte.";
      this.host.paint();
      return;
    }
    if (!reread) {
      this.loading = true;
      this.host.paint();
    }
    const f = this.filters;
    const query = { q, cat: this.cat, bbox, limit: PLACES_SHOWN, open: f.open, features: f.features, cuisine: f.cuisine,
      minRating: f.minRating, sort: f.sort };
    let places: Place[] = [];
    let coverage: Coverage | null = null;
    let error = "";
    let near = ici;
    try {
      const got = await listPlaces({ ...query, near: ici ? "ici" : null });
      places = got.places;
      coverage = got.reviews;
      if (got.here) this.hereFix = { lat: got.here.lat, lon: got.here.lon };
    } catch (err) {
      if (ici && err instanceof ApiError && err.status === 409) {
        // sa position n'est plus connue du serveur (cessé de la partager) : il le dit, et on cherche dans la zone
        this.hint = `${err.message} Elle cherche dans la zone de la carte.`;
        this.hereFix = null;
        near = false;
        const zone = this.zone();
        try {
          const got = zone || q ? await listPlaces({ ...query, bbox: zone }) : null;
          places = got?.places ?? [];
          coverage = got?.reviews ?? null;
        } catch (again) {
          error = failureText(again);
        }
      } else {
        error = failureText(err);
      }
    }
    if (seq !== this.searchSeq) return;
    // la relecture après le préchargement : une panne passagère ne vide pas la liste montrée
    if (reread && error) return;
    this.places = places;
    this.coverage = coverage;
    this.searchedNear = near;
    this.error = error;
    if (!reread && q !== this.addrQ) this.findAddresses(q, places.length > 0);
    this.loading = false;
    this.searched = true;
    if (this.sel && !selectedPlace({ places: this.places, addresses: this.addresses, sel: this.sel })) this.sel = null;
    if (!reread) this.host.fitNext(refit && where === "moi");
    // autour de toi, le serveur a mis en file les notes de ta case : elles arrivent au prochain affichage
    if (!reread && near && coverage && coverage.ready && coverage.loaded < coverage.cells) {
      this.rereadTimer = window.setTimeout(() => void this.search(false, true), PRELOAD_REREAD_MS);
    }
    if (this.host.open() && this.host.current() === "explorer" && !this.fiche) this.host.paint();
  }

  /** La zone de la carte (sans vraie carte, celle de ce qu'elle montre, ou de la carte servie). */
  private zone(): [number, number, number, number] | null {
    const view = this.host.view();
    if (view) return view.frame();
    const b = sceneBounds(this.host.scene()) ?? mapInfo.value?.bounds ?? null;
    return b ? [b[0], b[1], b[2], b[3]] : null;
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
    if (this.host.open() && this.host.current() === "explorer" && !this.fiche) this.host.paint();
  }

  /** Quitter un regard de Mika pour une recherche à soi (l'adresse suit, sans redessiner l'écran). */
  private leaveRegard(): void {
    if (!this.regard) return;
    this.regard = null;
    this.sel = null;
    this.host.dropItem();
  }

  /** Le lieu dont on parle : celui de la fiche ouverte, sinon celui qu'on a choisi dans la liste. */
  private chosenPlace(): Place | null {
    if (this.fiche) {
      const f = this.fiches.get(this.fiche).value;
      return f?.place ?? this.ficheHit;
    }
    const shown = this.regardShown();
    if (shown) {
      const places = shown.regard.places.map(asPlace);
      return places.find((p, i) => placeId(p, i) === this.sel) ?? null;
    }
    return selectedPlace({ places: this.places, addresses: this.addresses, sel: this.sel });
  }

  /** Un filtre de plus ou de moins : la recherche se refait (la fiche choisie s'oublie). */
  private setFilters(next: Partial<ExplorerFilters>): void {
    this.filters = { ...this.filters, ...next };
    this.sel = null;
    void this.search(false);
  }

  // ── Les gestes ─────────────────────────────────────────────────────

  mount(section: HTMLElement): void {
    const here = () => this.host.current() === "explorer";
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
    on(section, "[data-flt]", "click", (_e, b) => {
      if (!here()) return;
      const id = b.dataset.flt ?? "";
      const f = this.filters;
      if (id === "open") this.setFilters({ open: !f.open });
      else if (id === "rating") this.setFilters({ minRating: f.minRating === null ? MIN_RATING : null });
      else if (id.startsWith("f:")) {
        const feature = id.slice(2);
        this.setFilters({ features: f.features.includes(feature) ? f.features.filter((x) => x !== feature) : [...f.features, feature] });
      }
    });
    section.addEventListener("change", (e) => {
      const t = e.target as HTMLSelectElement;
      if (here() && t.matches?.("[data-cuisine]")) this.setFilters({ cuisine: t.value });
    });
    on(section, "[data-sort]", "click", () => {
      if (!here()) return;
      const sorts = this.host.carte.value?.sorts ?? [];
      if (sorts.length < 2) return;
      const i = sorts.findIndex((s) => s.id === this.filters.sort);
      this.setFilters({ sort: sorts[(i + 1) % sorts.length].id });
    });
    on(section, "[data-lieu]", "click", (_e, b) => {
      const id = b.dataset.lieu ?? null;
      const p = id ? this.listed().find((x, i) => placeId(x, i) === id) : null;
      if (p && id && this.openFromList(p, id)) return;
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
      if (p) void addToTripMenu(this.host, b, p);
    });
    on(section, "[data-ask-place]", "click", () => {
      const p = this.chosenPlace();
      if (p) this.host.hooks.ask(askAboutPlace(p));
    });
    on(section, "[data-refresh]", "click", () => {
      if (here()) void this.refresh();
    });
    on(section, "[data-fiche-retry]", "click", () => {
      if (here()) void this.readFiche(true);
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
