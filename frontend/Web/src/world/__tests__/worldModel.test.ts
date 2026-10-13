import { describe, expect, it } from "vitest";
import spec from "../../../../../backendv2/docs/protocole-monde.md?raw";
import exampleWorld from "../../../../../backendv2/examples/monde/chambre.json?raw";
import defaultWorld from "../../../../../backendv2/src/mika/faculties/world/chambre.json?raw";
import { forActor, forObject, forSelf, freeSlot } from "../actionMenu";
import { intentAt, intentDone } from "../intentTimeline";
import { CLIENT_FRAME_TYPES, type Intent, type ServerFrame, type WorldDef } from "../protocol.g";
import { readServer } from "../wire";
import { WorldMirror } from "../WorldMirror";

const EXAMPLES = [...spec.matchAll(/```json (client|serveur)\n([\s\S]*?)```/g)].map((m) => ({
  side: m[1],
  json: m[2],
}));

function world(text: string): WorldDef {
  return JSON.parse(text) as WorldDef;
}

function frame(json: string): ServerFrame {
  const read = readServer(json);
  if (!read.frame) throw new Error(read.error);
  return read.frame;
}

/** Le monde d'exemple, Mika au milieu de sa chambre, la tasse posée près du bureau. */
function ready(def: WorldDef = world(exampleWorld)): WorldMirror {
  const mirror = new WorldMirror();
  mirror.apply({ type: "definition", world: def });
  mirror.apply(
    frame(`{"type": "snapshot", "state": {"rev": 0, "seq": 100,
      "actors": [{"id": "mika", "room": "bedroom", "place": "center"}],
      "objects": [{"id": "mug", "location": {"kind": "room", "room": "bedroom", "near": "desk"}},
                  {"id": "window_pane", "location": {"kind": "room", "room": "bedroom", "near": "window"}},
                  {"id": "plant", "location": {"kind": "room", "room": "bedroom", "near": "window"}},
                  {"id": "shelves", "location": {"kind": "room", "room": "bedroom", "near": "bookshelf"}},
                  {"id": "petit_prince", "location": {"kind": "on", "object": "shelves", "slot": 0}}]}}`)
  );
  return mirror;
}

/** Un monde où chaque chose est à sa place de départ (ce que le noyau pose au premier démarrage). */
function atHome(def: WorldDef): WorldMirror {
  const mirror = new WorldMirror();
  mirror.apply({ type: "definition", world: def });
  mirror.apply({
    type: "snapshot",
    state: {
      rev: def.rev ?? 0,
      seq: 1,
      actors: [{ id: "mika", room: "bedroom", place: "center" }],
      objects: (def.objects ?? []).map((o) => ({ id: o.id, location: o.home, state: o.state ?? null })),
    },
  });
  return mirror;
}

describe("le fil du monde", () => {
  it("la spécification a des exemples des deux côtés", () => {
    expect(EXAMPLES.filter((e) => e.side === "client").length).toBeGreaterThanOrEqual(10);
    expect(EXAMPLES.filter((e) => e.side === "serveur").length).toBeGreaterThanOrEqual(10);
  });

  it("chaque trame du noyau de la spécification se reconnaît", () => {
    for (const { json } of EXAMPLES.filter((e) => e.side === "serveur")) {
      const read = readServer(json);
      expect(read.frame, json).not.toBeNull();
      expect(read.frame!.type).toBe(JSON.parse(json).type);
    }
  });

  it("chaque commande de la spécification est d'un type connu", () => {
    for (const { json } of EXAMPLES.filter((e) => e.side === "client")) {
      expect(CLIENT_FRAME_TYPES as readonly string[]).toContain(JSON.parse(json).type);
    }
  });

  it("une trame d'un type inconnu est signalée sans planter", () => {
    const read = readServer('{"type": "teleport", "seq": 12}');
    expect(read.frame).toBeNull();
    expect(read.error).toContain("teleport");
    expect(read.seq).toBe(12);
    expect(readServer("pas du JSON").frame).toBeNull();
    expect(readServer("[1, 2]").frame).toBeNull();
  });

  it("les mondes du noyau se lisent", () => {
    for (const text of [exampleWorld, defaultWorld]) {
      const def = world(text);
      expect(def.places.map((p) => p.id)).toEqual(
        expect.arrayContaining(["center", "window", "desk", "bed", "bookshelf", "door"])
      );
      expect(def.actors.some((a) => a.id === "mika")).toBe(true);
    }
  });
});

describe("le miroir du monde", () => {
  it("rien n'est appliqué avant l'instantané", () => {
    const mirror = new WorldMirror();
    expect(mirror.apply({ type: "delta", seq: 3, at: 0, cause: { source: "kernel" }, changes: [] })).toBe("not_ready");
  });

  it("une action terminée déplace l'acteur et ce qu'il prend", () => {
    const mirror = ready();
    const started: string[] = [];
    mirror.on("intentStarted", (i) => started.push(i.id));
    mirror.apply({
      type: "intent",
      seq: 101,
      intent: {
        id: "i-101",
        actor: "mika",
        started: 0,
        eta: 10,
        deadline: 20,
        cause: { source: "mika" },
        steps: [{ kind: "walk", to_room: "bedroom", to_place: "desk", duration_us: 5_000_000 }],
      },
    });
    expect(started).toEqual(["i-101"]);
    expect(mirror.intentOf("mika")).toBeDefined();

    mirror.apply({
      type: "intent_end",
      seq: 104,
      intent: "i-101",
      actor: "mika",
      outcome: "done",
      changes: [
        { kind: "actor_moved", actor: "mika", room: "bedroom", place: "desk", posture: "sit" },
        { kind: "object_moved", object: "mug", to: { kind: "held", actor: "mika", hand: "right" } },
      ],
    });
    expect(mirror.intentOf("mika")).toBeUndefined();
    expect(mirror.actor("mika")!.place).toBe("desk");
    expect(mirror.actor("mika")!.posture).toBe("sit");
    expect(mirror.actor("mika")!.holding).toEqual(["mug"]);
    expect(mirror.holderOf("mug")).toBe("mika");
    expect(mirror.roomOfObject("mug")).toBe("bedroom");
    expect(mirror.seq).toBe(104);
  });

  it("une action qui commence arrache l'acteur à son occupation", () => {
    const mirror = ready();
    mirror.apply({
      type: "delta",
      seq: 101,
      at: 0,
      cause: { source: "mika" },
      changes: [{ kind: "actor_activity", actor: "mika", activity: { name: "read", since: 0 } }],
    });
    expect(mirror.actor("mika")!.activity?.name).toBe("read");
    const changed: string[] = [];
    mirror.on("actor", (id) => changed.push(id));
    mirror.apply({
      type: "intent",
      seq: 102,
      intent: { id: "i-102", actor: "mika", started: 0, eta: 1, deadline: 2, cause: { source: "mika" }, steps: [] },
    });
    expect(mirror.actor("mika")!.activity).toBeNull();
    expect(changed).toEqual(["mika"]);
  });

  it("une trame déjà vue est ignorée", () => {
    const mirror = ready();
    const effect = mirror.apply({
      type: "delta",
      seq: 100,
      at: 0,
      cause: { source: "kernel" },
      changes: [{ kind: "object_state", object: "mug", state: "empty" }],
    });
    expect(effect).toBe("duplicate");
    expect(mirror.object("mug")!.state).toBeUndefined();
  });

  it("poser un objet le retire de la main", () => {
    const mirror = ready();
    mirror.apply({
      type: "delta",
      seq: 101,
      at: 0,
      cause: { source: "mika" },
      changes: [{ kind: "object_moved", object: "mug", to: { kind: "held", actor: "mika" } }],
    });
    mirror.apply({
      type: "delta",
      seq: 102,
      at: 0,
      cause: { source: "mika" },
      changes: [{ kind: "object_moved", object: "mug", to: { kind: "on", object: "writing_desk", slot: 0 } }],
    });
    expect(mirror.actor("mika")!.holding).toEqual([]);
    expect(mirror.roomOfObject("mug")).toBe("bedroom");
  });

  it("un objet consommé quitte la main qui le tenait", () => {
    const mirror = ready();
    const removed: string[] = [];
    mirror.on("objectRemoved", (id) => removed.push(id));
    mirror.apply({
      type: "delta",
      seq: 101,
      at: 0,
      cause: { source: "mika" },
      changes: [
        { kind: "object_moved", object: "mug", to: { kind: "held", actor: "mika" } },
        { kind: "object_gone", object: "mug" },
      ],
    });
    expect(mirror.object("mug")).toBeUndefined();
    expect(mirror.actor("mika")!.holding).toEqual([]);
    expect(removed).toEqual(["mug"]);
  });

  it("une personne entre et sort", () => {
    const mirror = ready();
    mirror.apply({ type: "presence", seq: 101, actor: "player:user_1", joined: true, room: "bedroom", place: "door", label: "Adrien" });
    expect(mirror.visitors.get("player:user_1")!.label).toBe("Adrien");
    expect(mirror.actor("player:user_1")!.place).toBe("door");
    mirror.apply({ type: "presence", seq: 102, actor: "player:user_1", joined: false });
    expect(mirror.actor("player:user_1")).toBeUndefined();
  });

  it("une édition remplace ou retire", () => {
    const mirror = ready();
    const rev = mirror.world!.rev;
    let rebuilt = 0;
    mirror.on("definition", () => rebuilt++);
    mirror.apply({
      type: "definition_delta",
      seq: 101,
      base: rev,
      rev: rev + 1,
      changes: [
        { op: "remove", of: "object", id: "mug" },
        { op: "put", item: { kind: "room", id: "attic", label: "le grenier" } },
      ],
    });
    expect(mirror.world!.rev).toBe(rev + 1);
    expect(mirror.world!.object("mug")).toBeUndefined();
    expect(mirror.world!.room("attic")!.label).toBe("le grenier");
    expect(rebuilt).toBe(1);
  });

  it("un abonné qui lève ne laisse pas le miroir à moitié appliqué", () => {
    const mirror = ready();
    mirror.on("object", () => {
      throw new Error("vue cassée");
    });
    mirror.apply({
      type: "delta",
      seq: 101,
      at: 0,
      cause: { source: "mika" },
      changes: [
        { kind: "object_state", object: "window_pane", state: "open" },
        { kind: "object_state", object: "plant", state: "watered" },
      ],
    });
    expect(mirror.object("window_pane")!.state).toBe("open");
    expect(mirror.object("plant")!.state).toBe("watered");
    expect(mirror.seq).toBe(101);
  });

  it("le calendrier d'une action place l'acteur sur son trajet", () => {
    const intent: Intent = {
      id: "i",
      actor: "mika",
      started: 1_000_000,
      eta: 0,
      deadline: 0,
      cause: { source: "mika" },
      steps: [
        { kind: "posture", posture: "stand", duration_us: 1_000_000 },
        { kind: "walk", duration_us: 4_000_000 },
      ],
    };
    const p = intentAt(intent, 3_000_000);
    expect(p.step).toBe(1);
    expect(p.fraction).toBeCloseTo(0.25, 9);
    expect(intentDone(intent, intentAt(intent, 9_000_000))).toBe(true);
  });
});

describe("le menu des actions", () => {
  const me = "player:user_1";

  it("une fenêtre fermée s'ouvre et se regarde, elle ne se prend pas", () => {
    const mirror = ready();
    const labels = forObject(mirror, me, "window_pane").map((o) => o.label);
    expect(labels).toEqual(["Ouvrir", "Regarder dehors"]);
    expect(forObject(mirror, me, "window_pane")[0].primary).toBe(true);
  });

  it("ouverte, elle se ferme", () => {
    const mirror = ready();
    mirror.apply({
      type: "delta",
      seq: 101,
      at: 0,
      cause: { source: "mika" },
      changes: [{ kind: "object_state", object: "window_pane", state: "open" }],
    });
    expect(forObject(mirror, me, "window_pane").map((o) => o.label)).toEqual(["Fermer", "Regarder dehors"]);
  });

  it("ce qui se porte se prend ; ce qu'elle tient se demande", () => {
    const mirror = ready();
    expect(forObject(mirror, me, "plant")[0]).toMatchObject({
      label: "Prendre ta plante",
      primary: true,
      command: { type: "act", action: "take", object: "plant" },
    });
    mirror.apply({
      type: "delta",
      seq: 101,
      at: 0,
      cause: { source: "mika" },
      changes: [{ kind: "object_moved", object: "plant", to: { kind: "held", actor: "mika", hand: "both" } }],
    });
    expect(forObject(mirror, me, "plant")[0]).toMatchObject({
      label: "Le demander (ta plante)",
      command: { type: "address", to: "mika", request: "ask", object: "plant" },
    });
  });

  it("une place prise sur une surface ne se propose pas", () => {
    const mirror = ready();
    expect(freeSlot(mirror, "shelves", 6)).toBe(1);
    expect(freeSlot(mirror, "shelves", 0)).toBe(-1);
  });

  it("le lit s'assied et s'allonge", () => {
    const mirror = atHome(world(defaultWorld));
    expect(forObject(mirror, me, "bed_frame").map((o) => o.label)).toEqual(["S'asseoir", "S'allonger"]);
  });

  it("envers Mika : un coucou d'abord, puis les demandes et les gestes", () => {
    const mirror = ready();
    const options = forActor(mirror, me, "mika");
    expect(options[0]).toMatchObject({ label: "Faire coucou", primary: true, command: { type: "address", to: "mika", gesture: "wave" } });
    expect(options.map((o) => o.label)).toContain("Lui caresser la tête");
    expect(forActor(mirror, me, me)).toEqual([]);
  });

  it("sans corps dans le monde, rien à faire de soi-même", () => {
    expect(forSelf(ready(), me)).toEqual([]);
  });
});
