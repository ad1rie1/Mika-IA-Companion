import * as THREE from "three";
import { intentAt } from "./intentTimeline";
import type { Affordance, GestureOut, Intent, Location, PoseOut, Size, Step } from "./protocol.g";
import { buildHinges, type Hinge } from "./RoomHinges";
import { ROOM_OBJECTS } from "./roomBindings";
import type { WorldMirror } from "./WorldMirror";
import type { WorldSession } from "./WorldSession";

/** L'acteur de Mika dans le monde (`contracts.world.MIKA`). */
export const MIKA = "mika";

/** Ce que la scène sait du corps de Mika (le VRM, animé ailleurs). */
export interface MikaBody {
  /** Le creux de sa main, en coordonnées du monde ; null avant le modèle. */
  palm(side: "left" | "right", out: THREE.Vector3): THREE.Vector3 | null;
  /** Ses hanches et sa tête, pour la viser. */
  hips(out: THREE.Vector3): THREE.Vector3 | null;
  head(out: THREE.Vector3): THREE.Vector3 | null;
}

/** Ce que la personne vise : un objet, quelqu'un. */
export interface Focus {
  kind: "object" | "actor";
  id: string;
  label: string;
  point: THREE.Vector3;
}

export interface StageHooks {
  /** Un geste vient d'être montré (celle qui le reçoit y réagit). */
  onGesture?(gesture: GestureOut): void;
  /** Mika en est à un pas « agir » de son action, arrivée : jouer son animation. */
  onMikaAct?(step: Step, affordance: Affordance | undefined): void;
  /** Son corps est-il encore en route (la marche du client) ? Le geste attend qu'elle arrive. */
  mikaMoving?(): boolean;
}

/** La taille d'une silhouette selon la sorte d'objet (l'objet que la pièce ne dessine pas). */
const PLACEHOLDER: Record<Size, [number, number, number]> = {
  hand: [0.12, 0.12, 0.12],
  arms: [0.4, 0.34, 0.3],
  fixed: [0.5, 0.6, 0.5],
};

/** Viser Mika : à cette distance (m) de l'axe hanches–tête. */
const MIKA_RADIUS = 0.24;
/** Une pose reçue vaut ce temps (s) ; au-delà, le corps revient à son lieu. */
const POSE_FRESH_S = 1.5;

interface OtherBody {
  group: THREE.Group;
  /** Déjà posé une fois : il glisse ensuite vers où il va. */
  placed: boolean;
  /** Une pose relayée (une personne qui marche), et quand. */
  pose: { pos: THREE.Vector3; yaw: number; at: number } | null;
  hop: number;
}

/**
 * La scène qui montre le monde : elle lit le miroir (la définition et l'état
 * reçus du noyau) et met chaque chose à sa place — l'état des meubles (porte,
 * fenêtre, armoire ouvertes ou fermées), les objets que la pièce ne dessine
 * pas (une silhouette, là où le monde les dit : au sol près d'un lieu, sur une
 * surface, dans une main), les autres personnages. Le jumeau de `WorldStage`
 * côté Unity, à la mesure d'un écran : elle ne décide rien et n'écrit rien
 * dans le monde.
 *
 * Mika elle-même n'est pas placée ici : son corps suit déjà `inner_state`
 * (lieu, occupation, sommeil) par la conversation — le même état, que le noyau
 * dérive du monde. La scène ne fait que poser ce qu'elle tient dans sa main et
 * jouer l'animation d'un pas « agir » quand elle est arrivée.
 *
 * Une seule pièce est dessinée (celle de room.glb) : ce qui est ailleurs est
 * caché, sans planter (protocole-monde.md § 10).
 */
export class WorldStage {
  private room: THREE.Object3D | null = null;
  private mika: MikaBody | null = null;
  private session: WorldSession | null = null;
  private unsubscribe: (() => void)[] = [];

  private hinges: Hinge[] = [];
  /** Les nœuds de la pièce qui dessinent un objet du monde. */
  private readonly authored = new Map<string, THREE.Object3D[]>();
  private readonly placeholders = new Map<string, THREE.Mesh>();
  private readonly others = new Map<string, OtherBody>();
  /** Qui possède un morceau de la scène (pour viser). */
  private readonly owner = new Map<THREE.Object3D, { kind: "object" | "actor"; id: string }>();
  /** Les objets qu'une définition a nommés (une édition qui en retire un le cache). */
  private readonly everDefined = new Set<string>();
  /** La pièce que room.glb dessine (celle du lieu « center »). */
  private roomId: string | null = null;
  private mikaIntent: { intent: Intent; fired: Set<number> } | null = null;
  private readonly group = new THREE.Group();
  private readonly placeholderMaterial = new THREE.MeshStandardMaterial({
    color: 0xd8c8ff,
    roughness: 0.65,
    metalness: 0,
  });
  private elapsed = 0;

  constructor(
    scene: THREE.Scene,
    private readonly hooks: StageHooks = {}
  ) {
    this.group.name = "Monde (dynamique)";
    scene.add(this.group);
  }

  // ── liaisons ──────────────────────────────────────────────────────

  /** La pièce est chargée (room.glb) : ses battants et ses meubles se relient au monde. */
  bindRoom(root: THREE.Object3D): void {
    this.room = root;
    this.hinges = buildHinges(root);
    this.rebuild();
    this.applyAll(true);
  }

  /** Le modèle de Mika est là : ce qu'elle tient va dans sa main. */
  bindMika(body: MikaBody): void {
    this.mika = body;
    this.applyAll(true);
  }

  bindSession(session: WorldSession): void {
    for (const off of this.unsubscribe) off();
    this.session = session;
    const m = session.mirror;
    this.unsubscribe = [
      m.on("definition", () => {
        this.rebuild();
        this.applyAll(true);
      }),
      m.on("reset", () => this.applyAll(true)),
      m.on("object", (id) => this.applyObject(id, false)),
      m.on("objectRemoved", (id) => this.removeObject(id)),
      m.on("actor", (id) => this.applyActor(id)),
      m.on("intentStarted", (intent) => this.onIntent(intent)),
      m.on("intentEnded", (end) => {
        if (this.mikaIntent?.intent.id === end.intent) this.mikaIntent = null;
        this.applyActor(end.actor);
      }),
      m.on("gesture", (g) => this.onGesture(g)),
      session.on("pose", (p) => this.onPose(p)),
    ];
    if (m.world) this.rebuild();
    if (m.ready) this.applyAll(true);
  }

  private get mirror(): WorldMirror | null {
    return this.session?.mirror ?? null;
  }

  // ── la définition ─────────────────────────────────────────────────

  private rebuild(): void {
    const world = this.mirror?.world;
    if (!world) return;
    this.roomId = world.place("center")?.room ?? world.place(world.actor(MIKA)?.home)?.room ?? world.def.rooms[0]?.id ?? null;

    // Les meubles que la pièce dessine : on les vise ; retirés du monde, on les cache.
    this.owner.clear();
    this.authored.clear();
    if (this.room) {
      for (const [id, names] of Object.entries(ROOM_OBJECTS)) {
        const nodes = names.map((n) => this.room!.getObjectByName(n)).filter((n): n is THREE.Object3D => !!n);
        if (nodes.length === 0) continue;
        const defined = world.object(id) !== undefined;
        if (defined) {
          this.everDefined.add(id);
          this.authored.set(id, nodes);
          for (const n of nodes) this.owner.set(n, { kind: "object", id });
        }
        const visible = defined || !this.everDefined.has(id);
        for (const n of nodes) n.visible = visible;
        for (const h of this.hinges) if (h.object === id) h.pivot.visible = visible;
      }
      for (const h of this.hinges) if (this.authored.has(h.object)) this.owner.set(h.pivot, { kind: "object", id: h.object });
    }

    // Les objets sans dessin : une silhouette chacun.
    for (const [id, mesh] of [...this.placeholders]) {
      if (world.object(id) && !this.authored.has(id)) continue;
      this.disposePlaceholder(id, mesh);
    }
    for (const def of world.def.objects ?? []) {
      if (this.authored.has(def.id) || this.placeholders.has(def.id)) continue;
      const [w, h, d] = PLACEHOLDER[world.archetype(def.archetype)?.size ?? "fixed"];
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), this.placeholderMaterial);
      mesh.name = `Objet ${def.id} (silhouette)`;
      mesh.castShadow = true;
      mesh.visible = false;
      this.group.add(mesh);
      this.placeholders.set(def.id, mesh);
    }
    for (const [id, mesh] of this.placeholders) this.owner.set(mesh, { kind: "object", id });

    // Les personnages déclarés (sauf elle) : une silhouette chacun.
    for (const def of world.def.actors) if (def.id !== MIKA) this.ensureOther(def.id);
    for (const [id, body] of this.others) this.owner.set(body.group, { kind: "actor", id });
  }

  private disposePlaceholder(id: string, mesh: THREE.Mesh): void {
    mesh.removeFromParent();
    mesh.geometry.dispose();
    this.placeholders.delete(id);
  }

  // ── l'état ────────────────────────────────────────────────────────

  private applyAll(instant: boolean): void {
    const m = this.mirror;
    if (!m?.ready) return;
    for (const id of m.objects.keys()) this.applyObject(id, instant);
    for (const id of m.actors.keys()) this.applyActor(id);
    for (const intent of m.intents.values()) this.onIntent(intent);
  }

  private applyObject(id: string, instant: boolean): void {
    const m = this.mirror;
    const state = m?.object(id);
    if (!m?.world || !state) return;
    const value = state.state ?? m.world.archetypeOf(id)?.initial_state ?? null;
    for (const h of this.hinges) if (h.object === id) h.apply(value, instant);
    const mesh = this.placeholders.get(id);
    if (mesh) this.placeObject(mesh, id, state.location);
  }

  private removeObject(id: string): void {
    const mesh = this.placeholders.get(id);
    if (mesh) mesh.visible = false;
  }

  /** Met une silhouette là où le monde dit qu'est l'objet (une main se suit à chaque image). */
  private placeObject(mesh: THREE.Mesh, id: string, location: Location): void {
    const m = this.mirror!;
    const inRoom = m.roomOfObject(id) === this.roomId;
    mesh.userData.held = null;
    switch (location.kind) {
      case "held": {
        // La personne de ce poste n'a pas de corps ici : ce qu'elle tient ne se voit pas.
        const local = location.actor === this.session?.actor;
        mesh.visible = !local && inRoom;
        mesh.userData.held = { actor: location.actor, hand: location.hand ?? "right" };
        break;
      }
      case "in":
        mesh.visible = false; // rangé dedans : on ne le voit pas
        break;
      case "on": {
        const top = this.surfacePoint(location.object, location.slot);
        mesh.visible = inRoom && top !== null;
        if (top) mesh.position.set(top.x, top.y + halfHeight(mesh), top.z);
        break;
      }
      case "room": {
        const near = this.nearPlace(location.near);
        mesh.visible = inRoom && near !== null;
        if (near) mesh.position.set(near.x, halfHeight(mesh), near.z);
        break;
      }
    }
  }

  /** Le dessus d'un meuble, à sa place n° `slot` (réparties le long de son grand côté). */
  private surfacePoint(objectId: string, slot: number): THREE.Vector3 | null {
    const world = this.mirror?.world;
    const node = this.authored.get(objectId)?.[0] ?? this.placeholders.get(objectId);
    if (!world || !node) return null;
    const box = new THREE.Box3().setFromObject(node);
    if (box.isEmpty()) return null;
    const n = Math.max(1, world.archetypeOf(objectId)?.surface_slots ?? 1);
    const f = (Math.min(Math.max(slot, 0), n - 1) + 0.5) / n;
    const sx = box.max.x - box.min.x;
    const sz = box.max.z - box.min.z;
    const x = sx >= sz ? box.min.x + sx * f : (box.min.x + box.max.x) / 2;
    const z = sx >= sz ? (box.min.z + box.max.z) / 2 : box.min.z + sz * f;
    return new THREE.Vector3(x, box.max.y + 0.005, z);
  }

  /** Au sol près d'un lieu : un pas devant lui, un peu à droite (comme Unity le pose). */
  private nearPlace(placeId: string | null | undefined): THREE.Vector3 | null {
    const place = this.mirror?.world?.place(placeId);
    if (!place || place.room !== this.roomId) return null;
    const phi = place.facing ?? 0;
    const right = { x: -Math.cos(phi), z: Math.sin(phi) };
    const forward = { x: Math.sin(phi), z: Math.cos(phi) };
    return new THREE.Vector3(place.pos.x + 0.25 * right.x + 0.45 * forward.x, 0, place.pos.z + 0.25 * right.z + 0.45 * forward.z);
  }

  // ── les autres personnages ────────────────────────────────────────

  private ensureOther(id: string): OtherBody {
    let body = this.others.get(id);
    if (body) return body;
    const group = new THREE.Group();
    group.name = `Acteur ${id}`;
    const color = id.startsWith("player:") ? 0xa9d6ff : 0xffcfae;
    const material = new THREE.MeshStandardMaterial({ color, roughness: 0.7 });
    const trunk = new THREE.Mesh(new THREE.CapsuleGeometry(0.19, 0.75, 6, 12), material);
    trunk.position.y = 0.6;
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.15, 16, 12), material);
    head.position.y = 1.33;
    for (const part of [trunk, head]) {
      part.castShadow = true;
      group.add(part);
    }
    group.visible = false;
    this.group.add(group);
    body = { group, placed: false, pose: null, hop: 0 };
    this.others.set(id, body);
    this.owner.set(group, { kind: "actor", id });
    return body;
  }

  private applyActor(id: string): void {
    if (id === MIKA) {
      // Ce qu'elle tient suit sa main ; ce qu'elle a lâché retrouve sa place.
      for (const [objectId, mesh] of this.placeholders) {
        const state = this.mirror?.object(objectId);
        if (state) this.placeObject(mesh, objectId, state.location);
      }
      return;
    }
    const state = this.mirror?.actor(id);
    if (id === this.session?.actor) return; // la personne de ce poste n'a pas de corps ici
    if (!state) {
      const gone = this.others.get(id);
      if (gone) {
        gone.group.removeFromParent();
        this.others.delete(id);
        this.owner.delete(gone.group);
      }
      return;
    }
    this.ensureOther(id);
  }

  private onPose(pose: PoseOut): void {
    if (pose.actor === this.session?.actor || pose.actor === MIKA) return;
    if (!this.mirror?.actor(pose.actor)) return; // pas (encore) dans le monde : rien à montrer
    const body = this.ensureOther(pose.actor);
    body.pose = { pos: new THREE.Vector3(pose.pos.x, pose.pos.y, pose.pos.z), yaw: pose.yaw, at: this.elapsed };
  }

  /** Où est un autre personnage maintenant : sur son trajet, à sa pose relayée, à son lieu. */
  private whereIs(id: string, body: OtherBody): { pos: THREE.Vector3; yaw: number; posture: string } | null {
    const m = this.mirror;
    const state = m?.actor(id);
    if (!m?.world || !state || state.room !== this.roomId) return null;
    const posture = state.posture ?? "stand";
    if (body.pose && this.elapsed - body.pose.at < POSE_FRESH_S) return { pos: body.pose.pos, yaw: body.pose.yaw, posture };
    const intent = m.intentOf(id);
    const clock = this.session?.clock;
    let place = m.world.place(state.place);
    if (intent && clock?.isSynced) {
      const at = intentAt(intent, clock.nowUs);
      let from = place;
      for (let i = 0; i < intent.steps.length; i++) {
        const s = intent.steps[i];
        if (s.kind !== "walk") continue;
        const to = m.world.place(s.to_place);
        if (i < at.step) {
          from = to ?? from;
          continue;
        }
        if (i === at.step && from && to) {
          const k = at.fraction;
          const pos = new THREE.Vector3(
            from.pos.x + (to.pos.x - from.pos.x) * k,
            0,
            from.pos.z + (to.pos.z - from.pos.z) * k
          );
          return { pos, yaw: Math.atan2(to.pos.x - from.pos.x, to.pos.z - from.pos.z), posture: "stand" };
        }
        break;
      }
      place = from;
    }
    if (!place) return null;
    return { pos: new THREE.Vector3(place.pos.x, 0, place.pos.z), yaw: place.facing ?? 0, posture };
  }

  // ── les actions et les gestes ─────────────────────────────────────

  private onIntent(intent: Intent): void {
    if (intent.actor === MIKA && this.mikaIntent?.intent.id !== intent.id) {
      this.mikaIntent = { intent, fired: new Set() };
    }
  }

  private onGesture(g: GestureOut): void {
    const body = this.others.get(g.actor);
    if (body) body.hop = 0.45;
    this.hooks.onGesture?.(g);
  }

  /** Les pas « agir » de son action, une fois arrivée là où ils se jouent. */
  private cueMikaActs(): void {
    const current = this.mikaIntent;
    const clock = this.session?.clock;
    const world = this.mirror?.world;
    if (!current || !clock?.isSynced || !world || this.hooks.mikaMoving?.()) return;
    const at = intentAt(current.intent, clock.nowUs);
    for (let i = 0; i <= Math.min(at.step, current.intent.steps.length - 1); i++) {
      const step = current.intent.steps[i];
      if (step.kind !== "act" || current.fired.has(i)) continue;
      current.fired.add(i);
      const affordance = world.archetypeOf(step.object)?.affordances?.find((a) => a.id === step.action);
      this.hooks.onMikaAct?.(step, affordance);
    }
  }

  // ── chaque image ──────────────────────────────────────────────────

  update(dt: number): void {
    this.elapsed += dt;
    for (const h of this.hinges) h.update(dt);
    this.cueMikaActs();
    // Ce qu'une main tient la suit.
    const palm = new THREE.Vector3();
    for (const mesh of this.placeholders.values()) {
      const held = mesh.userData.held as { actor: string; hand: string } | null;
      if (!held || !mesh.visible) continue;
      const side = held.hand === "left" ? "left" : "right";
      if (held.actor === MIKA) {
        if (this.mika?.palm(side, palm)) mesh.position.copy(palm);
      } else {
        const other = this.others.get(held.actor)?.group;
        if (other) mesh.position.copy(other.position).add(new THREE.Vector3(0, 0.95, 0));
      }
    }
    const k = 1 - Math.exp(-dt * 10);
    for (const [id, body] of this.others) {
      const where = this.whereIs(id, body);
      body.group.visible = where !== null;
      if (!where) {
        body.placed = false;
        continue;
      }
      const lower = where.posture === "sit" ? 0.35 : where.posture === "lie" ? 0.55 : 0;
      const hop = body.hop > 0 ? Math.sin((1 - body.hop / 0.45) * Math.PI) * 0.06 : 0;
      body.hop = Math.max(0, body.hop - dt);
      const target = where.pos.clone().setY(where.pos.y - lower + hop);
      if (body.placed) body.group.position.lerp(target, k);
      else body.group.position.copy(target);
      body.placed = true;
      body.group.rotation.set(where.posture === "lie" ? -Math.PI / 2 : 0, where.yaw, 0, "YXZ");
    }
  }

  // ── viser ─────────────────────────────────────────────────────────

  /**
   * Ce que vise un rayon (le pointeur) : ce qu'il rencontre d'abord dans la
   * pièce. Un mur, un meuble qui n'est pas du monde arrêtent le rayon — on ne
   * vise pas le ciel au travers du mur.
   */
  pick(raycaster: THREE.Raycaster): Focus | null {
    const m = this.mirror;
    if (!m?.world) return null;
    const roots = [this.room, this.group].filter((r): r is THREE.Object3D => r !== null);
    let best: Focus | null = null;
    let bestDistance = Infinity;
    for (const hit of raycaster.intersectObjects(roots, true)) {
      if (!(hit.object as THREE.Mesh).isMesh || !shown(hit.object)) continue;
      const who = this.ownerOf(hit.object);
      if (who) best = { ...who, label: this.labelOf(who.kind, who.id), point: hit.point.clone() };
      bestDistance = hit.distance;
      break;
    }
    // Mika : un cylindre autour de l'axe hanches–tête (son modèle animé coûterait trop à viser).
    const hips = this.mika?.hips(new THREE.Vector3());
    const head = this.mika?.head(new THREE.Vector3());
    if (hips && head && m.world.actor(MIKA)) {
      const onRay = new THREE.Vector3();
      const d2 = raycaster.ray.distanceSqToSegment(hips, head, onRay);
      if (d2 < MIKA_RADIUS * MIKA_RADIUS && onRay.distanceTo(raycaster.ray.origin) < bestDistance) {
        best = { kind: "actor", id: MIKA, label: this.labelOf("actor", MIKA), point: onRay };
      }
    }
    return best;
  }

  private ownerOf(obj: THREE.Object3D): { kind: "object" | "actor"; id: string } | null {
    for (let o: THREE.Object3D | null = obj; o; o = o.parent) {
      const who = this.owner.get(o);
      if (who) return who;
    }
    return null;
  }

  labelOf(kind: "object" | "actor", id: string): string {
    const m = this.mirror;
    if (!m?.world) return id;
    if (kind === "object") return m.world.labelOf(id);
    return m.world.actor(id)?.label || m.visitors.get(id)?.label || id;
  }
}

function halfHeight(mesh: THREE.Mesh): number {
  const g = mesh.geometry as THREE.BoxGeometry;
  return (g.parameters?.height ?? 0.1) / 2;
}

/** Visible, lui et tous ses parents (un meuble retiré du monde ne se vise plus). */
function shown(obj: THREE.Object3D): boolean {
  for (let o: THREE.Object3D | null = obj; o; o = o.parent) if (!o.visible) return false;
  return true;
}
