/**
 * Where Mika can go in her room, and how to get there — pure geometry, no
 * three.js.
 *
 * The decision to move belongs to the AI (the backend sends a PLACE, never
 * coordinates): a closed vocabulary keeps a model from walking her into a
 * wall or out of the room, and every place below is something she can do
 * there — sit at her desk, look out of the window, sit on her bed (or lie
 * in it when she sleeps), browse her books, go to the door.
 *
 * Coordinates are three.js room space (metres, Y up, the room from
 * Environment.ts / room.glb). `facing` is a world yaw: forward is
 * (sin φ, cos φ) on (x, z), so 0 faces +Z — the default camera.
 */

export const PLACE_IDS = ["center", "window", "desk", "bed", "bookshelf", "door"] as const;
export type PlaceId = (typeof PLACE_IDS)[number];

const PLACE_SET: ReadonlySet<string> = new Set(PLACE_IDS);
export function isPlaceId(value: unknown): value is PlaceId {
  return typeof value === "string" && PLACE_SET.has(value);
}

export type Posture = "stand" | "sit" | "lie";

export interface Vec2 {
  x: number;
  z: number;
}

export interface Place {
  id: PlaceId;
  /** Where the walk ends, on the floor. */
  approach: Vec2;
  /** Facing (world yaw) once there. */
  facing: number;
  posture: "stand" | "sit";
  /** For a seat: where the hips settle and at what height (seat top). */
  seat?: { x: number; z: number; height: number };
  /** For the bed when she sleeps: where the hips rest, and the yaw of the
   * body's long axis (head toward the pillow). */
  lie?: { x: number; z: number; height: number; headYaw: number };
  /**
   * A seat that moves (the desk chair, object `DeskChair` of room.glb): she
   * pulls it back along its own backward axis, steps in front of it, sits,
   * and rolls in with it. `pull` is how far it comes out (m), `stand` how
   * far in front of the pulled seat her hips stand before sitting back.
   */
  prop?: { name: string; pull: number; stand: number };
}

/** Body radius kept clear of every obstacle (she is small: ~1.3 m tall). */
export const BODY_RADIUS = 0.22;

/** The room's walkable box (inside the skirting boards). */
export const ROOM_BOUNDS = { minX: -3.85, maxX: 3.85, minZ: -4.35, maxZ: 3.35 };

/** The desk chair's yaw in room.glb (its front, local −Z, faces the desk). */
const CHAIR_YAW = 0.3;

// Measured on room.glb (assets-src/blender, report of 2026-10-02). The
// procedural fallback room uses the same layout. This table is READ by
// backendv2/tests/unit/test_world_contract.py (TestLaChambreDuClientWeb),
// which compares it with backendv2/examples/monde/chambre.json: move a place
// here, move it there; keep each entry as `id`, `approach`, `facing`,
// `posture` in that order.
export const PLACES: Record<PlaceId, Place> = {
  // On the rug, facing whoever is in front of her — the conversation spot.
  center: { id: "center", approach: { x: 0, z: -0.5 }, facing: 0, posture: "stand" },
  // Window on the left wall (sill at x −3.86): she stands close and looks out.
  window: { id: "window", approach: { x: -3.25, z: -1.2 }, facing: -Math.PI / 2, posture: "stand" },
  // Desk chair: reached from its right side (+x), pulled back, sat on,
  // rolled in. Seat top 0.51, facing the desk along the chair's own front.
  desk: {
    id: "desk",
    approach: { x: -0.7, z: -3.3 },
    facing: -Math.PI + CHAIR_YAW,
    posture: "sit",
    seat: { x: -1.4, z: -3.3, height: 0.51 },
    prop: { name: "DeskChair", pull: 0.42, stand: 0.2 },
  },
  // Edge of the bed (duvet top 0.49, its edge at x −2.63), facing the room;
  // asleep she lies in it, head on the pillow at the bedside-table end (+Z).
  bed: {
    id: "bed",
    approach: { x: -2.33, z: 1.3 },
    facing: Math.PI / 2,
    posture: "sit",
    seat: { x: -2.85, z: 1.3, height: 0.47 },
    lie: { x: -3.32, z: 1.62, height: 0.56, headYaw: 0 },
  },
  // Bookshelf on the right wall: she faces the books.
  bookshelf: { id: "bookshelf", approach: { x: 3.22, z: -2.2 }, facing: Math.PI / 2, posture: "stand" },
  // Front wall door: she stands before it, back to the room's centre.
  door: { id: "door", approach: { x: 1.8, z: 2.75 }, facing: 0, posture: "stand" },
};

/** The chair's backward axis on the floor — the way it is pulled out. */
export const CHAIR_BACK: Vec2 = { x: Math.sin(CHAIR_YAW), z: Math.cos(CHAIR_YAW) };

/** Where her hips stand before sitting on a pulled-out seat. */
export function seatEntry(place: Place): Vec2 | null {
  if (!place.seat || !place.prop) return null;
  const d = place.prop.pull - place.prop.stand;
  return { x: place.seat.x + CHAIR_BACK.x * d, z: place.seat.z + CHAIR_BACK.z * d };
}

/** The seat once pulled out. */
export function pulledSeat(place: Place): Vec2 | null {
  if (!place.seat || !place.prop) return null;
  const d = place.prop.pull;
  return { x: place.seat.x + CHAIR_BACK.x * d, z: place.seat.z + CHAIR_BACK.z * d };
}

export interface Rect {
  minX: number;
  minZ: number;
  maxX: number;
  maxZ: number;
}

/** Furniture footprints she must walk around (not inflated). */
export const OBSTACLES: Rect[] = [
  { minX: -2.35, minZ: -4.45, maxX: -0.45, maxZ: -3.73 }, // desk
  { minX: -1.72, minZ: -3.61, maxX: -0.98, maxZ: -2.88 }, // desk chair (at rest)
  { minX: -0.35, minZ: -4.31, maxX: -0.09, maxZ: -4.05 }, // paper bin
  { minX: -3.97, minZ: 0.14, maxX: -2.63, maxZ: 2.43 }, // bed + duvet overhang
  { minX: -3.82, minZ: 2.54, maxX: -3.36, maxZ: 2.96 }, // bedside table
  { minX: -2.66, minZ: 2.48, maxX: -2.34, maxZ: 2.92 }, // slippers
  { minX: -3.69, minZ: 3.07, maxX: -3.43, maxZ: 3.36 }, // snake plant
  { minX: -4.0, minZ: -4.5, maxX: -3.36, maxZ: -3.27 }, // wardrobe
  { minX: 3.61, minZ: -2.955, maxX: 4.0, maxZ: -1.445 }, // bookshelf
  { minX: 3.24, minZ: -4.26, maxX: 3.78, maxZ: -3.63 }, // fig (pot + leaves)
  { minX: 2.61, minZ: -1.29, maxX: 3.9, maxZ: -0.09 }, // reading cushion + books
  { minX: 3.52, minZ: 0.035, maxX: 4.0, maxZ: 1.165 }, // dresser
  { minX: 3.34, minZ: 2.87, maxX: 3.76, maxZ: 3.32 }, // laundry basket
];

function inflate(r: Rect, by: number): Rect {
  return { minX: r.minX - by, minZ: r.minZ - by, maxX: r.maxX + by, maxZ: r.maxZ + by };
}

function inside(p: Vec2, r: Rect): boolean {
  return p.x > r.minX && p.x < r.maxX && p.z > r.minZ && p.z < r.maxZ;
}

/** Does the segment a→b cross the (open) rectangle? Liang–Barsky. */
export function segmentHitsRect(a: Vec2, b: Vec2, r: Rect): boolean {
  const dx = b.x - a.x;
  const dz = b.z - a.z;
  let t0 = 0;
  let t1 = 1;
  const clip = (p: number, q: number): boolean => {
    if (Math.abs(p) < 1e-12) return q > 0;
    const t = q / p;
    if (p < 0) {
      if (t > t1) return false;
      if (t > t0) t0 = t;
    } else {
      if (t < t0) return false;
      if (t < t1) t1 = t;
    }
    return true;
  };
  const eps = 1e-6;
  if (
    clip(-dx, a.x - (r.minX + eps)) &&
    clip(dx, r.maxX - eps - a.x) &&
    clip(-dz, a.z - (r.minZ + eps)) &&
    clip(dz, r.maxZ - eps - a.z)
  ) {
    return t1 - t0 > 1e-9;
  }
  return false;
}

const dist = (a: Vec2, b: Vec2) => Math.hypot(a.x - b.x, a.z - b.z);

export function clampToRoom(p: Vec2): Vec2 {
  return {
    x: Math.max(ROOM_BOUNDS.minX, Math.min(ROOM_BOUNDS.maxX, p.x)),
    z: Math.max(ROOM_BOUNDS.minZ, Math.min(ROOM_BOUNDS.maxZ, p.z)),
  };
}

/**
 * Shortest obstacle-free polyline from `from` to `to` (visibility graph
 * over the inflated furniture corners, Dijkstra). Returns the waypoints
 * AFTER `from`, ending at `to`. A start that is inside an inflated
 * footprint (she is standing up from the chair, getting off the bed) is
 * allowed to leave it; the path never enters another one. Falls back to
 * the straight line when no path exists — a stuck avatar is worse than one
 * that brushes a corner.
 */
export function planPath(
  from: Vec2,
  to: Vec2,
  obstacles: Rect[] = OBSTACLES,
  radius = BODY_RADIUS
): Vec2[] {
  const rects = obstacles.map((r) => inflate(r, radius));
  // Footprints the endpoints stand in are not obstacles for this trip.
  const blocking = rects.filter((r) => !inside(from, r) && !inside(to, r));
  const clear = (a: Vec2, b: Vec2) => !blocking.some((r) => segmentHitsRect(a, b, r));

  if (clear(from, to)) return [to];

  const margin = 0.02;
  const nodes: Vec2[] = [from, to];
  for (const r of blocking) {
    for (const c of [
      { x: r.minX - margin, z: r.minZ - margin },
      { x: r.maxX + margin, z: r.minZ - margin },
      { x: r.minX - margin, z: r.maxZ + margin },
      { x: r.maxX + margin, z: r.maxZ + margin },
    ]) {
      const inRoom =
        c.x >= ROOM_BOUNDS.minX && c.x <= ROOM_BOUNDS.maxX && c.z >= ROOM_BOUNDS.minZ && c.z <= ROOM_BOUNDS.maxZ;
      if (inRoom && !blocking.some((o) => inside(c, o))) nodes.push(c);
    }
  }

  const n = nodes.length;
  const best = new Array<number>(n).fill(Infinity);
  const prev = new Array<number>(n).fill(-1);
  const done = new Array<boolean>(n).fill(false);
  best[0] = 0;
  for (;;) {
    let u = -1;
    for (let i = 0; i < n; i++) if (!done[i] && best[i] < Infinity && (u < 0 || best[i] < best[u])) u = i;
    if (u < 0 || u === 1) break;
    done[u] = true;
    for (let v = 0; v < n; v++) {
      if (done[v] || v === u) continue;
      if (!clear(nodes[u], nodes[v])) continue;
      const d = best[u] + dist(nodes[u], nodes[v]);
      if (d < best[v]) {
        best[v] = d;
        prev[v] = u;
      }
    }
  }
  if (best[1] === Infinity) return [to];
  const path: Vec2[] = [];
  for (let i = 1; i !== 0; i = prev[i]) path.unshift(nodes[i]);
  return path;
}

/** Length of a polyline starting at `from`. */
export function pathLength(from: Vec2, path: Vec2[]): number {
  let total = 0;
  let p = from;
  for (const q of path) {
    total += dist(p, q);
    p = q;
  }
  return total;
}
