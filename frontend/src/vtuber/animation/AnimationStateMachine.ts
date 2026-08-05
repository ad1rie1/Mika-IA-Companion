import * as THREE from "three";
import type {
  AnimationStateName,
  HandShapeName,
  SleepPhase,
} from "../../types";
import { ClipLibrary, REST_CLIP_NAME, type LoadedClip } from "./ClipLibrary";

// v2: flip when locomotion clips + the root-motion driver land. Until
// then "walking"/"interacting" are declared but unreachable.
export const LOCOMOTION_ENABLED = false;

// Per-edge crossfade durations (seconds). One primitive (playClip) does
// every transition — there is structurally no code path that snaps.
const FADE = {
  variation: 0.6, // idle→idle / talk→talk rotation
  toTalking: 0.4,
  toIdle: 0.5,
  gestureIn: 0.25, // default, per-clip fadeIn overrides
  gestureOut: 0.45, // default, per-clip fadeOut overrides
  gestureInterrupt: 0.2,
  toSleep: 1.2,
  sleepPhaseSwap: 1.0,
  wake: 1.0, // waking up is slow on purpose
  start: 0.5,
};

const DEFAULT_HOLD: Record<"idle" | "talking", [number, number]> = {
  idle: [8, 16],
  // Livelier rotation while talking — this cadence IS the "talk beats":
  // with a single base layer, gesticulation variety comes from rotating
  // the talk pool, not from a separate additive gesture layer.
  talking: [4, 9],
};

const sample = (range: [number, number]) =>
  range[0] + Math.random() * Math.max(0, range[1] - range[0]);

export interface StateMachineHooks {
  onHandShapes?: (left: HandShapeName, right: HandShapeName) => void;
}

/**
 * Body-animation state machine over a THREE.AnimationMixer rooted at
 * the VRM's normalized humanoid rig.
 *
 * States: idle (weighted multi-clip pool), talking (talk pool),
 * gesture (one-shot, fades back BEFORE the clip ends), sleeping
 * (parameterized by SleepPhase), walking/interacting (reserved v2).
 */
export class AnimationStateMachine {
  private mixer: THREE.AnimationMixer;
  private library: ClipLibrary;
  private hooks: StateMachineHooks;

  private _state: AnimationStateName = "idle";
  private started = false;
  private speaking = false;
  private sleepPhase: SleepPhase = "awake";

  private currentAction: THREE.AnimationAction | null = null;
  private currentClip: LoadedClip | null = null;

  private holdTimer = 0;
  private holdDuration = 10;

  // Gesture bookkeeping
  private gestureFadeOut = FADE.gestureOut;
  /** For looping "gestures" (e.g. thinking): seconds left before return. */
  private gestureHoldRemaining: number | null = null;
  /** 1-deep queue, newest wins. */
  private queuedGesture: LoadedClip | null = null;

  /** Emotion-driven idle override (sad/anxious/bored postures). */
  private idleVariant: string | null = null;

  // Debug: pinned clip pauses all scheduling (Alt+M / Alt+O).
  private debugPinned = false;
  private debugIndex = -1;

  constructor(
    mixer: THREE.AnimationMixer,
    library: ClipLibrary,
    hooks: StateMachineHooks = {}
  ) {
    this.mixer = mixer;
    this.library = library;
    this.hooks = hooks;
  }

  get state(): AnimationStateName {
    return this._state;
  }

  get currentClipName(): string | null {
    return this.currentClip?.name ?? null;
  }

  get clipTime(): number {
    return this.currentAction?.time ?? 0;
  }

  get clipDuration(): number {
    return this.currentClip?.clip.duration ?? 0;
  }

  start(): void {
    if (this.started) return;
    this.started = true;
    if (this.sleepPhase !== "awake") {
      this.enterSleeping(FADE.start);
    } else {
      this.enterBase(this.speaking ? "talking" : "idle", FADE.start);
    }
  }

  update(dt: number): void {
    if (!this.started || this.debugPinned) return;

    switch (this._state) {
      case "idle":
      case "talking": {
        this.holdTimer += dt;
        if (this.holdTimer >= this.holdDuration) {
          this.enterBase(this._state, FADE.variation);
        }
        break;
      }
      case "gesture": {
        this.updateGesture(dt);
        break;
      }
      case "sleeping":
      case "walking":
      case "interacting":
        break;
    }
  }

  // ── Inputs ────────────────────────────────────────────────────────

  setSpeaking(speaking: boolean): void {
    if (speaking === this.speaking) return;
    this.speaking = speaking;
    if (!this.started || this.debugPinned) return;
    if (this._state === "sleeping") return;
    if (this._state === "gesture") {
      // A gesture owns the base layer until it fades back; finishGesture
      // re-reads this.speaking, so the flip needs nothing but the flag.
      return;
    }
    this.enterBase(
      speaking ? "talking" : "idle",
      speaking ? FADE.toTalking : FADE.toIdle
    );
  }

  setSleepPhase(phase: SleepPhase): void {
    if (phase === this.sleepPhase) return;
    const prev = this.sleepPhase;
    this.sleepPhase = phase;
    if (!this.started || this.debugPinned) return;

    if (phase === "awake") {
      this.enterBase(this.speaking ? "talking" : "idle", FADE.wake);
      return;
    }
    // Falling asleep cancels any gesture immediately; a phase change
    // while already asleep just swaps clip/timeScale.
    this.queuedGesture = null;
    this.gestureHoldRemaining = null;
    this.enterSleeping(prev === "awake" ? FADE.toSleep : FADE.sleepPhaseSwap);
  }

  /** Emotion-driven idle override. null returns to the normal pool. */
  setIdleVariant(clipName: string | null): void {
    const resolved = clipName && this.library.has(clipName) ? clipName : null;
    if (resolved === this.idleVariant) return;
    this.idleVariant = resolved;
    if (this.started && !this.debugPinned && this._state === "idle") {
      this.enterBase("idle", FADE.variation);
    }
  }

  /** Play a one-shot (or briefly-held looping) gesture clip. Returns
   * false when the state forbids it (sleeping, not started). */
  requestGesture(loaded: LoadedClip): boolean {
    if (!this.started || this.debugPinned) return false;
    if (this._state === "sleeping" || this._state === "walking" || this._state === "interacting") {
      return false;
    }

    if (this._state === "gesture") {
      // Re-requesting the gesture that is ALREADY playing would land on
      // the same AnimationAction and hard-reset it to t=0 (a visible
      // snap, e.g. two [LAUGH] tokens in one reply) — treat it as
      // satisfied instead.
      if (this.currentClip?.name === loaded.name) return true;
      const progressed =
        this.clipDuration > 0 ? this.clipTime / this.clipDuration : 1;
      if (progressed >= 0.25) {
        // Newest wins once the running gesture had its moment.
        this.startGesture(loaded, FADE.gestureInterrupt);
      } else {
        this.queuedGesture = loaded; // newest overwrites
      }
      return true;
    }

    this.startGesture(loaded, loaded.meta.fadeIn ?? FADE.gestureIn);
    return true;
  }

  /** v2 seam: reserved states are declared but refuse to activate. */
  requestState(state: "walking" | "interacting"): boolean {
    if (!LOCOMOTION_ENABLED) {
      console.warn(`AnimationStateMachine: "${state}" is reserved for v2 (locomotion) — not implemented`);
      return false;
    }
    return false;
  }

  // ── Debug (Alt+M / Alt+O) ─────────────────────────────────────────

  /** Pin the next loaded clip (looped) so each retarget can be checked
   * visually in seconds. Pauses all scheduling until debugResume(). */
  debugCycleClip(): string {
    const names = this.library.listNames();
    if (names.length === 0) return "(no clips loaded)";
    this.debugPinned = true;
    this.debugIndex = (this.debugIndex + 1) % names.length;
    const loaded = this.library.get(names[this.debugIndex])!;
    this.playClip(loaded, 0.3, { forceLoop: true });
    return loaded.name;
  }

  debugResume(): void {
    if (!this.debugPinned) return;
    this.debugPinned = false;
    this.debugIndex = -1;
    if (this.sleepPhase !== "awake") this.enterSleeping(FADE.sleepPhaseSwap);
    else this.enterBase(this.speaking ? "talking" : "idle", FADE.toIdle);
  }

  /** Re-pick the base clip if we're still holding the synthetic rest
   * pose — called as downloaded clips stream in, so Mika comes alive
   * the moment the first real idle lands. */
  refreshBaseIfResting(): void {
    if (!this.started || this.debugPinned) return;
    if (
      (this._state === "idle" || this._state === "talking") &&
      this.currentClip?.name === REST_CLIP_NAME
    ) {
      this.enterBase(this._state, FADE.variation);
    } else if (this._state === "sleeping" && this.currentClip?.name === REST_CLIP_NAME) {
      this.enterSleeping(FADE.sleepPhaseSwap);
    }
  }

  // ── Internals ─────────────────────────────────────────────────────

  private updateGesture(dt: number): void {
    const action = this.currentAction;
    if (!action || !this.currentClip) {
      this.finishGesture();
      return;
    }
    if (this.gestureHoldRemaining !== null) {
      // Looping gesture (e.g. thinking): held for a sampled duration.
      this.gestureHoldRemaining -= dt;
      if (this.gestureHoldRemaining <= 0) this.finishGesture();
      return;
    }
    // One-shot: start the fade back BEFORE the end so there is never a
    // frame without a pose source. clampWhenFinished is the safety net —
    // a lag spike overshooting the window holds the last frame under the
    // crossfade instead of snapping to t=0. action.time is in clip
    // seconds; divide by |timeScale| to compare wall-clock durations.
    const speed = Math.max(1e-4, Math.abs(action.timeScale || 1));
    const remaining = (this.currentClip.clip.duration - action.time) / speed;
    if (remaining <= this.gestureFadeOut || !action.isRunning()) {
      this.finishGesture();
    }
  }

  private finishGesture(): void {
    const queued = this.queuedGesture;
    this.queuedGesture = null;
    if (queued) {
      this.startGesture(queued, queued.meta.fadeIn ?? FADE.gestureIn);
      return;
    }
    // Speaking may have flipped mid-gesture — the live flag decides.
    this.enterBase(this.speaking ? "talking" : "idle", this.gestureFadeOut);
  }

  private startGesture(loaded: LoadedClip, fadeIn: number): void {
    this._state = "gesture";
    this.gestureFadeOut = loaded.meta.fadeOut ?? FADE.gestureOut;
    const loops = loaded.meta.loop === true;
    this.playClip(loaded, fadeIn, { once: !loops });
    this.gestureHoldRemaining = loops
      ? sample(loaded.meta.hold ?? [3.5, 5.5])
      : null;
  }

  private enterBase(state: "idle" | "talking", fade: number): void {
    this._state = state;
    this.gestureHoldRemaining = null;
    const loaded = this.pickBaseClip(state);
    this.playClip(loaded, fade);
    this.holdTimer = 0;
    this.holdDuration = sample(loaded.meta.hold ?? DEFAULT_HOLD[state]);
  }

  private enterSleeping(fade: number): void {
    if (this.sleepPhase === "awake") return;
    this._state = "sleeping";
    const { loaded, timeScale } = this.library.sleepConfig(this.sleepPhase);
    this.playClip(loaded, fade, { timeScale });
  }

  private pickBaseClip(state: "idle" | "talking"): LoadedClip {
    // Emotion-selected variant bypasses the weighted rotation entirely
    // (variants ship with weight 0 precisely so they are ONLY reachable
    // this way).
    if (state === "idle" && this.idleVariant) {
      const variant = this.library.get(this.idleVariant);
      if (variant) return variant;
    }

    let pool: LoadedClip[];
    if (state === "talking") {
      pool = this.library.byCategory("talk");
      if (pool.length === 0) pool = this.library.byCategory("idle");
    } else {
      pool = this.library.byCategory("idle");
    }
    // Weight-0 entries never enter the spontaneous rotation. Without
    // this filter, a pool whose candidates sum to weight 0 (e.g. only
    // idle_sad/idle_bored downloaded) would deterministically pick the
    // first variant while Mika's actual emotion is neutral.
    const spontaneous = pool.filter((c) => (c.meta.weight ?? 1) > 0);
    if (spontaneous.length === 0) {
      // Nothing spontaneously pickable: keep what's playing if it
      // belongs to the pool, else fall back to the synthetic rest.
      const current = this.currentClip;
      if (current && pool.some((c) => c.name === current.name)) return current;
      return this.library.restLoaded;
    }

    // Weighted random, excluding the current clip when possible.
    const candidates = spontaneous.filter(
      (c) => c.name !== this.currentClip?.name
    );
    const usable = candidates.length > 0 ? candidates : spontaneous;
    const total = usable.reduce((s, c) => s + (c.meta.weight ?? 1), 0);
    let r = Math.random() * total;
    for (const c of usable) {
      r -= c.meta.weight ?? 1;
      if (r <= 0) return c;
    }
    return usable[usable.length - 1];
  }

  /** THE crossfade primitive: reset → play → crossFadeTo. Every clip
   * change in the system goes through here. */
  private playClip(
    loaded: LoadedClip,
    fade: number,
    opts: { once?: boolean; timeScale?: number; forceLoop?: boolean } = {}
  ): THREE.AnimationAction {
    const timeScale = opts.timeScale ?? loaded.meta.timeScale ?? 1;
    const action = this.mixer.clipAction(loaded.clip);

    if (action === this.currentAction) {
      // Same clip re-selected. Loops just retune speed (sleep phase
      // swaps re-using one clip); one-shots — and a debug pin landing on
      // a clip whose action was left in LoopOnce — restart cleanly.
      if (opts.once || opts.forceLoop) {
        action.reset();
        if (opts.once && !opts.forceLoop) {
          action.setLoop(THREE.LoopOnce, 1);
          action.clampWhenFinished = true;
        } else {
          action.setLoop(THREE.LoopRepeat, Infinity);
        }
        action.setEffectiveTimeScale(timeScale);
        action.setEffectiveWeight(1);
        action.play();
      } else {
        action.setEffectiveTimeScale(timeScale);
      }
      this.currentClip = loaded;
      return action;
    }

    action.reset(); // CRITICAL: clears residual weight/time from any
    action.enabled = true; // previous fade-out of this same action
    action.setEffectiveTimeScale(timeScale);
    action.setEffectiveWeight(1);
    if (opts.once && !opts.forceLoop) {
      action.setLoop(THREE.LoopOnce, 1);
      action.clampWhenFinished = true;
    } else {
      action.setLoop(THREE.LoopRepeat, Infinity);
    }
    action.play();

    if (this.currentAction && this.currentAction !== action) {
      // NOT crossFadeTo: three's fadeOut restarts the outgoing weight
      // ramp at 1 regardless of its current value, so interrupting an
      // in-flight crossfade (gesture during a wake fade, [SIGH] cue
      // right after onSpeakStart…) made the half-faded action pop to
      // full weight for a frame. Freezing its CURRENT effective weight
      // first makes the ramp start where the action actually is; the
      // momentary total-weight shortfall blends toward the rest pose
      // pre-written each frame in AnimationSystem.update — benign.
      const w = this.currentAction.getEffectiveWeight();
      this.currentAction.setEffectiveWeight(w);
      this.currentAction.fadeOut(fade);
      action.fadeIn(fade);
    } else if (!this.currentAction) {
      // Very first activation: full weight immediately. Fading in from
      // nothing rendered the untouched T-pose on the first frames of
      // every page load.
      action.setEffectiveWeight(1);
    }

    this.currentAction = action;
    this.currentClip = loaded;

    if (loaded.meta.hands) {
      this.hooks.onHandShapes?.(loaded.meta.hands[0], loaded.meta.hands[1]);
    }
    return action;
  }
}
