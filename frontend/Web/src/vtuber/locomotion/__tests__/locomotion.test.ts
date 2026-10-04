import * as THREE from "three";
import { describe, expect, it } from "vitest";
import {
  BODY_RADIUS,
  OBSTACLES,
  PLACES,
  PLACE_IDS,
  ROOM_BOUNDS,
  isPlaceId,
  planPath,
  segmentHitsRect,
  type PlaceId,
  type Posture,
  type Vec2,
} from "../roomLayout";
import { LocomotionController } from "../LocomotionController";
import { CHAIR_BACK, pulledSeat, seatEntry } from "../roomLayout";

const inflated = OBSTACLES.map((r) => ({
  minX: r.minX - BODY_RADIUS + 0.01,
  minZ: r.minZ - BODY_RADIUS + 0.01,
  maxX: r.maxX + BODY_RADIUS - 0.01,
  maxZ: r.maxZ + BODY_RADIUS - 0.01,
}));

function clearPath(from: Vec2, path: Vec2[]): boolean {
  let a = from;
  for (const b of path) {
    if (inflated.some((r) => segmentHitsRect(a, b, r))) return false;
    a = b;
  }
  return true;
}

describe("room layout", () => {
  it("knows its places and nothing else", () => {
    for (const id of PLACE_IDS) expect(isPlaceId(id)).toBe(true);
    for (const bad of ["garden", "", "DESK", null, 3, undefined]) expect(isPlaceId(bad)).toBe(false);
  });

  it("every place is reachable floor: inside the room, outside the furniture", () => {
    for (const id of PLACE_IDS) {
      const a = PLACES[id].approach;
      expect(a.x).toBeGreaterThanOrEqual(ROOM_BOUNDS.minX);
      expect(a.x).toBeLessThanOrEqual(ROOM_BOUNDS.maxX);
      expect(a.z).toBeGreaterThanOrEqual(ROOM_BOUNDS.minZ);
      expect(a.z).toBeLessThanOrEqual(ROOM_BOUNDS.maxZ);
      for (const r of inflated) {
        const inside = a.x > r.minX && a.x < r.maxX && a.z > r.minZ && a.z < r.maxZ;
        expect(inside, `${id} approach inside an obstacle`).toBe(false);
      }
    }
  });

  it("goes straight when nothing is in the way", () => {
    expect(planPath(PLACES.center.approach, PLACES.door.approach)).toEqual([PLACES.door.approach]);
  });

  it("walks around the bed rather than through it", () => {
    const from = PLACES.window.approach;
    const to = PLACES.bed.approach;
    expect(inflated.some((r) => segmentHitsRect(from, to, r))).toBe(true); // the straight line is blocked
    const path = planPath(from, to);
    expect(path.length).toBeGreaterThan(1);
    expect(path[path.length - 1]).toEqual(to);
    expect(clearPath(from, path)).toBe(true);
  });

  it("every trip between two places is collision-free", () => {
    for (const a of PLACE_IDS) {
      for (const b of PLACE_IDS) {
        if (a === b) continue;
        const path = planPath(PLACES[a].approach, PLACES[b].approach);
        expect(clearPath(PLACES[a].approach, path), `${a} → ${b}`).toBe(true);
      }
    }
  });
});

function stage(opts: { sleep?: "awake" | "deep_sleep" } = {}) {
  const root = new THREE.Object3D();
  root.position.set(0, 0, -0.5);
  root.rotation.y = Math.PI; // a VRM 0.x root
  const log = { walk: [] as Array<number | null>, posture: [] as Posture[] };
  const loco = new LocomotionController({
    root,
    baseYaw: Math.PI,
    hipsHeight: 0.75,
    body: {
      walk: (ts) => log.walk.push(ts),
      posture: (p) => log.posture.push(p),
    },
  });
  if (opts.sleep) loco.setSleepPhase(opts.sleep);
  const run = (seconds: number) => {
    for (let t = 0; t < seconds; t += 1 / 30) loco.update(1 / 30);
  };
  const floor = () => new THREE.Vector2(root.position.x, root.position.z);
  return { root, loco, log, run, floor };
}

const near = (p: THREE.Vector2, q: Vec2, eps = 0.06) => Math.hypot(p.x - q.x, p.y - q.z) < eps;

describe("LocomotionController", () => {
  it("the first place snaps (a reconnect), later ones are walked", () => {
    const s = stage();
    s.loco.setPlace("window");
    expect(near(s.floor(), PLACES.window.approach)).toBe(true);
    expect(s.loco.moving).toBe(false);
    s.loco.setPlace("bookshelf");
    expect(s.loco.moving).toBe(true);
    s.run(1);
    expect(s.log.walk.some((ts) => ts !== null && ts > 0)).toBe(true);
    s.run(20);
    expect(s.loco.moving).toBe(false);
    expect(s.loco.place).toBe("bookshelf");
    expect(near(s.floor(), PLACES.bookshelf.approach)).toBe(true);
    // Facing what the place is about (world yaw + the model's own flip).
    const yaw = new THREE.Euler().setFromQuaternion(s.root.quaternion, "YXZ").y;
    expect(Math.cos(yaw - (PLACES.bookshelf.facing + Math.PI))).toBeGreaterThan(0.99);
  });

  it("sits down at the desk: on the seat, lower, in the sit posture", () => {
    const s = stage();
    s.loco.setPlace("center");
    s.loco.setPlace("desk");
    s.run(25);
    expect(s.loco.place).toBe("desk");
    expect(s.loco.posture).toBe("sit");
    expect(s.log.posture).toContain("sit");
    expect(near(s.floor(), PLACES.desk.seat!)).toBe(true);
    expect(s.root.position.y).toBeLessThan(0);
  });

  it("gets up before walking away from a seat", () => {
    const s = stage();
    s.loco.setPlace("desk");
    s.log.posture.length = 0;
    s.loco.setPlace("window");
    s.run(0.2);
    expect(s.log.posture[0]).toBe("stand");
    expect(s.loco.walking).toBe(false); // rising first
    s.run(25);
    expect(s.loco.place).toBe("window");
    expect(s.loco.posture).toBe("stand");
  });

  it("asking for where she already is, or is already going, does nothing", () => {
    const s = stage();
    s.loco.setPlace("center");
    s.loco.setPlace("center");
    expect(s.loco.moving).toBe(false);
    s.loco.setPlace("door");
    s.run(0.5);
    const walks = s.log.walk.length;
    s.loco.setPlace("door");
    s.run(0.01);
    expect(s.log.walk.length - walks).toBeLessThanOrEqual(1);
    s.run(20);
    expect(s.loco.place).toBe("door");
  });

  it("a new place mid-trip re-plans from where she stands", () => {
    const s = stage();
    s.loco.setPlace("center");
    s.loco.setPlace("door");
    s.run(1.5);
    const mid = s.floor().clone();
    expect(near(mid, PLACES.center.approach)).toBe(false);
    s.loco.setPlace("window");
    s.run(0.05);
    expect(Math.hypot(s.floor().x - mid.x, s.floor().y - mid.y)).toBeLessThan(0.1); // no teleport
    s.run(25);
    expect(s.loco.place).toBe("window");
  });

  it("asleep she does not wander — except to bed, where she lies down", () => {
    const s = stage();
    s.loco.setPlace("center");
    s.loco.setSleepPhase("deep_sleep");
    s.loco.setPlace("window");
    s.run(2);
    expect(s.loco.moving).toBe(false);
    s.loco.setPlace("bed");
    s.run(30);
    expect(s.loco.place).toBe("bed");
    expect(s.loco.posture).toBe("lie");
    // The body is horizontal: the model's up axis lies on the floor plane.
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(s.root.quaternion);
    expect(Math.abs(up.y)).toBeLessThan(0.05);
  });

  it("waking in bed she sits up on its edge; a place asked during the night comes after", () => {
    const s = stage({ sleep: "deep_sleep" });
    s.loco.setPlace("bed"); // snap, asleep → lying
    expect(s.loco.posture).toBe("lie");
    s.loco.setPlace("desk"); // deferred
    s.run(1);
    expect(s.loco.posture).toBe("lie");
    s.loco.setSleepPhase("awake");
    s.run(40);
    expect(s.loco.place).toBe("desk" as PlaceId);
    expect(s.loco.posture).toBe("sit");
  });
});

describe("the desk chair", () => {
  function withChair() {
    const s = stage();
    const chair = new THREE.Object3D();
    chair.position.set(-1.4, 0, -3.3);
    s.loco.setProp("desk", chair);
    const out = () => (chair.position.x + 1.4) * CHAIR_BACK.x + (chair.position.z + 3.3) * CHAIR_BACK.z;
    return { ...s, chair, out };
  }

  it("she pulls it out, sits, and rolls in with it", () => {
    const s = withChair();
    s.loco.setPlace("center");
    s.loco.setPlace("desk");
    let maxOut = 0;
    let sawEntry = false;
    for (let t = 0; t < 30; t += 1 / 30) {
      s.loco.update(1 / 30);
      maxOut = Math.max(maxOut, s.out());
      if (near(s.floor(), seatEntry(PLACES.desk)!, 0.03)) sawEntry = true;
    }
    expect(sawEntry).toBe(true); // she stood in front of the pulled-out seat
    expect(maxOut).toBeGreaterThan(PLACES.desk.prop!.pull * 0.95);
    expect(s.out()).toBeLessThan(0.01); // rolled back in, with her on it
    expect(near(s.floor(), PLACES.desk.seat!)).toBe(true);
    expect(s.loco.posture).toBe("sit");
  });

  it("leaving, she rolls out, steps aside, and the chair goes back in — she never walks through it", () => {
    const s = withChair();
    s.loco.setPlace("desk"); // snap: seated, chair in
    s.loco.setPlace("bookshelf");
    let maxOut = 0;
    const trail: THREE.Vector2[] = [];
    for (let t = 0; t < 30; t += 1 / 30) {
      s.loco.update(1 / 30);
      maxOut = Math.max(maxOut, s.out());
      trail.push(s.floor().clone());
    }
    expect(maxOut).toBeGreaterThan(PLACES.desk.prop!.pull * 0.95);
    expect(s.out()).toBeLessThan(0.01);
    expect(s.loco.place).toBe("bookshelf");
    // Her path never crosses the pulled-out seat.
    const seat = pulledSeat(PLACES.desk)!;
    const crossed = trail.some((p, i) => i > 60 && Math.hypot(p.x - seat.x, p.y - seat.z) < 0.15);
    expect(crossed).toBe(false);
  });

  it("without the chair object she still sits (from the side)", () => {
    const s = stage();
    s.loco.setPlace("center");
    s.loco.setPlace("desk");
    s.run(25);
    expect(s.loco.posture).toBe("sit");
    expect(near(s.floor(), PLACES.desk.seat!)).toBe(true);
  });
});
