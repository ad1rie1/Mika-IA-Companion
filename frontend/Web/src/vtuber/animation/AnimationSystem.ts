import * as THREE from "three";
import { VRM } from "@pixiv/three-vrm";
import type {
  AvatarStateSnapshot,
  EmotionBlend,
  EmotionName,
  EmotionReading,
  ProsodicCue,
  SleepPhase,
  VoicePersona,
} from "../../types";
import { ClipLibrary, applyRestPose } from "./ClipLibrary";
import { AnimationStateMachine, SLEEP_YAWN_CLIP } from "./AnimationStateMachine";
import { BlinkController } from "./BlinkController";
import { FaceIdleController } from "./FaceIdleController";
import { HandAnimator } from "./HandAnimator";
import { GazeController } from "./GazeController";
import { OverlayContext, type ProceduralOverlay } from "./overlays/Overlay";
import { BreathingOverlay } from "./overlays/BreathingOverlay";
import { LifeOverlay } from "./overlays/LifeOverlay";
import { SpeechBodyOverlay } from "./overlays/SpeechBodyOverlay";
import { planSpeechBeats } from "./speechBeats";
import { LocomotionController } from "../locomotion/LocomotionController";
import { isPlaceId, type PlaceId, type Posture } from "../locomotion/roomLayout";
import {
  LIE_CLIP_NAME,
  SIT_CLIP_NAME,
  WALK_CLIP_NAME,
  buildLieClip,
  buildSitClip,
  buildWalkClip,
  standingHipsHeight,
} from "../locomotion/proceduralClips";
import type { LoadedClip } from "./ClipLibrary";
import { SleepOverlay } from "./overlays/SleepOverlay";
import { HeadEmotionOverlay } from "./overlays/HeadEmotionOverlay";
import { HeadAttentionOverlay, viewerReachable } from "./overlays/HeadAttentionOverlay";
import { AttentionDirector, type AttentionInput, type AttentionState } from "./attention";
import { activityFocus, type ActivityFocus } from "./activity";
import { CUE_GESTURE, decideGesture } from "./gestures";

const DEFAULT_MANIFEST_URL = "/animations/manifest.json";

/** How long after the last keystroke she still counts as being listened
 * to — the gaze rests on the viewer while they type. */
export const LISTENING_HOLD_S = 2.5;

/** A yawn needs real tiredness, and comes every few minutes at most. */
export const YAWN_MIN_FATIGUE = 0.55;
export const YAWN_INTERVAL_S: [number, number] = [120, 300];

/**
 * Facade over the whole body-animation stack — the ONLY object main.ts
 * wires. Owns, in per-frame order:
 *
 *   1. humanoid.resetNormalizedPose()   clean identity base
 *   2. state machine                    clip scheduling / transitions
 *   3. THREE.AnimationMixer             base layer (bones + hips pos)
 *   4. AttentionDirector                where her attention is (pure)
 *   5. overlays (additive quaternions)  breathing → life (micro-motion,
 *                                       weight shifts) → sleep tilt →
 *                                       emotion head pose → attention head
 *                                       turn → speech beats (nods, tilts)
 *   6. HandAnimator                     fingers (absolute; clips are
 *                                       stripped of finger tracks)
 *   7. GazeController                   eyes (absolute; clips have none) —
 *                                       runs AFTER the head overlays so it
 *                                       points at the residual (VOR)
 *   8. BlinkController                  blink expression + REM flicker,
 *                                       gaze-evoked blinks
 *   9. FaceIdleController               ARKit micro-expressions
 *
 * main.ts then runs lipSync / environment and calls vtuberModel.update
 * (vrm.update) LAST — that invariant is unchanged from the old system.
 */
export class AnimationSystem {
  readonly library = new ClipLibrary();

  private vrm: VRM | null = null;
  private mixer: THREE.AnimationMixer | null = null;
  private machine: AnimationStateMachine | null = null;
  private ctx: OverlayContext | null = null;
  private overlays: ProceduralOverlay[] = [];
  private blink = new BlinkController();
  private faceIdle = new FaceIdleController();
  private hands = new HandAnimator();
  private gaze = new GazeController();
  private director = new AttentionDirector();
  private speechBody = new SpeechBodyOverlay();
  /** Character the voice is at (lip-sync cursor), −1 = none. */
  private speechCursor = -1;
  private root: THREE.Object3D | null = null;
  private camera: THREE.Object3D | null = null;

  /** What the body shows (see effectiveSleep). */
  private sleepPhase: SleepPhase = "awake";
  /** What the backend says. */
  private requestedSleep: SleepPhase = "awake";
  private locomotion: LocomotionController | null = null;
  /** A place received before the model loaded — applied as a snap. */
  private pendingPlace: PlaceId | null = null;
  /** Movable seats handed over before the model loaded. */
  private pendingProps = new Map<PlaceId, THREE.Object3D | null>();
  /** What she is doing in her room (the backend's name), and how it shows. */
  private activityName: string | null = null;
  private focus: ActivityFocus | null = null;
  private speaking = false;
  private replyPending = false;
  /** Internal clock (sum of clamped dt) — the typing memo is stamped on it. */
  private clock = 0;
  private lastTypingAt = -Infinity;
  private lastOneshotAt: number | null = null;
  private fatigue = 0;
  /** Seconds until a tired, idle Mika yawns (null = not tired enough). */
  private yawnIn: number | null = null;
  private lastPersona: VoicePersona | undefined;
  /** Le fond de sa journée (setMood), gardé aussi avant l'init. */
  private mood: EmotionReading | null = null;
  private _ready = false;

  get ready(): boolean {
    return this._ready;
  }

  /**
   * Wire the VRM and start animating immediately on the synthetic rest
   * clip (no T-pose flash), then stream the Mixamo clips in. Resolves
   * once the manifest pass is finished; the avatar is already alive
   * from the first frame.
   */
  async init(
    vrm: VRM,
    opts: {
      manifestUrl?: string;
      root?: THREE.Object3D | null;
      /** Whose position she looks at. Null = no viewer: forward gaze. */
      camera?: THREE.Object3D | null;
      onProgress?: (done: number, total: number, name: string) => void;
    } = {}
  ): Promise<void> {
    this.root = opts.root ?? null;
    this.camera = opts.camera ?? null;
    this.hands.setVRM(vrm);
    this.gaze.setVRM(vrm);
    this.gaze.setCamera(this.camera);

    if (!vrm.humanoid) {
      console.warn("AnimationSystem: VRM has no humanoid — body animation disabled");
      return;
    }

    this.library.prepare(vrm);
    this.mixer = new THREE.AnimationMixer(vrm.humanoid.normalizedHumanBonesRoot);
    this.machine = new AnimationStateMachine(this.mixer, this.library, {
      onHandShapes: (l, r) => this.hands.setPoseShape(l, r),
    });
    this.ctx = new OverlayContext(vrm);
    this.ctx.sleepPhase = this.sleepPhase;
    this.ctx.speaking = this.speaking;
    this.ctx.persona = this.lastPersona;
    this.ctx.fatigue = this.fatigue;
    this.ctx.mood = this.mood;
    this.ctx.camera = this.camera;
    this.overlays = [
      new BreathingOverlay(),
      new LifeOverlay(),
      new SleepOverlay(),
      new HeadEmotionOverlay(),
      // It measures the viewer in the head frame as everything above posed
      // it, so its turn is the residual.
      new HeadAttentionOverlay(),
      // Speech beats after the attention turn: a nod is a gesture, not a
      // change of where she looks — the gaze (run after every head writer)
      // keeps the eyes on the viewer through it.
      this.speechBody,
    ];

    // Re-apply signals that may have arrived before init.
    this.machine.setSpeaking(this.speaking);
    this.machine.setSleepPhase(this.sleepPhase);
    this.machine.setAffect(this.ctx.emotion, this.ctx.intensity, this.mood);
    this.machine.start();
    if (this.root) this.initLocomotion(vrm, this.root);
    this.vrm = vrm; // update() starts animating from this point on

    await this.library.loadManifest(opts.manifestUrl ?? DEFAULT_MANIFEST_URL, {
      onProgress: opts.onProgress,
      // As downloaded clips stream in, swap the rest pose for real life.
      onClipLoaded: (loaded) => {
        this.machine?.refreshBaseIfResting();
        // A downloaded walk (manifest category "locomotion") replaces the
        // procedural one.
        if (loaded.meta.category === "locomotion") this.walkClip = loaded;
      },
    });
    this._ready = true;
    console.log(
      `AnimationSystem: ${this.library.listNames().length} clip(s) ready`
    );
  }

  update(delta: number): void {
    const vrm = this.vrm;
    const ctx = this.ctx;
    if (!vrm || !ctx) return;

    const dt = Math.min(delta, 0.1);
    this.clock += dt;

    if (this.locomotion) {
      this.locomotion.update(dt);
      this.applyEffectiveSleep();
      ctx.walking = this.locomotion.walking;
    }

    if (this.machine && this.mixer && vrm.humanoid) {
      // Identity base every frame: a clip missing some tracks degrades
      // to rest, never to a stale rotation from a previous clip. The
      // A-pose arms are then pre-written so both the mixer's blend
      // shortfall target and uncovered bones read as a relaxed stance,
      // never the bind T-pose.
      vrm.humanoid.resetNormalizedPose();
      applyRestPose(vrm);
      this.machine.update(dt);
      this.mixer.update(dt);
    }

    // Where her attention is, decided before any head writer runs. The
    // reachability it reads was measured last frame — one frame of lag on
    // "is the viewer behind me" is nothing.
    const input: AttentionInput = {
      speaking: this.speaking,
      replyPending: this.replyPending,
      listening: this.clock - this.lastTypingAt < LISTENING_HOLD_S,
      persona: ctx.persona,
      emotion: ctx.emotion,
      intensity: ctx.intensity,
      sleepPhase: this.sleepPhase,
      walking: ctx.walking,
      reachable:
        ctx.camera !== null &&
        ctx.viewerMeasured &&
        viewerReachable(ctx.viewerYaw, ctx.viewerPitch),
      viewerAngle: ctx.viewerMeasured ? Math.hypot(ctx.viewerYaw, ctx.viewerPitch) : 0,
      focus: this.focus,
    };
    this.updateYawn(dt);
    const intent = this.director.update(dt, input);
    ctx.attention = intent;
    ctx.speechCursor = this.speechCursor;

    for (const overlay of this.overlays) {
      overlay.update(dt, ctx);
    }
    this.hands.update(dt);
    this.gaze.update(dt, intent);
    ctx.gazeShift = intent.shift;
    this.blink.update(dt, ctx);
    // Micro-expressions last: ARKit shapes, disjoint from the emotion
    // shapes, the lip-sync visemes and `blink`, so all four compose.
    this.faceIdle.update(dt, ctx);
  }

  // ── Signals ───────────────────────────────────────────────────────

  setSpeaking(speaking: boolean): void {
    this.speaking = speaking;
    if (this.ctx) this.ctx.speaking = speaking;
    this.hands.setSpeaking(speaking);
    this.machine?.setSpeaking(speaking);
  }

  /**
   * Energy 0…1 from the inner state (circadian rhythm × REST drive). Below
   * ~0.55 she gets tired in her body: slower breath, less fidgeting, heavier
   * blinks, and now and then — idle, awake, not mid-conversation — a yawn.
   */
  setEnergy(energy: number): void {
    this.fatigue = Math.max(0, Math.min(1, (0.55 - energy) / 0.4));
    if (this.ctx) this.ctx.fatigue = this.fatigue;
    if (this.fatigue < YAWN_MIN_FATIGUE) this.yawnIn = null;
    else if (this.yawnIn === null) this.yawnIn = this.sampleYawnDelay();
  }

  private sampleYawnDelay(): number {
    const [lo, hi] = YAWN_INTERVAL_S;
    return (lo + Math.random() * (hi - lo)) / Math.max(0.3, this.fatigue);
  }

  private updateYawn(dt: number): void {
    if (this.yawnIn === null) return;
    const idle =
      this.sleepPhase === "awake" &&
      !this.speaking &&
      !this.replyPending &&
      this.clock - this.lastTypingAt > LISTENING_HOLD_S &&
      this.machine?.state === "idle";
    if (!idle) return;
    this.yawnIn -= dt;
    if (this.yawnIn > 0) return;
    this.yawnIn = this.sampleYawnDelay();
    const yawn = this.library.variant(SLEEP_YAWN_CLIP);
    if (yawn) this.machine?.requestGesture(yawn);
  }

  /** The voice starts an utterance: plan where the head and brows will
   * punctuate it. Called with the text the TTS actually plays (same
   * contract as the lip-sync plan). */
  beginUtterance(text: string, _msPerChar?: number): void {
    this.speechBody.begin(planSpeechBeats(text));
  }

  /** Where the voice is in the utterance (the lip-sync cursor), each
   * frame; −1 when nothing is being articulated. */
  setSpeechCursor(charIndex: number): void {
    this.speechCursor = charIndex;
  }

  /** A message was accepted and no reply came yet: she is composing —
   * the gaze goes up and to the side with brief check-ins. Cleared by the
   * reply; the director also gives up on its own after THINKING_MAX_S. */
  setReplyPending(pending: boolean): void {
    // Receiving the message is visible: a small acknowledging nod before
    // the gaze goes off to compose — never while asleep.
    if (pending && !this.replyPending && this.sleepPhase === "awake") {
      this.speechBody.acknowledge();
    }
    this.replyPending = pending;
  }

  /** The person in front of her typed something just now: listening
   * gaze — eyes on them, fewer aversions — for LISTENING_HOLD_S. */
  noteUserTyping(): void {
    this.lastTypingAt = this.clock;
  }

  setEmotion(
    emotion: EmotionName,
    intensity: number,
    blend: EmotionBlend = [],
    persona?: VoicePersona,
    opts: { ambient?: boolean } = {}
  ): void {
    const clamped = Math.max(0, Math.min(1, intensity));
    // Ambient drift says nothing about how she is speaking, so it must not
    // clear the persona a reply set — playCue reads it after the fact.
    if (!opts.ambient) {
      this.lastPersona = persona;
      if (this.ctx) this.ctx.persona = persona;
    }
    if (this.ctx) {
      this.ctx.emotion = emotion;
      this.ctx.intensity = clamped;
    }
    this.gaze.setEmotion(emotion, clamped);
    this.hands.setEmotion(emotion, clamped);

    if (!this.machine) return;
    // Le corps porte le moment mêlé au fond ; les gestes, eux, répondent
    // au moment seul (decideGesture ci-dessous).
    this.machine.setAffect(emotion, clamped, this.mood);
    const decision = decideGesture({
      emotion,
      intensity: clamped,
      blend,
      // No persona on drift: the persona gate exists to keep a murmured
      // thought from getting a body beat, and `ambient` already blocks
      // every one-shot. Passing it on would also veto the postures.
      persona: opts.ambient ? undefined : persona,
      sleepPhase: this.sleepPhase,
      nowMs: performance.now(),
      lastOneshotAtMs: this.lastOneshotAt,
      ambient: opts.ambient,
      // Ce que la machine tient déjà : sans lui, la décroissance de
      // l'oscillateur retraverse le seuil dans les deux sens toutes les
      // quelques secondes et chaque sortie re-tire un idle au hasard.
      activeVariant: this.machine.idleVariantName,
    });

    if (decision.action === "idleVariant") {
      this.machine.setIdleVariant(decision.clip);
      return;
    }
    // Any non-variant emotion returns the idle pool to normal.
    this.machine.setIdleVariant(null);

    if (decision.action === "oneshot") {
      // Either side: the same reaction does not always come from the same
      // hand.
      const loaded = this.library.variant(decision.clip);
      if (loaded && this.machine.requestGesture(loaded)) {
        this.lastOneshotAt = performance.now();
      }
    }
  }

  /**
   * Le fond de sa journée — son humeur à elle (`emotion_state.global`,
   * ADR 0032). Le corps le porte, mêlé au moment (`bodyAffect`) : choix
   * des clips, tempo, tenue des postures, respiration, micro-mouvements.
   * Le visage, la tête, le regard, les mains et les gestes restent sur ce
   * qu'elle vient de dire. `null` l'oublie : le corps suit le moment seul.
   */
  setMood(emotion: EmotionName | null, intensity: number): void {
    const mood = emotion === null ? null : { emotion, intensity: Math.max(0, Math.min(1, intensity)) };
    this.mood = mood;
    if (!this.ctx) return;
    this.ctx.mood = mood;
    this.machine?.setAffect(this.ctx.emotion, this.ctx.intensity, mood);
  }

  setSleepPhase(phase: SleepPhase): void {
    this.requestedSleep = phase;
    this.locomotion?.setSleepPhase(phase);
    this.applyEffectiveSleep();
  }

  /**
   * Asleep is shown once she is in her place for it. When the backend puts
   * her to sleep and sends her to bed in the same breath, she walks there
   * with her eyes open and dozes off once lying down — not a sleepwalker
   * crossing the room with closed eyes. The lights (Environment) dim at
   * once all the same.
   */
  private applyEffectiveSleep(): void {
    const loco = this.locomotion;
    const travelling = loco !== null && loco.moving && loco.posture !== "lie";
    const phase: SleepPhase = this.requestedSleep !== "awake" && travelling ? "awake" : this.requestedSleep;
    if (phase === this.sleepPhase) return;
    this.sleepPhase = phase;
    if (this.ctx) this.ctx.sleepPhase = phase;
    this.hands.setSleepPhase(phase);
    this.gaze.setSleepPhase(phase);
    this.machine?.setSleepPhase(phase);
  }

  // ── Locomotion ────────────────────────────────────────────────────

  private walkClip: LoadedClip | null = null;

  private initLocomotion(vrm: VRM, root: THREE.Object3D): void {
    const machine = this.machine;
    if (!machine) return;
    const synth = (name: string, clip: THREE.AnimationClip): LoadedClip => ({
      name,
      clip,
      meta: { url: "", category: "locomotion", loop: true, hands: ["relaxed", "relaxed"] },
      report: null,
    });
    this.walkClip = this.library.byCategory("locomotion")[0] ?? synth(WALK_CLIP_NAME, buildWalkClip(vrm));
    const sit = synth(SIT_CLIP_NAME, buildSitClip(vrm));
    const lie = synth(LIE_CLIP_NAME, buildLieClip(vrm));
    this.locomotion = new LocomotionController({
      root,
      baseYaw: root.rotation.y,
      hipsHeight: standingHipsHeight(vrm),
      body: {
        walk: (timeScale) => {
          if (timeScale === null) machine.setWalking(null);
          else if (this.walkClip) machine.setWalking(this.walkClip, timeScale);
        },
        posture: (posture: Posture, fade) =>
          machine.setPosture(posture === "sit" ? sit : posture === "lie" ? lie : null, fade),
      },
    });
    this.locomotion.setSleepPhase(this.requestedSleep);
    for (const [place, obj] of this.pendingProps) this.locomotion.setProp(place, obj);
    this.pendingProps.clear();
    if (this.pendingPlace) {
      this.locomotion.setPlace(this.pendingPlace, { instant: true });
      this.pendingPlace = null;
    }
  }

  /**
   * Where the AI put her (the backend's `place`, state not command). An
   * unknown value is ignored; the first place ever received snaps her there,
   * every later change is walked.
   */
  setPlace(place: unknown, opts: { instant?: boolean } = {}): void {
    if (!isPlaceId(place)) {
      if (place !== undefined && place !== null) console.warn(`AnimationSystem: unknown place "${String(place)}"`);
      return;
    }
    if (!this.locomotion) {
      this.pendingPlace = place;
      return;
    }
    this.locomotion.setPlace(place, opts);
  }

  /**
   * What she is doing in her room (the backend's `activity.name`, a state
   * like the place): between two exchanges her eyes rest on it and her
   * hands hold it (activity.ts) — a sign of the person brings her eyes
   * back at once. Null, or a name the table does not know: nothing.
   */
  setActivity(name: unknown): void {
    const next = typeof name === "string" ? name : null;
    if (next === this.activityName) return;
    this.activityName = next;
    this.focus = activityFocus(next);
    if (next !== null && !this.focus) console.warn(`AnimationSystem: unknown activity "${next}"`);
    this.hands.setActivity(this.focus?.hands ?? null, this.focus?.handMotion ?? 1);
  }

  /**
   * The room's movable seat for a place (room.glb's `DeskChair` for the
   * desk): she pulls it out, sits, rolls in with it. Null removes it.
   */
  setPlaceProp(place: PlaceId, obj: THREE.Object3D | null): void {
    if (this.locomotion) this.locomotion.setProp(place, obj);
    else this.pendingProps.set(place, obj);
  }

  /** Where she is (null before any place was received), and her posture. */
  get place(): { place: PlaceId | null; posture: Posture; moving: boolean } {
    const loco = this.locomotion;
    return {
      place: loco?.place ?? this.pendingPlace,
      posture: loco?.posture ?? "stand",
      moving: loco?.moving ?? false,
    };
  }

  /** Prosodic beat from the TTS ([SIGH]/[LAUGH]/[BREATH]). Bypasses the
   * emote cooldown — the LLM authored it as a beat — but not the sleep
   * gate, nor the inner-persona gate: a murmured thought never gets a
   * full-body beat (same contract as decideGesture). Silence when the
   * clip isn't loaded. */
  playCue(cue: ProsodicCue): void {
    if (this.sleepPhase !== "awake" || this.lastPersona === "inner" || !this.machine) {
      return;
    }
    // The breath IS the cue, before any clip: a sigh empties the lungs
    // even when no sigh clip is on disk.
    if (this.ctx) {
      if (cue === "sigh") this.ctx.breathRequest = "sigh";
      else if (cue === "breath") this.ctx.breathRequest = "catch";
    }
    const clipName = CUE_GESTURE[cue];
    if (!clipName) return;
    const loaded = this.library.variant(clipName);
    if (loaded) this.machine.requestGesture(loaded);
  }

  /** Manual/debug gesture trigger by manifest clip name. */
  playGesture(name: string): boolean {
    if (!this.machine) return false;
    const loaded = this.library.get(name);
    return loaded ? this.machine.requestGesture(loaded) : false;
  }

  // ── v2 seam: serializable body state ──────────────────────────────

  getSnapshot(): AvatarStateSnapshot {
    const pos: [number, number, number] = this.root
      ? [this.root.position.x, this.root.position.y, this.root.position.z]
      : [0, 0, 0];
    return {
      seq: 0, // backend-assigned once avatar_state sync exists (v2)
      t: Date.now(),
      position: pos,
      facing: this.root?.rotation.y ?? 0,
      behaviorState: this.machine?.state ?? "idle",
      clipName: this.machine?.currentClipName ?? null,
      clipTime: this.machine?.clipTime ?? 0,
      sleepPhase: this.sleepPhase,
      emotion: this.ctx?.emotion ?? "neutral",
      emotionIntensity: this.ctx?.intensity ?? 0,
      anchorId: null,
      place: this.locomotion?.place ?? null,
    };
  }

  // ── Debug surface (AnimationDebugger) ─────────────────────────────

  listClips(): string[] {
    return this.library.listNames();
  }

  debugCycleClip(): string {
    return this.machine?.debugCycleClip() ?? "(not initialized)";
  }

  debugResume(): void {
    this.machine?.debugResume();
  }

  getDebugState(): {
    state: string;
    clip: string | null;
    clipTime: number;
    clipDuration: number;
    sleepPhase: SleepPhase;
    emotion: EmotionName;
    intensity: number;
    /** Le fond que porte le corps (null : le moment seul). */
    mood: EmotionReading | null;
    speaking: boolean;
    clipCount: number;
    attention: AttentionState;
    /** Semantic eye angles applied (pitch/yaw, rad). */
    gaze: { pitch: number; yaw: number };
    tempo: number;
  } {
    const applied = this.gaze.applied;
    return {
      state: this.machine?.state ?? "(none)",
      clip: this.machine?.currentClipName ?? null,
      clipTime: this.machine?.clipTime ?? 0,
      clipDuration: this.machine?.clipDuration ?? 0,
      sleepPhase: this.sleepPhase,
      emotion: this.ctx?.emotion ?? "neutral",
      intensity: this.ctx?.intensity ?? 0,
      mood: this.mood,
      speaking: this.speaking,
      clipCount: this.library.listNames().length,
      attention: this.director.currentState,
      gaze: { pitch: applied.pitch, yaw: applied.yaw },
      tempo: this.machine?.affectTempo ?? 1,
    };
  }

  getRetargetReports() {
    return this.library.reports;
  }
}
