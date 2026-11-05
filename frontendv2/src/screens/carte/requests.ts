/**
 * Carte : ménager ce qui sort du serveur, et ne rien faire deux fois — sans DOM. Une adresse et un trajet comptent dans
 * les bornes du serveur (`protocole-moi.md` § 10 : 60 adresses et 20 trajets par minute et par compte, 429 au-delà ; le
 * serveur d'itinéraires public ne répond qu'une fois par seconde, pour tous). Ici : les adresses gardées par texte
 * (`AddressBook`), le trajet d'un voyage gardé pour ses arrêts et relu un moment après le dernier geste (`TripRoutes`),
 * les gestes sur un voyage faits l'un après l'autre (`GestureQueue`), et quand un envoi refusé a usé sa clé.
 */
import type { Place, Trip, TripRoute } from "../../api/carte";
import { ApiError } from "../../api/moi";
import { routableStops, tripRouteKey } from "./format";

// ── Les adresses ─────────────────────────────────────────────────────

/** Combien d'adresses on demande pour un texte (chaque écran en montre autant ou moins). */
export const ADDRESS_LIMIT = 5;
/** Combien de temps la saisie doit s'arrêter avant qu'une adresse se demande. */
export const ADDRESS_WAIT_MS = 700;

/** Un texte qui vaut d'être cherché en adresse : trois caractères au moins, et un chiffre ou cinq caractères. */
export function wantsAddress(q: string): boolean {
  const text = q.trim();
  return text.length >= 3 && (/\d/.test(text) || text.length >= 5);
}

function addressKey(q: string): string {
  return q.trim().replace(/\s+/g, " ").toLowerCase();
}

/**
 * Les adresses trouvées, par texte (les espaces et la casse n'y comptent pas) : un texte déjà cherché ne se redemande
 * pas, deux demandes du même texte n'en font qu'une. Un refus (429, 503) ne se garde pas : l'appelant le dit.
 */
export class AddressBook {
  private readonly found = new Map<string, Place[]>();
  private readonly pending = new Map<string, Promise<Place[]>>();

  constructor(
    private readonly fetcher: (q: string, limit: number) => Promise<Place[]>,
    private readonly keep = 100,
  ) {}

  /** Ce qu'on a déjà trouvé pour ce texte, sinon `null` (rien ne part). */
  peek(q: string): Place[] | null {
    return this.found.get(addressKey(q)) ?? null;
  }

  lookup(q: string): Promise<Place[]> {
    const key = addressKey(q);
    const known = this.found.get(key);
    if (known) return Promise.resolve(known);
    let pending = this.pending.get(key);
    if (!pending) {
      pending = this.fetcher(q.trim(), ADDRESS_LIMIT)
        .then((got) => {
          this.found.set(key, got);
          // les plus anciens s'en vont
          while (this.found.size > this.keep) this.found.delete(this.found.keys().next().value as string);
          return got;
        })
        .finally(() => this.pending.delete(key));
      this.pending.set(key, pending);
    }
    return pending;
  }
}

// ── Le trajet d'un voyage ────────────────────────────────────────────

/** Combien de temps après le dernier geste le trajet se relit (dix flèches au clavier : une seule relecture). */
export const ROUTE_WAIT_MS = 1500;

/** Ce qu'on montre du trajet d'un voyage tel qu'il est maintenant. */
export interface RouteShown {
  /** Le trajet calculé pour ces arrêts, sinon `null`. */
  route: TripRoute | null;
  /** Son refus, pour ces arrêts (le trajet d'avant ne se montre plus à côté). */
  error: unknown;
  /** Il se recalcule (les arrêts ont changé depuis). */
  pending: boolean;
}

interface RouteState {
  key: string;
  route: TripRoute | null;
  error: unknown;
}

/**
 * Le trajet de chaque voyage, gardé pour ce dont il dépend (`tripRouteKey` : ses arrêts dans l'ordre, son mode, ce
 * qu'il évite) : un trajet qui n'est plus celui des arrêts ne se montre pas. Un voyage qui change se relit `wait` ms
 * après le dernier geste ; ouvert, de suite ; sous deux arrêts, il n'a pas de trajet. `landed` : un trajet (ou son refus)
 * vient d'arriver.
 */
export class TripRoutes {
  private readonly states = new Map<string, RouteState>();
  /** Le voyage tel qu'on le sait : c'est lui qu'une relecture sert. */
  private readonly latest = new Map<string, Trip>();
  private readonly timers = new Map<string, ReturnType<typeof setTimeout>>();
  /** La relecture en cours (sa clé), et le numéro de la dernière partie. */
  private readonly reading = new Map<string, string>();
  private readonly seqs = new Map<string, number>();

  constructor(
    private readonly fetcher: (id: string) => Promise<TripRoute>,
    private readonly landed: (id: string) => void,
    private readonly wait = ROUTE_WAIT_MS,
  ) {}

  shown(trip: Trip): RouteShown {
    if (routableStops(trip) < 2) return { route: null, error: null, pending: false };
    const state = this.states.get(trip.id);
    if (state && state.key === tripRouteKey(trip)) return { route: state.route, error: state.error, pending: false };
    return { route: null, error: null, pending: true };
  }

  /**
   * Le voyage tel qu'il est (ouvert, relu, changé par un geste) : son trajet se relit s'il n'est plus le sien —
   * `soon` : de suite (sans écourter un geste qui attend déjà) ; sinon `wait` ms après ce geste-ci. `force` : même s'il
   * l'est (« Réessayer »).
   */
  want(trip: Trip, opts: { soon?: boolean; force?: boolean } = {}): void {
    const id = trip.id;
    this.latest.set(id, trip);
    if (routableStops(trip) < 2) {
      this.cancel(id);
      this.states.delete(id);
      return;
    }
    const key = tripRouteKey(trip);
    if (!opts.force && (this.states.get(id)?.key === key || this.reading.get(id) === key)) {
      this.cancel(id); // revenu à ce qu'on a déjà (un arrêt monté puis redescendu) : rien à relire
      return;
    }
    if (opts.soon && !opts.force && this.timers.has(id)) return;
    this.cancel(id);
    if (opts.soon || opts.force) {
      void this.read(id);
      return;
    }
    this.timers.set(id, setTimeout(() => {
      this.timers.delete(id);
      void this.read(id);
    }, this.wait));
  }

  private cancel(id: string): void {
    const timer = this.timers.get(id);
    if (timer !== undefined) clearTimeout(timer);
    this.timers.delete(id);
  }

  private async read(id: string): Promise<void> {
    const trip = this.latest.get(id);
    if (!trip) return;
    const key = tripRouteKey(trip);
    const seq = (this.seqs.get(id) ?? 0) + 1;
    this.seqs.set(id, seq);
    this.reading.set(id, key);
    let state: RouteState;
    try {
      state = { key, route: await this.fetcher(id), error: null };
    } catch (error) {
      state = { key, route: null, error };
    }
    if (this.seqs.get(id) !== seq) return; // une relecture plus récente est partie
    this.reading.delete(id);
    this.states.set(id, state);
    this.landed(id);
  }
}

/**
 * « Sur la route » quand le voyage a un autre trajet (`key`) : rien à faire (fermé, ou déjà cherché pour lui) ; prendre
 * sa clé sans rien demander (`adopt` : un de ses lieux vient d'être ajouté, la liste reste vraie) ; ou se rechercher.
 */
export function alongAfterRoute(along: { cat: string; key: string; adopt: boolean; loading: boolean }, key: string): "keep" | "adopt" | "reload" {
  if (!along.cat || along.key === key) return "keep";
  return along.adopt && !along.loading ? "adopt" : "reload";
}

// ── Les gestes sur un voyage ─────────────────────────────────────────

/**
 * Les gestes sur un voyage, faits l'un après l'autre : chacun part du voyage que le précédent a laissé (son index se
 * lit sur lui). Un geste refusé annule ceux qui attendaient derrière lui : ils partaient d'un voyage qui n'a pas eu
 * lieu. `run` rend vrai si le geste a abouti, faux s'il a été annulé ; un refus se lève.
 */
export class GestureQueue {
  private tail: Promise<unknown> = Promise.resolve();
  private waiting = 0;
  private generation = 0;

  /** Un geste en cours, ou qui attend. */
  get busy(): boolean {
    return this.waiting > 0;
  }

  run(write: () => Promise<void>): Promise<boolean> {
    const generation = this.generation;
    this.waiting += 1;
    const done = this.tail
      .then(async () => {
        if (generation !== this.generation) return false;
        try {
          await write();
          return true;
        } catch (err) {
          this.generation += 1;
          throw err;
        }
      })
      .finally(() => {
        this.waiting -= 1;
      });
    this.tail = done.catch(() => undefined);
    return done;
  }
}

/**
 * Un envoi refusé par le serveur (400, 404, 409 : il a lu, et dit non) a usé sa clé : le refaire est une autre demande,
 * avec une autre clé. Une panne, un 429, un 503 : on ne sait pas s'il a abouti, ou il n'a pas été tenté — on le refait
 * avec la même clé, et le serveur ne refait pas ce qui l'a été.
 */
export function refused(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 400 || err.status === 404 || err.status === 409);
}
