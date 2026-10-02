import type { VRMHumanBoneName } from "@pixiv/three-vrm";
import type { OverlayContext, ProceduralOverlay } from "./Overlay";

/**
 * The life between the recorded frames.
 *
 * A Mixamo idle is a few seconds of motion capture on a loop: after the
 * third repetition the eye knows exactly when the shoulder will dip. A
 * standing person is never on a loop — the torso sways a little, the head
 * drifts and re-centres, the wrists turn, and every few seconds the weight
 * moves from one leg to the other and the posture re-settles. This layer
 * adds exactly that on top of whatever the clip does:
 *
 *   1. continuous micro-motion — per bone and axis, a sum of incommensurate
 *      sines (never visibly periodic), small enough to stay under the clip;
 *   2. weight shifts — at irregular intervals the torso leans to one side
 *      over a second or two and stays there, the chest and neck taking back
 *      part of it so the head stays level (people keep their eyes level);
 *   3. re-settles — now and then a quick, small posture adjustment of the
 *      neck and shoulders, the "fidget" that marks a live body.
 *
 * Arousal scales all of it: an anxious or excited body is busier, a sad or
 * bored one stiller; in sleep only a trace remains. Hips are left alone on
 * purpose — rotating them would slide the planted feet.
 */

interface NoiseChannel {
  bone: VRMHumanBoneName;
  axis: 0 | 1 | 2;
  /** Amplitude (rad) at arousal 0. */
  amp: number;
  /** Time scale of the noise (≈ Hz of its slowest component). */
  rate: number;
  seed: number;
  /** Extra amplitude while speaking (the upper body animates speech). */
  talk?: number;
}

/** Three incommensurate sines, normalised to ~[-1, 1]. */
export function lifeNoise(t: number, seed: number): number {
  return (
    (Math.sin(t * 6.283 + seed * 1.7) +
      Math.sin(t * 6.283 * 2.31 + seed * 3.9) * 0.55 +
      Math.sin(t * 6.283 * 3.73 + seed * 5.3) * 0.3) /
    1.85
  );
}

export const LIFE_CHANNELS: NoiseChannel[] = [
  { bone: "spine", axis: 0, amp: 0.008, rate: 0.11, seed: 1 },
  { bone: "spine", axis: 1, amp: 0.012, rate: 0.07, seed: 2 },
  { bone: "spine", axis: 2, amp: 0.01, rate: 0.09, seed: 3 },
  { bone: "chest", axis: 0, amp: 0.006, rate: 0.13, seed: 4 },
  { bone: "chest", axis: 1, amp: 0.012, rate: 0.1, seed: 5, talk: 1.6 },
  { bone: "chest", axis: 2, amp: 0.007, rate: 0.08, seed: 6 },
  { bone: "neck", axis: 0, amp: 0.012, rate: 0.19, seed: 7, talk: 1.4 },
  { bone: "neck", axis: 1, amp: 0.016, rate: 0.15, seed: 8, talk: 1.3 },
  { bone: "neck", axis: 2, amp: 0.012, rate: 0.13, seed: 9 },
  { bone: "leftShoulder", axis: 2, amp: 0.014, rate: 0.17, seed: 10, talk: 1.5 },
  { bone: "rightShoulder", axis: 2, amp: 0.014, rate: 0.21, seed: 11, talk: 1.5 },
  { bone: "leftUpperArm", axis: 0, amp: 0.014, rate: 0.09, seed: 12 },
  { bone: "leftUpperArm", axis: 2, amp: 0.016, rate: 0.12, seed: 13 },
  { bone: "rightUpperArm", axis: 0, amp: 0.014, rate: 0.1, seed: 14 },
  { bone: "rightUpperArm", axis: 2, amp: 0.016, rate: 0.14, seed: 15 },
  { bone: "leftHand", axis: 0, amp: 0.05, rate: 0.23, seed: 16, talk: 1.6 },
  { bone: "leftHand", axis: 2, amp: 0.04, rate: 0.29, seed: 17 },
  { bone: "rightHand", axis: 0, amp: 0.05, rate: 0.27, seed: 18, talk: 1.6 },
  { bone: "rightHand", axis: 2, amp: 0.04, rate: 0.31, seed: 19 },
];

/** Weight shift: lean of the spine (rad), and what the chest / neck give
 * back so the eyes stay level. */
export const SHIFT_LEAN = 0.03;
const SHIFT_CHEST_BACK = 0.45;
const SHIFT_NECK_BACK = 0.4;
const SHIFT_INTERVAL: [number, number] = [6, 17];
const SHIFT_SECONDS: [number, number] = [1.3, 2.4];

/** Re-settle: a quick small adjustment of neck and shoulders. */
const SETTLE_INTERVAL: [number, number] = [11, 30];
const SETTLE_SECONDS = 0.55;
const SETTLE_AMP = 0.035;

const AMP_EASE = 1.5;

function smooth(t: number): number {
  const x = Math.max(0, Math.min(1, t));
  return x * x * (3 - 2 * x);
}

export class LifeOverlay implements ProceduralOverlay {
  private time = 0;
  /** Eased global amplitude — a mood change retunes the body over ~1 s. */
  private gain = 1;
  private talkGain = 0;

  private lean = 0;
  private leanFrom = 0;
  private leanTo = 0;
  private shiftT = 1;
  private shiftDur = 1.8;
  private nextShift: number;

  private settle = { neckX: 0, neckY: 0, neckZ: 0, shoulders: 0 };
  private settleFrom = { ...this.settle };
  private settleTo = { ...this.settle };
  private settleT = 1;
  private nextSettle: number;

  private readonly rot = new Map<VRMHumanBoneName, [number, number, number]>();

  constructor(private readonly random: () => number = Math.random) {
    this.time = random() * 1000;
    this.nextShift = this.sample(SHIFT_INTERVAL);
    this.nextSettle = this.sample(SETTLE_INTERVAL);
  }

  update(dt: number, ctx: OverlayContext): void {
    this.time += dt;
    const awake = ctx.sleepPhase === "awake";
    const a = awake ? ctx.arousal : 0;
    // Busier when wired, stiller when drained; a trace in sleep.
    const target = awake
      ? Math.max(0.5, Math.min(1.6, 1 + 0.6 * a)) * (1 - 0.35 * ctx.fatigue)
      : 0.15;
    const ease = Math.min(1, dt * AMP_EASE);
    this.gain += (target - this.gain) * ease;
    this.talkGain += ((ctx.speaking ? 1 : 0) - this.talkGain) * ease;
    // Walking carries its own motion: only a trace of the standing sway.
    if (ctx.walking) this.gain = Math.min(this.gain, 0.35);
    // Anxious bodies move faster, sad ones slower.
    const tempo = 1 + 0.35 * a;

    this.rot.clear();
    const add = (bone: VRMHumanBoneName, axis: 0 | 1 | 2, v: number) => {
      let r = this.rot.get(bone);
      if (!r) this.rot.set(bone, (r = [0, 0, 0]));
      r[axis] += v;
    };

    for (const c of LIFE_CHANNELS) {
      const talk = 1 + ((c.talk ?? 1) - 1) * this.talkGain;
      add(c.bone, c.axis, lifeNoise(this.time * c.rate * tempo, c.seed) * c.amp * this.gain * talk);
    }

    if (awake && !ctx.walking) {
      this.updateShift(dt);
      this.updateSettle(dt, a);
    } else {
      // Asleep: the lean relaxes back to centre, no new events.
      this.lean += (0 - this.lean) * ease;
      this.nextShift = Math.max(this.nextShift, 2);
    }
    add("spine", 2, this.lean);
    add("chest", 2, -this.lean * SHIFT_CHEST_BACK);
    add("neck", 2, -this.lean * SHIFT_NECK_BACK);

    const s = this.settle;
    add("neck", 0, s.neckX);
    add("neck", 1, s.neckY);
    add("neck", 2, s.neckZ);
    add("leftShoulder", 2, s.shoulders);
    add("rightShoulder", 2, -s.shoulders);

    for (const [bone, [x, y, z]] of this.rot) ctx.addRotation(bone, x, y, z);
  }

  private updateShift(dt: number): void {
    if (this.shiftT < 1) {
      this.shiftT = Math.min(1, this.shiftT + dt / this.shiftDur);
      this.lean = this.leanFrom + (this.leanTo - this.leanFrom) * smooth(this.shiftT);
      return;
    }
    this.nextShift -= dt;
    if (this.nextShift > 0) return;
    // Mostly to the other side; sometimes just back toward the middle.
    const side = this.leanTo > 0 ? -1 : this.leanTo < 0 ? 1 : this.random() < 0.5 ? -1 : 1;
    const amount = this.random() < 0.25 ? 0.2 : 0.6 + this.random() * 0.4;
    this.leanFrom = this.lean;
    this.leanTo = side * SHIFT_LEAN * amount;
    this.shiftT = 0;
    this.shiftDur = this.sample(SHIFT_SECONDS);
    this.nextShift = this.sample(SHIFT_INTERVAL);
  }

  private updateSettle(dt: number, arousal: number): void {
    if (this.settleT < 1) {
      this.settleT = Math.min(1, this.settleT + dt / SETTLE_SECONDS);
      const k = smooth(this.settleT);
      const f = this.settleFrom;
      const t = this.settleTo;
      this.settle = {
        neckX: f.neckX + (t.neckX - f.neckX) * k,
        neckY: f.neckY + (t.neckY - f.neckY) * k,
        neckZ: f.neckZ + (t.neckZ - f.neckZ) * k,
        shoulders: f.shoulders + (t.shoulders - f.shoulders) * k,
      };
      return;
    }
    // Restless moods re-settle more often.
    this.nextSettle -= dt * (1 + Math.max(0, arousal));
    if (this.nextSettle > 0) return;
    const r = () => (this.random() * 2 - 1) * SETTLE_AMP;
    this.settleFrom = { ...this.settle };
    this.settleTo = { neckX: r() * 0.6, neckY: r(), neckZ: r() * 0.7, shoulders: r() * 0.5 };
    this.settleT = 0;
    this.nextSettle = this.sample(SETTLE_INTERVAL);
  }

  private sample([lo, hi]: [number, number]): number {
    return lo + this.random() * (hi - lo);
  }
}
