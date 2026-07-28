import type { SleepPhase } from "../../types";
import type { OverlayContext, ProceduralOverlay } from "./overlays/Overlay";

// Target eye-closure per phase — awake lets the regular blink cycle
// drive the eyes; the sleep phases hold them near-closed continuously.
const PHASE_EYE_CLOSURE: Record<SleepPhase, number> = {
  awake: 0,
  light_sleep: 0.85,
  rem: 0.95, // still closed but eyelids "flicker" (REM)
  deep_sleep: 1.0,
};

const EASE_SECONDS = 1.2;

/**
 * Blink cycle + sleep eye closure + REM flicker, on the "blink"
 * expression only. Expressions are orthogonal to the bone-clip system,
 * so this survived the rewrite nearly verbatim (from the old custom
 * AnimationMixer class).
 */
export class BlinkController implements ProceduralOverlay {
  private blinkTimer = 0;
  private blinkInterval = 3 + Math.random() * 2;
  private isBlinking = false;
  private blinkProgress = 0;
  private eyeClosure = 0;
  private remFlickerTimer = 0;

  update(dt: number, ctx: OverlayContext): void {
    const manager = ctx.vrm.expressionManager;
    if (!manager) return;

    // Ease toward the phase's closure target.
    const target = PHASE_EYE_CLOSURE[ctx.sleepPhase];
    const rate = Math.min(1, (dt / EASE_SECONDS) * 4);
    const diff = target - this.eyeClosure;
    this.eyeClosure = Math.abs(diff) < 0.0005 ? target : this.eyeClosure + diff * rate;

    if (ctx.sleepPhase === "awake") {
      // Residual closure right after waking: blend it down before the
      // normal blink cycle takes over.
      if (this.eyeClosure > 0.02) {
        manager.setValue("blink", this.eyeClosure);
        return;
      }
      this.updateBlink(dt, manager);
      return;
    }

    let value = this.eyeClosure;
    // Flicker only once the lids are actually near the REM closure —
    // its 0.7 floor otherwise snaps the eyes shut on a direct
    // awake→rem transition (page load mid-REM, Alt+S, debug endpoint)
    // instead of the 1.2s ease every other phase change gets.
    if (ctx.sleepPhase === "rem" && this.eyeClosure > 0.75) {
      this.remFlickerTimer += dt;
      value += Math.sin(this.remFlickerTimer * 8) * 0.04;
      value = Math.max(0.7, Math.min(1.0, value));
    }
    manager.setValue("blink", value);
  }

  private updateBlink(
    dt: number,
    manager: NonNullable<OverlayContext["vrm"]["expressionManager"]>
  ): void {
    this.blinkTimer += dt;

    if (!this.isBlinking && this.blinkTimer >= this.blinkInterval) {
      this.isBlinking = true;
      this.blinkProgress = 0;
      this.blinkTimer = 0;
      this.blinkInterval = 2.5 + Math.random() * 3;
    }

    if (this.isBlinking) {
      this.blinkProgress += dt * 8;
      let blinkValue: number;
      if (this.blinkProgress < 0.5) {
        blinkValue = this.blinkProgress * 2;
      } else if (this.blinkProgress < 1.0) {
        blinkValue = 1 - (this.blinkProgress - 0.5) * 2;
      } else {
        blinkValue = 0;
        this.isBlinking = false;
      }
      manager.setValue("blink", blinkValue);
    }
  }
}
