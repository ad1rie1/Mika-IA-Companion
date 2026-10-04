import * as THREE from "three";
import type { SleepPhase } from "../../types";
import {
  CHAIR_BACK,
  PLACES,
  planPath,
  pulledSeat,
  seatEntry,
  type PlaceId,
  type Posture,
  type Vec2,
} from "./roomLayout";
import { SEAT_HIPS_ABOVE, WALK_SPEED } from "./proceduralClips";

/**
 * Carries out where the AI put her — never decides it.
 *
 * The backend owns `place` (a closed vocabulary, see roomLayout.ts); this
 * controller turns a change of place into a believable trip: get up if she
 * is seated or lying, walk the obstacle-free path at a pace the walk cycle's
 * feet match, turn to face what the place is about, then sit or lie down.
 * At the desk the chair is part of it: she pulls it out on her way in,
 * steps in front of it, sits, and rolls in with it — and rolls back out,
 * stands, steps aside and pushes it in when she leaves.
 *
 * It is written to be driven by a model, i.e. by inputs it cannot trust to
 * be well-behaved:
 *
 *   - the place is STATE, not a command: asking for where she already is
 *     (or is already going) does nothing, and a reconnect re-sends it;
 *   - a new place mid-trip re-plans from where she stands — no teleport, no
 *     finishing the old trip first; mid sit-down or get-up it waits for the
 *     body to be upright again;
 *   - asleep, she does not walk anywhere but to bed — another place is kept
 *     for when she wakes;
 *   - the first place it ever gets (page load, reconnect) is a snap, not a
 *     walk from the middle of the room.
 *
 * The root transform is composed every frame from a floor position, a
 * height offset (seated), a facing and a lie blend, so every transition is
 * a tween of a few numbers and nothing can be left half-rotated.
 */

/** What the controller asks of the animation state machine. */
export interface LocomotionBody {
  /** Walk at this playback speed (1 = the clip's own stride), or stop. */
  walk(timeScale: number | null): void;
  /** Hold a seated / lying posture clip, or stand. */
  posture(posture: Posture, fade: number): void;
}

export interface LocomotionOptions {
  root: THREE.Object3D;
  /** The model's own yaw on the root (π for a VRM 0.x, 0 for a 1.0). */
  baseYaw: number;
  /** Standing hips height of the rig (m). */
  hipsHeight: number;
  body: LocomotionBody;
}

type Phase =
  | "settled"
  | "rollOut" // seated, rolling back from the desk with the chair
  | "rising" // seat → floor
  | "unlying" // bed → bed edge
  | "turning" // in place, toward the first leg of the path
  | "walking"
  | "facing" // in place, toward what the place is about
  | "sitting" // floor → seat
  | "rollIn" // seated, rolling in to the desk with the chair
  | "lying"; // bed edge → bed

const RISE_S = 0.95;
const SIT_S = 1.05;
const LIE_S = 1.7;
const ROLL_S = 0.8;
/** Turn rate in place (rad/s) and while walking. */
const TURN_RATE = 2.6;
const WALK_TURN_RATE = 3.4;
/** Heading error past which she turns on the spot before walking. */
const TURN_IN_PLACE = 0.9;
/** Slow-down zone before the last waypoint (m). */
const ARRIVE_ZONE = 0.35;
const ARRIVE_MIN = 0.4;
/** Stepping in place while turning: playback speed of the walk cycle. */
const SHUFFLE_TIMESCALE = 0.45;
/** She reaches for the chair this far from where she will sit (m). */
const CHAIR_REACH = 1.0;
/** How fast a chair slides when she pulls or pushes it alone (m/s). */
const CHAIR_SPEED = 0.8;

function smooth(t: number): number {
  const x = Math.max(0, Math.min(1, t));
  return x * x * (3 - 2 * x);
}

function wrapAngle(a: number): number {
  return Math.atan2(Math.sin(a), Math.cos(a));
}

function yawTo(from: Vec2, to: Vec2): number {
  return Math.atan2(to.x - from.x, to.z - from.z);
}

const dist = (a: Vec2, b: Vec2) => Math.hypot(a.x - b.x, a.z - b.z);

const _qUp = new THREE.Quaternion();
const _qLie = new THREE.Quaternion();
const _qBase = new THREE.Quaternion();
const _qTmp = new THREE.Quaternion();
const _Y = new THREE.Vector3(0, 1, 0);
const _X = new THREE.Vector3(1, 0, 0);

interface Pose {
  pos: Vec2;
  height: number;
  facing: number;
  lie: number;
  /** How far the place's chair is pulled out (m). */
  chair: number;
}

interface Prop {
  obj: THREE.Object3D;
  rest: THREE.Vector3;
}

export class LocomotionController {
  /** Where she is (or last settled). */
  place: PlaceId | null = null;
  /** Where the backend wants her. */
  private target: PlaceId | null = null;
  /** Requested while asleep, for when she wakes. */
  private deferred: PlaceId | null = null;
  private sleep: SleepPhase = "awake";

  posture: Posture = "stand";
  private phase: Phase = "settled";

  // Composed root state.
  private pos: Vec2 = { x: 0, z: -0.5 };
  private height = 0;
  private facing = 0;
  private lieBlend = 0;

  // The desk chair (or any place's movable seat).
  private props = new Map<PlaceId, Prop>();
  private chair = 0;
  private chairGoal = 0;
  /** Whose chair `chair` measures. */
  private chairOf: PlaceId | null = null;
  /** Push the chair back in once she has stepped aside (first waypoint). */
  private pushChairAtFirstWaypoint = false;

  // Tween.
  private t = 0;
  private dur = 1;
  private from: Pose = { pos: { x: 0, z: 0 }, height: 0, facing: 0, lie: 0, chair: 0 };
  private to: Pose = { pos: { x: 0, z: 0 }, height: 0, facing: 0, lie: 0, chair: 0 };

  private path: Vec2[] = [];
  private speed = 0;

  constructor(private readonly opts: LocomotionOptions) {
    const r = opts.root;
    this.pos = { x: r.position.x, z: r.position.z };
    this.facing = wrapAngle(r.rotation.y - opts.baseYaw);
  }

  get moving(): boolean {
    return this.phase !== "settled";
  }

  get walking(): boolean {
    return this.phase === "walking" || this.phase === "turning";
  }

  get currentPhase(): Phase {
    return this.phase;
  }

  /** Floor position and facing (world yaw), for snapshots. */
  get floor(): { x: number; z: number; facing: number } {
    return { x: this.pos.x, z: this.pos.z, facing: this.facing };
  }

  /**
   * The room's movable seat for a place (the `DeskChair` object), once the
   * room has loaded. Its current position is its rest. Without one, she
   * sits from the side, as before.
   */
  setProp(place: PlaceId, obj: THREE.Object3D | null): void {
    if (!obj) {
      this.props.delete(place);
      return;
    }
    this.props.set(place, { obj, rest: obj.position.clone() });
    this.applyChair();
  }

  /** The backend's place. `instant` snaps (first state after a connect). */
  setPlace(place: PlaceId, opts: { instant?: boolean } = {}): void {
    if (opts.instant || this.place === null) {
      this.snap(place);
      return;
    }
    if (this.sleep !== "awake" && place !== "bed") {
      this.deferred = place;
      return;
    }
    this.deferred = null;
    if (place === this.target) return;
    this.target = place;
    if (this.phase === "settled" || this.phase === "facing") this.depart();
    else if (this.phase === "walking" || this.phase === "turning") this.replan();
    // rising / sitting / rolling / lying / unlying: picked up when the tween ends.
  }

  setSleepPhase(phase: SleepPhase): void {
    const was = this.sleep;
    this.sleep = phase;
    if (phase === "awake" && was !== "awake") {
      if (this.deferred) {
        const next = this.deferred;
        this.deferred = null;
        this.setPlace(next);
        return;
      }
      if (this.posture === "lie" && this.phase === "settled") this.startUnlie();
      return;
    }
    if (phase !== "awake" && this.phase === "settled" && this.place === "bed" && this.posture === "sit") {
      this.startLie();
    }
  }

  update(dt: number): void {
    switch (this.phase) {
      case "settled":
        break;
      case "rollOut":
      case "rising":
      case "unlying":
      case "sitting":
      case "rollIn":
      case "lying":
      case "facing":
        this.t += dt;
        this.applyTween(smooth(this.t / this.dur));
        if (this.t >= this.dur) this.endTween();
        break;
      case "turning":
        this.updateTurning(dt);
        break;
      case "walking":
        this.updateWalking(dt);
        break;
    }
    // A chair she is not holding slides on its own toward where she left it.
    if (this.phase !== "rollIn" && this.phase !== "rollOut" && this.phase !== "sitting") {
      const step = CHAIR_SPEED * dt;
      this.chair += Math.max(-step, Math.min(step, this.chairGoal - this.chair));
    }
    this.compose();
  }

  // ── Trip ──────────────────────────────────────────────────────────

  private depart(): void {
    if (this.posture === "lie") return this.startUnlie();
    if (this.posture === "sit") {
      if (this.place && this.props.has(this.place) && PLACES[this.place].prop) return this.startRollOut();
      return this.startRise();
    }
    this.startWalk();
  }

  /** Where the walk to a place ends: in front of its pulled-out seat, or its approach. */
  private walkEnd(place: PlaceId): Vec2 {
    const p = PLACES[place];
    const entry = this.props.has(place) ? seatEntry(p) : null;
    return entry ?? p.approach;
  }

  private startWalk(): void {
    const place = this.target ? PLACES[this.target] : null;
    if (!place) return this.settle();
    const leaving = this.place && this.place !== this.target ? PLACES[this.place] : null;
    const fromSeat = leaving && this.props.has(leaving.id) && leaving.prop && this.chair > 0.01;
    // Out of a pulled chair: step aside first (never through the chair),
    // and push it back in once out of the way.
    const start = fromSeat ? leaving.approach : this.pos;
    let path = planPath(start, place.approach);
    if (fromSeat) path = [leaving.approach, ...path];
    this.pushChairAtFirstWaypoint = Boolean(fromSeat);
    // Into a movable seat: through its approach, then in front of the seat.
    if (this.props.has(place.id) && place.prop) path = [...path, this.walkEnd(place.id)];
    this.path = path;
    if (this.path.length === 1 && dist(this.path[0], this.pos) < 0.05) {
      this.path = [];
      return this.startFacing();
    }
    const heading = yawTo(this.pos, this.path[0]);
    if (Math.abs(wrapAngle(heading - this.facing)) > TURN_IN_PLACE) {
      this.phase = "turning";
      this.opts.body.walk(SHUFFLE_TIMESCALE);
    } else {
      this.phase = "walking";
      this.speed = WALK_SPEED * 0.6;
      this.opts.body.walk(this.speed / WALK_SPEED);
    }
  }

  private replan(): void {
    const place = this.target ? PLACES[this.target] : null;
    if (!place) return;
    let path = planPath(this.pos, place.approach);
    if (this.props.has(place.id) && place.prop) path = [...path, this.walkEnd(place.id)];
    this.path = path;
  }

  private updateTurning(dt: number): void {
    if (this.path.length === 0) return this.startFacing();
    const heading = yawTo(this.pos, this.path[0]);
    const err = wrapAngle(heading - this.facing);
    const step = Math.sign(err) * Math.min(Math.abs(err), TURN_RATE * dt);
    this.facing = wrapAngle(this.facing + step);
    if (Math.abs(err) < 0.25) {
      this.phase = "walking";
      this.speed = WALK_SPEED * 0.5;
    }
  }

  private remaining(): number {
    if (this.path.length === 0) return 0;
    let total = dist(this.pos, this.path[0]);
    for (let i = 1; i < this.path.length; i++) total += dist(this.path[i - 1], this.path[i]);
    return total;
  }

  private updateWalking(dt: number): void {
    if (this.path.length === 0) return this.startFacing();
    const next = this.path[0];
    const remaining = this.remaining();
    // Reaching for the chair of the seat she is heading to.
    const target = this.target;
    if (target && this.props.has(target) && PLACES[target].prop && remaining < CHAIR_REACH) {
      this.chairOf = target;
      this.chairGoal = PLACES[target].prop!.pull;
    }
    // Accelerate to cruise, slow into the last steps.
    const cruise = WALK_SPEED * (remaining < ARRIVE_ZONE ? Math.max(ARRIVE_MIN, remaining / ARRIVE_ZONE) : 1);
    this.speed += (cruise - this.speed) * Math.min(1, dt * 4);
    this.opts.body.walk(Math.max(0.35, this.speed / WALK_SPEED));

    const heading = yawTo(this.pos, next);
    const err = wrapAngle(heading - this.facing);
    this.facing = wrapAngle(this.facing + Math.sign(err) * Math.min(Math.abs(err), WALK_TURN_RATE * dt));
    // Move along the facing (a body walks where it faces), but never past
    // the waypoint — corners are rounded by the turn rate.
    let step = this.speed * dt;
    const toNext = dist(this.pos, next);
    if (step >= toNext || toNext < 0.04) {
      this.pos = { x: next.x, z: next.z };
      this.path.shift();
      step = 0;
      if (this.pushChairAtFirstWaypoint) {
        this.pushChairAtFirstWaypoint = false;
        this.chairGoal = 0;
      }
      if (this.path.length === 0) return this.startFacing();
    }
    if (step > 0) {
      // Facing and true heading are blended so a sharp corner cannot carry
      // her into furniture while she is still turning.
      const dir = Math.abs(err) > 0.5 ? heading : this.facing;
      this.pos = { x: this.pos.x + Math.sin(dir) * step, z: this.pos.z + Math.cos(dir) * step };
    }
  }

  private startFacing(): void {
    const place = this.target ? PLACES[this.target] : null;
    if (!place) return this.settle();
    const delta = wrapAngle(place.facing - this.facing);
    // A real turn on the spot takes a few small steps; a slight one doesn't.
    this.opts.body.walk(Math.abs(delta) > 0.35 ? SHUFFLE_TIMESCALE : null);
    this.tween("facing", Math.max(0.35, Math.abs(delta) / TURN_RATE), {
      ...this.pose(),
      height: 0,
      facing: this.facing + delta,
      lie: 0,
    });
  }

  private startSit(): void {
    const place = this.target ? PLACES[this.target] : null;
    if (!place?.seat) return this.settle();
    this.posture = "sit";
    this.opts.body.posture("sit", SIT_S);
    // Onto the pulled-out chair (she rolls in after), or straight onto the seat.
    const onto = (this.props.has(place.id) && pulledSeat(place)) || { x: place.seat.x, z: place.seat.z };
    this.tween("sitting", SIT_S, {
      ...this.pose(),
      pos: onto,
      height: this.seatOffset(place.seat.height),
      lie: 0,
    });
  }

  private startRollIn(): void {
    const place = this.target ? PLACES[this.target] : null;
    if (!place?.seat) return this.settle();
    this.chairOf = place.id;
    this.tween("rollIn", ROLL_S, { ...this.pose(), pos: { x: place.seat.x, z: place.seat.z }, chair: 0 });
  }

  private startRollOut(): void {
    const place = this.place ? PLACES[this.place] : null;
    const out = place ? pulledSeat(place) : null;
    if (!place?.prop || !out) return this.startRise();
    this.chairOf = place.id;
    this.tween("rollOut", ROLL_S, { ...this.pose(), pos: out, chair: place.prop.pull });
  }

  private startRise(): void {
    const place = this.place ? PLACES[this.place] : null;
    this.posture = "stand";
    this.opts.body.posture("stand", RISE_S);
    const entry = place && this.props.has(place.id) ? seatEntry(place) : null;
    this.chairGoal = this.chair; // the chair stays where it is while she stands
    this.tween("rising", RISE_S, {
      ...this.pose(),
      pos: entry ?? (place ? place.approach : this.pos),
      height: 0,
      lie: 0,
    });
  }

  private startLie(): void {
    const bed = PLACES.bed;
    if (!bed.lie) return;
    this.posture = "lie";
    this.opts.body.posture("lie", LIE_S);
    this.tween("lying", LIE_S, { ...this.pose(), lie: 1 });
  }

  private startUnlie(): void {
    const bed = PLACES.bed;
    this.posture = "sit";
    this.opts.body.posture("sit", LIE_S);
    this.tween("unlying", LIE_S, {
      ...this.pose(),
      pos: bed.seat ? { x: bed.seat.x, z: bed.seat.z } : this.pos,
      height: bed.seat ? this.seatOffset(bed.seat.height) : 0,
      facing: bed.facing,
      lie: 0,
    });
  }

  private endTween(): void {
    const phase = this.phase;
    this.applyTween(1);
    if (phase === "facing") {
      this.opts.body.walk(null);
      this.place = this.target;
      const place = this.target ? PLACES[this.target] : null;
      if (place?.posture === "sit") return this.startSit();
      return this.settle();
    }
    if (phase === "sitting") {
      this.place = this.target;
      if (this.place && this.props.has(this.place) && PLACES[this.place].prop) return this.startRollIn();
      if (this.place === "bed" && this.sleep !== "awake") return this.startLie();
      return this.settle();
    }
    if (phase === "rollIn") {
      this.chairGoal = 0;
      return this.settle();
    }
    if (phase === "rollOut") {
      this.chairGoal = this.chair;
      return this.startRise();
    }
    if (phase === "lying") return this.settle();
    if (phase === "unlying") {
      // Woken, or asked elsewhere: from the bed edge, carry on.
      if (this.target && this.target !== "bed") return this.startRise();
      return this.settle();
    }
    if (phase === "rising") {
      if (this.target && this.target !== this.place) return this.startWalk();
      return this.settle();
    }
  }

  private settle(): void {
    this.phase = "settled";
    this.opts.body.walk(null);
    // A target changed while the body was busy: go now.
    if (this.target && this.target !== this.place) this.depart();
  }

  // ── Snap ──────────────────────────────────────────────────────────

  private snap(place: PlaceId): void {
    const p = PLACES[place];
    this.place = place;
    this.target = place;
    this.deferred = null;
    this.path = [];
    this.opts.body.walk(null);
    this.facing = p.facing;
    this.lieBlend = 0;
    this.chair = 0;
    this.chairGoal = 0;
    this.chairOf = p.prop ? place : this.chairOf;
    if (p.posture === "sit" && p.seat) {
      const lie = place === "bed" && this.sleep !== "awake";
      this.posture = lie ? "lie" : "sit";
      this.pos = { x: p.seat.x, z: p.seat.z };
      this.height = this.seatOffset(p.seat.height);
      this.lieBlend = lie ? 1 : 0;
    } else {
      this.posture = "stand";
      this.pos = { ...p.approach };
      this.height = 0;
    }
    this.opts.body.posture(this.posture, 0.3);
    this.phase = "settled";
    this.compose();
  }

  // ── Root composition ──────────────────────────────────────────────

  private seatOffset(seatHeight: number): number {
    return seatHeight + SEAT_HIPS_ABOVE - this.opts.hipsHeight;
  }

  private pose(): Pose {
    return { pos: { ...this.pos }, height: this.height, facing: this.facing, lie: this.lieBlend, chair: this.chair };
  }

  private tween(phase: Phase, dur: number, to: Pose): void {
    this.phase = phase;
    this.t = 0;
    this.dur = Math.max(0.05, dur);
    this.from = this.pose();
    this.to = { ...to, pos: { ...to.pos } };
  }

  private applyTween(k: number): void {
    const f = this.from;
    const t = this.to;
    this.pos = { x: f.pos.x + (t.pos.x - f.pos.x) * k, z: f.pos.z + (t.pos.z - f.pos.z) * k };
    this.height = f.height + (t.height - f.height) * k;
    this.facing = f.facing + wrapAngle(t.facing - f.facing) * k;
    this.lieBlend = f.lie + (t.lie - f.lie) * k;
    if (this.phase === "rollIn" || this.phase === "rollOut") this.chair = f.chair + (t.chair - f.chair) * k;
  }

  private applyChair(): void {
    const owner = this.chairOf;
    const prop = owner ? this.props.get(owner) : null;
    if (!prop) return;
    prop.obj.position.set(
      prop.rest.x + CHAIR_BACK.x * this.chair,
      prop.rest.y,
      prop.rest.z + CHAIR_BACK.z * this.chair
    );
  }

  private compose(): void {
    this.applyChair();
    const root = this.opts.root;
    _qBase.setFromAxisAngle(_Y, this.opts.baseYaw);
    _qUp.setFromAxisAngle(_Y, this.facing).multiply(_qBase);
    let x = this.pos.x;
    let y = this.height;
    let z = this.pos.z;
    if (this.lieBlend > 0) {
      const lie = PLACES.bed.lie!;
      // Face up, head toward headYaw: Ry(headYaw + π) · Rx(−π/2) · base.
      _qLie
        .setFromAxisAngle(_Y, lie.headYaw + Math.PI)
        .multiply(_qTmp.setFromAxisAngle(_X, -Math.PI / 2))
        .multiply(_qBase);
      const d = { x: Math.sin(lie.headYaw), z: Math.cos(lie.headYaw) };
      const lx = lie.x - d.x * this.opts.hipsHeight;
      const lz = lie.z - d.z * this.opts.hipsHeight;
      const k = this.lieBlend;
      x += (lx - x) * k;
      y += (lie.height - y) * k;
      z += (lz - z) * k;
      root.quaternion.slerpQuaternions(_qUp, _qLie, k);
    } else {
      root.quaternion.copy(_qUp);
    }
    root.position.set(x, y, z);
  }
}
