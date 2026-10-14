import * as THREE from "three";
import type { SleepPhase } from "../../types";
import {
  PLACES,
  aroundChair,
  placeFrame,
  planPath,
  seatFront,
  type Place,
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
 * A seat is taken as the Unity client takes it (`ActorBody.SitDown`,
 * `StandUp`): a chair is walked round to the front of its seat — never
 * through its armrests —, she stands there, her back to it, as far ahead as
 * the captured sit-down carries her hips back, and sits down with the
 * capture; getting up, the captured stand-up carries her forward, and she
 * steps out round the chair. The chair itself never moves but by her desk's
 * gestures (desk/, `setSeatDrive`).
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

/** A captured sit-down or stand-up (the Unity workshop's `sit_down`, `stand_up`). */
export interface SeatTransition {
  /** Its length (s). */
  seconds: number;
  /** How far it carries her hips (m): back onto the seat sitting down, forward standing up. */
  travel: number;
}

/** What the controller asks of the animation state machine. */
export interface LocomotionBody {
  /** Walk at this playback speed (1 = the clip's own stride), or stop. */
  walk(timeScale: number | null): void;
  /** Hold a seated / lying posture clip, or stand. */
  posture(posture: Posture, fade: number): void;
  /** The captured transition, when its clip is loaded. */
  transition?(kind: "sit" | "stand"): SeatTransition | null;
  /** Play it, once; `posture()` follows when it is over. */
  playTransition?(kind: "sit" | "stand"): void;
  /** How far into the transition the clip is (0–1), null when it is not playing: the root keeps its pace. */
  transitionProgress?(kind: "sit" | "stand"): number | null;
}

export interface LocomotionOptions {
  root: THREE.Object3D;
  /** The model's own yaw on the root (π for a VRM 0.x, 0 for a 1.0). */
  baseYaw: number;
  /** Standing hips height of the rig (m). */
  hipsHeight: number;
  /**
   * Where the seated clip holds the hips above the root (m): the standing
   * height for the procedural one, which keeps them at rest; the measured
   * height for the Unity workshop's (≈ 0.567). The root rises or sinks by
   * the difference so the hips land on the seat. Absent: `hipsHeight`.
   */
  seatedHipsHeight?: () => number;
  /**
   * Seated, may she get up now? Her desk keeps her until its chair is back
   * at its place by her own gestures (desk/DeskChoreography.ts): the wanted
   * place waits. Absent: always.
   */
  holdSeat?: () => boolean;
  /**
   * Her walking pace (m/s): the walk clip's own (the workshop's capture,
   * ≈ 0.89 — Unity walks her at 0.9), so its feet keep the ground at its
   * natural cadence. Absent: the procedural walk's WALK_SPEED.
   */
  walkSpeed?: () => number;
  body: LocomotionBody;
}

type Phase =
  | "settled"
  | "rising" // seat → floor
  | "unlying" // bed → bed edge
  | "turning" // in place, toward the first leg of the path
  | "walking"
  | "facing" // in place, toward what the place is about
  | "sitting" // floor → seat
  | "lying"; // bed edge → bed

const RISE_S = 0.95;
const SIT_S = 1.05;
const LIE_S = 1.7;
/** Where she stands before sitting without the capture: a little before the seat, her back to it (Unity's StandOff). */
const STAND_OFF = 0.2;
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

const NO_DRIVE = { yaw: 0, roll: 0 } as const;
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
}

interface Prop {
  obj: THREE.Object3D;
  rest: THREE.Vector3;
  restRot: THREE.Quaternion;
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

  // A place's chair (the desk's), moved only by her desk's gestures.
  private props = new Map<PlaceId, Prop>();
  /** How her desk's gestures leave the seat she is on (see setSeatDrive). */
  private drive = { yaw: 0, roll: 0 };

  // Tween.
  private t = 0;
  private dur = 1;
  private from: Pose = { pos: { x: 0, z: 0 }, height: 0, facing: 0, lie: 0 };
  private to: Pose = { pos: { x: 0, z: 0 }, height: 0, facing: 0, lie: 0 };
  /** The tween follows a captured transition clip (linear root, the clip's own pace). */
  private captured: "sit" | "stand" | null = null;

  private path: Vec2[] = [];
  /**
   * Which waypoints are steps around a seat (into it, out of it): walked
   * straight, after turning on the spot — the Unity client's `Step`. A walk
   * rounds its corners by the turn rate, and round a chair that cut through
   * the armrest.
   */
  private steps: boolean[] = [];
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
   * The room's chair for a place (the `DeskChair` object), once the room has
   * loaded: its current transform is its rest. She walks round it to sit.
   */
  setProp(place: PlaceId, obj: THREE.Object3D | null): void {
    if (!obj) {
      this.props.delete(place);
      return;
    }
    this.props.set(place, { obj, rest: obj.position.clone(), restRot: obj.quaternion.clone() });
    this.applyChair();
  }

  /**
   * Seated at a place with a chair, the chair as her desk's gestures leave
   * it (the Unity client's `ChairRig`): swivelled `yaw` degrees to her right
   * on its foot, rolled `roll` metres toward the desk along the seat's
   * forward at home — and she, sitting on it, turns and rolls with it.
   */
  setSeatDrive(yaw: number, roll: number): void {
    this.drive.yaw = yaw;
    this.drive.roll = roll;
  }

  /** Seated and settled, the backend wants her elsewhere: she is about to get up. */
  get wantsToLeave(): boolean {
    return this.phase === "settled" && this.posture === "sit" && this.target !== null && this.target !== this.place;
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
    // rising / sitting / lying / unlying: picked up when the tween ends.
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
        // A departure the seat held back (her desk bringing its chair home) goes as soon as it may.
        if (this.target && this.target !== this.place && this.posture === "sit" && !this.opts.holdSeat?.()) this.depart();
        break;
      case "rising":
      case "unlying":
      case "sitting":
      case "lying":
      case "facing":
        this.t += dt;
        this.applyTween(this.progress());
        if (this.done()) this.endTween();
        break;
      case "turning":
        this.updateTurning(dt);
        break;
      case "walking":
        this.updateWalking(dt);
        break;
    }
    this.compose();
  }

  /** Where the tween is: a captured transition at its clip's pace, the rest by the clock. */
  private progress(): number {
    if (this.captured) {
      const p = this.opts.body.transitionProgress?.(this.captured);
      if (p !== null && p !== undefined) return Math.min(1, p);
    }
    return Math.min(1, this.t / this.dur);
  }

  private done(): boolean {
    // A captured clip that stopped being reported (cut short): the clock ends it.
    return this.progress() >= 1 || this.t >= this.dur * 1.6 + 0.3;
  }

  /** Her walking pace now (m/s). */
  private cruise(): number {
    return this.opts.walkSpeed?.() ?? WALK_SPEED;
  }

  // ── Trip ──────────────────────────────────────────────────────────

  private depart(): void {
    if (this.posture === "lie") return this.startUnlie();
    if (this.posture === "sit") {
      if (this.opts.holdSeat?.()) return; // picked up by update() when the seat lets her go
      return this.startRise();
    }
    this.startWalk();
  }

  /** How far the sit-down (or stand-up) carries her hips, the capture's or the procedural step. */
  private travel(kind: "sit" | "stand"): number {
    return this.opts.body.transition?.(kind)?.travel ?? STAND_OFF;
  }

  /** Into a seat: from its approach, round its chair, to the front of the seat. */
  private intoSeat(place: Place): Vec2[] {
    const front = seatFront(place, this.travel("sit"));
    if (!front) return [];
    const corner = this.props.has(place.id) ? aroundChair(place, front, place.approach) : null;
    return corner ? [corner, front] : [front];
  }

  /** Out of a chair she has just got up from: round it, back to its approach. */
  private outOfSeat(place: Place): Vec2[] {
    if (!this.props.has(place.id) || dist(this.pos, place.approach) < 0.12) return [];
    const corner = aroundChair(place, this.pos, place.approach);
    return corner ? [corner, place.approach] : [place.approach];
  }

  private startWalk(): void {
    const place = this.target ? PLACES[this.target] : null;
    if (!place) return this.settle();
    const leaving = this.place && this.place !== this.target ? PLACES[this.place] : null;
    const out = leaving ? this.outOfSeat(leaving) : [];
    const start = out.length > 0 ? out[out.length - 1] : this.pos;
    const into = place.posture === "sit" ? this.intoSeat(place) : [];
    const walk = planPath(start, place.approach);
    this.setPath([...out, ...walk, ...into], out.length, into.length);
    if (this.path.length === 1 && dist(this.path[0], this.pos) < 0.05) {
      this.setPath([], 0, 0);
      return this.startFacing();
    }
    const heading = yawTo(this.pos, this.path[0]);
    if (Math.abs(wrapAngle(heading - this.facing)) > TURN_IN_PLACE) {
      this.phase = "turning";
      this.opts.body.walk(SHUFFLE_TIMESCALE);
    } else {
      this.phase = "walking";
      this.speed = this.cruise() * 0.6;
      this.opts.body.walk(this.speed / WALK_SPEED);
    }
  }

  private replan(): void {
    const place = this.target ? PLACES[this.target] : null;
    if (!place) return;
    const into = place.posture === "sit" ? this.intoSeat(place) : [];
    this.setPath([...planPath(this.pos, place.approach), ...into], 0, into.length);
  }

  /** A path whose first `lead` and last `tail` waypoints are steps around a seat. */
  private setPath(path: Vec2[], lead: number, tail: number): void {
    this.path = path;
    this.steps = path.map((_, i) => i < lead || i >= path.length - tail);
  }

  private updateTurning(dt: number): void {
    if (this.path.length === 0) return this.startFacing();
    const heading = yawTo(this.pos, this.path[0]);
    const err = wrapAngle(heading - this.facing);
    const step = Math.sign(err) * Math.min(Math.abs(err), TURN_RATE * dt);
    this.facing = wrapAngle(this.facing + step);
    if (Math.abs(err) < 0.25) {
      this.phase = "walking";
      this.speed = this.cruise() * 0.5;
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
    if (this.steps[0]) return this.updateStep(dt, next);
    const remaining = this.remaining();
    // Accelerate to cruise, slow into the last steps.
    const cruise = this.cruise() * (remaining < ARRIVE_ZONE ? Math.max(ARRIVE_MIN, remaining / ARRIVE_ZONE) : 1);
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
      this.steps.shift();
      step = 0;
      if (this.path.length === 0) return this.startFacing();
    }
    if (step > 0) {
      // Facing and true heading are blended so a sharp corner cannot carry
      // her into furniture while she is still turning.
      const dir = Math.abs(err) > 0.5 ? heading : this.facing;
      this.pos = { x: this.pos.x + Math.sin(dir) * step, z: this.pos.z + Math.cos(dir) * step };
    }
  }

  /** A step around a seat: turned toward it on the spot, then straight to it. */
  private updateStep(dt: number, next: Vec2): void {
    const toNext = dist(this.pos, next);
    const heading = toNext > 1e-4 ? yawTo(this.pos, next) : this.facing;
    const err = wrapAngle(heading - this.facing);
    if (Math.abs(err) > 0.12 && toNext > 0.04) {
      this.facing = wrapAngle(this.facing + Math.sign(err) * Math.min(Math.abs(err), TURN_RATE * dt));
      this.speed = 0;
      this.opts.body.walk(SHUFFLE_TIMESCALE);
      return;
    }
    // Slow steps (a walk's pace would not stop in a few decimetres).
    const cruise = this.cruise() * Math.max(ARRIVE_MIN, Math.min(1, toNext / ARRIVE_ZONE));
    this.speed += (cruise - this.speed) * Math.min(1, dt * 4);
    this.opts.body.walk(Math.max(0.35, this.speed / WALK_SPEED));
    this.facing = heading;
    const step = this.speed * dt;
    if (step >= toNext || toNext < 0.02) {
      this.pos = { x: next.x, z: next.z };
      this.path.shift();
      this.steps.shift();
      if (this.path.length === 0) this.startFacing();
      return;
    }
    this.pos = { x: this.pos.x + Math.sin(heading) * step, z: this.pos.z + Math.cos(heading) * step };
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

  /** Down onto the seat behind her: the capture carries her hips back, the root follows at its pace. */
  private startSit(): void {
    const place = this.target ? PLACES[this.target] : null;
    if (!place?.seat) return this.settle();
    this.posture = "sit";
    const to = { ...this.pose(), pos: { x: place.seat.x, z: place.seat.z }, height: this.seatOffset(place.seat), lie: 0 };
    const capture = this.opts.body.transition?.("sit");
    if (capture && this.opts.body.playTransition) {
      this.opts.body.playTransition("sit");
      this.tween("sitting", capture.seconds, to, "sit");
      return;
    }
    this.opts.body.posture("sit", SIT_S);
    this.tween("sitting", SIT_S, to);
  }

  /** Up over her feet: the capture carries her hips forward; then she steps out. */
  private startRise(): void {
    const place = this.place ? PLACES[this.place] : null;
    this.posture = "stand";
    const capture = this.opts.body.transition?.("stand");
    const front = place ? seatFront(place, capture?.travel ?? STAND_OFF) : null;
    const to = { ...this.pose(), pos: front ?? (place ? place.approach : this.pos), height: 0, lie: 0 };
    if (capture && this.opts.body.playTransition) {
      this.opts.body.playTransition("stand");
      this.tween("rising", capture.seconds, to, "stand");
      return;
    }
    this.opts.body.posture("stand", RISE_S);
    this.tween("rising", RISE_S, to);
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
      height: bed.seat ? this.seatOffset(bed.seat) : 0,
      facing: bed.facing,
      lie: 0,
    });
  }

  private endTween(): void {
    const phase = this.phase;
    const captured = this.captured;
    this.applyTween(1);
    this.captured = null;
    if (phase === "facing") {
      this.opts.body.walk(null);
      this.place = this.target;
      const place = this.target ? PLACES[this.target] : null;
      if (place?.posture === "sit") return this.startSit();
      return this.settle();
    }
    if (phase === "sitting") {
      // The capture over, the seated stance holds.
      if (captured) this.opts.body.posture("sit", 0.35);
      this.place = this.target;
      if (this.place === "bed" && this.sleep !== "awake") return this.startLie();
      return this.settle();
    }
    if (phase === "lying") return this.settle();
    if (phase === "unlying") {
      // Woken, or asked elsewhere: from the bed edge, carry on.
      if (this.target && this.target !== "bed") return this.startRise();
      return this.settle();
    }
    if (phase === "rising") {
      if (captured) this.opts.body.posture("stand", 0.35);
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
    this.setPath([], 0, 0);
    this.captured = null;
    this.opts.body.walk(null);
    this.facing = p.facing;
    this.lieBlend = 0;
    if (p.posture === "sit" && p.seat) {
      const lie = place === "bed" && this.sleep !== "awake";
      this.posture = lie ? "lie" : "sit";
      this.pos = { x: p.seat.x, z: p.seat.z };
      this.height = this.seatOffset(p.seat);
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

  /** How far the root goes down for her hips to sit on this seat (see SEAT_HIPS_ABOVE). */
  private seatOffset(seat: { height: number; sink: number }): number {
    return seat.height + SEAT_HIPS_ABOVE - seat.sink - (this.opts.seatedHipsHeight?.() ?? this.opts.hipsHeight);
  }

  /**
   * The seated clip changed under her (the workshop's arrived after the
   * procedural one): settled on a seat, her root is set again for it.
   */
  reseat(): void {
    if (this.phase !== "settled" || this.posture !== "sit" || !this.place) return;
    const seat = PLACES[this.place].seat;
    if (!seat) return;
    this.height = this.seatOffset(seat);
    this.compose();
  }

  private pose(): Pose {
    return { pos: { ...this.pos }, height: this.height, facing: this.facing, lie: this.lieBlend };
  }

  private tween(phase: Phase, dur: number, to: Pose, captured: "sit" | "stand" | null = null): void {
    this.phase = phase;
    this.t = 0;
    this.dur = Math.max(0.05, dur);
    this.captured = captured;
    this.from = this.pose();
    this.to = { ...to, pos: { ...to.pos } };
  }

  private applyTween(p: number): void {
    const f = this.from;
    const t = this.to;
    let kPos = smooth(p);
    let kHeight = smooth(p);
    if (this.captured === "sit") {
      // The capture's own travel, taken out of its hips and given back to the
      // root at its pace; the root rises to the seat as the hips go down.
      kPos = p;
      kHeight = smooth((p - 0.35) / 0.6);
    } else if (this.captured === "stand") {
      // The root back on the floor while the legs push (the first part).
      kPos = p;
      kHeight = smooth(p / 0.6);
    }
    this.pos = { x: f.pos.x + (t.pos.x - f.pos.x) * kPos, z: f.pos.z + (t.pos.z - f.pos.z) * kPos };
    this.height = f.height + (t.height - f.height) * kHeight;
    const k = smooth(p);
    this.facing = f.facing + wrapAngle(t.facing - f.facing) * k;
    this.lieBlend = f.lie + (t.lie - f.lie) * k;
  }

  /** The seat drive in force: seated and settled at a place with a chair, else none. */
  private activeDrive(): { yaw: number; roll: number } {
    const seated = this.posture === "sit" && this.place !== null && this.props.has(this.place) && this.phase === "settled";
    return seated ? this.drive : NO_DRIVE;
  }

  private applyChair(): void {
    const d = this.activeDrive();
    for (const [place, prop] of this.props) {
      const driven = place === this.place ? d : NO_DRIVE;
      // Rolled toward the desk along the seat's forward at home.
      const { ahead } = placeFrame(PLACES[place]);
      prop.obj.position.set(prop.rest.x + ahead.x * driven.roll, prop.rest.y, prop.rest.z + ahead.z * driven.roll);
      // Swivelled on its foot, to her right (a negative turn about +Y).
      prop.obj.quaternion.setFromAxisAngle(_Y, (-driven.yaw * Math.PI) / 180).multiply(prop.restRot);
    }
  }

  private compose(): void {
    this.applyChair();
    const root = this.opts.root;
    // On a chair her desk's gestures move: she turns and rolls with it.
    const d = this.activeDrive();
    const home = this.place ? PLACES[this.place].facing : this.facing;
    _qBase.setFromAxisAngle(_Y, this.opts.baseYaw);
    _qUp.setFromAxisAngle(_Y, this.facing - (d.yaw * Math.PI) / 180).multiply(_qBase);
    let x = this.pos.x + Math.sin(home) * d.roll;
    let y = this.height;
    let z = this.pos.z + Math.cos(home) * d.roll;
    if (this.lieBlend > 0) {
      const lie = PLACES.bed.lie!;
      // Face up, head toward headYaw: Ry(headYaw + π) · Rx(−π/2) · base.
      _qLie
        .setFromAxisAngle(_Y, lie.headYaw + Math.PI)
        .multiply(_qTmp.setFromAxisAngle(_X, -Math.PI / 2))
        .multiply(_qBase);
      const dir = { x: Math.sin(lie.headYaw), z: Math.cos(lie.headYaw) };
      const lx = lie.x - dir.x * this.opts.hipsHeight;
      const lz = lie.z - dir.z * this.opts.hipsHeight;
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
