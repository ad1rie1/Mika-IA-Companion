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
import { CHAIR_CLEAR, aroundChair, placeFrame, seatFront } from "../roomLayout";

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

describe("the desk chair, as the Unity client takes it", () => {
  function withChair() {
    const s = stage();
    const chair = new THREE.Object3D();
    chair.position.set(-1.4, 0, -3.3);
    chair.rotation.y = 0.3;
    s.loco.setProp("desk", chair);
    const rest = { pos: chair.position.clone(), rot: chair.quaternion.clone() };
    const still = () => chair.position.distanceTo(rest.pos) < 1e-9 && chair.quaternion.angleTo(rest.rot) < 1e-6;
    return { ...s, chair, still };
  }

  it("she walks round the chair to the front of its seat and sits down where it stands — it never moves", () => {
    const s = withChair();
    s.loco.setPlace("center");
    s.loco.setPlace("desk");
    const front = seatFront(PLACES.desk, 0.2)!;
    const corner = aroundChair(PLACES.desk, front, PLACES.desk.approach)!;
    expect(corner).not.toBeNull(); // the desk's approach is beside the chair
    let sawCorner = false;
    let sawFront = false;
    let still = true;
    for (let t = 0; t < 30; t += 1 / 30) {
      s.loco.update(1 / 30);
      if (near(s.floor(), corner, 0.03)) sawCorner = true;
      if (near(s.floor(), front, 0.03)) sawFront = true;
      still &&= s.still();
    }
    expect(sawCorner).toBe(true);
    expect(sawFront).toBe(true);
    expect(still).toBe(true);
    expect(near(s.floor(), PLACES.desk.seat!)).toBe(true);
    expect(s.loco.posture).toBe("sit");
  });

  it("she never crosses the chair's armrests: beside the seat she keeps her distance", () => {
    const s = withChair();
    s.loco.setPlace("center");
    s.loco.setPlace("desk");
    const seat = PLACES.desk.seat!;
    const { right } = placeFrame(PLACES.desk);
    for (let t = 0; t < 30; t += 1 / 30) {
      s.loco.update(1 / 30);
      if (s.loco.posture !== "stand") break;
      const p = s.floor();
      const lateral = Math.abs((p.x - seat.x) * right.x + (p.y - seat.z) * right.z);
      const ahead = (p.x - seat.x) * right.z - (p.y - seat.z) * right.x; // along the seat's forward
      // standing beside the seat (not in front of it, not far behind), she is clear of the armrest
      if (ahead < 0.1 && ahead > -0.6) expect(lateral).toBeGreaterThan(CHAIR_CLEAR - 0.06);
    }
  });

  it("leaving, she gets up in front of the seat and steps out round the chair", () => {
    const s = withChair();
    s.loco.setPlace("desk"); // snap: seated
    s.loco.setPlace("bookshelf");
    const front = seatFront(PLACES.desk, 0.2)!;
    let sawFront = false;
    let still = true;
    for (let t = 0; t < 30; t += 1 / 30) {
      s.loco.update(1 / 30);
      if (near(s.floor(), front, 0.03)) sawFront = true;
      still &&= s.still();
    }
    expect(sawFront).toBe(true);
    expect(still).toBe(true);
    expect(s.loco.place).toBe("bookshelf");
  });

  it("seated, her desk's gestures swivel and roll the chair — and her with it", () => {
    const s = withChair();
    s.loco.setPlace("desk");
    s.loco.setSeatDrive(19.45, 0.255);
    s.run(0.1);
    const { ahead } = placeFrame(PLACES.desk);
    expect(s.chair.position.x).toBeCloseTo(-1.4 + ahead.x * 0.255, 6);
    expect(s.chair.position.z).toBeCloseTo(-3.3 + ahead.z * 0.255, 6);
    // swivelled to her right: a negative turn about +Y
    expect(new THREE.Euler().setFromQuaternion(s.chair.quaternion, "YXZ").y).toBeCloseTo(0.3 - (19.45 * Math.PI) / 180, 5);
    expect(near(s.floor(), { x: PLACES.desk.seat!.x + ahead.x * 0.255, z: PLACES.desk.seat!.z + ahead.z * 0.255 }, 0.001)).toBe(true);
  });

  it("held by her desk, she stays seated; let go, she gets up", () => {
    let hold = true;
    const root = new THREE.Object3D();
    const loco = new LocomotionController({
      root,
      baseYaw: Math.PI,
      hipsHeight: 0.75,
      holdSeat: () => hold,
      body: { walk: () => {}, posture: () => {} },
    });
    loco.setPlace("desk");
    loco.setPlace("center");
    for (let t = 0; t < 3; t += 1 / 30) loco.update(1 / 30);
    expect(loco.posture).toBe("sit");
    expect(loco.wantsToLeave).toBe(true);
    hold = false;
    for (let t = 0; t < 15; t += 1 / 30) loco.update(1 / 30);
    expect(loco.place).toBe("center");
  });

  it("a captured sit-down: she stands as far ahead as it carries her back, the root keeps the clip's pace", () => {
    const root = new THREE.Object3D();
    root.position.set(0, 0, -0.5);
    root.rotation.y = Math.PI;
    let progress: number | null = null;
    const played: string[] = [];
    const loco = new LocomotionController({
      root,
      baseYaw: Math.PI,
      hipsHeight: 0.75,
      seatedHipsHeight: () => 0.567,
      body: {
        walk: () => {},
        posture: (p) => played.push(p),
        transition: (kind) => (kind === "sit" ? { seconds: 1.6, travel: 0.313 } : { seconds: 0.9, travel: 0.294 }),
        playTransition: (kind) => {
          played.push(`transition:${kind}`);
          progress = 0;
        },
        transitionProgress: () => progress,
      },
    });
    loco.setPlace("center");
    loco.setPlace("bed"); // no chair: straight to the front of its edge
    const front = seatFront(PLACES.bed, 0.313)!;
    for (let t = 0; t < 30 && !played.includes("transition:sit"); t += 1 / 30) loco.update(1 / 30);
    const at = () => ({ x: root.position.x, z: root.position.z });
    expect(Math.hypot(at().x - front.x, at().z - front.z)).toBeLessThan(0.05);
    // the clip half way (whatever the clock says): the root half way to the seat, still on the floor
    progress = 0.5;
    loco.update(1 / 30);
    const seat = PLACES.bed.seat!;
    expect(at().x).toBeCloseTo((front.x + seat.x) / 2, 2);
    expect(root.position.y).toBeLessThan(0.02);
    progress = 1;
    loco.update(1 / 30);
    expect(Math.hypot(at().x - seat.x, at().z - seat.z)).toBeLessThan(0.01);
    expect(played[played.length - 1]).toBe("sit");
    // the seat puts her hips at 0.47 + 0.15 − 0.03: the workshop clip holds them at 0.567
    expect(root.position.y).toBeCloseTo(0.47 + 0.15 - 0.03 - 0.567, 6);
  });

  it("without the chair object she still sits", () => {
    const s = stage();
    s.loco.setPlace("center");
    s.loco.setPlace("desk");
    s.run(25);
    expect(s.loco.posture).toBe("sit");
    expect(near(s.floor(), PLACES.desk.seat!)).toBe(true);
  });
});
