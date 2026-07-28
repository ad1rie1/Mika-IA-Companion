import type { SleepPhase } from "../../../types";
import type { OverlayContext, ProceduralOverlay } from "./Overlay";

// Breath frequency multiplier — slow, deep breathing while asleep.
const PHASE_BREATH_FREQUENCY: Record<SleepPhase, number> = {
  awake: 1.5,
  light_sleep: 0.7,
  rem: 0.8,
  deep_sleep: 0.45,
};

// Breath amplitude multiplier — deeper chest motion in sleep.
const PHASE_BREATH_AMPLITUDE: Record<SleepPhase, number> = {
  awake: 1.0,
  light_sleep: 1.4,
  rem: 1.2,
  deep_sleep: 1.8,
};

const BASE_AMPLITUDE = 0.005; // radians — idle clips already breathe;
// this additive layer deepens it and carries the sleep-phase contrast.
const EASE_SECONDS = 1.2;

/** Additive spine pitch following a sine breath cycle. */
export class BreathingOverlay implements ProceduralOverlay {
  private timer = 0;
  private freq = PHASE_BREATH_FREQUENCY.awake;
  private amp = PHASE_BREATH_AMPLITUDE.awake;

  update(dt: number, ctx: OverlayContext): void {
    const rate = Math.min(1, (dt / EASE_SECONDS) * 4);
    this.freq += (PHASE_BREATH_FREQUENCY[ctx.sleepPhase] - this.freq) * rate;
    this.amp += (PHASE_BREATH_AMPLITUDE[ctx.sleepPhase] - this.amp) * rate;

    this.timer += dt * this.freq;
    const breathe = Math.sin(this.timer) * BASE_AMPLITUDE * this.amp;
    ctx.addRotation("spine", breathe, 0, 0);
  }
}
