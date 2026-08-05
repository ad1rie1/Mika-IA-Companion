import * as THREE from "three";
import { VRM } from "@pixiv/three-vrm";
import type {
  AvatarStateSnapshot,
  EmotionBlend,
  EmotionName,
  ProsodicCue,
  SleepPhase,
  VoicePersona,
} from "../../types";
import { ClipLibrary, applyRestPose } from "./ClipLibrary";
import { AnimationStateMachine } from "./AnimationStateMachine";
import { BlinkController } from "./BlinkController";
import { FaceIdleController } from "./FaceIdleController";
import { HandAnimator } from "./HandAnimator";
import { GazeController } from "./GazeController";
import { OverlayContext, type ProceduralOverlay } from "./overlays/Overlay";
import { BreathingOverlay } from "./overlays/BreathingOverlay";
import { SleepOverlay } from "./overlays/SleepOverlay";
import { HeadEmotionOverlay } from "./overlays/HeadEmotionOverlay";
import { CUE_GESTURE, decideGesture } from "./gestures";

const DEFAULT_MANIFEST_URL = "/animations/manifest.json";

/**
 * Facade over the whole body-animation stack — the ONLY object main.ts
 * wires. Owns, in per-frame order:
 *
 *   1. humanoid.resetNormalizedPose()   clean identity base
 *   2. state machine                    clip scheduling / transitions
 *   3. THREE.AnimationMixer             base layer (bones + hips pos)
 *   4. overlays (additive quaternions)  breathing → sleep tilt → head
 *   5. HandAnimator                     fingers (absolute; clips are
 *                                       stripped of finger tracks)
 *   6. GazeController                   eyes (absolute; clips have none)
 *   7. BlinkController                  blink expression + REM flicker
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
  private root: THREE.Object3D | null = null;

  private sleepPhase: SleepPhase = "awake";
  private speaking = false;
  private lastOneshotAt: number | null = null;
  private lastPersona: VoicePersona | undefined;
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
      onProgress?: (done: number, total: number, name: string) => void;
    } = {}
  ): Promise<void> {
    this.root = opts.root ?? null;
    this.hands.setVRM(vrm);
    this.gaze.setVRM(vrm);

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
    this.overlays = [
      new BreathingOverlay(),
      new SleepOverlay(),
      new HeadEmotionOverlay(),
    ];

    // Re-apply signals that may have arrived before init.
    this.machine.setSpeaking(this.speaking);
    this.machine.setSleepPhase(this.sleepPhase);
    this.machine.start();
    this.vrm = vrm; // update() starts animating from this point on

    await this.library.loadManifest(opts.manifestUrl ?? DEFAULT_MANIFEST_URL, {
      onProgress: opts.onProgress,
      // As downloaded clips stream in, swap the rest pose for real life.
      onClipLoaded: () => this.machine?.refreshBaseIfResting(),
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

    for (const overlay of this.overlays) {
      overlay.update(dt, ctx);
    }
    this.hands.update(dt);
    this.gaze.update(dt);
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
    if (!opts.ambient) this.lastPersona = persona;
    if (this.ctx) {
      this.ctx.emotion = emotion;
      this.ctx.intensity = clamped;
    }
    this.gaze.setEmotion(emotion, clamped);
    this.hands.setEmotion(emotion, clamped);

    if (!this.machine) return;
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
      const loaded = this.library.get(decision.clip);
      if (loaded && this.machine.requestGesture(loaded)) {
        this.lastOneshotAt = performance.now();
      }
    }
  }

  setSleepPhase(phase: SleepPhase): void {
    this.sleepPhase = phase;
    if (this.ctx) this.ctx.sleepPhase = phase;
    this.hands.setSleepPhase(phase);
    this.gaze.setSleepPhase(phase);
    this.machine?.setSleepPhase(phase);
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
    const clipName = CUE_GESTURE[cue];
    if (!clipName) return;
    const loaded = this.library.get(clipName);
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
    speaking: boolean;
    clipCount: number;
  } {
    return {
      state: this.machine?.state ?? "(none)",
      clip: this.machine?.currentClipName ?? null,
      clipTime: this.machine?.clipTime ?? 0,
      clipDuration: this.machine?.clipDuration ?? 0,
      sleepPhase: this.sleepPhase,
      emotion: this.ctx?.emotion ?? "neutral",
      intensity: this.ctx?.intensity ?? 0,
      speaking: this.speaking,
      clipCount: this.library.listNames().length,
    };
  }

  getRetargetReports() {
    return this.library.reports;
  }
}
