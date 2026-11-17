/**
 * Carte › Itinéraire : ses points et leurs propositions (ta position, les lieux de l'index, les adresses), le calcul du
 * trajet, le regard de Mika (ce qu'elle a calculé, posé tel qu'elle l'a gardé), tes choix (`own` : le mode, ce qu'il
 * évite, écrits par tes seuls gestes), le GPX et « En faire un voyage ». Son état et ses gestes sont à lui ; le cadre
 * (`index.ts`) lui donne les lectures communes et la carte (`ItineraryHost`).
 */
import { addStop, createTrip, fetchRoute, searchPlaces, CARTE_LIMITS, type Place, type Route } from "../../api/carte";
import { safeDecode, type LatLon } from "../../map/polyline";
import type { ScenePin } from "../../map/scene";
import { placeWhat } from "../../map/words";
import { $, on } from "../../shell/dom";
import { toast } from "../../shell/float";
import { failureText, newNonce, toastFailure } from "../../shared/kit";
import {
  askAboutRoute,
  fileName,
  routeChoices,
  routeGpx,
  withChoice,
  type RouteChoice,
  type RouteChoices,
} from "./format";
import type { CarteFrame } from "./index";
import { ADDRESS_WAIT_MS, ADDRESSES_SUGGESTED, refused, wantsAddress } from "./requests";
import { chosenPoints, itiKey, itineraryMarkup, pointLetter, typedPoint, type ItiPoint } from "./view";

/** Ce qu'Itinéraire demande au cadre. */
export interface ItineraryHost extends CarteFrame {
  /** La main se repose après un dessin : ce n'est pas la personne qui entre dans un champ. */
  refocusing(): boolean;
}

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

function emptyPoint(): ItiPoint {
  return { query: "", name: "", lat: null, lon: null };
}

function suggestionOf(p: Place): Suggestion {
  return { label: p.name, sub: placeWhat(p), point: { query: p.name, name: p.name, lat: p.lat, lon: p.lon } };
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

export class ItineraryTab {
  private points: ItiPoint[] = [emptyPoint(), emptyPoint()];
  /** Tes choix (le mode, ce qu'il évite) : écrits par tes seuls gestes, repris par un trajet que tu commences. */
  private own: RouteChoices = { mode: "voiture", avoid: [] };
  /**
   * Le mode et ce qu'évite le trajet montré : les tiens, ou ceux du trajet de Mika qu'on regarde — et qu'on garde en le
   * modifiant (un point, une étape, inverser), sans qu'ils deviennent tiens.
   */
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
  /** La dernière frappe dans un point : une adresse attend `ADDRESS_WAIT_MS` après elle. */
  private typedAt = 0;
  /** « En faire un voyage » : en cours, et la clé de cette intention (redemandé après une panne : le même voyage). */
  private sendingTrip = false;
  private tripIntent: { key: string; nonce: string } | null = null;

  constructor(private readonly host: ItineraryHost) {}

  /** Ce que la route ouvre dans Itinéraire : un trajet de Mika (un regard). */
  applyItem(seq: string): void {
    this.itiRegard = null;
    this.itiFrom = null;
    this.applyRouteRegard(seq);
  }

  /** Les lectures sont là : le regard de la route, s'il vient d'être lu ; sinon, un départ de ta position. */
  loaded(seq: string | null): void {
    if (seq && this.itiFrom !== seq && this.host.regards.get(seq).value) this.applyRouteRegard(seq);
    // un itinéraire part de sa position, quand son téléphone l'a donnée (comme la maquette : « Ma position · … »)
    const start = this.points[0];
    const here = this.host.here();
    if (!seq && here && !start.query && start.lat === null) this.points[0] = this.herePoint(here);
  }

  /** Sa position, en point d'un itinéraire (son nom, celui du lieu : c'est lui qu'un voyage gardera). */
  private herePoint(here: { lat: number; lon: number; label: string }): ItiPoint {
    return { query: here.label ? `Ma position · ${here.label}` : "Ma position", name: here.label || "Ma position", lat: here.lat, lon: here.lon };
  }

  /** « Itinéraire jusqu'ici » (Explorer) : de ta position à ce lieu. */
  routeTo(p: Place): void {
    const here = this.host.here();
    this.points = [here ? this.herePoint(here) : emptyPoint(), { query: p.name, name: p.name, lat: p.lat, lon: p.lon }];
    // un trajet que tu commences : tes choix, pas ceux du trajet de Mika montré avant
    ({ mode: this.mode, avoid: this.avoid } = routeChoices(this.own, null));
    this.route = null;
    this.routeFor = "";
    this.routeError = "";
    this.itiRegard = null;
    this.host.fitNext();
    this.host.shell.go("#carte/itineraire");
    void this.computeRoute();
  }

  /**
   * Ce que Mika a calculé, posé tel qu'elle l'a gardé : ses points, son mode, ce qu'elle évitait (quand le regard le
   * dit), son tracé et son résumé. Rien ne se recalcule avant ton premier changement (ou « Recalculer »). Son mode et
   * ses cases se montrent sans devenir les tiens (`own`) : un trajet que tu commences ensuite reprend les tiens.
   */
  private applyRouteRegard(seq: string): void {
    const regard = this.host.regards.get(seq).value;
    if (!regard) return;
    this.itiFrom = seq;
    const pts = regard.places.filter((p) => typeof p.lat === "number" && typeof p.lon === "number");
    if (pts.length >= 2) {
      this.points = pts.slice(0, CARTE_LIMITS.points).map((p) => ({ query: p.name ?? "", name: p.name ?? "", lat: p.lat as number, lon: p.lon as number }));
    }
    const route = regard.route;
    // ce qu'un regard ne dit pas (un regard d'avant ne dit pas ce qu'il évitait) : tes choix
    ({ mode: this.mode, avoid: this.avoid } = routeChoices(this.own, route));
    this.itiRegard = { title: regard.title, distance_m: route?.distance_m ?? null, duration_s: route?.duration_s ?? null,
      line: safeDecode(route?.shape), key: itiKey(this.points, this.mode, this.avoid) };
    this.route = null;
    this.routeFor = "";
    this.routeError = "";
    this.routing = false;
    this.routeSeq += 1;
    this.host.fitNext();
  }

  /** Ce que montre l'itinéraire est-il celui de ses points (un point retapé, un trajet qui se recalcule : non) ? */
  private itiStale(): boolean {
    const shownKey = this.route ? this.routeFor : this.itiRegard?.key ?? null;
    return typedPoint(this.points) || (shownKey !== null && shownKey !== itiKey(this.points, this.mode, this.avoid));
  }

  private suggestionList(): Suggestion[] {
    return [...this.sugg.mine, ...this.sugg.addresses, ...this.sugg.places];
  }

  itineraryHtml(): string {
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
    const map = this.host.pane({ pins, lines }, title);
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

  /**
   * Ton geste sur le mode ou une case : le trajet montré le prend, et il devient ton choix pour les trajets que tu
   * commences — lui seul (`withChoice`) : les autres cases d'un trajet de Mika que tu modifies ne deviennent pas tiennes.
   */
  private choose(choice: RouteChoice): void {
    this.own = withChoice(this.own, choice);
    ({ mode: this.mode, avoid: this.avoid } = withChoice({ mode: this.mode, avoid: this.avoid }, choice));
    this.changed();
  }

  /** Tu changes l'itinéraire (un mode, une case, un point) : ce que Mika avait calculé cède la place, il se recalcule. */
  private changed(): void {
    if (this.itiRegard && this.itiRegard.key === itiKey(this.points, this.mode, this.avoid) && !typedPoint(this.points)) {
      this.host.paint(); // rien de ce qui fait le trajet n'a changé (une étape vide retirée)
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
      if (this.host.open() && this.host.current() === "itineraire") this.host.paint();
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
      this.host.fitNext();
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
    const here = this.host.here();
    const mine: Suggestion[] = here && (!q || "ma position".startsWith(q.toLowerCase()))
      ? [{ label: "Ma position", sub: here.label || "ta dernière position", mine: true, point: this.herePoint(here) }] : [];
    const info = this.host.carte.value;
    const places = q.length >= 2 && info?.places.ready ? await searchPlaces({ q, near: here, limit: 6 }).catch(() => [] as Place[]) : [];
    if (seq !== this.suggestSeq || !this.host.open() || this.host.current() !== "itineraire") return;
    const wanted = !!info?.addresses.ready && wantsAddress(q);
    const known = wanted ? this.host.addressBook.peek(q) : null;
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
      found = await this.host.addressBook.lookup(q);
    } catch (err) {
      note = failureText(err);
    }
    if (seq !== this.suggestSeq || !this.host.open() || this.host.current() !== "itineraire") return;
    this.sugg = { ...this.sugg, addresses: found.slice(0, ADDRESSES_SUGGESTED).map(suggestionOf), note };
    this.showSuggestions(i);
  }

  private showSuggestions(i: number): void {
    this.suggestFor = this.suggestionList().length || this.sugg.note ? i : null;
    this.host.paint();
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
    this.host.fitNext();
    this.changed();
    this.host.paint();
    // la suite : le point suivant encore vide
    const next = this.points.findIndex((p) => typeof p.lat !== "number");
    if (next >= 0) $<HTMLInputElement>(`[data-pt="${next}"]`, this.host.body() ?? document)?.focus();
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
      this.host.trips.invalidate();
      toast("Voyage créé : ses arrêts, au jour 1.", { ico: "plus" });
      this.host.shell.go(`#carte/voyages/${encodeURIComponent(made.id)}`);
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

  // ── Les gestes ─────────────────────────────────────────────────────

  mount(section: HTMLElement): void {
    on(section, "[data-mode]", "click", (_e, b) => this.choose({ mode: b.dataset.mode ?? "voiture" }));
    section.addEventListener("change", (e) => {
      const t = e.target as HTMLInputElement;
      if (!t.matches("[data-avoid]")) return;
      this.choose({ avoid: t.dataset.avoid ?? "", on: t.checked });
    });
    on(section, "[data-iti-add]", "click", () => {
      if (this.points.length >= CARTE_LIMITS.points) return;
      this.points.splice(this.points.length - 1, 0, emptyPoint());
      this.host.paint();
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
      this.host.hooks.ask(askAboutRoute(chosen.map((p) => p.name), this.routeFacts(), this.mode));
    });
    section.addEventListener("keydown", (e) => {
      const t = e.target as HTMLElement;
      if (t.matches("[data-pt]") && e.key === "Escape") {
        this.closeSuggestions();
        this.host.paint();
      }
      if (t.matches("[data-pt]") && e.key === "Enter" && this.suggestFor === Number(t.dataset.pt) && this.suggestionList().length) {
        e.preventDefault();
        this.pick(Number(t.dataset.pt), 0);
      }
    });
    section.addEventListener("input", (e) => {
      const t = e.target as HTMLInputElement;
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
      if (this.host.refocusing()) return; // la main reposée après un dessin : ses propositions sont déjà là
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
        if (this.host.current() === "itineraire") this.host.paint();
      }, 150);
    });
  }
}
