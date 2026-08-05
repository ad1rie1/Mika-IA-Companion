import type { EmotionName, SleepPhase } from "../../types";
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

/** Blink shapes, in seconds. A real blink closes fast and opens slower;
 * a single fixed timing for every blink is what makes an avatar read as
 * a metronome. */
interface BlinkShape {
  close: number;
  hold: number;
  open: number;
}

const QUICK: BlinkShape = { close: 0.055, hold: 0.02, open: 0.09 };
const SOFT: BlinkShape = { close: 0.13, hold: 0.07, open: 0.2 };

// Alert emotions blink more often; low-energy ones blink slower and
// favour the long, heavy-lidded blink.
const RESTLESS = new Set<EmotionName>([
  "excited", "scared", "anxious", "surprised", "angry", "frustrated",
]);
const HEAVY = new Set<EmotionName>([
  "bored", "dreamy", "melancholic", "sad", "lonely", "relieved", "nostalgic",
]);

/**
 * Blink cycle + sleep eye closure + REM flicker, on the "blink"
 * expression only. Expressions are orthogonal to the bone-clip system.
 *
 * Three blink flavours (quick / double / soft), an emotion-modulated
 * cadence, and a slightly faster rate while speaking — a single blink
 * pattern on a loop is one of the strongest "it's a rig" tells, and the
 * blink is most of what the face does when no emotion is active.
 */
export class BlinkController implements ProceduralOverlay {
  private blinkTimer = 0;
  private nextBlinkAt = 3 + Math.random() * 2;
  private eyeClosure = 0;
  private remFlickerTimer = 0;

  // Current blink in flight
  private blinking = false;
  private elapsed = 0;
  private shape: BlinkShape = QUICK;
  /** A second quick blink follows this one (human double-blink). */
  private doublePending = false;
  /** The blink about to start IS that second beat — it never re-rolls. */
  private secondBeatArmed = false;

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
      this.updateBlink(dt, ctx, manager);
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
    ctx: OverlayContext,
    manager: NonNullable<OverlayContext["vrm"]["expressionManager"]>
  ): void {
    if (!this.blinking) {
      this.blinkTimer += dt;
      if (this.blinkTimer >= this.nextBlinkAt) this.startBlink(ctx);
      else return;
    }

    this.elapsed += dt;
    const { close, hold, open } = this.shape;
    const total = close + hold + open;

    let value: number;
    if (this.elapsed < close) {
      value = this.elapsed / close;
    } else if (this.elapsed < close + hold) {
      value = 1;
    } else if (this.elapsed < total) {
      value = 1 - (this.elapsed - close - hold) / open;
    } else {
      value = 0;
      this.blinking = false;
      this.blinkTimer = 0;
      if (this.doublePending) {
        // Second beat of a double blink: a short gap, then another quick
        // one. The flag hands over to secondBeatArmed rather than being
        // simply consumed — startBlink runs 70ms later and has to know
        // that this next blink is the beat, not a new draw.
        this.doublePending = false;
        this.secondBeatArmed = true;
        this.nextBlinkAt = 0.07;
      } else {
        this.nextBlinkAt = this.sampleInterval(ctx);
      }
    }
    manager.setValue("blink", Math.max(0, Math.min(1, value)));
  }

  private startBlink(ctx: OverlayContext): void {
    this.blinking = true;
    this.elapsed = 0;
    this.blinkTimer = 0;
    if (this.secondBeatArmed) {
      // Forced quick, and deliberately no re-roll: a draw here would let
      // the beat come out SOFT (a slow blink 70ms after a quick one reads
      // as a glitch, not as a tic) and could arm yet another double.
      this.secondBeatArmed = false;
      this.shape = QUICK;
      return;
    }

    const heavy = HEAVY.has(ctx.emotion);
    const roll = Math.random();
    if (roll < (heavy ? 0.45 : 0.15)) {
      this.shape = SOFT;
    } else {
      this.shape = QUICK;
      // Doubles only on quick blinks, and not when heavy-lidded.
      this.doublePending = !heavy && roll > 0.85;
    }
  }

  private sampleInterval(ctx: OverlayContext): number {
    let base = 2.5 + Math.random() * 3;
    if (RESTLESS.has(ctx.emotion)) base *= 0.65;
    else if (HEAVY.has(ctx.emotion)) base *= 1.3;
    if (ctx.speaking) base *= 0.85; // people blink more while talking
    return base;
  }
}
