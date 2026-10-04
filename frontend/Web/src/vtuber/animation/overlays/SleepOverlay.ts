import type { SleepPhase } from "../../../types";
import type { OverlayContext, ProceduralOverlay } from "./Overlay";

// Slight forward head tilt during sleep — avatar visibly "dozes".
const PHASE_HEAD_TILT: Record<SleepPhase, number> = {
  awake: 0,
  light_sleep: 0.12,
  rem: 0.18,
  deep_sleep: 0.25,
};

const EASE_SECONDS = 1.2;

/** Additive neck doze-tilt per sleep phase. Being additive, it needs no
 * "reset the bone on wake" bookkeeping: not contributing IS zero. */
export class SleepOverlay implements ProceduralOverlay {
  private tilt = 0;

  update(dt: number, ctx: OverlayContext): void {
    const target = PHASE_HEAD_TILT[ctx.sleepPhase];
    const rate = Math.min(1, (dt / EASE_SECONDS) * 4);
    this.tilt += (target - this.tilt) * rate;
    if (Math.abs(this.tilt) < 0.0005) {
      this.tilt = target === 0 ? 0 : this.tilt;
      if (this.tilt === 0) return;
    }
    ctx.addRotation("neck", this.tilt, 0, 0);
  }
}
