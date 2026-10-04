import type { OverlayContext, ProceduralOverlay } from "./Overlay";
import { lifeNoise } from "./LifeOverlay";
import type { BeatKind, SpeechBeat } from "../speechBeats";

/**
 * The head and brows punctuating speech.
 *
 * Talk clips rotate every few seconds, but nothing in them knows what is
 * being said: the head of a recorded clip nods on its own schedule. This
 * layer fires on the speech beats of the reply actually being spoken
 * (`speechBeats.ts`), when the speech cursor reaches them:
 *
 *   stress     a small nod on the word
 *   emphasis   a bigger nod, a slight turn, the brows flash
 *   question   chin up and head tilted on the last word, brows held up
 *   final      the nod that closes a statement
 *   pause      the head reorients a little; a quick breath is taken
 *   trail      a soft tilt, trailing off
 *   phraseStart  the head lifts a touch on a catch-breath
 *
 * Each axis is a damped spring (slightly underdamped: a real neck
 * overshoots a hair and settles), kicked by beats and pulled toward held
 * targets (the question tilt). Plus a continuous speech-rate head motion
 * while talking — people's heads are never still when they speak.
 *
 * It runs AFTER the attention head turn, so the gaze controller (which
 * runs after every head writer) keeps the eyes on the viewer through each
 * nod — the vestibulo-ocular reflex for free.
 */

class Spring {
  x = 0;
  v = 0;
  constructor(
    private readonly omega: number,
    private readonly zeta: number
  ) {}
  step(dt: number, target: number): number {
    // Semi-implicit Euler, sub-stepped: stable at any frame time we get.
    const n = Math.max(1, Math.ceil(dt / (1 / 120)));
    const h = dt / n;
    for (let i = 0; i < n; i++) {
      const a = -this.omega * this.omega * (this.x - target) - 2 * this.zeta * this.omega * this.v;
      this.v += a * h;
      this.x += this.v * h;
    }
    return this.x;
  }
  /** Velocity kick sized so the free response peaks at ≈ `peak`. */
  kick(peak: number): void {
    this.v += peak * this.omega * 1.7;
  }
}

/** Nod peak per beat (rad, + = head down). */
const NOD: Record<BeatKind, number> = {
  phraseStart: -0.025,
  stress: 0.045,
  emphasis: 0.075,
  pause: 0.02,
  trail: 0.016,
  question: 0,
  final: 0.055,
};
const BROW: Partial<Record<BeatKind, number>> = {
  phraseStart: 0.3,
  stress: 0.35,
  emphasis: 1,
  question: 0.6,
  trail: 0.25,
};
/** Beats that come with a quick catch-breath. */
const CATCH: ReadonlySet<BeatKind> = new Set(["phraseStart", "pause"]);

export const QUESTION_TILT = 0.075;
export const QUESTION_LIFT = -0.035;
const QUESTION_HOLD_S = 1.3;
const TRAIL_TILT = 0.04;
const TRAIL_HOLD_S = 1.2;
/** A beat whose position the cursor overshot by more than this many
 * characters (a resync jump) is skipped, not fired late in a burst. */
const STALE_CHARS = 12;
const BROW_DECAY = 3.2;

const NECK_SHARE = 0.4;

export class SpeechBodyOverlay implements ProceduralOverlay {
  private beats: SpeechBeat[] = [];
  /** Nobody starts talking on empty lungs: the first beat of an utterance
   * takes a breath whatever its kind. */
  private firstBreath = false;
  private next = 0;
  private lastCursor = -1;

  private pitch = new Spring(11, 0.5);
  private yaw = new Spring(8, 0.6);
  private roll = new Spring(5, 0.75);
  private pitchHold = 0;
  private yawHold = 0;
  private rollHold = 0;
  private holdRemaining = 0;
  private holdKind: BeatKind | null = null;
  private questionSide = 1;

  private emphasis = 0;
  private question = 0;
  private time = 0;
  private talk = 0;

  constructor(private readonly random: () => number = Math.random) {}

  /** "Got it": the small nod and brow lift of someone receiving a message
   * they are about to answer. Not a speech beat — fires while silent. */
  acknowledge(): void {
    this.pitch.kick(0.04);
    this.emphasis = Math.max(this.emphasis, 0.35);
  }

  /** A new utterance starts: its beats replace whatever was left. */
  begin(beats: SpeechBeat[]): void {
    this.beats = beats;
    this.next = 0;
    this.lastCursor = -1;
    this.firstBreath = true;
  }

  update(dt: number, ctx: OverlayContext): void {
    this.time += dt;
    const awake = ctx.sleepPhase === "awake";
    const speaking = ctx.speaking && awake;
    // A murmur to herself is not addressed to anyone: barely any beat.
    const scale =
      (ctx.persona === "inner" ? 0.35 : 1) *
      Math.max(0.55, Math.min(1.4, 1 + 0.45 * ctx.arousal));

    if (speaking) this.consume(ctx, scale);

    if (this.holdRemaining > 0) {
      this.holdRemaining -= dt;
      if (this.holdRemaining <= 0) {
        this.pitchHold = 0;
        this.rollHold = 0;
        this.yawHold *= 0.5;
        this.holdKind = null;
      }
    }
    if (!speaking) this.yawHold += (0 - this.yawHold) * Math.min(1, dt * 0.8);

    this.talk += ((speaking ? 1 : 0) - this.talk) * Math.min(1, dt * 3);
    const pitch = this.pitch.step(dt, this.pitchHold);
    const yaw = this.yaw.step(dt, this.yawHold);
    const roll = this.roll.step(dt, this.rollHold);

    // Continuous speech-rate motion: faster and smaller than the life
    // layer's drift, only while the voice runs.
    const k = this.talk * scale;
    const np = lifeNoise(this.time * 0.9, 31) * 0.012 * k;
    const ny = lifeNoise(this.time * 0.7, 37) * 0.016 * k;
    const nr = lifeNoise(this.time * 0.6, 41) * 0.01 * k;

    const p = pitch + np;
    const y = yaw + ny;
    const r = roll + nr;
    ctx.addRotation("neck", p * NECK_SHARE, y * NECK_SHARE, r * NECK_SHARE);
    ctx.addRotation("head", p * (1 - NECK_SHARE), y * (1 - NECK_SHARE), r * (1 - NECK_SHARE));

    const questionTarget = this.holdKind === "question" ? 1 : 0;
    this.question += (questionTarget - this.question) * Math.min(1, dt * 5);
    this.emphasis = Math.max(0, this.emphasis - dt * BROW_DECAY * Math.max(0.2, this.emphasis));
    ctx.speechEmphasis = this.emphasis;
    ctx.speechQuestion = this.question;
  }

  private consume(ctx: OverlayContext, scale: number): void {
    const cursor = ctx.speechCursor;
    if (cursor < 0 || this.beats.length === 0) return;
    if (cursor < this.lastCursor - 3) {
      // The voice re-seated the cursor backwards: re-arm from there.
      this.next = this.beats.findIndex((b) => b.at >= cursor);
      if (this.next < 0) this.next = this.beats.length;
    }
    this.lastCursor = cursor;
    while (this.next < this.beats.length && this.beats[this.next].at <= cursor) {
      const beat = this.beats[this.next++];
      if (cursor - beat.at <= STALE_CHARS) this.fire(beat, ctx, scale);
    }
  }

  private fire(beat: SpeechBeat, ctx: OverlayContext, scale: number): void {
    const s = beat.strength * scale;
    this.pitch.kick(NOD[beat.kind] * s);
    this.emphasis = Math.min(1, Math.max(this.emphasis, (BROW[beat.kind] ?? 0) * s));
    if (CATCH.has(beat.kind) || this.firstBreath) ctx.breathRequest = ctx.breathRequest ?? "catch";
    this.firstBreath = false;

    switch (beat.kind) {
      case "emphasis":
        this.yaw.kick((this.random() < 0.5 ? -1 : 1) * 0.02 * s);
        break;
      case "pause":
        // Clauses re-aim the head a little, as speakers do between ideas.
        this.yawHold = (this.random() * 2 - 1) * 0.03 * scale;
        break;
      case "question":
        this.questionSide = this.random() < 0.7 ? this.questionSide : -this.questionSide;
        this.rollHold = this.questionSide * QUESTION_TILT * s;
        this.pitchHold = QUESTION_LIFT * s;
        this.holdRemaining = QUESTION_HOLD_S;
        this.holdKind = "question";
        break;
      case "trail":
        this.rollHold = (this.random() < 0.5 ? -1 : 1) * TRAIL_TILT * s;
        this.pitchHold = 0.015 * s;
        this.holdRemaining = TRAIL_HOLD_S;
        this.holdKind = "trail";
        break;
      case "final":
        this.pitchHold = 0;
        this.rollHold = 0;
        this.holdKind = null;
        break;
    }
  }
}
