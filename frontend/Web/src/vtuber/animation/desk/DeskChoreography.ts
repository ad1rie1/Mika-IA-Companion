/**
 * Her desk, as the Unity client plays it (`BodyActivity`, the desk part):
 * the animation workshop's clips (`desk_*`, `chair_*`), made against the
 * real desk for NAMED POSITIONS of the chair — measured in the workshop
 * (frontend/Unity/ArtSource/atelier/desk_plan.json, the seat's frame):
 *
 *   - « home »: where she sits down and gets up, the chair at its place;
 *   - « type »: swivelled 19.45° to her right and rolled 25.5 cm toward the
 *     desk, the keyboard before her (typing, the mouse, a sip from her mug,
 *     her pen taken to look at, thinking, stretching);
 *   - « write »: turned 45° to her left from « type », the notebook before her;
 *   - turned ±45° or ±90° from « type » or « home », toward whoever talks to her.
 *
 * She goes from one to the next by a GESTURE: pulling herself to the desk or
 * pushing away from it, hands on its edge (chair_pull_in, chair_push_out);
 * swivelling, her feet pushing the floor (chair_turn_*); taking the pen from
 * the notebook or laying it back (desk_write_start, desk_write_end). The
 * chair follows the gesture's own curves frame by frame (ChairYaw, ChairRoll:
 * how far it has gone, 0 → 1): it never moves without her. The mug and the
 * pen stay where they lie until a hand takes them (the Hold curve, carried
 * by DeskStage); the mouse follows her palm.
 *
 * Pure: no three.js, no clock — it reads its clips through a `DeskPlayer`
 * and is told the time. The angles are the workshop's (degrees, + to her
 * right), the roll in metres (+ toward the desk).
 */

export type DeskActivity = "work" | "draw" | null;
type Mode = "rest" | "type" | "write" | "lean";
export type DeskStop = "unknown" | "home" | "type" | "write";

export const TYPE_YAW = 19.45;
export const TYPE_ROLL = 0.2549;
export const WRITE_TURN = -45;
export const TURN_STEP = 45;
/** ±90° from « type » or « home » (the swivels checked in the workshop). */
export const MAX_TURN_STEPS = 2;
export const MAX_SWIVEL = 150;
/** Between two gestures, the next one's starting pose is held this long (the fade is 0.45 s). */
export const SETTLE_S = 0.5;
/** Turned toward someone, she stays so a little after they fall silent (s). */
export const ENGAGE_LINGER_S = 3;
/** The Hold curve above which the object is in her hand. */
export const CARRY_HOLD = 0.25;

/** Each pose of the desk and the workshop clip that plays it (BodyAnim.DeskClips). */
export const DESK_POSES: Readonly<Record<string, string>> = {
  desk: "desk_rest",
  type: "desk_type",
  mouse: "desk_mouse",
  write: "desk_write",
  read: "desk_read",
  lap: "desk_lap",
  lean_desk: "desk_think",
  drink: "desk_drink",
  take: "desk_take",
  stretch: "desk_stretch",
  turn_left_45: "chair_turn_left_45",
  turn_right_45: "chair_turn_right_45",
  turn_left_90: "chair_turn_left_90",
  turn_right_90: "chair_turn_right_90",
  pull_in: "chair_pull_in",
  push_out: "chair_push_out",
  write_start: "desk_write_start",
  write_end: "desk_write_end",
};

/** The poses whose hand holds something: the mug (drink), the pen (take, and the writing ones). */
const CARRY_POSES: readonly string[] = ["write_end", "write", "write_start", "drink", "take"];

/** What the choreography needs from the body that plays its clips. */
export interface DeskPlayer {
  /** This pose's clip is loaded. */
  has(pose: string): boolean;
  /** Ask for this pose's clip (a one-shot plays once; `restart` replays it). */
  play(pose: string, restart: boolean): void;
  /** This pose's clip owns the body alone (its fade-in done). */
  settled(pose: string): boolean;
  /** How far into this pose's clip she is, in cycles (0.5: half way; a loop goes on past 1); null if it is not playing. */
  progress(pose: string): number | null;
  /** The clip's length (s). */
  seconds(pose: string): number;
  /** One of the clip's curves (ChairYaw, ChairRoll, Hold) where it is now; 0 if it is not playing. */
  curve(pose: string, name: string): number;
}

export interface DeskInput {
  /** What she does at her desk (the backend's activity). */
  activity: DeskActivity;
  /** Someone talks to her: where they are (degrees, + to her right) from the seat's forward at home; null: nobody. */
  companion: number | null;
  /** She is about to get up: the chair goes home first, the pen back. */
  leaving: boolean;
  keyboard: boolean;
  mug: boolean;
  pen: boolean;
  mouse: boolean;
}

/** A gesture that moves the chair (or the pen): from where to where, and how far it has gone. */
interface Gesture {
  pose: string;
  start: number;
  seconds: number;
  yaw0: number;
  roll0: number;
  yaw1: number;
  roll1: number;
  yawK: number;
  rollK: number;
  movesChair: boolean;
  to: DeskStop;
  toSteps: number;
}

export const baseYaw = (s: DeskStop) => (s === "type" ? TYPE_YAW : s === "write" ? TYPE_YAW + WRITE_TURN : 0);
export const baseRoll = (s: DeskStop) => (s === "type" || s === "write" ? TYPE_ROLL : 0);

/** The pose a gesture starts from: she settles into it before setting off. */
function startPose(gesture: string): string {
  return gesture === "push_out" ? "desk" : gesture === "write_end" ? "write" : "lap";
}

/** The signed difference b − a of two angles, in (−180, 180]. */
function deltaAngle(a: number, b: number): number {
  let d = (b - a) % 360;
  if (d > 180) d -= 360;
  if (d <= -180) d += 360;
  return d;
}

export class DeskChoreography {
  /** Where the chair is: swivel (deg, + to her right) and roll (m, + toward the desk). */
  yaw = 0;
  roll = 0;
  stop: DeskStop = "unknown";
  /** Turned this many 45° steps from `stop` (« home » or « type »). */
  steps = 0;
  /** The pen in her writing hand (between desk_write_start and desk_write_end). */
  penWriting = false;
  /** The pose her clips play (null: none yet). */
  pose: string | null = null;

  private poseStart = 0;
  private gesture: Gesture | null = null;
  private engagedSeen = -100;
  private mode: Mode = "rest";
  private activity: DeskActivity = null;
  private variant = 0;
  private workSwitch = 0;
  private onMouse = false;
  private mouseGrab: number | null = null;
  private idleAct: string | null = null;
  private idleActAt = 0;
  private requestedAct: string | null = null;
  private clipUntil = 0;
  private warnedMissing = false;

  constructor(
    private readonly player: DeskPlayer,
    private readonly random: () => number = Math.random
  ) {}

  /** The gesture under way, for a picture of where she is (« pull_in », « type », « home+90 »…). */
  get where(): string {
    if (this.gesture) return this.gesture.pose;
    if (this.stop === "unknown") return "?";
    return this.stop + (this.steps !== 0 ? `${this.steps > 0 ? "+" : ""}${this.steps * TURN_STEP}` : "");
  }

  /** Home, still, the pen put down, a moment on her lap: she can get up. */
  readyToStand(now: number): boolean {
    return (
      this.gesture === null &&
      !this.penWriting &&
      (this.stop === "home" || this.stop === "unknown") &&
      this.steps === 0 &&
      (this.pose === null || (this.pose === "lap" && now - this.poseStart > 0.4))
    );
  }

  /** The mouse is under her palm (the stage moves it with her hand). */
  get mouseInUse(): boolean {
    return this.pose === "mouse" && this.player.settled("mouse");
  }

  /** The object in one of her hands now, and how firmly (the gesture's Hold curve). */
  carry(): { object: "mug" | "pen"; hand: "left" | "right"; hold: number } | null {
    const pose = this.pose;
    if (!pose || !CARRY_POSES.includes(pose)) return null;
    const hold = this.player.curve(pose, "Hold");
    return {
      object: pose === "drink" ? "mug" : "pen",
      hand: pose === "drink" || pose === "take" ? "left" : "right",
      hold,
    };
  }

  /** She left her seat some other way (snapped elsewhere): the chair goes back to its place, the rest is forgotten. */
  reset(): void {
    this.yaw = 0;
    this.roll = 0;
    this.stop = "unknown";
    this.steps = 0;
    this.gesture = null;
    this.penWriting = false;
    this.pose = null;
    this.idleAct = null;
    this.requestedAct = null;
    this.idleActAt = 0;
    this.onMouse = false;
    this.mouseGrab = null;
  }

  /** Brought home by force (her gestures could not, or a clip is missing). */
  forceHome(): void {
    this.yaw = 0;
    this.roll = 0;
    this.stop = "home";
    this.steps = 0;
    this.gesture = null;
    this.penWriting = false;
  }

  update(now: number, input: DeskInput): void {
    if (this.stop === "unknown") this.survey();
    this.decide(input);
    const g = this.gesture;
    if (g) {
      this.driveChair(g);
      const progress = this.player.progress(g.pose);
      if ((progress !== null && progress >= 0.999) || now - g.start >= g.seconds * 1.5 + 0.5) this.finish(g);
      return;
    }
    // A hand gesture under way (a sip, the pen taken, a stretch) ends before anything else.
    if (this.idleAct !== null && this.idleAct !== "think" && now < this.clipUntil) return;
    const want = this.want(now, input);
    const next = this.next(want.target, want.steps, want.pen);
    if (next) {
      this.approach(next, now);
      return;
    }
    this.occupy(now, input);
  }

  // ── what to do, now ───────────────────────────────────────────────

  private decide(input: DeskInput): void {
    if (input.activity !== this.activity) {
      this.activity = input.activity;
      this.variant = Math.floor(this.random() * 3);
    }
    let mode: Mode;
    if (input.companion !== null) mode = "rest";
    else if (input.activity === "work" && input.keyboard) mode = "type";
    else if (input.activity === "draw") mode = "write";
    else mode = this.variant === 2 ? "lean" : "rest";
    if (mode !== this.mode) {
      this.mode = mode;
      this.variant = Math.floor(this.random() * 3);
    }
  }

  /** Where the chair must be: toward whoever talks, else before the work. */
  private want(now: number, input: DeskInput): { target: DeskStop; steps: number; pen: boolean } {
    if (input.leaving) return { target: "home", steps: 0, pen: false };
    if (input.companion !== null) this.engagedSeen = now;
    if (now - this.engagedSeen < ENGAGE_LINGER_S && (input.companion !== null || this.lastCompanion !== null)) {
      if (input.companion !== null) this.lastCompanion = input.companion;
      // Swivel by 45° or 90° (steps of her feet) from « type » or « home »: below 30°, her head is enough.
      const target: DeskStop = this.stop === "home" ? "home" : "type";
      const yaw0 = baseYaw(target);
      const rel = deltaAngle(yaw0, this.lastCompanion!);
      const current = target === this.stop ? this.steps : 0;
      let steps: number;
      // Keep the step under way while the person does not clearly leave it.
      if (Math.abs(rel - current * TURN_STEP) < TURN_STEP * 0.78) steps = current;
      else steps = Math.abs(rel) < 30 ? 0 : Math.max(-MAX_TURN_STEPS, Math.min(MAX_TURN_STEPS, Math.round(rel / TURN_STEP)));
      while (steps !== 0 && Math.abs(yaw0 + steps * TURN_STEP) > MAX_SWIVEL) steps -= Math.sign(steps);
      return { target, steps, pen: false };
    }
    this.lastCompanion = null;
    if (this.mode === "write") return { target: "write", steps: 0, pen: true };
    return { target: "type", steps: 0, pen: false };
  }

  private lastCompanion: number | null = null;

  /** The next gesture to bring the chair (and the pen) where they must be; null: they are. */
  private next(target: DeskStop, steps: number, pen: boolean): Gesture | null {
    // The pen laid back on the notebook first, before anything but writing.
    if (this.penWriting && !(target === "write" && steps === 0 && pen)) return this.stay("write_end", this.stop, this.steps);
    if (this.steps !== 0) {
      const d = target === this.stop ? steps - this.steps : -this.steps;
      return d !== 0 ? this.turn(d) : null;
    }
    switch (this.stop) {
      case "home":
        if (target === "home") return steps !== 0 ? this.turn(steps) : null;
        return this.make("pull_in", "home", "type");
      case "type":
        if (target === "type") return steps !== 0 ? this.turn(steps) : null;
        if (target === "write") return this.make("turn_left_45", "type", "write");
        return this.make("push_out", "type", "home");
      case "write":
        if (target === "write") return pen && !this.penWriting ? this.stay("write_start", "write", 0) : null;
        return this.make("turn_right_45", "write", "type");
    }
    return null;
  }

  private turn(d: number): Gesture {
    const n = Math.max(-MAX_TURN_STEPS, Math.min(MAX_TURN_STEPS, d));
    const pose = `${n > 0 ? "turn_right_" : "turn_left_"}${Math.abs(n) === 1 ? "45" : "90"}`;
    const y0 = baseYaw(this.stop) + this.steps * TURN_STEP;
    const r = baseRoll(this.stop);
    return this.gestureOf(pose, y0, r, y0 + n * TURN_STEP, r, this.stop, this.steps + n);
  }

  private make(pose: string, from: DeskStop, to: DeskStop): Gesture {
    return this.gestureOf(pose, baseYaw(from), baseRoll(from), baseYaw(to), baseRoll(to), to, 0);
  }

  private stay(pose: string, at: DeskStop, steps: number): Gesture {
    const y = baseYaw(at) + steps * TURN_STEP;
    const g = this.gestureOf(pose, y, baseRoll(at), y, baseRoll(at), at, steps);
    g.movesChair = false;
    return g;
  }

  private gestureOf(pose: string, yaw0: number, roll0: number, yaw1: number, roll1: number, to: DeskStop, toSteps: number): Gesture {
    return {
      pose,
      start: 0,
      seconds: this.player.seconds(pose),
      yaw0,
      roll0,
      yaw1,
      roll1,
      yawK: 0,
      rollK: 0,
      movesChair: true,
      to,
      toSteps,
    };
  }

  /**
   * Settle into the gesture's starting pose, then set off. The pen is laid
   * back only at the end of a line (the writing loop at the start of one of
   * its two lines), the mouse let go only where the hand took it.
   */
  private approach(g: Gesture, now: number): void {
    if (this.pose === "mouse" && !this.mouseAtGrab()) return;
    const start = startPose(g.pose);
    if (!this.player.has(g.pose)) {
      if (!this.warnedMissing) {
        this.warnedMissing = true;
        console.warn(`[desk] gesture « ${g.pose} » not loaded: the chair takes its place at once.`);
      }
      this.finish(g);
      return;
    }
    if (this.pose !== start || !this.player.settled(start) || now - this.poseStart < SETTLE_S) {
      this.setPose(start, now);
      return;
    }
    if (g.pose === "write_end" && !this.loopAt("write", 0.04, 0.5)) return;
    g.start = now;
    this.gesture = g;
    this.setPose(g.pose, now);
  }

  private finish(g: Gesture): void {
    if (g.movesChair) {
      this.yaw = g.yaw1;
      this.roll = g.roll1;
    }
    this.stop = g.to;
    this.steps = g.toSteps;
    if (g.pose === "write_start") this.penWriting = true;
    if (g.pose === "write_end") this.penWriting = false;
    if (this.gesture === g) this.gesture = null;
  }

  /** The chair follows the gesture's run (its pivot and roll curves, 0 → 1), never back. */
  private driveChair(g: Gesture): void {
    if (!g.movesChair) return;
    g.yawK = Math.max(g.yawK, clamp01(this.player.curve(g.pose, "ChairYaw")));
    if (g.roll0 !== g.roll1) g.rollK = Math.max(g.rollK, clamp01(this.player.curve(g.pose, "ChairRoll")));
    this.yaw = g.yaw0 + (g.yaw1 - g.yaw0) * g.yawK;
    this.roll = g.roll0 + (g.roll1 - g.roll0) * g.rollK;
  }

  /**
   * Arrived where she should be: what her hands do. Turned toward someone,
   * or at home, hands on her lap; before the notebook, she writes; before
   * the keyboard, her occupation.
   */
  private occupy(now: number, input: DeskInput): void {
    if (this.stop === "home" || this.steps !== 0) return this.setPose("lap", now);
    if (this.stop === "write") return this.setPose(this.penWriting ? "write" : "lap", now);
    const engaged = now - this.engagedSeen < ENGAGE_LINGER_S;
    // The mouse is let go only where the hand took it: it stays where it was.
    const onMouse = this.mode === "type" && this.onMouse && now < this.workSwitch && !engaged;
    if (this.pose === "mouse" && !onMouse && !this.mouseAtGrab()) return;
    if (engaged) return this.setPose("desk", now);
    switch (this.mode) {
      case "type":
        if (now >= this.workSwitch) {
          this.onMouse = !this.onMouse && input.mouse;
          this.workSwitch = now + (this.onMouse ? 3 + this.random() * 4 : 8 + this.random() * 10);
        }
        this.setPose(this.onMouse ? "mouse" : "type", now);
        break;
      case "lean":
        // Leaning on her elbows: the same life as at rest (a sip, her pen, a stretch); thinking is the stance.
        this.idle(now, "lean_desk", input);
        break;
      default:
        this.idle(now, "desk", input);
    }
  }

  /**
   * At rest at her desk: hands down (« desk », or leaning « lean_desk »),
   * and now and then she thinks, stretches, takes a sip, picks up her pen.
   */
  private idle(now: number, rest: string, input: DeskInput): void {
    // Thinking gives way to a requested gesture; a hand gesture finishes.
    if (this.idleAct !== null && now < this.clipUntil && !(this.idleAct === "think" && this.requestedAct !== null)) return;
    if (this.idleAct !== null) {
      this.idleAct = null;
      this.idleActAt = now + 15 + this.random() * 20;
    }
    if (this.idleActAt <= 0) this.idleActAt = now + 8 + this.random() * 12;
    let act = this.requestedAct;
    if (act === null && now >= this.idleActAt) {
      const roll = this.random();
      act = roll < 0.45 ? "think" : roll < 0.62 && input.mug ? "drink" : roll < 0.8 && input.pen ? "take" : "stretch";
    }
    // Leaning already, thinking is no further gesture.
    if (act === "think" && rest === "lean_desk") {
      this.requestedAct = null;
      this.idleActAt = now + 15 + this.random() * 20;
      act = null;
    }
    if (act !== null && this.player.has(act === "think" ? "lean_desk" : act)) {
      const pose = act === "think" ? "lean_desk" : act;
      // The same gesture again: through the resting hands first.
      if (this.pose === pose) {
        this.setPose(rest === pose ? "desk" : rest, now);
        this.requestedAct = act;
        return;
      }
      this.requestedAct = null;
      this.idleAct = act;
      this.setPose(pose, now, true);
      this.clipUntil = now + (act === "think" ? 9 + this.random() * 7 : this.player.seconds(act));
      return;
    }
    this.setPose(rest, now);
  }

  /** Play a small resting gesture now (« think », « drink », « take », « stretch ») instead of waiting for the draw. */
  request(gesture: "think" | "drink" | "take" | "stretch"): void {
    this.requestedAct = gesture;
  }

  private setPose(pose: string, now: number, restart = false): void {
    if (this.pose === pose && !restart) return;
    this.pose = pose;
    this.poseStart = now;
    if (pose !== "mouse") this.mouseGrab = null;
    this.player.play(pose, restart);
  }

  /** The pose's loop is at the start of one of its cycles (or at fraction `also`). */
  private loopAt(pose: string, window: number, also = -1): boolean {
    if (!this.player.settled(pose)) return true;
    const p = this.player.progress(pose);
    if (p === null) return true;
    const f = p - Math.floor(p);
    return f < window || (also >= 0 && f >= also && f < also + window);
  }

  /** The mouse loop has come back to where the hand took it (letting go leaves it at its place). */
  private mouseAtGrab(): boolean {
    if (this.pose !== "mouse" || !this.player.settled("mouse")) return true;
    const p = this.player.progress("mouse");
    if (p === null) return true;
    if (this.mouseGrab === null) return true; // never taken: nothing to put back
    const f = p - Math.floor(p);
    const d = Math.abs(f - this.mouseGrab);
    return Math.min(d, 1 - d) < 0.02;
  }

  /** Where the chair is on arriving (a named position, more or less); anywhere else, it is set back home. */
  private survey(): void {
    for (const s of ["home", "type", "write"] as const) {
      for (let k = -MAX_TURN_STEPS; k <= MAX_TURN_STEPS; k++) {
        if (s === "write" && k !== 0) continue;
        if (Math.abs(deltaAngle(this.yaw, baseYaw(s) + k * TURN_STEP)) > 2 || Math.abs(this.roll - baseRoll(s)) > 0.01) continue;
        this.stop = s;
        this.steps = k;
        return;
      }
    }
    this.yaw = 0;
    this.roll = 0;
    this.stop = "home";
    this.steps = 0;
  }

  /** Remember where the mouse was taken — for the stage, which only follows. */
  noteMouseTaken(): void {
    if (this.pose === "mouse" && this.mouseGrab === null) {
      const p = this.player.progress("mouse");
      if (p !== null) this.mouseGrab = p - Math.floor(p);
    }
  }
}

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}
