import { VRM } from "@pixiv/three-vrm";

export type SleepPhase = "awake" | "light_sleep" | "rem" | "deep_sleep";

// How long (seconds) to smoothly ease in/out of the sleep pose when
// phase transitions. A hard snap would make the avatar look glitchy.
const SLEEP_TRANSITION_DURATION = 1.2;

// Target eye-closure per phase — awake lets the regular blink cycle
// drive the eyes; the sleep phases hold them near-closed continuously.
const PHASE_EYE_CLOSURE: Record<SleepPhase, number> = {
  awake: 0,
  light_sleep: 0.85,
  rem: 0.95,       // still closed but eyelids "flicker" (REM)
  deep_sleep: 1.0,
};

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

// Slight forward head tilt during sleep — avatar visibly "dozes".
const PHASE_HEAD_TILT: Record<SleepPhase, number> = {
  awake: 0,
  light_sleep: 0.12,
  rem: 0.18,
  deep_sleep: 0.25,
};

export class AnimationMixer {
  private vrm: VRM | null = null;
  private blinkTimer = 0;
  private blinkInterval = 3 + Math.random() * 2;
  private isBlinking = false;
  private blinkProgress = 0;

  private breatheTimer = 0;
  private isSpeaking = false;

  // Sleep state: target values come from `sleepPhase`; current values
  // are eased toward the target so transitions look natural.
  private sleepPhase: SleepPhase = "awake";
  private eyeClosureCurrent = 0;
  private breathFreqCurrent = 1.5;
  private breathAmpCurrent = 1.0;
  private headTiltCurrent = 0;
  // REM flicker: during REM phase, eyelids oscillate slightly for realism.
  private remFlickerTimer = 0;

  setVRM(vrm: VRM) {
    this.vrm = vrm;
  }

  setSpeaking(speaking: boolean) {
    this.isSpeaking = speaking;
  }

  getIsSpeaking(): boolean {
    return this.isSpeaking;
  }

  setSleepPhase(phase: SleepPhase): void {
    if (this.sleepPhase === phase) return;
    this.sleepPhase = phase;
  }

  getSleepPhase(): SleepPhase {
    return this.sleepPhase;
  }

  update(delta: number) {
    if (!this.vrm) return;

    // Ease toward the current phase's target values. Using a time-based
    // linear ease keeps the code simple and the motion feels natural.
    this.easeSleepTargets(delta);

    if (this.sleepPhase === "awake") {
      this.updateBlink(delta);
    } else {
      this.updateSleepEyes(delta);
    }
    this.updateBreathe(delta);
    this.updateHeadPose();
    // Lip sync is now handled by LipSyncController
  }

  private easeSleepTargets(delta: number) {
    const rate = delta / SLEEP_TRANSITION_DURATION;
    const stepToward = (cur: number, target: number) => {
      const diff = target - cur;
      if (Math.abs(diff) < 0.0005) return target;
      return cur + diff * Math.min(1, rate * 4);
    };
    this.eyeClosureCurrent = stepToward(
      this.eyeClosureCurrent,
      PHASE_EYE_CLOSURE[this.sleepPhase]
    );
    this.breathFreqCurrent = stepToward(
      this.breathFreqCurrent,
      PHASE_BREATH_FREQUENCY[this.sleepPhase]
    );
    this.breathAmpCurrent = stepToward(
      this.breathAmpCurrent,
      PHASE_BREATH_AMPLITUDE[this.sleepPhase]
    );
    this.headTiltCurrent = stepToward(
      this.headTiltCurrent,
      PHASE_HEAD_TILT[this.sleepPhase]
    );
  }

  private updateBlink(delta: number) {
    if (!this.vrm?.expressionManager) return;

    // If we still have residual sleep eye-closure (just woke up), blend
    // it down rather than firing the normal blink cycle immediately.
    if (this.eyeClosureCurrent > 0.02) {
      this.vrm.expressionManager.setValue("blink", this.eyeClosureCurrent);
      return;
    }

    this.blinkTimer += delta;

    if (!this.isBlinking && this.blinkTimer >= this.blinkInterval) {
      this.isBlinking = true;
      this.blinkProgress = 0;
      this.blinkTimer = 0;
      this.blinkInterval = 2.5 + Math.random() * 3;
    }

    if (this.isBlinking) {
      this.blinkProgress += delta * 8;
      // Blink curve: quick close, slower open
      let blinkValue: number;
      if (this.blinkProgress < 0.5) {
        blinkValue = this.blinkProgress * 2;
      } else if (this.blinkProgress < 1.0) {
        blinkValue = 1 - (this.blinkProgress - 0.5) * 2;
      } else {
        blinkValue = 0;
        this.isBlinking = false;
      }
      this.vrm.expressionManager.setValue("blink", blinkValue);
    }
  }

  private updateSleepEyes(delta: number) {
    if (!this.vrm?.expressionManager) return;
    let value = this.eyeClosureCurrent;
    // REM flicker: small oscillation on top of the base closure
    if (this.sleepPhase === "rem") {
      this.remFlickerTimer += delta;
      value += Math.sin(this.remFlickerTimer * 8) * 0.04;
      value = Math.max(0.7, Math.min(1.0, value));
    }
    this.vrm.expressionManager.setValue("blink", value);
  }

  private updateBreathe(delta: number) {
    if (!this.vrm?.humanoid) return;

    this.breatheTimer += delta * this.breathFreqCurrent;
    // Subtle breathing motion on the spine; amplitude scales with sleep depth
    const spine = this.vrm.humanoid.getNormalizedBoneNode("spine");
    if (spine) {
      const baseAmplitude = 0.005;
      const breatheAmount =
        Math.sin(this.breatheTimer) * baseAmplitude * this.breathAmpCurrent;
      spine.rotation.x = breatheAmount;
    }
  }

  private updateHeadPose() {
    if (!this.vrm?.humanoid) return;
    if (this.headTiltCurrent < 0.005) return;
    // Tilt the head forward as if dozing. Only touches the neck bone so
    // it coexists cleanly with any other head-rotation logic.
    const neck = this.vrm.humanoid.getNormalizedBoneNode("neck");
    if (neck) {
      neck.rotation.x = this.headTiltCurrent;
    }
  }
}
