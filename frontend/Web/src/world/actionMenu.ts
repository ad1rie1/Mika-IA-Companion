import type { Act, Address, Describe, Edit, Moved, Reply, Report } from "./protocol.g";
import type { WorldMirror } from "./WorldMirror";

type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;

/** Les trames qui attendent un accusé (`result`). */
export type CommandFrame = Act | Moved | Address | Reply | Report | Edit | Describe;
/** Une commande avant l'envoi : son `cmd` est fixé par la session. */
export type CommandDraft = DistributiveOmit<CommandFrame, "cmd">;

/** Une chose que la personne peut faire là, maintenant : ce qu'on lui affiche, et la commande qui part. */
export interface ActionOption {
  label: string;
  command: CommandDraft;
  /** Le geste par défaut (le premier proposé). */
  primary: boolean;
}

/**
 * Ce qu'une personne peut tenter sur ce qu'elle regarde, déduit de la
 * définition et de l'état reçus. C'est un menu, pas une validation : le noyau
 * reste seul juge (et dit pourquoi il refuse). On n'y propose que ce qui a
 * une chance raisonnable de passer, pour ne pas faire choisir l'impossible.
 * (Le jumeau de `Mika.World.Model.ActionMenu` côté Unity, mêmes libellés.)
 */
export function handsBusy(mirror: WorldMirror, actor: string | null): number {
  const me = mirror.actor(actor);
  if (!me) return 0;
  let n = 0;
  for (const held of me.holding) n += mirror.world?.archetypeOf(held)?.size === "arms" ? 2 : 1;
  return n;
}

/** Les actions possibles sur un objet. */
export function forObject(mirror: WorldMirror, actor: string | null, objectId: string): ActionOption[] {
  const options: ActionOption[] = [];
  const world = mirror.world;
  const def = world?.object(objectId);
  const state = mirror.object(objectId);
  if (!world || !def || !state) return options;
  const archetype = world.archetype(def.archetype);
  const label = def.label || archetype?.label || objectId;
  const holder = mirror.holderOf(objectId);
  const me = mirror.actor(actor);
  const myHeld = me?.holding[0];
  const busy = handsBusy(mirror, actor);
  const add = (labelText: string, command: CommandDraft, primary = options.length === 0) =>
    options.push({ label: labelText, command, primary });

  const size = archetype?.size ?? "fixed";
  if (archetype && size !== "fixed") {
    if (holder === undefined && busy + (size === "arms" ? 2 : 1) <= 2) {
      add(`Prendre ${label}`, { type: "act", action: "take", object: objectId }, true);
    } else if (holder !== undefined && holder !== actor) {
      add(`Le demander (${label})`, { type: "address", to: holder, request: "ask", object: objectId }, false);
    } else if (holder !== undefined && holder === actor) {
      add(`Lâcher ${label}`, { type: "act", action: "drop", object: objectId }, false);
    }
  }

  if (myHeld !== undefined && myHeld !== objectId && archetype) {
    const heldLabel = world.labelOf(myHeld);
    const slot = freeSlot(mirror, objectId, archetype.surface_slots ?? 0);
    if (slot >= 0) {
      add(`Poser ${heldLabel} ici`, {
        type: "act",
        action: "put",
        object: myHeld,
        target: { kind: "on", object: objectId, slot },
      });
    } else if ((archetype.container_slots ?? 0) > 0 && contained(mirror, objectId) < (archetype.container_slots ?? 0)) {
      add(`Ranger ${heldLabel} dedans`, {
        type: "act",
        action: "put",
        object: myHeld,
        target: { kind: "in", object: objectId },
      }, false);
    }
  }

  const current = state.state ?? archetype?.initial_state ?? null;
  for (const a of archetype?.affordances ?? []) {
    if (a.requires_state && a.requires_state.length > 0 && (current === null || !a.requires_state.includes(current))) {
      continue;
    }
    if (a.held && holder !== actor) continue;
    add(capitalize(a.label), { type: "act", action: a.id, object: objectId });
  }

  for (const place of world.def.places ?? []) {
    if (place.of_object !== objectId) continue;
    const kind = place.place_kind ?? "spot";
    if (kind === "seat" || kind === "bed") add("S'asseoir", { type: "act", action: "sit", place: place.id });
    if (kind === "bed") add("S'allonger", { type: "act", action: "lie", place: place.id }, false);
  }
  return options;
}

/** Ce qu'on peut faire envers quelqu'un (Mika, une autre personne) : des gestes, des demandes. */
export function forActor(mirror: WorldMirror, actor: string | null, other: string | null): ActionOption[] {
  const options: ActionOption[] = [];
  if (!other || other === actor) return options;
  const me = mirror.actor(actor);
  const them = mirror.actor(other);
  const world = mirror.world;
  const labelOf = (id: string) => world?.labelOf(id) ?? id;
  const add = (label: string, command: CommandDraft, primary = false) => options.push({ label, command, primary });
  add("Faire coucou", { type: "address", to: other, gesture: "wave" }, true);
  const myHeld = me?.holding[0];
  if (myHeld !== undefined) {
    add(`Lui tendre ${labelOf(myHeld)}`, { type: "address", to: other, request: "offer", object: myHeld });
  }
  const theirHeld = them?.holding[0];
  if (theirHeld !== undefined) {
    add(`Lui demander ${labelOf(theirHeld)}`, { type: "address", to: other, request: "ask", object: theirHeld });
  }
  add("Lui faire un câlin", { type: "address", to: other, request: "hug" });
  add("Tope là", { type: "address", to: other, request: "high_five" });
  add("Lui prendre la main", { type: "address", to: other, request: "hold_hand" });
  add("Lui caresser la tête", { type: "address", to: other, gesture: "pat_head" });
  add("Hocher la tête", { type: "address", to: other, gesture: "nod" });
  add("Applaudir", { type: "address", to: other, gesture: "clap" });
  add("La taquiner (pousser du doigt)", { type: "address", to: other, gesture: "poke" });
  return options;
}

/** Ce que la personne peut faire d'elle-même (sans cible) : se lever, lâcher ce qu'elle tient. */
export function forSelf(mirror: WorldMirror, actor: string | null): ActionOption[] {
  const options: ActionOption[] = [];
  const me = mirror.actor(actor);
  if (!me) return options;
  if ((me.posture ?? "stand") !== "stand") {
    options.push({ label: "Se lever", command: { type: "act", action: "stand" }, primary: true });
  }
  for (const held of me.holding) {
    options.push({
      label: `Lâcher ${mirror.world?.labelOf(held) ?? held}`,
      command: { type: "act", action: "drop", object: held },
      primary: false,
    });
  }
  return options;
}

/** La première place libre d'une surface, -1 s'il n'y en a pas. */
export function freeSlot(mirror: WorldMirror, surfaceId: string, slots: number): number {
  if (slots <= 0) return -1;
  const taken = new Set<number>();
  for (const o of mirror.objects.values()) {
    if (o.location.kind === "on" && o.location.object === surfaceId) taken.add(o.location.slot);
  }
  for (let i = 0; i < slots; i++) if (!taken.has(i)) return i;
  return -1;
}

function contained(mirror: WorldMirror, containerId: string): number {
  let n = 0;
  for (const o of mirror.objects.values()) if (o.location.kind === "in" && o.location.object === containerId) n++;
  return n;
}

function capitalize(s: string): string {
  return s ? s[0].toLocaleUpperCase("fr") + s.slice(1) : s;
}
