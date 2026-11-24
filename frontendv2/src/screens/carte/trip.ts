/**
 * Carte › Voyages : la liste des voyages, et le voyage ouvert — ses gestes (faits l'un après l'autre par la file, et
 * montrés avant que le serveur les dise : l'optimiste), « Sur la route », la note d'un arrêt, optimiser l'ordre d'un
 * jour, et ajouter un lieu à un voyage (depuis Explorer, « Sur la route » ou la fenêtre « Ajouter un arrêt »). Son état
 * et ses gestes sont à lui ; le cadre (`index.ts`) lui donne les lectures communes et la carte (`TripHost`).
 */
import {
  addStop,
  fetchOnRoute,
  fetchTripRoute,
  moveStop,
  noteStop,
  optimizeDay,
  removeStop,
  CARTE_LIMITS,
  type Place,
  type Trip,
} from "../../api/carte";
import { tripPins } from "../../map/cards";
import type { LatLon } from "../../map/polyline";
import { straightLine } from "../../map/scene";
import { $, on } from "../../shell/dom";
import { toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import { errorBlock, failureText, loadingBlock, newNonce, toastFailure } from "../../shared/kit";
import {
  alongPlace,
  askAboutTrip,
  movedTrip,
  movedWords,
  notedTrip,
  noopMove,
  removedTrip,
  stepMove,
  tripLines,
  tripRouteKey,
} from "./format";
import type { CarteFrame } from "./index";
import { alongAfterRoute, GestureQueue, gone, refused, TripRoutes } from "./requests";
import { alongIndexOf, alongPins, tripEditorMarkup, tripsMarkup } from "./view";

/** La largeur du couloir de « Sur la route », en mètres (les mots de la maquette : « à moins de 10 km »). */
const CORRIDOR_M = 10_000;

/** Ce que Voyages demande au cadre, et par lui aux fenêtres d'un voyage. */
export interface TripHost extends CarteFrame {
  /** Le voyage ouvert, sinon "" (la liste, un autre onglet). */
  tripId(): string;
  /** Le voyage ouvert vient d'être lu, ou ne l'est plus (404) : ses actions arrivent ou partent avec lui. */
  syncTripHead(): void;
  /** Un dessin a été demandé pendant qu'on glissait un arrêt (`drag.ts`) : fait quand il tombe. */
  paintLater(): boolean;
  /** Dire à un lecteur d'écran ce qui vient de se passer (sans bouger la main). */
  say(text: string): void;
  /** La carte ne montre rien : le voyage ne se lit pas (ou pas encore). */
  emptyScene(): void;
  /** Les fenêtres d'un voyage (`modals.ts`). */
  newTripModal(): void;
  editTripModal(trip: Trip): void;
  addStopModal(day: number): void;
}

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

export class TripsTab {
  /** Le trajet de chaque voyage, pour ses arrêts tels qu'ils sont ; relu après un geste, une fois qu'ils ne bougent plus. */
  private readonly routes = new TripRoutes((id) => fetchTripRoute(id), (id) => this.routeLanded(id));
  private along: AlongState = emptyAlong("");
  private alongSeq = 0;
  /** Un voyage montré avant que le serveur le dise (un arrêt déplacé, retiré). */
  private optimistic: Trip | null = null;
  /** Les gestes sur le voyage, l'un après l'autre. */
  private readonly gestures = new GestureQueue();
  /** Combien de gestes ont fini : la relecture d'un geste laisse faire celle d'un geste fini après lui. */
  private finished = 0;
  /** Un geste refusé (ou annulé derrière un refus) depuis la dernière relecture : ce qu'on montrait de lui n'a pas eu lieu. */
  private refusedSince = false;
  private optimizing = false;
  /** L'arrêt dont on écrit la note (un seul à la fois) et ce qu'on a tapé, gardé d'un dessin à l'autre. */
  private noting: { stop: string; draft: string } | null = null;
  /** La clé de la note qu'on enregistre (cet arrêt, ce texte) : redite après une panne, elle ne s'écrit qu'une fois. */
  private noteIntent: { key: string; nonce: string } | null = null;

  constructor(private readonly host: TripHost) {}

  /** Des gestes sur le voyage ouvert sont en cours : sa relecture les suivra (le direct ne le relit pas avant). */
  get busy(): boolean {
    return this.gestures.busy;
  }

  /** Ce que la route ouvre : un voyage (« Sur la route » repart à vide pour un autre). */
  applyItem(item: string | null): void {
    this.optimistic = null;
    this.refusedSince = false;
    this.host.fitNext();
    if (this.along.trip !== item) this.along = emptyAlong(item ?? "");
    this.noting = null;
  }

  /** Le trajet d'un voyage qu'on ouvre : de suite s'il n'est plus celui de ses arrêts (des gestes en cours le reliront). */
  opened(id: string, force: boolean): void {
    const trip = id ? this.host.tripCache.get(id).value : null;
    if (trip && !this.gestures.busy) this.routes.want(trip, { soon: true, force });
  }

  /** Une épingle touchée sur la carte du voyage ouvert. */
  pinClicked(id: string): void {
    // un arrêt, ou un lieu de « Sur la route » (son épingle secondaire) : sa ligne, mise en évidence
    const along = alongIndexOf(id);
    const target = along === null ? `[data-stop="${CSS.escape(id)}"]` : `[data-along-place="${along}"]`;
    const body = this.host.body();
    const li = body ? $<HTMLElement>(target, body) : null;
    li?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    li?.classList.add("flash");
    window.setTimeout(() => li?.classList.remove("flash"), 1200);
  }

  tripsHtml(): string {
    const trips = this.host.trips;
    if (!trips.value) {
      return trips.error ? `<div class="fill-scroll">${errorBlock(trips.error, "Impossible de lire tes voyages")}</div>` : loadingBlock();
    }
    // sa miniature se relit si la liste dit le voyage changé depuis (par elle dans le chat, ailleurs)
    return tripsMarkup(trips.value, (t) => this.host.minis.dataOf({ kind: "trip", ref: t.id }, t.updated), Date.now());
  }

  shownTrip(): Trip | null {
    const id = this.host.tripId();
    return id ? this.tripOf(id) : null;
  }

  /** Le voyage `id` tel qu'on le montre : celui d'un geste pas encore confirmé, sinon le dernier lu (aucun : `null`). */
  tripOf(id: string): Trip | null {
    if (this.optimistic && this.optimistic.id === id) return this.optimistic;
    return this.host.tripCache.get(id).value;
  }

  tripHtml(): string {
    const id = this.host.tripId();
    const cached = this.host.tripCache.get(id);
    const trip = this.shownTrip();
    if (!trip) {
      this.host.emptyScene();
      return cached.error
        ? `<div class="fill-scroll">${gone(cached.error)
          ? `<div class="empty">${ico("map")}<b>Ce voyage n'existe pas</b><p>Il a été supprimé, ou il n'est pas à toi.</p><a class="btn sm" href="#carte/voyages">${ico("chev-left", "sm")}Tes voyages</a></div>`
          : errorBlock(cached.error, "Impossible de lire ce voyage")}</div>`
        : loadingBlock();
    }
    // le trajet de ces arrêts-ci, jamais celui d'avant un geste : en attendant, les arrêts reliés à vol d'oiseau
    const shown = this.routes.shown(trip);
    const route = shown.route;
    const stops = tripPins(trip);
    const routed = tripLines(route);
    const straight = straightLine(stops.map((p): LatLon => [p.lat, p.lon]));
    const lines = routed.length ? routed.map((points) => ({ points })) : straight ? [straight] : [];
    const onRoute = this.along.trip === id ? this.along : emptyAlong(id);
    // les lieux de « Sur la route », en épingles secondaires à côté des arrêts ; leur arrivée ne recadre pas la carte
    // (seuls l'ouverture du voyage et le changement de vue demandent un cadrage : `fitNext`)
    const pins = [...alongPins({ trip, route, onRoute }), ...stops];
    const map = this.host.pane({ pins, lines }, trip.title || "Le voyage");
    return tripEditorMarkup({
      trip,
      route,
      routePending: shown.pending,
      routeError: shown.error && !gone(shown.error) ? failureText(shown.error) : "",
      onRoute,
      noting: this.noting,
      info: this.host.carte.value,
      now: Date.now(),
      map,
    });
  }

  invalidateTrip(id: string): void {
    this.host.tripCache.invalidate(id);
    this.host.trips.invalidate();
    this.host.minis.invalidate({ kind: "trip", ref: id });
  }

  /**
   * Ajouter un lieu à un voyage, avec la clé de cette intention (`nonce`) : redit (un double clic, un réessai), le serveur
   * ne l'ajoute qu'une fois. Au voyage ouvert, après ses autres gestes. Rend ce qui s'est passé (`error` : son refus).
   */
  async addPlace(trip: string, title: string, p: Place, day: number, index: number, nonce: string,
    note = ""): Promise<{ ok: boolean; error: unknown }> {
    const write = async () => {
      const done = await addStop(trip, { name: p.name.slice(0, CARTE_LIMITS.name) || "Lieu", lat: p.lat, lon: p.lon, kind: (p.kind_fr || "").slice(0, CARTE_LIMITS.kind),
        day, index, ...(note ? { note } : {}) }, nonce);
      toast(done.deduped ? `Déjà ajouté au voyage « ${title || "sans titre"} ».` : `Ajouté au voyage « ${title || "sans titre"} », jour ${day}.`, { ico: "plus" });
    };
    if (trip === this.host.tripId()) return this.gesture(trip, write);
    try {
      await write();
      this.invalidateTrip(trip);
      return { ok: true, error: null };
    } catch (err) {
      toastFailure(err);
      return { ok: false, error: err };
    }
  }

  /**
   * Un geste sur le voyage ouvert : écrit après ceux d'avant (`GestureQueue`), puis — quand plus rien n'attend — le
   * voyage relu, et son trajet un moment après. Un refus se dit (un toast, sauf `quiet`) ; rend ce qui s'est passé.
   */
  async gesture(id: string, write: () => Promise<unknown>, quiet = false): Promise<{ ok: boolean; error: unknown }> {
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
    this.finished += 1;
    if (!ok) this.refusedSince = true;
    if (!this.gestures.busy) void this.reloadTrip(id, this.finished);
    return { ok, error };
  }

  /**
   * Après les gestes (`seen` : combien avaient fini) : le voyage relu — après une lecture qui était partie avant eux
   * (`Cached.load`) —, redessiné ; son trajet, `ROUTE_WAIT_MS` après le dernier. Relu, il remplace ce qu'on montrait
   * d'eux. Pas relu (une panne) : l'échec se dit ; si tous ont abouti, ce qu'ils ont posé reste montré (le serveur l'a
   * écrit : le voyage d'avant eux serait faux), sinon le dernier lu fait foi.
   */
  private async reloadTrip(id: string, seen: number): Promise<void> {
    this.invalidateTrip(id);
    const cache = this.host.tripCache.get(id);
    await cache.load(true);
    // un autre geste est parti, ou a fini depuis : sa relecture, partie après lui, fera foi
    if (this.gestures.busy || this.finished !== seen) return;
    const failed = cache.error !== null && !gone(cache.error) ? cache.error : null;
    if (failed) {
      const kept = this.optimistic?.id === id && !this.refusedSince ? this.optimistic : null;
      toast(kept
        ? `C'est enregistré, mais le voyage ne s'est pas relu : ${failureText(failed)} L'écran garde ce que tu as fait.`
        : `Le voyage ne s'est pas relu : ${failureText(failed)}`, { ico: "alert", duration: 4200 });
      if (kept) {
        this.routes.want(kept);
        if (this.host.open()) this.host.paint();
        return;
      }
    }
    this.optimistic = null;
    this.refusedSince = false;
    if (this.host.tripId() === id) this.host.syncTripHead(); // supprimé ailleurs (404) : ses actions partent
    const trip = this.host.tripCache.get(id).value;
    if (trip) this.routes.want(trip);
    // revenu à des arrêts dont on a déjà le trajet (monté puis redescendu) : rien ne se relit, « Sur la route » suit
    if (trip && !this.routes.shown(trip).pending) this.routeLanded(id);
    else if (this.host.open()) this.host.paint();
  }

  /** Un trajet (ou son refus) vient d'arriver : « Sur la route » suit s'il avait été cherché pour d'autres arrêts. */
  private routeLanded(id: string): void {
    const trip = this.host.tripCache.get(id).value;
    if (trip && this.along.trip === id) {
      const next = alongAfterRoute(this.along, tripRouteKey(trip));
      if (next === "adopt") this.along = { ...this.along, key: tripRouteKey(trip), adopt: false };
      if (next === "reload") void this.loadAlong(id, this.along.cat);
    }
    if (this.host.open() && this.host.current() === "voyage" && this.host.tripId() === id) this.host.paint();
  }

  private async loadAlong(id: string, cat: string): Promise<void> {
    const seq = ++this.alongSeq;
    const trip = this.host.tripCache.get(id).value;
    const key = trip ? tripRouteKey(trip) : "";
    this.along = { ...emptyAlong(id), cat, loading: true, key };
    this.host.paint();
    try {
      const got = await fetchOnRoute(id, { cat, day: 0, corridor: CORRIDOR_M, limit: 12 });
      if (seq !== this.alongSeq) return;
      // une clé par lieu, faite avec la liste : « Ajouter » cliqué deux fois ne l'ajoute qu'une fois
      this.along = { ...emptyAlong(id), cat, places: got.places, routed: got.route, key, keys: got.places.map(() => newNonce()) };
    } catch (err) {
      if (seq !== this.alongSeq) return;
      this.along = { ...emptyAlong(id), cat, error: failureText(err), key };
    }
    if (this.host.open() && this.host.current() === "voyage") this.host.paint();
  }

  moveTo(stop: string, day: number, index: number): void {
    const id = this.host.tripId();
    const trip = this.shownTrip();
    // lâché où il était (un tremblement de la poignée) : rien ne part
    if (!id || !trip || noopMove(trip, stop, day, index)) {
      if (this.host.paintLater()) this.host.paint();
      return;
    }
    this.optimistic = movedTrip(trip, stop, day, index);
    this.host.paint();
    const nonce = newNonce();
    void this.gesture(id, () => moveStop(id, stop, day, index, nonce));
  }

  private remove(stop: string): void {
    const id = this.host.tripId();
    const trip = this.shownTrip();
    const s = trip?.days.flatMap((d) => d.stops).find((x) => x.id === stop);
    if (!id || !trip || !s) return;
    // retiré de suite à l'écran : un second clic ne trouve plus son bouton
    this.optimistic = removedTrip(trip, stop);
    if (this.noting?.stop === stop) this.noting = null;
    this.host.paint();
    const nonce = newNonce();
    void this.gesture(id, async () => {
      await removeStop(id, stop, nonce);
      toast(s.by === "mika" ? "Arrêt retiré. Mika le saura en relisant le voyage." : "Arrêt retiré.", { ico: "x" });
    });
  }

  // ── La note d'un arrêt ─────────────────────────────────────────────

  /** Le contrôle `selector` prend la main après le dessin (le champ qui s'ouvre, le crayon quand il se referme). */
  private focusAfterPaint(selector: string, end = false): void {
    const body = this.host.body();
    const el = body ? $<HTMLElement>(selector, body) : null;
    if (!el) return;
    el.focus({ preventScroll: true });
    if (end && el instanceof HTMLInputElement) el.setSelectionRange(el.value.length, el.value.length);
  }

  /** « Noter » : le champ en place, prérempli de sa note ; un autre arrêt en saisie se referme (un seul à la fois). */
  private openNote(stop: string): void {
    const s = this.shownTrip()?.days.flatMap((d) => d.stops).find((x) => x.id === stop);
    if (!s) return;
    if (this.noting?.stop === stop) return this.closeNote(stop);
    this.noting = { stop, draft: s.note };
    this.host.paint();
    this.focusAfterPaint(`[data-note-input="${CSS.escape(stop)}"]`, true);
  }

  /** Échap, « Annuler » : le champ se referme sans rien écrire ; la main revient au crayon. */
  private closeNote(stop: string): void {
    if (this.noting?.stop !== stop) return;
    this.noting = null;
    this.host.paint();
    this.focusAfterPaint(`[data-note-stop="${CSS.escape(stop)}"]`);
  }

  /**
   * Entrée, « Enregistrer » : la note (vidée : effacée) montrée de suite, écrite après les autres gestes, avec la clé de
   * cette intention (cet arrêt, ce texte). Refusée ou pas partie, le champ se rouvre sur ce qu'on avait tapé.
   */
  private saveNote(stop: string): void {
    const id = this.host.tripId();
    const trip = this.shownTrip();
    const noting = this.noting;
    const s = trip?.days.flatMap((d) => d.stops).find((x) => x.id === stop);
    if (!id || !trip || !noting || noting.stop !== stop || !s) return;
    const note = noting.draft.trim().slice(0, CARTE_LIMITS.note);
    if (note === s.note) return this.closeNote(stop);
    const key = JSON.stringify([id, stop, note]);
    if (this.noteIntent?.key !== key) this.noteIntent = { key, nonce: newNonce() };
    const nonce = this.noteIntent.nonce;
    this.optimistic = notedTrip(trip, stop, note);
    this.noting = null;
    this.host.paint();
    this.focusAfterPaint(`[data-note-stop="${CSS.escape(stop)}"]`);
    void this.gesture(id, async () => {
      await noteStop(id, stop, note, nonce);
      toast(note ? "Note enregistrée." : "Note effacée.", { ico: "pen" });
    }).then(({ ok, error }) => {
      if (ok || refused(error)) this.noteIntent = null;
      // pas écrite : ce qu'on avait tapé revient dans son champ, si on n'en a pas ouvert un autre entre-temps
      if (ok || this.noting || this.host.tripId() !== id) return;
      if (!this.shownTrip()?.days.some((d) => d.stops.some((x) => x.id === stop))) return;
      this.noting = { stop, draft: noting.draft };
      if (this.host.open()) this.host.paint();
    });
  }

  private async optimize(): Promise<void> {
    const id = this.host.tripId();
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
    const id = this.host.tripId();
    const trip = this.shownTrip();
    const p = this.along.places[i];
    const nonce = this.along.keys[i];
    if (!id || !trip || !p || !nonce || this.along.sending === i) return;
    const [day, index] = alongPlace(trip, this.routes.shown(trip).route, p.along_m);
    const along = this.along;
    this.along = { ...along, sending: i };
    this.host.paint();
    void this.addPlace(id, trip.title, p, day, index, nonce).then(({ ok }) => {
      if (this.along.trip === id && this.along.keys === along.keys && this.along.sending === i) {
        this.along = { ...this.along, sending: null, adopt: this.along.adopt || ok };
        if (this.host.open()) this.host.paint();
      }
    });
  }

  // ── Les gestes ─────────────────────────────────────────────────────

  mount(section: HTMLElement): void {
    on(section, "[data-new-trip]", "click", () => this.host.newTripModal());
    on(section, "[data-edit-trip]", "click", () => {
      const trip = this.shownTrip();
      if (trip) this.host.editTripModal(trip);
    });
    on(section, "[data-ask-trip]", "click", () => {
      const trip = this.shownTrip();
      if (trip) this.host.hooks.ask(askAboutTrip(trip));
    });
    on(section, "[data-optimize]", "click", () => void this.optimize());
    on(section, "[data-retirer]", "click", (_e, b) => this.remove(b.dataset.retirer ?? ""));
    on(section, "[data-note-stop]", "click", (_e, b) => this.openNote(b.dataset.noteStop ?? ""));
    on(section, "[data-note-save]", "click", (_e, b) => this.saveNote(b.dataset.noteSave ?? ""));
    on(section, "[data-note-cancel]", "click", (_e, b) => this.closeNote(b.dataset.noteCancel ?? ""));
    on(section, "[data-add-stop]", "click", (_e, b) => this.host.addStopModal(Number(b.dataset.addStop) || 1));
    on(section, "[data-onroute]", "click", (_e, b) => {
      const id = this.host.tripId();
      const cat = b.dataset.onroute ?? "";
      if (!id) return;
      if (this.along.trip === id && this.along.cat === cat) {
        this.alongSeq += 1;
        this.along = emptyAlong(id);
        this.host.paint();
        return;
      }
      void this.loadAlong(id, cat);
    });
    on(section, "[data-add-along]", "click", (_e, b) => this.addAlong(Number(b.dataset.addAlong)));
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
        if (moved) this.host.say(movedWords(moved, stop));
        return;
      }
      // la note d'un arrêt : Entrée l'enregistre, Échap referme son champ sans rien écrire
      if (t.matches("[data-note-input]") && !e.isComposing && (e.key === "Enter" || e.key === "Escape")) {
        e.preventDefault();
        if (e.key === "Enter") this.saveNote(t.dataset.noteInput ?? "");
        else this.closeNote(t.dataset.noteInput ?? "");
      }
    });
    section.addEventListener("input", (e) => {
      const t = e.target as HTMLInputElement;
      if (t.matches("[data-note-input]")) {
        // gardé d'un dessin à l'autre (le voyage relu après un autre geste redessine l'écran)
        const noting = this.noting;
        if (noting && noting.stop === t.dataset.noteInput) noting.draft = t.value;
      }
    });
  }
}
