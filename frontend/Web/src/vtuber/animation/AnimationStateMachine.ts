import * as THREE from "three";
import type {
  AnimationStateName,
  EmotionName,
  EmotionReading,
  HandShapeName,
  SleepPhase,
} from "../../types";
import { ClipLibrary, REST_CLIP_NAME, type LoadedClip } from "./ClipLibrary";
import { affectHoldScale, affectTimeScale, clipAffinity } from "./affect";
import { baseClipName } from "./clipMirror";

// "walking" is driven by the locomotion controller (setWalking);
// "interacting" stays reserved.
export const LOCOMOTION_ENABLED = true;

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
  toWalk: 0.35,
  fromWalk: 0.45,
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

/**
 * How long the talking posture is held after the voice stops. People keep
 * their stance a beat past the last word, and two queued replies start the
 * next utterance ~300 ms after the previous one ends — an immediate return
 * to idle flip-flopped the whole body between them.
 */
export const SPEECH_SETTLE_S = 0.7;

/** Manifest names of the two sleep-edge gestures. Optional: a manifest
 * without them falls asleep and wakes with the plain crossfades. */
export const SLEEP_YAWN_CLIP = "gesture_yawn";
export const WAKE_STRETCH_CLIP = "gesture_stretch";

/** Ease speed of the affect tempo (1/s) — a mood change retunes the
 * clip's playback over ~half a second, never in one frame. */
const TEMPO_EASE = 2.0;

/**
 * Per-pick playback jitter (±). A recorded clip that always comes back at
 * the same speed, from the same frame, is a loop the eye learns within a
 * minute; drawn anew at every pick, the same motion is never quite the
 * same twice. Symmetric around 1 so a centred random source (tests inject
 * 0.5) reproduces the unjittered behaviour exactly.
 */
export const BASE_TEMPO_JITTER = 0.07;
export const GESTURE_TEMPO_JITTER = 0.1;

export interface StateMachineHooks {
  onHandShapes?: (left: HandShapeName, right: HandShapeName) => void;
  /** Random source for pool picks and hold sampling (tests inject one). */
  random?: () => number;
}

/**
 * Body-animation state machine over a THREE.AnimationMixer rooted at
 * the VRM's normalized humanoid rig.
 *
 * States: idle (weighted multi-clip pool), talking (talk pool),
 * gesture (one-shot, fades back BEFORE the clip ends), sleeping
 * (parameterized by SleepPhase), walking/interacting (reserved v2).
 *
 * The pools are affect-aware: a clip's declared arousal/valence weighs
 * its pick against the current emotion (`affect.ts`), and the base clip's
 * tempo and hold follow the emotion's arousal — a heated argument clip
 * for an angry reply, slow and long-held stances for a low mood. Quand le
 * fond de sa journée est connu, c'est le mélange moment + fond qui compte
 * (`bodyAffect`) : le corps porte l'humeur du jour, le visage le moment.
 */
export class AnimationStateMachine {
  private mixer: THREE.AnimationMixer;
  private library: ClipLibrary;
  private hooks: StateMachineHooks;
  private random: () => number;

  private _state: AnimationStateName = "idle";
  private started = false;
  private speaking = false;
  private sleepPhase: SleepPhase = "awake";

  private currentAction: THREE.AnimationAction | null = null;
  private currentClip: LoadedClip | null = null;
  /** Manifest/sleep timeScale of the current action, before affect tempo. */
  private currentTimeScale = 1;

  private holdTimer = 0;
  private holdDuration = 10;

  // Gesture bookkeeping
  private gestureFadeOut = FADE.gestureOut;
  /** For looping "gestures" (e.g. thinking): seconds left before return. */
  private gestureHoldRemaining: number | null = null;
  /** 1-deep queue, newest wins. */
  private queuedGesture: LoadedClip | null = null;
  /** The running gesture is the yawn that precedes sleep: on its end,
   * fall asleep instead of returning to a base pool. */
  private sleepAfterGesture = false;

  /** Emotion-driven idle override (sad/anxious/bored postures). */
  private idleVariant: string | null = null;

  /**
   * Seated or lying: one clip stands in for both base pools, held without
   * rotation, and sleep dozes in it. Standing gestures and talk clips move
   * the legs — they would stand her up off the chair — so none plays.
   */
  private postureClip: LoadedClip | null = null;
  /** Walk clip while the locomotion controller moves the root. */
  private walkClip: LoadedClip | null = null;

  /** Affect feeding pool weights, tempo and hold. */
  private affectEmotion: EmotionName = "neutral";
  private affectIntensity = 0.5;
  /** Son humeur du jour, mêlée au moment ; null = le moment seul. */
  private affectMood: EmotionReading | null = null;
  private tempoTarget = 1;
  private tempo = 1;
  /** This pick's playback jitter (see BASE_TEMPO_JITTER). */
  private pickTempo = 1;

  /** Seconds left before the talking posture returns to idle (null = no
   * return pending). */
  private settleRemaining: number | null = null;

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
    this.random = hooks.random ?? Math.random;
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

  /** Posture d'émotion en cours, telle qu'elle a été RÉSOLUE (un clip
   * absent de la librairie vaut null) — c'est cette valeur-là, pas celle
   * demandée, qui alimente l'hystérésis de `decideGesture`. */
  get idleVariantName(): string | null {
    return this.idleVariant;
  }

  /** The voice stopped and the body is holding its stance for a beat. */
  get isSettling(): boolean {
    return this.settleRemaining !== null;
  }

  /** Effective playback tempo of the base clip (affect-driven). */
  get affectTempo(): number {
    return this.tempo;
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
        if (this.postureClip) {
          // A posture is held, not rotated; only the tempo follows mood.
          this.settleRemaining = null;
          this.updateTempo(dt);
          break;
        }
        if (this.settleRemaining !== null) {
          this.settleRemaining -= dt;
          if (this.settleRemaining <= 0) {
            this.settleRemaining = null;
            if (!this.speaking && this._state === "talking") {
              this.enterBase("idle", FADE.toIdle);
              break;
            }
          }
        }
        this.holdTimer += dt;
        if (this.holdTimer >= this.holdDuration) {
          this.enterBase(this._state, FADE.variation);
        }
        this.updateTempo(dt);
        break;
      }
      case "gesture": {
        this.updateGesture(dt);
        break;
      }
      case "walking":
        // The walk's pace is the root's travel (no affect tempo): feet that
        // step faster than the body moves slide.
        this.currentAction?.setEffectiveTimeScale(this.currentTimeScale);
        break;
      case "sleeping":
      case "interacting":
        break;
    }
  }

  // ── Locomotion (driven by the LocomotionController) ───────────────

  /** Walk (loaded clip at a playback speed matching the root's travel), or
   * stop walking (null) back into the posture / base pool. */
  setWalking(loaded: LoadedClip | null, timeScale = 1): void {
    if (!this.started) return;
    if (loaded) {
      this.walkClip = loaded;
      this.queuedGesture = null;
      this.gestureHoldRemaining = null;
      this.sleepAfterGesture = false;
      this.settleRemaining = null;
      this._state = "walking";
      this.pickTempo = 1;
      if (this.currentClip?.name === loaded.name) {
        this.currentTimeScale = timeScale;
      } else {
        this.playClip(loaded, FADE.toWalk, { timeScale });
      }
      return;
    }
    if (!this.walkClip) return;
    this.walkClip = null;
    if (this._state !== "walking") return;
    if (this.sleepPhase !== "awake") this.enterSleeping(FADE.fromWalk);
    else this.enterBase(this.speaking ? "talking" : "idle", FADE.fromWalk);
  }

  /** Seated / lying posture clip, or null to stand. */
  setPosture(loaded: LoadedClip | null, fade = 0.9): void {
    if (loaded === this.postureClip) return;
    this.postureClip = loaded;
    if (!this.started || this.debugPinned || this._state === "walking") return;
    if (this._state === "sleeping") {
      this.enterSleeping(fade);
      return;
    }
    // A gesture in flight is cut: one does not finish a wave while sitting.
    this.queuedGesture = null;
    this.gestureHoldRemaining = null;
    this.enterBase(this.speaking ? "talking" : "idle", fade);
  }

  get isWalking(): boolean {
    return this._state === "walking";
  }

  get posture(): LoadedClip | null {
    return this.postureClip;
  }

  // ── Inputs ────────────────────────────────────────────────────────

  setSpeaking(speaking: boolean): void {
    if (speaking === this.speaking) return;
    this.speaking = speaking;
    if (!this.started || this.debugPinned) return;
    if (this._state === "sleeping" || this._state === "walking") return;
    if (this._state === "gesture") {
      // A gesture owns the base layer until it fades back; finishGesture
      // re-reads this.speaking, so the flip needs nothing but the flag.
      return;
    }
    if (speaking) {
      // Voice resumed during the settle: the posture never left, nothing
      // to re-pick.
      this.settleRemaining = null;
      if (this._state !== "talking") this.enterBase("talking", FADE.toTalking);
      return;
    }
    // Hold the talking stance a beat before relaxing (see SPEECH_SETTLE_S).
    this.settleRemaining = SPEECH_SETTLE_S;
  }

  setSleepPhase(phase: SleepPhase): void {
    if (phase === this.sleepPhase) return;
    const prev = this.sleepPhase;
    this.sleepPhase = phase;
    if (!this.started || this.debugPinned) return;

    if (this._state === "walking") {
      // The walk finishes first; setWalking(null) lands in the right state.
      return;
    }
    if (phase === "awake") {
      if (this._state === "gesture") {
        // Woken mid-yawn: let it finish, it lands on a base pool by itself.
        this.sleepAfterGesture = false;
        return;
      }
      // Waking with a stretch, when one is on disk and she is not already
      // answering someone — the wake fade carries the sleep→stretch edge.
      const stretch = this.postureClip ? null : this.library.variant(WAKE_STRETCH_CLIP, this.random);
      if (stretch && !this.speaking) {
        this.sleepAfterGesture = false;
        this.startGesture(stretch, FADE.wake);
        return;
      }
      this.enterBase(this.speaking ? "talking" : "idle", FADE.wake);
      return;
    }

    // Falling asleep cancels any queued gesture; a phase change while
    // already asleep just swaps clip/timeScale.
    this.queuedGesture = null;
    if (prev === "awake" && (this._state === "idle" || this._state === "talking")) {
      // Yawn first, then doze — nobody drops straight from standing to
      // sleep. A running gesture is not interrupted for a yawn; a phase
      // change while she is already asleep never yawns.
      const yawn = this.postureClip ? null : this.library.variant(SLEEP_YAWN_CLIP, this.random);
      if (yawn && !this.speaking) {
        this.settleRemaining = null;
        this.sleepAfterGesture = true;
        this.startGesture(yawn, yawn.meta.fadeIn ?? FADE.gestureIn);
        return;
      }
    }
    this.gestureHoldRemaining = null;
    this.sleepAfterGesture = false;
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

  /** Current affect: weighs pool picks, retunes tempo and hold. Never
   * triggers a transition by itself — the running clip just changes pace.
   * `mood` : le fond de sa journée, mêlé au moment (`bodyAffect`) ; null,
   * le moment seul. */
  setAffect(emotion: EmotionName, intensity: number, mood: EmotionReading | null = null): void {
    this.affectEmotion = emotion;
    this.affectIntensity = Math.max(0, Math.min(1, intensity));
    this.affectMood = mood;
    this.tempoTarget = affectTimeScale(emotion, this.affectIntensity, mood);
  }

  /** Play a one-shot (or briefly-held looping) gesture clip. Returns
   * false when the state forbids it (sleeping, not started). */
  requestGesture(loaded: LoadedClip): boolean {
    if (!this.started || this.debugPinned) return false;
    // Standing clips: never while seated, lying or walking.
    if (this.postureClip) return false;
    if (this._state === "sleeping" || this._state === "walking" || this._state === "interacting") {
      return false;
    }

    if (this._state === "gesture") {
      // Re-requesting the gesture that is ALREADY playing would land on
      // the same AnimationAction and hard-reset it to t=0 (a visible
      // snap, e.g. two [LAUGH] tokens in one reply) — treat it as
      // satisfied instead. Its mirrored twin counts as the same gesture.
      if (this.currentClip && baseClipName(this.currentClip.name) === baseClipName(loaded.name)) {
        return true;
      }
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

    this.settleRemaining = null;
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
    if (this.walkClip) this.setWalking(this.walkClip);
    else if (this.sleepPhase !== "awake") this.enterSleeping(FADE.sleepPhaseSwap);
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

  private updateTempo(dt: number): void {
    this.tempo += (this.tempoTarget - this.tempo) * Math.min(1, dt * TEMPO_EASE);
    if (this.currentAction) {
      this.currentAction.setEffectiveTimeScale(
        this.currentTimeScale * this.tempo * this.pickTempo
      );
    }
  }

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
    if (this.sleepAfterGesture) {
      this.sleepAfterGesture = false;
      if (this.sleepPhase !== "awake") {
        // The yawn is over: doze off, whatever was queued behind it.
        this.queuedGesture = null;
        this.gestureHoldRemaining = null;
        this.enterSleeping(FADE.toSleep);
        return;
      }
    }
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
    this.playClip(loaded, fadeIn, {
      once: !loops,
      timeScale: (loaded.meta.timeScale ?? 1) * this.jitter(GESTURE_TEMPO_JITTER),
    });
    this.gestureHoldRemaining = loops
      ? this.sample(loaded.meta.hold ?? [3.5, 5.5])
      : null;
  }

  private enterBase(state: "idle" | "talking", fade: number): void {
    this._state = state;
    this.gestureHoldRemaining = null;
    this.settleRemaining = null;
    const loaded = this.pickBaseClip(state);
    // A new pick enters its loop at a random frame and its own pace: the
    // same idle never restarts from the same breath twice.
    this.pickTempo = this.postureClip ? 1 : this.jitter(BASE_TEMPO_JITTER);
    this.playClip(loaded, fade, { randomPhase: !this.postureClip });
    this.holdTimer = 0;
    this.holdDuration =
      this.sample(loaded.meta.hold ?? DEFAULT_HOLD[state]) *
      affectHoldScale(this.affectEmotion, this.affectIntensity, this.affectMood);
  }

  private enterSleeping(fade: number): void {
    if (this.sleepPhase === "awake") return;
    this._state = "sleeping";
    this.settleRemaining = null;
    this.pickTempo = 1;
    if (this.postureClip) {
      // Dozing in the chair, asleep in the bed: the posture holds.
      this.playClip(this.postureClip, fade);
      return;
    }
    const { loaded, timeScale } = this.library.sleepConfig(this.sleepPhase);
    this.playClip(loaded, fade, { timeScale });
  }

  /** Pick weight of a pool clip under the current affect. Exposed for
   * tests; the pool logic itself lives in pickBaseClip. */
  poolWeight(loaded: LoadedClip): number {
    return (
      (loaded.meta.weight ?? 1) *
      clipAffinity(loaded.meta, this.affectEmotion, this.affectIntensity, this.affectMood)
    );
  }

  private pickBaseClip(state: "idle" | "talking"): LoadedClip {
    if (this.postureClip) return this.postureClip;
    // Emotion-selected variant bypasses the weighted rotation entirely
    // (variants ship with weight 0 precisely so they are ONLY reachable
    // this way).
    if (state === "idle" && this.idleVariant) {
      // Either side: a slump held for a minute shifts its weight over.
      const variant = this.library.variant(this.idleVariant, this.random);
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

    // Weighted random, excluding the current clip when possible. The
    // affinity term (affect.ts) tilts the draw toward clips whose declared
    // arousal/valence match the emotion; undeclared clips keep their weight.
    // Neither the current clip nor its mirrored twin: the same motion
    // from the other side right after is still the same motion.
    const current = this.currentClip ? baseClipName(this.currentClip.name) : null;
    const candidates = spontaneous.filter((c) => baseClipName(c.name) !== current);
    const usable = candidates.length > 0 ? candidates : spontaneous;
    const weights = usable.map((c) => this.poolWeight(c));
    const total = weights.reduce((s, w) => s + w, 0);
    let r = this.random() * total;
    for (let i = 0; i < usable.length; i++) {
      r -= weights[i];
      if (r <= 0) return usable[i];
    }
    return usable[usable.length - 1];
  }

  private sample(range: [number, number]): number {
    return range[0] + this.random() * Math.max(0, range[1] - range[0]);
  }

  /** 1 ± amount, centred: a random source returning 0.5 yields exactly 1. */
  private jitter(amount: number): number {
    return 1 + amount * (2 * this.random() - 1);
  }

  /** THE crossfade primitive: reset → play → crossFadeTo. Every clip
   * change in the system goes through here. */
  private playClip(
    loaded: LoadedClip,
    fade: number,
    opts: { once?: boolean; timeScale?: number; forceLoop?: boolean; randomPhase?: boolean } = {}
  ): THREE.AnimationAction {
    const timeScale = opts.timeScale ?? loaded.meta.timeScale ?? 1;
    const action = this.mixer.clipAction(loaded.clip);
    this.currentTimeScale = timeScale;

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
    if (opts.randomPhase && !opts.once) {
      action.time = this.random() * loaded.clip.duration;
    }
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
