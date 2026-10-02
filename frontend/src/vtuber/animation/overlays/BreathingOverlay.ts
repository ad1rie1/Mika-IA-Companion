import type { SleepPhase } from "../../../types";
import type { OverlayContext, ProceduralOverlay } from "./Overlay";

/**
 * Breathing — the motion a living body never stops making.
 *
 * The previous layer was a 0.005 rad sine on the spine: a metronome under
 * the clip's own (recorded, looping) breath. A human breath is none of
 * that: the inhale is quicker than the exhale and is followed by a short
 * pause, no two cycles have the same length or depth, it speeds up with
 * arousal and slows in sleep, every few minutes one breath is deeper than
 * the others, and while speaking it changes regime entirely — a quick
 * catch-breath before each clause, then a long slow exhale that carries
 * the words. A sigh is a big inhale and a long release with the shoulders
 * dropping.
 *
 * The fill (0 = empty, 1 = full lungs) lifts the chest and spine into a
 * slight extension and raises the shoulders; the neck takes back half of
 * the pitch so the face stays steady on whoever she is looking at. The
 * fill is published on the context (`ctx.breath`) for anyone riding it.
 */

/** Cycles per second at rest, before arousal. ~15/min awake. */
const PHASE_RATE_HZ: Record<SleepPhase, number> = {
  awake: 0.25,
  light_sleep: 0.2,
  rem: 0.23,
  deep_sleep: 0.16,
};
const PHASE_DEPTH: Record<SleepPhase, number> = {
  awake: 1.0,
  light_sleep: 1.3,
  rem: 1.15,
  deep_sleep: 1.5,
};

/** Share of the cycle spent inhaling / where the exhale ends (the rest is
 * the post-exhale pause). */
const INHALE_END = 0.36;
const EXHALE_END = 0.86;

/** Rare augmented breath ("soupir physiologique"), per resting cycle. */
const DEEP_BREATH_P = 0.07;

/** Bone deltas at fill = 1 (rad, VRM 1.0 convention). */
export const BREATH_SPINE_PITCH = -0.011;
export const BREATH_CHEST_PITCH = -0.016;
export const BREATH_SHOULDER_LIFT = 0.032;
/** Share of the torso pitch the neck gives back. */
const NECK_COMPENSATION = 0.5;

/** Speech regime: inhale speed (1/s) on a catch, exhale speed while
 * talking, and how full a catch-breath gets. */
const CATCH_RATE = 9;
const CATCH_SECONDS = 0.32;
const CATCH_FILL = 0.8;
const SPEECH_EXHALE_RATE = 0.28;
const SPEECH_FLOOR = 0.12;

/** A sigh, scripted as (time s, fill) keys. */
const SIGH: ReadonlyArray<readonly [number, number]> = [
  [0, 0],
  [1.0, 1.75],
  [1.3, 1.8],
  [3.2, -0.3],
  [4.0, 0],
];

function smooth(t: number): number {
  const x = Math.max(0, Math.min(1, t));
  return x * x * (3 - 2 * x);
}

/** Resting breath waveform over one cycle, p ∈ [0, 1). */
export function breathWave(p: number): number {
  if (p < INHALE_END) return smooth(p / INHALE_END);
  if (p < EXHALE_END) return 1 - smooth((p - INHALE_END) / (EXHALE_END - INHALE_END));
  return 0;
}

function sampleKeys(keys: ReadonlyArray<readonly [number, number]>, t: number): number {
  for (let i = 1; i < keys.length; i++) {
    const [t1, v1] = keys[i];
    if (t <= t1) {
      const [t0, v0] = keys[i - 1];
      return v0 + (v1 - v0) * smooth((t - t0) / Math.max(1e-6, t1 - t0));
    }
  }
  return keys[keys.length - 1][1];
}

export class BreathingOverlay implements ProceduralOverlay {
  private phase = Math.random();
  private cycleScale = 1;
  private depthScale = 1;
  private fill = 0;
  private catchRemaining = 0;
  private sighTime: number | null = null;
  private wasSpeaking = false;

  constructor(private readonly random: () => number = Math.random) {}

  update(dt: number, ctx: OverlayContext): void {
    const request = ctx.breathRequest;
    ctx.breathRequest = null;
    if (request === "sigh" && ctx.sleepPhase === "awake") this.sighTime = 0;
    else if (request === "catch") this.catchRemaining = CATCH_SECONDS;

    const a = ctx.sleepPhase === "awake" ? ctx.arousal : 0;
    const depth = PHASE_DEPTH[ctx.sleepPhase] * (1 - 0.15 * a);

    if (this.sighTime !== null) {
      this.sighTime += dt;
      this.fill = sampleKeys(SIGH, this.sighTime);
      if (this.sighTime >= SIGH[SIGH.length - 1][0]) {
        this.sighTime = null;
        this.phase = EXHALE_END; // resume after the release, in the pause
      }
    } else if (ctx.speaking && ctx.sleepPhase === "awake") {
      // Speech breathing: catch quickly, then let the words carry the air
      // out slowly. Never the resting sine while talking.
      if (this.catchRemaining > 0) {
        this.catchRemaining -= dt;
        this.fill += (CATCH_FILL * depth - this.fill) * Math.min(1, dt * CATCH_RATE);
      } else {
        this.fill += (SPEECH_FLOOR - this.fill) * Math.min(1, dt * SPEECH_EXHALE_RATE);
      }
      this.wasSpeaking = true;
    } else {
      if (this.wasSpeaking) {
        // Back to resting breath from wherever the speech left the lungs:
        // enter the cycle on its exhale, at the matching fill.
        this.wasSpeaking = false;
        this.phase = INHALE_END + (1 - Math.min(1, this.fill)) * (EXHALE_END - INHALE_END) * 0.5;
      }
      const rate =
        PHASE_RATE_HZ[ctx.sleepPhase] *
        Math.max(0.75, Math.min(1.5, 1 + 0.4 * a)) *
        (1 - 0.2 * ctx.fatigue);
      this.phase += (dt * rate) / this.cycleScale;
      if (this.phase >= 1) {
        this.phase -= 1;
        // No two breaths alike: each cycle draws its own length and depth.
        this.cycleScale = 0.85 + this.random() * 0.35;
        this.depthScale =
          ctx.sleepPhase === "awake" && this.random() < DEEP_BREATH_P
            ? 1.7
            : 0.8 + this.random() * 0.35;
      }
      const target = breathWave(this.phase) * depth * this.depthScale;
      // Eased rather than assigned: a speech→rest hand-over or a phase
      // change never jumps the chest.
      this.fill += (target - this.fill) * Math.min(1, dt * 8);
    }

    ctx.breath = this.fill;
    const f = this.fill;
    ctx.addRotation("spine", BREATH_SPINE_PITCH * f, 0, 0);
    ctx.addRotation("chest", BREATH_CHEST_PITCH * f, 0, 0);
    ctx.addRotation(
      "neck",
      -(BREATH_SPINE_PITCH + BREATH_CHEST_PITCH) * NECK_COMPENSATION * f,
      0,
      0
    );
    // The left shoulder points along +X: a positive roll lifts it; the
    // right one points along −X, so its lift is the opposite roll.
    ctx.addRotation("leftShoulder", 0, 0, BREATH_SHOULDER_LIFT * f);
    ctx.addRotation("rightShoulder", 0, 0, -BREATH_SHOULDER_LIFT * f);
  }
}
