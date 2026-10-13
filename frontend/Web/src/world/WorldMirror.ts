import type {
  ActorState,
  Change,
  GestureOut,
  Intent,
  IntentEnd,
  ObjectState,
  Presence,
  Request,
  RequestClose,
  ServerFrame,
  WorldState,
} from "./protocol.g";
import { WorldIndex } from "./WorldIndex";

/** Ce qu'une trame a fait au miroir. */
export type FrameEffect =
  /** Appliquée. */
  | "applied"
  /** Déjà vue (seq inférieur ou égal au dernier appliqué) : ignorée. */
  | "duplicate"
  /** Pas une trame d'état (accusé, bail, pong, erreur) : rien à appliquer. */
  | "not_state"
  /** Reçue avant la définition ou l'instantané : ignorée, l'état complet suivra. */
  | "not_ready";

/** Une personne présente dans le monde, telle que `presence` l'a annoncée. */
export interface Visitor {
  actor: string;
  label: string;
  asset: string | null;
}

/** Un acteur tel que le miroir le tient : ce qu'il tient est toujours une liste. */
export type MirroredActor = ActorState & { holding: string[] };

export interface MirrorEvents {
  /** Nouvelle définition (entière ou éditée) : reconstruire ce qui en dépend. */
  definition: (world: WorldIndex) => void;
  /** Un instantané a remplacé tout l'état : poser chaque chose sans rien jouer. */
  reset: () => void;
  actor: (id: string) => void;
  object: (id: string) => void;
  objectRemoved: (id: string) => void;
  intentStarted: (intent: Intent) => void;
  intentEnded: (end: IntentEnd) => void;
  requestOpened: (request: Request) => void;
  requestClosed: (close: RequestClose) => void;
  gesture: (gesture: GestureOut) => void;
  presence: (presence: Presence) => void;
}

type Listeners = { [K in keyof MirrorEvents]: Set<MirrorEvents[K]> };

/**
 * La copie locale du monde : la définition et l'état vécu, tenus à jour par
 * les trames du noyau, dans l'ordre du journal. C'est la seule chose que les
 * vues lisent : un écran ne montre jamais un état qu'il n'a pas reçu (règle 1
 * du protocole), même le sien.
 *
 * Le `seq` est celui du journal du noyau : il croît, mais n'est pas contigu
 * (le journal porte aussi le reste de sa vie). Une trame dont le `seq`
 * n'avance pas est un doublon (un rattrapage qui chevauche). Sans three.js,
 * sans réseau : testable seul. (Le jumeau de `Mika.World.Model.WorldMirror`.)
 */
export class WorldMirror {
  private readonly actorStates = new Map<string, MirroredActor>();
  private readonly objectStates = new Map<string, ObjectState>();
  private readonly intentsById = new Map<string, Intent>();
  private readonly requestsById = new Map<string, Request>();
  private readonly visitorsById = new Map<string, Visitor>();
  private readonly listeners: Listeners = {
    definition: new Set(),
    reset: new Set(),
    actor: new Set(),
    object: new Set(),
    objectRemoved: new Set(),
    intentStarted: new Set(),
    intentEnded: new Set(),
    requestOpened: new Set(),
    requestClosed: new Set(),
    gesture: new Set(),
    presence: new Set(),
  };

  world: WorldIndex | null = null;
  /** Le dernier `seq` appliqué ; -1 tant qu'aucun état n'a été posé. */
  seq = -1;

  /** Vrai dès qu'une définition et un état complet ont été reçus. */
  get ready(): boolean {
    return this.world !== null && this.seq >= 0;
  }

  get actors(): ReadonlyMap<string, MirroredActor> {
    return this.actorStates;
  }

  get objects(): ReadonlyMap<string, ObjectState> {
    return this.objectStates;
  }

  get intents(): ReadonlyMap<string, Intent> {
    return this.intentsById;
  }

  get requests(): ReadonlyMap<string, Request> {
    return this.requestsById;
  }

  get visitors(): ReadonlyMap<string, Visitor> {
    return this.visitorsById;
  }

  /** S'abonne ; rend de quoi se désabonner. */
  on<K extends keyof MirrorEvents>(event: K, fn: MirrorEvents[K]): () => void {
    const set = this.listeners[event] as Set<MirrorEvents[K]>;
    set.add(fn);
    return () => set.delete(fn);
  }

  private emit<K extends keyof MirrorEvents>(event: K, ...args: Parameters<MirrorEvents[K]>): void {
    for (const fn of this.listeners[event] as Set<(...a: Parameters<MirrorEvents[K]>) => void>) {
      try {
        fn(...args);
      } catch (err) {
        // Une vue qui lève ne doit pas laisser le miroir à moitié appliqué.
        console.warn(`[monde] un abonné à « ${event} » a levé :`, err);
      }
    }
  }

  actor(id: string | null | undefined): MirroredActor | undefined {
    return id ? this.actorStates.get(id) : undefined;
  }

  object(id: string | null | undefined): ObjectState | undefined {
    return id ? this.objectStates.get(id) : undefined;
  }

  /** L'action en cours d'un acteur (au plus une : une nouvelle interrompt la précédente). */
  intentOf(actor: string): Intent | undefined {
    for (const i of this.intentsById.values()) if (i.actor === actor) return i;
    return undefined;
  }

  /** Qui tient un objet, ou `undefined`. */
  holderOf(objectId: string): string | undefined {
    const loc = this.object(objectId)?.location;
    return loc?.kind === "held" ? loc.actor : undefined;
  }

  /** La pièce où se trouve un objet (en remontant surfaces et contenants, ou par la main qui le tient). */
  roomOfObject(objectId: string): string | undefined {
    const o = this.object(objectId);
    if (!o) return undefined;
    if (o.location.kind === "held") return this.actor(o.location.actor)?.room;
    return this.world?.roomOf(o.location, (id) => this.object(id)?.location ?? this.world?.object(id)?.home);
  }

  apply(frame: ServerFrame): FrameEffect {
    if (frame.type === "definition") {
      this.world = WorldIndex.of(frame.world);
      this.emit("definition", this.world);
      return "applied";
    }
    if (frame.type === "snapshot") {
      this.resetTo(frame.state);
      return "applied";
    }
    const seq = seqOf(frame);
    if (seq === null) return "not_state";
    if (!this.ready) return "not_ready";
    if (seq <= this.seq) return "duplicate";

    switch (frame.type) {
      case "definition_delta":
        this.world = this.world!.with(frame.changes, frame.rev);
        this.seq = frame.seq;
        this.emit("definition", this.world);
        break;
      case "delta":
        this.seq = frame.seq;
        this.applyChanges(frame.changes);
        break;
      case "intent": {
        this.seq = frame.seq;
        const intent = frame.intent;
        this.intentsById.set(intent.id, intent);
        // Comme le noyau : une action qui commence arrache l'acteur à ce qu'il
        // faisait, sans changement dans la trame.
        const starter = this.actorStates.get(intent.actor);
        const interrupted = starter !== undefined && starter.activity != null;
        if (interrupted) starter.activity = null;
        this.emit("intentStarted", intent);
        if (interrupted) this.emit("actor", intent.actor);
        break;
      }
      case "intent_end": {
        this.seq = frame.seq;
        this.intentsById.delete(frame.intent);
        this.applyChanges(frame.changes);
        const actor = this.actorStates.get(frame.actor);
        if (actor && actor.moving?.intent === frame.intent) {
          actor.moving = null;
          this.emit("actor", frame.actor);
        }
        this.emit("intentEnded", frame);
        break;
      }
      case "request":
        this.seq = frame.seq;
        this.requestsById.set(frame.request.id, frame.request);
        this.emit("requestOpened", frame.request);
        break;
      case "request_end":
        this.seq = frame.seq;
        this.requestsById.delete(frame.request);
        this.applyChanges(frame.changes);
        this.emit("requestClosed", frame);
        break;
      case "gesture":
        this.seq = frame.seq;
        this.emit("gesture", frame);
        break;
      case "presence":
        this.seq = frame.seq;
        this.applyPresence(frame);
        break;
      default:
        return "not_state";
    }
    return "applied";
  }

  private resetTo(state: WorldState): void {
    this.actorStates.clear();
    this.objectStates.clear();
    this.intentsById.clear();
    this.requestsById.clear();
    for (const a of state.actors) this.actorStates.set(a.id, { ...a, holding: [...(a.holding ?? [])] });
    for (const o of state.objects) this.objectStates.set(o.id, { ...o });
    for (const i of state.intents ?? []) this.intentsById.set(i.id, i);
    for (const r of state.requests ?? []) this.requestsById.set(r.id, r);
    // Les visiteurs connus restent (l'instantané ne porte pas leur nom) ; on
    // oublie ceux qui n'y sont plus.
    for (const id of [...this.visitorsById.keys()]) if (!this.actorStates.has(id)) this.visitorsById.delete(id);
    this.seq = state.seq;
    this.emit("reset");
  }

  private applyPresence(p: Presence): void {
    if (p.joined) {
      this.visitorsById.set(p.actor, { actor: p.actor, label: p.label ?? "", asset: p.asset ?? null });
      const state = this.actorOrNew(p.actor);
      if (p.room) state.room = p.room;
      state.place = p.place ?? null;
    } else {
      this.visitorsById.delete(p.actor);
      this.actorStates.delete(p.actor);
    }
    this.emit("presence", p);
    this.emit("actor", p.actor);
  }

  private applyChanges(changes: readonly Change[] | undefined): void {
    for (const change of changes ?? []) {
      switch (change.kind) {
        case "actor_moved": {
          const a = this.actorOrNew(change.actor);
          a.room = change.room;
          a.place = change.place ?? null;
          a.posture = change.posture ?? "stand";
          a.moving = null;
          this.emit("actor", change.actor);
          break;
        }
        case "actor_activity": {
          const a = this.actorOrNew(change.actor);
          a.activity = change.activity ?? null;
          this.emit("actor", change.actor);
          break;
        }
        case "object_moved": {
          const o = this.objectOrNew(change.object, change.to);
          const before = o.location.kind === "held" ? o.location.actor : undefined;
          o.location = change.to;
          const after = change.to.kind === "held" ? change.to.actor : undefined;
          if (before !== undefined && before !== after) {
            const b = this.actorStates.get(before);
            if (b) {
              b.holding = b.holding.filter((id) => id !== change.object);
              this.emit("actor", before);
            }
          }
          if (after !== undefined) {
            const a = this.actorOrNew(after);
            if (!a.holding.includes(change.object)) a.holding.push(change.object);
            this.emit("actor", after);
          }
          this.emit("object", change.object);
          break;
        }
        case "object_state": {
          const o = this.objectOrNew(change.object);
          o.state = change.state ?? null;
          this.emit("object", change.object);
          break;
        }
        case "object_gone": {
          const holder = this.holderOf(change.object);
          this.objectStates.delete(change.object);
          if (holder !== undefined) {
            const h = this.actorStates.get(holder);
            if (h) {
              h.holding = h.holding.filter((id) => id !== change.object);
              this.emit("actor", holder);
            }
          }
          this.emit("objectRemoved", change.object);
          break;
        }
        // Un changement d'une sorte inconnue : une version plus récente du noyau, ignorée.
      }
    }
  }

  private actorOrNew(id: string): MirroredActor {
    let a = this.actorStates.get(id);
    if (!a) {
      a = { id, room: "", holding: [] };
      this.actorStates.set(id, a);
    }
    return a;
  }

  private objectOrNew(id: string, at?: ObjectState["location"]): ObjectState {
    let o = this.objectStates.get(id);
    if (!o) {
      const home = this.world?.object(id)?.home;
      o = { id, location: at ?? home ?? { kind: "room", room: "" } };
      this.objectStates.set(id, o);
    }
    return o;
  }
}

/** Le `seq` d'une trame d'état, `null` pour les autres. */
export function seqOf(frame: ServerFrame): number | null {
  switch (frame.type) {
    case "definition_delta":
    case "delta":
    case "intent":
    case "intent_end":
    case "request":
    case "request_end":
    case "gesture":
    case "presence":
      return frame.seq;
    default:
      return null;
  }
}
