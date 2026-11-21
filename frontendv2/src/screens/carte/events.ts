/**
 * Carte › Événements (ADR 0259) : ce qui se passe autour de toi ou dans la zone de la carte — quand (aujourd'hui, ce
 * week-end, cette semaine, des dates), quoi (les thèmes du serveur, gratuit), un texte — groupé par jour, en épingles
 * sur la carte, avec ce que la base sait de la zone (« lue en partie : 3 cases sur 11 ») ; la fiche d'un événement
 * (`#carte/evenements/e:<uuid>`), « Itinéraire », « Ajouter au voyage » (au bon jour), « En parler à Mika » ; ce que Mika
 * a trouvé (`#carte/evenements/regard-<n>`), en rose. Les événements viennent des offices de tourisme (DATAtourisme),
 * gardés sur ce serveur. Son état et ses gestes sont à lui ; le cadre lui donne les lectures communes et la carte.
 */
import { EVENT_REF, fetchEvent, listEvents, type Coverage, type EventFiche, type EventItem, type Photo, type Place } from "../../api/carte";
import { ApiError } from "../../api/moi";
import { mapInfo } from "../../map/info";
import { regardItem, regardOf } from "../../map/notes";
import { sceneBounds, type Scene, type ScenePin } from "../../map/scene";
import type { MapView } from "../../map/view";
import { on } from "../../shell/dom";
import { CachedMap, failureText } from "../../shared/kit";
import { askAboutEvent, eventsLegend, eventsMarkup, eventTripDay, ficheIsHers, themeLabels, whenRange, type WhenKind } from "./agenda";
import { addToTripMenu, type ExplorerHost } from "./explorer";
import { eventFicheMarkup, type FicheBack } from "./fiche";
import type { Origin } from "./format";
import type { CarteFrame } from "./index";
import { photoSeen } from "./photos";
import { gone } from "./requests";
import { shownPhotos } from "./sources";
import type { Where } from "./view";

/** Combien d'événements une recherche montre (le plus que l'API rende). */
const EVENTS_SHOWN = 50;
const TYPE_MS = 400;
const FICHE_TTL = 5 * 60_000;

/** Ce que l'onglet demande au cadre, et par lui aux autres onglets. */
export interface EventsHost extends CarteFrame, Pick<ExplorerHost, "routeTo" | "addPlace" | "newTripModal"> {
  view(): MapView | null;
  scene(): Scene;
  /** Quitter l'objet de la route (ce que Mika a trouvé) : l'adresse suit, sans redessiner l'écran. */
  dropItem(): void;
}

/** Un événement comme lieu (un arrêt de voyage, la fin d'un itinéraire) : son nom, et où. */
function asPlace(e: EventItem): Place {
  return { id: "", name: e.name, kind: "", kind_fr: "Événement", category: "", lat: e.lat ?? NaN, lon: e.lon ?? NaN,
    town: "", distance_m: e.distance_m, along_m: null };
}

/** Un événement tel que la liste l'attend, depuis ce qu'un regard a gardé. */
function asEvent(e: Partial<EventItem>): EventItem {
  return { id: e.id ?? "", name: e.name ?? "", start: e.start ?? "", end: e.end ?? "", when_text: e.when_text ?? "",
    place: e.place ?? "", lat: e.lat ?? null, lon: e.lon ?? null, distance_m: e.distance_m ?? null, themes: e.themes ?? [],
    free: e.free ?? null, price: e.price ?? "", photo: e.photo ?? "" };
}

export class EventsTab {
  private q = "";
  private when: WhenKind = "week";
  private dates = { start: "", end: "" };
  private themes: string[] = [];
  private free = false;
  private where: Where | null = null;
  private events: EventItem[] = [];
  private coverage: Coverage | null = null;
  private hereFix: { lat: number; lon: number } | null = null;
  private error = "";
  private hint = "";
  private loading = false;
  private searched = false;
  private searchedNear = false;
  private sel: string | null = null;
  private regard: string | null = null;
  /** L'événement dont la fiche est ouverte, sinon `null`. */
  private fiche: string | null = null;
  private ficheHit: EventItem | null = null;
  /** La fiche s'est ouverte depuis celle d'un lieu (« Bientôt, tout près ») : son retour y ramène (R2-W06). */
  private from: Origin | null = null;
  private readonly fiches = new CachedMap<EventFiche>((id) => fetchEvent(id), FICHE_TTL);
  private seq = 0;
  private typeTimer = 0;
  private moveTimer = 0;
  /** La première recherche part d'elle-même, une fois qu'on sait où chercher. */
  private started = false;

  constructor(private readonly host: EventsHost) {}

  /**
   * Ce que la route ouvre : la fiche d'un événement, ce que Mika a trouvé, ou la liste. `from` : la fiche de l'autre
   * onglet d'où l'on vient (R2-W06). Un événement qui n'est pas dans le regard montré le quitte : il n'est pas à elle
   * (R2-W05).
   */
  applyItem(item: string | null, from: Origin | null = null): void {
    const id = item && EVENT_REF.test(item) ? item : null;
    if (id) {
      if (this.fiche !== id || from) this.from = from;
      const regard = this.regardEvents();
      if (regard && !ficheIsHers(regard, id)) this.regard = null;
      if (this.fiche !== id) {
        if (this.ficheHit?.id !== id) this.ficheHit = this.listed().find((e) => e.id === id) ?? null;
        if (!this.ficheHit) this.host.fitNext();
      }
      this.fiche = id;
      this.sel = id;
      void this.readFiche(false);
      return;
    }
    const back = this.fiche !== null;
    this.fiche = null;
    this.from = null;
    const seq = regardOf(item);
    if (seq) {
      if (back && this.regard === seq) return;
      this.regard = seq;
      this.sel = null;
      this.host.fitNext();
    } else {
      this.regard = null;
    }
  }

  /** Les lectures sont là : on sait où chercher (« Autour de moi » si son téléphone l'a dit) ; la première recherche part. */
  loaded(): void {
    if (this.where === null && this.host.position.settled) this.where = this.host.here() ? "moi" : "zone";
    if (!this.started && this.where !== null && !this.regard) {
      this.started = true;
      void this.search();
    }
  }

  pinClicked(id: string): void {
    if (id === "fiche") return;
    if (this.listed().some((e) => e.id === id)) this.openEvent(id);
  }

  /** La carte a bougé : « Dans cette zone » cherche dans ce qu'elle montre maintenant. */
  mapMoved(): void {
    if (this.host.current() !== "evenements" || this.fiche || this.regard || this.where !== "zone" || !this.searched) return;
    window.clearTimeout(this.moveTimer);
    this.moveTimer = window.setTimeout(() => void this.search(false), 600);
  }

  /** Les photos de la fiche ouverte (la visionneuse les suit). */
  photos(): Photo[] {
    const f = this.fiche ? this.fiches.get(this.fiche).value : null;
    return f ? shownPhotos(f.photos) : [];
  }

  private regardEvents(): { title: string; events: EventItem[] } | null {
    if (!this.regard) return null;
    const cached = this.host.regards.get(this.regard);
    const r = cached && !gone(cached.error) ? cached.value : null;
    return r ? { title: r.title, events: (r.events ?? []).map(asEvent).filter((e) => EVENT_REF.test(e.id)) } : null;
  }

  private listed(): EventItem[] {
    return this.regardEvents()?.events ?? this.events;
  }

  private openEvent(id: string): void {
    this.ficheHit = this.listed().find((e) => e.id === id) ?? null;
    this.sel = id;
    this.host.shell.go(`#carte/evenements/${encodeURIComponent(id)}`);
  }

  private async readFiche(force: boolean): Promise<void> {
    const id = this.fiche;
    if (!id) return;
    const cached = this.fiches.get(id);
    const before = cached.version;
    if (!cached.settled || force) this.host.paint();
    await cached.load(force);
    if (this.fiche !== id || !this.host.open() || this.host.current() !== "evenements") return;
    if (cached.version !== before || force) this.host.paint();
  }

  private here(): { lat: number; lon: number } | null {
    const h = this.host.here();
    return this.hereFix ?? (h ? { lat: h.lat, lon: h.lon } : null);
  }

  // ── Le dessin ──────────────────────────────────────────────────────

  eventsHtml(): string {
    const info = this.host.carte.value;
    const now = Date.now();
    const regard = this.regardEvents();
    const inRegard = !!this.regard;
    const pendingRegard = this.regard && !regard ? this.host.regards.get(this.regard) : null;
    // ce que Mika a trouvé, tant qu'il se lit : rien de la recherche d'avant
    const events = regard ? regard.events : inRegard ? [] : this.events;
    const here = this.where === "moi" && !regard ? this.here() : null;
    let fiche = "";
    let pins: ScenePin[] = events.flatMap((e): ScenePin[] => (typeof e.lat === "number" && typeof e.lon === "number"
      ? [{ id: e.id, lat: e.lat, lon: e.lon, title: e.name, mika: !!regard, selected: e.id === this.sel }] : []));
    let title = regard ? regard.title || "Ce que Mika a trouvé" : "Événements";
    if (this.fiche) {
      const cached = this.fiches.get(this.fiche);
      const f = gone(cached.error) ? null : cached.value;
      const e = f?.event ?? this.ficheHit;
      fiche = eventFicheMarkup({
        event: this.ficheHit, fiche: f, loading: !cached.settled, error: cached.error, gone: gone(cached.error),
        back: this.ficheBack(), mika: ficheIsHers(regard, this.fiche), themes: themeLabels(info), here, seen: photoSeen,
      });
      // ouverte d'ailleurs (un lieu, la route) : son épingle seule, une fois connue — d'ici là, rien (le cadrage attend)
      if (!this.ficheHit) {
        pins = e && typeof e.lat === "number" && typeof e.lon === "number"
          ? [{ id: "fiche", lat: e.lat, lon: e.lon, title: e.name, selected: true, mika: ficheIsHers(regard, this.fiche) }] : [];
      }
      title = e?.name || "Cet événement";
    }
    const legend = this.fiche ? "" : eventsLegend({ events, where: this.searchedNear ? "moi" : "zone", regard, searched: inRegard ? !!regard : this.searched });
    const map = this.host.pane({ pins, lines: [], here: this.fiche && !pins.length ? null : here }, title, legend, !!pendingRegard?.error);
    return eventsMarkup({
      info, q: this.q, when: this.when, dates: this.dates, themes: this.themes, free: this.free, where: this.where ?? "zone",
      events, coverage: inRegard ? null : this.coverage, error: inRegard ? "" : this.error,
      loading: inRegard ? !!pendingRegard && !pendingRegard.error : this.loading,
      searched: inRegard ? !!regard : this.searched, sel: this.sel, hint: inRegard ? "" : this.hint,
      regard: inRegard ? { title: regard?.title ?? "" } : null,
      regardError: pendingRegard?.error ?? null, regardGone: !!pendingRegard && gone(pendingRegard.error),
      fiche, seen: photoSeen, now, map,
    });
  }

  private ficheBack(): FicheBack {
    if (this.from) return this.from;
    if (this.regard && ficheIsHers(this.regardEvents(), this.fiche)) {
      return { href: `#carte/evenements/${regardItem(this.regard)}`, label: "Ce que Mika a trouvé" };
    }
    return { href: "#carte/evenements", label: "Les événements" };
  }

  // ── La recherche ───────────────────────────────────────────────────

  private zone(): [number, number, number, number] | null {
    const view = this.host.view();
    if (view) return view.frame();
    const b = sceneBounds(this.host.scene()) ?? mapInfo.value?.bounds ?? null;
    return b ? [b[0], b[1], b[2], b[3]] : null;
  }

  private async search(refit = true): Promise<void> {
    const seq = ++this.seq;
    this.hint = "";
    await this.host.position.load();
    const where = this.where ?? "zone";
    const q = this.q.trim();
    let ici = where === "moi" && !!this.host.here();
    if (where === "moi" && !ici) this.hint = "Mika ne sait pas où tu es : ton téléphone ne lui a pas donné ta position. Elle cherche dans la zone de la carte.";
    const bbox = ici ? null : this.zone();
    if (!ici && !bbox && !q) {
      this.hint = "Déplace la carte sur l'endroit à explorer, ou cherche un nom.";
      this.host.paint();
      return;
    }
    const range = whenRange(this.when, Date.now(), this.dates);
    const query = { start: range.start, end: range.end, themes: this.themes, q, free: this.free, limit: EVENTS_SHOWN };
    this.loading = true;
    this.host.paint();
    let events: EventItem[] = [];
    let coverage: Coverage | null = null;
    let error = "";
    try {
      const got = await listEvents({ ...query, near: ici ? "ici" : null, bbox });
      events = got.events;
      coverage = got.coverage;
      if (got.here) this.hereFix = { lat: got.here.lat, lon: got.here.lon };
    } catch (err) {
      if (ici && err instanceof ApiError && err.status === 409) {
        this.hint = `${err.message} Elle cherche dans la zone de la carte.`;
        this.hereFix = null;
        ici = false;
        const zone = this.zone();
        try {
          const got = zone || q ? await listEvents({ ...query, bbox: zone }) : null;
          events = got?.events ?? [];
          coverage = got?.coverage ?? null;
        } catch (again) {
          error = failureText(again);
        }
      } else {
        error = failureText(err);
      }
    }
    if (seq !== this.seq) return;
    this.events = events.filter((e) => EVENT_REF.test(e.id));
    this.coverage = coverage;
    this.error = error;
    this.loading = false;
    this.searched = true;
    this.searchedNear = ici;
    if (this.sel && !this.events.some((e) => e.id === this.sel)) this.sel = null;
    // autour de toi, la carte se cadre sur ce qu'on a trouvé ; « dans cette zone », elle reste où on l'a mise
    this.host.fitNext(refit && ici);
    if (this.host.open() && this.host.current() === "evenements" && !this.fiche) this.host.paint();
  }

  // ── Les gestes ─────────────────────────────────────────────────────

  /** L'événement dont on parle : celui de la fiche ouverte. */
  private chosen(): EventItem | null {
    if (!this.fiche) return null;
    return this.fiches.get(this.fiche).value?.event ?? this.ficheHit;
  }

  /** Quitter ce que Mika a trouvé pour une recherche à soi. */
  private leaveRegard(): void {
    if (!this.regard) return;
    this.regard = null;
    this.host.dropItem();
  }

  mount(section: HTMLElement): void {
    const mine = () => this.host.current() === "evenements";
    on(section, "[data-when]", "click", (_e, b) => {
      if (!mine()) return;
      const when = (b.dataset.when ?? "week") as WhenKind;
      this.when = when;
      if (when === "dates" && !this.dates.start) this.dates = whenRange("week", Date.now());
      void this.search(false);
    });
    on(section, "[data-theme]", "click", (_e, b) => {
      if (!mine()) return;
      const t = b.dataset.theme ?? "";
      this.themes = this.themes.includes(t) ? this.themes.filter((x) => x !== t) : [...this.themes, t];
      void this.search(false);
    });
    on(section, "[data-free]", "click", () => {
      if (!mine()) return;
      this.free = !this.free;
      void this.search(false);
    });
    on(section, "[data-ev-where]", "click", (_e, b) => {
      if (!mine()) return;
      this.where = b.dataset.evWhere === "moi" ? "moi" : "zone";
      this.leaveRegard();
      void this.search();
    });
    on(section, "[data-ev]", "click", (_e, b) => {
      if (mine() && b.dataset.ev) this.openEvent(b.dataset.ev);
    });
    on(section, "[data-ev-route]", "click", () => {
      const e = this.chosen();
      if (e && typeof e.lat === "number" && typeof e.lon === "number") this.host.routeTo(asPlace(e));
    });
    on(section, "[data-ev-trip]", "click", (ev, b) => {
      ev.stopPropagation();
      const e = this.chosen();
      if (e && typeof e.lat === "number" && typeof e.lon === "number") void addToTripMenu(this.host, b, asPlace(e), (t) => eventTripDay(t, e));
    });
    on(section, "[data-ev-ask]", "click", () => {
      const e = this.chosen();
      if (e) this.host.hooks.ask(askAboutEvent(e));
    });
    on(section, "[data-fiche-retry]", "click", () => {
      if (mine()) void this.readFiche(true);
    });
    section.addEventListener("change", (e) => {
      const t = e.target as HTMLInputElement;
      if (!mine() || !t.matches?.("[data-ev-start], [data-ev-end]")) return;
      if (t.matches("[data-ev-start]")) this.dates = { ...this.dates, start: t.value };
      else this.dates = { ...this.dates, end: t.value };
      void this.search(false);
    });
    section.addEventListener("input", (e) => {
      const t = e.target as HTMLInputElement;
      if (!t.matches("[data-evq]")) return;
      this.q = t.value;
      this.leaveRegard();
      window.clearTimeout(this.typeTimer);
      this.typeTimer = window.setTimeout(() => void this.search(false), TYPE_MS);
    });
  }
}
