import type {
  ActorDef,
  ArchetypeDef,
  DefChange,
  DefItem,
  DefKind,
  Location,
  ObjectDef,
  PlaceDef,
  RoomDef,
  WorldDef,
} from "./protocol.g";

/**
 * La définition du monde (ce que le créateur a écrit), indexée par
 * identifiant. Immuable : une édition (`with`) en donne une nouvelle, si
 * bien qu'un lecteur qui tient l'ancienne ne la voit jamais changer sous lui.
 *
 * Le client ne valide pas la définition : le noyau l'a fait avant de la
 * diffuser (« cohérent ou rien »). Ce qui manque ici (un lieu inconnu, un
 * archétype absent) est un cas de version — on l'ignore sans planter.
 * (Le jumeau de `Mika.World.Model.WorldIndex` côté Unity.)
 */
export class WorldIndex {
  readonly rooms: ReadonlyMap<string, RoomDef>;
  readonly places: ReadonlyMap<string, PlaceDef>;
  readonly archetypes: ReadonlyMap<string, ArchetypeDef>;
  readonly objects: ReadonlyMap<string, ObjectDef>;
  readonly actors: ReadonlyMap<string, ActorDef>;

  private constructor(readonly def: WorldDef) {
    this.rooms = byId(def.rooms);
    this.places = byId(def.places);
    this.archetypes = byId(def.archetypes);
    this.objects = byId(def.objects);
    this.actors = byId(def.actors);
  }

  static of(def: WorldDef): WorldIndex {
    return new WorldIndex(def);
  }

  get rev(): number {
    return this.def.rev ?? 0;
  }

  get id(): string {
    return this.def.id;
  }

  room(id: string | null | undefined): RoomDef | undefined {
    return id ? this.rooms.get(id) : undefined;
  }

  place(id: string | null | undefined): PlaceDef | undefined {
    return id ? this.places.get(id) : undefined;
  }

  object(id: string | null | undefined): ObjectDef | undefined {
    return id ? this.objects.get(id) : undefined;
  }

  actor(id: string | null | undefined): ActorDef | undefined {
    return id ? this.actors.get(id) : undefined;
  }

  archetype(id: string | null | undefined): ArchetypeDef | undefined {
    return id ? this.archetypes.get(id) : undefined;
  }

  archetypeOf(objectId: string | null | undefined): ArchetypeDef | undefined {
    return this.archetype(this.object(objectId)?.archetype);
  }

  /** Ce qu'elle lit d'un objet : son nom, sinon celui de sa sorte, sinon son identifiant. */
  labelOf(objectId: string): string {
    const def = this.object(objectId);
    return def?.label || this.archetype(def?.archetype)?.label || objectId;
  }

  placesIn(room: string): PlaceDef[] {
    return (this.def.places ?? []).filter((p) => p.room === room);
  }

  /** Le lieu où entre une personne : le lieu `spawn` de la pièce, sinon le premier lieu `spawn`. */
  spawnPlace(room?: string | null): PlaceDef | undefined {
    const spawns = (this.def.places ?? []).filter((p) => p.tags?.includes("spawn"));
    return spawns.find((p) => p.room === room) ?? spawns[0] ?? this.def.places?.[0];
  }

  /**
   * La pièce d'un emplacement, en remontant les surfaces et les contenants
   * (jamais en boucle). Tenu par une main : la pièce est celle de l'acteur,
   * que la définition ne connaît pas (`undefined`).
   */
  roomOf(
    location: Location | null | undefined,
    locationOfObject: (id: string) => Location | null | undefined = (id) => this.object(id)?.home
  ): string | undefined {
    const seen = new Set<string>();
    let loc = location;
    while (loc) {
      switch (loc.kind) {
        case "room":
          return loc.room;
        case "on":
        case "in":
          if (seen.has(loc.object)) return undefined;
          seen.add(loc.object);
          loc = locationOfObject(loc.object);
          break;
        default:
          return undefined;
      }
    }
    return undefined;
  }

  /**
   * La définition après un lot d'éditions (`definition_delta`). Le lot vient
   * du noyau, qui l'a déjà validé en entier : on l'applique tel quel.
   */
  with(changes: readonly DefChange[], rev: number): WorldIndex {
    const def: WorldDef = structuredClone(this.def);
    def.rev = rev;
    for (const change of changes) {
      if (change.op === "put") put(def, change.item);
      else if (change.op === "remove") remove(def, change.of, change.id);
    }
    return new WorldIndex(def);
  }
}

function byId<T extends { id: string }>(items: readonly T[] | undefined): Map<string, T> {
  const map = new Map<string, T>();
  for (const item of items ?? []) map.set(item.id, item);
  return map;
}

function replace<T extends { id: string }>(list: T[], item: T): void {
  const i = list.findIndex((x) => x.id === item.id);
  if (i >= 0) list[i] = item;
  else list.push(item);
}

function put(def: WorldDef, item: DefItem): void {
  switch (item.kind) {
    case "room":
      replace((def.rooms ??= []), item);
      break;
    case "place":
      replace((def.places ??= []), item);
      break;
    case "archetype":
      replace((def.archetypes ??= []), item);
      break;
    case "object":
      replace((def.objects ??= []), item);
      break;
    case "actor":
      replace((def.actors ??= []), item);
      break;
  }
}

function remove(def: WorldDef, kind: DefKind, id: string): void {
  const without = <T extends { id: string }>(list: T[] | undefined) => (list ?? []).filter((x) => x.id !== id);
  switch (kind) {
    case "room":
      def.rooms = without(def.rooms);
      break;
    case "place":
      def.places = without(def.places);
      break;
    case "archetype":
      def.archetypes = without(def.archetypes);
      break;
    case "object":
      def.objects = without(def.objects);
      break;
    case "actor":
      def.actors = without(def.actors);
      break;
  }
}
